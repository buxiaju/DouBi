"""Bilibili metadata API.

Async wrapper around ``yt_dlp.YoutubeDL.extract_info`` for fetching
single-item metadata, plus flat-playlist extraction for user pages
(space, favlist, watch-later). yt-dlp's B 站 extractor handles WBI
signing, login cookies, and 4K/HDR/杜比 format negotiation natively,
so we don't need to reimplement any of that.

**Anti-bot**: B 站's space endpoints return HTTP 412 ("Request is
blocked") when the client has no ``buvid3`` cookie. We generate a
fresh one per API client and attach it via the ``Cookie`` header so
space / series enumeration works without a login.

B 站 is more login-sensitive than 抖音: most "favlist", "watch
later", and "history" endpoints need a valid ``SESSDATA`` cookie.
:class:`BilibiliAPI` is a cookie-aware subclass of the basic API
contract — it warns (instead of silently returning empty) when
authentication is required.
"""

from __future__ import annotations

import logging
import random
import string
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import yt_dlp

from ...core.models import (
    Author,
    MediaItem,
    MediaType,
    Platform,
)

logger = logging.getLogger("doubi.platforms.bilibili.api")


def generate_buvid3() -> str:
    """Generate a B 站 ``buvid3`` anonymous identifier.

    Format: ``{hex}-{hex}-{hex}-{hex}infoc``. B 站 uses this cookie
    to identify anonymous clients; a fresh value greatly reduces
    412 (blocked) responses on space / series endpoints.
    """
    def _hex(n: int) -> str:
        return uuid.uuid4().hex[:n]
    return f"{_hex(8)}-{_hex(4)}-{_hex(4)}-{_hex(4)}infoc"


