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
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

from ..core.models import DownloadOptions, MediaItem
from ..core.storage.file_layout import resolve_item_dir
from ._subproc import (
    SubprocessTimeout,
    find_bundled_ffmpeg,
    run_supervised_subprocess,
)
from .base import (
    Engine,
    EngineProgress,
    EngineProgressCallback,
    cancel_flag_polling,
    output_path_under,
    safe_basename_for_item,
)

logger = logging.getLogger("doubi.engines.m3u8")

_EXT_RE = re.compile(r"\.([a-zA-Z0-9]{2,5})(?:$|\?)")

_VIDEO_EXT = {"mp4", "m4v", "webm", "ts", "flv", "mkv", "avi", "mov"}

# ffmpeg progress line parser — extracts current time and total duration.
# Typical: "frame=  123 fps= 45 q=23.0 size=    1024kB time=00:00:05.12 bitrate= 1600kbits/s speed=   25x"
_PROGRESS_TIME_RE = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")

# The packaged GUI is windowed, so any synchronous subprocess we spawn
# must not flash a console. Only defined on Windows.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# 分片级重试。一条 VOD 播放列表常有数千个分片，按每个分片 99.9% 的成功率
# 算，2835 个分片一次跑通的概率也只有约 5.7%——所以重试不是「锦上添花」，
# 而是让长播放列表能够下完的必要条件。退避按尝试次数线性增长。
_SEGMENT_MAX_ATTEMPTS = 3
_SEGMENT_RETRY_BACKOFF = 0.5

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
    """Locate ffmpeg: bundled copy first, then PATH.

    The bundled copy wins over PATH because it is version-pinned and
    known-good, whereas a system ffmpeg could be anything. Returns None
    when neither exists — ``M3u8Engine`` then degrades to the aiohttp
    segment downloader instead of failing.
    """
    bundled = find_bundled_ffmpeg()
    if bundled:
        return bundled
    on_path = shutil.which("ffmpeg")
    if on_path:
        return on_path
    return None


