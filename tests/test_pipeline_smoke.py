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


def test_classify_douyin_modal_id_feed_url():
    c = classify_douyin_url("https://www.douyin.com/jingxuan?modal_id=7676517073484352822")
    assert c.type is DouyinURLType.VIDEO
    assert c.item_id == "7676517073484352822"


def test_classify_douyin_modal_id_with_other_params():
    c = classify_douyin_url("https://www.douyin.com/discover?foo=1&modal_id=7676517073484352822")
    assert c.type is DouyinURLType.VIDEO
    assert c.item_id == "7676517073484352822"


def test_registry_detect_douyin_modal_id():
    adapter = PlatformRegistry.detect("https://www.douyin.com/jingxuan?modal_id=7676517073484352822")
    assert adapter is not None
    assert adapter.platform is Platform.DOUYIN


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


# ---------------------------------------------------------------------------
# Per-item cookie injection (yt-dlp needs s_v_web_id / sessionid etc.)
# ---------------------------------------------------------------------------


def _make_douyin_item() -> MediaItem:
    return MediaItem(
        platform=Platform.DOUYIN,
        item_id="7676517073484352822",
        title="cookie injection test",
        media_type=MediaType.VIDEO,
        source_url="https://www.douyin.com/video/7676517073484352822",
    )


def test_pipeline_injects_platform_cookie_file(monkeypatch, tmp_path):
    """Engine must receive the platform cookie file when the caller
    did not pin one — otherwise yt-dlp fails with "Fresh cookies
    (not necessarily logged in) are needed" on every Douyin download."""
    cookie_file = tmp_path / "douyin.txt"
    cookie_file.write_text(
        "# Netscape HTTP Cookie File\n"
        ".douyin.com\tTRUE\t/\tTRUE\t1999999999\ts_v_web_id\tverify_x\n"
    )
    monkeypatch.setenv("DOUBI_DOUYIN_COOKIES", str(cookie_file))

    _FakeEngine.download_calls = []
    pipeline = DownloadPipeline(engine=_FakeEngine())
    options = DownloadOptions(output_root=tmp_path / "out")
    ok = asyncio.run(pipeline._download_with_progress(
        _make_douyin_item(), options, None, "job0001",
    ))
    assert ok is True
    assert len(_FakeEngine.download_calls) == 1
    _, engine_opts = _FakeEngine.download_calls[0]
    assert engine_opts.cookies_file == cookie_file
    # the caller's options bag must stay untouched
    assert options.cookies_file is None


def test_pipeline_respects_explicit_cookie_file(monkeypatch, tmp_path):
    """An explicitly pinned cookies_file wins over platform resolution."""
    explicit = tmp_path / "explicit.txt"
    explicit.write_text("# pinned\n")

    platform_cookie = tmp_path / "douyin.txt"
    platform_cookie.write_text(
        "# Netscape HTTP Cookie File\n"
        ".douyin.com\tTRUE\t/\tTRUE\t1999999999\ts_v_web_id\tverify_x\n"
    )
    monkeypatch.setenv("DOUBI_DOUYIN_COOKIES", str(platform_cookie))

    _FakeEngine.download_calls = []
    pipeline = DownloadPipeline(engine=_FakeEngine())
    options = DownloadOptions(output_root=tmp_path / "out", cookies_file=explicit)
    ok = asyncio.run(pipeline._download_with_progress(
        _make_douyin_item(), options, None, "job0002",
    ))
    assert ok is True
    _, engine_opts = _FakeEngine.download_calls[0]
    assert engine_opts.cookies_file == explicit


def test_pipeline_no_cookie_file_stays_none(monkeypatch, tmp_path):
    """No persisted cookie file -> engine still gets cookies_file=None
    (never crashes, never fabricates a path)."""
    monkeypatch.setenv("DOUBI_DOUYIN_COOKIES", str(tmp_path / "missing.txt"))

    _FakeEngine.download_calls = []
    pipeline = DownloadPipeline(engine=_FakeEngine())
    options = DownloadOptions(output_root=tmp_path / "out")
    ok = asyncio.run(pipeline._download_with_progress(
        _make_douyin_item(), options, None, "job0003",
    ))
    assert ok is True
    _, engine_opts = _FakeEngine.download_calls[0]
    assert engine_opts.cookies_file is None


