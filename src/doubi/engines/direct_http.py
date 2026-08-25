"""Direct HTTP download engine for video file直链.

Handles direct video URLs (.mp4, .webm, .flv, etc.) via streaming
HTTP GET. Supports progress reporting via Content-Length and resume
via HTTP Range requests.

Unlike yt-dlp, this engine does NOT try to parse the webpage — it
treats the URL as a direct media file, which is what generic sniffed
items need.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

from ..core.models import DownloadOptions, MediaItem
from ..core.storage.file_layout import resolve_item_dir
from .base import Engine, EngineProgress, EngineProgressCallback

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
        out_dir.mkdir(parents=True, exist_ok=True)

        basename = self._safe_basename(item)
        ext = item.extra.get("sniff_ext") or self._guess_ext(item.source_url) or "mp4"
        output_path = out_dir / f"{basename}.{ext}"
        part_path = output_path.with_suffix(output_path.suffix + ".part")

        url = item.source_url
        logger.info("[direct_http] downloading: %s → %s", url, output_path)

        try:
            await self._download_file(
                aiohttp, url, part_path, output_path, options, on_progress
            )
        except Exception as exc:
            logger.error("[direct_http] download failed: %s", exc)
            if on_progress:
                on_progress(EngineProgress(
                    fraction=0.0,
                    message=f"direct_http error: {exc}",
                ))
            return False

        if on_progress:
            on_progress(EngineProgress(fraction=1.0, message="download complete"))
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
        existing = 0
        headers = {}

        if options.resume and part_path.exists():
            existing = part_path.stat().st_size
            if existing > 0:
                headers["Range"] = f"bytes={existing}-"
                logger.debug("[direct_http] resume from byte %d", existing)

        async with aiohttp.ClientSession() as session:
            async with session.get(url, proxy=options.proxy, headers=headers) as resp:
                if resp.status == 416:
                    # Range Not Satisfiable — file already complete
                    part_path.rename(output_path)
                    return

                if existing > 0 and resp.status == 200:
                    # Server doesn't support Range — start over
                    existing = 0
                    part_path.unlink(missing_ok=True)

                resp.raise_for_status()

                total = int(resp.headers.get("Content-Length", 0)) or 0
                if existing > 0 and resp.status == 206:
                    total += existing

                downloaded = existing
                chunk_size = 64 * 1024  # 64 KB
                last_pct = -1

                mode = "ab" if (options.resume and existing > 0 and resp.status == 206) else "wb"
                with open(part_path, mode) as f:
                    while True:
                        chunk = await resp.content.read(chunk_size)
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
    def _safe_basename(item: MediaItem) -> str:
        """Return a subprocess-safe basename (no spaces / special chars)."""
        raw = item.output_template or (item.title or item.item_id)
        s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', raw)
        s = re.sub(r'\s+', '_', s).strip('_')
        return s or "video"

    @staticmethod
    def _guess_ext(url: str) -> str:
        m = _EXT_RE.search(url)
        if m:
            return m.group(1).lower()
        return "mp4"