@lru_cache(maxsize=8)
def _ffmpeg_supports_https(ffmpeg_path: str) -> bool:
    """Whether this ffmpeg binary was built with a TLS backend.

    Not every ffmpeg can fetch ``https://`` URLs. The copy we bundle is
    the custom build shipped with N_m3u8DL-CLI, compiled *without*
    openssl/gnutls because its only job there was concatenating already
    downloaded local ``.ts`` files. Handing it an https playlist yields::

        https protocol not found, recompile FFmpeg with openssl, gnutls
        or securetransport enabled.

    ``-protocols`` lists what the binary can actually do, so we ask it
    once and cache the answer per path. A probe failure is treated as
    "no https" so we degrade to the aiohttp downloader rather than
    launching a doomed subprocess.
    """
    try:
        proc = subprocess.run(
            [ffmpeg_path, "-hide_banner", "-protocols"],
            capture_output=True,
            timeout=10,
            check=False,
            creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        logger.warning("[m3u8] could not probe ffmpeg protocols: %s", ffmpeg_path)
        return False

    listing = (proc.stdout + proc.stderr).decode("utf-8", errors="replace")
    return any(line.strip() == "https" for line in listing.splitlines())


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
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            err_msg = f"无法创建输出目录 {out_dir}: {exc}"
            logger.error("[m3u8] %s", err_msg)
            if on_progress:
                on_progress(EngineProgress(fraction=0.0, message=err_msg))
            return False

        basename = safe_basename_for_item(item)
        raw_ext = item.extra.get("sniff_ext") or self._guess_ext(item.source_url) or "mp4"
        ext = self._sanitize_output_ext(raw_ext)
        output_path = output_path_under(out_dir, basename, ext)

        if self._ffmpeg and self._can_ffmpeg_fetch(item.source_url):
            return await self._download_via_ffmpeg(
                item, output_path, options, on_progress
            )
        logger.warning("ffmpeg unusable for this URL, falling back to aiohttp segment downloader")
        return await self._download_via_aiohttp(
            item, output_path, options, on_progress
        )

    def _can_ffmpeg_fetch(self, url: str) -> bool:
        """Whether handing *url* to ffmpeg can possibly work.

        Guards the one case that always failed silently: an https
        playlist given to a ffmpeg built without TLS. ffmpeg exits 1
        with "Protocol not found" before writing a single byte, and
        because the aiohttp fallback was only chosen when ffmpeg was
        *missing* (not when it was incapable), the download died there
        instead of degrading.
        """
        if not self._ffmpeg:
            return False
        if not url.lower().startswith("https"):
            return True
        if _ffmpeg_supports_https(self._ffmpeg):
            return True
        logger.warning(
            "[m3u8] %s was built without TLS support; cannot fetch https playlist",
            self._ffmpeg,
        )
        return False

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

        if on_progress:
            on_progress(EngineProgress(fraction=0.0, message="ffmpeg 启动中..."))

        total_duration: float = 0.0
        last_progress_frac: float = -1.0
        fatal_error: str = ""
        parse_buf = bytearray()
        last_line: str = ""
        cancel_flag = getattr(options, "cancel_check", None)

        def _process_line(decoded: str) -> None:
            nonlocal total_duration, last_progress_frac, fatal_error, last_line
            if not decoded:
                return
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

        def _on_chunk(chunk: bytes) -> None:
            parse_buf.extend(chunk)
            while True:
                cr = parse_buf.find(b"\r")
                lf = parse_buf.find(b"\n")
                if cr == -1 and lf == -1:
                    break
                sep_idx = cr if lf == -1 or (cr != -1 and cr < lf) else lf
                line_bytes = bytes(parse_buf[:sep_idx])
                del parse_buf[:sep_idx + 1]
                if sep_idx == cr and parse_buf and parse_buf[0:1] == b"\n":
                    del parse_buf[:1]
                _process_line(line_bytes.decode("utf-8", errors="replace").strip())

        try:
            rc, _ = await run_supervised_subprocess(
                ffmpeg_args,
                on_chunk=_on_chunk,
                cancel_check=cancel_flag,
                stdout_limit=1024 * 1024,
                chunk_size=4096,
                watchdog_seconds=240.0,  # ffmpeg merge phase is slow for huge files
            )
        except SubprocessTimeout as e:
            rc = -1
            fatal_error = str(e)
        except asyncio.CancelledError:
            raise

        if parse_buf:
            _process_line(bytes(parse_buf).decode("utf-8", errors="replace").strip())

        if rc != 0:
            err_msg = fatal_error or last_line[-300:] or f"ffmpeg exited with code {rc}"
            logger.error("[m3u8] ffmpeg failed (rc=%d): %s", rc, err_msg)
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

        segments: list[str] = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # urljoin, not string concatenation: playlists mix relative
            # ("seg-1.ts"), root-relative ("/video/adjump/x.ts", common for
            # injected ad segments) and absolute URIs. Naive concatenation
            # turns the root-relative form into ".../dir//video/..." — a
            # double slash the origin answers with 404, killing the whole
            # download mid-way.
            segments.append(urljoin(url, line))
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
        cancel_flag = getattr(options, "cancel_check", None)
        total = len(segments)
        # Reuse the knob yt-dlp 和 aria2 已经在用的 ``concurrent_fragments``，
        # 而不是新造一个：同一个设置在所有引擎上应当含义一致。
        limit = max(1, int(getattr(options, "concurrent_fragments", 4) or 1))
        sem = asyncio.Semaphore(limit)
        done = 0

        async def fetch_one(session, idx: int, seg_url: str) -> None:
            nonlocal done
            seg_path = tmp_dir / f"seg_{idx:05d}.ts"
            async with sem:
                for attempt in range(1, _SEGMENT_MAX_ATTEMPTS + 1):
                    if cancel_flag_polling(cancel_flag):
                        raise asyncio.CancelledError("aiohttp m3u8 download stopped")
                    try:
                        async with session.get(seg_url, proxy=options.proxy) as resp:
                            resp.raise_for_status()
                            seg_data = await resp.read()
                        seg_path.write_bytes(seg_data)
                        break
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        # 一条播放列表动辄上千分片，偶发的连接重置/超时几乎
                        # 必然发生。没有重试的话，任何一次抖动都会让整场
                        # 下载前功尽弃，这正是之前用户看到的失败形态。
                        if attempt >= _SEGMENT_MAX_ATTEMPTS:
                            raise RuntimeError(
                                f"segment {idx + 1}/{total} failed after "
                                f"{attempt} attempts: {exc}"
                            ) from exc
                        logger.warning(
                            "[m3u8] segment %d/%d attempt %d failed (%s), retrying",
                            idx + 1, total, attempt, exc,
                        )
                        await asyncio.sleep(_SEGMENT_RETRY_BACKOFF * attempt)

            done += 1
            if on_progress:
                # done 按「完成顺序」递增而非分片下标，因此进度条始终单调。
                on_progress(EngineProgress(
                    fraction=done / total,
                    message=f"下载分片 {done}/{total}",
                ))

        try:
            timeout = aiohttp.ClientTimeout(total=None, sock_connect=15, sock_read=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                tasks = [
                    asyncio.create_task(fetch_one(session, idx, seg_url))
                    for idx, seg_url in enumerate(segments)
                ]
                try:
                    await asyncio.gather(*tasks)
                except BaseException:
                    # 必须显式取消并等待兄弟任务收敛：否则 session 会在它们
                    # 还在飞的时候被 __aexit__ 关掉，抛出一堆掩盖真实原因的
                    # "Session is closed" 噪声。
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    raise

            with open(output_path, "wb") as out_f:
                for idx in range(total):
                    seg_path = tmp_dir / f"seg_{idx:05d}.ts"
                    out_f.write(seg_path.read_bytes())
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

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
