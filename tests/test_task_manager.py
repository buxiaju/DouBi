"""Tests for the M5.4 TaskManager (GUI task state).

The manager is a thin Qt-aware wrapper around the pipeline. We test
it headlessly with ``QT_QPA_PLATFORM=offscreen``. Tests are async so
``TaskManager.add`` (which uses ``asyncio.get_event_loop()``) and the
task completion all happen on the same event loop (pytest-asyncio
mode=AUTO is configured in pyproject.toml).
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _require_gui() -> None:
    try:
        import PySide6  # noqa: F401
    except ImportError as exc:   # pragma: no cover
        pytest.skip(f"PySide6 not installed: {exc}")


@pytest.fixture(scope="module")
def qapp():
    _require_gui()
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


def _make_item(item_id="BV1", title="t"):
    from doubi.core.models import Author, MediaItem, MediaType, Platform
    return MediaItem(
        platform=Platform.BILIBILI, item_id=item_id, title=title,
        author=Author(name="u"), media_type=MediaType.VIDEO,
        source_url=f"https://www.bilibili.com/video/{item_id}",
    )


def _make_options(tmp_path):
    from doubi.core.models import DownloadOptions
    return DownloadOptions(output_root=tmp_path)


class _StubPipeline:
    """Pipeline whose download_item records calls and returns success."""

    def __init__(self, *, ok=True, delay=0.0):
        self.ok = ok
        self.delay = delay
        self.calls: list = []

    async def download_item(self, item, options, *, on_progress=None):
        self.calls.append((item, options))
        if self.delay:
            await asyncio.sleep(self.delay)
        if on_progress is not None:
            from doubi.core.pipeline import ProgressEvent
            on_progress(ProgressEvent(
                job_id="j", item=item, phase="downloading",
                fraction=0.5, message="50%",
            ))
        return self.ok


class _SwallowingPipeline:
    """Pipeline that reports a stop as ``False`` instead of raising.

    This is how the real stack behaves: ``YtDlpEngine`` runs inside
    ``asyncio.to_thread``, catches its own DownloadCancelled and returns
    ``False``, so the manager never sees a CancelledError and has to
    consult the stop flag to tell a pause apart from a real failure.
    Swallowing the cancellation here is what makes that path reachable
    from a pure-asyncio stub.
    """

    def __init__(self, *, result_when_stopped=False):
        self.result_when_stopped = result_when_stopped
        self.calls: list = []

    async def download_item(self, item, options, *, on_progress=None):
        self.calls.append((item, options))
        try:
            await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            return self.result_when_stopped
        return True


class _ScriptedProgressPipeline:
    """Pipeline that replays a fixed list of ``ProgressEvent`` kwargs.

    Exists to reproduce the exact emission order the retry loop produces
    (``core/pipeline._download_with_progress``): real progress climbs, a
    retry notice arrives with ``fraction=0.0`` because nothing is in
    flight at that instant, then progress resumes. A stub that only ever
    emits monotonic fractions cannot catch a rewind bug.
    """

    def __init__(self, script, *, ok=True):
        self.script = script
        self.ok = ok

    async def download_item(self, item, options, *, on_progress=None):
        from doubi.core.pipeline import ProgressEvent
        if on_progress is not None:
            for kwargs in self.script:
                on_progress(ProgressEvent(job_id="j", item=item, **kwargs))
        return self.ok


def _retry_event(attempt=1, max_retries=2, delay=2.0):
    """The retry notice exactly as ``DownloadPipeline`` emits it.

    Mirrors pipeline.py: phase stays ``downloading`` (a new phase would
    fall into every surface's ``else`` branch) and ``fraction`` is 0.0.
    """
    return dict(
        phase="downloading", fraction=0.0,
        message=f"retrying ({attempt}/{max_retries}) in {delay:.0f}s: engine returned False",
        extra={"retry": attempt, "max_retries": max_retries,
               "delay": delay, "reason": "engine returned False"},
    )


async def _started(ticks: int = 2) -> None:
    """Yield to the loop so freshly spawned attempts reach the pipeline.

    ``add`` / ``resume`` only schedule a task; without a yield the
    coroutine body never runs, so a stop request would cancel it before
    it ever touched the pipeline. Real usage always has the loop
    running, so tests have to reproduce that.
    """
    for _ in range(ticks):
        await asyncio.sleep(0)


async def _drain(timeout: float = 2.0) -> None:
    """Wait until no task created by the manager is pending."""
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pending = [t for t in asyncio.all_tasks()
                   if t is not asyncio.current_task() and not t.done()]
        if not pending:
            return
        await asyncio.gather(*pending, return_exceptions=True)


async def test_add_and_complete_task(qapp, tmp_path):
    from doubi.ui.task_manager import TaskManager

    mgr = TaskManager(_StubPipeline())
    events: list[str] = []
    mgr.task_added.connect(lambda tid: events.append(f"added:{tid}"))
    mgr.task_finished.connect(lambda tid, t: events.append(f"done:{tid}"))
    mgr.task_failed.connect(lambda tid, m: events.append(f"fail:{tid}"))

    task_id = mgr.add(_make_item(), _make_options(tmp_path))
    assert task_id == "T0001"
    assert mgr.active_count() == 1

    await _drain()

    assert mgr.active_count() == 0
    assert mgr.completed_count() == 1
    info = mgr.get(task_id)
    assert info is not None
    assert info.status == "completed"
    assert info.fraction == 1.0
    assert any(e.startswith("added:") for e in events)
    assert any(e.startswith("done:") for e in events)
    assert not any(e.startswith("fail:") for e in events)


async def test_add_failed_task(qapp, tmp_path):
    from doubi.ui.task_manager import TaskManager

    mgr = TaskManager(_StubPipeline(ok=False))
    events: list[str] = []
    mgr.task_failed.connect(lambda tid, m: events.append(f"fail:{tid}:{m}"))

    task_id = mgr.add(_make_item("BV2"), _make_options(tmp_path))
    await _drain()

    assert mgr.completed_count() == 1
    info = mgr.get(task_id)
    assert info.status == "failed"
    assert any(e.startswith("fail:") for e in events)


async def test_dedup_same_item(qapp, tmp_path):
    from doubi.ui.task_manager import TaskManager

    mgr = TaskManager(_StubPipeline(delay=0.2))
    opts = _make_options(tmp_path)
    t1 = mgr.add(_make_item("BV1"), opts)
    t2 = mgr.add(_make_item("BV1"), opts)   # same item_id + platform
    assert t1 == t2, "duplicate download should be deduplicated"
    assert mgr.active_count() == 1

    await _drain()
    assert mgr.completed_count() == 1


async def test_remove_active_cancels(qapp, tmp_path):
    from doubi.ui.task_manager import TaskManager

    mgr = TaskManager(_StubPipeline(delay=0.5))
    task_id = mgr.add(_make_item("BV3"), _make_options(tmp_path))
    mgr.remove(task_id)
    assert mgr.active_count() == 0

    await _drain()
    assert mgr.get(task_id) is None


async def test_clear_completed(qapp, tmp_path):
    from doubi.ui.task_manager import TaskManager

    mgr = TaskManager(_StubPipeline())
    mgr.add(_make_item("BV4"), _make_options(tmp_path))
    await _drain()
    assert mgr.completed_count() == 1
    mgr.clear_completed()
    assert mgr.completed_count() == 0


async def test_active_tasks_ordered(qapp, tmp_path):
    from doubi.ui.task_manager import TaskManager

    mgr = TaskManager(_StubPipeline(delay=0.3))
    opts = _make_options(tmp_path)
    a = mgr.add(_make_item("BV5"), opts)
    b = mgr.add(_make_item("BV6"), opts)
    ids = [t.task_id for t in mgr.active_tasks()]
    assert ids == [a, b]

    await _drain()


# ----------------------------------------------------------------------
# P3-2: pause / resume
# ----------------------------------------------------------------------


async def test_pause_keeps_task_active(qapp, tmp_path):
    """A paused task must stay in the active list, unlike a removed one.

    That is the whole point of the non-terminal ``paused`` state: the
    partial file stays on disk and the slot stays claimed, so resume is
    a real resume rather than a fresh download.
    """
    from doubi.ui.task_manager import TaskManager

    mgr = TaskManager(_SwallowingPipeline())
    task_id = mgr.add(_make_item("BV10"), _make_options(tmp_path))
    await _started()
    assert mgr.pause(task_id) is True

    # Status flips synchronously: the worker would otherwise only notice
    # the flag on the engine's next progress tick.
    info = mgr.get(task_id)
    assert info is not None
    assert info.status == "paused"
    assert mgr.active_count() == 1
    assert mgr.paused_count() == 1
    assert mgr.running_count() == 0

    await _drain()

    # Still active after the worker unwound — not moved to completed and
    # not reported as a failure.
    assert mgr.active_count() == 1
    assert mgr.completed_count() == 0
    assert mgr.get(task_id).status == "paused"


async def test_pause_options_not_shared_between_tasks(qapp, tmp_path):
    """Pausing one task must not pause its siblings.

    Callers legally reuse a single DownloadOptions across several add()
    calls, so the cancel probe has to be installed on a per-attempt copy
    instead of mutating the caller's bag.
    """
    from doubi.ui.task_manager import TaskManager

    pipeline = _SwallowingPipeline()
    mgr = TaskManager(pipeline)
    opts = _make_options(tmp_path)
    a = mgr.add(_make_item("BV11"), opts)
    b = mgr.add(_make_item("BV12"), opts)
    await _started()

    mgr.pause(a)
    assert mgr.get(a).status == "paused"
    assert mgr.get(b).status == "running"
    assert opts.cancel_check is None, "caller's options must stay untouched"

    # Each attempt received its own probe, and only a's is tripped.
    probes = [o.cancel_check for _, o in pipeline.calls]
    assert len(probes) == 2
    assert probes[0] is not probes[1]
    assert probes[0]() is True
    assert probes[1]() is False

    mgr.remove(b)
    await _drain()


async def test_resume_restarts_and_completes(qapp, tmp_path):
    from doubi.ui.task_manager import TaskManager

    pipeline = _SwallowingPipeline()
    mgr = TaskManager(pipeline)
    task_id = mgr.add(_make_item("BV13"), _make_options(tmp_path))
    await _started()
    mgr.pause(task_id)
    await _drain()
    assert mgr.get(task_id).status == "paused"

    assert mgr.resume(task_id) is True
    assert mgr.get(task_id).status == "running"
    await _started()
    assert len(pipeline.calls) == 2, "resume should start a new attempt"

    await _drain()
    assert mgr.completed_count() == 1
    assert mgr.get(task_id).status == "completed"


async def test_resume_gets_fresh_flag(qapp, tmp_path):
    """The resumed attempt must not inherit the paused attempt's flag.

    If the flag were keyed by task_id and merely cleared, the old worker
    (possibly still inside the engine thread) would come back to life and
    two writers would share one ``.part`` file.
    """
    from doubi.ui.task_manager import TaskManager

    pipeline = _SwallowingPipeline()
    mgr = TaskManager(pipeline)
    task_id = mgr.add(_make_item("BV14"), _make_options(tmp_path))
    await _started()
    mgr.pause(task_id)
    first_probe = pipeline.calls[0][1].cancel_check
    await _drain()

    mgr.resume(task_id)
    await _started()
    second_probe = pipeline.calls[1][1].cancel_check
    assert second_probe is not first_probe
    assert first_probe() is True, "the paused attempt stays stopped"
    assert second_probe() is False

    mgr.remove(task_id)
    await _drain()


async def test_pause_rejects_non_running_states(qapp, tmp_path):
    from doubi.ui.task_manager import TaskManager

    mgr = TaskManager(_StubPipeline())
    task_id = mgr.add(_make_item("BV15"), _make_options(tmp_path))
    await _drain()

    # Completed: nothing to pause, and nothing to resume either.
    assert mgr.pause(task_id) is False
    assert mgr.resume(task_id) is False
    assert mgr.pause("T9999") is False
    assert mgr.resume("T9999") is False


async def test_resume_rejects_running_task(qapp, tmp_path):
    from doubi.ui.task_manager import TaskManager

    pipeline = _SwallowingPipeline()
    mgr = TaskManager(pipeline)
    task_id = mgr.add(_make_item("BV16"), _make_options(tmp_path))
    await _started()
    assert mgr.resume(task_id) is False
    assert len(pipeline.calls) == 1, "must not spawn a duplicate attempt"

    mgr.remove(task_id)
    await _drain()


async def test_late_pause_loses_to_finished_download(qapp, tmp_path):
    """A transfer that already succeeded must not be marked paused.

    The stop request can land after the engine finished; treating that as
    a pause would leave the task waiting forever with nothing left to do.
    """
    from doubi.ui.task_manager import TaskManager

    # result_when_stopped=True simulates "the file was already complete
    # when the stop arrived".
    mgr = TaskManager(_SwallowingPipeline(result_when_stopped=True))
    task_id = mgr.add(_make_item("BV17"), _make_options(tmp_path))
    await _started()
    mgr.pause(task_id)
    await _drain()

    assert mgr.completed_count() == 1
    assert mgr.get(task_id).status == "completed"


async def test_pause_all_and_resume_all(qapp, tmp_path):
    from doubi.ui.task_manager import TaskManager

    pipeline = _SwallowingPipeline()
    mgr = TaskManager(pipeline)
    opts = _make_options(tmp_path)
    mgr.add(_make_item("BV18"), opts)
    mgr.add(_make_item("BV19"), opts)
    await _started()

    assert mgr.pause_all() == 2
    assert mgr.paused_count() == 2
    assert mgr.running_count() == 0
    assert mgr.pause_all() == 0, "already paused tasks are not paused again"
    await _drain()

    assert mgr.resume_all() == 2
    assert mgr.running_count() == 2
    await _started()
    assert len(pipeline.calls) == 4

    await _drain()
    assert mgr.completed_count() == 2


async def test_remove_paused_task(qapp, tmp_path):
    """Removing a paused task must drop it, not resurrect it."""
    from doubi.ui.task_manager import TaskManager

    mgr = TaskManager(_SwallowingPipeline())
    task_id = mgr.add(_make_item("BV20"), _make_options(tmp_path))
    await _started()
    mgr.pause(task_id)
    await _drain()
    assert mgr.get(task_id).status == "paused"

    mgr.remove(task_id)
    await _drain()
    assert mgr.get(task_id) is None
    assert mgr.active_count() == 0
    assert mgr.completed_count() == 0


# ---------------------------------------------------------------------------
# M6.9: retry notices must not rewind the progress bar
# ---------------------------------------------------------------------------


async def test_retry_notice_does_not_rewind_progress(qapp, tmp_path):
    """A retry notice must keep the last real fraction.

    ``DownloadPipeline`` emits its retry notice with ``fraction=0.0``
    (nothing is transferring at that moment). ``_on_progress`` used to
    assign that value unconditionally, so a task sitting at 80% visibly
    snapped back to 0 on every transient failure — reading as "it started
    over" even though ``resume=True`` means it did not.

    Verified to fail before the fix: dropping the ``extra['retry']`` guard
    in ``ui/task_manager._on_progress`` makes the mid-flight assertion
    below report 0.0.
    """
    from doubi.ui.task_manager import TaskManager

    seen: list[float] = []
    mid_flight: list[float] = []

    pipeline = _ScriptedProgressPipeline([
        dict(phase="downloading", fraction=0.8, message="80%"),
        _retry_event(attempt=1),
    ])
    mgr = TaskManager(pipeline)

    def _capture(task_id, fraction, message):
        seen.append(fraction)
        info = mgr.get(task_id)
        if info is not None:
            mid_flight.append(info.fraction)

    mgr.task_progress.connect(_capture)

    task_id = mgr.add(_make_item("BV30"), _make_options(tmp_path))
    await _drain()

    # The retry notice is the second event. Neither the signal argument
    # nor the TaskInfo may report a fraction below the 0.8 already reached.
    assert seen == [0.8, 0.8], f"progress rewound: {seen}"
    assert mid_flight == [0.8, 0.8], f"TaskInfo rewound: {mid_flight}"


async def test_retry_notice_still_updates_the_message(qapp, tmp_path):
    """Suppressing the fraction must not suppress the text.

    The retry notice is the *only* thing that tells a GUI user why their
    download is stalling. Guarding too broadly (skipping the whole event)
    would trade a cosmetic bug for a silent one.
    """
    from doubi.ui.task_manager import TaskManager

    messages: list[str] = []
    pipeline = _ScriptedProgressPipeline([
        dict(phase="downloading", fraction=0.8, message="80%"),
        _retry_event(attempt=2, max_retries=2, delay=4.0),
    ])
    mgr = TaskManager(pipeline)
    mgr.task_progress.connect(lambda tid, frac, msg: messages.append(msg))

    task_id = mgr.add(_make_item("BV31"), _make_options(tmp_path))
    await _drain()

    assert any("retrying (2/2)" in m for m in messages), messages


# ---------------------------------------------------------------------------
# Cross-process resume: the pending_task row must track the task's life
# ---------------------------------------------------------------------------
#
# Every test above builds options *without* a database, so all of them
# exercise the ``db_path is None`` early return. The persistence wiring is
# only reachable with a real path, hence the separate fixture below.


def _db_options(tmp_path):
    from doubi.core.models import DownloadOptions
    return DownloadOptions(output_root=tmp_path, database=tmp_path / "doubi.db")


async def _rows(db_path) -> list:
    """Read the pending table straight from disk, bypassing the manager."""
    from doubi.core.storage import Database
    async with Database(db_path) as db:
        return await db.list_unfinished()


async def _wait_rows(db_path, count: int, timeout: float = 2.0) -> list:
    """Poll the table until it holds *count* rows, then return them.

    Persistence is deliberately fire-and-forget (see ``_run_db``), so
    there is no handle to await. ``_drain`` is not a substitute here: it
    would also run the download to completion, and a terminal state
    *deletes* the very row we came to inspect.
    """
    import time
    deadline = time.monotonic() + timeout
    while True:
        rows = await _rows(db_path)
        if len(rows) == count or time.monotonic() > deadline:
            return rows
        await asyncio.sleep(0.01)


async def test_pending_row_written_on_add_and_dropped_on_completion(qapp, tmp_path):
    """The row exists exactly as long as the work is outstanding."""
    from doubi.ui.task_manager import TaskManager

    opts = _db_options(tmp_path)
    # A slow pipeline keeps the task in flight long enough to observe.
    mgr = TaskManager(_SwallowingPipeline())
    task_id = mgr.add(_make_item("BV40", "标题"), opts)
    await _started()

    rows = await _wait_rows(opts.database, 1)
    assert [r.task_id for r in rows] == [task_id]
    row = rows[0]
    assert row.source_url.endswith("BV40")
    assert row.title == "标题"
    # Snapshots are what let a restart skip the re-parse entirely.
    assert row.item_snapshot and row.item_snapshot["item_id"] == "BV40"
    assert row.options_snapshot and "output_root" in row.options_snapshot

    # Letting the transfer finish must clear it: a completed download has
    # no business showing up in the next launch's restore prompt.
    await _drain()
    assert await _rows(opts.database) == []


async def test_pending_row_survives_pause_and_carries_the_fraction(qapp, tmp_path):
    """A paused task is the whole point of the table, so it must persist."""
    from doubi.ui.task_manager import TaskManager

    opts = _db_options(tmp_path)
    mgr = TaskManager(_SwallowingPipeline())
    task_id = mgr.add(_make_item("BV41"), opts)
    await _started()
    mgr.get(task_id).fraction = 0.42
    mgr.pause(task_id)
    await _drain()

    rows = await _rows(opts.database)
    assert len(rows) == 1
    assert rows[0].status == "paused"
    assert rows[0].fraction == pytest.approx(0.42)


async def test_pending_row_dropped_on_remove_and_restored_on_retry(qapp, tmp_path):
    from doubi.ui.task_manager import TaskManager

    opts = _db_options(tmp_path)
    # The delay is what makes the *retried* attempt observable: with an
    # instant pipeline the new attempt would fail again inside the same
    # drain, deleting the row before we could look at it.
    mgr = TaskManager(_StubPipeline(ok=False, delay=0.3))
    task_id = mgr.add(_make_item("BV42"), opts)
    await _drain()
    # A failure is terminal, so the row is gone.
    assert await _rows(opts.database) == []

    # ...and a retry makes the work outstanding again, snapshots included,
    # because the terminal transition deleted the row that held them.
    assert mgr.retry(task_id) is True
    await _started()
    rows = await _wait_rows(opts.database, 1)
    assert [r.task_id for r in rows] == [task_id]
    assert rows[0].item_snapshot is not None

    mgr.remove(task_id)
    await _drain()
    assert await _rows(opts.database) == []


async def test_restore_reinstates_as_paused_without_downloading(qapp, tmp_path):
    """Restored tasks wait for an explicit resume.

    Auto-starting on launch would be the wrong default: the app may have
    been killed *because* the transfer was saturating the line. The
    stub pipeline records every call, so an empty ``calls`` list is proof
    that nothing was spawned.
    """
    from doubi.ui.task_manager import TaskManager

    opts = _db_options(tmp_path)
    writer = TaskManager(_SwallowingPipeline())
    old_id = writer.add(_make_item("BV43", "上次的标题"), opts)
    await _started()
    writer.get(old_id).fraction = 0.6
    writer.pause(old_id)
    await _drain()

    # A brand new process: fresh manager, fresh pipeline, same database.
    pipeline = _StubPipeline()
    mgr = TaskManager(pipeline)
    added: list[str] = []
    mgr.task_added.connect(added.append)

    rows = await TaskManager.list_restorable(opts.database)
    restored = mgr.restore(rows, _db_options(tmp_path))
    await _drain()

    assert restored == [old_id], "the original task_id must be preserved"
    assert added == [old_id]
    assert pipeline.calls == [], "restore must not start the transfer"
    info = mgr.get(old_id)
    assert info.status == "paused"
    assert info.fraction == pytest.approx(0.6)
    assert info.title == "上次的标题"
    # The snapshot must carry enough metadata to resume in place.
    assert info.item.source_url.endswith("BV43")
    assert info.item.platform.value == "bilibili"
    # Options come back off the snapshot, not off the bare defaults.
    assert info.options.database == opts.database

    # And it is genuinely resumable, i.e. a real active task, not a corpse.
    assert mgr.resume(old_id) is True
    await _started()
    assert len(pipeline.calls) == 1


async def test_restore_reseeds_counter_so_new_ids_cannot_collide(qapp, tmp_path):
    """``add`` mints ``T{n:04d}`` from a counter that restarts at zero.

    Without reseeding, the first new task after restoring ``T0001..T0003``
    would be handed ``T0001`` again and overwrite a restored task's row.
    """
    from doubi.ui.task_manager import TaskManager

    opts = _db_options(tmp_path)
    writer = TaskManager(_SwallowingPipeline())
    for n in range(3):
        writer.add(_make_item(f"BV5{n}"), opts)
    await _started()
    writer.pause_all()
    await _drain()

    mgr = TaskManager(_StubPipeline())
    rows = await TaskManager.list_restorable(opts.database)
    restored = mgr.restore(rows, _db_options(tmp_path))
    assert sorted(restored) == ["T0001", "T0002", "T0003"]

    fresh = mgr.add(_make_item("BV_new"), opts)
    await _drain()
    assert fresh == "T0004", f"id collided with a restored task: {fresh}"

    # ``_drain`` gathers the download tasks, and finishing one *schedules*
    # the row deletion. ``gather`` returns the moment the task is done, but
    # done-callbacks are dispatched with ``call_soon``, so the write is not
    # in ``_db_tasks`` yet -- and ``flush_pending_writes`` short-circuits on
    # an empty set, so flushing right here would wait for nothing. The
    # ``sleep(0)`` hands the loop one turn to run those callbacks, so the
    # queue is populated before we wait on it.
    await asyncio.sleep(0)
    await mgr.flush_pending_writes()
    await writer.flush_pending_writes()


async def test_restore_falls_back_to_source_url_when_snapshot_is_missing(qapp, tmp_path):
    """A row from an older schema has no snapshot but is still downloadable."""
    from doubi.core.storage import Database, PendingTaskRow
    from doubi.ui.task_manager import TaskManager

    opts = _db_options(tmp_path)
    async with Database(opts.database) as db:
        await db.upsert_pending_task(PendingTaskRow(
            task_id="T0007", platform="bilibili", status="paused",
            source_url="https://www.bilibili.com/video/BV60",
            item_id="BV60", title="无快照",
        ))
        # A row with nothing to download is unusable and must be skipped
        # rather than restored into a task that can only fail.
        await db.upsert_pending_task(PendingTaskRow(
            task_id="T0008", platform="bilibili", status="paused",
            source_url="",
        ))

    mgr = TaskManager(_StubPipeline())
    rows = await TaskManager.list_restorable(opts.database)
    restored = mgr.restore(rows, _db_options(tmp_path))
    await _drain()

    assert restored == ["T0007"]
    info = mgr.get("T0007")
    assert info.item.source_url.endswith("BV60")
    assert info.item.platform.value == "bilibili"
    assert info.item.item_id == "BV60"


async def test_download_survives_an_unwritable_database(qapp, tmp_path):
    """Bookkeeping is a convenience; it must never break a good download.

    The path below has a *file* where its parent directory should be, so
    ``Database.initialize``'s mkdir raises. If ``_run_db`` let that
    propagate, the download itself would die with it.
    """
    from doubi.core.models import DownloadOptions
    from doubi.ui.task_manager import TaskManager

    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x", encoding="utf-8")
    opts = DownloadOptions(
        output_root=tmp_path, database=blocker / "sub" / "doubi.db"
    )

    mgr = TaskManager(_StubPipeline())
    task_id = mgr.add(_make_item("BV70"), opts)
    await _drain()

    assert mgr.get(task_id).status == "completed"


async def test_list_restorable_tolerates_a_broken_database(qapp, tmp_path):
    """Startup must not be abortable by a bad database path."""
    from doubi.ui.task_manager import TaskManager

    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")

    assert await TaskManager.list_restorable(None) == []
    assert await TaskManager.list_restorable(blocker / "sub" / "doubi.db") == []


async def test_flush_pending_writes_lands_the_last_transition(qapp, tmp_path):
    """Shutdown must not drop the state the next launch depends on.

    ``pause`` returns before its row is written, so a window closing
    right after it would take the event loop down with the write still
    queued -- and the task would come back looking like it was still
    running. Awaiting the flush is what makes the pause durable.
    """
    from doubi.ui.task_manager import TaskManager

    opts = _db_options(tmp_path)
    mgr = TaskManager(_SwallowingPipeline())
    task_id = mgr.add(_make_item("BV80"), opts)
    await _started()

    mgr.pause(task_id)
    # No _wait_rows / _drain here on purpose: the flush alone has to be
    # sufficient, because at shutdown there is nothing else left to run.
    await mgr.flush_pending_writes()

    rows = await _rows(opts.database)
    assert [r.task_id for r in rows] == [task_id]
    assert rows[0].status == "paused"

    await _drain()


async def test_flush_pending_writes_ignores_running_downloads(qapp, tmp_path):
    """The flush waits for bookkeeping, never for the transfer itself.

    ``_SwallowingPipeline`` sleeps for 0.5s, far longer than a row write.
    If the flush awaited download tasks too, closing the window during an
    active download would hang for the length of the download.
    """
    import time

    from doubi.ui.task_manager import TaskManager

    opts = _db_options(tmp_path)
    mgr = TaskManager(_SwallowingPipeline())
    mgr.add(_make_item("BV81"), opts)
    await _started()

    started = time.monotonic()
    await mgr.flush_pending_writes()
    elapsed = time.monotonic() - started

    assert elapsed < 0.4, f"flush waited on the download ({elapsed:.2f}s)"
    await _drain()


async def test_normal_progress_still_moves_backwards_when_told_to(qapp, tmp_path):
    """The guard must key off ``extra['retry']``, not off "fraction went down".

    A resumed attempt legitimately reports a *lower* fraction than the
    previous attempt reached (the engine restarts its own accounting).
    Implementing the fix as "never decrease" would freeze the bar at a
    stale high-water mark, so pin the narrower rule here.
    """
    from doubi.ui.task_manager import TaskManager

    seen: list[float] = []
    pipeline = _ScriptedProgressPipeline([
        dict(phase="downloading", fraction=0.8, message="80%"),
        dict(phase="downloading", fraction=0.1, message="10%"),
    ])
    mgr = TaskManager(pipeline)
    mgr.task_progress.connect(lambda tid, frac, msg: seen.append(frac))

    mgr.add(_make_item("BV32"), _make_options(tmp_path))
    await _drain()

    assert seen == [0.8, 0.1], f"non-retry events must pass through: {seen}"


async def test_retry_notice_before_any_progress_is_harmless(qapp, tmp_path):
    """A retry on attempt 1 can arrive before any real fraction exists.

    ``TaskInfo.fraction`` starts at 0.0, so the guard must not depend on a
    previous value being present.
    """
    from doubi.ui.task_manager import TaskManager

    pipeline = _ScriptedProgressPipeline([_retry_event(attempt=1)], ok=False)
    mgr = TaskManager(pipeline)

    task_id = mgr.add(_make_item("BV33"), _make_options(tmp_path))
    await _drain()

    info = mgr.get(task_id)
    assert info is not None
    assert info.fraction == 0.0
    assert "retrying" in info.message


async def test_discard_restorable_makes_the_answer_stick(qapp, tmp_path):
    """Declining the restore prompt must survive the next launch.

    Without this, the same prompt returns on every start; by the third
    time the user stops reading it, which also disarms it for the launch
    where it actually matters.
    """
    from doubi.ui.task_manager import TaskManager

    opts = _db_options(tmp_path)
    writer = TaskManager(_SwallowingPipeline())
    writer.add(_make_item("BV50", "不想要的"), opts)
    writer.add(_make_item("BV51", "也不想要"), opts)
    await _started()
    writer.pause_all()
    await _drain()
    await writer.flush_pending_writes()

    rows = await TaskManager.list_restorable(opts.database)
    assert len(rows) == 2, "precondition: both tasks are restorable"

    mgr = TaskManager(_StubPipeline())
    added: list[str] = []
    mgr.task_added.connect(added.append)
    mgr.discard_restorable(rows, opts.database)
    await mgr.flush_pending_writes()

    assert await TaskManager.list_restorable(opts.database) == []
    assert added == [], "discarding must not revive the tasks"
    # The partial files are the user's; this forgets the bookkeeping only.
    assert tmp_path.exists()


async def test_discard_restorable_without_a_database_is_a_no_op(qapp, tmp_path):
    """``database`` is optional config, so the None path must not raise."""
    from doubi.ui.task_manager import TaskManager

    opts = _db_options(tmp_path)
    writer = TaskManager(_SwallowingPipeline())
    writer.add(_make_item("BV52"), opts)
    await _started()
    writer.pause_all()
    await _drain()
    await writer.flush_pending_writes()
    rows = await TaskManager.list_restorable(opts.database)
    assert rows

    mgr = TaskManager(_StubPipeline())
    mgr.discard_restorable(rows, None)
    await mgr.flush_pending_writes()

    # Nothing was asked for, so nothing was deleted from the real database.
    assert len(await TaskManager.list_restorable(opts.database)) == len(rows)