# ---------------------------------------------------------------------------
# User-page modal links (video opened from a profile's compilation tab)
# ---------------------------------------------------------------------------


def test_classify_douyin_user_modal_id_is_video():
    """A user-profile URL carrying modal_id points at ONE video (opened
    from the 合集/compilation tab), not at the user's post list."""
    c = classify_douyin_url(
        "https://www.douyin.com/user/MS4wLjABAAAAxOhRVmiuLmYd089wiv1NYCyMXrJWG-qY3AwNDUDlTun9-9YScGFs0q1T70UnNosh"
        "?from_tab_name=main&modal_id=7647081804364516651&relation=0&showSubTab=compilation&vid=7647081804364516651"
    )
    assert c.type is DouyinURLType.VIDEO
    assert c.item_id == "7647081804364516651"


def test_classify_douyin_user_vid_only_is_video():
    """Compilation share variants that carry only vid= (no modal_id)
    must still classify as the single video."""
    c = classify_douyin_url(
        "https://www.douyin.com/user/MS4wLjABAAAAxxxx?from_tab_name=main&vid=7647081804364516651"
    )
    assert c.type is DouyinURLType.VIDEO
    assert c.item_id == "7647081804364516651"


def test_classify_douyin_user_without_modal_stays_user():
    """A plain profile URL (with or without query) must NOT be turned
    into a video — it should still expand the user's post list."""
    c = classify_douyin_url("https://www.douyin.com/user/MS4wLjABAAAAxxxx?showTab=post")
    assert c.type is DouyinURLType.USER
    assert c.item_id == "MS4wLjABAAAAxxxx"


def test_registry_detect_douyin_user_modal_id():
    adapter = PlatformRegistry.detect(
        "https://www.douyin.com/user/MS4wLjABAAAAxxxx?modal_id=7647081804364516651"
    )
    assert adapter is not None
    assert adapter.platform is Platform.DOUYIN


# ---------------------------------------------------------------------------
# needs_expansion 收敛（容器判定单一真源）
# ---------------------------------------------------------------------------


def test_needs_expansion_children_present():
    """children 已挂的容器（favlist / section）两个判据都应命中。"""
    parent = MediaItem(platform=Platform.BILIBILI, item_id="ml123", title="fav",
                       media_type=MediaType.FAVLIST)
    parent.children.append(
        MediaItem(platform=Platform.BILIBILI, item_id="BV1xx411c7mD", title="child"))
    assert parent.is_container()
    assert parent.needs_expansion()


def test_needs_expansion_mix_without_children():
    """抖音 MIX 容器解析时刻意不填 children -- is_container() 是 False，
    但 pipeline 必须走 expand。这正是 needs_expansion 存在的理由。"""
    item = MediaItem(platform=Platform.DOUYIN, item_id="712345", title="mix",
                     media_type=MediaType.MIX)
    assert not item.is_container()
    assert item.needs_expansion()


def test_needs_expansion_user_without_children():
    item = MediaItem(platform=Platform.DOUYIN, item_id="MS4wLj", title="u",
                     media_type=MediaType.USER)
    assert not item.is_container()
    assert item.needs_expansion()


def test_needs_expansion_single_video_false():
    item = MediaItem(platform=Platform.BILIBILI, item_id="BV1xx411c7mD", title="v")
    assert not item.is_container()
    assert not item.needs_expansion()


def test_pipeline_source_has_no_inline_container_check():
    """结构性守卫：pipeline 不得再出现 ``media_type in (MediaType.USER, ...)``
    的手写判定 -- 三处调用点历史上正是靠「同步三处」的口头约定维持，
    曾经因为只改了一处而漏修（M6.7 顺带修复 LIST 合集同类判定）。
    想改判定规则只能改 ``MediaItem.needs_expansion``。"""
    import doubi.core.pipeline as pipeline_mod
    src = Path(pipeline_mod.__file__).read_text(encoding="utf-8")
    assert "media_type in (MediaType.USER" not in src, (
        "pipeline.py 里出现了内联容器判定；请改用 MediaItem.needs_expansion()"
    )
    # 收敛后的三处调用点必须还在（防止有人把守卫整个删掉）
    assert src.count("needs_expansion()") >= 3
