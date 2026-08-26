"""Direct HTTP download engine for video file直链.

Handles direct video URLs (.mp4, .webm, .flv, etc.) via streaming
HTTP GET. Supports progress reporting via Content-Length and resume
via HTTP Range requests.

Unlike yt-dlp, this engine does NOT try to parse the webpage — it
treats the URL as a direct media file, which is what generic sniffed
items need.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Optional

from ..core.models import DownloadOptions, MediaItem
from ..core.storage.file_layout import resolve_item_dir
from .base import (
    Engine,
    EngineProgress,
    EngineProgressCallback,
    cancel_flag_polling,
    output_path_under,
    safe_basename_for_item,
)

logger = logging.getLogger("doubi.engines.direct_http")

_EXT_RE = re.compile(r"\.([a-zA-Z0-9]{2,5})(?:$|\?)")

_VIDEO_EXT = {"mp4", "m4v", "webm", "ts", "flv", "mkv", "avi", "mov", "m4s"}


class DirectHttpEngine(Engine):
    """直链视频文件下载引擎。

    ``supports()`` returns True when:
    * ``item.extra["is_direct_video"]`` is True (set by GenericAdapter), OR
    * The source_url has a known video extension (.mp4, .webm, etc.).
    """

    name = "direct_http"

    def supports(self, item: MediaItem) -> bool:
        if item.extra.get("is_direct_video"):
            return True
        if item.extra.get("is_hls"):
            return False  # m3u8 → M3u8Engine
        url = item.source_url or ""
        m = _EXT_RE.search(url)
        if m:
            return m.group(1).lower() in _VIDEO_EXT
        return False

    async def download(
        self,
        item: MediaItem,
        options: DownloadOptions,
        *,
        on_progress: Optional[EngineProgressCallback] = None,
    ) -> bool:
        try:
            import aiohttp
        except ImportError:
            logger.error("aiohttp not installed; cannot use DirectHttpEngine")
            if on_progress:
                on_progress(EngineProgress(
                    fraction=0.0,
                    message="aiohttp is required for direct video downloads",
                ))
            return False

        out_dir = resolve_item_dir(item, options)
        # Directory itself could be deep and exceed MAX_PATH; wrap mkdir
        # in try/except and fail with a clear message instead of a raw
        # OSError from the depths.
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            err_msg = f"无法创建输出目录 {out_dir}: {exc}"
            logger.error("[direct_http] %s", err_msg)
            if on_progress:
                on_progress(EngineProgress(fraction=0.0, message=err_msg))
            return False

        basename = safe_basename_for_item(item)
        ext = item.extra.get("sniff_ext") or self._guess_ext(item.source_url) or "mp4"
        output_path = output_path_under(out_dir, basename, ext)
        part_path = output_path.with_suffix(output_path.suffix + ".part")

        url = item.source_url
        logger.info("[direct_http] downloading: %s → %s", url, output_path)

        try:
            await self._download_file(
                aiohttp, url, part_path, output_path, options, on_progress
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("[direct_http] download failed: %s", exc)
            if on_progress:
                on_progress(EngineProgress(
                    fraction=0.0,
                    message=f"direct_http error: {exc}",
                ))
            return False

        if on_progress:
            on_progress(EngineProgress(fraction=1.0, message="下载完成"))
        logger.info("[direct_http] download complete: %s", output_path)
        return True

    async def _download_file(
        self,
        aiohttp,
        url: str,
        part_path: Path,
        output_path: Path,
        options: DownloadOptions,
        on_progress: Optional[EngineProgressCallback],
    ) -> None:
        cancel_flag = getattr(options, "cancel_check", None)

        existing = 0
        headers = {}
        if options.resume and part_path.exists():
            existing = part_path.stat().st_size
            if existing > 0:
                headers["Range"] = f"bytes={existing}-"
                logger.debug("[direct_http] resume from byte %d", existing)

        timeout = aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, proxy=options.proxy, headers=headers) as resp:
                if resp.status == 416:
                    part_path.rename(output_path)
                    return
                if existing > 0 and resp.status == 200:
                    existing = 0
                    part_path.unlink(missing_ok=True)
                resp.raise_for_status()

                total = int(resp.headers.get("Content-Length", 0)) or 0
                if existing > 0 and resp.status == 206:
                    total += existing

                downloaded = existing
                chunk_size = 64 * 1024
                last_pct = -1
                stale_seconds = 0.0

                mode = "ab" if (options.resume and existing > 0 and resp.status == 206) else "wb"
                with open(part_path, mode) as f:
                    loop = asyncio.get_event_loop()
                    last_activity_at = loop.time()
                    while True:
                        # Cancel check first, so a paused/removed task stops
                        # downloading even in the middle of content read.
                        if cancel_flag_polling(cancel_flag):
                            raise asyncio.CancelledError("direct_http cancelled via flag")
                        try:
                            chunk = await asyncio.wait_for(
                                resp.content.read(chunk_size),
                                timeout=30.0,
                            )
                        except asyncio.TimeoutError:
                            now = loop.time()
                            stale_seconds += now - last_activity_at
                            if stale_seconds > 180:
                                raise RuntimeError(
                                    f"direct_http stalled: no data for {int(stale_seconds)}s"
                                )
                            continue
                        last_activity_at = loop.time()
                        stale_seconds = 0.0
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)

                        if on_progress and total > 0:
                            pct = int(downloaded * 100 / total)
                            if pct != last_pct:
                                last_pct = pct
                                on_progress(EngineProgress(
                                    fraction=downloaded / total,
                                    message=f"下载中 {pct}%",
                                ))

        if part_path.exists():
            part_path.rename(output_path)

    @staticmethod
    def _guess_ext(url: str) -> str:
        m = _EXT_RE.search(url)
        if m:
            return m.group(1).lower()
        return "mp4"
