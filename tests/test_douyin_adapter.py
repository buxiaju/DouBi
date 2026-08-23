"""Tests for M2 Douyin modules: api / naming / auth / strategies / adapter wiring."""

from __future__ import annotations

import asyncio
import datetime as dt
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from doubi.core.models import (
    Author,
    DownloadOptions,
    MediaItem,
    MediaType,
    Platform,
)
from doubi.core import naming
from doubi.platforms.douyin import auth
from doubi.platforms.douyin.api import DouyinAPI
from doubi.platforms.douyin.adapter import DouyinAdapter
from doubi.platforms.douyin.strategies import LikeStrategy, PostStrategy


def _item(title: str = "测试视频", author: str = "张三", date=None) -> MediaItem:
    return MediaItem(
        platform=Platform.DOUYIN, item_id="7123456789012345678",
        title=title, author=Author(name=author), publish_time=date,
        media_type=MediaType.VIDEO,
        source_url="https://www.douyin.com/video/7123456789012345678",
    )


def test_render_filename_default_template():
    item = _item(date=dt.datetime(2026, 1, 15))
    options = DownloadOptions(output_root=Path("./out"))
    name = naming.render_filename(item, options)
    assert "7123456789012345678" in name
    assert "测试视频" in name
    options2 = DownloadOptions(
        output_root=Path("./out"),
        filename_template="{date}_{author}_{title}_{item_id}",
    )
    name2 = naming.render_filename(item, options2)
    assert "2026-01-15" in name2
    assert "张三" in name2


def test_render_filename_sanitizes_illegal_chars():
    item = _item(title='a<b>c:d/e\\f|g?h*i"j')
    options = DownloadOptions(output_root=Path("./out"))
    name = naming.render_filename(item, options)
    for illegal in '<>:"/\\|?*':
        assert illegal not in name


def test_render_filename_index_zero_padded():
    item = _item()
    options = DownloadOptions(output_root=Path("./out"), filename_template="{index}_{title}")
    assert naming.render_filename(item, options, index=1).startswith("001_")
    assert naming.render_filename(item, options, index=42).startswith("042_")


def test_render_filename_preserves_unknown_tokens():
    item = _item()
    options = DownloadOptions(output_root=Path("./out"), filename_template="{nope}_{title}")
    name = naming.render_filename(item, options)
    assert "{nope}" in name
    assert "测试视频" in name


def test_render_filename_empty_values_dont_crash():
    item = MediaItem(platform=Platform.DOUYIN, item_id="", title="", author=Author(),
                     media_type=MediaType.VIDEO, source_url="x")
    options = DownloadOptions(output_root=Path("./out"))
    name = naming.render_filename(item, options)
    assert name


def test_render_filename_length_cap():
    item = _item(title="x" * 1000)
    options = DownloadOptions(output_root=Path("./out"))
    name = naming.render_filename(item, options)
    assert len(name) <= naming.MAX_BASENAME


def test_set_item_output_template():
    item = _item()
    options = DownloadOptions(output_root=Path("./out"))
    assert item.output_template is None
    naming.set_item_output_template(item, options)
    assert item.output_template is not None


def test_default_cookie_path(monkeypatch, tmp_path):
    monkeypatch.setenv("DOUBI_DOUYIN_COOKIES", str(tmp_path / "my.txt"))
    assert auth.default_cookie_path() == tmp_path / "my.txt"


def test_ensure_cookie_dir_creates_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DOUBI_COOKIE_DIR", str(tmp_path / "sub"))
    d = auth.ensure_cookie_dir()
    assert d.exists() and d.is_dir()


def test_has_cookie_file(tmp_path):
    p = tmp_path / "ok.txt"
    p.write_text("# header\n")
    assert auth.has_cookie_file(p) is True
    assert auth.has_cookie_file(tmp_path / "missing.txt") is False


def test_write_netscape_cookies(tmp_path):
    cookies = [
        {"domain": ".douyin.com", "path": "/", "name": "ttwid", "value": "abc", "secure": True, "expires": 0},
        {"domain": "www.douyin.com", "path": "/", "name": "msToken", "value": "xyz"},
    ]
    p = auth.write_netscape_cookies(cookies, path=tmp_path / "douyin.txt")
    text = p.read_text(encoding="utf-8")
    assert ".douyin.com\tTRUE\t/\tTRUE\t0\tttwid\tabc" in text
    assert "www.douyin.com\tFALSE\t/\tFALSE\t0\tmsToken\txyz" in text


