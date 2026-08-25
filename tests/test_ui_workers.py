"""Tests for the M5 GUI shell.

PySide6 / qfluentwidgets are *optional* — these tests run in a
headless test environment without them. They cover:
  * ``is_gui_available`` reports False
  * The page factories raise a clear error when called without GUI
  * The :class:`DownloadWorker` (which has no Qt deps) wires
    through the pipeline correctly
"""

from __future__ import annotations

import asyncio
import datetime as dt
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from doubi.core.models import (  # noqa: E402
    Author,
    DownloadOptions,
    MediaItem,
    MediaType,
    Platform,
)
from doubi.ui import GUIUnavailableError, is_gui_available  # noqa: E402
from doubi.ui.workers import DownloadWorker, DownloadTask  # noqa: E402


pytestmark = pytest.mark.gui


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


def test_gui_availability_reflects_env():
    """The flag accurately reports whether PySide6 is installed."""
    # In this test env we don't have PySide6 — is_gui_available() should be False
    if _has_pyside6():
        assert is_gui_available() is True
    else:
        assert is_gui_available() is False


def _has_pyside6() -> bool:
    try:
        import PySide6  # noqa: F401
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# Page factories — should raise a clear error when GUI is missing
# ---------------------------------------------------------------------------


def test_page_factory_douyin_imports_gui_raises_without_pyside6():
    """When PySide6 is not installed, the page builder surfaces a clean error."""
    if _has_pyside6():
        pytest.skip("PySide6 is installed; cannot test missing-deps path")
    from doubi.ui.pages.download import build_download_widgets
    with pytest.raises((ImportError, ModuleNotFoundError)):
        build_download_widgets()


def test_page_factory_history_imports_gui_raises_without_pyside6():
    if _has_pyside6():
        pytest.skip("PySide6 is installed; cannot test missing-deps path")
    from doubi.ui.pages.history import build_history_widgets
    with pytest.raises((ImportError, ModuleNotFoundError)):
        build_history_widgets()


def test_page_factory_settings_imports_gui_raises_without_pyside6():
    if _has_pyside6():
        pytest.skip("PySide6 is installed; cannot test missing-deps path")
    from doubi.ui.pages.settings import build_settings_widgets
    with pytest.raises((ImportError, ModuleNotFoundError)):
        build_settings_widgets()


# ---------------------------------------------------------------------------
# DownloadWorker — no Qt deps, exercises the pipeline
# ---------------------------------------------------------------------------


def test_download_task_dataclass_holds_options():
    task = DownloadTask(
        url="https://example.com/video",
        options=DownloadOptions(output_root=Path("./o")),
        pipeline=None,  # not used in __init__
    )
    assert task.url == "https://example.com/video"
    assert task.options.output_root == Path("./o")


class _SpySignals:
    """Stand-in for the Qt signal bag that DownloadWorker expects."""

    def __init__(self):
        self.started_calls: list = []
        self.progress_calls: list = []
        self.finished_calls: list = []
        self.failed_calls: list = []

    # Fake .emit() that's a method
    def _make_emit(name):
        def _emit(*args):
            getattr(self, f"{name}_calls").append(args)
        return _emit

    started = property(lambda s: s, lambda s, v: None)
    progress = property(lambda s: s, lambda s, v: None)
    finished = property(lambda s: s, lambda s, v: None)
    failed = property(lambda s: s, lambda s, v: None)


def test_download_worker_emits_signals_on_success(monkeypatch, tmp_path):
    """Worker.run() should call started → finished on a successful parse."""
    from doubi.core.pipeline import DownloadPipeline

    class _StubEngine:
        name = "stub"
        def supports(self, item): return True
        async def download(self, item, options, *, on_progress=None):
            return True

    pipeline = DownloadPipeline(engine=_StubEngine())
    worker = DownloadWorker(
        url="https://www.bilibili.com/video/BV1xx",
        options=DownloadOptions(output_root=tmp_path),
        pipeline=pipeline,
    )

    # Fake the Qt signal bag with simple Python records
    sig = MagicMock()
    sig.started = MagicMock()
    sig.progress = MagicMock()
    sig.finished = MagicMock()
    sig.failed = MagicMock()
    worker.signals = sig

    async def _parse(url):
        return MediaItem(
            platform=Platform.BILIBILI, item_id="BV1xx", title="测试",
            author=Author(name="UP"), media_type=MediaType.VIDEO, source_url=url,
        )
    monkeypatch.setattr(pipeline, "parse", _parse)

    asyncio.run(worker.run())

    sig.started.emit.assert_called_once()
    sig.finished.emit.assert_called_once()
    sig.failed.emit.assert_not_called()
    # The finished.emit args should be (url, item)
    args = sig.finished.emit.call_args.args
    assert args[0] == "https://www.bilibili.com/video/BV1xx"
    assert isinstance(args[1], MediaItem)


