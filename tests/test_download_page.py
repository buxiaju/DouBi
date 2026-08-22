"""Tests for the M5.4 DownloadPage — the Bili23-style task manager.

The page is a passive observer of a TaskManager: when a task is
added, it renders a TaskRow; when the task finishes, it moves the row
to the "已完成" list. We drive it through a real TaskManager + stub
pipeline, headlessly.
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


def _make_item(item_id="BV1"):
    from doubi.core.models import Author, MediaItem, MediaType, Platform
    return MediaItem(
        platform=Platform.BILIBILI, item_id=item_id, title=f"t-{item_id}",
        author=Author(name="u"), media_type=MediaType.VIDEO,
        source_url=f"https://www.bilibili.com/video/{item_id}",
    )


def _make_options(tmp_path):
    from doubi.core.models import DownloadOptions
    return DownloadOptions(output_root=tmp_path)


class _OkPipeline:
    async def download_item(self, item, options, *, on_progress=None):
        return True


async def _drain(timeout: float = 2.0) -> None:
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pending = [t for t in asyncio.all_tasks()
                   if t is not asyncio.current_task() and not t.done()]
        if not pending:
            return
        await asyncio.gather(*pending, return_exceptions=True)


async def test_download_page_renders_task_and_completes(qapp, tmp_path):
    from doubi.ui.pages.download import build_download_widgets
    from doubi.ui.task_manager import TaskManager

    cls, _ = build_download_widgets()
    page = cls()
    mgr = TaskManager(_OkPipeline())
    page.set_task_manager(mgr)

    task_id = mgr.add(_make_item(), _make_options(tmp_path))
    qapp.processEvents()

    # Active tab should have a row now
    assert task_id in page._rows
    row = page._rows[task_id]
    assert row.info.status == "running"
    assert "下载中" in row.status_label.text()

    await _drain()
    qapp.processEvents()

    # Task moved to completed; row is still tracked but its info is terminal
    assert mgr.completed_count() == 1
    assert row.info.status == "completed"
    assert "完成" in row.status_label.text()


async def test_download_page_remove_all_active(qapp, tmp_path):
    from doubi.ui.pages.download import build_download_widgets
    from doubi.ui.task_manager import TaskManager

    class _SlowPipeline:
        async def download_item(self, item, options, *, on_progress=None):
            await asyncio.sleep(0.5)
            return True

    cls, _ = build_download_widgets()
    page = cls()
    mgr = TaskManager(_SlowPipeline())
    page.set_task_manager(mgr)

    mgr.add(_make_item("BV1"), _make_options(tmp_path))
    mgr.add(_make_item("BV2"), _make_options(tmp_path))
    qapp.processEvents()
    assert mgr.active_count() == 2
    assert len(page._rows) == 2

    page._remove_all_active()
    assert mgr.active_count() == 0

    await _drain()
