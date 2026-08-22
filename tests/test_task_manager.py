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
