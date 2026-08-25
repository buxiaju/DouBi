"""Tests for M3 Bilibili modules: url / api / auth / strategies / adapter."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
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
from doubi.core.registry import PlatformRegistry  # noqa: E402
from doubi.platforms.bilibili import auth, url  # noqa: E402
from doubi.platforms.bilibili.adapter import BilibiliAdapter  # noqa: E402
from doubi.platforms.bilibili.api import BilibiliAPI  # noqa: E402
from doubi.platforms.bilibili.strategies import (  # noqa: E402
    ContainerStrategy,
    FavlistStrategy,
    MixStrategy,
    SpaceStrategy,
    WatchLaterStrategy,
)
from doubi.platforms.bilibili.url import (  # noqa: E402
    BilibiliURLType,
    classify_bilibili_url,
)


# ---------------------------------------------------------------------------
# url classification
# ---------------------------------------------------------------------------


def test_classify_bilibili_video_bv():
    c = classify_bilibili_url("https://www.bilibili.com/video/BV1xx411c7mD")
    assert c.type is BilibiliURLType.VIDEO
    assert c.item_id == "BV1xx411c7mD"


def test_classify_bilibili_video_av():
    c = classify_bilibili_url("https://www.bilibili.com/video/av170001")
    assert c.type is BilibiliURLType.VIDEO
    assert c.item_id == "av170001"


def test_classify_bilibili_video_bv_with_query():
    c = classify_bilibili_url("https://www.bilibili.com/video/BV1xx411c7mD?p=2&t=42")
    # First pattern is most specific; might match /video/BV... so it should hit VIDEO.
    assert c.type is BilibiliURLType.VIDEO


def test_classify_bilibili_bangumi_ss():
    c = classify_bilibili_url("https://www.bilibili.com/bangumi/play/ss12345")
    assert c.type is BilibiliURLType.BANGUMI
    assert c.item_id == "ss12345"


def test_classify_bilibili_bangumi_ep():
    c = classify_bilibili_url("https://www.bilibili.com/bangumi/play/ep67890")
    assert c.type is BilibiliURLType.BANGUMI
    assert c.item_id == "ep67890"


def test_classify_bilibili_cheese():
    c = classify_bilibili_url("https://www.bilibili.com/cheese/play/ss42")
    assert c.type is BilibiliURLType.COURSE
    assert c.item_id == "ss42"


def test_classify_bilibili_space_subdomain():
    c = classify_bilibili_url("https://space.bilibili.com/123456")
    assert c.type is BilibiliURLType.SPACE
    assert c.item_id == "123456"


def test_classify_bilibili_favlist():
    c = classify_bilibili_url("https://www.bilibili.com/favlist?fid=987654")
    assert c.type is BilibiliURLType.FAVLIST
    assert c.item_id == "987654"


def test_classify_bilibili_watch_later():
    c = classify_bilibili_url("https://www.bilibili.com/watchlater")
    assert c.type is BilibiliURLType.WATCH_LATER


def test_classify_bilibili_history():
    c = classify_bilibili_url("https://www.bilibili.com/history")
    assert c.type is BilibiliURLType.HISTORY


def test_classify_bilibili_popular():
    c = classify_bilibili_url("https://www.bilibili.com/v/popular")
    assert c.type is BilibiliURLType.POPULAR


def test_classify_bilibili_list_ml():
    c = classify_bilibili_url("https://www.bilibili.com/list/ml12345")
    assert c.type is BilibiliURLType.LIST
    assert c.item_id == "ml12345"


def test_classify_bilibili_short():
    c = classify_bilibili_url("https://b23.tv/abcd1234")
    assert c.type is BilibiliURLType.SHORT


# ---------------------------------------------------------------------------
# 直播 URL 识别（live.bilibili.com/{room_id}）
# ---------------------------------------------------------------------------


def test_classify_bilibili_live_plain():
    c = classify_bilibili_url("https://live.bilibili.com/12345")
    assert c.type is BilibiliURLType.LIVE
    assert c.item_id == "12345"


def test_classify_bilibili_live_h5_prefix():
    c = classify_bilibili_url("https://live.bilibili.com/h5/12345")
    assert c.type is BilibiliURLType.LIVE
    assert c.item_id == "12345"


def test_classify_bilibili_live_with_query():
    c = classify_bilibili_url("https://live.bilibili.com/12345?share_source=copy_web")
    assert c.type is BilibiliURLType.LIVE
    assert c.item_id == "12345"


def test_classify_bilibili_live_not_confused_with_space():
    """``bilibili.com/12345`` 是 SPACE（纯数字 UID），不是直播。

    直播必须挂在 ``live.bilibili.com`` 子域，这条用例守住两种纯数字 URL
    的边界，防止 LIVE pattern 误吞 SPACE。
    """
    c = classify_bilibili_url("https://www.bilibili.com/12345")
    assert c.type is BilibiliURLType.SPACE


def test_bilibili_adapter_matches_live_url():
    """适配器 ``match_url`` 必须认 live.bilibili.com，否则会被路由到 UNKNOWN。"""
    from doubi.platforms.bilibili.adapter import BilibiliAdapter
    assert BilibiliAdapter().match_url("https://live.bilibili.com/12345") is True


def test_bilibili_adapter_classify_live_to_media_type():
    """LIVE URL 类型映射到 ``MediaType.LIVE``。"""
    from doubi.platforms.bilibili.adapter import _classify_single_type
    assert _classify_single_type(BilibiliURLType.LIVE) is MediaType.LIVE


def test_classify_media_type_recognizes_live_extractor():
    """yt-dlp 的直播 extractor ``ie_key=BiliBiliLive`` 被识别为 LIVE。"""
    from doubi.platforms.bilibili.api import _classify_media_type
    info = {"ie_key": "BiliBiliLive", "extractor": "BiliBiliLive"}
    assert _classify_media_type(info) is MediaType.LIVE


def test_bilibili_adapter_supports_live_media_type():
    from doubi.platforms.bilibili.adapter import BilibiliAdapter
    assert MediaType.LIVE.value in BilibiliAdapter().supported_media_types()


def test_classify_bilibili_unknown():
    c = classify_bilibili_url("https://example.com/something")
    assert c.type is BilibiliURLType.UNKNOWN
    assert c.item_id == ""


# ---------------------------------------------------------------------------
# 裸编号归一化（纯编号解析）
# ---------------------------------------------------------------------------


def test_classify_bare_bv_id():
    c = classify_bilibili_url("BV1GJ411x7h7")
    assert c.type is BilibiliURLType.VIDEO
    assert c.item_id == "BV1GJ411x7h7"
    assert c.normalized_url == "https://www.bilibili.com/video/BV1GJ411x7h7"


def test_classify_bare_av_id():
    c = classify_bilibili_url("av170001")
    assert c.type is BilibiliURLType.VIDEO
    assert c.item_id == "av170001"
    assert c.normalized_url == "https://www.bilibili.com/video/av170001"


def test_classify_bare_ep_id():
    c = classify_bilibili_url("ep374668")
    assert c.type is BilibiliURLType.BANGUMI
    assert c.item_id == "ep374668"
    assert c.normalized_url == "https://www.bilibili.com/bangumi/play/ep374668"


def test_classify_bare_ss_id():
    c = classify_bilibili_url("ss34244")
    assert c.type is BilibiliURLType.BANGUMI
    assert c.item_id == "ss34244"
    assert c.normalized_url == "https://www.bilibili.com/bangumi/play/ss34244"


def test_classify_bare_ml_id():
    c = classify_bilibili_url("ml12345")
    assert c.type is BilibiliURLType.LIST
    assert c.item_id == "ml12345"
    assert c.normalized_url == "https://www.bilibili.com/list/ml12345"


def test_classify_bare_id_with_whitespace():
    """用户复制时可能带前后空白。"""
    c = classify_bilibili_url("  BV1GJ411x7h7  ")
    assert c.type is BilibiliURLType.VIDEO
    assert c.item_id == "BV1GJ411x7h7"


def test_classify_bare_id_does_not_match_url_fragment():
    """完整 URL 里的 BV 片段不能被裸编号 pattern 误中。"""
    c = classify_bilibili_url("https://www.bilibili.com/video/BV1GJ411x7h7")
    assert c.type is BilibiliURLType.VIDEO
    assert c.normalized_url == "https://www.bilibili.com/video/BV1GJ411x7h7"


def test_classify_bare_id_rejects_invalid_bv():
    """短了一截的 BV 不是合法编号。"""
    c = classify_bilibili_url("BV1GJ411")
    assert c.type is BilibiliURLType.UNKNOWN


def test_match_url_accepts_bare_bv():
    """PlatformRegistry.detect 必须把裸编号路由到 BilibiliAdapter。"""
    from doubi.platforms.bilibili.adapter import BilibiliAdapter
    adapter = BilibiliAdapter.__new__(BilibiliAdapter)
    assert adapter.match_url("BV1GJ411x7h7") is True
    assert adapter.match_url("av170001") is True
    assert adapter.match_url("ep374668") is True
    assert adapter.match_url("ss34244") is True
    assert adapter.match_url("ml12345") is True


def test_registry_detect_bare_bv():
    from doubi.core.registry import PlatformRegistry
    adapter = PlatformRegistry.detect("BV1GJ411x7h7")
    assert adapter is not None
    assert adapter.platform is Platform.BILIBILI


# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------


def test_default_cookie_path(monkeypatch, tmp_path):
    monkeypatch.setenv(auth.ENV_COOKIE_FILE, str(tmp_path / "my.txt"))
    assert auth.default_cookie_path() == tmp_path / "my.txt"


def test_has_cookie_file(tmp_path):
    p = tmp_path / "ok.txt"
    p.write_text("# header\n")
    assert auth.has_cookie_file(p) is True

    p2 = tmp_path / "empty.txt"
    p2.write_text("")
    assert auth.has_cookie_file(p2) is False

    assert auth.has_cookie_file(tmp_path / "missing.txt") is False


def test_write_netscape_cookies_bilibili(tmp_path):
    cookies = [
        {"domain": ".bilibili.com", "path": "/", "name": "SESSDATA", "value": "abc%2Cdef", "secure": True},
        {"domain": ".bilibili.com", "path": "/", "name": "bili_jct", "value": "xyz"},
    ]
    p = auth.write_netscape_cookies(cookies, path=tmp_path / "bilibili.txt")
    text = p.read_text(encoding="utf-8")
    # domain flag path secure expires name value
    assert ".bilibili.com\tTRUE\t/\tTRUE\t0\tSESSDATA\tabc%2Cdef" in text
    assert "bili_jct\txyz" in text


# ---------------------------------------------------------------------------
# api
# ---------------------------------------------------------------------------


def _fake_bili_info_dict(**overrides) -> dict:
    base = {
        "id": "BV1xx411c7mD",
        "title": "测试视频标题",
        "uploader": "测试UP主",
        "uploader_id": "123456",
        "uploader_url": "https://space.bilibili.com/123456",
        "thumbnail": "https://example.com/cover.jpg",
        "duration": 600.5,
        "timestamp": 1736899200,
        "view_count": 100000,
        "like_count": 5000,
        "formats": [{"vcodec": "h264", "acodec": "aac"}],
        "ie_key": "Bilibili",
    }
    base.update(overrides)
    return base


def test_api_to_media_item_basic():
    item = BilibiliAPI().to_media_item(_fake_bili_info_dict(), "https://www.bilibili.com/video/BV1xx411c7mD")
    assert item.platform is Platform.BILIBILI
    assert item.item_id == "BV1xx411c7mD"
    assert item.title == "测试视频标题"
    assert item.author.name == "测试UP主"
    assert item.author.id == "123456"
    assert item.cover_url == "https://example.com/cover.jpg"
    assert item.duration == 600.5
    assert item.media_type is MediaType.VIDEO
    assert item.extra["view_count"] == 100000


def test_api_to_media_item_picks_largest_thumbnail():
    info = _fake_bili_info_dict()
    info["thumbnails"] = [
        {"url": "https://x/small.jpg", "height": 360},
        {"url": "https://x/large.jpg", "height": 1080},
    ]
    info.pop("thumbnail", None)
    item = BilibiliAPI().to_media_item(info, "x")
    assert item.cover_url == "https://x/large.jpg"


def test_api_to_media_item_extracts_uid_from_uploader_url():
    info = _fake_bili_info_dict()
    info.pop("uploader_id", None)
    info["uploader_url"] = "https://space.bilibili.com/789012"
    item = BilibiliAPI().to_media_item(info, "x")
    assert item.author.id == "789012"


def test_api_to_media_item_classifies_bangumi():
    info = _fake_bili_info_dict(ie_key="BiliBiliBangumiSeason")
    item = BilibiliAPI().to_media_item(info, "x")
    assert item.media_type is MediaType.BANGUMI
    assert item.extra["is_bangumi"] is True


def test_api_to_media_item_classifies_cheese():
    info = _fake_bili_info_dict(ie_key="BiliBiliCheeseSeason")
    item = BilibiliAPI().to_media_item(info, "x")
    assert item.media_type is MediaType.COURSE


def test_api_flat_to_media_item_sparse():
    entry = {
        "id": "BV1yy9999yyy",
        "title": "sparse",
        "uploader": "u1",
        "thumbnails": [{"url": "https://x/t.jpg"}],
        "url": "https://www.bilibili.com/video/BV1yy9999yyy",
    }
    item = BilibiliAPI().flat_to_media_item(entry)
    assert item.item_id == "BV1yy9999yyy"
    assert item.title == "sparse"
    assert item.author.name == "u1"
    assert item.cover_url == "https://x/t.jpg"
    assert item.source_url == "https://www.bilibili.com/video/BV1yy9999yyy"
    assert item.extra["_flat_entry"] is True


def test_api_fetch_returns_none_on_error(monkeypatch):
    api = BilibiliAPI()

    class _BoomCtx:
        def __enter__(self): raise RuntimeError("simulated")
        def __exit__(self, *a): return False

    def _fake_ytdl(opts): return _BoomCtx()
    fake_mod = type("M", (), {"YoutubeDL": _fake_ytdl})
    monkeypatch.setattr(api, "_ytdlp", fake_mod)
    assert asyncio.run(api.fetch("https://www.bilibili.com/video/BV1")) is None


# ---------------------------------------------------------------------------
# strategies
# ---------------------------------------------------------------------------


def _stub_bili_api(entries):
    """Build a BilibiliAPI whose fetch_flat returns a fake info dict."""
    api = BilibiliAPI()
    async def _fake(url, *, playlist_items=None):
        return {"entries": entries}
    api.fetch_flat = _fake
    return api


def _stub_space_api(api, archives, total=None):
    """Patch the strategies module's httpx path to return a canned
    arc/search response. Returns a list of mock client stubs."""
    import httpx as _httpx

    if total is None:
        total = len(archives)

    async def _fake_get(url, *args, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.json = MagicMock(return_value={
            "code": 0,
            "message": "0",
            "data": {
                "list": archives,
                "page": {"count": total},
            },
        })
        return resp

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)
    fake_client.get = AsyncMock(side_effect=_fake_get)

    return lambda **kw: fake_client


def test_space_strategy_extracts_uid(monkeypatch):
    """SpaceStrategy hits the /x/space/arc/search API directly."""
    fake_client = _stub_space_api(BilibiliAPI(), [
        {"bvid": "BV1", "title": "v1", "author": "u1", "mid": 11,
         "duration": 100, "pubdate": 1600000000, "pic": "https://x/1.jpg"},
        {"bvid": "BV2", "title": "v2", "author": "u1", "mid": 11,
         "duration": 100, "pubdate": 1600000000, "pic": "https://x/2.jpg"},
    ])
    monkeypatch.setattr(httpx, "AsyncClient", fake_client)

    s = SpaceStrategy(BilibiliAPI())
    items = asyncio.run(s.expand("https://space.bilibili.com/123456", max_count=0))
    assert len(items) == 2
    assert all(it.platform is Platform.BILIBILI for it in items)
    assert {it.item_id for it in items} == {"BV1", "BV2"}


def test_space_strategy_respects_max_count(monkeypatch):
    """When max_count is set, we cap the result list."""
    archives = [
        {"bvid": f"BV{i}", "title": f"v{i}", "author": "u", "mid": 1,
         "duration": 1, "pubdate": 1, "pic": "https://x"}
        for i in range(10)
    ]
    fake_client = _stub_space_api(BilibiliAPI(), archives, total=10)
    monkeypatch.setattr(httpx, "AsyncClient", fake_client)

    s = SpaceStrategy(BilibiliAPI())
    items = asyncio.run(s.expand("https://space.bilibili.com/1", max_count=3))
    assert len(items) == 3


def test_space_strategy_wrong_url_returns_empty():
    api = BilibiliAPI()
    s = SpaceStrategy(api)
    items = asyncio.run(s.expand("https://www.bilibili.com/video/BV1"))
    assert items == []


def test_favlist_strategy_requires_cookies():
    api = BilibiliAPI()  # no cookies
    s = FavlistStrategy(api)
    items = asyncio.run(s.expand("https://www.bilibili.com/favlist?fid=1"))
    assert items == []


def test_favlist_strategy_with_cookies_returns_items():
    api = BilibiliAPI(cookies_file="/tmp/c.txt")
    api.fetch_flat = _stub_bili_api([
        {"id": "BV9", "title": "fav1", "uploader": "u", "url": "https://x/9"},
    ]).fetch_flat
    s = FavlistStrategy(api)
    items = asyncio.run(s.expand("https://www.bilibili.com/favlist?fid=1"))
    assert len(items) == 1


def test_watch_later_strategy_requires_cookies():
    api = BilibiliAPI()
    s = WatchLaterStrategy(api)
    items = asyncio.run(s.expand("https://www.bilibili.com/watchlater"))
    assert items == []


def test_mix_strategy_extracts_ml_id(monkeypatch):
    """MixStrategy scrapes mid from the list page, then hits the series API."""
    api = BilibiliAPI()

    # Mock httpx.AsyncClient so no real network is used.
    async def _fake_get(url, *args, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        if "/list/ml" in url:
            # First call: the /list/ page → HTML containing mid
            resp.text = '<html><script>"mid":643216573</script></html>'
            resp.json = MagicMock(side_effect=ValueError("not json"))
        else:
            # Second call: the series/archives API
            resp.json = MagicMock(return_value={
                "code": 0,
                "message": "0",
                "data": {
                    "archives": [
                        {"bvid": "BV1", "title": "mix1", "author": "u",
                         "mid": 643216573, "duration": 100, "pubdate": 1600000000,
                         "pic": "https://x/pic.jpg"},
                    ],
                    "page": {"count": 1, "total": 1},
                },
            })
        return resp

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)
    fake_client.get = AsyncMock(side_effect=_fake_get)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: fake_client)

    s = MixStrategy(api)
    items = asyncio.run(s.expand("https://www.bilibili.com/list/ml12345"))
    assert len(items) == 1
    assert items[0].item_id == "BV1"
    assert items[0].title == "mix1"
    assert items[0].author.name == "u"


def test_mix_strategy_wrong_url_returns_empty():
    api = BilibiliAPI()
    s = MixStrategy(api)
    items = asyncio.run(s.expand("https://www.bilibili.com/video/BV1"))
    assert items == []


# ---------------------------------------------------------------------------
# adapter
# ---------------------------------------------------------------------------


def test_adapter_instantiates_with_strategies():
    a = BilibiliAdapter()
    strategies = {s.name for s in a.available_strategies()}
    assert "space" in strategies
    assert "favlist" in strategies
    assert "watch_later" in strategies
    assert "mix" in strategies


def test_adapter_get_strategy():
    a = BilibiliAdapter()
    assert a.get_strategy("space") is not None
    assert a.get_strategy("nope") is None


def test_adapter_parse_space_returns_container():
    a = BilibiliAdapter()
    item = asyncio.run(a.parse("https://space.bilibili.com/123456"))
    assert item is not None
    assert item.media_type is MediaType.USER
    assert item.item_id == "123456"
    assert item.extra["url_type"] == "space"
    assert item.extra["default_strategy"] == "space"
    assert "space" in item.extra["available_strategies"]


def test_adapter_parse_favlist_returns_container():
    a = BilibiliAdapter()
    item = asyncio.run(a.parse("https://www.bilibili.com/favlist?fid=999"))
    assert item is not None
    assert item.media_type is MediaType.FAVLIST
    assert item.item_id == "999"
    assert item.extra["default_strategy"] == "favlist"


def test_adapter_parse_bangumi_returns_minimal_when_api_fails(monkeypatch):
    a = BilibiliAdapter()

    async def _fake_fetch(url, *, allow_playlist=False):
        return None
    monkeypatch.setattr(a.api, "fetch", _fake_fetch)

    item = asyncio.run(a.parse("https://www.bilibili.com/bangumi/play/ss12345"))
    assert item is not None
    assert item.platform is Platform.BILIBILI
    assert item.item_id == "ss12345"
    # Without metadata, media_type defaults to VIDEO; the bangumi
    # classification will be re-applied once the engine fetches info
    # and we patch _parse_single to return a proper item. The minimal
    # fallback keeps the URL, so yt-dlp can still try.
    assert item.source_url.startswith("https://www.bilibili.com/")


def test_adapter_parse_video_populates_metadata(monkeypatch):
    a = BilibiliAdapter()

    async def _fake_fetch(url, *, allow_playlist=False):
        return _fake_bili_info_dict()
    monkeypatch.setattr(a.api, "fetch", _fake_fetch)

    item = asyncio.run(a.parse("https://www.bilibili.com/video/BV1xx411c7mD"))
    assert item is not None
    assert item.title == "测试视频标题"
    assert item.author.name == "测试UP主"
    assert item.duration == 600.5
    assert item.media_type is MediaType.VIDEO


def test_adapter_parse_multi_page_video_expands_to_container(monkeypatch):
    """BV 分P（多页）视频应被解析为 COLLECTION 容器 + children。"""
    a = BilibiliAdapter()

    async def _fake_fetch(url, *, allow_playlist=False):
        # 模拟 yt-dlp 对分P视频返回 playlist + entries
        return {
            "_type": "playlist",
            "id": "BV1zygDzDES2",
            "title": "测试分P合集标题",
            "uploader": "测试UP主",
            "uploader_id": "123456",
            "thumbnail": "https://example.com/cover.jpg",
            "duration": 1800.0,
            "entries": [
                {
                    "id": "BV1zygDzDES2_p1",
                    "title": "P1 开场介绍",
                    "uploader": "测试UP主",
                    "url": "https://www.bilibili.com/video/BV1zygDzDES2?p=1",
                    "thumbnail": "https://example.com/p1.jpg",
                    "duration": 300.0,
                },
                {
                    "id": "BV1zygDzDES2_p2",
                    "title": "P2 核心讲解",
                    "uploader": "测试UP主",
                    "url": "https://www.bilibili.com/video/BV1zygDzDES2?p=2",
                    "thumbnail": "https://example.com/p2.jpg",
                    "duration": 600.0,
                },
                {
                    "id": "BV1zygDzDES2_p3",
                    "title": "P3 总结与作业",
                    "uploader": "测试UP主",
                    "url": "https://www.bilibili.com/video/BV1zygDzDES2?p=3",
                    "thumbnail": "https://example.com/p3.jpg",
                    "duration": 900.0,
                },
            ],
        }
    monkeypatch.setattr(a.api, "fetch", _fake_fetch)

    item = asyncio.run(a.parse("https://www.bilibili.com/video/BV1zygDzDES2"))
    assert item is not None
    # 父级应为 COLLECTION 容器
    assert item.media_type is MediaType.COLLECTION
    assert item.item_id == "BV1zygDzDES2"
    assert item.title == "测试分P合集标题"
    assert item.author.name == "测试UP主"
    assert item.cover_url == "https://example.com/cover.jpg"
    assert item.extra.get("is_multi_page") is True
    assert item.extra.get("multi_page_count") == 3
    # children 正确展开
    assert len(item.children) == 3
    assert item.is_container() is True
    # 每个 child 都应是可下载的 VIDEO
    for idx, child in enumerate(item.children, 1):
        assert child.platform is Platform.BILIBILI
        assert child.media_type is MediaType.VIDEO
        assert f"P{idx}" in child.title
    # expand() 应直接返回已有 children（不重新调 strategy）
    children_from_expand = asyncio.run(a.expand(item))
    assert children_from_expand == item.children


def test_adapter_parse_single_page_video_not_container(monkeypatch):
    """只有 1 分P（真正单视频）时不应展开成容器。"""
    a = BilibiliAdapter()

    async def _fake_fetch(url, *, allow_playlist=False):
        # _type=playlist 但 entries 只有 1 个 => 按单视频处理
        base = _fake_bili_info_dict()
        base["_type"] = "playlist"
        base["entries"] = [
            {"id": "BV1xx411c7mD_p1", "title": "只有一集",
             "uploader": "u", "url": "https://x/1"}
        ]
        return base
    monkeypatch.setattr(a.api, "fetch", _fake_fetch)

    item = asyncio.run(a.parse("https://www.bilibili.com/video/BV1xx411c7mD"))
    assert item is not None
    # 非容器
    assert item.media_type is MediaType.VIDEO
    assert item.is_container() is False
    assert len(item.children) == 0
    assert item.extra.get("is_multi_page") is None


# ---------------------------------------------------------------------------
# ugc_season: collections whose episodes are grouped into categories
# ---------------------------------------------------------------------------

# A syntactically valid BV id: url._BV_RE is "BV1" + 9 base58 chars
# (the alphabet omits 0, I, O and l).
_SEASON_ROOT_BV = "BV1RootSeas1"


def _fake_ep_bv(i: int, j: int) -> str:
    """Deterministic, regex-valid bvid for section ``i`` episode ``j``."""
    return f"BV1s{i + 1}e{j + 1}Test1"


def _fake_view_data(*, sections: list[tuple[str, list[str]]]) -> dict:
    """Build a view-API payload shaped like ``data`` from /web-interface/view.

    ``sections`` is a list of ``(section_title, [episode_title, ...])``.

    Episode bvids are generated as ``BV1s{i+1}e{j+1}Test1`` so they satisfy
    ``url._BV_RE`` (``BV1`` + exactly 9 chars from the base58 alphabet, which
    excludes ``0``/``I``/``O``/``l``). Indices are 1-based for that reason.
    An id of the wrong length would still *partially* match the URL regex and
    be silently truncated, so the 12-char total matters.
    """
    return {
        "bvid": _SEASON_ROOT_BV,
        "title": "根视频标题",
        "owner": {"name": "水木观畴电子通信考研", "mid": 42},
        "pic": "https://example.com/season.jpg",
        "pages": [{"cid": 1, "page": 1, "part": "P1", "duration": 100}],
        "ugc_season": {
            "id": 8316465,
            "title": "高分必备660！",
            "sections": [
                {
                    "id": 9245156 + i,
                    "title": sec_title,
                    "episodes": [
                        {
                            "id": 201212309 + i * 100 + j,
                            "aid": 116532478745132 + j,
                            "bvid": _fake_ep_bv(i, j),
                            "cid": 38156832155 + j,
                            "title": ep_title,
                            "page": {"part": f"{j + 1}.1", "duration": 200 + j},
                        }
                        for j, ep_title in enumerate(ep_titles)
                    ],
                }
                for i, (sec_title, ep_titles) in enumerate(sections)
            ],
        },
    }


def test_parse_ugc_season_normalizes_nested_structure():
    api = BilibiliAPI()
    data = _fake_view_data(sections=[
        ("模拟电子技术", ["1-2章", "3-5章"]),
        ("信号与系统", ["第1-2章"]),
    ])
    season = api.parse_ugc_season(data)
    assert season is not None
    assert season["season_id"] == 8316465
    assert season["season_title"] == "高分必备660！"
    assert [s["section_title"] for s in season["sections"]] == [
        "模拟电子技术", "信号与系统",
    ]
    first = season["sections"][0]
    assert len(first["episodes"]) == 2
    ep = first["episodes"][0]
    assert ep["bvid"] == _fake_ep_bv(0, 0)
    assert ep["title"] == "1-2章"
    assert ep["duration"] == 200


def test_parse_ugc_season_returns_none_without_season():
    api = BilibiliAPI()
    assert api.parse_ugc_season({"bvid": "BV1", "pages": []}) is None
    assert api.parse_ugc_season(None) is None


def test_parse_ugc_season_skips_episodes_without_bvid():
    api = BilibiliAPI()
    data = _fake_view_data(sections=[("分类A", ["e1", "e2"])])
    data["ugc_season"]["sections"][0]["episodes"][0].pop("bvid")
    season = api.parse_ugc_season(data)
    assert season is not None
    assert len(season["sections"][0]["episodes"]) == 1


def test_adapter_parse_categorised_season_exposes_section_children(monkeypatch):
    """带分类的合集应只在顶层暴露「每个分类一行」，点击才展开 episode。"""
    a = BilibiliAdapter()

    async def _fake_fetch(url, *, allow_playlist=False):
        return {"_type": "playlist", "id": _SEASON_ROOT_BV, "entries": []}

    async def _fake_view(bvid):
        return _fake_view_data(sections=[
            ("模拟电子技术", ["1-2章", "3-5章"]),
            ("信号与系统", ["第1-2章"]),
        ])

    monkeypatch.setattr(a.api, "fetch", _fake_fetch)
    monkeypatch.setattr(a.api, "fetch_view_data", _fake_view)

    item = asyncio.run(a.parse(f"https://www.bilibili.com/video/{_SEASON_ROOT_BV}"))
    assert item is not None
    assert item.media_type is MediaType.COLLECTION
    assert item.title == "高分必备660！"
    assert item.author.name == "水木观畴电子通信考研"
    assert item.extra.get("is_ugc_season") is True
    assert item.extra.get("season_id") == 8316465
    assert item.extra.get("section_count") == 2
    assert item.extra.get("episode_count") == 3

    # Top-level children are the sections themselves, not the episodes.
    assert item.is_container() is True
    assert len(item.children) == 2
    assert [c.title for c in item.children] == ["模拟电子技术", "信号与系统"]
    for child in item.children:
        assert child.media_type is MediaType.COLLECTION
        assert child.extra["_from_ugc_season_section"] is True
        assert child.extra["collection_title"] == "高分必备660！"
        assert child.children == []  # 还没点击展开
        assert child.extra["_season_parent_id"] == item.item_id

    # Section item_ids must stay unique.
    assert len({c.item_id for c in item.children}) == len(item.children)
    # expand() short-circuits on the pre-filled (section) children.
    assert asyncio.run(a.expand(item)) == item.children


def test_adapter_expand_section_materialises_episodes(monkeypatch):
    """点击 section 行应触发 ``expand_section`` 并返回该分类下的 episode。"""
    a = BilibiliAdapter()

    async def _fake_fetch(url, *, allow_playlist=False):
        return {"_type": "playlist", "id": _SEASON_ROOT_BV, "entries": []}

    async def _fake_view(bvid):
        return _fake_view_data(sections=[
            ("模拟电子技术", ["1-2章", "3-5章"]),
            ("信号与系统", ["第1-2章"]),
        ])

    monkeypatch.setattr(a.api, "fetch", _fake_fetch)
    monkeypatch.setattr(a.api, "fetch_view_data", _fake_view)

    season = asyncio.run(a.parse(f"https://www.bilibili.com/video/{_SEASON_ROOT_BV}"))
    sec_a, sec_b = season.children

    eps_a = asyncio.run(a.expand_section(sec_a))
    assert [c.item_id for c in eps_a] == [_fake_ep_bv(0, 0), _fake_ep_bv(0, 1)]
    assert [c.title for c in eps_a] == ["1-2章", "3-5章"]
    for ep in eps_a:
        assert ep.media_type is MediaType.VIDEO
        assert ep.extra["collection_title"] == "高分必备660！"
        assert ep.extra["section_title"] == "模拟电子技术"
        assert ep.source_url == f"https://www.bilibili.com/video/{ep.item_id}"

    # Second call returns the cached list (no recomputation).
    again = asyncio.run(a.expand_section(sec_a))
    assert again is eps_a or again == eps_a

    # Expanding the other section does not affect the first one.
    eps_b = asyncio.run(a.expand_section(sec_b))
    assert [c.item_id for c in eps_b] == [_fake_ep_bv(1, 0)]
    assert [c.title for c in eps_b] == ["第1-2章"]
    assert sec_a.children  # already expanded stays expanded

    # Total episode ids across both sections must remain unique.
    all_ids = [c.item_id for c in sec_a.children] + [c.item_id for c in sec_b.children]
    assert len(set(all_ids)) == len(all_ids)


def test_adapter_expand_section_rejects_non_section_items(monkeypatch):
    """非 section item 调 ``expand_section`` 应直接 ValueError。"""
    a = BilibiliAdapter()
    plain = MediaItem(
        platform=Platform.BILIBILI, item_id="BV1xx", title="x",
        source_url="https://www.bilibili.com/video/BV1xx",
    )
    try:
        asyncio.run(a.expand_section(plain))
    except ValueError as exc:
        assert "section child" in str(exc)
    else:
        raise AssertionError("expand_section should refuse non-section items")


def test_adapter_expand_section_missing_parent_raises(monkeypatch):
    """section 行若找不到所属 season 容器（adapter 缓存被清空），应 LookupError。"""
    a = BilibiliAdapter()
    # Build a section manually without going through parse(); it carries
    # the backlink flag but the parent never made it into _parsed_items.
    orphan = MediaItem(
        platform=Platform.BILIBILI,
        item_id="ugcseason1#1",
        title="模拟电子技术",
        source_url="https://www.bilibili.com/video/BV1RootSeas1",
        extra={
            "_from_ugc_season_section": True,
            "section_index": 0,
            "_season_parent_id": "ugcseason1",
        },
    )
    try:
        asyncio.run(a.expand_section(orphan))
    except LookupError:
        pass
    else:
        raise AssertionError("expand_section should fail without a parent")


def test_adapter_expand_episode_pages_returns_video_rows(monkeypatch):
    """expand_episode_pages should hit the view API and split data.pages."""
    a = BilibiliAdapter()
    episode = MediaItem(
        platform=Platform.BILIBILI,
        item_id="BV1oxdwBBE3B",
        title="1-2章",
        author=Author(name="水木观畴电子通信考研"),
        source_url="https://www.bilibili.com/video/BV1oxdwBBE3B",
        extra={
            "_from_ugc_season": True,
            "collection_title": "高分必备660！",
            "section_title": "模拟电子技术",
            "episode_id": 201212309,
        },
    )

    async def _fake_view(bvid):
        return {
            "bvid": bvid,
            "pages": [
                {"cid": 1, "page": 1, "part": "1.1", "duration": 200},
                {"cid": 2, "page": 2, "part": "1.2", "duration": 250},
                {"cid": 3, "page": 3, "part": "1.3", "duration": 300},
            ],
        }

    monkeypatch.setattr(a.api, "fetch_view_data", _fake_view)
    pages = asyncio.run(a.expand_episode_pages(episode))
    assert [p.title for p in pages] == ["1.1", "1.2", "1.3"]
    assert [p.item_id for p in pages] == ["BV1oxdwBBE3B#p1", "BV1oxdwBBE3B#p2", "BV1oxdwBBE3B#p3"]
    assert all(p.media_type is MediaType.VIDEO for p in pages)
    assert all("?p=" in p.source_url for p in pages)
    for p in pages:
        # file_layout path must include episode title so 三层目录生效.
        assert p.extra["episode_title"] == "1-2章"
        assert p.extra["collection_title"] == "高分必备660！"
        assert p.extra["section_title"] == "模拟电子技术"


def test_adapter_single_section_season_is_not_treated_as_categorised(monkeypatch):
    """无分类的合集只有一个「正片」section，必须走原分P逻辑而非分类逻辑。"""
    a = BilibiliAdapter()

    async def _fake_fetch(url, *, allow_playlist=False):
        base = _fake_bili_info_dict()
        base["_type"] = "playlist"
        base["entries"] = [
            {"id": f"{_SEASON_ROOT_BV}_p1", "title": "P1", "uploader": "u",
             "url": f"https://www.bilibili.com/video/{_SEASON_ROOT_BV}?p=1"},
            {"id": f"{_SEASON_ROOT_BV}_p2", "title": "P2", "uploader": "u",
             "url": f"https://www.bilibili.com/video/{_SEASON_ROOT_BV}?p=2"},
        ]
        return base

    async def _fake_view(bvid):
        return _fake_view_data(sections=[("正片", ["第一集", "第二集"])])

    monkeypatch.setattr(a.api, "fetch", _fake_fetch)
    monkeypatch.setattr(a.api, "fetch_view_data", _fake_view)

    item = asyncio.run(a.parse(f"https://www.bilibili.com/video/{_SEASON_ROOT_BV}"))
    assert item is not None
    assert item.extra.get("is_ugc_season") is None
    assert item.extra.get("is_multi_page") is True
    assert len(item.children) == 2
    for child in item.children:
        assert child.extra.get("section_title") is None


def test_pipeline_parse_and_expand_multi_page_video(monkeypatch):
    """GUI 的 parse_and_expand 应对分P视频正确返回 (container, children)。"""
    import doubi.core.pipeline as pipeline_mod

    class _SpyEngine:
        name = "spy"
        def supports(self, item): return True
        async def download(self, item, options, *, on_progress=None):
            return True

    pipeline = pipeline_mod.DownloadPipeline(engine=_SpyEngine())

    async def _fake_parse(url):
        # 模拟 adapter 返回的分P容器
        parent = MediaItem(
            platform=Platform.BILIBILI,
            item_id="BV1zygDzDES2",
            title="分P合集",
            media_type=MediaType.COLLECTION,
            source_url=url,
        )
        parent.children = [
            MediaItem(platform=Platform.BILIBILI, item_id=f"BVp{i}",
                      title=f"P{i}", media_type=MediaType.VIDEO,
                      source_url=f"{url}?p={i}")
            for i in range(1, 4)
        ]
        parent.extra["is_multi_page"] = True
        parent.extra["multi_page_count"] = 3
        return parent
    monkeypatch.setattr(pipeline, "parse", _fake_parse)

    container, children = asyncio.run(pipeline.parse_and_expand(
        "https://www.bilibili.com/video/BV1zygDzDES2",
    ))
    assert container is not None
    assert container.media_type is MediaType.COLLECTION
    assert len(children) == 3
    assert [c.item_id for c in children] == ["BVp1", "BVp2", "BVp3"]


def test_adapter_expand_container_uses_default_strategy(monkeypatch):
    a = BilibiliAdapter()

    async def _fake_expand(url, *, max_count=0):
        return [MediaItem(
            platform=Platform.BILIBILI, item_id="BVc1", title="child",
            author=Author(), media_type=MediaType.VIDEO,
            source_url="https://x/c1",
        )]
    monkeypatch.setattr(a.get_strategy("space"), "expand", _fake_expand)

    item = asyncio.run(a.parse("https://space.bilibili.com/1"))
    children = asyncio.run(a.expand(item))
    assert len(children) == 1
    assert item.children == children
    assert item.extra["applied_strategy"] == "space"


def test_adapter_expand_container_uses_named_strategy(monkeypatch):
    a = BilibiliAdapter()

    async def _fake_expand(url, *, max_count=0):
        return [MediaItem(
            platform=Platform.BILIBILI, item_id="BVmix1", title="mixchild",
            author=Author(), media_type=MediaType.VIDEO,
            source_url="https://x/m1",
        )]
    monkeypatch.setattr(a.get_strategy("mix"), "expand", _fake_expand)

    # Parse a list URL, then expand with mix
    item = asyncio.run(a.parse("https://www.bilibili.com/list/ml999"))
    children = asyncio.run(a.expand(item, strategy="mix"))
    assert len(children) == 1
    assert item.extra["applied_strategy"] == "mix"


def test_adapter_supported_media_types():
    a = BilibiliAdapter()
    types = a.supported_media_types()
    assert "video" in types
    assert "bangumi" in types
    assert "course" in types


# ---------------------------------------------------------------------------
# integration with registry + pipeline
# ---------------------------------------------------------------------------


def test_registry_still_has_douyin_after_bilibili_changes():
    """Adding B 站deep modules shouldn't break douyin registration."""
    import doubi.platforms  # noqa: F401
    platforms = {a.platform for a in PlatformRegistry.all()}
    assert Platform.DOUYIN in platforms
    assert Platform.BILIBILI in platforms


