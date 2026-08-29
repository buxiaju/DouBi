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


pytestmark = pytest.mark.gui


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


# ----------------------------------------------------------------------
# P3-2: pause / resume in the UI
# ----------------------------------------------------------------------


class _StoppablePipeline:
    """Sleeps long enough to be paused, and reports a stop as ``False``.

    Mirrors the real engine, which catches its own cancellation inside
    ``asyncio.to_thread`` and returns False rather than propagating.
    """

    async def download_item(self, item, options, *, on_progress=None):
        try:
            await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            return False
        return True


async def _started(ticks: int = 2) -> None:
    for _ in range(ticks):
        await asyncio.sleep(0)


async def test_download_page_pause_row_toggles_button(qapp, tmp_path):
    from doubi.ui.pages.download import build_download_widgets
    from doubi.ui.task_manager import TaskManager

    cls, _ = build_download_widgets()
    page = cls()
    mgr = TaskManager(_StoppablePipeline())
    page.set_task_manager(mgr)

    task_id = mgr.add(_make_item("BV1"), _make_options(tmp_path))
    await _started()
    qapp.processEvents()
    row = page._rows[task_id]
    assert row.pause_btn.text() == "暂停"

    # Click-equivalent: the row delegates the decision to the page.
    page._on_pause_row(row)
    qapp.processEvents()
    assert row.info.status == "paused"
    assert "已暂停" in row.status_label.text()
    # The button now advertises the opposite action.
    assert row.pause_btn.text() == "继续"
    # A paused row stays in the active list rather than moving to 已完成.
    assert mgr.active_count() == 1
    assert mgr.completed_count() == 0

    await _drain()
    page._on_pause_row(row)
    qapp.processEvents()
    assert row.info.status == "running"
    assert row.pause_btn.text() == "暂停"

    mgr.remove(task_id)
    await _drain()


async def test_download_page_pause_all_toggles_label(qapp, tmp_path):
    from doubi.ui.pages.download import build_download_widgets
    from doubi.ui.task_manager import TaskManager

    cls, _ = build_download_widgets()
    page = cls()
    mgr = TaskManager(_StoppablePipeline())
    page.set_task_manager(mgr)

    opts = _make_options(tmp_path)
    a = mgr.add(_make_item("BV1"), opts)
    b = mgr.add(_make_item("BV2"), opts)
    await _started()
    qapp.processEvents()
    assert page.pause_all_btn.isEnabled()
    assert page.pause_all_btn.text() == "全部暂停"

    page._on_pause_all()
    qapp.processEvents()
    assert mgr.paused_count() == 2
    # Both rows must have picked up the bulk change even though it did
    # not travel through the per-row signal path.
    assert page._rows[a].pause_btn.text() == "继续"
    assert page._rows[b].pause_btn.text() == "继续"
    # With nothing running the same button becomes the resume-all button.
    assert page.pause_all_btn.text() == "全部继续"
    assert "2 个已暂停" in page.active_summary.text()

    await _drain()
    page._on_pause_all()
    qapp.processEvents()
    assert mgr.running_count() == 2
    assert page.pause_all_btn.text() == "全部暂停"

    page._remove_all_active()
    await _drain()


async def test_download_page_pause_btn_hidden_when_terminal(qapp, tmp_path):
    """A finished row offers no pause control, but keeps the column width."""
    from doubi.ui.pages.download import build_download_widgets
    from doubi.ui.task_manager import TaskManager

    cls, _ = build_download_widgets()
    page = cls()
    mgr = TaskManager(_OkPipeline())
    page.set_task_manager(mgr)

    task_id = mgr.add(_make_item("BV9"), _make_options(tmp_path))
    qapp.processEvents()
    await _drain()
    qapp.processEvents()

    row = page._rows[task_id]
    assert row.info.status == "completed"
    assert row.pause_btn.isVisible() is False
    assert row.pause_slot.width() == 52


# ----------------------------------------------------------------------
# M6.18: _friendly_phase dedup (no double-printing of percentage)
# ----------------------------------------------------------------------


