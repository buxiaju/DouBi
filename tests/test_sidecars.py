"""Tests for the opt-in sidecars added in P0 (NFO + B 站 danmaku).

Root cause these cover:
    ``DownloadOptions.write_nfo`` / ``write_danmaku`` were reachable from
    the CLI (``--nfo`` / ``--danmaku``) and the config file, but nothing
    in the pipeline or the engine ever read them, so both switches
    silently did nothing.

判据:
    * ``write_nfo`` → a ``<basename>.nfo`` appears beside the media file
      with the item's real metadata (NOT yt-dlp's ``writeinfojson``
      schema, which no media library can read).
    * ``write_danmaku`` → the adapter hook resolves the page's ``cid``
      and writes ``<basename>.danmaku.xml``.
    * Both switches off → no sidecar is written at all.
"""

from __future__ import annotations

import asyncio
import sys
import zlib
from pathlib import Path

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


def _make_item(**kw) -> MediaItem:
    defaults = dict(
        platform=Platform.BILIBILI,
        item_id="BV1zygDzDES2",
        title="测试视频",
        author=Author(id="123", name="UP主"),
        media_type=MediaType.VIDEO,
        source_url="https://www.bilibili.com/video/BV1zygDzDES2",
        duration=185.0,
        cover_url="https://i0.hdslb.com/cover.jpg",
    )
    defaults.update(kw)
    item = MediaItem(**defaults)
    item.output_template = "测试视频_BV1zygDzDES2"
    return item


def _make_options(tmp_path, **kw) -> DownloadOptions:
    opts = DownloadOptions(
        output_root=tmp_path,
        filename_template="{title}_{item_id}",
    )
    for k, v in kw.items():
        setattr(opts, k, v)
    return opts


# ---------------------------------------------------------------------------
# NFO
# ---------------------------------------------------------------------------

def test_nfo_xml_contains_item_metadata():
    from doubi.core.storage.nfo import build_nfo_xml

    item = _make_item()
    item.extra["description"] = "简介内容"
    xml = build_nfo_xml(item)

    assert "<movie" in xml
    assert "<title>测试视频</title>" in xml
    assert "<plot>简介内容</plot>" in xml
    # Kodi expects runtime in whole minutes, not seconds: 185s → 3min.
    assert "<runtime>3</runtime>" in xml
    assert "<studio>UP主</studio>" in xml
    assert "bilibili" in xml


def test_nfo_omits_empty_fields():
    """A missing tag reads as "unknown"; an empty tag can render as a
    blank title in a scraper, so empty values must be dropped."""
    from doubi.core.storage.nfo import build_nfo_xml

    item = _make_item(title="仅标题", author=Author(), cover_url=None, duration=None)
    xml = build_nfo_xml(item)

    assert "<title>仅标题</title>" in xml
    for tag in ("<studio>", "<director>", "<thumb>", "<runtime>", "<plot>"):
        assert tag not in xml


def test_write_nfo_creates_file(tmp_path):
    from doubi.core.storage.nfo import write_nfo

    item = _make_item()
    target = tmp_path / "out"
    path = write_nfo(item, target, "测试视频_BV1zygDzDES2")

    assert path is not None
    assert path.name == "测试视频_BV1zygDzDES2.nfo"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("<?xml")
    assert "测试视频" in text


def test_pipeline_writes_nfo_when_enabled(tmp_path):
    """End-to-end through the post-download stage."""
    from doubi.core.pipeline import DownloadPipeline

    pipeline = DownloadPipeline.__new__(DownloadPipeline)
    item = _make_item()
    opts = _make_options(tmp_path, write_nfo=True)

    asyncio.run(pipeline._run_post_download(item, opts, "job1234", None))

    found = list(tmp_path.rglob("*.nfo"))
    assert len(found) == 1, f"expected exactly one NFO, got {found}"


def test_pipeline_writes_no_nfo_when_disabled(tmp_path):
    from doubi.core.pipeline import DownloadPipeline

    pipeline = DownloadPipeline.__new__(DownloadPipeline)
    opts = _make_options(tmp_path, write_nfo=False)

    asyncio.run(pipeline._run_post_download(_make_item(), opts, "job1234", None))

    assert list(tmp_path.rglob("*.nfo")) == []


def test_default_adapter_hook_is_not_treated_as_override():
    """The base class defines a no-op ``post_download``; the pipeline must
    not fire a ``postprocess`` event for adapters that only inherit it."""
    from doubi.core.pipeline import DownloadPipeline
    from doubi.platforms.base import PlatformAdapter

    class _Plain(PlatformAdapter):
        @property
        def platform(self):
            return Platform.DOUYIN

        def matches(self, url: str) -> bool:
            return False

        async def parse(self, url: str):
            return None

    class _Custom(_Plain):
        async def post_download(self, item, options) -> None:
            return None

    assert DownloadPipeline._overrides_post_download(_Plain()) is False
    assert DownloadPipeline._overrides_post_download(_Custom()) is True


# ---------------------------------------------------------------------------
# danmaku
# ---------------------------------------------------------------------------

class _FakeAPI:
    """Stands in for BilibiliAPI: records calls, returns canned pages."""

    timeout = 5

    def __init__(self, pages=None):
        self._pages = pages
        self.view_calls: list[str] = []

    def build_cookie_header(self) -> str:
        return "SESSDATA=x; buvid3=y"

    async def fetch_view_pages(self, bvid: str):
        self.view_calls.append(bvid)
        return self._pages


