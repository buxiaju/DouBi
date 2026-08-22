"""Douyin metadata API.

Thin async wrapper around ``yt_dlp.YoutubeDL.extract_info()`` for
fetching single-item metadata. yt-dlp already handles x-bogus /
a-bogus signing, cookie validation, and short-link resolution, so
we don't need to reimplement any of that.

Scope in M2:
    * Single-item metadata fetch (title, author, cover, duration, publish_time)
    * Flat-playlist enumeration for user pages (best-effort)
    * Conversion from yt-dlp's info dict to our :class:`MediaItem`

Out of scope (M2.1+):
    * Direct Douyin web API calls for richer info
    * Pagination cursors
    * Comment / like counts beyond what yt-dlp exposes
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import yt_dlp

from ...core.models import (
    Author,
    MediaItem,
    MediaType,
    Platform,
)

logger = logging.getLogger("doubi.platforms.douyin.api")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_timestamp(value: Any) -> Optional[datetime]:
    """Convert a unix timestamp (int/float) or ISO string to datetime."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(int(value), tz=timezone.utc).replace(tzinfo=None)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        # ISO 8601 with optional Z
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
            return dt.replace(tzinfo=None) if dt.tzinfo else dt
        except ValueError:
            pass
    return None


def _classify_media_type(info: dict) -> MediaType:
    """Pick a MediaType based on yt-dlp's info dict signals."""
    live = info.get("is_live") or info.get("live_status") == "is_live"
    if live:
        return MediaType.LIVE
    duration = info.get("duration") or 0
    # yt-dlp sometimes returns a list of image URLs for 抖音 图文 posts
    formats = info.get("formats") or []
    has_video = any(f.get("vcodec") not in (None, "none") for f in formats)
    has_audio = any(f.get("acodec") not in (None, "none") for f in formats)
    if not has_video and not has_audio:
        # Could be an image post
        thumbs = info.get("thumbnails") or []
        if thumbs:
            return MediaType.IMAGE_ALBUM
    return MediaType.VIDEO


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------


class DouyinAPI:
    """Async metadata fetcher backed by yt-dlp.

    The class is intentionally small. The heavy lifting (signing,
    redirect following, format probing) all lives inside yt-dlp; we
    just provide a typed async-friendly surface on top.
    """

    def __init__(
        self,
        *,
        cookies_file: Optional[str] = None,
        proxy: Optional[str] = None,
        user_agent: Optional[str] = None,
        timeout: int = 30,
        yt_dlp_module: Any = None,
    ):
        self.cookies_file = cookies_file
        self.proxy = proxy
        self.user_agent = user_agent
        self.timeout = timeout
        # Pre-create the slot so the property works + tests can monkeypatch it
        self._ytdlp: Any = yt_dlp_module

    def _opts(self, *, flat: bool = False) -> dict:
        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": flat,
            "noplaylist": not flat,        # single URL = treat as one item
            "ignoreerrors": False,
        }
        if self.cookies_file:
            opts["cookiefile"] = self.cookies_file
        if self.proxy:
            opts["proxy"] = self.proxy
        if self.user_agent:
            opts["user_agent"] = self.user_agent
        return opts

    # ---- public API --------------------------------------------------

    async def fetch(self, url: str) -> Optional[dict]:
        """Fetch rich metadata for a single URL.

        Returns the yt-dlp info dict, or ``None`` on failure. This is
        the method the adapter uses to populate ``MediaItem`` fields
        like title, author, cover, and publish_time.
        """
        return await asyncio.to_thread(self._extract_sync, url, flat=False)

    async def fetch_flat(
        self,
        url: str,
        *,
        playlist_items: Optional[str] = None,
    ) -> Optional[dict]:
        """Enumerate a container (user page, mix) without downloading.

        Returns a yt-dlp info dict with an ``entries`` list. Each entry
        has at minimum ``id``, ``title``, ``url`` (sometimes), and
        ``thumbnails``. Use :meth:`flat_to_media_item` to convert.

        ``playlist_items`` follows yt-dlp's syntax: ``"1:50"``, ``"5,"``,
        ``"1,3,5"``, etc. ``None`` means all.
        """
        opts = self._opts(flat=True)
        if playlist_items:
            opts["playlist_items"] = playlist_items
        return await asyncio.to_thread(self._extract_sync, url, flat=True, opts_override=opts)

    # ---- internals ---------------------------------------------------

    def _extract_sync(
        self,
        url: str,
        *,
        flat: bool,
        opts_override: Optional[dict] = None,
    ) -> Optional[dict]:
        opts = opts_override or self._opts(flat=flat)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            return info
        except yt_dlp.utils.DownloadError as e:
            logger.warning("yt-dlp DownloadError for %s: %s", url, e)
            return None
        except Exception:
            logger.exception("Unexpected yt-dlp error for %s", url)
            return None

    # ---- conversions -------------------------------------------------

    def to_media_item(self, info: dict, source_url: str) -> MediaItem:
        """Build a fully-populated :class:`MediaItem` from a yt-dlp info dict."""
        author = Author(
            id=str(info.get("uploader_id") or info.get("channel_id") or info.get("creator_id") or ""),
            name=str(info.get("uploader") or info.get("channel") or info.get("creator") or ""),
            avatar_url=info.get("uploader_avatar") or info.get("channel_thumbnail"),
        )
        thumbs = info.get("thumbnails") or []
        cover = None
        if thumbs and isinstance(thumbs, list):
            # Pick the largest by preference (thumbnails are typically height-sorted asc)
            best = max(thumbs, key=lambda t: t.get("height") or t.get("width") or 0) if thumbs else None
            cover = best.get("url") if best else None
        cover = cover or info.get("thumbnail")

        return MediaItem(
            platform=Platform.DOUYIN,
            item_id=str(info.get("id") or ""),
            title=str(info.get("title") or info.get("description") or ""),
            author=author,
            cover_url=cover,
            duration=info.get("duration"),
            publish_time=_parse_timestamp(info.get("timestamp") or info.get("release_timestamp")),
            media_type=_classify_media_type(info),
            source_url=source_url,
            extra={
                "view_count": info.get("view_count"),
                "like_count": info.get("like_count"),
                "comment_count": info.get("comment_count"),
                "repost_count": info.get("repost_count"),
                "description": info.get("description"),
                "tags": info.get("tags") or [],
            },
        )

    def flat_to_media_item(self, entry: dict, fallback_url: str = "") -> MediaItem:
        """Convert a single flat-playlist entry into a :class:`MediaItem`.

        Flat entries are much sparser than full info dicts — we may
        only have an id, title, and a thumbnail URL. That's enough to
        create a placeholder; the engine will fetch the real media.
        """
        thumbs = entry.get("thumbnails") or []
        cover = thumbs[0].get("url") if thumbs else None
        cover = cover or entry.get("thumbnail")
        url = entry.get("url") or entry.get("webpage_url") or fallback_url
        return MediaItem(
            platform=Platform.DOUYIN,
            item_id=str(entry.get("id") or ""),
            title=str(entry.get("title") or ""),
            author=Author(name=str(entry.get("uploader") or "")),
            cover_url=cover,
            duration=entry.get("duration"),
            publish_time=_parse_timestamp(entry.get("timestamp")),
            media_type=MediaType.VIDEO,
            source_url=url,
            extra={"_flat_entry": True},
        )
