"""YtDlpGenericAdapter tests (M6.17).

适配器本身很简单——大部分工作是 :func:`yt_dlp.YoutubeDL.extract_info` 完成的。
**测试必须不联网**：所有网络调用走 ``monkeypatch`` 替换
``_do_extract_thread``，它只是 ``asyncio.to_thread`` 的薄包装，单点替换
就能注入任意 fake info dict（单条 / playlist / 抛异常）。

兜底链契约（registry priority）：

* 具体平台 (priority=0) — douyin / bilibili / youtube
* ytdlp_generic (priority=-1) — 本文主角
* generic (priority=-2) — Playwright 嗅探兜底

也覆盖 ``strategies.py`` 的字段归一化逻辑（不同 extractor 的字段名差异）。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


from doubi.core.models import MediaItem, MediaType, Platform
from doubi.core.registry import PlatformRegistry
from doubi.platforms.ytdlp_generic import YtDlpGenericAdapter
from doubi.platforms.ytdlp_generic import strategies


# ===========================================================================
# Helpers
# ===========================================================================


def _stub_extract(monkeypatch, info_or_exception):
    """把 ``_do_extract_thread`` 替换成同步返回固定值或抛异常的函数。

    ``info_or_exception`` 可以是 ``dict``（成功）或 ``Exception`` 实例
    （失败路径）。该函数本身就是 async 函数，直接返回（不调 to_thread），
    保持与真实实现相同的协程契约。
    """
    async def fake(fn):
        if isinstance(info_or_exception, BaseException):
            raise info_or_exception
        if isinstance(info_or_exception, dict):
            # 真实 _do_extract_thread 是 ``await asyncio.to_thread(fn)``，
            # fn 本身返回 dict。fake 直接返回 dict 即可。
            return info_or_exception
        return None
    monkeypatch.setattr(
        "doubi.platforms.ytdlp_generic.adapter._do_extract_thread",
        fake,
    )


def _video_info(**overrides) -> dict:
    """构造一个「长得像 yt-dlp 真实返回」的 video InfoDict。"""
    base = {
        "id": "abc123",
        "title": "Sample Video Title",
        "uploader": "Sample Uploader",
        "uploader_id": "@sample",
        "duration": 213.0,
        "timestamp": 1700000000,
        "view_count": 1000,
        "like_count": 42,
        "description": "Sample description text",
        "tags": ["sample", "test"],
        "thumbnails": [
            {"url": "https://example.com/thumb_small.jpg", "width": 320, "height": 180},
            {"url": "https://example.com/thumb_large.jpg", "width": 1280, "height": 720},
        ],
        "extractor": "SampleSite",
        "extractor_key": "samplesite",
        "formats": [{"vcodec": "h264", "acodec": "aac"}],
    }
    base.update(overrides)
    return base


def _playlist_info(*entries) -> dict:
    """构造 playlist InfoDict：_type='playlist' + entries list。"""
    return {
        "_type": "playlist",
        "id": "PL123",
        "title": "Sample Playlist",
        "uploader": "Curator",
        "entries": list(entries),
    }


def _flat_entry(id_: str, title: str, **extras) -> dict:
    return {"id": id_, "title": title, "url": f"https://example.com/v/{id_}", **extras}


# ===========================================================================
# Registry / match_url
# ===========================================================================


class TestRegistryPriority:
    """ytdlp_generic 必须插在「具体平台 (priority=0)」与「generic (priority=-2)」之间。"""

    def test_priority_is_minus_one(self):
        adapter = YtDlpGenericAdapter()
        assert adapter.priority == -1

    def test_platform_enum_value(self):
        assert YtDlpGenericAdapter().platform is Platform.YT_DLP_GENERIC

    def test_match_url_accepts_any_http(self):
        adapter = YtDlpGenericAdapter()
        for u in (
            "https://twitter.com/user/status/123",
            "http://example.com/video",
            "https://vimeo.com/123456",
            "https://www.instagram.com/p/abc",
        ):
            assert adapter.match_url(u), f"应匹配 {u}"

    def test_match_url_rejects_empty_or_non_http(self):
        adapter = YtDlpGenericAdapter()
        for u in ("", "ftp://example.com", "about:blank", "javascript:void(0)"):
            assert not adapter.match_url(u), f"应拒绝 {u!r}"

    def test_concrete_platforms_still_wins(self):
        """YouTube / 抖音 / B 站 URL 仍然走具体平台，不是 ytdlp_generic。"""
        import doubi.platforms  # noqa: F401
        # 触发注册所有 adapter
        assert PlatformRegistry.detect(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        ).name == "youtube"
        assert PlatformRegistry.detect(
            "https://www.bilibili.com/video/BV1xxx",
        ).name == "bilibili"
        assert PlatformRegistry.detect(
            "https://www.douyin.com/video/7123456789012345678",
        ).name == "douyin"

    def test_unknown_url_falls_to_ytdlp_generic(self):
        """yt-dlp 认识的未知 URL（Twitter/Instagram/Vimeo）→ ytdlp_generic。"""
        import doubi.platforms  # noqa: F401
        for u in (
            "https://twitter.com/user/status/123",
            "https://www.instagram.com/p/abc",
            "https://vimeo.com/123456",
            "https://www.reddit.com/r/videos/comments/abc",
        ):
            detected = PlatformRegistry.detect(u)
            assert detected is not None, f"应能匹配 {u}"
            assert detected.name == "ytdlp", (
                f"{u} 应匹配 ytdlp_generic（priority=-1），实际 {detected.name}"
            )


# ===========================================================================
# adapter.parse — single video
# ===========================================================================


class TestParseSingleVideo:
    def test_returns_media_item_with_platform_ytdlp(self, monkeypatch):
        _stub_extract(monkeypatch, _video_info())
        adapter = YtDlpGenericAdapter()
        item = asyncio.run(adapter.parse("https://example.com/v/abc123"))
        assert item is not None
        assert item.platform is Platform.YT_DLP_GENERIC

    def test_field_mapping(self, monkeypatch):
        _stub_extract(monkeypatch, _video_info())
        adapter = YtDlpGenericAdapter()
        item = asyncio.run(adapter.parse("https://example.com/v/abc123"))
        assert item is not None
        assert item.item_id == "abc123"
        assert item.title == "Sample Video Title"
        assert item.author.name == "Sample Uploader"
        assert item.author.id == "@sample"
        assert item.duration == 213.0
        # 缩略图：挑 height 最大的那张
        assert item.cover_url == "https://example.com/thumb_large.jpg"
        assert item.source_url == "https://example.com/v/abc123"
        # publish_time 是 timestamp 1700000000 转 datetime
        assert item.publish_time is not None
        assert item.publish_time.year == 2023

    def test_extra_metadata_preserved(self, monkeypatch):
        _stub_extract(monkeypatch, _video_info())
        adapter = YtDlpGenericAdapter()
        item = asyncio.run(adapter.parse("https://example.com/v/abc123"))
        assert item is not None
        assert item.extra["extractor"] == "SampleSite"
        assert item.extra["view_count"] == 1000
        assert item.extra["like_count"] == 42
        assert item.extra["tags"] == ["sample", "test"]
        # description 截断到 500 字符
        assert item.extra["description"] == "Sample description text"

    def test_live_status_classifies_as_live(self, monkeypatch):
        info = _video_info(is_live=True, live_status="is_live")
        _stub_extract(monkeypatch, info)
        adapter = YtDlpGenericAdapter()
        item = asyncio.run(adapter.parse("https://example.com/live"))
        assert item is not None
        assert item.media_type is MediaType.LIVE

    def test_video_format_signals_classify_as_video(self, monkeypatch):
        # 默认 _video_info() formats 有 vcodec=h264 → VIDEO
        _stub_extract(monkeypatch, _video_info())
        adapter = YtDlpGenericAdapter()
        item = asyncio.run(adapter.parse("https://example.com/v/abc123"))
        assert item is not None
        assert item.media_type is MediaType.VIDEO


# ===========================================================================
# adapter.parse — playlist / collection
# ===========================================================================


class TestParsePlaylist:
    def test_returns_container_with_children(self, monkeypatch):
        entries = [
            _flat_entry("v1", "First Video", duration=10),
            _flat_entry("v2", "Second Video", duration=20),
            _flat_entry("v3", "Third Video", duration=30),
        ]
        _stub_extract(monkeypatch, _playlist_info(*entries))
        adapter = YtDlpGenericAdapter()
        item = asyncio.run(adapter.parse("https://example.com/playlist/PL123"))
        assert item is not None
        assert item.media_type is MediaType.COLLECTION
        assert item.item_id == "PL123"
        assert item.title == "Sample Playlist"
        assert item.platform is Platform.YT_DLP_GENERIC
        # 3 个 child 都拍平了
        assert len(item.children) == 3
        assert item.children[0].item_id == "v1"
        assert item.children[0].title == "First Video"
        assert item.children[0].source_url == "https://example.com/v/v1"
        # extra 记录 entry_count
        assert item.extra["entry_count"] == 3

    def test_empty_playlist_still_returns_container(self, monkeypatch):
        _stub_extract(monkeypatch, _playlist_info())
        adapter = YtDlpGenericAdapter()
        item = asyncio.run(adapter.parse("https://example.com/playlist/empty"))
        assert item is not None
        assert item.media_type is MediaType.COLLECTION
        assert item.children == []

    def test_filter_url_transparent_entries(self, monkeypatch):
        """``_type == 'url_transparent'`` 的 entry 应被过滤掉，避免重复。"""
        entries = [
            _flat_entry("v1", "Visible"),
            {"_type": "url_transparent", "id": "hidden", "url": "https://x"},
        ]
        _stub_extract(monkeypatch, _playlist_info(*entries))
        adapter = YtDlpGenericAdapter()
        item = asyncio.run(adapter.parse("https://example.com/p"))
        assert item is not None
        ids = [c.item_id for c in item.children]
        assert "v1" in ids
        assert "hidden" not in ids


# ===========================================================================
# adapter.parse — failure paths
# ===========================================================================


class TestParseFailure:
    def test_download_error_returns_none(self, monkeypatch):
        """yt-dlp DownloadError（地区限制 / 私有视频等）→ return None。"""
        import yt_dlp
        _stub_extract(monkeypatch, yt_dlp.utils.DownloadError("geo restricted"))
        adapter = YtDlpGenericAdapter()
        item = asyncio.run(adapter.parse("https://example.com/private"))
        assert item is None

    def test_extractor_error_returns_none(self, monkeypatch):
        """ExtractorError（站点签名变更）→ return None，不抛。"""
        import yt_dlp
        _stub_extract(monkeypatch, yt_dlp.utils.ExtractorError("signature expired"))
        adapter = YtDlpGenericAdapter()
        item = asyncio.run(adapter.parse("https://example.com/broken"))
        assert item is None

    def test_network_error_returns_none(self, monkeypatch):
        """任意网络异常 → return None。"""
        _stub_extract(monkeypatch, ConnectionError("SSL: EOF"))
        adapter = YtDlpGenericAdapter()
        item = asyncio.run(adapter.parse("https://example.com/net-fail"))
        assert item is None

    def test_extract_returns_none_dict_returns_none(self, monkeypatch):
        """yt-dlp 偶尔返回 None（如完全空的 URL）→ 我们也返回 None。"""
        _stub_extract(monkeypatch, None)
        adapter = YtDlpGenericAdapter()
        item = asyncio.run(adapter.parse("https://example.com/empty"))
        assert item is None


# ===========================================================================
# strategies — field normalization
# ===========================================================================


class TestStrategies:
    """覆盖 strategies.py 的字段归一化（不同 extractor 命名差异）。"""

    def test_info_to_author_prefers_uploader_over_channel(self):
        info = {"uploader": "X", "channel": "Y", "creator": "Z"}
        author = strategies.info_to_author(info)
        assert author.name == "X"

    def test_info_to_author_falls_back_to_channel(self):
        info = {"channel": "Y"}
        assert strategies.info_to_author(info).name == "Y"

    def test_info_to_author_falls_back_to_creator(self):
        info = {"creator": "Z"}
        assert strategies.info_to_author(info).name == "Z"

    def test_info_to_author_picks_creator_id(self):
        info = {"uploader_id": "uid", "creator_id": "cid"}
        # uploader_id 在 _UPLOADER_ID_KEYS 里排第一，应胜出
        assert strategies.info_to_author(info).id == "uid"

    def test_info_to_author_no_data_returns_blank(self):
        author = strategies.info_to_author({})
        assert author.name == ""
        assert author.id == ""

    def test_info_to_cover_picks_largest_thumbnail(self):
        info = {
            "thumbnails": [
                {"url": "https://x/small", "height": 100},
                {"url": "https://x/large", "height": 1080},
                {"url": "https://x/medium", "height": 720},
            ],
        }
        assert strategies.info_to_cover(info) == "https://x/large"

    def test_info_to_cover_falls_back_to_thumbnail(self):
        assert strategies.info_to_cover({"thumbnail": "https://x/t"}) == "https://x/t"

    def test_info_to_cover_returns_none_when_empty(self):
        assert strategies.info_to_cover({}) is None

    def test_info_to_media_type_live(self):
        assert strategies.info_to_media_type({"is_live": True}) is MediaType.LIVE
        assert strategies.info_to_media_type({"live_status": "is_live"}) is MediaType.LIVE

    def test_info_to_media_type_image_album(self):
        info = {
            "formats": [{"vcodec": "none", "acodec": "none"}],
            "thumbnails": [{"url": "x"}],
        }
        assert strategies.info_to_media_type(info) is MediaType.IMAGE_ALBUM

    def test_info_to_media_type_video_default(self):
        assert strategies.info_to_media_type({"formats": [{"vcodec": "h264"}]}) is MediaType.VIDEO
        assert strategies.info_to_media_type({}) is MediaType.VIDEO

    def test_is_playlist_info_by_type(self):
        assert strategies.is_playlist_info({"_type": "playlist"}) is True
        assert strategies.is_playlist_info({"_type": "multi_video"}) is True
        assert strategies.is_playlist_info({"_type": "video"}) is False

    def test_is_playlist_info_by_entries(self):
        assert strategies.is_playlist_info({"entries": [{"id": "a"}]}) is True
        assert strategies.is_playlist_info({"entries": []}) is False

    def test_entries_to_children_filters_garbage(self):
        entries = [
            _flat_entry("a", "A"),
            None,
            {},
            {"_type": "url_transparent", "id": "x"},
            {"_type": "url_transparent", "id": "y", "url": "https://y"},
        ]
        children = strategies.entries_to_children(entries)
        ids = [c.item_id for c in children]
        # 只有 "a" 通过：None / {} / url_transparent 全部过滤
        assert ids == ["a"]

    def test_entries_to_children_preserves_url_field(self):
        entries = [_flat_entry("a", "A")]
        children = strategies.entries_to_children(entries)
        assert children[0].source_url == "https://example.com/v/a"


# ===========================================================================
# Sanity: supported_media_types + post_download + repr
# ===========================================================================


class TestMisc:
    def test_supported_media_types(self):
        adapter = YtDlpGenericAdapter()
        types = adapter.supported_media_types()
        assert MediaType.VIDEO.value in types
        assert MediaType.LIVE.value in types

    def test_post_download_is_noop(self):
        import asyncio
        from doubi.core.models import DownloadOptions
        adapter = YtDlpGenericAdapter()
        item = MediaItem(
            platform=Platform.YT_DLP_GENERIC,
            item_id="x", title="t", source_url="https://x",
        )
        # 必须不抛
        result = asyncio.run(adapter.post_download(item, DownloadOptions()))
        assert result is None

    def test_repr_contains_platform_and_priority(self):
        r = repr(YtDlpGenericAdapter())
        assert "YtDlpGenericAdapter" in r
        assert "ytdlp" in r
        assert "priority=-1" in r
