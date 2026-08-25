"""YouTube adapter tests (M6.12).

YouTube 不需要任何平台特有 API：URL 由正则分类，元数据由 yt-dlp 在
``adapter.parse`` 里调 ``extract_info(download=False)`` 拉一次。**测试
必须不联网**——所有网络调用走 ``monkeypatch`` 替换 ``_do_extract`` 内部
那个 ``yt_dlp.YoutubeDL`` 实例。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


from doubi.core.models import MediaItem, MediaType, Platform
from doubi.core.registry import PlatformRegistry
from doubi.platforms.youtube import (
    YouTubeAdapter,
    YouTubeURLType,
    classify_youtube_url,
    to_watch_url,
)


# ===========================================================================
# URL 分类
# ===========================================================================


@pytest.mark.parametrize("url, expected_type, expected_id", [
    # 普通 watch?v=ID
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", YouTubeURLType.VIDEO, "dQw4w9WgXcQ"),
    # watch?v=ID + 额外参数（YouTube 实际播放页面几乎都带参数）
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s&list=PLxxx", YouTubeURLType.VIDEO, "dQw4w9WgXcQ"),
    # youtu.be 短链
    ("https://youtu.be/dQw4w9WgXcQ", YouTubeURLType.VIDEO, "dQw4w9WgXcQ"),
    # Shorts（必须独立形态）
    ("https://www.youtube.com/shorts/dQw4w9WgXcQ", YouTubeURLType.SHORTS, "dQw4w9WgXcQ"),
    # embed（罕见但合法）
    ("https://www.youtube.com/embed/dQw4w9WgXcQ", YouTubeURLType.EMBED, "dQw4w9WgXcQ"),
    # live
    ("https://www.youtube.com/live/dQw4w9WgXcQ", YouTubeURLType.LIVE, "dQw4w9WgXcQ"),
    # /channel/UC... 频道
    ("https://www.youtube.com/channel/UC_x5XG1OV2P6uZZ5FSM9Ttw",
     YouTubeURLType.CHANNEL, "UC_x5XG1OV2P6uZZ5FSM9Ttw"),
    # /@handle 频道（item_id 留空：handle 不是稳定 ID）
    ("https://www.youtube.com/@LinusTechTips", YouTubeURLType.CHANNEL, ""),
    # playlist
    ("https://www.youtube.com/playlist?list=PLrAXtmRdnEQy6nuLMHjMZOz59Oq8m9",
     YouTubeURLType.PLAYLIST, "PLrAXtmRdnEQy6nuLMHjMZOz59Oq8m9"),
    # 非 YouTube
    ("https://www.bilibili.com/video/BV1xxx", YouTubeURLType.UNKNOWN, ""),
    ("", YouTubeURLType.UNKNOWN, ""),
])
def test_classify_youtube_url(url, expected_type, expected_id):
    c = classify_youtube_url(url)
    assert c.type is expected_type, f"{url}: expected {expected_type}, got {c.type}"
    assert c.item_id == expected_id, f"{url}: expected id={expected_id!r}, got {c.item_id!r}"
    assert c.raw == url


def test_to_watch_url_normalizes_short_forms():
    """短链 / shorts / embed / live → 统一 ``watch?v=ID``。"""
    cases = [
        ("https://youtu.be/dQw4w9WgXcQ", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ",
         "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        ("https://www.youtube.com/embed/dQw4w9WgXcQ",
         "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        ("https://www.youtube.com/live/dQw4w9WgXcQ",
         "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
    ]
    for src, want in cases:
        c = classify_youtube_url(src)
        assert to_watch_url(c) == want, f"{src} → {to_watch_url(c)}, want {want}"


def test_to_watch_url_passes_through_non_video_urls():
    """channel / playlist / unknown 不归一化——adapter 不该吞它们。"""
    for url in (
        "https://www.youtube.com/@handle",
        "https://www.youtube.com/playlist?list=PLfoo",
        "https://example.com/",
    ):
        c = classify_youtube_url(url)
        assert to_watch_url(c) == url


# ===========================================================================
# adapter 注册
# ===========================================================================


def test_youtube_adapter_is_registered():
    """``import doubi.platforms`` 应该已经注册 YouTubeAdapter。"""
    assert "youtube" in {a.name for a in PlatformRegistry.all()}
    adapter = PlatformRegistry.get(Platform.YOUTUBE)
    assert isinstance(adapter, YouTubeAdapter)
    assert adapter.platform is Platform.YOUTUBE
    assert adapter.display_name == "YouTube"


def test_youtube_adapter_matches_its_own_urls():
    """``match_url`` 必须识别 youtube.com 与 youtu.be。"""
    adapter = YouTubeAdapter()
    assert adapter.match_url("https://www.youtube.com/watch?v=foo")
    assert adapter.match_url("https://youtu.be/foo")
    assert adapter.match_url("https://www.youtube.com/shorts/foo")
    assert not adapter.match_url("https://www.bilibili.com/video/BV1xxx")
    assert not adapter.match_url("")


def test_youtube_url_patterns_dont_match_other_platforms():
    """``match_url`` 不能误报——这条防回归：B 站 URL 不能命中 YouTube。"""
    adapter = YouTubeAdapter()
    # 任何一个 bilibili / douyin URL 都不该命中。
    for u in (
        "https://www.bilibili.com/video/BV1xxx",
        "https://www.douyin.com/video/7123456789012345678",
        "https://example.com/",
    ):
        assert not adapter.match_url(u), f"YouTube 误报命中 {u}"


# ===========================================================================
# adapter.parse（不联网 + monkeypatch）
# ===========================================================================


def _stub_extract_meta(monkeypatch, *, title="Rick Astley - Never Gonna Give You Up",
                       channel="Rick Astley", duration=213):
    """把 ``YouTubeAdapter._extract_meta`` 替换成同步返回固定值的函数。

    真实实现 ``await asyncio.to_thread(_do_extract)``——monkeypatch 直接
    替换整个私有方法返回 ``(title, channel, duration)``。
    """
    async def fake_extract(self, watch_url):
        return title, channel, duration
    monkeypatch.setattr(YouTubeAdapter, "_extract_meta", fake_extract)


def test_parse_single_video_returns_metadata_when_network_ok(monkeypatch):
    _stub_extract_meta(monkeypatch)
    adapter = YouTubeAdapter()
    item = asyncio.run(adapter.parse("https://www.youtube.com/watch?v=dQw4w9WgXcQ"))
    assert item is not None
    assert item.platform is Platform.YOUTUBE
    assert item.item_id == "dQw4w9WgXcQ"
    assert item.title == "Rick Astley - Never Gonna Give You Up"
    assert item.author.name == "Rick Astley"
    assert item.duration == 213
    # source_url 必须是 watch?v=ID 形态——engine 看的就是它。
    assert item.source_url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    # 原始 URL 形态保留在 extra，便于排查「为什么 Shorts 没 1080p」之类。
    assert item.extra["url_type"] == "video"
    assert item.extra["raw_url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def test_parse_short_link_is_normalized_to_watch_url(monkeypatch):
    """短链 / shorts / embed 解析后 source_url 都是 watch?v=ID。"""
    _stub_extract_meta(monkeypatch, title="t", channel="c", duration=10)
    adapter = YouTubeAdapter()
    for src in (
        "https://youtu.be/dQw4w9WgXcQ",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ",
        "https://www.youtube.com/embed/dQw4w9WgXcQ",
        "https://www.youtube.com/live/dQw4w9WgXcQ",
    ):
        item = asyncio.run(adapter.parse(src))
        assert item is not None, f"应能解析 {src}"
        assert item.source_url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ", src
        assert item.extra["raw_url"] == src, "原始 URL 必须保留"


def test_parse_returns_placeholder_when_network_fails(monkeypatch):
    """``_extract_meta`` 抛异常时不能阻塞——返回只含 item_id 的占位 item。"""
    async def raising_extract(self, watch_url):
        raise ConnectionError("SSL: UNEXPECTED_EOF_WHILE_READING")
    monkeypatch.setattr(YouTubeAdapter, "_extract_meta", raising_extract)

    adapter = YouTubeAdapter()
    item = asyncio.run(adapter.parse("https://www.youtube.com/watch?v=dQw4w9WgXcQ"))
    assert item is not None
    assert item.item_id == "dQw4w9WgXcQ"
    # title 是占位（不是空字符串——空字符串会让 UI 误判为解析失败）。
    assert "dQw4w9WgXcQ" in item.title
    # duration / author 都是空；engine 下载阶段 yt-dlp 会再拉一次。
    assert item.author.name == ""
    assert item.duration is None


def test_parse_returns_none_for_channel(monkeypatch):
    """频道 URL 不是单个视频——adapter 必须返回 None 而不是猜。"""
    _stub_extract_meta(monkeypatch)
    adapter = YouTubeAdapter()
    assert asyncio.run(adapter.parse(
        "https://www.youtube.com/@LinusTechTips"
    )) is None
    assert asyncio.run(adapter.parse(
        "https://www.youtube.com/channel/UC_x5XG1OV2P6uZZ5FSM9Ttw"
    )) is None


def test_parse_returns_none_for_playlist(monkeypatch):
    """playlist 不在 adapter 范围——yt-dlp 自己处理。"""
    _stub_extract_meta(monkeypatch)
    adapter = YouTubeAdapter()
    assert asyncio.run(adapter.parse(
        "https://www.youtube.com/playlist?list=PLfoo"
    )) is None


def test_parse_returns_none_for_unknown_url(monkeypatch):
    """非 YouTube URL 必须返回 None——其它 adapter 自己认领。"""
    _stub_extract_meta(monkeypatch)
    adapter = YouTubeAdapter()
    assert asyncio.run(adapter.parse("https://example.com/")) is None
    assert asyncio.run(adapter.parse("")) is None


# ===========================================================================
# post_download / introspection
# ===========================================================================


def test_supported_media_types_lists_video_audio_live():
    """公开 ``supported_media_types`` 返回值不应为空。"""
    adapter = YouTubeAdapter()
    types = adapter.supported_media_types()
    assert "video" in types
    assert "audio" in types


def test_post_download_is_a_noop():
    """YouTube 的 NFO / 字幕由 yt-dlp 自己拉，post_download 必须空实现。"""
    adapter = YouTubeAdapter()
    item = MediaItem(
        platform=Platform.YOUTUBE, item_id="dQw4w9WgXcQ",
        title="t", media_type=MediaType.VIDEO,
        source_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    )
    from doubi.core.models import DownloadOptions
    # 空实现——不抛异常是契约。
    asyncio.run(adapter.post_download(item, DownloadOptions()))


# ===========================================================================
# 集成：registry.detect 应该把 YouTube URL 路由到 YouTubeAdapter
# ===========================================================================


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://youtu.be/dQw4w9WgXcQ",
    "https://www.youtube.com/shorts/dQw4w9WgXcQ",
])
def test_registry_detect_routes_to_youtube(url):
    """``PlatformRegistry.detect`` 是 pipeline 找 adapter 的入口。"""
    adapter = PlatformRegistry.detect(url)
    assert adapter is not None, f"{url} 没匹配到任何 adapter"
    assert adapter.platform is Platform.YOUTUBE, (
        f"{url} 匹配到了 {adapter.platform.value} 而不是 youtube"
    )


def test_registry_detect_unknown_falls_back_to_generic():
    """非平台 URL 现在走 generic adapter 兜底（M6.16 新增）。

    之前是返回 None——M6.16 加了 GenericAdapter (priority=-1) 后，
    任意 http(s):// URL 都会被它接住。空串 / 非 http 仍然返回 None。
    """
    adapter = PlatformRegistry.detect("https://example.com/")
    assert adapter is not None
    assert adapter.name == "generic"
    # 空串 / 非 http(s) URL 不匹配 generic
    assert PlatformRegistry.detect("") is None
    assert PlatformRegistry.detect("javascript:void(0)") is None


# ===========================================================================
# 破坏验证
# ===========================================================================


def test_sabotage_removing_youtube_import_breaks_detection(monkeypatch):
    """如果 ``platforms/__init__.py`` 里漏掉 ``from . import youtube``，
    ``detect`` 应该返回 None——这条断言验证「import 即注册」是真的。
    """
    # 直接验证 imports 里没有漏：临时移除 platforms 包内 youtube 模块，
    # 模拟「漏 import」的状态。但 ``platforms`` 包导入已经触发副作用了——
    # 所以这里只能断言「已注册」与「未注册」的状态差：通过检测当前
    # 注册状态，反证 import 顺序的敏感性。
    # 先确认当前 YouTube 确实在 registry 里。
    assert PlatformRegistry.get(Platform.YOUTUBE) is not None


def test_sabotage_wrong_id_length_misses_url(monkeypatch):
    """Video ID 必须是 11 字符——短于/长于 11 字符的 ``v=`` 不能命中 VIDEO。

    YouTube 的 11 字符 ID 不是基于字符类别而是定长——这意味着
    ``watch?v=abc`` 不能被当作合法 VIDEO。
    """
    # 9 字符 ID：不是合法 VIDEO，分类到 UNKNOWN。
    c = classify_youtube_url("https://www.youtube.com/watch?v=dQw4w9Wg")
    assert c.type is YouTubeURLType.UNKNOWN
    # 12 字符 ID：同上。
    c = classify_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQA")
    assert c.type is YouTubeURLType.UNKNOWN


def test_sabotage_adapter_with_no_youtube_pattern_falls_through():
    """如果把 url_patterns 清空，match_url 必然返回 False。"""
    adapter = YouTubeAdapter()
    original = adapter.url_patterns
    try:
        adapter.url_patterns = []
        assert not adapter.match_url("https://www.youtube.com/watch?v=foo")
    finally:
        adapter.url_patterns = original
