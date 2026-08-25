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
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
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
        # Pending-row writes only. Kept apart from _pending_tasks so
        # shutdown can await the bookkeeping without awaiting downloads.
        self._db_tasks: set[asyncio.Task] = set()
        # task_id -> the asyncio.Task of its *current* attempt. Without
        # this map the manager cannot address one specific running
        # download, which is what pause / resume / remove all need.
        self._tasks: dict[str, asyncio.Task] = {}
        # task_id -> the _StopFlag of its *current* attempt.
        self._flags: dict[str, _StopFlag] = {}
        # Serialises the pending-row writes so they commit in the order
        # the transitions happened; see :meth:`_run_db`.
        self._db_lock = asyncio.Lock()

    # ---- cross-process resume persistence -----------------------------
    #
    # Every persisting call below is fire-and-forget: a database hiccup
    # must never break a download that is otherwise fine. Resume is a
    # convenience layered on top, not a precondition.
    #
    # Note what is deliberately *absent*: nothing persists from the
    # progress callback. ``Engine.download`` runs inside
    # ``asyncio.to_thread``, so yt-dlp's progress hook -- and therefore
    # ``_on_progress`` -- executes on a worker thread, where touching
    # this loop would be a cross-thread violation. Rows are written on
    # state transitions only (add / pause / resume / retry), all of
    # which run on the qasync loop, i.e. the Qt main thread.

    def _persist_row(self, info: TaskInfo, *, with_snapshots: bool) -> None:
        """Schedule an upsert of *info* into the pending_task table.

        *with_snapshots* is ``False`` for plain status flips: the upsert
        ``COALESCE``s snapshots, so re-sending the same blobs on every
        pause would be pure write amplification.
        """
        db_path = info.options.database
        if db_path is None:
            return
        from ..core.storage import item_to_json, options_to_json

        row_kwargs: dict = {
            "task_id": info.task_id,
            "platform": info.item.platform.value,
            "source_url": info.item.source_url,
            "status": info.status,
            "item_id": info.item.item_id,
            "title": info.title,
            "fraction": info.fraction,
            "message": info.message,
        }
        if with_snapshots:
            row_kwargs["options_snapshot"] = options_to_json(info.options)
            row_kwargs["item_snapshot"] = item_to_json(info.item)
        self._run_db(self._upsert_pending(db_path, row_kwargs))

    def _forget_row(self, info: TaskInfo) -> None:
        """Schedule deletion of *info*'s pending row.

        Terminal states delete rather than update: a task the user will
        never resume has no business reappearing in the restore prompt,
        and dropping the row keeps the table the size of the work that
        is actually outstanding.
        """
        db_path = info.options.database
        if db_path is None:
            return
        self._run_db(self._delete_pending(db_path, info.task_id))

    @staticmethod
    async def _upsert_pending(db_path, row_kwargs: dict) -> None:
        # Short open/close cycle per write, matching the pipeline's own
        # pattern: aiosqlite backs every live connection with a thread,
        # and a task can stay pending for hours.
        from ..core.storage import Database, PendingTaskRow

        async with Database(db_path) as db:
            await db.upsert_pending_task(PendingTaskRow(**row_kwargs))

    @staticmethod
    async def _delete_pending(db_path, task_id: str) -> None:
        from ..core.storage import Database

        async with Database(db_path) as db:
            await db.delete_pending_task(task_id)

    def _run_db(self, coro) -> None:
        """Fire off a persistence coroutine, swallowing its failures.

        Held in ``_pending_tasks`` for the same reason downloads are:
        asyncio only keeps a weak reference to a task, so an unheld one
        can be garbage-collected mid-flight.

        The lock is not about corruption -- SQLite handles that -- it is
        about *order*. Each write opens its own connection, so two
        in-flight writes can commit in either order, and the row records
        a state rather than an increment: ``add``'s "running" landing
        after ``pause``'s "paused" would leave a task the user paused
        looking like it was still downloading, and the next launch would
        offer to resume something it should have offered to continue.
        Acquiring FIFO in submission order makes last-write-wins mean
        last-*transition*-wins.
        """
        async def _guarded() -> None:
            try:
                async with self._db_lock:
                    await coro
            except asyncio.CancelledError:
                # Cancelled before the lock was ours, so ``coro`` never
                # started and would otherwise be reported as "never
                # awaited" at loop teardown. Closing it says explicitly
                # that this write was dropped -- which is what a
                # shutdown mid-queue really means. Harmless no-op if the
                # cancellation arrived while the coroutine was running.
                coro.close()
                raise
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("TaskManager: resume bookkeeping failed: %s", exc)

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            # No loop (e.g. a unit test constructing the manager bare).
            coro.close()
            return
        t = loop.create_task(_guarded())
        # Tracked separately from downloads: shutdown wants to wait for
        # these to land, and must not wait for a download to finish.
        self._db_tasks.add(t)
        t.add_done_callback(self._db_tasks.discard)

    async def flush_pending_writes(self, timeout: float = 3.0) -> None:
        """Wait for the queued pending-row writes to reach the disk.

        The writes are deliberately fire-and-forget, which is right while
        the app is running -- a state change must never block on I/O --
        but wrong at shutdown: whatever is still queued when the event
        loop closes is silently dropped, and it is precisely the *last*
        transitions (the pauses the user triggered on the way out) that
        the next launch needs in order to offer a resume.

        Bounded, because a hung write must not stop the window from
        closing; a lost row degrades resume, while a frozen quit is a
        bug the user can see.
        """
        while self._db_tasks:
            batch = tuple(self._db_tasks)
            _done, pending = await asyncio.wait(batch, timeout=timeout)
            if pending:
                logger.warning(
                    "TaskManager: %d pending-row write(s) did not finish "
                    "within %.1fs; resume state may be stale",
                    len(pending),
                    timeout,
                )
                return

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
        self._persist_row(info, with_snapshots=True)
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
            self._forget_row(info)
            self.task_removed.emit(task_id)
            return
        info = self._completed.pop(task_id, None)
        if info is not None:
            self._forget_row(info)
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
        self._persist_row(info, with_snapshots=False)
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
        self._persist_row(info, with_snapshots=False)
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
        """Re-run a failed / cancelled task, or a completed task whose
        local output file was deleted.

        The :class:`TaskInfo` is moved back from ``_completed`` into
        ``_active`` with its runtime state reset, then a fresh download
        coroutine is spawned. ``task_added`` is re-emitted so the UI can
        move the row back into the "下载中" list.

        Returns ``True`` when a retry was actually started.
        """
        info = self._completed.get(task_id)
        if info is None:
            return False
        if info.status not in ("failed", "cancelled", "completed"):
            return False

        # Completed tasks are only retryable if the local file is gone.
        if info.status == "completed" and not self._save_path_missing(info):
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
        info.save_path = None
        info.created_at = datetime.now()
        self._active[task_id] = info
        self.task_added.emit(task_id)
        # A retry is outstanding work again, so the row comes back --
        # with snapshots, since the terminal transition deleted it.
        self._persist_row(info, with_snapshots=True)

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

    @staticmethod
    def _save_path_missing(info: TaskInfo) -> bool:
        """Return True when the task has a save_path but it no longer
        exists locally, or when all plausible output files under the
        item's output directory are missing.

        Used by the GUI to determine if a "已完成" task should become
        "可重新下载" because the user deleted the files.
        """
        if info.save_path:
            if not Path(info.save_path).exists():
                return True
            # Even if save_path points to a dir or meta file, check if
            # the directory actually contains any media-sized file.
            # Most engines save_path is a media file itself, so the
            # check above covers 99% of cases. We return False here
            # (i.e., file exists → nothing to do).
            return False
        # No save_path recorded at all: try to rebuild via default
        # templates from the MediaItem and see if anything is there.
        try:
            from ..core.storage.file_layout import resolve_item_dir
            out_dir = resolve_item_dir(info.item, info.options)
            if out_dir.exists():
                # Look for files matching item's title/ basename
                media_exts = (".mp4", ".mkv", ".flv", ".webm", ".mov", ".avi",
                              ".m4v", ".ts", ".m4a")
                base = (info.item.output_template
                        or info.item.title or info.item.item_id or "").strip()
                any_file = False
                for p in out_dir.iterdir():
                    if not p.is_file():
                        continue
                    if p.suffix.lower() in media_exts and p.stat().st_size > 1024:
                        any_file = True
                        break
                return not any_file
        except Exception:
            return False
        return True

    # ---- cross-process restore ----------------------------------------

    @staticmethod
    async def list_restorable(db_path) -> list:
        """Read the rows left behind by a previous process.

        Kept here rather than in the window so the caller needs no
        storage import: it only has to decide whether to ask the user.
        Returns an empty list when there is no database or it cannot be
        read -- a startup path must not be able to abort the launch.
        """
        if db_path is None:
            return []
        from ..core.storage import Database

        try:
            async with Database(db_path) as db:
                return await db.list_unfinished()
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("TaskManager: cannot list unfinished tasks: %s", exc)
            return []

    def restore(self, rows, base_options: DownloadOptions) -> list[str]:
        """Reinstate *rows* as **paused** tasks; returns the ids revived.

        Paused, never running: a restart is exactly the moment the user's
        intent is least certain -- the app may have been killed precisely
        because the download was saturating the line -- so the transfer
        waits for an explicit resume. The partial files stay on disk
        either way, so nothing is lost by waiting.

        *base_options* supplies today's defaults for every field the
        snapshot lacks, which is what lets a row written by an older
        build survive a schema that has since grown fields.
        """
        from ..core.storage import item_from_json, options_from_json

        restored: list[str] = []
        for row in rows:
            options = options_from_json(
                getattr(row, "options_snapshot", None), base_options
            )
            item = item_from_json(getattr(row, "item_snapshot", None))
            if item is None:
                # No snapshot (a failed write, or an older schema). The
                # source_url alone is enough to download; what is lost is
                # the metadata the directory template renders from, so
                # this task may land in a different folder and re-fetch
                # from zero. Still far better than dropping the task.
                item = MediaItem(
                    platform=Platform.from_str(row.platform),
                    item_id=row.item_id or "",
                    title=row.title or "",
                    source_url=row.source_url,
                )
            if not item.source_url:
                # Nothing to hand the engine; the row is unusable.
                logger.debug("TaskManager: skipping %s, no source_url", row.task_id)
                continue

            task_id = row.task_id
            if task_id in self._active or task_id in self._completed:
                # Someone already added work under this id in this
                # process. Re-keying keeps both, at the cost of the old
                # row lingering until its new twin reaches a terminal
                # state -- an orphan row is cheaper than a lost task.
                self._counter += 1
                task_id = f"T{self._counter:04d}"

            info = TaskInfo(
                task_id=task_id,
                item=item,
                options=options,
                status="paused",
                fraction=row.fraction or 0.0,
                title=row.title or item.title or item.item_id,
                message="已暂停（上次未完成）",
            )
            self._active[task_id] = info
            self._reseed_counter(task_id)
            self.task_added.emit(task_id)
            # The row may still say "running" if the process was killed
            # mid-transfer; rewrite it so the table matches what the user
            # is now looking at.
            self._persist_row(info, with_snapshots=True)
            self.task_progress.emit(task_id, info.fraction, info.message)
            restored.append(task_id)

        if restored:
            logger.info("TaskManager: restored %d unfinished task(s)", len(restored))
        return restored

    def discard_restorable(self, rows, db_path) -> None:
        """Drop *rows* from the database without reviving them.

        The prompt's "no" answer has to be durable. Leaving the rows in
        place would re-ask the same question at every launch, and the
        third time the user sees it they will stop reading it -- which
        also disarms the prompt for the launch where it actually matters.

        *db_path* is taken from the caller rather than the rows: a row
        records the task, not where it was stored, and the caller has the
        path already because that is what it passed to
        :meth:`list_restorable`.

        The partial files stay on disk untouched: this forgets the
        bookkeeping, not the bytes.
        """
        if db_path is None:
            return
        for row in rows:
            self._run_db(self._delete_pending(db_path, row.task_id))

    def _reseed_counter(self, task_id: str) -> None:
        """Push ``_counter`` past *task_id* so :meth:`add` cannot collide.

        Restored ids are the ones a previous process handed out, so
        without this the next :meth:`add` would mint ``T0001`` again and
        overwrite a restored task's own pending row.
        """
        if not (task_id.startswith("T") and task_id[1:].isdigit()):
            return
        self._counter = max(self._counter, int(task_id[1:]))

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
            # A retry notice carries ``fraction=0.0`` because at that moment
            # nothing is in flight -- it is a *message*, not a measurement.
            # Taking it literally would rewind a bar sitting at 80% back to
            # zero on every transient failure, which reads as "the download
            # restarted from scratch" even when ``resume=True`` means it did
            # not. Keep the last real fraction and only swap the text.
            #
            # The signal argument is kept consistent with ``info`` on purpose.
            # Today ``pages/download._on_task_progress`` ignores it and re-reads
            # ``manager.get(task_id).fraction``, so only the line above actually
            # moves the bar -- but emitting a 0.0 that contradicts ``info``
            # would leave a trap for the next consumer that does trust the
            # argument. Every other emit site in this file already passes
            # ``info.fraction``.
            if not (ev.extra or {}).get("retry"):
                info.fraction = ev.fraction
            info.message = ev.message
            self.task_progress.emit(task_id, info.fraction, ev.message)

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
            # Single funnel for the completed / failed terminal states, so
            # the pending row is dropped in exactly one place.
            self._forget_row(info)

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
            # Re-persist so the row carries the fraction the engine
            # actually reached: pause() wrote the row the moment the
            # button was pressed, but the transfer kept going until the
            # next progress tick noticed the flag.
            self._persist_row(info, with_snapshots=False)
            self.task_progress.emit(task_id, info.fraction, "已暂停")
            return

        info.status = "cancelled"
        self._active.pop(task_id, None)
        self._forget_row(info)
        self.task_failed.emit(task_id, "已取消")
