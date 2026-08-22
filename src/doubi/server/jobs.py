"""In-memory job manager for the REST server.

Jobs have the following lifecycle::

    pending → running → completed
                       ↘ failed

Old jobs are evicted when the job count exceeds ``max_jobs`` or
the per-job TTL is exceeded. In-flight jobs are never evicted.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger("doubi.server.jobs")


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Job:
    job_id: str
    url: str
    status: JobStatus = JobStatus.PENDING
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    error: Optional[str] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    submitted_at: Optional[float] = None
    item_title: Optional[str] = None
    item_author: Optional[str] = None
    item_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "url": self.url,
            "status": self.status.value,
            "total": self.total,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "submitted_at": self.submitted_at,
            "item_title": self.item_title,
            "item_author": self.item_author,
            "item_id": self.item_id,
        }


#: Signature of the per-job executor: takes a URL, returns a dict with
#: any of {total, succeeded, failed, item_title, item_author, item_id}.
ExecutorFn = Callable[[str], Awaitable[dict[str, Any]]]


class JobManager:
    """Submit, track, evict download jobs.

    Concurrency: at most ``max_concurrency`` jobs run at once;
    further submissions wait in a FIFO queue.
    """

    DEFAULT_MAX_JOBS = 500
    DEFAULT_JOB_TTL_SECONDS = 24 * 3600.0

    def __init__(
        self,
        executor: ExecutorFn,
        *,
        max_concurrency: int = 2,
        max_jobs: int = DEFAULT_MAX_JOBS,
        job_ttl_seconds: float = DEFAULT_JOB_TTL_SECONDS,
    ):
        self._executor = executor
        self._max_concurrency = max(1, max_concurrency)
        self._max_jobs = max(1, max_jobs)
        self._job_ttl_seconds = job_ttl_seconds

        self._jobs: dict[str, Job] = {}
        self._lock = asyncio.Lock()
        self._sem = asyncio.Semaphore(self._max_concurrency)
        self._evicted_count = 0

    # ---- submission -------------------------------------------------

    async def submit(self, url: str) -> Job:
        async with self._lock:
            self._evict_locked()
            job = Job(job_id=uuid.uuid4().hex, url=url,
                      submitted_at=time.time())
            self._jobs[job.job_id] = job

        # Schedule the actual download outside the lock
        asyncio.create_task(self._run(job))
        return job

    async def _run(self, job: Job) -> None:
        async with self._sem:
            async with self._lock:
                job.status = JobStatus.RUNNING
                job.started_at = time.time()

            try:
                result = await self._executor(job.url)
            except Exception as exc:
                logger.exception("job %s failed", job.job_id)
                async with self._lock:
                    job.status = JobStatus.FAILED
                    job.error = str(exc)
                    job.finished_at = time.time()
                    self._evict_locked()
                return

            async with self._lock:
                job.status = JobStatus.COMPLETED
                job.total = int(result.get("total", 0))
                job.succeeded = int(result.get("succeeded", 0))
                job.failed = int(result.get("failed", 0))
                job.item_title = result.get("item_title")
                job.item_author = result.get("item_author")
                job.item_id = result.get("item_id")
                job.finished_at = time.time()
                # A job just finished → evict any surplus completed
                # jobs so the store stays within max_jobs over time
                # (submit() alone can't guarantee this when many
                # jobs complete after the last submit).
                self._evict_locked(exclude_job_id=job.job_id)

    # ---- queries -----------------------------------------------------

    async def get(self, job_id: str) -> Optional[Job]:
        async with self._lock:
            return self._jobs.get(job_id)

    async def list_jobs(self) -> list[Job]:
        async with self._lock:
            # Most recent first
            return sorted(self._jobs.values(), key=lambda j: j.started_at or 0, reverse=True)

    # ---- maintenance -------------------------------------------------

    async def shutdown(self) -> None:
        """Mark all running jobs as failed; in-flight downloads will
        continue but their results will be discarded.
        """
        async with self._lock:
            for j in self._jobs.values():
                if j.status is JobStatus.RUNNING:
                    j.status = JobStatus.FAILED
                    j.error = "server shutdown"
                    j.finished_at = time.time()

    def _evict_locked(self, exclude_job_id: str | None = None) -> None:
        """Drop finished (or pending) jobs that are too old or beyond the cap.

        MUST be called with ``self._lock`` held. ``exclude_job_id``
        is protected from eviction (used when the caller just finished
        a job and doesn't want its own record dropped).
        """
        now = time.time()
        # 1. TTL-based eviction: only applies to jobs that have finished
        to_drop = [
            jid for jid, j in self._jobs.items()
            if jid != exclude_job_id
            and j.status in (JobStatus.COMPLETED, JobStatus.FAILED)
            and j.finished_at is not None
            and (now - j.finished_at) > self._job_ttl_seconds
        ]
        for jid in to_drop:
            del self._jobs[jid]
            self._evicted_count += 1
        # 2. Cap-based eviction: prefer evicting PENDING (queued, not
        #    running) jobs first; only then COMPLETED/FAILED ones.
        #    We never evict RUNNING jobs because the executor still
        #    holds references to them and would write a result that
        #    no one can see.
        if len(self._jobs) > self._max_jobs:
            pending = sorted(
                (j for j in self._jobs.values()
                 if j.status is JobStatus.PENDING and j.job_id != exclude_job_id),
                key=lambda j: j.submitted_at or 0,   # FIFO: oldest first
            )
            finished = sorted(
                (j for j in self._jobs.values()
                 if j.status in (JobStatus.COMPLETED, JobStatus.FAILED)
                 and j.job_id != exclude_job_id),
                key=lambda j: j.finished_at or 0,
            )
            victims = list(pending) + list(finished)
            excess = len(self._jobs) - self._max_jobs
            for j in victims[:excess]:
                del self._jobs[j.job_id]
                self._evicted_count += 1

    @property
    def evicted_count(self) -> int:
        return self._evicted_count