def test_download_worker_emits_failed_when_no_match(monkeypatch, tmp_path):
    """Worker.run() should call started → failed when parse returns None."""
    from doubi.core.pipeline import DownloadPipeline

    class _StubEngine:
        name = "stub"
        def supports(self, item): return True
        async def download(self, item, options, *, on_progress=None):
            return True

    pipeline = DownloadPipeline(engine=_StubEngine())
    worker = DownloadWorker(
        url="https://example.com/unknown",
        options=DownloadOptions(output_root=tmp_path),
        pipeline=pipeline,
    )
    sig = MagicMock()
    sig.started = MagicMock()
    sig.progress = MagicMock()
    sig.finished = MagicMock()
    sig.failed = MagicMock()
    worker.signals = sig

    async def _parse(url): return None
    monkeypatch.setattr(pipeline, "parse", _parse)

    asyncio.run(worker.run())

    sig.started.emit.assert_called_once()
    sig.failed.emit.assert_called_once()
    sig.finished.emit.assert_not_called()
    # failed.emit args: (url, message)
    args = sig.failed.emit.call_args.args
    assert "no platform" in args[1] or "parse" in args[1]


def test_download_worker_emits_progress_during_download(monkeypatch, tmp_path):
    """Worker forwards pipeline progress events to the progress signal."""
    from doubi.core.pipeline import DownloadPipeline, ProgressEvent

    class _StubEngine:
        name = "stub"
        def supports(self, item): return True
        async def download(self, item, options, *, on_progress=None):
            if on_progress is not None:
                on_progress(ProgressEvent(
                    job_id="j", item=item, phase="downloading",
                    fraction=0.42, message="42%",
                ))
            return True

    pipeline = DownloadPipeline(engine=_StubEngine())
    worker = DownloadWorker(
        url="https://www.douyin.com/video/123",
        options=DownloadOptions(output_root=tmp_path),
        pipeline=pipeline,
    )
    sig = MagicMock()
    sig.started = MagicMock()
    sig.progress = MagicMock()
    sig.finished = MagicMock()
    sig.failed = MagicMock()
    worker.signals = sig

    async def _parse(url):
        return MediaItem(
            platform=Platform.DOUYIN, item_id="123", title="x",
            author=Author(), media_type=MediaType.VIDEO, source_url=url,
        )
    monkeypatch.setattr(pipeline, "parse", _parse)

    asyncio.run(worker.run())

    # The pipeline emits multiple progress events (starting, downloading, done).
    # Check that our 42% event is in the call list.
    fractions = [call.args[1].fraction for call in sig.progress.emit.call_args_list]
    assert 0.42 in fractions, f"expected 0.42 in {fractions}"
    # And the URL is the first arg of every call
    urls = [call.args[0] for call in sig.progress.emit.call_args_list]
    assert all(u == "https://www.douyin.com/video/123" for u in urls)


def test_download_worker_emits_failed_on_exception(monkeypatch, tmp_path):
    """If the pipeline raises, the worker emits failed with the error message."""
    from doubi.core.pipeline import DownloadPipeline

    pipeline = DownloadPipeline(engine=MagicMock())
    worker = DownloadWorker(
        url="https://x",
        options=DownloadOptions(output_root=tmp_path),
        pipeline=pipeline,
    )
    sig = MagicMock()
    sig.started = MagicMock()
    sig.progress = MagicMock()
    sig.finished = MagicMock()
    sig.failed = MagicMock()
    worker.signals = sig

    async def _bad_parse(url):
        raise RuntimeError("kaboom")
    monkeypatch.setattr(pipeline, "parse", _bad_parse)

    asyncio.run(worker.run())

    sig.failed.emit.assert_called_once()
    args = sig.failed.emit.call_args.args
    assert args[0] == "https://x"
    assert "kaboom" in args[1]


# ---------------------------------------------------------------------------
# main_window / app import surface
# ---------------------------------------------------------------------------


def test_main_window_import_does_not_crash_when_gui_missing():
    """Importing the main_window module should be safe (deferred to runtime)."""
    # If PySide6 is missing, just importing the module shouldn't fail
    # (the import errors are inside build_main_window).
    from doubi.ui import main_window
    assert hasattr(main_window, "build_main_window")


def test_app_main_with_no_gui_exits_cleanly(monkeypatch):
    """`main()` should raise GUIUnavailableError when PySide6 is missing."""
    if _has_pyside6():
        pytest.skip("PySide6 is installed; cannot test missing-deps path")
    from doubi.ui.app import main
    with pytest.raises(GUIUnavailableError, match="pip install"):
        main([])
