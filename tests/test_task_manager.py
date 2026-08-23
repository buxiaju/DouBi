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
