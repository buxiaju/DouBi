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
import copy
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
    Author,
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


def _stub_adapter_parse(monkeypatch, **overrides):
    """把 ``PlatformRegistry.detect`` 命中的适配器换成不联网的桩。

    0.3.3 修：``test_pipeline_parse_*`` / ``..._uses_fake_engine`` 原先直接拿
    真实 URL 走 ``pipeline.parse``，而 ``parse`` 会调适配器的真 ``parse`` →
    yt-dlp → 真实网络。这些用例的本意只是验证「pipeline 正确路由到平台适配器、
    并把返回值透传」，跟网络上有没有这个视频毫无关系。网络通畅时它们靠真请求
    侥幸变绿，网络被黑洞时整轮全量跑就挂死在 ``/video/7123456789012345678``
    这种不存在的资源上。

    桩只替换 ``parse``，``platform`` / ``name`` / ``match_url`` 全部保留真值——
    断言仍然覆盖 registry 的路由与平台识别。
    """
    async def _fake_parse(url, *args, **kwargs):  # noqa: ARG001
        return _mk_item(url, **overrides)

    monkeypatch.setattr(PlatformRegistry, "detect", _detect_with_stub(_fake_parse))


def _detect_with_stub(fake_parse):
    real_detect = PlatformRegistry.detect

    def _detect(url, *args, **kwargs):
        adapter = real_detect(url, *args, **kwargs)
        if adapter is None:
            return None
        stub = copy.copy(adapter)
        stub.parse = fake_parse
        return stub

    return _detect


def _mk_item(url: str, **overrides) -> MediaItem:
    """按 URL 造一个「平台识别正确」的最小 MediaItem。"""
    from doubi.platforms.douyin.url import classify_douyin_url, DouyinURLType

    platform = Platform.DOUYIN if "douyin.com" in url else Platform.BILIBILI
    media_type = MediaType.VIDEO
    item_id = "unknown"

    if platform is Platform.DOUYIN:
        kind = classify_douyin_url(url)
        item_id = url.rstrip("/").rsplit("/", 1)[-1].split("?")[0]
        if kind is DouyinURLType.LIVE:
            media_type = MediaType.LIVE
    else:
        tail = url.rstrip("/").rsplit("/", 1)[-1].split("?")[0]
        item_id = tail
        if "/bangumi/" in url:
            media_type = MediaType.BANGUMI

    return MediaItem(
        platform=platform,
        item_id=item_id,
        title=f"stub:{item_id}",
        author=Author(id="stub", name="stub"),
        media_type=media_type,
        source_url=url,
        extra={"stubbed": True},
        **overrides,
    )


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


def test_registry_detect_unknown_falls_back_to_ytdlp_generic():
    """不认识的 URL 现在先走 ytdlp_generic（M6.17+），generic 是更下一层兜底。

    兜底链：具体平台 (priority=0) → ytdlp_generic (priority=-1) → generic
    (priority=-2)。``https://example.com/something`` 没有具体平台匹配，
    ytdlp_generic 第一个命中（match_url 永真）。
    """
    adapter = PlatformRegistry.detect("https://example.com/something")
    assert adapter is not None
    assert adapter.name == "ytdlp", (
        f"M6.17+ 未知 URL 应优先匹配 ytdlp_generic，实际 {adapter.name}"
    )


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


def test_classify_douyin_collection_no_seq():
    """``/collection/{mix_id}`` → COLLECTION + seq=None（整个合集）。"""
    c = classify_douyin_url("https://www.douyin.com/collection/7663019958858680347")
    assert c.type is DouyinURLType.COLLECTION
    assert c.item_id == "7663019958858680347"
    assert c.seq is None


def test_classify_douyin_collection_with_seq():
    """``/collection/{mix_id}/{seq}`` → COLLECTION + seq=int（M6.45+）。

    seq 后缀是抖音 web 选中合集里某条视频时复制出来的链接，原 M6.17
    实现把它当纯 collection URL，``seq`` 静默吞掉 → adapter 把整个
    合集当单条任务。修：``ClassifiedURL.seq`` 捕获，``adapter.parse``
    据此切单条 / MIX 容器两种模式。
    """
    c = classify_douyin_url("https://www.douyin.com/collection/7663019958858680347/1")
    assert c.type is DouyinURLType.COLLECTION
    assert c.item_id == "7663019958858680347"
    assert c.seq == 1

    c2 = classify_douyin_url("https://www.douyin.com/collection/7663019958858680347/42")
    assert c2.item_id == "7663019958858680347"
    assert c2.seq == 42

    c3 = classify_douyin_url("https://www.douyin.com/collection/7663019958858680347/3?from=share")
    assert c3.seq == 3


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