def _parse_timestamp(value: Any) -> Optional[datetime]:
    """B 站 returns unix timestamps (int). Be defensive anyway."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(int(value), tz=timezone.utc).replace(tzinfo=None)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        s = value.strip()
        if s.isdigit():
            try:
                return datetime.fromtimestamp(int(s), tz=timezone.utc).replace(tzinfo=None)
            except (OverflowError, OSError, ValueError):
                return None
    return None


def _classify_media_type(info: dict) -> MediaType:
    """B 站 mapping: bangumi/cheese/live are special; everything else is video."""
    ie_key = (info.get("ie_key") or "").lower()
    extractor = (info.get("extractor") or "").lower()
    if "bangumi" in ie_key or "bangumi" in extractor:
        return MediaType.BANGUMI
    if "cheese" in ie_key or "cheese" in extractor:
        return MediaType.COURSE
    # yt-dlp 的直播 extractor ie_key 是 "BiliBiliLive"
    if "live" in ie_key or "live" in extractor:
        return MediaType.LIVE
    return MediaType.VIDEO


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------


class BilibiliAPI:
    """Async metadata fetcher backed by yt-dlp, B 站 aware."""

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
        self._ytdlp: Any = yt_dlp_module
        # Fresh anonymous identifier per client — B 站 412-blocks
        # clients without a buvid3 cookie on space/series endpoints.
        self._buvid3 = generate_buvid3()

    @property
    def ytdlp(self) -> Any:
        if self._ytdlp is None:
            try:
                import yt_dlp
                self._ytdlp = yt_dlp
            except ImportError as e:
                raise RuntimeError(
                    "yt-dlp is not installed. Run `pip install yt-dlp`."
                ) from e
        return self._ytdlp

    # ---- shared helpers ------------------------------------------------

    def build_cookie_header(self) -> str:
        """Build a ``Cookie:`` HTTP header string from the cookie file
        plus an anonymous ``buvid3`` fallback.

        Mirrors :meth:`ContainerStrategy._build_cookie_header` but
        lives on the API layer so any Bilibili* component can reuse
        the same cookie-munging logic (direct API calls via httpx
        need the exact same header set that yt-dlp would send).
        """
        cookies: dict[str, str] = {}
        from pathlib import Path
        if self.cookies_file:
            try:
                from .auth import parse_netscape_file
                for c in parse_netscape_file(Path(self.cookies_file)):
                    name = c.get("name")
                    value = c.get("value")
                    if name and value is not None and "bilibili" in c.get("domain", ""):
                        cookies[name] = value
            except Exception as exc:   # noqa: BLE001
                logger.debug("BilibiliAPI: failed to read cookie file: %s", exc)
        cookies.setdefault("buvid3", self._buvid3)
        return "; ".join(f"{k}={v}" for k, v in cookies.items() if v)

    async def fetch_view_pages(self, bvid: str) -> Optional[list[dict]]:
        """Fetch the raw ``pages`` list for a BV video via the official
        ``/x/web-interface/view`` JSON endpoint.

        This is the **authoritative** source of multi-page (分P)
        metadata. We call it as a fallback whenever yt-dlp reports
        ``_type="playlist"`` but returns a zero-length ``entries``
        list — which happens reliably when yt-dlp runs with a cookie
        file attached (it treats the BV as a single video and skips
        the playlist enumeration, even though the playlist-level
        title and ``playlist_count`` meta are still populated).

        Returns a list of ``pages`` dicts, each with keys like
        ``page``, ``cid``, ``part`` (title), ``duration``,
        ``first_frame`` (cover) etc.

        The playlist-level metadata that yt-dlp omits under cookie mode
        (**owner name / mid / cover / publish date**) is stored on the
        first page dict under the synthetic key ``"__playlist_meta"``
        so :class:`BilibiliAdapter` can fill them in for both the
        container and every child without a second HTTP call.

        Returns ``None`` if the API call failed for any reason
        (network / code != 0 / missing data).
        """
        data = await self.fetch_view_data(bvid)
        if data is None:
            return None
        pages = data.get("pages")
        if not isinstance(pages, list) or not pages:
            return None

        # Stash playlist-level metadata that yt-dlp cookie-mode omits
        # so adapter can use it without re-round-tripping.
        pages[0]["__playlist_meta"] = self.extract_playlist_meta(data)
        return pages

    @staticmethod
    def extract_playlist_meta(data: dict) -> dict:
        """Pull the playlist-level fields yt-dlp cookie-mode omits out of
        a raw ``/x/web-interface/view`` ``data`` object."""
        owner = data.get("owner") or {}
        return {
            "owner_name": owner.get("name"),
            "owner_mid": owner.get("mid"),
            "owner_face": owner.get("face"),
            "cover": data.get("pic") or data.get("thumbnail"),
            "title": data.get("title"),
            "desc": data.get("desc"),
            "pubdate_ts": data.get("pubdate") or data.get("ctime"),
            "duration_total": data.get("duration"),  # seconds, sum
            "stat_view": (data.get("stat") or {}).get("view"),
        }

    async def fetch_view_data(self, bvid: str) -> Optional[dict]:
        """Fetch the whole ``data`` object from ``/x/web-interface/view``.

        This is the single low-level accessor for the official view
        endpoint. Both :meth:`fetch_view_pages` (分P list) and
        :meth:`fetch_ugc_season` (合集/分类结构) are thin wrappers over
        it, so a caller that needs both only pays for one HTTP request
        if it calls this directly.

        Returns ``None`` on any failure (network / non-200 / non-JSON /
        ``code != 0`` / missing ``data``).
        """
        if not bvid:
            return None
        import httpx
        cookie_header = self.build_cookie_header()
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            "Referer": f"https://www.bilibili.com/video/{bvid}/",
        }
        if cookie_header:
            headers["Cookie"] = cookie_header
        try:
            async with httpx.AsyncClient(headers=headers, timeout=self.timeout) as client:
                resp = await client.get(
                    "https://api.bilibili.com/x/web-interface/view",
                    params={"bvid": bvid},
                )
                if resp.status_code != 200:
                    logger.debug("BilibiliAPI: view API HTTP %s for %s", resp.status_code, bvid)
                    return None
                try:
                    payload = resp.json()
                except ValueError:
                    logger.debug("BilibiliAPI: view API returned non-JSON for %s", bvid)
                    return None
        except Exception as exc:   # noqa: BLE001
            logger.debug("BilibiliAPI: view API httpx error for %s: %s", bvid, exc)
            return None

        if payload.get("code") != 0:
            logger.debug("BilibiliAPI: view API code=%s msg=%s for %s",
                         payload.get("code"), payload.get("message"), bvid)
            return None
        data = payload.get("data") or {}
        return data or None

    async def fetch_ugc_season(self, bvid: str) -> Optional[dict]:
        """Fetch the 合集 (``ugc_season``) structure a BV belongs to.

        B 站 collections can be **categorised**: a season holds several
        ``sections`` (rendered as the horizontal tab row in the web UI),
        and each section holds ``episodes`` (the vertical list below the
        tabs). Every episode is its own BV — and may itself be a 分P
        video with hundreds of pages.

        Shape returned (only the fields we need, already normalised)::

            {
              "season_id": 8316465,
              "season_title": "高分必备660！",
              "sections": [
                 {"section_id": 9245156,
                  "section_title": "模拟电子技术",
                  "episodes": [
                     {"episode_id": 201212309, "bvid": "BV1oxdwBBE3B",
                      "aid": ..., "cid": ..., "title": "1-2章",
                      "duration": 211, "part": "1.1"},
                     ...]},
                 ...]
            }

        Returns ``None`` when the BV is not part of a season, or when
        the season carries no episode at all.
        """
        data = await self.fetch_view_data(bvid)
        if not data:
            return None
        return self.parse_ugc_season(data)

    @staticmethod
    def parse_ugc_season(data: dict) -> Optional[dict]:
        """Normalise the raw ``data.ugc_season`` block of the view API.

        Split out of :meth:`fetch_ugc_season` so it can be unit-tested
        against a recorded payload with no network access.

        Accepts ``None`` (and any non-dict) so callers may forward a failed
        :meth:`fetch_view_data` result without an extra guard.
        """
        if not isinstance(data, dict):
            return None
        season = data.get("ugc_season")
        if not isinstance(season, dict):
            return None
        raw_sections = season.get("sections")
        if not isinstance(raw_sections, list):
            return None

        sections: list[dict] = []
        for raw_sec in raw_sections:
            if not isinstance(raw_sec, dict):
                continue
            raw_eps = raw_sec.get("episodes")
            if not isinstance(raw_eps, list):
                continue
            episodes: list[dict] = []
            for raw_ep in raw_eps:
                if not isinstance(raw_ep, dict):
                    continue
                ep_bvid = str(raw_ep.get("bvid") or "").strip()
                if not ep_bvid:
                    # Without a bvid we cannot build a source_url.
                    continue
                page = raw_ep.get("page")
                page = page if isinstance(page, dict) else {}
                try:
                    dur = int(page.get("duration") or 0)
                except (TypeError, ValueError):
                    dur = 0
                episodes.append({
                    "episode_id": raw_ep.get("id"),
                    "bvid": ep_bvid,
                    "aid": raw_ep.get("aid"),
                    "cid": raw_ep.get("cid") or page.get("cid"),
                    "title": str(raw_ep.get("title") or "").strip(),
                    "part": str(page.get("part") or "").strip(),
                    "duration": dur or None,
                })
            if not episodes:
                continue
            sections.append({
                "section_id": raw_sec.get("id"),
                "section_title": str(raw_sec.get("title") or "").strip(),
                "episodes": episodes,
            })

        if not sections:
            return None
        return {
            "season_id": season.get("id"),
            "season_title": str(season.get("title") or "").strip(),
            "sections": sections,
        }

    # ---- public API --------------------------------------------------

    async def fetch(self, url: str, *, allow_playlist: bool = False) -> Optional[dict]:
        """Fetch rich metadata for a single URL.

        Parameters
        ----------
        allow_playlist:
            When True, ``noplaylist`` is disabled so yt-dlp may return
            a playlist dict (with ``entries``) for multi-page /
            multi-part videos. Used by the adapter to detect and expand
            分P (multi-page) B 站 videos into a container + children.

            Unlike ``fetch_flat``, this mode keeps ``extract_flat=False``
            so each entry carries full title / uploader / duration /
            unique page-level id (e.g. ``BVxxx_p17``). Without this,
            entries are so sparse (only ``url`` / ``_type``) that the
            GUI shows empty titles and TaskManager dedupes all pages to
            a single task because ``item_id`` is blank.

            ``playlistend=0`` disables yt-dlp's default playlist cap
            so 200+ episode 合集 (common for B 站 courses) are fully
            enumerated during parse.

            When False (default), the engine-friendly mode: only the
            selected / first page is returned as a single info dict.
        """
        opts: dict[str, Any] | None = None
        if allow_playlist:
            opts = self._single_opts()
            opts["noplaylist"] = False
            opts["extract_flat"] = False
            # Remove the playlist cap — B 站合集经常 200+ 分P
            opts.setdefault("playlistend", 0)
            opts.setdefault("playliststart", 1)
            # 避免某些 extractor 截断
            opts.setdefault("lazy_playlist", False)
        return await self._extract_async(url, flat=False, opts_override=opts)

    async def fetch_flat(
        self,
        url: str,
        *,
        playlist_items: Optional[str] = None,
    ) -> Optional[dict]:
        """Enumerate a container URL without downloading."""
        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": True,
            "noplaylist": False,
        }
        if self.cookies_file:
            opts["cookiefile"] = self.cookies_file
        if self.proxy:
            opts["proxy"] = self.proxy
        if self.user_agent:
            opts["user_agent"] = self.user_agent
        # Attach buvid3 ONLY if there's no cookies file — otherwise the
        # http_headers.Cookie override would replace all file cookies
        # (SESSDATA etc.) with just buvid3, leaving the request
        # anonymous and triggering 412 / "请先登录" responses.
        if not self.cookies_file:
            opts["http_headers"] = {"Cookie": f"buvid3={self._buvid3}"}
        if playlist_items:
            opts["playlist_items"] = playlist_items
        return await self._extract_async(url, flat=True, opts_override=opts)

    # ---- internals ---------------------------------------------------

    async def _extract_async(
        self, url: str, *, flat: bool, opts_override: Optional[dict]
    ) -> Optional[dict]:
        import asyncio
        return await asyncio.to_thread(self._extract_sync, url, flat=flat, opts_override=opts_override)

    def _extract_sync(
        self,
        url: str,
        *,
        flat: bool,
        opts_override: Optional[dict],
    ) -> Optional[dict]:
        if opts_override is None:
            opts_override = self._single_opts()
        try:
            with self.ytdlp.YoutubeDL(opts_override) as ydl:
                return ydl.extract_info(url, download=False)
        except yt_dlp.utils.DownloadError as e:
            logger.warning("yt-dlp DownloadError for %s: %s", url, e)
            return None
        except Exception:
            logger.exception("Unexpected yt-dlp error for %s", url)
            return None

    def _single_opts(self) -> dict:
        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": False,
            "noplaylist": True,
        }
        if self.cookies_file:
            opts["cookiefile"] = self.cookies_file
        if self.proxy:
            opts["proxy"] = self.proxy
        if self.user_agent:
            opts["user_agent"] = self.user_agent
        # Same as fetch_flat: only attach buvid3 when there's no
        # cookies file. With a cookies file, let yt-dlp merge the file
        # cookies (SESSDATA, bili_jct, etc.) on its own.
        if not self.cookies_file:
            opts["http_headers"] = {"Cookie": f"buvid3={self._buvid3}"}
        return opts

    # ---- conversions -------------------------------------------------

    def to_media_item(self, info: dict, source_url: str) -> MediaItem:
        """Build a fully-populated :class:`MediaItem` from a yt-dlp info dict."""
        # B 站 uses "channel" / "uploader" interchangeably; "creator" for UP
        author_name = (
            info.get("uploader")
            or info.get("channel")
            or info.get("creator")
            or ""
        )
        author_id = str(
            info.get("uploader_id")
            or info.get("channel_id")
            or info.get("creator_id")
            or info.get("uploader_url", "").rsplit("/", 1)[-1]
            or ""
        )
        thumbs = info.get("thumbnails") or []
        cover = None
        if thumbs:
            best = max(thumbs, key=lambda t: t.get("height") or t.get("width") or 0)
            cover = best.get("url")
        cover = cover or info.get("thumbnail")

        return MediaItem(
            platform=Platform.BILIBILI,
            item_id=str(info.get("id") or ""),
            title=str(info.get("title") or ""),
            author=Author(id=author_id, name=author_name),
            cover_url=cover,
            duration=info.get("duration"),
            publish_time=_parse_timestamp(info.get("timestamp") or info.get("release_timestamp")),
            media_type=_classify_media_type(info),
            source_url=source_url,
            extra={
                "view_count": info.get("view_count"),
                "like_count": info.get("like_count"),
                "comment_count": info.get("comment_count"),
                "description": info.get("description"),
                "tags": info.get("tags") or [],
                "duration_string": info.get("duration_string"),
                "is_bangumi": "bangumi" in (info.get("ie_key") or "").lower(),
            },
        )

    def flat_to_media_item(self, entry: dict, fallback_url: str = "") -> MediaItem:
        """Convert a flat-playlist entry into a :class:`MediaItem`."""
        thumbs = entry.get("thumbnails") or []
        cover = thumbs[0].get("url") if thumbs else None
        cover = cover or entry.get("thumbnail")
        url = entry.get("url") or entry.get("webpage_url") or fallback_url
        return MediaItem(
            platform=Platform.BILIBILI,
            item_id=str(entry.get("id") or ""),
            title=str(entry.get("title") or ""),
            author=Author(name=str(entry.get("uploader") or entry.get("channel") or "")),
            cover_url=cover,
            duration=entry.get("duration"),
            publish_time=_parse_timestamp(entry.get("timestamp")),
            media_type=MediaType.VIDEO,
            source_url=url,
            extra={"_flat_entry": True},
        )
