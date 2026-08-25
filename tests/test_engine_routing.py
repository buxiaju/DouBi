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
