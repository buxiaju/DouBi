"""TaskManager — shared state for the GUI's parse / download pages.

The :class:`TaskManager` is the single source of truth for "what's
currently being downloaded" and "what's finished". Both the
:class:`ParsePage` (which adds tasks when the user clicks "下载选中")
and the :class:`DownloadPage` (which displays them in two tabs)
share the same instance, owned by :class:`MainWindow`.

The manager is intentionally small: it does NOT do any I/O itself.
Each task is wrapped in a thin :class:`DownloadWorker` (the existing
M5 worker) that calls into :class:`DownloadPipeline.download_item`,
emits progress / finished / failed events, and the manager re-emits
those as Qt signals for the UI to consume.

Lifecycle
---------
1. ``ParsePage`` parses URLs, builds a list of :class:`MediaItem`.
2. User picks rows, clicks "下载选中" → :meth:`TaskManager.add`.
3. Manager creates a :class:`TaskInfo` (status='running'),
   spawns a :class:`DownloadWorker` in the background, emits
   ``task_added`` so :class:`DownloadPage` can render a card.
4. Worker emits progress / finished / failed events; the manager
   updates the :class:`TaskInfo` and re-emits the corresponding
   signals to the UI.
5. When the task finishes (ok or fail), the manager moves the
   :class:`TaskInfo` to the completed list, emits ``task_completed``.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from PySide6.QtCore import QObject, Signal, Slot

from ..core.models import DownloadOptions, MediaItem, Platform
from ..core.pipeline import DownloadPipeline, ProgressEvent

logger = logging.getLogger("doubi.ui.task_manager")


@dataclass
class TaskInfo:
    """A single download task's state, owned by the manager."""

    task_id: str
    item: MediaItem
    options: DownloadOptions
    status: str = "running"             # running | completed | failed | cancelled
    fraction: float = 0.0
    title: str = ""
    message: str = ""
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    finished_at: Optional[datetime] = None
    save_path: Optional[str] = None

    def is_terminal(self) -> bool:
        return self.status in ("completed", "failed", "cancelled")