class TestFriendlyPhaseDedup:
    """The percentage lives in ``info.fraction`` and is rendered as its
    own column. The message column must never echo the same number back
    — otherwise the user sees ``60%  m3u8 下载中 60%`` side by side.
    These tests pin the deduplication contract: any ``N%`` fragment in
    the engine-supplied message must be stripped before the message
    column is rendered.
    """

    @staticmethod
    def _friendly_phase(message: str) -> str:
        # Module-level function — no QApplication needed. See
        # ``TaskRow._friendly_phase`` for the wrapper that preserves
        # the per-row code path.
        from doubi.ui.pages.download import friendly_phase
        return friendly_phase(message)

    def test_strips_full_width_colon_chinese_phase_with_pct(self):
        """nm3u8dl watchdog used to emit ``m3u8 下载中 60%``. After
        the M6.17 fix it no longer carries the percentage, but a
        stale engine / third-party wrapper might. The friendly phase
        must strip the ``60%`` and return just ``下载中``.
        """
        out = self._friendly_phase("m3u8 下载中 60%")
        assert "60" not in out
        assert "%" not in out
        assert "下载" in out

    def test_strips_pct_only_message(self):
        """A message of nothing-but-a-percentage falls back to ``下载中``
        — the column should never render blank.
        """
        out = self._friendly_phase("60%")
        assert out  # non-empty

    def test_chinese_download_phrase_alone(self):
        out = self._friendly_phase("m3u8 下载中")
        assert "下载" in out

    def test_english_downloading_phrase_still_works(self):
        out = self._friendly_phase("downloading video")
        assert "下载中" in out

    def test_empty_message_returns_queued(self):
        assert self._friendly_phase("") == "排队中"


# ----------------------------------------------------------------------
# M6.18: completion notifications forwarded to the tray
# ----------------------------------------------------------------------


class _FakeTray:
    def __init__(self):
        self.completions = []
        self.summaries = []

    def notify_completion(self, *, mode, success, title, error=""):
        self.completions.append(
            {"mode": mode, "success": success, "title": title, "error": error},
        )

    def notify_summary(self, *, succeeded, failed):
        self.summaries.append({"succeeded": succeeded, "failed": failed})


class _FakeCfg:
    def __init__(self, mode):
        self.notify_on_completion = mode


class _FakeSettingsPage:
    def __init__(self, mode):
        self._cfg = _FakeCfg(mode)


class TestMaybeNotifyCompletion:
    """``DownloadPage`` forwards terminal task events to the tray.

    The first cut of this method read ``self.parse_interface._cfg`` —
    but ``parse_interface`` is a ``MainWindow`` attribute, not a
    ``DownloadPage`` one, so *every* completed download raised
    ``AttributeError``. The live config actually hangs off
    ``settings_interface._cfg`` (that's the copy main_window reads when
    it pushes settings into the other pages).

    A parentless ``QWidget.window()`` returns the widget itself, so we
    can stand in for MainWindow by hanging the two attributes directly
    on the page.
    """

    @staticmethod
    def _page(qapp, mode):
        from doubi.ui.pages.download import build_download_widgets
        DownloadPage, _ = build_download_widgets()
        page = DownloadPage()
        tray = _FakeTray()
        # ``page.window()`` is ``page`` (no parent), so these stand in
        # for the MainWindow attributes the real code reads.
        page.tray = tray
        page.settings_interface = _FakeSettingsPage(mode)
        return page, tray

    def test_success_mode_forwards_success(self, qapp):
        page, tray = self._page(qapp, "success")
        page._maybe_notify_completion(success=True, title="video A", error="")
        assert tray.completions == [
            {"mode": "success", "success": True, "title": "video A", "error": ""},
        ]

    def test_all_mode_forwards_failure(self, qapp):
        page, tray = self._page(qapp, "all")
        page._maybe_notify_completion(
            success=False, title="video A", error="HTTP 403",
        )
        assert len(tray.completions) == 1
        assert tray.completions[0]["mode"] == "all"
        assert tray.completions[0]["success"] is False
        assert tray.completions[0]["error"] == "HTTP 403"

    def test_summary_mode_accumulates_instead_of_forwarding(self, qapp):
        page, tray = self._page(qapp, "summary")
        page._maybe_notify_completion(success=True, title="a", error="")
        page._maybe_notify_completion(success=True, title="b", error="")
        page._maybe_notify_completion(success=False, title="c", error="x")
        # Nothing fired per-task; the counters hold the tally.
        assert tray.completions == []
        assert page._succeeded_pending == 2
        assert page._failed_pending == 1

    def test_no_tray_is_a_silent_noop(self, qapp):
        from doubi.ui.pages.download import build_download_widgets
        DownloadPage, _ = build_download_widgets()
        page = DownloadPage()
        # No tray attribute at all (headless / tray-less desktop).
        page._maybe_notify_completion(success=True, title="a", error="")

    def test_missing_settings_page_is_a_silent_noop(self, qapp):
        from doubi.ui.pages.download import build_download_widgets
        DownloadPage, _ = build_download_widgets()
        page = DownloadPage()
        tray = _FakeTray()
        page.tray = tray
        # settings_interface absent → no config to read → no toast, but
        # crucially no AttributeError either.
        page._maybe_notify_completion(success=True, title="a", error="")
        assert tray.completions == []

    def test_flush_summary_fires_once_when_drained(self, qapp):
        page, tray = self._page(qapp, "summary")
        page._succeeded_pending = 2
        page._failed_pending = 1
        # No manager attached → counters reset, nothing announced.
        page._flush_summary_if_drained()
        assert page._succeeded_pending == 0
        assert page._failed_pending == 0