# ---------------------------------------------------------------------------
# validate_cookies fallback (risk-control 404 → cookie presence)
# ---------------------------------------------------------------------------


class _FailingClient:
    """Stands in for httpx.AsyncClient; every GET raises (simulates 404)."""

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, url):
        raise RuntimeError("simulated 404 Not Found")


def _write_cookie_file(path, names):
    cookies = [
        {"domain": ".douyin.com", "path": "/", "name": n, "value": "v"}
        for n in names
    ]
    return auth.write_netscape_cookies(cookies, path=path)


def test_validate_cookies_falls_back_to_session_cookie(monkeypatch, tmp_path):
    """API 404 (risk control) + sessionid present → still logged in."""
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _FailingClient)
    p = _write_cookie_file(tmp_path / "cookies.txt", ["ttwid", "sessionid", "msToken"])
    info = asyncio.run(auth.validate_cookies(p))
    assert info.is_logged_in is True
    assert info.raw["fallback"] == "cookie_presence"
    assert "sessionid" in info.raw["matched"]


def test_validate_cookies_fallback_guest_cookies_not_logged_in(monkeypatch, tmp_path):
    """API failure + guest-only cookies → must NOT report logged in."""
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _FailingClient)
    p = _write_cookie_file(tmp_path / "cookies.txt", ["ttwid", "msToken", "odin_tt"])
    info = asyncio.run(auth.validate_cookies(p))
    assert info.is_logged_in is False


def test_validate_cookies_fallback_no_file_not_logged_in(monkeypatch, tmp_path):
    """API failure + no cookie file → not logged in."""
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _FailingClient)
    info = asyncio.run(auth.validate_cookies(tmp_path / "missing.txt"))
    assert info.is_logged_in is False


def _fake_info_dict(**overrides) -> dict:
    base = {
        "id": "7123456789012345678", "title": "测试标题", "uploader": "测试作者",
        "uploader_id": "MS4wLjABAAAAxxxx", "uploader_avatar": "https://example.com/avatar.jpg",
        "thumbnail": "https://example.com/cover.jpg", "duration": 32.5,
        "timestamp": 1736899200, "view_count": 12345, "like_count": 678, "comment_count": 9,
        "formats": [{"vcodec": "h264", "acodec": "aac"}],
    }
    base.update(overrides)
    return base


def test_api_to_media_item_basic():
    api = DouyinAPI()
    item = api.to_media_item(_fake_info_dict(), "https://www.douyin.com/video/7123456789012345678")
    assert item.platform is Platform.DOUYIN
    assert item.item_id == "7123456789012345678"
    assert item.title == "测试标题"
    assert item.author.name == "测试作者"
    assert item.author.id == "MS4wLjABAAAAxxxx"
    assert item.cover_url == "https://example.com/cover.jpg"
    assert item.duration == 32.5
    assert item.media_type is MediaType.VIDEO
    assert item.extra["view_count"] == 12345
    assert item.publish_time == dt.datetime(2025, 1, 15, 0, 0, 0)


def test_api_to_media_item_picks_largest_thumbnail():
    info = _fake_info_dict()
    info["thumbnails"] = [
        {"url": "https://example.com/small.jpg", "height": 200, "width": 200},
        {"url": "https://example.com/large.jpg", "height": 1080, "width": 1920},
    ]
    info.pop("thumbnail", None)
    item = DouyinAPI().to_media_item(info, "x")
    assert item.cover_url == "https://example.com/large.jpg"


def test_api_to_media_item_classifies_image_album():
    info = _fake_info_dict()
    info["formats"] = []
    info["thumbnails"] = [{"url": "https://x/y.jpg"}]
    item = DouyinAPI().to_media_item(info, "x")
    assert item.media_type is MediaType.IMAGE_ALBUM


def test_api_to_media_item_classifies_live():
    info = _fake_info_dict()
    info["is_live"] = True
    item = DouyinAPI().to_media_item(info, "x")
    assert item.media_type is MediaType.LIVE