class TaskManager(QObject):
    """Owns the GUI's active and completed download tasks."""

    # --- signals consumed by DownloadPage -----------------------------
    task_added = Signal(str)                       # task_id
    task_progress = Signal(str, float, str)        # task_id, fraction, message
    task_finished = Signal(str, str)               # task_id, title
    task_failed = Signal(str, str)                 # task_id, message
    task_removed = Signal(str)                     # task_id

    def __init__(self, pipeline: DownloadPipeline, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._pipeline = pipeline
        self._active: dict[str, TaskInfo] = {}
        self._completed: dict[str, TaskInfo] = {}
        self._counter = 0
        self._pending_tasks: set[asyncio.Task] = set()

    # ---- public API ---------------------------------------------------

    def add(self, item: MediaItem, options: DownloadOptions) -> str:
        """Spawn a download task for *item* and return its task_id."""
        # De-dup: if the same (platform, item_id) is already running,
        # return its task_id instead of starting a duplicate.
        for existing in self._active.values():
            if (existing.item.platform is item.platform
                    and existing.item.item_id == item.item_id):
                logger.info("TaskManager: dedup, reusing %s/%s",
                            item.platform.value, item.item_id)
                return existing.task_id

        self._counter += 1
        task_id = f"T{self._counter:04d}"
        info = TaskInfo(
            task_id=task_id,
            item=item,
            options=options,
            title=item.title or item.item_id,
        )
        self._active[task_id] = info
        self.task_added.emit(task_id)

        # Spawn the actual download in the asyncio loop.
        loop = asyncio.get_event_loop()
        t = loop.create_task(self._run_download(task_id, item, options))
        self._pending_tasks.add(t)
        t.add_done_callback(self._pending_tasks.discard)
        return task_id

    def active_tasks(self) -> list[TaskInfo]:
        """Snapshot of currently running tasks (oldest first)."""
        return sorted(
            self._active.values(),
            key=lambda ti: ti.created_at,
        )

    def completed_tasks(self) -> list[TaskInfo]:
        """Snapshot of finished tasks, newest first."""
        return sorted(
            self._completed.values(),
            key=lambda ti: ti.finished_at or ti.created_at,
            reverse=True,
        )

    def active_count(self) -> int:
        return len(self._active)

    def completed_count(self) -> int:
        return len(self._completed)

    def get(self, task_id: str) -> Optional[TaskInfo]:
        return self._active.get(task_id) or self._completed.get(task_id)

    def remove(self, task_id: str) -> None:
        """Remove a task (cancels if running)."""
        info = self._active.pop(task_id, None)
        if info is not None:
            info.status = "cancelled"
            self.task_removed.emit(task_id)
            return
        info = self._completed.pop(task_id, None)
        if info is not None:
            self.task_removed.emit(task_id)

    def clear_completed(self) -> None:
        """Drop all completed/failed tasks."""
        for task_id in list(self._completed.keys()):
            self._completed.pop(task_id, None)
            self.task_removed.emit(task_id)

    def failed_count(self) -> int:
        """How many finished tasks are retryable (failed / cancelled)."""
        return sum(1 for info in self._completed.values()
                   if info.status in ("failed", "cancelled"))

    def retry(self, task_id: str) -> bool:
        """Re-run a failed / cancelled task, keeping its original task_id.

        The :class:`TaskInfo` is moved back from ``_completed`` into
        ``_active`` with its runtime state reset, then a fresh download
        coroutine is spawned. ``task_added`` is re-emitted so the UI can
        move the row back into the "下载中" list.

        Returns ``True`` when a retry was actually started.
        """
        info = self._completed.get(task_id)
        if info is None or info.status not in ("failed", "cancelled"):
            return False

        # Avoid producing a duplicate of something already running.
        for existing in self._active.values():
            if (existing.item.platform is info.item.platform
                    and existing.item.item_id == info.item.item_id):
                logger.info("TaskManager: retry skipped, %s/%s already active",
                            info.item.platform.value, info.item.item_id)
                return False

        self._completed.pop(task_id, None)
        info.status = "running"
        info.fraction = 0.0
        info.message = ""
        info.error = None
        info.finished_at = None
        info.created_at = datetime.now()
        self._active[task_id] = info
        self.task_added.emit(task_id)

        loop = asyncio.get_event_loop()
        t = loop.create_task(self._run_download(task_id, info.item, info.options))
        self._pending_tasks.add(t)
        t.add_done_callback(self._pending_tasks.discard)
        logger.info("TaskManager: retrying %s (%s)", task_id, info.title)
        return True

    def retry_all_failed(self) -> int:
        """Retry every failed / cancelled task; returns how many started."""
        started = 0
        for task_id in list(self._completed.keys()):
            if self.retry(task_id):
                started += 1
        return started

    # ---- internals ----------------------------------------------------

    async def _run_download(
        self, task_id: str, item: MediaItem, options: DownloadOptions
    ) -> None:
        """Async body that calls into the pipeline and updates state."""
        info = self._active.get(task_id)
        if info is None:
            return

        def _on_progress(ev: ProgressEvent) -> None:
            info.fraction = ev.fraction
            info.message = ev.message
            self.task_progress.emit(task_id, ev.fraction, ev.message)

        try:
            ok = await self._pipeline.download_item(
                item, options, on_progress=_on_progress,
            )
        except asyncio.CancelledError:
            info.status = "cancelled"
            self._active.pop(task_id, None)
            self.task_failed.emit(task_id, "已取消")
            return
        except Exception as exc:   # noqa: BLE001
            logger.exception("TaskManager[%s] download raised", task_id)
            info.status = "failed"
            info.error = str(exc)
            info.finished_at = datetime.now()
            self._move_to_completed(task_id)
            self.task_failed.emit(task_id, str(exc))
            return

        if ok:
            info.status = "completed"
            info.fraction = 1.0
            info.title = item.title or info.title
            info.finished_at = datetime.now()
            self._move_to_completed(task_id)
            self.task_finished.emit(task_id, info.title)
        else:
            info.status = "failed"
            info.error = info.message or "下载失败"
            info.finished_at = datetime.now()
            self._move_to_completed(task_id)
            self.task_failed.emit(task_id, info.error)

    def _move_to_completed(self, task_id: str) -> None:
        info = self._active.pop(task_id, None)
        if info is not None:
            self._completed[task_id] = info
