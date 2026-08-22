"""Container expansion strategies for Bilibili.

B 站 has more container types than 抖音:
    * :class:`SpaceStrategy`    — UP 主个人空间
    * :class:`FavlistStrategy`  — 当前账号的收藏夹（需要登录）
    * :class:`WatchLaterStrategy`— 当前账号的稍后再看（需要登录）
    * :class:`MixStrategy`      — 合集 / 系列

All four use yt-dlp's flat-playlist extraction under the hood. The
container types that need login (favlist, watch-later) check for a
cookie file and return ``[]`` with a clear warning if not present,
rather than failing with a cryptic 403.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ...core.models import (
    Author,
    MediaItem,
    MediaType,
    Platform,
)
from .api import BilibiliAPI
from .url import BilibiliURLType, classify_bilibili_url

logger = logging.getLogger("doubi.platforms.bilibili.strategies")


class ContainerStrategy(ABC):
    """Base class for container-expansion strategies."""

    name: str = "base"
    description: str = ""
    requires_login: bool = False
    target_url_types: tuple[BilibiliURLType, ...] = ()

    def __init__(self, api: BilibiliAPI):
        self.api = api

    @abstractmethod
    async def expand(self, url: str, *, max_count: int = 0) -> list[MediaItem]:
        """Return a list of children for the container URL."""
        raise NotImplementedError

    # ---- shared helpers ---------------------------------------------

    @classmethod
    def _extracted_id(cls, url: str) -> Optional[str]:
        classified = classify_bilibili_url(url)
        if classified.type in cls.target_url_types:
            return classified.item_id
        return None

    def _build_cookie_header(self) -> str:
        """Cookie header combining file cookies + buvid3 fallback.

        Priority:
          1. If a cookies file is configured, read SESSDATA / bili_jct /
             DedeUserID from it. Append buvid3 if not already present.
          2. Otherwise, fall back to just ``buvid3=...`` so the request
             isn't rejected as a brand-new client.
        """
        cookies: dict[str, str] = {}
        if self.api.cookies_file:
            try:
                from .auth import parse_netscape_file
                for c in parse_netscape_file(Path(self.api.cookies_file)):
                    name = c.get("name")
                    value = c.get("value")
                    if name and value is not None and "bilibili" in c.get("domain", ""):
                        cookies[name] = value
            except Exception as exc:   # noqa: BLE001
                logger.debug("container: failed to read cookie file: %s", exc)
        cookies.setdefault("buvid3", getattr(self.api, "_buvid3", ""))
        return "; ".join(f"{k}={v}" for k, v in cookies.items() if v)

    async def _get_wbi_keys(
        self, cookie_header: str,
    ) -> Optional[tuple[str, str]]:
        """Fetch (img_key, sub_key) from /x/web-interface/nav for signing.

        B 站's ``/x/space/arc/search`` and ``/x/series/archives`` now
        return ``code=-799`` ("风控校验失败") without a valid ``wts``
        and ``w_rid`` query parameter. This helper caches the keys
        per-API instance to avoid hammering /nav.
        """
        cached = getattr(self, "_wbi_keys_cache", None)
        if cached is not None:
            return cached
        try:
            from .wbi import fetch_wbi_keys
            cookies_list = []
            if cookie_header:
                for chunk in cookie_header.split("; "):
                    if "=" in chunk:
                        n, v = chunk.split("=", 1)
                        cookies_list.append({"name": n, "value": v})
            keys = await fetch_wbi_keys(cookies=cookies_list)
            if keys is not None:
                self._wbi_keys_cache = keys
            return keys
        except Exception as exc:   # noqa: BLE001
            logger.debug("container: WBI key fetch failed: %s", exc)
            return None


# ---------------------------------------------------------------------------
# SpaceStrategy
# ---------------------------------------------------------------------------


class SpaceStrategy(ContainerStrategy):
    """A UP 主's personal space (videos they uploaded).

    B 站's ``space.bilibili.com`` HTML endpoint returns HTTP 412 for
    most programmatic clients (the anti-bot signature inspects the
    ``Buvid`` / ``fp_local`` / etc. cookies plus TLS fingerprint).
    yt-dlp's :class:`BilibiliSpaceVideo` extractor hits the same wall.

    We therefore call B 站's own API directly:
        ``/x/space/arc/search?mid={mid}&pn=1&ps=30``

    Paginating through ``pn`` until the ``page.count`` is exhausted.
    This works for public uploads of any UP — no login needed, and
    SESSDATA (when present) unlocks the higher rate-limit tier.
    """

    name = "space"
    description = "Download a UP 主's uploaded videos"
    requires_login = False
    target_url_types = (BilibiliURLType.SPACE,)

    #: page size for the space API
    PAGE_SIZE = 30
    SPACE_ARC_SEARCH = "https://api.bilibili.com/x/space/arc/search"

    async def expand(self, url: str, *, max_count: int = 0) -> list[MediaItem]:
        uid = self._extracted_id(url)
        if not uid:
            logger.warning("SpaceStrategy: not a space URL: %s", url)
            return []

        import httpx
        cookie_header = self._build_cookie_header()
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            "Referer": f"https://space.bilibili.com/{uid}/",
        }
        if cookie_header:
            headers["Cookie"] = cookie_header

        # Cache WBI keys — the first call to the API that hits -799
        # (请求过于频繁) triggers a WBI-signed retry.
        wbi_keys: Optional[tuple[str, str]] = None
        items: list[MediaItem] = []
        page = 1
        try:
            async with httpx.AsyncClient(headers=headers, timeout=20) as client:
                while True:
                    params = {
                        "mid": uid,
                        "pn": page,
                        "ps": self.PAGE_SIZE,
                        "order": "pubdate",
                        "tid": 0,
                        "keyword": "",
                        "platform": "web",
                        "web_location": 1550101,
                        "order_avoided": "true",
                    }
                    if wbi_keys is not None:
                        from .wbi import sign_query
                        params = sign_query(params, wbi_keys)
                    resp = await client.get(
                        self.SPACE_ARC_SEARCH,
                        params=params,
                    )
                    data = resp.json()
                    if data.get("code") != 0:
                        # -799 "请求过于频繁" — retry once with WBI signing.
                        if data.get("code") == -799 and wbi_keys is None:
                            wbi_keys = await self._get_wbi_keys(cookie_header)
                            if wbi_keys is not None:
                                continue
                        logger.warning(
                            "SpaceStrategy: arc/search API error: %s",
                            data.get("message"),
                        )
                        # If we still got nothing, fall back to yt-dlp.
                        if not items and not cookie_header:
                            return await self._yt_dlp_fallback(url, max_count)
                        break
                    res = data.get("data") or {}
                    archives = res.get("list") or []
                    if not archives and not items:
                        logger.info(
                            "SpaceStrategy: API returned code=0 with empty list (mid=%s)",
                            uid,
                        )
                    for a in archives:
                        bvid = a.get("bvid")
                        if not bvid:
                            continue
                        items.append(MediaItem(
                            platform=Platform.BILIBILI,
                            item_id=bvid,
                            title=a.get("title") or "",
                            author=Author(
                                id=str(a.get("mid") or uid),
                                name=a.get("author") or "",
                            ),
                            cover_url=(
                                a.get("pic") if a.get("pic", "").startswith("http")
                                else (f"https:{a['pic']}" if a.get("pic") else None)
                            ),
                            duration=a.get("duration"),
                            publish_time=_ts(a.get("pubdate")),
                            media_type=MediaType.VIDEO,
                            source_url=f"https://www.bilibili.com/video/{bvid}",
                            extra={"_flat_entry": True},
                        ))
                    page_info = res.get("page") or {}
                    total = int(page_info.get("count") or 0)
                    if not archives or len(items) >= total or page * self.PAGE_SIZE >= total:
                        break
                    page += 1
        except httpx.HTTPError as exc:
            logger.warning("SpaceStrategy: arc/search failed: %s", exc)
        except ValueError as exc:
            logger.warning("SpaceStrategy: arc/search returned non-JSON: %s", exc)

        if max_count and max_count > 0:
            items = items[:max_count]
        logger.info("SpaceStrategy[%s]: %d items", uid, len(items))
        return items

    async def _yt_dlp_fallback(self, url: str, max_count: int) -> list[MediaItem]:
        """Last-resort: ask yt-dlp to flatten the space URL."""
        playlist_items = f"1:{max_count}" if max_count and max_count > 0 else None
        info = await self.api.fetch_flat(url, playlist_items=playlist_items)
        if not info:
            return []
        entries = info.get("entries") or []
        if not entries and info.get("id"):
            entries = [info]
        items = [self.api.flat_to_media_item(e, fallback_url=url) for e in entries if e.get("id")]
        if max_count:
            items = items[:max_count]
        return items


# ---------------------------------------------------------------------------
# FavlistStrategy
# ---------------------------------------------------------------------------


class FavlistStrategy(ContainerStrategy):
    """Current account's favorites (收藏夹). Requires SESSDATA cookie."""

    name = "favlist"
    description = "Download the current account's favorites (login required)"
    requires_login = True
    target_url_types = (BilibiliURLType.FAVLIST,)

    async def expand(self, url: str, *, max_count: int = 0) -> list[MediaItem]:
        fid = self._extracted_id(url)
        if not fid:
            logger.warning("FavlistStrategy: not a favlist URL: %s", url)
            return []

        if not self.api.cookies_file:
            logger.warning(
                "FavlistStrategy: no cookies configured. "
                "Run `doubi auth bilibili` (M3.1) or set DOUBI_BILIBILI_COOKIES."
            )
            return []

        playlist_items = f"1:{max_count}" if max_count and max_count > 0 else None
        info = await self.api.fetch_flat(url, playlist_items=playlist_items)
        if not info:
            return []
        entries = info.get("entries") or []
        items = [self.api.flat_to_media_item(e, fallback_url=url) for e in entries if e.get("id")]
        if max_count:
            items = items[:max_count]
        logger.info("FavlistStrategy[%s]: %d items", fid, len(items))
        return items


