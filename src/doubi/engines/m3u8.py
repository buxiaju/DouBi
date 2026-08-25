"""M3U8 / HLS download engine.

Uses ffmpeg as a subprocess to fetch HLS streams. ffmpeg handles all
HLS edge cases natively: master playlists, AES-128 encryption,
variant playlists, and discontinuities.

For environments without ffmpeg, falls back to a pure-Python
segment downloader (aiohttp + ts concat) that handles simple
unencrypted single-variant playlists.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from ..core.models import DownloadOptions, MediaItem
from ..core.storage.file_layout import resolve_item_dir
from .base import Engine, EngineProgress, EngineProgressCallback

logger = logging.getLogger("doubi.engines.m3u8")

_EXT_RE = re.compile(r"\.([a-zA-Z0-9]{2,5})(?:$|\?)")

_VIDEO_EXT = {"mp4", "m4v", "webm", "ts", "flv", "mkv", "avi", "mov"}

# ffmpeg progress line parser — extracts current time and total duration.
# Typical: "frame=  123 fps= 45 q=23.0 size=    1024kB time=00:00:05.12 bitrate= 1600kbits/s speed=   25x"
_PROGRESS_TIME_RE = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")

# Common ffmpeg error patterns that indicate the HLS stream is valid
# but unplayable with current settings.
_FFMPEG_FATAL = (
    "Protocol not found",
    "Invalid data found when processing the input",
    "Server returned",
    "404 Not Found",
    "403 Forbidden",
    "Connection refused",
    "timed out",
)


def _resolve_ffmpeg() -> Optional[str]:
    on_path = shutil.which("ffmpeg")
    if on_path:
        return on_path
    try:
        import imageio_ffmpeg
        path = imageio_ffmpeg.get_ffmpeg_exe()
        if path and Path(path).exists():
            return path
    except Exception:
        pass
    return None


def _parse_time_to_seconds(hms: str) -> float:
    """Convert 'HH:MM:SS.ms' to seconds."""
    parts = hms.split(":")
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    return 0.0


class M3u8Engine(Engine):
    """HLS/m3u8 download engine.

    Uses ffmpeg for robust HLS downloads (handles AES-128, master
    playlists, etc.). Falls back to aiohttp-based segment download
    when ffmpeg is unavailable.

    ``supports()`` returns True when:
    * ``item.extra["is_hls"]`` is True (set by GenericAdapter), OR
    * The source_url contains ``.m3u8`` / ``.m3u``.
    """

    name = "m3u8"

    def __init__(self, ffmpeg_path: Optional[str] = None):
        self._ffmpeg = ffmpeg_path or _resolve_ffmpeg()
        if self._ffmpeg:
            logger.info("[m3u8] using ffmpeg: %s", self._ffmpeg)
        else:
            logger.warning("[m3u8] ffmpeg not found, will use aiohttp fallback")

    def supports(self, item: MediaItem) -> bool:
        if item.extra.get("is_hls"):
            return True
        url = item.source_url or ""
        lower = url.lower()
        return ".m3u8" in lower or ".m3u" in lower

    async def download(
        self,
        item: MediaItem,
        options: DownloadOptions,
        *,
        on_progress: Optional[EngineProgressCallback] = None,
    ) -> bool:
        out_dir = resolve_item_dir(item, options)
        out_dir.mkdir(parents=True, exist_ok=True)

        basename = self._safe_basename(item)
        raw_ext = item.extra.get("sniff_ext") or self._guess_ext(item.source_url) or "mp4"
        ext = self._sanitize_output_ext(raw_ext)
        output_path = out_dir / f"{basename}.{ext}"

        if self._ffmpeg:
            return await self._download_via_ffmpeg(
                item, output_path, options, on_progress
            )
        logger.warning("ffmpeg not found, falling back to aiohttp segment downloader")
        return await self._download_via_aiohttp(
            item, output_path, options, on_progress
        )

    # ------------------------------------------------------------------
    # ffmpeg path — the robust, production-grade route
    # ------------------------------------------------------------------

    async def _download_via_ffmpeg(
        self,
        item: MediaItem,
        output_path: Path,
        options: DownloadOptions,
        on_progress: Optional[EngineProgressCallback],
    ) -> bool:
        assert self._ffmpeg is not None
        url = item.source_url

        ffmpeg_args = [
            self._ffmpeg,
            "-y",
            "-loglevel", "info",
            "-protocol_whitelist", "file,http,https,tcp,tls,crypto,data",
        ]

        if options.proxy:
            ffmpeg_args += ["-http_proxy", options.proxy]

        ffmpeg_args += [
            "-i", url,
            "-c", "copy",
            "-bsf:a", "aac_adtstoasc",
            "-movflags", "+faststart",
            "-f", output_path.suffix.lstrip(".") or "mp4",
            str(output_path),
        ]

        logger.info("[m3u8] ffmpeg download: %s → %s", url, output_path)

        # Fire initial progress tick so the UI leaves "准备中" before the
        # subprocess is even spawned.
        if on_progress:
            on_progress(EngineProgress(fraction=0.0, message="ffmpeg 启动中..."))

        proc = await asyncio.create_subprocess_exec(
            *ffmpeg_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=1024 * 1024,  # 1 MiB buffer — defend against large \r lines
        )

        total_duration: float = 0.0
        last_progress_frac: float = -1.0
        fatal_error: str = ""

        async def _read_stream(stream, buf_start=b""):
            """Stream reader that splits on both \r and \n.

            ffmpeg sometimes writes progress with \r only.  The default
            line-iterator is \n-bound and raises LimitOverrunError when a
            single \r-terminated block exceeds the default 64 KiB buffer.
            """
            buf = bytes(buf_start)
            while True:
                chunk = await stream.read(4096)
                if not chunk:
                    break
                buf += chunk
                while True:
                    cr = buf.find(b"\r")
                    lf = buf.find(b"\n")
                    if cr == -1 and lf == -1:
                        break
                    sep_idx = cr if lf == -1 or (cr != -1 and cr < lf) else lf
                    line_bytes = buf[:sep_idx]
                    buf = buf[sep_idx + 1:]
                    if sep_idx == cr and buf.startswith(b"\n"):
                        buf = buf[1:]
                    yield line_bytes.decode("utf-8", errors="replace").strip()
            if buf:
                yield buf.decode("utf-8", errors="replace").strip()

        async def _read_stderr():
            nonlocal total_duration, last_progress_frac, fatal_error
            assert proc.stderr is not None
            last_line = ""
            async for decoded in _read_stream(proc.stderr):
                if not decoded:
                    continue
                last_line = decoded

                if "Duration:" in decoded:
                    m = _PROGRESS_TIME_RE.search(decoded)
                    if m:
                        total_duration = _parse_time_to_seconds(
                            f"{m.group(1)}:{m.group(2)}:{m.group(3)}"
                        )
                        if on_progress and total_duration > 0:
                            on_progress(EngineProgress(
                                fraction=0.0,
                                message=f"ffmpeg 解析完成 时长 {int(total_duration)}s",
                            ))

                if "time=" in decoded and on_progress:
                    m = _PROGRESS_TIME_RE.search(decoded)
                    if m and total_duration > 0:
                        current = _parse_time_to_seconds(
                            f"{m.group(1)}:{m.group(2)}:{m.group(3)}"
                        )
                        frac = min(1.0, current / total_duration)
                        pct = int(frac * 100)
                        if pct != int(last_progress_frac * 100):
                            last_progress_frac = frac
                            on_progress(EngineProgress(
                                fraction=frac,
                                message=f"ffmpeg 下载中 {pct}%",
                            ))

                for pattern in _FFMPEG_FATAL:
                    if pattern.lower() in decoded.lower():
                        fatal_error = decoded
                        break

            return last_line

        _, stderr_text = await asyncio.gather(
            proc.wait(),
            _read_stderr(),
        )

        if proc.returncode != 0:
            err_msg = fatal_error or stderr_text[-300:] or "ffmpeg exited with non-zero code"
            logger.error("[m3u8] ffmpeg failed (rc=%d): %s", proc.returncode, err_msg)
            if on_progress:
                on_progress(EngineProgress(
                    fraction=0.0,
                    message=f"m3u8 engine error: {err_msg}",
                ))
            return False

        if not output_path.exists() or output_path.stat().st_size == 0:
            logger.error("[m3u8] ffmpeg succeeded but output file is missing/empty")
            if on_progress:
                on_progress(EngineProgress(
                    fraction=0.0,
                    message="m3u8 engine error: output file empty or missing",
                ))
            return False

        if on_progress:
            on_progress(EngineProgress(fraction=1.0, message="m3u8 下载完成"))
        logger.info("[m3u8] download complete: %s (%d bytes)", output_path, output_path.stat().st_size)
        return True

    # ------------------------------------------------------------------
    # aiohttp fallback — simple segment downloader for unencrypted HLS
    # ------------------------------------------------------------------

    async def _download_via_aiohttp(
        self,
        item: MediaItem,
        output_path: Path,
        options: DownloadOptions,
        on_progress: Optional[EngineProgressCallback],
    ) -> bool:
        try:
            import aiohttp
        except ImportError:
            logger.error("aiohttp not installed; cannot download m3u8 without ffmpeg")
            if on_progress:
                on_progress(EngineProgress(
                    fraction=0.0,
                    message="Neither ffmpeg nor aiohttp is available for m3u8 download",
                ))
            return False

        url = item.source_url
        try:
            segments = await self._fetch_segments(aiohttp, url, options)
        except Exception as exc:
            logger.error("[m3u8] failed to parse playlist: %s", exc)
            if on_progress:
                on_progress(EngineProgress(
                    fraction=0.0,
                    message=f"m3u8 download error: playlist parse failed: {exc}",
                ))
            return False

        if not segments:
            logger.error("[m3u8] no segments found in playlist")
            if on_progress:
                on_progress(EngineProgress(
                    fraction=0.0,
                    message="m3u8 download error: no segments found in playlist",
                ))
            return False

        logger.info("[m3u8] downloading %d segments → %s", len(segments), output_path)

        try:
            await self._download_and_concat(aiohttp, segments, output_path, options, on_progress)
        except Exception as exc:
            logger.error("[m3u8] download failed: %s", exc)
            if on_progress:
                on_progress(EngineProgress(
                    fraction=0.0,
                    message=f"m3u8 engine error: {exc}",
                ))
            return False

        if on_progress:
            on_progress(EngineProgress(fraction=1.0, message="m3u8 下载完成"))
        return True

    async def _fetch_segments(self, aiohttp, url: str, options: DownloadOptions) -> list[str]:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, proxy=options.proxy) as resp:
                resp.raise_for_status()
                text = await resp.text()

        base = url.rsplit("/", 1)[0] + "/"
        lines = text.splitlines()
        segments: list[str] = []
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("http"):
                segments.append(line)
            else:
                segments.append(base + line)
        return segments

    async def _download_and_concat(
        self,
        aiohttp,
        segments: list[str],
        output_path: Path,
        options: DownloadOptions,
        on_progress: Optional[EngineProgressCallback],
    ) -> None:
        tmp_dir = Path(tempfile.mkdtemp(prefix="doubi_m3u8_"))
        try:
            async with aiohttp.ClientSession() as session:
                for idx, seg_url in enumerate(segments):
                    seg_path = tmp_dir / f"seg_{idx:05d}.ts"
                    async with session.get(seg_url, proxy=options.proxy) as resp:
                        resp.raise_for_status()
                        seg_data = await resp.read()
                    seg_path.write_bytes(seg_data)

                    if on_progress:
                        frac = (idx + 1) / len(segments)
                        on_progress(EngineProgress(
                            fraction=frac,
                            message=f"下载分片 {idx + 1}/{len(segments)}",
                        ))

            with open(output_path, "wb") as out_f:
                for idx in range(len(segments)):
                    seg_path = tmp_dir / f"seg_{idx:05d}.ts"
                    out_f.write(seg_path.read_bytes())
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    @staticmethod
    def _safe_basename(item: MediaItem) -> str:
        """Return a subprocess-safe basename (no spaces / special chars)."""
        raw = item.output_template or (item.title or item.item_id)
        s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', raw)
        s = re.sub(r'\s+', '_', s).strip('_')
        return s or "video"

    @staticmethod
    def _sanitize_output_ext(ext: str) -> str:
        """Strip input-only extensions, default to mp4."""
        if ext.lower() in {"m3u8", "m3u", "ts", "aac", "mp3"}:
            return "mp4"
        return ext.lower()

    @staticmethod
    def _guess_ext(url: str) -> str:
        m = _EXT_RE.search(url)
        if m:
            return m.group(1).lower()
        return "mp4"
