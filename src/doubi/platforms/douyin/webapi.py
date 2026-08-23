"""Signed Douyin web API client.

Douyin's mobile-web API (``https://www.douyin.com/aweme/v1/web/...``)
is the only way to *enumerate* containers — the 合集 (collection /
mix) listing, a user's post feed, aweme detail. yt-dlp only supports
single ``/video/{id}` URLs (verified against yt-dlp 2026.08.19), so
container expansion cannot ride on yt-dlp.

Every request must be signed with ``a_bogus`` (see
:mod:`doubi.platforms.douyin.sign`, ported from douyin-downloader-main)
and carry a browser-like query string plus the user's cookies.

This module is intentionally small and synchronous-signing /
async-requesting:

    * cookies come from the existing Netscape cookie file (auth.py)
    * ``msToken`` is taken from the cookie file when present, else a
      random false token (Douyin accepts a fake msToken for the
      signature to be *well-formed*; the reference project uses the
      same fallback)
    * responses are normalized to ``{items, has_more, max_cursor}``

Ported from douyin-downloader-main ``core/api_client.py`` (MIT),
trimmed to the endpoints DouBi needs and switched from aiohttp to
httpx (already a DouBi dependency).
"""

from __future__ import annotations

import asyncio
import logging
import random
import string
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

from ...core.models import Author, MediaItem, MediaType, Platform
from .auth import parse_netscape_file
from .sign import ABogus, BrowserFingerprintGenerator

logger = logging.getLogger("doubi.platforms.douyin.webapi")

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
)

_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Referer": "https://www.douyin.com/?recommend=1",
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
}

# HTTP statuses douyin's risk control answers with; retry-worthy.
_RISK_CONTROL_STATUSES = {403, 429, 461, 471}


def _false_ms_token() -> str:
    return "".join(random.choice(string.ascii_letters + string.digits) for _ in range(182)) + "=="


def _default_query(ms_token: str) -> dict[str, Any]:
    """Browser-like query params every web API call must carry."""
    return {
        "device_platform": "webapp",
        "aid": "6383",
        "channel": "channel_pc_web",
        "update_version_code": "170400",
        "pc_client_type": "1",
        "pc_libra_divert": "Windows",
        "version_code": "290100",
        "version_name": "29.1.0",
        "cookie_enabled": "true",
        "screen_width": "1536",
        "screen_height": "864",
        "browser_language": "zh-CN",
        "browser_platform": "Win32",
        "browser_name": "Chrome",
        "browser_version": "139.0.0.0",
        "browser_online": "true",
        "engine_name": "Blink",
        "engine_version": "139.0.0.0",
        "os_name": "Windows",
        "os_version": "10",
        "cpu_core_num": "16",
        "device_memory": "8",
        "platform": "PC",
        "downlink": "10",
        "effective_type": "4g",
        "round_trip_time": "200",
        "support_h265": "1",
        "support_dash": "1",
        "uifid": "",
        "msToken": ms_token,
    }


def _normalize_page(raw: Any, *, item_keys: tuple[str, ...] = ()) -> dict[str, Any]:
    """Reduce an API page to ``{items, has_more, max_cursor}``."""
    data = raw if isinstance(raw, dict) else {}
    items: list[Any] = []
    for key in ("items", *item_keys, "aweme_list", "mix_list"):
        value = data.get(key)
        if isinstance(value, list):
            items = value
            break
    cursor = data.get("max_cursor")
    if cursor is None:
        cursor = data.get("cursor")
    return {
        "items": items,
        "has_more": bool(data.get("has_more")),
        "max_cursor": int(cursor or 0),
    }