# ---------------------------------------------------------------------------
# WatchLaterStrategy
# ---------------------------------------------------------------------------


class WatchLaterStrategy(ContainerStrategy):
    """Current account's watch-later list (稍后再看). Requires SESSDATA cookie."""

    name = "watch_later"
    description = "Download the current account's watch-later list (login required)"
    requires_login = True
    target_url_types = (BilibiliURLType.WATCH_LATER,)

    async def expand(self, url: str, *, max_count: int = 0) -> list[MediaItem]:
        if not self.api.cookies_file:
            logger.warning(
                "WatchLaterStrategy: no cookies configured. "
                "Run `doubi auth bilibili` (M3.1) or set DOUBI_BILIBILI_COOKIES."
            )
            return []

        playlist_items = f"1:{max_count}" if max_count and max_count > 0 else None
        info = await self.api.fetch_flat(url, playlist_items=playlist_items)
        if not info:
            return []
        entries = info.get("entries") or []
        items = [self.api.flat_to_media_item(e, fallback_url=url) for e in entries if e.get("id")]
        if max_count:
            items = items[:max_count]
        logger.info("WatchLaterStrategy: %d items", len(items))
        return items


# ---------------------------------------------------------------------------
# MixStrategy
# ---------------------------------------------------------------------------


class MixStrategy(ContainerStrategy):
    """A 合集 / 系列 (B 站 "list/ml...").

    yt-dlp's B 站 extractor does NOT handle ``/list/ml{id}`` well
    (it raises "Could not access playlist" for many series). We use
    B 站's own series API instead:

        1. GET the ``/list/ml{id}`` page, scrape the UP 主's ``mid``.
        2. GET ``/x/series/archives?mid={mid}&series_id={id}&pn=..&ps=..``
        3. Each archive → MediaItem(bvid, title, duration, url).

    This matches the Bili23 "合集展开" behavior and is far more
    reliable than yt-dlp's flat extraction for this URL shape.
    """

    name = "mix"
    description = "Download a video collection / series"
    requires_login = False
    target_url_types = (BilibiliURLType.LIST,)

    #: series list API (public, no login needed for public series)
    SERIES_ARCHIVES_URL = "https://api.bilibili.com/x/series/archives"

    async def expand(self, url: str, *, max_count: int = 0) -> list[MediaItem]:
        ml_id = self._extracted_id(url)
        if not ml_id:
            logger.warning("MixStrategy: not a list URL: %s", url)
            return []

        import httpx
        # Build Cookie header: prefer file cookies (SESSDATA etc.),
        # fall back to a fresh buvid3 when no file is configured.
        cookie_header = self._build_cookie_header()
        wbi_keys = await self._get_wbi_keys(cookie_header)
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            "Referer": url,
        }
        if cookie_header:
            headers["Cookie"] = cookie_header

        # Step 1: scrape mid from the /list/ page
        mid = ""
        try:
            async with httpx.AsyncClient(headers=headers, timeout=20,
                                         follow_redirects=True) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    import re
                    m = re.search(r'"mid":(\d+)', resp.text)
                    if m:
                        mid = m.group(1)
        except httpx.HTTPError as exc:
            logger.warning("MixStrategy: failed to fetch list page %s: %s", url, exc)

        if not mid:
            logger.warning("MixStrategy: could not extract mid from %s", url)
            return []

        # Step 2: fetch archives from the series API
        items: list[MediaItem] = []
        page = 1
        page_size = 30
        # The series API doesn't accept WBI signing (it returns -400 if
        # you add wts/w_rid), so we only fall back to WBI-signed retry
        # when the API says "too many requests" (code=-799).
        wbi_keys = await self._get_wbi_keys(cookie_header)
        try:
            async with httpx.AsyncClient(headers=headers, timeout=20) as client:
                while True:
                    params = {
                        "mid": mid,
                        "series_id": ml_id,
                        "pn": page,
                        "ps": page_size,
                    }
                    if wbi_keys is not None:
                        from .wbi import sign_query
                        params = sign_query(params, wbi_keys)
                    resp = await client.get(
                        self.SERIES_ARCHIVES_URL,
                        params=params,
                    )
                    data = resp.json()
                    if data.get("code") != 0:
                        if data.get("code") == -799 and wbi_keys is None:
                            # Re-fetch keys in case they expired, then retry
                            self._wbi_keys_cache = None
                            wbi_keys = await self._get_wbi_keys(cookie_header)
                            if wbi_keys is not None:
                                continue
                        logger.warning("MixStrategy: series API error: %s", data.get("message"))
                        break
                    res = data.get("data") or {}
                    archives = res.get("archives") or []
                    for a in archives:
                        bvid = a.get("bvid")
                        if not bvid:
                            continue
                        items.append(MediaItem(
                            platform=Platform.BILIBILI,
                            item_id=bvid,
                            title=a.get("title") or "",
                            author=Author(
                                id=str(a.get("mid") or ""),
                                name=a.get("author") or "",
                            ),
                            cover_url=(
                                a.get("pic")
                                if a.get("pic") and a.get("pic").startswith("http")
                                else (f"https:{a['pic']}" if a.get("pic") else None)
                            ),
                            duration=a.get("duration"),
                            publish_time=_ts(a.get("pubdate")),
                            media_type=MediaType.VIDEO,
                            source_url=f"https://www.bilibili.com/video/{bvid}",
                            extra={"_flat_entry": True},
                        ))
                    # pagination
                    page_info = res.get("page") or {}
                    total_pages = int(page_info.get("count") or 1)
                    if page >= total_pages or not archives:
                        break
                    page += 1
        except httpx.HTTPError as exc:
            logger.warning("MixStrategy: series API request failed: %s", exc)
        except ValueError as exc:
            logger.warning("MixStrategy: series API returned non-JSON: %s", exc)

        if max_count and max_count > 0:
            items = items[:max_count]
        logger.info("MixStrategy[%s]: %d items (mid=%s)", ml_id, len(items), mid)
        return items


def _ts(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc).replace(tzinfo=None)
    except (ValueError, OverflowError, OSError):
        return None
