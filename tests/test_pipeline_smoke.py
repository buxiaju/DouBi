"""Smoke tests for the M1 skeleton.

These tests cover:
    * Registry registration of built-in adapters
    * URL pattern matching for Douyin and Bilibili
    * URL classification for Douyin
    * Short URL resolution (skipped if no network)
    * Pipeline parse step (no actual download)
    * End-to-end CLI `--help` and `platforms` subcommand
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

# Make `src/` importable when running pytest from the repo root.
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Import after path adjustment
from doubi.core.models import (  # noqa: E402
    MediaItem,
    MediaType,
    Platform,
    Stream,
    DownloadOptions,
)
from doubi.core.registry import PlatformRegistry  # noqa: E402
from doubi.core.pipeline import DownloadPipeline, ProgressEvent  # noqa: E402
from doubi.engines.base import Engine, EngineProgress  # noqa: E402
from doubi.platforms.douyin.url import (  # noqa: E402
    DouyinURLType,
    classify_douyin_url,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _ensure_adapters_loaded():
    """Make sure platform adapters are registered.

    The `doubi.platforms` package triggers registration on import. We
    import the platforms package once so registry tests have something
    to inspect even if a future refactor breaks that side effect.
    """
    import doubi.platforms  # noqa: F401
    yield


class _FakeEngine(Engine):
    """Engine that records calls and pretends to succeed."""

    name = "fake"
    supports_calls: list = []
    download_calls: list = []

    def supports(self, item: MediaItem) -> bool:
        _FakeEngine.supports_calls.append(item)
        return True

    async def download(self, item, options, *, on_progress=None):
        _FakeEngine.download_calls.append((item, options))
        if on_progress is not None:
            on_progress(EngineProgress(fraction=0.5, message="halfway"))
            on_progress(EngineProgress(fraction=1.0, message="done"))
        return True


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_registry_contains_douyin_and_bilibili():
    platforms = {a.platform for a in PlatformRegistry.all()}
    assert Platform.DOUYIN in platforms
    assert Platform.BILIBILI in platforms


def test_registry_get_by_name_and_platform():
    a = PlatformRegistry.get(Platform.DOUYIN)
    assert a.name == "douyin"
    b = PlatformRegistry.get_by_name("bilibili")
    assert b.platform is Platform.BILIBILI


def test_registry_detect_douyin():
    adapter = PlatformRegistry.detect("https://www.douyin.com/video/7123456789012345678")
    assert adapter is not None
    assert adapter.platform is Platform.DOUYIN


def test_registry_detect_bilibili():
    adapter = PlatformRegistry.detect("https://www.bilibili.com/video/BV1xx411c7mD")
    assert adapter is not None
    assert adapter.platform is Platform.BILIBILI


def test_registry_detect_unknown_returns_none():
    assert PlatformRegistry.detect("https://example.com/something") is None


# ---------------------------------------------------------------------------
# URL classification (Douyin)
# ---------------------------------------------------------------------------


def test_classify_douyin_video():
    c = classify_douyin_url("https://www.douyin.com/video/7123456789012345678")
    assert c.type is DouyinURLType.VIDEO
    assert c.item_id == "7123456789012345678"


def test_classify_douyin_note():
    c = classify_douyin_url("https://www.douyin.com/note/7341234567890123456")
    assert c.type is DouyinURLType.NOTE


def test_classify_douyin_user():
    c = classify_douyin_url("https://www.douyin.com/user/MS4wLjABAAAAxxxx?foo=bar")
    assert c.type is DouyinURLType.USER


def test_classify_douyin_short():
    c = classify_douyin_url("https://v.douyin.com/abcd1234/")
    assert c.type is DouyinURLType.SHORT


def test_classify_douyin_live():
    c = classify_douyin_url("https://live.douyin.com/123456789")
    assert c.type is DouyinURLType.LIVE


def test_classify_douyin_unknown():
    c = classify_douyin_url("https://example.com/foo")
    assert c.type is DouyinURLType.UNKNOWN
    assert c.item_id == ""


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def test_pipeline_parse_douyin():
    pipeline = DownloadPipeline(engine=_FakeEngine())
    item = asyncio.run(pipeline.parse("https://www.douyin.com/video/7123456789012345678"))
    assert item is not None
    assert item.platform is Platform.DOUYIN
    assert item.item_id == "7123456789012345678"
    assert item.media_type is MediaType.VIDEO
    assert item.source_url.startswith("https://www.douyin.com/")


def test_pipeline_parse_bilibili_bvid():
    pipeline = DownloadPipeline(engine=_FakeEngine())
    item = asyncio.run(pipeline.parse("https://www.bilibili.com/video/BV1xx411c7mD"))
    assert item is not None
    assert item.platform is Platform.BILIBILI
    assert item.item_id.startswith("BV")
    assert item.media_type is MediaType.VIDEO


def test_pipeline_parse_bilibili_bangumi():
    pipeline = DownloadPipeline(engine=_FakeEngine())
    item = asyncio.run(pipeline.parse("https://www.bilibili.com/bangumi/play/ss12345"))
    assert item is not None
    assert item.media_type is MediaType.BANGUMI
    assert item.item_id == "ss12345"


def test_pipeline_process_url_unknown_returns_none():
    pipeline = DownloadPipeline(engine=_FakeEngine())
    item = asyncio.run(pipeline.process_url(
        "https://example.com/something",
        DownloadOptions(output_root=Path("./_test_out")),
    ))
    assert item is None


def test_pipeline_process_url_uses_fake_engine():
    _FakeEngine.download_calls = []
    pipeline = DownloadPipeline(engine=_FakeEngine(), max_concurrent=2)
    options = DownloadOptions(output_root=Path("./_test_out"))

    progress_events: list[ProgressEvent] = []
    item = asyncio.run(pipeline.process_url(
        "https://www.douyin.com/video/7123456789012345678",
        options,
        on_progress=progress_events.append,
    ))
    assert item is not None
    assert len(_FakeEngine.download_calls) == 1
    # 1 from process_url ("downloading") + 2 from fake engine ("halfway" + "done") + 1 final ("done")
    assert any(e.phase == "done" for e in progress_events)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_help(monkeypatch, capsys):
    """argparse calls SystemExit(0) on --help; accept that and check output."""
    from doubi.cli.main import main
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "doubi" in out.lower()
    assert "download" in out
    assert "platforms" in out


def test_cli_platforms(capsys):
    from doubi.cli.main import main
    rc = main(["platforms"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "douyin" in out
    assert "bilibili" in out
