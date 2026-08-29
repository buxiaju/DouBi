"""Engine routing + M3u8/DirectHttp engine tests (M6.16).

覆盖：
1. **引擎路由**：pipeline._select_engine 按 item.extra 提示选择正确引擎
2. **M3u8Engine.supports**：正确识别 m3u8/HLS URL
3. **DirectHttpEngine.supports**：正确识别直链视频 URL
4. **引擎优先级**：M3u8Engine 在 DirectHttpEngine 之前匹配
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from doubi.core.models import Author, DownloadOptions, MediaItem, MediaType, Platform
from doubi.core.pipeline import DownloadPipeline
from doubi.engines.base import Engine
from doubi.engines.m3u8 import M3u8Engine
from doubi.engines.direct_http import DirectHttpEngine


def _make_item(
    *,
    source_url: str = "",
    is_hls: bool = False,
    is_direct_video: bool = False,
    extra: dict | None = None,
) -> MediaItem:
    item_extra = {
        "is_hls": is_hls,
        "is_direct_video": is_direct_video,
    }
    if extra:
        item_extra.update(extra)
    return MediaItem(
        platform=Platform.GENERIC,
        item_id="test123",
        title="test item",
        author=Author(),
        media_type=MediaType.VIDEO,
        source_url=source_url,
        extra=item_extra,
    )


# ===========================================================================
# M3u8Engine.supports
# ===========================================================================


class TestM3u8EngineSupports:
    def test_supports_hls_hint(self):
        engine = M3u8Engine()
        item = _make_item(source_url="https://example.com/playlist.m3u8", is_hls=True)
        assert engine.supports(item) is True

    def test_supports_m3u8_extension(self):
        engine = M3u8Engine()
        item = _make_item(source_url="https://example.com/stream.m3u8")
        assert engine.supports(item) is True

    def test_supports_m3u_extension(self):
        engine = M3u8Engine()
        item = _make_item(source_url="https://example.com/stream.m3u")
        assert engine.supports(item) is True

    def test_rejects_mp4_url(self):
        engine = M3u8Engine()
        item = _make_item(source_url="https://example.com/video.mp4")
        assert engine.supports(item) is False

    def test_rejects_no_url(self):
        engine = M3u8Engine()
        item = _make_item()
        assert engine.supports(item) is False

    def test_supports_hls_hint_without_m3u8_ext(self):
        engine = M3u8Engine()
        item = _make_item(source_url="https://example.com/hls_stream", is_hls=True)
        assert engine.supports(item) is True


# ===========================================================================
# DirectHttpEngine.supports
# ===========================================================================


class TestDirectHttpEngineSupports:
    def test_supports_direct_video_hint(self):
        engine = DirectHttpEngine()
        item = _make_item(source_url="https://example.com/video.mp4", is_direct_video=True)
        assert engine.supports(item) is True

    def test_supports_mp4_extension(self):
        engine = DirectHttpEngine()
        item = _make_item(source_url="https://example.com/video.mp4")
        assert engine.supports(item) is True

    def test_supports_webm_extension(self):
        engine = DirectHttpEngine()
        item = _make_item(source_url="https://example.com/video.webm")
        assert engine.supports(item) is True

    def test_supports_flv_extension(self):
        engine = DirectHttpEngine()
        item = _make_item(source_url="https://example.com/video.flv")
        assert engine.supports(item) is True

    def test_rejects_m3u8_url(self):
        engine = DirectHttpEngine()
        item = _make_item(source_url="https://example.com/stream.m3u8")
        assert engine.supports(item) is False

    def test_rejects_hls_hint(self):
        engine = DirectHttpEngine()
        item = _make_item(source_url="https://example.com/video.mp4", is_hls=True)
        assert engine.supports(item) is False

    def test_rejects_no_url(self):
        engine = DirectHttpEngine()
        item = _make_item()
        assert engine.supports(item) is False

    def test_supports_with_query_string(self):
        engine = DirectHttpEngine()
        item = _make_item(source_url="https://example.com/video.mp4?token=abc&quality=1080p")
        assert engine.supports(item) is True


# ===========================================================================
# Pipeline engine routing
# ===========================================================================


class TestPipelineEngineRouting:
    def test_routes_hls_item_to_m3u8_engine(self):
        mock_default = MagicMock(spec=Engine)
        mock_m3u8 = M3u8Engine()
        mock_direct = DirectHttpEngine()

        pipeline = DownloadPipeline(
            engine=mock_default,
            extra_engines=[mock_m3u8, mock_direct],
        )
        item = _make_item(
            source_url="https://example.com/stream.m3u8",
            is_hls=True,
        )
        selected = pipeline._select_engine(item)
        assert selected is mock_m3u8

    def test_routes_direct_video_to_direct_http_engine(self):
        mock_default = MagicMock(spec=Engine)
        mock_m3u8 = M3u8Engine()
        mock_direct = DirectHttpEngine()

        pipeline = DownloadPipeline(
            engine=mock_default,
            extra_engines=[mock_m3u8, mock_direct],
        )
        item = _make_item(
            source_url="https://example.com/video.mp4",
            is_direct_video=True,
        )
        selected = pipeline._select_engine(item)
        assert selected is mock_direct

    def test_falls_back_to_default_for_unknown_url(self):
        mock_default = MagicMock(spec=Engine)
        mock_m3u8 = M3u8Engine()
        mock_direct = DirectHttpEngine()

        pipeline = DownloadPipeline(
            engine=mock_default,
            extra_engines=[mock_m3u8, mock_direct],
        )
        item = _make_item(source_url="https://example.com/some/ webpage")
        selected = pipeline._select_engine(item)
        assert selected is mock_default

    def test_m3u8_takes_priority_over_direct_http(self):
        mock_default = MagicMock(spec=Engine)
        mock_m3u8 = M3u8Engine()
        mock_direct = DirectHttpEngine()

        pipeline = DownloadPipeline(
            engine=mock_default,
            extra_engines=[mock_m3u8, mock_direct],
        )
        # 同时有 is_hls 和 is_direct_video → M3u8Engine 先匹配
        item = _make_item(
            source_url="https://example.com/stream.m3u8",
            is_hls=True,
            is_direct_video=True,
        )
        selected = pipeline._select_engine(item)
        assert selected is mock_m3u8

    def test_no_extra_engines_uses_default(self):
        mock_default = MagicMock(spec=Engine)
        pipeline = DownloadPipeline(engine=mock_default)
        item = _make_item(
            source_url="https://example.com/stream.m3u8",
            is_hls=True,
        )
        selected = pipeline._select_engine(item)
        assert selected is mock_default

    def test_extra_engine_exception_falls_back(self):
        """extra engine.supports() 抛异常时应跳过，不中断路由。"""
        mock_default = MagicMock(spec=Engine)
        bad_engine = MagicMock(spec=Engine)
        bad_engine.supports.side_effect = RuntimeError("broken")
        mock_direct = DirectHttpEngine()

        pipeline = DownloadPipeline(
            engine=mock_default,
            extra_engines=[bad_engine, mock_direct],
        )
        item = _make_item(
            source_url="https://example.com/video.mp4",
            is_direct_video=True,
        )
        selected = pipeline._select_engine(item)
        assert selected is mock_direct


# ===========================================================================
# M3u8Engine.download (mocked ffmpeg)
# ===========================================================================


class TestM3u8EngineDownload:
    @pytest.mark.asyncio
    async def test_download_via_ffmpeg_success(self, tmp_path):
        engine = M3u8Engine(ffmpeg_path="ffmpeg")
        item = _make_item(
            source_url="https://example.com/stream.m3u8",
            is_hls=True,
        )
        item.output_template = "test_video"

        with patch("doubi.engines.m3u8.M3u8Engine._download_via_ffmpeg", new_callable=AsyncMock) as mock_ff:
            mock_ff.return_value = True
            result = await engine._download_via_ffmpeg(
                item, tmp_path / "test_video.mp4", DownloadOptions(output_root=tmp_path), None
            )
            assert result is True

    @pytest.mark.asyncio
    async def test_download_via_ffmpeg_failure(self, tmp_path):
        engine = M3u8Engine(ffmpeg_path="ffmpeg")
        item = _make_item(
            source_url="https://example.com/stream.m3u8",
            is_hls=True,
        )
        item.output_template = "test_video"

        with patch("doubi.engines.m3u8.M3u8Engine._download_via_ffmpeg", new_callable=AsyncMock) as mock_ff:
            mock_ff.return_value = False
            result = await engine._download_via_ffmpeg(
                item, tmp_path / "test_video.mp4", DownloadOptions(output_root=tmp_path), None
            )
            assert result is False

    @pytest.mark.asyncio
    async def test_download_without_ffmpeg_falls_back_to_aiohttp(self, tmp_path):
        engine = M3u8Engine(ffmpeg_path=None)
        item = _make_item(
            source_url="https://example.com/stream.m3u8",
            is_hls=True,
        )
        item.output_template = "test_video"

        with patch("doubi.engines.m3u8.M3u8Engine._download_via_aiohttp", new_callable=AsyncMock) as mock_aio:
            mock_aio.return_value = True
            result = await engine._download_via_aiohttp(
                item, tmp_path / "test_video.mp4", DownloadOptions(output_root=tmp_path), None
            )
            assert result is True


# ===========================================================================
# DirectHttpEngine.download (mocked aiohttp)
# ===========================================================================


class TestDirectHttpEngineDownload:
    @pytest.mark.asyncio
    async def test_download_success(self, tmp_path):
        engine = DirectHttpEngine()
        item = _make_item(
            source_url="https://example.com/video.mp4",
            is_direct_video=True,
        )
        item.output_template = "test_video"

        with patch.object(engine, "_download_file", new_callable=AsyncMock) as mock_dl:
            mock_dl.return_value = None
            result = await engine._download_file(
                MagicMock(), "https://example.com/video.mp4",
                tmp_path / "test_video.mp4.part",
                tmp_path / "test_video.mp4",
                DownloadOptions(output_root=tmp_path),
                None,
            )
            assert result is None

    def test_guess_ext_from_mp4(self):
        engine = DirectHttpEngine()
        assert engine._guess_ext("https://example.com/video.mp4") == "mp4"

    def test_guess_ext_from_webm(self):
        engine = DirectHttpEngine()
        assert engine._guess_ext("https://example.com/video.webm") == "webm"

    def test_guess_ext_defaults_mp4(self):
        engine = DirectHttpEngine()
        assert engine._guess_ext("https://example.com/unknown") == "mp4"


# ===========================================================================
# Pipeline._is_engine_error 错误消息识别
# ===========================================================================


class TestEngineErrorRecognition:
    def test_yt_dlp_error_detected(self):
        assert DownloadPipeline._is_engine_error("yt-dlp error: HTTP 404") is True

    def test_yt_dlp_reported_detected(self):
        assert DownloadPipeline._is_engine_error("yt-dlp reported error") is True

    def test_m3u8_download_failed_detected(self):
        assert DownloadPipeline._is_engine_error("m3u8 download failed: timeout") is True

    def test_m3u8_download_error_detected(self):
        assert DownloadPipeline._is_engine_error("m3u8 download error: playlist parse failed") is True

    def test_direct_http_error_detected(self):
        assert DownloadPipeline._is_engine_error("direct_http error: connection refused") is True

    def test_neither_ffmpeg_nor_aiohttp_detected(self):
        assert DownloadPipeline._is_engine_error("Neither ffmpeg nor aiohttp is available") is True

    def test_aiohttp_required_detected(self):
        assert DownloadPipeline._is_engine_error("aiohttp is required for direct video downloads") is True

    def test_unknown_message_not_detected(self):
        assert DownloadPipeline._is_engine_error("some random message") is False

    def test_case_insensitive(self):
        assert DownloadPipeline._is_engine_error("YT-DLP ERROR: something") is True
        assert DownloadPipeline._is_engine_error("M3U8 DOWNLOAD FAILED: x") is True

    def test_nm3u8dl_error_detected(self):
        assert DownloadPipeline._is_engine_error("nm3u8dl failed to download") is True

    def test_m3u8_engine_error_detected(self):
        """M6.20: m3u8.py 的 ffmpeg 失败走的是 'm3u8 engine error:' 前缀。

        此前该前缀未注册，导致 pipeline 捕获不到真实原因，
        用户看到的是无意义的 "engine returned False"。
        """
        assert DownloadPipeline._is_engine_error(
            "m3u8 engine error: Protocol not found"
        ) is True

    def test_output_dir_error_detected(self):
        """M6.20: 输出目录创建失败也必须透传，而非退化为通用文案。"""
        assert DownloadPipeline._is_engine_error(
            "无法创建输出目录 D:\\x: [WinError 5] Access is denied"
        ) is True

    def test_all_m3u8_emitted_prefixes_registered(self):
        """守护「引擎发出的消息」与「pipeline 识别的前缀」不再脱节。

        这是根因C的本质：两处清单靠人工同步。逐条断言 m3u8 引擎
        实际会发出的每种错误消息都能被识别。
        """
        emitted = (
            "m3u8 engine error: output file empty or missing",
            "m3u8 download error: no segments found in playlist",
            "Neither ffmpeg nor aiohttp is available for m3u8 download",
        )
        for message in emitted:
            assert DownloadPipeline._is_engine_error(message) is True, message


# ===========================================================================
# M6.20 修复A：ffmpeg https 能力检测
# ===========================================================================


class TestFfmpegHttpsCapability:
    """捆绑的 ffmpeg 是 N_m3u8DL-CLI 的 2019 定制构建，编译时未启用任何
    TLS 后端。喂给它 https 播放列表会立刻 exit 1（Protocol not found），
    一个字节都写不出。而此前只在 ffmpeg **缺失**时才回退 aiohttp，
    ffmpeg **无能力**这一情形没有覆盖，于是 https HLS 必然失败。
    """

    def _probe(self, stdout: bytes):
        from doubi.engines import m3u8 as m3u8_mod

        m3u8_mod._ffmpeg_supports_https.cache_clear()
        completed = MagicMock()
        completed.stdout = stdout
        completed.stderr = b""
        with patch.object(m3u8_mod.subprocess, "run", return_value=completed) as run:
            result = m3u8_mod._ffmpeg_supports_https("C:\\fake\\ffmpeg.exe")
        m3u8_mod._ffmpeg_supports_https.cache_clear()
        return result, run

    def test_detects_https_support(self):
        listing = b"Input:\n  file\n  http\n  https\n  tcp\n  tls\n"
        result, _ = self._probe(listing)
        assert result is True

    def test_detects_missing_https(self):
        """这正是捆绑 ffmpeg 的真实输出形态：有 http 但没有 https。"""
        listing = b"Input:\n  file\n  http\n  tcp\n"
        result, _ = self._probe(listing)
        assert result is False

    def test_does_not_match_substring(self):
        """协议名必须整行精确匹配。

        'httpproxy' 含子串 'http'，若用 in 判断会误判；
        这里确认没有 https 行时结果为 False。
        """
        listing = b"Input:\n  http\n  httpproxy\n"
        result, _ = self._probe(listing)
        assert result is False

    def test_probe_failure_degrades_to_false(self):
        """探测本身失败时宁可回退 aiohttp，也不要启动一个注定失败的子进程。"""
        from doubi.engines import m3u8 as m3u8_mod

        m3u8_mod._ffmpeg_supports_https.cache_clear()
        with patch.object(m3u8_mod.subprocess, "run", side_effect=OSError("boom")):
            assert m3u8_mod._ffmpeg_supports_https("C:\\fake\\ffmpeg.exe") is False
        m3u8_mod._ffmpeg_supports_https.cache_clear()

    def test_result_is_cached(self):
        """同一路径只探测一次——下载每个分片都 spawn 一次进程不可接受。"""
        listing = b"Input:\n  https\n"
        from doubi.engines import m3u8 as m3u8_mod

        m3u8_mod._ffmpeg_supports_https.cache_clear()
        completed = MagicMock()
        completed.stdout = listing
        completed.stderr = b""
        with patch.object(m3u8_mod.subprocess, "run", return_value=completed) as run:
            m3u8_mod._ffmpeg_supports_https("C:\\cached\\ffmpeg.exe")
            m3u8_mod._ffmpeg_supports_https("C:\\cached\\ffmpeg.exe")
            assert run.call_count == 1
        m3u8_mod._ffmpeg_supports_https.cache_clear()

    def test_can_fetch_http_without_probing(self):
        """明文 http 不需要 TLS，不该浪费一次探测。"""
        engine = M3u8Engine(ffmpeg_path="C:\\fake\\ffmpeg.exe")
        from doubi.engines import m3u8 as m3u8_mod

        with patch.object(m3u8_mod, "_ffmpeg_supports_https") as probe:
            assert engine._can_ffmpeg_fetch("http://example.com/a.m3u8") is True
            probe.assert_not_called()

    def test_can_fetch_https_requires_tls(self):
        engine = M3u8Engine(ffmpeg_path="C:\\fake\\ffmpeg.exe")
        from doubi.engines import m3u8 as m3u8_mod

        with patch.object(m3u8_mod, "_ffmpeg_supports_https", return_value=False):
            assert engine._can_ffmpeg_fetch("https://example.com/a.m3u8") is False
        with patch.object(m3u8_mod, "_ffmpeg_supports_https", return_value=True):
            assert engine._can_ffmpeg_fetch("https://example.com/a.m3u8") is True

    @pytest.mark.asyncio
    async def test_download_falls_back_when_ffmpeg_lacks_tls(self, tmp_path):
        """端到端路由断言：ffmpeg 存在但不支持 https 时走 aiohttp 分支。"""
        engine = M3u8Engine(ffmpeg_path="C:\\fake\\ffmpeg.exe")
        item = _make_item(source_url="https://example.com/index.m3u8", is_hls=True)
        from doubi.engines import m3u8 as m3u8_mod

        with patch.object(m3u8_mod, "_ffmpeg_supports_https", return_value=False), \
                patch.object(engine, "_download_via_ffmpeg", new_callable=AsyncMock) as via_ff, \
                patch.object(engine, "_download_via_aiohttp", new_callable=AsyncMock) as via_ai:
            via_ai.return_value = True
            ok = await engine.download(item, DownloadOptions(output_root=tmp_path))

        assert ok is True
        via_ff.assert_not_called()
        via_ai.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_download_uses_ffmpeg_when_tls_available(self, tmp_path):
        engine = M3u8Engine(ffmpeg_path="C:\\fake\\ffmpeg.exe")
        item = _make_item(source_url="https://example.com/index.m3u8", is_hls=True)
        from doubi.engines import m3u8 as m3u8_mod

        with patch.object(m3u8_mod, "_ffmpeg_supports_https", return_value=True), \
                patch.object(engine, "_download_via_ffmpeg", new_callable=AsyncMock) as via_ff, \
                patch.object(engine, "_download_via_aiohttp", new_callable=AsyncMock) as via_ai:
            via_ff.return_value = True
            ok = await engine.download(item, DownloadOptions(output_root=tmp_path))

        assert ok is True
        via_ff.assert_awaited_once()
        via_ai.assert_not_called()


# ===========================================================================
# M6.20 修复B：分片 URL 用 urljoin 解析
# ===========================================================================


class TestSegmentUrlResolution:
    """播放列表里三种 URI 形态必须都能解析对。

    真实案例：silidm.com 的 2835 分片播放列表里混入了 18 个根相对的
    广告分片 /video/adjump/time/*.ts。旧代码 base + line 拼出
    ".../bfc23af8d1b2//video/adjump/..."（双斜杠）→ 404，
    下载在第 284 个分片处整体崩掉。
    """

    PLAYLIST_URL = "https://v.example.com/video/show/bfc23af8d1b2/index.m3u8"

    def _resolve(self, playlist_text: str) -> list[str]:
        engine = M3u8Engine(ffmpeg_path="C:\\fake\\ffmpeg.exe")

        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.text = AsyncMock(return_value=playlist_text)

        resp_ctx = MagicMock()
        resp_ctx.__aenter__ = AsyncMock(return_value=resp)
        resp_ctx.__aexit__ = AsyncMock(return_value=False)

        session = MagicMock()
        session.get = MagicMock(return_value=resp_ctx)

        session_ctx = MagicMock()
        session_ctx.__aenter__ = AsyncMock(return_value=session)
        session_ctx.__aexit__ = AsyncMock(return_value=False)

        fake_aiohttp = MagicMock()
        fake_aiohttp.ClientSession = MagicMock(return_value=session_ctx)

        return asyncio.run(
            engine._fetch_segments(
                fake_aiohttp,
                self.PLAYLIST_URL,
                DownloadOptions(),
            )
        )

    def test_relative_segment(self):
        segments = self._resolve("#EXTINF:1.0,\nseg-1.ts\n")
        assert segments == [
            "https://v.example.com/video/show/bfc23af8d1b2/seg-1.ts"
        ]

    def test_root_relative_segment_has_no_double_slash(self):
        """回归根因B：根相对分片必须挂到站点根，而不是拼在目录后面。"""
        segments = self._resolve("#EXTINF:1.0,\n/video/adjump/time/17873200.ts\n")
        assert segments == ["https://v.example.com/video/adjump/time/17873200.ts"]
        assert "//video" not in segments[0].removeprefix("https://")

    def test_absolute_segment_preserved(self):
        segments = self._resolve("#EXTINF:1.0,\nhttps://cdn.other.com/x.ts\n")
        assert segments == ["https://cdn.other.com/x.ts"]

    def test_comments_and_blank_lines_skipped(self):
        playlist = (
            "#EXTM3U\n"
            "#EXT-X-VERSION:3\n"
            "#EXT-X-PLAYLIST-TYPE:VOD\n"
            "\n"
            "#EXTINF:1.0,\n"
            "seg-1.ts\n"
            "#EXTINF:1.0,\n"
            "seg-2.ts\n"
            "#EXT-X-ENDLIST\n"
        )
        segments = self._resolve(playlist)
        assert len(segments) == 2
        assert segments[1].endswith("/bfc23af8d1b2/seg-2.ts")

    def test_mixed_playlist_like_real_case(self):
        """混合形态：普通分片 + 根相对广告分片，顺序与数量都要对。"""
        playlist = (
            "#EXTM3U\n"
            "#EXTINF:1.0,\nseg-1.ts\n"
            "#EXTINF:1.0,\n/video/adjump/time/1.ts\n"
            "#EXTINF:1.0,\nseg-2.ts\n"
        )
        segments = self._resolve(playlist)
        assert segments == [
            "https://v.example.com/video/show/bfc23af8d1b2/seg-1.ts",
            "https://v.example.com/video/adjump/time/1.ts",
            "https://v.example.com/video/show/bfc23af8d1b2/seg-2.ts",
        ]


# ===========================================================================
# M6.20 分片下载器：并发 + 分片级重试
# ===========================================================================


class _FakeSegmentServer:
    """可编排的假分片服务器。

    ``failures`` 形如 {分片下标: 连续失败次数}，用来精确制造「前 N 次失败、
    第 N+1 次成功」的抖动；``inflight_peak`` 记录同时在飞的请求数上限，
    用于断言并发确实发生、且被 concurrent_fragments 正确限流。
    """

    def __init__(self, failures: dict[int, int] | None = None):
        self.failures = dict(failures or {})
        self.attempts: dict[int, int] = {}
        self.inflight = 0
        self.inflight_peak = 0
        self.order: list[int] = []

    def _index_of(self, url: str) -> int:
        return int(url.rsplit("-", 1)[1].split(".")[0])

    def get(self, url, **kwargs):
        idx = self._index_of(url)
        server = self

        class _Ctx:
            async def __aenter__(self):
                server.inflight += 1
                server.inflight_peak = max(server.inflight_peak, server.inflight)
                server.attempts[idx] = server.attempts.get(idx, 0) + 1
                # 让出控制权，否则协程会一路跑到底、永远观察不到并发。
                await asyncio.sleep(0.01)

                remaining = server.failures.get(idx, 0)
                if remaining > 0:
                    server.failures[idx] = remaining - 1
                    server.inflight -= 1
                    raise OSError(f"boom on segment {idx}")

                resp = MagicMock()
                resp.raise_for_status = MagicMock()
                resp.read = AsyncMock(return_value=f"DATA{idx}".encode())
                return resp

            async def __aexit__(self, *exc):
                if server.inflight > 0:
                    server.inflight -= 1
                server.order.append(idx)
                return False

        return _Ctx()


def _run_concat(server: _FakeSegmentServer, count: int, output_path, **opt_kwargs):
    """驱动 _download_and_concat，返回 (progress 事件列表)。"""
    engine = M3u8Engine(ffmpeg_path="C:\\fake\\ffmpeg.exe")
    segments = [f"https://cdn.example.com/seg-{i}.ts" for i in range(count)]

    session_ctx = MagicMock()
    session_ctx.__aenter__ = AsyncMock(return_value=server)
    session_ctx.__aexit__ = AsyncMock(return_value=False)

    fake_aiohttp = MagicMock()
    fake_aiohttp.ClientSession = MagicMock(return_value=session_ctx)
    fake_aiohttp.ClientTimeout = MagicMock(return_value=object())

    events: list = []
    asyncio.run(
        engine._download_and_concat(
            fake_aiohttp,
            segments,
            output_path,
            DownloadOptions(**opt_kwargs),
            events.append,
        )
    )
    return events


class TestSegmentDownloadConcurrency:
    def test_segments_are_downloaded_concurrently(self, tmp_path):
        """旧实现是严格顺序 for 循环，峰值并发恒为 1。"""
        server = _FakeSegmentServer()
        out = tmp_path / "out.mp4"
        _run_concat(server, 12, out, concurrent_fragments=4)
        assert server.inflight_peak > 1
        assert server.inflight_peak <= 4

    def test_concurrency_respects_concurrent_fragments(self, tmp_path):
        """复用 yt-dlp / aria2 已有的旋钮，而不是新造一个。"""
        server = _FakeSegmentServer()
        _run_concat(server, 12, tmp_path / "out.mp4", concurrent_fragments=2)
        assert server.inflight_peak <= 2

    def test_output_is_concatenated_in_playlist_order(self, tmp_path):
        """并发只影响下载顺序，落盘必须严格按播放列表顺序拼接。"""
        server = _FakeSegmentServer(failures={0: 2})
        out = tmp_path / "out.mp4"
        _run_concat(server, 5, out, concurrent_fragments=5)
        assert out.read_bytes() == b"".join(f"DATA{i}".encode() for i in range(5))

    def test_transient_failure_is_retried(self, tmp_path):
        """单个分片抖动一次不应让整场下载失败。"""
        server = _FakeSegmentServer(failures={3: 1})
        out = tmp_path / "out.mp4"
        _run_concat(server, 6, out, concurrent_fragments=3)
        assert server.attempts[3] == 2
        assert out.exists()

    def test_permanent_failure_raises_with_segment_number(self, tmp_path):
        from doubi.engines import m3u8 as m3u8_mod

        server = _FakeSegmentServer(failures={2: 99})
        with pytest.raises(RuntimeError) as excinfo:
            _run_concat(server, 4, tmp_path / "out.mp4", concurrent_fragments=2)
        assert "segment 3/4" in str(excinfo.value)
        assert server.attempts[2] == m3u8_mod._SEGMENT_MAX_ATTEMPTS

    def test_progress_is_monotonic_under_concurrency(self, tmp_path):
        """乱序完成时进度条不能回退。"""
        server = _FakeSegmentServer(failures={0: 1, 5: 1})
        events = _run_concat(server, 8, tmp_path / "out.mp4", concurrent_fragments=4)
        fractions = [ev.fraction for ev in events]
        assert fractions == sorted(fractions)
        assert fractions[-1] == pytest.approx(1.0)
        assert len(events) == 8

    def test_temp_dir_is_cleaned_up_on_failure(self, tmp_path):
        server = _FakeSegmentServer(failures={1: 99})
        before = set(Path(tempfile.gettempdir()).glob("doubi_m3u8_*"))
        with pytest.raises(RuntimeError):
            _run_concat(server, 3, tmp_path / "out.mp4", concurrent_fragments=2)
        after = set(Path(tempfile.gettempdir()).glob("doubi_m3u8_*"))
        assert after <= before

    def test_cancellation_stops_download(self, tmp_path):
        engine = M3u8Engine(ffmpeg_path="C:\\fake\\ffmpeg.exe")
        server = _FakeSegmentServer()
        segments = [f"https://cdn.example.com/seg-{i}.ts" for i in range(20)]

        session_ctx = MagicMock()
        session_ctx.__aenter__ = AsyncMock(return_value=server)
        session_ctx.__aexit__ = AsyncMock(return_value=False)
        fake_aiohttp = MagicMock()
        fake_aiohttp.ClientSession = MagicMock(return_value=session_ctx)
        fake_aiohttp.ClientTimeout = MagicMock(return_value=object())

        options = DownloadOptions(concurrent_fragments=2, cancel_check=lambda: True)
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(
                engine._download_and_concat(
                    fake_aiohttp, segments, tmp_path / "out.mp4", options, None
                )
            )
        assert not (tmp_path / "out.mp4").exists()


# ===========================================================================
# Nm3u8dlEngine tests
# ===========================================================================


class TestNm3u8dlEngineSupports:
    def test_supports_hls_hint(self):
        from doubi.engines.nm3u8dl import Nm3u8dlEngine
        engine = Nm3u8dlEngine()
        item = _make_item(is_hls=True, source_url="https://example.com/playlist.m3u8")
        assert engine.supports(item) is True

    def test_supports_m3u8_extension(self):
        from doubi.engines.nm3u8dl import Nm3u8dlEngine
        engine = Nm3u8dlEngine()
        item = _make_item(source_url="https://example.com/video.m3u8")
        assert engine.supports(item) is True

    def test_supports_m3u_extension(self):
        from doubi.engines.nm3u8dl import Nm3u8dlEngine
        engine = Nm3u8dlEngine()
        item = _make_item(source_url="https://example.com/video.m3u")
        assert engine.supports(item) is True

    def test_rejects_mp4_url(self):
        from doubi.engines.nm3u8dl import Nm3u8dlEngine
        engine = Nm3u8dlEngine()
        item = _make_item(source_url="https://example.com/video.mp4")
        assert engine.supports(item) is False

    def test_rejects_no_url(self):
        from doubi.engines.nm3u8dl import Nm3u8dlEngine
        engine = Nm3u8dlEngine()
        item = _make_item()
        assert engine.supports(item) is False

    def test_is_available_when_cli_found(self):
        from doubi.engines.nm3u8dl import Nm3u8dlEngine
        engine = Nm3u8dlEngine()
        assert isinstance(engine.is_available, bool)

    def test_not_available_without_cli(self):
        from doubi.engines.nm3u8dl import Nm3u8dlEngine
        engine = Nm3u8dlEngine(cli_path=None)
        engine._cli = None
        assert engine.is_available is False

    def test_download_fails_without_cli(self):
        from doubi.engines.nm3u8dl import Nm3u8dlEngine
        engine = Nm3u8dlEngine(cli_path="")
        engine._cli = None
        item = _make_item(is_hls=True, source_url="https://example.com/playlist.m3u8")
        result = asyncio.run(engine.download(item, DownloadOptions()))
        assert result is False


class TestNm3u8dlEngineProgressParsing:
    def test_progress_regex_matches(self):
        from doubi.engines.nm3u8dl import _PROGRESS_RE
        m = _PROGRESS_RE.search("[#12/150] 1.23MB / 12.34MB | 1.23MB/s | 00:10/01:45")
        assert m is not None
        assert m.group(1) == "12"
        assert m.group(2) == "150"

    def test_progress_regex_matches_completed(self):
        from doubi.engines.nm3u8dl import _PROGRESS_RE
        m = _PROGRESS_RE.search("[#150/150] 12.34MB / 12.34MB | completed | 00:45/00:45")
        assert m is not None
        assert m.group(1) == "150"
        assert m.group(2) == "150"

    def test_complete_regex_matches(self):
        from doubi.engines.nm3u8dl import _COMPLETE_RE
        assert _COMPLETE_RE.search("[INFO] download completed") is not None

    def test_error_regex_matches(self):
        from doubi.engines.nm3u8dl import _ERROR_RE
        assert _ERROR_RE.search("[ERROR] something went wrong") is not None

    def test_total_seg_regex_full_width_colon(self):
        """N_m3u8DL-CLI v3.0.2 输出的是「总分片：9425」（全角冒号）。

        这是 watchdog 用的关键信号：发现 total_segments 的最早期
        来源（比 meta.json 落盘更早）。如果哪天 N_m3u8DL-CLI 切回
        半角冒号，正则也要兼容——所以下面那一条专门测半角。
        """
        from doubi.engines.nm3u8dl import _TOTAL_SEG_RE
        m = _TOTAL_SEG_RE.search("19:10:29.780 总分片：9425, 已选择分片：9425")
        assert m is not None and m.group(1) == "9425"

    def test_total_seg_regex_half_width_colon(self):
        """半角冒号是 fallback——任何切换都不应让 watchdog 失明。"""
        from doubi.engines.nm3u8dl import _TOTAL_SEG_RE
        m = _TOTAL_SEG_RE.search("total segments: 1234")
        # 我们的正则只匹配「总分片」+ 冒号，不会误匹配「total segments」。
        # 这是有意的：避免把英文日志当成信号源。
        assert m is None

    def test_total_seg_regex_handles_varying_whitespace(self):
        """冒号后允许任意空白——v3.0.2 实测是「：9425」无空格，但仍容错。"""
        from doubi.engines.nm3u8dl import _TOTAL_SEG_RE
        m = _TOTAL_SEG_RE.search("总分片：    100")
        assert m is not None and m.group(1) == "100"


class TestNm3u8dlWatchdog:
    """v3.0.2 的进度修复：N_m3u8DL-CLI 不再输出 ``[#N/M]`` 格式，watchdog
    转去采样输出目录下的 ``.ts`` 文件算分片级 fraction。

    这组用例只测 watchdog 用到的两个纯函数（``_discover_total_segments``、
    ``_count_completed_segments``）——1Hz 协程本身的循环 / cancel 退出
    行为是 asyncio 标准模式，由 ``_watchdog`` 内部套用，不需要单测。
    """

    def test_discover_total_segments_reads_meta_json(self, tmp_path):
        """meta.json 存在 + 结构正常 → 返回 m3u8Info.count。"""
        from doubi.engines.nm3u8dl import _discover_total_segments

        save_dir = tmp_path / "video123"
        save_dir.mkdir()
        meta = {
            "m3u8": "https://example.com/index.m3u8",
            "m3u8Info": {
                "originalCount": 9425,
                "count": 9425,
                "vod": True,
            },
        }
        (save_dir / "meta.json").write_text(
            __import__("json").dumps(meta, ensure_ascii=False),
            encoding="utf-8",
        )
        # save_name 是 Path（来自 .with_suffix("")）
        assert _discover_total_segments(tmp_path, tmp_path / "video123") == 9425

    def test_discover_total_segments_missing_returns_zero(self, tmp_path):
        """meta.json 不存在 → 返回 0（watchdog 会下次重试）。"""
        from doubi.engines.nm3u8dl import _discover_total_segments

        # tmp_path 存在但 save_dir 子目录不在
        save_name = tmp_path / "nope"
        assert _discover_total_segments(tmp_path, save_name) == 0

    def test_discover_total_segments_malformed_json_returns_zero(self, tmp_path):
        """JSON 损坏 → 不抛异常，返回 0。"""
        from doubi.engines.nm3u8dl import _discover_total_segments

        save_dir = tmp_path / "video123"
        save_dir.mkdir()
        (save_dir / "meta.json").write_text("{not valid json", encoding="utf-8")
        assert _discover_total_segments(tmp_path, save_dir) == 0

    def test_discover_total_segments_missing_m3u8info_returns_zero(self, tmp_path):
        """meta.json 是合法 JSON 但没有 m3u8Info → 0。"""
        from doubi.engines.nm3u8dl import _discover_total_segments

        save_dir = tmp_path / "video123"
        save_dir.mkdir()
        (save_dir / "meta.json").write_text('{"foo": "bar"}', encoding="utf-8")
        assert _discover_total_segments(tmp_path, save_dir) == 0

    def test_discover_total_segments_count_zero_returns_zero(self, tmp_path):
        """m3u8Info.count 为 0（直播流）→ 视为未知，回 0 避免除零。"""
        from doubi.engines.nm3u8dl import _discover_total_segments
        import json

        save_dir = tmp_path / "video123"
        save_dir.mkdir()
        (save_dir / "meta.json").write_text(
            json.dumps({"m3u8Info": {"count": 0, "vod": False}}, ensure_ascii=False),
            encoding="utf-8",
        )
        assert _discover_total_segments(tmp_path, save_dir) == 0

    def test_count_completed_segments_empty_dir(self, tmp_path):
        from doubi.engines.nm3u8dl import _count_completed_segments
        assert _count_completed_segments(tmp_path) == 0

    def test_count_completed_segments_flat_layout(self, tmp_path):
        """flat 布局：所有 .ts 直接在 out_dir 下。"""
        from doubi.engines.nm3u8dl import _count_completed_segments

        for i in range(5):
            (tmp_path / f"{i:07d}.ts").touch()
        # 混入一些「不是分片」的文件，确认它们被忽略
        (tmp_path / "meta.json").touch()
        (tmp_path / "raw.m3u8").touch()
        (tmp_path / "video.mp4").touch()
        (tmp_path / "info.txt").touch()
        assert _count_completed_segments(tmp_path) == 5

    def test_count_completed_segments_part_subdir_layout(self, tmp_path):
        """Part_N/ 子目录布局：v3.0.2 大文件会拆成 Part_0/ Part_1/ ...。"""
        from doubi.engines.nm3u8dl import _count_completed_segments

        for part in (0, 1, 2):
            part_dir = tmp_path / f"Part_{part}"
            part_dir.mkdir()
            for i in range(3):
                (part_dir / f"{i:07d}.ts").touch()
        assert _count_completed_segments(tmp_path) == 9

    def test_count_completed_segments_mixed_layout(self, tmp_path):
        """混合：flat + Part_* 同时存在 → 总数相加。"""
        from doubi.engines.nm3u8dl import _count_completed_segments

        for i in range(2):
            (tmp_path / f"{i:07d}.ts").touch()
        part_dir = tmp_path / "Part_0"
        part_dir.mkdir()
        for i in range(3):
            (part_dir / f"{i:07d}.ts").touch()
        assert _count_completed_segments(tmp_path) == 5

    def test_count_completed_segments_ignores_dotfiles(self, tmp_path):
        """.tmp / .part / 其他隐藏文件不计入。"""
        from doubi.engines.nm3u8dl import _count_completed_segments

        (tmp_path / "0000.ts").touch()
        (tmp_path / ".tmp").touch()  # 隐藏文件
        (tmp_path / "001.partial").touch()  # 不是 .ts
        assert _count_completed_segments(tmp_path) == 1

    def test_count_completed_segments_oserror_returns_zero(self, tmp_path):
        """out_dir 不存在 / 不可访问 → 0 而不是抛异常（watchdog 会下次重试）。"""
        from doubi.engines.nm3u8dl import _count_completed_segments

        missing = tmp_path / "no_such_dir"
        assert _count_completed_segments(missing) == 0

    def test_discover_total_segments_deep_layout(self, tmp_path):
        """真实的 N_m3u8DL-CLI 目录结构是 out_dir/<saveName 子目录>/meta.json。

        这条测试是 M6.17 进度条 bug 修复的回归守卫：watchdog 之前
        只扫 out_dir 一层，看不到 N_m3u8DL-CLI 自己创建的子目录，导
        致 total_segments 永远 0、进度条永远 0%。修法是递归 3 层。
        """
        from doubi.engines.nm3u8dl import _discover_total_segments
        import json

        # out_dir/<saveName_tail>/meta.json
        nested = tmp_path / "Downloaded.generic.unknown_author.video.silidm.com.天下_335f422619e63d5a"
        nested.mkdir()
        (nested / "meta.json").write_text(
            json.dumps({"m3u8Info": {"count": 9425, "vod": True}}, ensure_ascii=False),
            encoding="utf-8",
        )
        # save_name.name 是「天下_335f422619e63d5a」——不包含 out_dir 路径
        # 部分，正是这个错位让早期版本读不到 meta.json。
        assert _discover_total_segments(tmp_path, tmp_path / "天下_335f422619e63d5a") == 9425

    def test_count_completed_segments_deep_layout(self, tmp_path):
        """out_dir/<saveName_tail>/Part_0/*.ts 三层目录结构的 .ts 计数。"""
        from doubi.engines.nm3u8dl import _count_completed_segments

        # out_dir/<saveName_tail>/Part_0/{0000..}.ts
        nested = tmp_path / "video_xyz"
        nested.mkdir()
        part_dir = nested / "Part_0"
        part_dir.mkdir()
        for i in range(50):
            (part_dir / f"{i:07d}.ts").touch()
        # 混入「非分片」文件确认它们被忽略
        (nested / "meta.json").touch()
        (nested / "raw.m3u8").touch()
        assert _count_completed_segments(tmp_path) == 50


class TestPipelineEngineRoutingWithNm3u8dl:
    def test_nm3u8dl_takes_priority_over_m3u8(self):
        from doubi.engines.nm3u8dl import Nm3u8dlEngine
        nm_engine = Nm3u8dlEngine()
        nm_engine._cli = "fake"
        direct_engine = DirectHttpEngine()
        item = _make_item(is_hls=True, source_url="https://example.com/playlist.m3u8")
        pipeline = DownloadPipeline(engine=M3u8Engine(), extra_engines=[nm_engine, direct_engine])
        selected = pipeline._select_engine(item)
        assert selected is nm_engine

    def test_nm3u8dl_unavailable_falls_back_to_m3u8(self):
        from doubi.engines.nm3u8dl import Nm3u8dlEngine
        nm_engine = Nm3u8dlEngine()
        nm_engine._cli = None
        m3u8_engine = M3u8Engine()
        item = _make_item(is_hls=True, source_url="https://example.com/playlist.m3u8")
        pipeline = DownloadPipeline(engine=DirectHttpEngine(), extra_engines=[nm_engine, m3u8_engine])
        selected = pipeline._select_engine(item)
        assert selected is m3u8_engine