def test_api_to_media_item_empty_title_falls_back_to_description():
    info = _fake_info_dict(title="", description="从 description 取标题")
    item = DouyinAPI().to_media_item(info, "x")
    assert item.title == "从 description 取标题"


def test_api_flat_to_media_item_sparse():
    api = DouyinAPI()
    entry = {"id": "abc", "title": "sparse title", "uploader": "u",
             "thumbnails": [{"url": "https://x/t.jpg"}],
             "url": "https://www.douyin.com/video/abc"}
    item = api.flat_to_media_item(entry)
    assert item.item_id == "abc"
    assert item.title == "sparse title"
    assert item.author.name == "u"
    assert item.cover_url == "https://x/t.jpg"
    assert item.extra["_flat_entry"] is True


def test_api_fetch_returns_none_on_error(monkeypatch):
    api = DouyinAPI()
    class _BoomCtx:
        def __enter__(self): raise RuntimeError("simulated")
        def __exit__(self, *a): return False
    def _fake_ytdl(opts): return _BoomCtx()
    fake_mod = type("M", (), {"YoutubeDL": _fake_ytdl})
    monkeypatch.setattr(api, "_ytdlp", fake_mod)
    result = asyncio.run(api.fetch("https://www.douyin.com/video/1"))
    assert result is None


def _stub_api_for_entries(entries):
    api = DouyinAPI()
    async def _fake(url, *, playlist_items=None):
        return {"entries": entries}
    api.fetch_flat = _fake
    return api


def test_post_strategy_expand_extracts_sec_uid_and_returns_items():
    api = _stub_api_for_entries([
        {"id": "1", "title": "v1", "uploader": "u1", "url": "https://x/1"},
        {"id": "2", "title": "v2", "uploader": "u1", "url": "https://x/2"},
    ])
    s = PostStrategy(api)
    items = asyncio.run(s.expand("https://www.douyin.com/user/MS4wLjABAAAAxxxx", max_count=0))
    assert len(items) == 2
    assert items[0].item_id == "1"
    assert all(it.platform is Platform.DOUYIN for it in items)


def test_post_strategy_respects_max_count():
    api = _stub_api_for_entries([
        {"id": str(i), "title": f"v{i}", "uploader": "u", "url": f"https://x/{i}"}
        for i in range(10)
    ])
    s = PostStrategy(api)
    items = asyncio.run(s.expand("https://www.douyin.com/user/SEC", max_count=3))
    assert len(items) == 3


def test_post_strategy_non_user_url_returns_empty():
    s = PostStrategy(DouyinAPI())
    items = asyncio.run(s.expand("https://www.douyin.com/video/1"))
    assert items == []


def test_like_strategy_requires_cookies():
    s = LikeStrategy(DouyinAPI())
    items = asyncio.run(s.expand("https://www.douyin.com/user/SEC"))
    assert items == []


def test_like_strategy_with_cookies_returns_items():
    api = DouyinAPI(cookies_file="/tmp/c.txt")
    api.fetch_flat = _stub_api_for_entries([
        {"id": "1", "title": "liked1", "uploader": "u", "url": "https://x/1"},
    ]).fetch_flat
    s = LikeStrategy(api)
    items = asyncio.run(s.expand("https://www.douyin.com/user/SEC"))
    assert len(items) == 1


def test_adapter_instantiates_with_strategies():
    a = DouyinAdapter()
    assert a.api is not None
    strategies = {s.name for s in a.available_strategies()}
    assert "post" in strategies
    assert "like" in strategies


def test_adapter_get_strategy():
    a = DouyinAdapter()
    assert a.get_strategy("post") is not None
    assert a.get_strategy("nope") is None


def test_adapter_parse_user_returns_container_with_no_children_yet():
    a = DouyinAdapter()
    item = asyncio.run(a.parse("https://www.douyin.com/user/MS4wLjABAAAAxxxx"))
    assert item is not None
    assert item.media_type is MediaType.USER
    assert item.item_id == "MS4wLjABAAAAxxxx"
    assert item.children == []
    assert "post" in item.extra["available_strategies"]


