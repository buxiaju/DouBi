"""M3u8Engine aiohttp 路径的 master playlist 解析测试。

aiohttp 是 ffmpeg 不可用/无 TLS 时的降级路径。``_fetch_segments``
曾把 master playlist 的变体 URI 当分片下载——产出的是几个 m3u8
文本拼成的垃圾「视频」。修复后选带宽最高的变体递归到媒体列表。
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

from doubi.core.models import DownloadOptions  # noqa: E402
from doubi.engines.m3u8 import (  # noqa: E402
    M3u8Engine,
    _pick_best_variant,
)


class _FakeResp:
    def __init__(self, text):
        self._text = text

    def raise_for_status(self):
        return None

    async def text(self):
        return self._text


class _FakeSession:
    """按 URL 返回预设文本的 aiohttp.ClientSession 替身。"""

    def __init__(self, pages: dict[str, str]):
        self._pages = pages
        self.requested: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def get(self, url, proxy=None):
        self.requested.append(url)
        if url not in self._pages:
            raise AssertionError(f"unexpected playlist request: {url}")
        return _FakeCtx(self._pages[url])


class _FakeCtx:
    def __init__(self, text):
        self._text = text

    async def __aenter__(self):
        return _FakeResp(self._text)

    async def __aexit__(self, *a):
        return False


class _FakeAiohttp:
    def __init__(self, session):
        self._session = session

    def ClientSession(self):
        return self._session


MASTER = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=480000,RESOLUTION=640x360,CODECS="avc1.42e00a,mp4a.40.2"
/video/low/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=1920000,RESOLUTION=1920x1080,CODECS="avc1.640028,mp4a.40.2"
/video/high/index.m3u8
"""

MEDIA = """#EXTM3U
#EXT-X-TARGETDURATION:10
#EXTINF:10.0,
seg-001.ts
#EXTINF:10.0,
seg-002.ts
"""


def _options(tmp_path) -> DownloadOptions:
    return DownloadOptions(output_root=tmp_path)


def test_master_playlist_picks_highest_bandwidth_variant(tmp_path):
    """master playlist 选带宽最高变体并递归到媒体分片（绝对 URL）。"""
    session = _FakeSession({
        "https://cdn.example.com/video/index.m3u8": MASTER,
        "https://cdn.example.com/video/high/index.m3u8": MEDIA,
    })
    engine = M3u8Engine()

    segments = asyncio.run(
        engine._fetch_segments(_FakeAiohttp(session),
                               "https://cdn.example.com/video/index.m3u8",
                               _options(tmp_path))
    )

    assert segments == [
        "https://cdn.example.com/video/high/seg-001.ts",
        "https://cdn.example.com/video/high/seg-002.ts",
    ]
    # low 变体绝不能被请求
    assert all("low" not in u for u in session.requested)


def test_media_playlist_passthrough_unchanged(tmp_path):
    """媒体播放列表行为不变：相对分片 urljoin 到播放列表目录。"""
    session = _FakeSession({
        "https://cdn.example.com/video/high/index.m3u8": MEDIA,
    })
    engine = M3u8Engine()

    segments = asyncio.run(
        engine._fetch_segments(_FakeAiohttp(session),
                               "https://cdn.example.com/video/high/index.m3u8",
                               _options(tmp_path))
    )
    assert segments == [
        "https://cdn.example.com/video/high/seg-001.ts",
        "https://cdn.example.com/video/high/seg-002.ts",
    ]


def test_pick_best_variant_prefers_bandwidth_over_order():
    """变体乱序（低码率在前）时仍选带宽最高的。"""
    text = (
        "#EXTM3U\n"
        '#EXT-X-STREAM-INF:BANDWIDTH=480000\n'
        "/low.m3u8\n"
        '#EXT-X-STREAM-INF:BANDWIDTH=1920000\n'
        "/high.m3u8\n"
    )
    assert _pick_best_variant(text, "https://x.com/h/index.m3u8") == "https://x.com/high.m3u8"


def test_pick_best_variant_root_relative_uri():
    """根相对 URI 正确 urljoin（注入广告分片的站点常见形态）。"""
    text = (
        "#EXTM3U\n"
        '#EXT-X-STREAM-INF:BANDWIDTH=1280000\n'
        "/vod/main/index.m3u8\n"
    )
    assert _pick_best_variant(text, "https://x.com/a/b/list.m3u8") == "https://x.com/vod/main/index.m3u8"


def test_master_without_variant_uri_raises():
    """有 STREAM-INF 却没有变体 URI → 报错而非静默空分片。"""
    text = "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000\n"
    with pytest.raises(ValueError, match="no variant URI"):
        _pick_best_variant(text, "https://x.com/h/index.m3u8")


def test_master_recursion_depth_bounded(tmp_path):
    """套娃 master playlist 有深度上限，不会无限递归。"""
    # 每层都指向下一层（同 URL 自指最省事）
    loop = (
        "#EXTM3U\n"
        '#EXT-X-STREAM-INF:BANDWIDTH=1000\n'
        "next.m3u8\n"
    )
    session = _FakeSession({
        "https://x.com/l0.m3u8": loop,
        "https://x.com/next.m3u8": loop,
    })
    engine = M3u8Engine()
    with pytest.raises(ValueError, match="recursion"):
        asyncio.run(
            engine._fetch_segments(_FakeAiohttp(session),
                                   "https://x.com/l0.m3u8",
                                   _options(tmp_path))
        )