def test_pipeline_parse_douyin(monkeypatch):
    _stub_adapter_parse(monkeypatch)
    pipeline = DownloadPipeline(engine=_FakeEngine())
    item = asyncio.run(pipeline.parse("https://www.douyin.com/video/7123456789012345678"))
    assert item is not None
    assert item.platform is Platform.DOUYIN
    assert item.item_id == "7123456789012345678"
    assert item.media_type is MediaType.VIDEO
    assert item.source_url.startswith("https://www.douyin.com/")


def test_pipeline_parse_bilibili_bvid(monkeypatch):
    _stub_adapter_parse(monkeypatch)
    pipeline = DownloadPipeline(engine=_FakeEngine())
    item = asyncio.run(pipeline.parse("https://www.bilibili.com/video/BV1xx411c7mD"))
    assert item is not None
    assert item.platform is Platform.BILIBILI
    assert item.item_id.startswith("BV")
    assert item.media_type is MediaType.VIDEO


def test_pipeline_parse_bilibili_bangumi(monkeypatch):
    _stub_adapter_parse(monkeypatch)
    pipeline = DownloadPipeline(engine=_FakeEngine())
    item = asyncio.run(pipeline.parse("https://www.bilibili.com/bangumi/play/ss12345"))
    assert item is not None
    assert item.media_type is MediaType.BANGUMI
    assert item.item_id == "ss12345"


def test_pipeline_process_url_unknown_returns_none_ytdlp_failed(monkeypatch):
    """M6.17+ 兜底链变更：不认识的 URL 先走 ytdlp_generic（priority=-1），

    yt-dlp 解析失败时返回 ``None``——pipeline 不再自动 chain 到 generic
    嗅探（那条路径需要用户主动触发，例如 CLI ``--force-sniff``）。

    行为变化：

    * M6.16: registry.detect → generic → sniff 失败 → 错误 MediaItem
    * M6.17+: registry.detect → ytdlp_generic → yt-dlp DownloadError → ``None``

    0.3.3 修：本用例原先直接拿 ``https://example.com/something`` 去跑，靠
    真实网络请求报错来凑出 ``None``。网络被黑洞时整个全量跑挂死在这里，
    而且绿灯与否取决于当时能不能连上 example.com。这里把 yt-dlp 本身换成
    「一进 with 就抛 DownloadError」的桩，把断言落回它真正想验证的那条
    链路（yt-dlp 失败 → adapter 返回 None → pipeline 透传）。
    """
    import yt_dlp

    class _BoomYDL:
        def __init__(self, opts):        # noqa: ARG002 - 对齐真实签名即可
            pass

        def __enter__(self):
            raise yt_dlp.utils.DownloadError("simulated: 404 / 站点不存在")

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(yt_dlp, "YoutubeDL", _BoomYDL)

    pipeline = DownloadPipeline(engine=_FakeEngine())
    item = asyncio.run(pipeline.process_url(
        "https://example.com/something",
        DownloadOptions(output_root=Path("./_test_out")),
    ))
    # ytdlp_generic 解析 ``https://example.com/something`` 时 yt-dlp 抛
    # DownloadError（404 / 站点不存在）→ adapter 返回 None → pipeline 透传。
    assert item is None


def test_generic_adapter_parse_returns_sniff_error_item(monkeypatch):
    """保留 M6.16 的 sniff 错误 item 路径——直接测 GenericAdapter。

    M6.17 之后 pipeline.process_url 不再自动走 generic，但 GenericAdapter
    本身仍然返回 sniff 错误 item（用户可主动调，或 CLI ``--force-sniff`` 触发）。

    0.3.3 修：本用例原先放真浏览器去嗅探 ``https://example.com/something``，
    固定烧掉 ~26s（全量 local 口径里 `--durations` 的头号大户），且依赖网络与
    本机 Playwright。断言关心的只是「嗅探失败 ⇒ 返回带 sniff_error 的错误
    item」，所以把 ``Sniffer.sniff`` 换成「返回带 error 的结果」——正是生产
    代码里 Playwright 缺失 / 超时 / 0 个 URL 的形态。
    """
    from doubi.core.sniffer import SniffResult, Sniffer
    from doubi.platforms.generic import GenericAdapter

    async def _no_urls(self, url, *args, **kwargs):  # noqa: ARG001
        # 与真实嗅探失败同形：items 空 + error 有值，但拿到页面标题。
        return SniffResult(
            page_url=url,
            page_title="Example Domain",
            items=[],
            error="simulated: 未嗅探到任何视频 URL",
        )

    monkeypatch.setattr(Sniffer, "sniff", _no_urls)

    adapter = GenericAdapter()
    item = asyncio.run(adapter.parse("https://example.com/something"))
    assert item is not None
    assert item.platform is Platform.GENERIC
    assert "嗅探失败" in item.title or "嗅探" in item.title
    assert "sniff_error" in item.extra or "sniffed_from" in item.extra


def test_pipeline_process_url_uses_fake_engine(monkeypatch):
    _stub_adapter_parse(monkeypatch)
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
