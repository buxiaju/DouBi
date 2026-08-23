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
from dataclasses import dataclass, field, replace
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
    # running | paused | completed | failed | cancelled
    #
    # ``paused`` is deliberately NOT terminal: a paused task keeps its
    # slot in the active list (and its partial files on disk) so
    # :meth:`TaskManager.resume` can pick it up again.
    status: str = "running"
    fraction: float = 0.0
    title: str = ""
    message: str = ""
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    finished_at: Optional[datetime] = None
    save_path: Optional[str] = None

    def is_terminal(self) -> bool:
        return self.status in ("completed", "failed", "cancelled")


class _StopFlag:
    """Cooperative stop signal for one *attempt* of one task.

    A fresh instance is created per attempt (initial download, resume,
    retry) and handed to the engine as
    :attr:`DownloadOptions.cancel_check`. That indirection matters:
    ``Engine.download`` runs inside ``asyncio.to_thread``, so
    ``Task.cancel()`` cannot interrupt a transfer that is already in
    flight — only a flag the engine polls from its progress hook can.

    Binding the flag to the attempt rather than to the ``task_id`` is
    what makes resume safe. A paused worker may still be sitting inside
    the engine thread when :meth:`TaskManager.resume` spawns the next
    attempt; if both attempts shared one flag, clearing it would revive
    the old thread and leave two writers on the same ``.part`` file.
    """

    __slots__ = ("stopped", "reason")

    def __init__(self) -> None:
        self.stopped = False
        # "paused" | "removed" — tells _run_download whether the task
        # should keep its slot in _active or disappear entirely.
        self.reason = ""

    def stop(self, reason: str) -> None:
        self.reason = reason
        self.stopped = True

    def __call__(self) -> bool:
        """Probe used by the engine's progress hook."""
        return self.stopped


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
        # task_id -> the asyncio.Task of its *current* attempt. Without
        # this map the manager cannot address one specific running
        # download, which is what pause / resume / remove all need.
        self._tasks: dict[str, asyncio.Task] = {}
        # task_id -> the _StopFlag of its *current* attempt.
        self._flags: dict[str, _StopFlag] = {}

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
        self._spawn(task_id, item, options)
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
            # Actually stop the work instead of just dropping the record:
            # the flag aborts a transfer already inside the engine thread,
            # while cancel() wakes an attempt still awaiting in the loop.
            self._stop_attempt(task_id, "removed")
            self.task_removed.emit(task_id)
            return
        info = self._completed.pop(task_id, None)
        if info is not None:
            self.task_removed.emit(task_id)

    def pause(self, task_id: str) -> bool:
        """Pause a running task, keeping it in the active list.

        Returns ``True`` when a running task was actually asked to stop.
        """
        info = self._active.get(task_id)
        if info is None or info.status != "running":
            return False
        self._stop_attempt(task_id, "paused")
        # Flip the state synchronously. The worker only notices the flag
        # on the engine's next progress tick, which can be seconds away
        # on a slow chunk; leaving the row as "下载中" until then would
        # look like the button did nothing.
        info.status = "paused"
        info.message = "已暂停"
        self.task_progress.emit(task_id, info.fraction, "已暂停")
        logger.info("TaskManager: pausing %s (%s)", task_id, info.title)
        return True

    def resume(self, task_id: str) -> bool:
        """Resume a paused task, continuing from its partial file.

        Returns ``True`` when a new attempt was started.
        """
        info = self._active.get(task_id)
        if info is None or info.status != "paused":
            return False
        info.status = "running"
        info.message = ""
        self._spawn(task_id, info.item, info.options)
        self.task_progress.emit(task_id, info.fraction, "")
        logger.info("TaskManager: resuming %s (%s)", task_id, info.title)
        return True

    def pause_all(self) -> int:
        """Pause every running task; returns how many were paused."""
        return sum(1 for info in self.active_tasks() if self.pause(info.task_id))

    def resume_all(self) -> int:
        """Resume every paused task; returns how many were restarted."""
        return sum(1 for info in self.active_tasks() if self.resume(info.task_id))

    def running_count(self) -> int:
        return sum(1 for info in self._active.values() if info.status == "running")

    def paused_count(self) -> int:
        return sum(1 for info in self._active.values() if info.status == "paused")

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

        self._spawn(task_id, info.item, info.options)
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

    def _spawn(
        self, task_id: str, item: MediaItem, options: DownloadOptions
    ) -> None:
        """Start one attempt for *task_id* and register it for control.

        The options bag is copied with :func:`dataclasses.replace` so the
        attempt gets its *own* ``cancel_check``. Writing the probe into
        the caller's instance would be a cross-task leak: callers legally
        share one :class:`DownloadOptions` across several :meth:`add`
        calls, so pausing one task would pause every task sharing it.
        """
        flag = _StopFlag()
        self._flags[task_id] = flag
        attempt_options = replace(options, cancel_check=flag)

        loop = asyncio.get_event_loop()
        t = loop.create_task(
            self._run_download(task_id, item, attempt_options, flag)
        )
        self._tasks[task_id] = t
        self._pending_tasks.add(t)
        t.add_done_callback(self._pending_tasks.discard)

    def _forget(self, task_id: str, task: asyncio.Task) -> None:
        """Drop control handles, but only if they are still this attempt's.

        A late-finishing attempt must not clobber the registration of the
        newer one that :meth:`resume` or :meth:`retry` already installed.
        """
        if self._tasks.get(task_id) is task:
            self._tasks.pop(task_id, None)
            self._flags.pop(task_id, None)

    def _stop_attempt(self, task_id: str, reason: str) -> None:
        """Stop the current attempt of *task_id* using both mechanisms.

        Neither half is sufficient alone. The flag is the only thing that
        can reach a transfer already running inside ``asyncio.to_thread``
        (that is what P3-1's cancel probe exists for), but it is polled
        from the engine's progress hook, so an attempt that has not
        reached the engine yet — still resolving, or queued behind the
        pipeline's semaphore — would never see it. ``Task.cancel()``
        covers exactly that window. Setting the flag *first* guarantees
        the reason is readable by whichever path unwinds.
        """
        flag = self._flags.get(task_id)
        if flag is not None:
            flag.stop(reason)
        task = self._tasks.get(task_id)
        if task is not None and not task.done():
            task.cancel()

    async def _run_download(
        self, task_id: str, item: MediaItem, options: DownloadOptions,
        flag: _StopFlag,
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
            self._finish_stopped(task_id, info, flag, default_reason="removed")
            return
        except Exception as exc:   # noqa: BLE001
            self._forget(task_id, asyncio.current_task())
            logger.exception("TaskManager[%s] download raised", task_id)
            info.status = "failed"
            info.error = str(exc)
            info.finished_at = datetime.now()
            self._move_to_completed(task_id)
            self.task_failed.emit(task_id, str(exc))
            return

        # A stop we requested surfaces as ``ok is False`` rather than an
        # exception: the engine swallows its own DownloadCancelled and
        # reports failure. Checking the flag is the only way to tell a
        # deliberate pause apart from a genuine download error.
        #
        # ``not ok`` is part of the condition on purpose. A pause can land
        # after the transfer already succeeded, and a finished file must
        # win over a stop request that arrived too late — otherwise the
        # task would sit "paused" forever with nothing left to download.
        if flag.stopped and not ok:
            self._finish_stopped(task_id, info, flag, default_reason="paused")
            return

        self._forget(task_id, asyncio.current_task())
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

    def _finish_stopped(
        self, task_id: str, info: TaskInfo, flag: _StopFlag,
        *, default_reason: str,
    ) -> None:
        """Settle an attempt that we stopped on purpose.

        ``paused`` keeps the task in ``_active`` (its ``.part`` files stay
        on disk thanks to the resume-aware cleanup in the yt-dlp engine)
        so :meth:`resume` can continue it. ``removed`` drops the task
        outright — deliberately *not* into ``_completed``, because a
        removed row must vanish from the UI, and ``get()`` must return
        ``None`` for it.
        """
        stale = self._tasks.get(task_id) is not asyncio.current_task()
        self._forget(task_id, asyncio.current_task())

        reason = flag.reason or default_reason
        if reason == "paused":
            # A newer attempt already owns this task_id; do not let this
            # dying one stamp "paused" over the fresh "running".
            if stale:
                return
            info.status = "paused"
            info.message = "已暂停"
            self.task_progress.emit(task_id, info.fraction, "已暂停")
            return

        info.status = "cancelled"
        self._active.pop(task_id, None)
        self.task_failed.emit(task_id, "已取消")