def test_adapter_expand_container_populates_children(monkeypatch):
    a = DouyinAdapter()
    async def _fake_expand(strategy, *, max_count=0):
        return [MediaItem(
            platform=Platform.DOUYIN, item_id="c1", title="child",
            author=Author(name="u"), media_type=MediaType.VIDEO,
            source_url="https://x/c1",
        )]
    monkeypatch.setattr(a.get_strategy("post"), "expand", _fake_expand)
    item = asyncio.run(a.parse("https://www.douyin.com/user/SEC"))
    children = asyncio.run(a.expand(item, strategy="post"))
    assert len(children) == 1
    assert item.extra["applied_strategy"] == "post"


def test_adapter_parse_single_returns_minimal_item_when_api_fails(monkeypatch):
    a = DouyinAdapter()
    async def _fake_fetch(url): return None
    monkeypatch.setattr(a.api, "fetch", _fake_fetch)
    item = asyncio.run(a.parse("https://www.douyin.com/video/7123456789012345678"))
    assert item is not None
    assert item.item_id == "7123456789012345678"
    assert item.source_url.startswith("https://www.douyin.com/")


def test_adapter_parse_single_populates_metadata(monkeypatch):
    a = DouyinAdapter()
    async def _fake_fetch(url): return _fake_info_dict()
    monkeypatch.setattr(a.api, "fetch", _fake_fetch)
    item = asyncio.run(a.parse("https://www.douyin.com/video/7123456789012345678"))
    assert item.title == "测试标题"
    assert item.author.name == "测试作者"


def test_adapter_parse_modal_id_url_is_canonicalized(monkeypatch):
    """Feed/modal URLs (/jingxuan?modal_id=...) must be rewritten to the
    canonical /video/{id} form before hitting yt-dlp and before being
    stored as source_url — yt-dlp's extractor doesn't understand modal_id.
    """
    a = DouyinAdapter()
    seen = {}
    async def _fake_fetch(url):
        seen["fetch_url"] = url
        return None
    monkeypatch.setattr(a.api, "fetch", _fake_fetch)
    item = asyncio.run(a.parse("https://www.douyin.com/jingxuan?modal_id=7676517073484352822"))
    assert item is not None
    assert item.item_id == "7676517073484352822"
    canonical = "https://www.douyin.com/video/7676517073484352822"
    assert seen["fetch_url"] == canonical
    assert item.source_url == canonical


def test_adapter_parse_video_url_is_not_rewritten(monkeypatch):
    """Already-canonical /video/{id} URLs must pass through unchanged."""
    a = DouyinAdapter()
    seen = {}
    async def _fake_fetch(url):
        seen["fetch_url"] = url
        return None
    monkeypatch.setattr(a.api, "fetch", _fake_fetch)
    url = "https://www.douyin.com/video/7123456789012345678?extra=1"
    item = asyncio.run(a.parse(url))
    assert seen["fetch_url"] == url
    assert item.source_url == url


# pipeline

class _SpyEngine:
    name = "spy"
    def supports(self, item): return True
    async def download(self, item, options, *, on_progress=None):
        return True


def test_pipeline_renders_output_template_before_engine_call(monkeypatch, tmp_path):
    import doubi.core.pipeline as pipeline_mod
    captured = {}
    class _SpyEngine:
        name = "spy"
        def supports(self, item): return True
        async def download(self, item, options, *, on_progress=None):
            captured["template"] = item.output_template
            return True
    pipeline = pipeline_mod.DownloadPipeline(engine=_SpyEngine())
    options = DownloadOptions(output_root=tmp_path)
    item = MediaItem(
        platform=Platform.DOUYIN, item_id="7123456789012345678", title="测试标题",
        author=Author(name="张三"), duration=10.0,
        publish_time=dt.datetime(2026, 1, 15), media_type=MediaType.VIDEO,
        source_url="https://www.douyin.com/video/7123456789012345678",
    )
    async def _fake_parse(url): return item
    monkeypatch.setattr(pipeline, "parse", _fake_parse)
    result = asyncio.run(pipeline.process_url(item.source_url, options))
    assert result is not None
    assert "测试标题" in captured["template"]