def test_extract_bvid_from_multipage_child():
    """分P children carry synthetic ids like ``BV1xx_p3``, so the raw id
    is not a usable bvid — ``parent_bvid`` must win."""
    from doubi.platforms.bilibili.danmaku import extract_bvid, extract_page_index

    item = _make_item(
        item_id="BV1zygDzDES2_p3",
        source_url="https://www.bilibili.com/video/BV1zygDzDES2?p=3",
    )
    item.extra["parent_bvid"] = "BV1zygDzDES2"
    item.extra["page_index"] = 3

    assert extract_bvid(item) == "BV1zygDzDES2"
    assert extract_page_index(item) == 3


def test_extract_page_index_falls_back_to_url():
    from doubi.platforms.bilibili.danmaku import extract_page_index

    item = _make_item(source_url="https://www.bilibili.com/video/BV1zygDzDES2?p=7")
    assert extract_page_index(item) == 7
    assert extract_page_index(_make_item()) == 1


def test_resolve_cid_prefers_extra_and_skips_http():
    from doubi.platforms.bilibili.danmaku import resolve_cid

    api = _FakeAPI(pages=[{"page": 1, "cid": 999}])
    item = _make_item()
    item.extra["cid"] = 4242

    cid = asyncio.run(resolve_cid(api, item))

    assert cid == 4242
    assert api.view_calls == [], "a known cid must not trigger an API call"


def test_resolve_cid_matches_declared_page_number():
    """分P numbering can have gaps (deleted pages), so the page number —
    not the list position — decides which cid we take."""
    from doubi.platforms.bilibili.danmaku import resolve_cid

    api = _FakeAPI(pages=[
        {"page": 1, "cid": 100},
        {"page": 3, "cid": 300},
    ])
    item = _make_item(item_id="BV1zygDzDES2_p3")
    item.extra["parent_bvid"] = "BV1zygDzDES2"
    item.extra["page_index"] = 3

    assert asyncio.run(resolve_cid(api, item)) == 300
    assert api.view_calls == ["BV1zygDzDES2"]


def test_resolve_cid_returns_none_without_pages():
    from doubi.platforms.bilibili.danmaku import resolve_cid

    assert asyncio.run(resolve_cid(_FakeAPI(pages=None), _make_item())) is None


def test_decode_body_handles_raw_deflate_and_plain_xml():
    """``list.so`` answers with header-less deflate, which no HTTP client
    decompresses for us; it sometimes answers with plain XML instead."""
    from doubi.platforms.bilibili.danmaku import _decode_body

    xml = "<i><d p='1'>弹幕</d></i>"
    compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    raw = compressor.compress(xml.encode("utf-8")) + compressor.flush()

    assert _decode_body(raw) == xml
    assert _decode_body(xml.encode("utf-8")) == xml
    assert _decode_body(b"") is None


def test_write_danmaku_places_file_beside_media(tmp_path):
    from doubi.platforms.bilibili.danmaku import write_danmaku
    from doubi.core.storage.file_layout import resolve_item_dir

    item = _make_item()
    opts = _make_options(tmp_path)
    path = write_danmaku(item, opts, "<i></i>")

    assert path is not None
    assert path.name == "测试视频_BV1zygDzDES2.danmaku.xml"
    assert path.parent == resolve_item_dir(item, opts)


def test_write_danmaku_needs_output_template(tmp_path):
    """Without a resolved basename the sidecar could not pair with the
    media file, so it must be skipped rather than guessed."""
    from doubi.platforms.bilibili.danmaku import write_danmaku

    item = _make_item()
    item.output_template = None
    assert write_danmaku(item, _make_options(tmp_path), "<i></i>") is None


def test_adapter_hook_respects_switch(tmp_path, monkeypatch):
    from doubi.platforms.bilibili.adapter import BilibiliAdapter
    from doubi.platforms.bilibili import danmaku as danmaku_mod

    calls: list[str] = []

    async def _fake_download(api, item, options):
        calls.append(item.item_id)
        return None

    monkeypatch.setattr(danmaku_mod, "download_danmaku", _fake_download)
    adapter = BilibiliAdapter()

    asyncio.run(adapter.post_download(
        _make_item(), _make_options(tmp_path, write_danmaku=False)))
    assert calls == []

    asyncio.run(adapter.post_download(
        _make_item(), _make_options(tmp_path, write_danmaku=True)))
    assert calls == ["BV1zygDzDES2"]


def test_adapter_hook_skips_containers(tmp_path, monkeypatch):
    """Containers are never downloaded themselves — their children are —
    so a container must not produce a stray sidecar."""
    from doubi.platforms.bilibili.adapter import BilibiliAdapter
    from doubi.platforms.bilibili import danmaku as danmaku_mod

    calls: list[str] = []

    async def _fake_download(api, item, options):
        calls.append(item.item_id)
        return None

    monkeypatch.setattr(danmaku_mod, "download_danmaku", _fake_download)

    container = _make_item(media_type=MediaType.COLLECTION)
    container.children = [_make_item(item_id="BV1zygDzDES2_p1")]

    asyncio.run(BilibiliAdapter().post_download(
        container, _make_options(tmp_path, write_danmaku=True)))

    assert calls == []


def test_download_danmaku_never_raises(tmp_path, monkeypatch):
    """The media file is already on disk; a sidecar failure must not
    escalate into a failed download."""
    from doubi.platforms.bilibili import danmaku as danmaku_mod

    async def _boom(api, item):
        raise RuntimeError("network exploded")

    monkeypatch.setattr(danmaku_mod, "resolve_cid", _boom)

    result = asyncio.run(danmaku_mod.download_danmaku(
        _FakeAPI(), _make_item(), _make_options(tmp_path)))

    assert result is None
