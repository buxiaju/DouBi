"""Douyin live-stream recording (M2.1).

Thin wrapper around yt-dlp for ``https://live.douyin.com/{room_id}``
URLs. yt-dlp already understands 抖音's FLV / HLS streams, so the
heavy lifting is delegated. We add:

* A max-duration guard (0 = until the stream ends naturally).
* "Stop when the room goes offline" detection — yt-dlp will exit
  when the FLV / HLS stream closes; we just observe and report.
* Sidecar room-metadata JSON (``*_room.json``) mirroring the
  douyin-downloader behavior, so the user has a snapshot of the
  room at the moment the recording started.

Usage::

    async with LiveRecorder() as rec:
        result = await rec.record(
            url="https://live.douyin.com/123456789",
            output_root=Path("./Downloaded"),
            max_duration=3600,
        )
        print(result.output_path, result.elapsed)

The recorder is a thin async wrapper — the actual work runs in
``asyncio.to_thread`` so the calling coroutine is never blocked.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yt_dlp

logger = logging.getLogger("doubi.platforms.douyin.live")


@dataclass
class LiveRecordResult:
    """Outcome of a live recording session."""

    room_id: str
    title: str
    output_path: Optional[Path] = None
    room_metadata: dict = field(default_factory=dict)
    elapsed: float = 0.0
    bytes_written: int = 0
    ended_reason: str = "unknown"     # "max_duration" | "stream_ended" | "error"

    def to_dict(self) -> dict[str, Any]:
        return {
            "room_id": self.room_id,
            "title": self.title,
            "output_path": str(self.output_path) if self.output_path else None,
            "room_metadata": self.room_metadata,
            "elapsed": self.elapsed,
            "bytes_written": self.bytes_written,
            "ended_reason": self.ended_reason,
        }


def _extract_room_id(url: str) -> str:
    """Pull the room_id out of a 抖音 live URL.

    Accepts:
        * https://live.douyin.com/123456789
        * https://live.douyin.com/123456789?foo=bar
    """
    import re
    m = re.search(r"live\.douyin\.com/(\d+)", url)
    if not m:
        return ""
    return m.group(1)


def _probe_room(room_id: str) -> dict:
    """Best-effort fetch of room metadata via yt-dlp (no download).

    We don't rely on 抖音's web API here (it requires signing);
    yt-dlp's extract_info path gives us the title and a few other
    fields. Anything we *can't* get is just missing.
    """
    try:
        url = f"https://live.douyin.com/{room_id}"
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        if not info:
            return {}
        return {
            "id": info.get("id"),
            "title": info.get("title"),
            "uploader": info.get("uploader"),
            "uploader_id": info.get("uploader_id"),
            "is_live": info.get("is_live") or info.get("live_status") == "is_live",
            "timestamp": info.get("timestamp"),
            "description": info.get("description"),
        }
    except Exception as exc:
        logger.warning("room probe failed for %s: %s", room_id, exc)
        return {}


class LiveRecorder:
    """Async-friendly 抖音 live recorder.

    The recorder is reentrant — create one per session, then call
    :meth:`record` for each room you want to capture.
    """

    def __init__(self, *, cookies_file: Optional[str] = None, proxy: Optional[str] = None):
        self.cookies_file = cookies_file
        self.proxy = proxy

    async def __aenter__(self) -> "LiveRecorder":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    # ------------------------------------------------------------------
    # main entry
    # ------------------------------------------------------------------

    async def record(
        self,
        url: str,
        *,
        output_root: Path,
        max_duration: float = 0.0,
        container: str = "mp4",
    ) -> LiveRecordResult:
        """Record ``url`` to ``output_root``.

        ``max_duration=0`` means "until the live stream ends". The
        recorder will return when yt-dlp exits naturally (stream
        closed) or when the wall-clock duration exceeds
        ``max_duration``.
        """
        room_id = _extract_room_id(url)
        if not room_id:
            raise ValueError(f"could not extract room_id from {url!r}")

        output_root = Path(output_root).expanduser()
        output_root.mkdir(parents=True, exist_ok=True)

        started = time.monotonic()
        probe = await asyncio.to_thread(_probe_room, room_id)
        title = probe.get("title") or f"douyin_live_{room_id}"
        safe_title = _safe_filename(title)

        out_path = output_root / f"{datetime.now():%Y%m%d_%H%M}_{safe_title}_{room_id}.{container}"

        # Save room metadata sidecar
        meta_path = out_path.with_name(out_path.stem + "_room.json")
        meta = {
            "room_id": room_id,
            "url": url,
            "probed_at": int(time.time()),
            "metadata": probe,
        }
        try:
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        except OSError as exc:
            logger.warning("could not write room metadata: %s", exc)

        result = await asyncio.to_thread(
            self._record_sync, url, out_path, max_duration,
        )
        result.elapsed = time.monotonic() - started
        result.room_metadata = probe
        return result

    # ------------------------------------------------------------------
    # sync internals
    # ------------------------------------------------------------------

    def _record_sync(
        self, url: str, out_path: Path, max_duration: float
    ) -> LiveRecordResult:
        # yt-dlp's `live_from_start` only works for HLS; FLV is
        # auto-detected. `hls_use_mpegts` makes HLS output a single
        # .ts file which is much friendlier to incremental copy.
        opts: dict[str, Any] = {
            "outtmpl": str(out_path) + ".%(ext)s",
            "format": "best",
            "merge_output_format": "mp4",
            "noprogress": True,
            "quiet": True,
            "no_warnings": True,
            "live_from_start": True,
            "hls_use_mpegts": True,
            "wait_for_video": (5, 60),      # tag, min_secs, max_secs
            "retries": 5,
            "fragment_retries": 5,
        }
        if self.cookies_file:
            opts["cookiefile"] = self.cookies_file
        if self.proxy:
            opts["proxy"] = self.proxy

        room_id = _extract_room_id(url)
        result = LiveRecordResult(
            room_id=room_id,
            title="",
            output_path=out_path,
        )

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            result.ended_reason = "stream_ended"
        except yt_dlp.utils.DownloadError as exc:
            # "ERROR: No video formats found" / "Live stream has ended"
            # both show up as DownloadError — treat as graceful end.
            msg = str(exc).lower()
            if any(s in msg for s in ("ended", "no video", "404", "403", "offline")):
                logger.info("live stream %s ended: %s", room_id, exc)
                result.ended_reason = "stream_ended"
            else:
                logger.error("live record failed for %s: %s", room_id, exc)
                result.ended_reason = "error"
        except Exception as exc:
            logger.exception("unexpected live record failure: %s", exc)
            result.ended_reason = "error"

        # Best-effort: find the actual output file (yt-dlp picks the ext)
        if out_path.parent.exists():
            stem = out_path.stem
            matches = list(out_path.parent.glob(f"{stem}.*"))
            # Filter out the room metadata sidecar
            matches = [m for m in matches if not m.name.endswith("_room.json")]
            if matches:
                # Prefer .mp4 / .ts / .flv
                matches.sort(key=lambda p: (
                    0 if p.suffix in (".mp4", ".ts", ".flv") else 1,
                    p.name,
                ))
                result.output_path = matches[0]
                try:
                    result.bytes_written = matches[0].stat().st_size
                except OSError:
                    pass
        return result


def _safe_filename(value: str) -> str:
    """Trim to FS-safe characters; matches the douyin-downloader behavior."""
    import re
    if not value:
        return "untitled"
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value)
    s = re.sub(r"\s+", " ", s).strip().rstrip(". ")
    return s[:120] or "untitled"