def test_pipeline_container_recursion(monkeypatch):
    import doubi.core.pipeline as pipeline_mod
    pipeline = pipeline_mod.DownloadPipeline(engine=_SpyEngine(), max_concurrent=2)
    child = MediaItem(platform=Platform.DOUYIN, item_id="c1", title="c",
                      author=Author(), media_type=MediaType.VIDEO, source_url="https://x/c1")
    container = MediaItem(platform=Platform.DOUYIN, item_id="SEC", title="user",
                          author=Author(), media_type=MediaType.USER,
                          source_url="https://www.douyin.com/user/SEC", children=[child])
    async def _fake_parse(url): return container
    monkeypatch.setattr(pipeline, "parse", _fake_parse)
    from doubi.platforms.douyin.adapter import DouyinAdapter
    async def _fake_expand(self, item, *, strategy="post", max_count=0):
        return [child]
    monkeypatch.setattr(DouyinAdapter, "expand", _fake_expand)
    result = asyncio.run(
        pipeline.process_url(container.source_url, DownloadOptions(output_root=Path("./out")))
    )
    assert result is not None
    assert result.extra.get("downloaded_count") == 1


# Root cause these two cover: ``_process_container`` set
# ``downloaded_count = len(children)`` — the number of items *attempted* —
# and threw away the DownloadJob returned by ``process_batch``, which held
# the only record of what actually succeeded. A playlist where every child
# failed still claimed a full house.
#
# 判据: downloaded_count counts successes only, failed_count counts the
# rest, and child_count keeps the attempted total, so the three are
# asserted separately rather than as a sum.

def test_pipeline_container_records_partial_failure(monkeypatch):
    import doubi.core.pipeline as pipeline_mod

    class _FlakyEngine:
        name = "flaky"
        def supports(self, item): return True
        async def download(self, item, options, *, on_progress=None):
            return item.item_id != "bad"

    pipeline = pipeline_mod.DownloadPipeline(engine=_FlakyEngine(), max_concurrent=2)
    good = MediaItem(platform=Platform.DOUYIN, item_id="good", title="g",
                     author=Author(), media_type=MediaType.VIDEO, source_url="https://x/good")
    bad = MediaItem(platform=Platform.DOUYIN, item_id="bad", title="b",
                    author=Author(), media_type=MediaType.VIDEO, source_url="https://x/bad")
    container = MediaItem(platform=Platform.DOUYIN, item_id="SEC", title="user",
                          author=Author(), media_type=MediaType.USER,
                          source_url="https://www.douyin.com/user/SEC",
                          children=[good, bad])
    async def _fake_parse(url): return container
    monkeypatch.setattr(pipeline, "parse", _fake_parse)
    from doubi.platforms.douyin.adapter import DouyinAdapter
    async def _fake_expand(self, item, *, strategy="post", max_count=0):
        return [good, bad]
    monkeypatch.setattr(DouyinAdapter, "expand", _fake_expand)

    result = asyncio.run(
        pipeline.process_url(container.source_url, DownloadOptions(output_root=Path("./out")))
    )
    assert result.extra["downloaded_count"] == 1
    assert result.extra["failed_count"] == 1
    assert result.extra["child_count"] == 2


def test_process_batch_reports_real_counts(monkeypatch):
    """DownloadJob.completed_count/failed_count must reflect outcomes."""
    import doubi.core.pipeline as pipeline_mod

    class _FlakyEngine:
        name = "flaky"
        def supports(self, item): return True
        async def download(self, item, options, *, on_progress=None):
            if item.item_id == "boom":
                raise RuntimeError("engine exploded")
            return item.item_id == "good"

    pipeline = pipeline_mod.DownloadPipeline(engine=_FlakyEngine(), max_concurrent=3)
    items = [
        MediaItem(platform=Platform.DOUYIN, item_id=iid, title=iid, author=Author(),
                  media_type=MediaType.VIDEO, source_url=f"https://x/{iid}")
        for iid in ("good", "bad", "boom")
    ]
    job = asyncio.run(
        pipeline.process_batch(items, DownloadOptions(output_root=Path("./out")))
    )
    assert job.total_count() == 3
    assert job.completed_count() == 1
    assert job.failed_count() == 2
    assert job.status == "completed"  # partial success is still 'completed'