class DouyinWebAPI:
    """Signed async client for douyin's mobile-web API."""

    BASE_URL = "https://www.douyin.com"

    def __init__(
        self,
        *,
        cookies_file: Optional[Path] = None,
        proxy: Optional[str] = None,
        timeout: float = 15.0,
    ):
        from .auth import default_cookie_path

        p = Path(cookies_file) if cookies_file else default_cookie_path()
        self.cookies: dict[str, str] = {}
        if p.exists():
            for c in parse_netscape_file(p):
                self.cookies[c["name"]] = c["value"]
        self.proxy = proxy
        self.timeout = timeout
        self.user_agent = _USER_AGENT

    # ------------------------------------------------------------------
    # signing + transport
    # ------------------------------------------------------------------

    def _signed_url(self, path: str, params: dict[str, Any]) -> str:
        query = urlencode(params)
        endpoint = f"{self.BASE_URL}{path}"
        try:
            fp = BrowserFingerprintGenerator.generate_fingerprint("Chrome")
            signer = ABogus(fp=fp, user_agent=self.user_agent)
            params_with_ab, _ab, _ua, _body = signer.generate_abogus(query, "")
            return f"{endpoint}?{params_with_ab}"
        except Exception:
            # Signing must not be fatal — an unsigned request usually
            # fails with risk-control, but that is still a better error
            # than crashing the expansion.
            logger.warning("a_bogus generation failed; sending unsigned", exc_info=True)
            return f"{endpoint}?{query}"

    async def _request_json(
        self,
        path: str,
        params: dict[str, Any],
        *,
        max_retries: int = 3,
    ) -> dict[str, Any]:
        """GET a signed URL and parse the JSON body. Returns ``{}`` on failure."""
        delays = [1, 2, 5]
        last_error = "unknown"
        for attempt in range(max_retries):
            ms_token = (self.cookies.get("msToken") or "").strip() or _false_ms_token()
            query = _default_query(ms_token)
            query.update(params)
            url = self._signed_url(path, query)
            try:
                async with httpx.AsyncClient(
                    timeout=self.timeout,
                    cookies=self.cookies,
                    headers=_HEADERS,
                    proxy=self.proxy or None,
                    follow_redirects=True,
                ) as client:
                    resp = await client.get(url)
                if resp.status_code == 200:
                    body = resp.content
                    if not body:
                        # Empty 200 = classic anti-bot signal → re-sign & retry
                        last_error = "empty 200 (anti-bot)"
                    else:
                        try:
                            data = resp.json()
                        except ValueError:
                            last_error = "non-JSON 200"
                        else:
                            if isinstance(data, dict):
                                return data
                            last_error = "non-dict JSON"
                elif resp.status_code in _RISK_CONTROL_STATUSES or resp.status_code >= 500:
                    last_error = f"HTTP {resp.status_code}"
                else:
                    logger.warning("douyin web API %s -> HTTP %s", path, resp.status_code)
                    return {}
            except httpx.HTTPError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "douyin web API %s attempt %d/%d failed: %s",
                path, attempt + 1, max_retries, last_error,
            )
            if attempt < max_retries - 1:
                await asyncio.sleep(delays[min(attempt, len(delays) - 1)])
        logger.error("douyin web API %s exhausted retries: %s", path, last_error)
        return {}

    # ------------------------------------------------------------------
    # endpoints
    # ------------------------------------------------------------------

    async def get_video_detail(self, aweme_id: str) -> Optional[dict[str, Any]]:
        """Single aweme detail (contains ``mix_info`` when part of a 合集)."""
        for aid in ("6383", "1128"):
            data = await self._request_json(
                "/aweme/v1/web/aweme/detail/",
                {"aweme_id": aweme_id, "aid": aid},
                max_retries=2,
            )
            detail = data.get("aweme_detail")
            if detail:
                return detail
        return None

    async def get_mix_detail(self, mix_id: str) -> Optional[dict[str, Any]]:
        data = await self._request_json("/aweme/v1/web/mix/detail/", {"mix_id": mix_id})
        if not data:
            return None
        return data.get("mix_info") or data.get("mix_detail") or data

    async def get_mix_aweme(self, mix_id: str, *, cursor: int = 0, count: int = 20) -> dict[str, Any]:
        """One page of a 合集's videos."""
        raw = await self._request_json(
            "/aweme/v1/web/mix/aweme/",
            {"mix_id": mix_id, "cursor": cursor, "count": count},
        )
        return _normalize_page(raw, item_keys=("aweme_list",))

    async def get_user_post(self, sec_uid: str, *, max_cursor: int = 0, count: int = 18) -> dict[str, Any]:
        """One page of a user's published videos."""
        raw = await self._request_json(
            "/aweme/v1/web/aweme/post/",
            {
                "sec_user_id": sec_uid,
                "max_cursor": max_cursor,
                "count": count,
                "locate_query": "false",
                "show_live_replay_strategy": "1",
                "need_time_list": "1",
                "time_list_query": "0",
                "whale_cut_token": "",
                "cut_version": "1",
                "publish_video_strategy_type": "2",
            },
        )
        return _normalize_page(raw, item_keys=("aweme_list",))

    # ------------------------------------------------------------------
    # paginated enumerators
    # ------------------------------------------------------------------

    async def iter_mix_awemes(self, mix_id: str, *, max_count: int = 0) -> list[dict[str, Any]]:
        """All (or the first ``max_count``) awemes of a 合集."""
        awemes: list[dict[str, Any]] = []
        cursor = 0
        while True:
            page = await self.get_mix_aweme(mix_id, cursor=cursor)
            items = _extract_awemes(page["items"])
            if not items:
                break
            awemes.extend(items)
            if max_count and len(awemes) >= max_count:
                awemes = awemes[:max_count]
                break
            if not page["has_more"]:
                break
            next_cursor = page["max_cursor"]
            if next_cursor == cursor:
                # cursor stuck → avoid infinite loop
                break
            cursor = next_cursor
        return awemes

    async def iter_user_posts(self, sec_uid: str, *, max_count: int = 0) -> list[dict[str, Any]]:
        """All (or the first ``max_count``) published awemes of a user."""
        awemes: list[dict[str, Any]] = []
        cursor = 0
        while True:
            page = await self.get_user_post(sec_uid, max_cursor=cursor)
            items = _extract_awemes(page["items"])
            if not items:
                break
            awemes.extend(items)
            if max_count and len(awemes) >= max_count:
                awemes = awemes[:max_count]
                break
            if not page["has_more"]:
                break
            next_cursor = page["max_cursor"]
            if next_cursor == cursor:
                break
            cursor = next_cursor
        return awemes