def test_bilibili_short_link_resolution_falls_back(monkeypatch):
    """If httpx can't reach b23.tv, parse() returns None (and logs)."""
    import httpx as _httpx

    a = BilibiliAdapter()
    real_get = _httpx.AsyncClient.get

    async def _fake_get(self, url, *a, **kw):
        raise _httpx.ConnectError("offline")

    monkeypatch.setattr(_httpx.AsyncClient, "get", _fake_get)
    item = asyncio.run(a.parse("https://b23.tv/abcd1234"))
    assert item is None


def test_pipeline_renders_bilibili_output_template(monkeypatch, tmp_path):
    """Pipeline must populate item.output_template before download for B 站too."""
    import doubi.core.pipeline as pipeline_mod

    captured = {}

    class _SpyEngine:
        name = "spy"
        def supports(self, item): return True
        async def download(self, item, options, *, on_progress=None):
            captured["template"] = item.output_template
            return True

    pipeline = pipeline_mod.DownloadPipeline(engine=_SpyEngine())

    async def _fake_parse(url):
        return MediaItem(
            platform=Platform.BILIBILI,
            item_id="BV1xx411c7mD",
            title="测试BV视频",
            author=Author(name="测试UP主"),
            duration=120.0,
            media_type=MediaType.VIDEO,
            source_url="https://www.bilibili.com/video/BV1xx411c7mD",
        )
    monkeypatch.setattr(pipeline, "parse", _fake_parse)

    options = DownloadOptions(output_root=tmp_path, filename_template="{title}_{author}_{item_id}")
    result = asyncio.run(pipeline.process_url(
        "https://www.bilibili.com/video/BV1xx411c7mD", options,
    ))
    assert result is not None
    tpl = captured.get("template")
    assert tpl is not None
    assert "测试BV视频" in tpl
    assert "测试UP主" in tpl
    assert "BV1xx411c7mD" in tpl