def test_process_batch_status_failed_when_nothing_succeeds(monkeypatch):
    import doubi.core.pipeline as pipeline_mod

    class _DeadEngine:
        name = "dead"
        def supports(self, item): return True
        async def download(self, item, options, *, on_progress=None):
            return False

    pipeline = pipeline_mod.DownloadPipeline(engine=_DeadEngine())
    items = [MediaItem(platform=Platform.DOUYIN, item_id="a", title="a", author=Author(),
                       media_type=MediaType.VIDEO, source_url="https://x/a")]
    job = asyncio.run(
        pipeline.process_batch(items, DownloadOptions(output_root=Path("./out")))
    )
    assert job.completed_count() == 0
    assert job.failed_count() == 1
    assert job.status == "failed"


def test_pipeline_parse_and_expand_single_item(monkeypatch):
    """A single-item URL returns (item, [])."""
    import doubi.core.pipeline as pipeline_mod
    pipeline = pipeline_mod.DownloadPipeline(engine=_SpyEngine())
    single = MediaItem(platform=Platform.DOUYIN, item_id="v1", title="v",
                       author=Author(), media_type=MediaType.VIDEO, source_url="https://x/v1")
    async def _fake_parse(url): return single
    monkeypatch.setattr(pipeline, "parse", _fake_parse)
    item, children = asyncio.run(pipeline.parse_and_expand("https://x/v1"))
    assert item is single
    assert children == []


def test_pipeline_parse_and_expand_container(monkeypatch):
    """A container URL expands into its children."""
    import doubi.core.pipeline as pipeline_mod
    pipeline = pipeline_mod.DownloadPipeline(engine=_SpyEngine())
    children = [
        MediaItem(platform=Platform.DOUYIN, item_id=f"c{i}", title=f"c{i}",
                  author=Author(), media_type=MediaType.VIDEO, source_url=f"https://x/c{i}")
        for i in range(3)
    ]
    container = MediaItem(platform=Platform.DOUYIN, item_id="SEC", title="user",
                          author=Author(), media_type=MediaType.USER,
                          source_url="https://www.douyin.com/user/SEC", children=[])
    async def _fake_parse(url): return container
    monkeypatch.setattr(pipeline, "parse", _fake_parse)
    from doubi.platforms.douyin.adapter import DouyinAdapter
    async def _fake_expand(self, item, *, strategy="post", max_count=0):
        return children
    monkeypatch.setattr(DouyinAdapter, "expand", _fake_expand)
    item, got = asyncio.run(pipeline.parse_and_expand("https://x/user", strategy="post"))
    assert item is container
    assert len(got) == 3
    assert got == children


def test_pipeline_parse_and_expand_failure(monkeypatch):
    """Parse failure returns (None, [])."""
    import doubi.core.pipeline as pipeline_mod
    pipeline = pipeline_mod.DownloadPipeline(engine=_SpyEngine())
    async def _fake_parse(url): return None
    monkeypatch.setattr(pipeline, "parse", _fake_parse)
    item, children = asyncio.run(pipeline.parse_and_expand("https://x/bad"))
    assert item is None
    assert children == []


def test_adapter_parse_user_modal_id_url_is_canonicalized(monkeypatch):
    """User-profile URLs carrying modal_id (video opened from the
    profile's 合集/compilation tab) must be treated as that single
    video and rewritten to /video/{id} — NOT expanded as a USER
    container (which would try to download the whole profile)."""
    a = DouyinAdapter()
    seen = {}

    async def _fake_fetch(url):
        seen["fetch_url"] = url
        return None

    monkeypatch.setattr(a.api, "fetch", _fake_fetch)
    item = asyncio.run(a.parse(
        "https://www.douyin.com/user/MS4wLjABAAAAxOhRVmiuLmYd089wiv1NYCyMXrJWG-qY3AwNDUDlTun9-9YScGFs0q1T70UnNosh"
        "?from_tab_name=main&modal_id=7647081804364516651&relation=0&showSubTab=compilation&vid=7647081804364516651"
    ))
    assert item is not None
    assert item.item_id == "7647081804364516651"
    assert item.media_type is not MediaType.USER
    canonical = "https://www.douyin.com/video/7647081804364516651"
    assert seen["fetch_url"] == canonical
    assert item.source_url == canonical