def _extract_awemes(items: list[Any]) -> list[dict[str, Any]]:
    """API items are sometimes wrapped (``aweme`` / ``aweme_info``)."""
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("aweme_id"):
            out.append(item)
            continue
        for key in ("aweme", "aweme_info", "aweme_detail"):
            value = item.get(key)
            if isinstance(value, dict) and value.get("aweme_id"):
                out.append(value)
                break
    return out


# ---------------------------------------------------------------------------
# aweme (API JSON) -> MediaItem
# ---------------------------------------------------------------------------


def _first_url(value: Any) -> Optional[str]:
    if isinstance(value, dict):
        urls = value.get("url_list")
        if isinstance(urls, list) and urls:
            return str(urls[0])
    return None


def aweme_to_media_item(aweme: dict[str, Any]) -> MediaItem:
    """Convert one web-API aweme dict into a downloadable MediaItem.

    The child is fully download-ready: its ``source_url`` is the
    canonical ``/video/{id}`` form yt-dlp's Douyin extractor expects.
    """
    aweme_id = str(aweme.get("aweme_id") or "")
    author_raw = aweme.get("author") or {}
    video = aweme.get("video") or {}
    desc = str(aweme.get("desc") or "").strip()
    # desc is multi-line; first non-empty line makes a usable title
    title = next((ln.strip() for ln in desc.splitlines() if ln.strip()), "") or aweme_id
    duration_ms = video.get("duration") or 0
    create_time = aweme.get("create_time")

    mix_info = aweme.get("mix_info") or {}
    is_image = bool(aweme.get("images") or aweme.get("aweme_type") == 150 or aweme.get("aweme_type") == 68)

    extra: dict[str, Any] = {
        "view_count": (aweme.get("statistics") or {}).get("play_count"),
        "like_count": (aweme.get("statistics") or {}).get("digg_count"),
        "description": desc,
    }
    if mix_info.get("mix_id"):
        extra["mix_id"] = str(mix_info.get("mix_id"))
        extra["mix_name"] = mix_info.get("mix_name")

    return MediaItem(
        platform=Platform.DOUYIN,
        item_id=aweme_id,
        title=title,
        author=Author(
            id=str(author_raw.get("sec_uid") or ""),
            name=str(author_raw.get("nickname") or ""),
        ),
        cover_url=_first_url(video.get("cover") or video.get("origin_cover") or aweme.get("video", {}).get("dynamic_cover")),
        duration=(float(duration_ms) / 1000.0) if duration_ms else None,
        publish_time=_to_datetime(create_time),
        media_type=MediaType.IMAGE_ALBUM if is_image else MediaType.VIDEO,
        source_url=f"https://www.douyin.com/video/{aweme_id}" if aweme_id else "",
        extra=extra,
    )


def _to_datetime(value: Any):
    if isinstance(value, (int, float)) and value > 0:
        from datetime import datetime, timezone

        return datetime.fromtimestamp(int(value), tz=timezone.utc).replace(tzinfo=None)
    return None
