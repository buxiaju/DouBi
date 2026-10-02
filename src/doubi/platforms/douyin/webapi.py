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
import json
import logging
import random
import re
import string
import uuid
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote, urlencode

import httpx

from ...core.models import Author, MediaItem, MediaType, Platform
from .auth import parse_netscape_file
from .sign import (
    ABogus,
    BrowserFingerprintGenerator,
    MsTokenFetcher,
    TtWidFetcher,
    is_sign_protected,
    websign_sign,
)
from .url import is_image_album_payload

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

# User-search filter maps (M6.49). TikTokDL ``search.py:105-132`` carries
# these as ``douyin_user_fans_map`` / ``douyin_user_type_map``. Each
# value is a *list* of backend filter strings — the platform expects
# a JSON-encoded list even when the user picks "all".
_DOYIN_USER_FANS_MAP: dict[int, list[str]] = {
    0: [""],
    1: ["0_1k"],
    2: ["1k_1w"],
    3: ["1w_10w"],
    4: ["10w_100w"],
    5: ["100w_"],
}
_DOYIN_USER_TYPE_MAP: dict[int, list[str]] = {
    0: [""],
    1: ["common_user"],
    2: ["enterprise_user"],
    3: ["personal_user"],
}


# M6.50 — Hot 榜 board params. TikTokDL ``src/interface/hot.py``
# lines 14-35 carries these as a list of ``SimpleNamespace`` records;
# we flatten to a dict so the webapi method picks the right entry by
# key and the CLI can present the same keys as ``--board`` choices.
#
# The four boards are:
#   positive      board_type=0  board_sub_type=""                抖音热榜
#   entertainment board_type=2  board_sub_type=2                  娱乐榜
#   society       board_type=2  board_sub_type=4                  社会榜
#   challenge     board_type=2  board_sub_type="hotspot_challenge" 挑战榜
#
# Note: ``board_sub_type`` is heterogeneous (int | str) because
# ``hotspot_challenge`` is a string token while the others are integers.
HOT_BOARD_PARAMS: dict[str, tuple[int, Any]] = {
    "positive": (0, ""),
    "entertainment": (2, 2),
    "society": (2, 4),
    "challenge": (2, "hotspot_challenge"),
}

# Display name (Chinese). Used by the CLI's ``--board all`` mode to
# prefix each line so the user can tell which board a row came from
# when results from different boards are interleaved.
HOT_BOARD_NAMES: dict[str, str] = {
    "positive": "抖音热榜",
    "entertainment": "娱乐榜",
    "society": "社会榜",
    "challenge": "挑战榜",
}

ALL_HOT_BOARDS: tuple[str, ...] = tuple(HOT_BOARD_PARAMS.keys())


# ---------------------------------------------------------------------------
# M6.55 — 直播 (live) detail + multi-quality
# ---------------------------------------------------------------------------
#
# Adapted from Johnserf-Seed/TikTokDownloader ``src/interface/live.py``
# lines 11-95 (MIT). TikTokDL drives two *different hosts* depending on
# which identifier the caller holds:
#
#   web_rid  — the public share link ``https://live.douyin.com/{web_rid}``
#       -> ``https://live.douyin.com/webcast/room/web/enter/``        (GET)
#   room_id  — ``doubi search --type live`` returns ``aweme_id`` which
#              *is* the room_id on that endpoint
#       -> ``https://webcast.amemv.com/webcast/room/reflow/info/``    (GET)
#
# Neither path is in TikTokDL's ``DOUYIN_SIGNED_PATHS`` frozenset, so
# both ride on ``a_bogus`` alone and get **no** WebSign. DouBi keeps
# that parity on purpose: the protected-path whitelist is a platform
# contract, and blanket-adding these would change the wire format
# relative to the reference implementation for no benefit.
#
# ``_default_query`` already injects ``aid=6383`` / ``msToken`` /
# ``uifid``; the entries here either agree with it or intentionally
# override it (``device_platform`` must be ``web``, not ``webapp``,
# and ``browser_platform`` must be ``MacIntel`` — the live web player
# sends a different browser fingerprint than the video feed).
LIVE_ENTER_BASE = "https://live.douyin.com"
LIVE_ENTER_PATH = "/webcast/room/web/enter/"
LIVE_REFLOW_BASE = "https://webcast.amemv.com"
LIVE_REFLOW_PATH = "/webcast/room/reflow/info/"

# Referer the 直播 web player sends. TikTokDL calls
# ``set_referer("https://live.douyin.com/")`` before the web_rid call.
LIVE_REFERER = "https://live.douyin.com/"

# Bytes 0- header set TikTokDL uses for ``webcast.amemv.com``
# (``params.headers_download`` == ``DOWNLOAD_HEADERS``,
# ``custom/internal.py:75-79``).
LIVE_REFLOW_HEADERS: dict[str, str] = {
    "Accept": "*/*",
    "Range": "bytes=0-",
    "Referer": "https://www.douyin.com/?recommend=1",
}

LIVE_ENTER_PARAMS: dict[str, Any] = {
    "aid": "6383",
    "app_name": "douyin_web",
    "live_id": "1",
    "device_platform": "web",
    "language": "zh-CN",
    "enter_from": "link_share",
    "cookie_enabled": "true",
    "screen_width": "1536",
    "screen_height": "864",
    "browser_language": "zh-CN",
    "browser_platform": "MacIntel",
    "browser_name": "Chrome",
    "browser_version": "146.0.0.0",
    "enter_source": "",
    "is_need_double_stream": "false",
    "insert_task_id": "",
    "live_reason": "",
}

# ``room.status`` — only the two values 抖音 actually returns for the
# web_rid / reflow endpoints are mapped. Unknown values fall through as
# ``"未知({status})"`` rather than being guessed, so a platform change
# shows up as a visible label instead of a silent lie.
LIVE_STATUS_NAMES: dict[int, str] = {
    2: "直播中",
    4: "已结束",
}

# Stream quality keys. 抖音's ``stream_url.flv_pull_url`` and
# ``stream_url.hls_pull_url_map`` are *parallel* dicts keyed by the
# same tokens, which is what makes "pick one quality, get both
# containers" possible. Labels are best-effort: an unrecognised key is
# surfaced verbatim instead of being dropped.
LIVE_QUALITY_NAMES: dict[str, str] = {
    "ORIGIN": "原画",
    "UHD": "超清",
    "FULL_HD1": "蓝光",
    "HD1": "高清",
    "SD1": "标清",
    "SD2": "流畅",
}

# Preferred display / "best first" order. Keys absent from this tuple
# sort *after* the known ones, preserving the platform's own ordering.
LIVE_QUALITY_ORDER: tuple[str, ...] = (
    "ORIGIN",
    "UHD",
    "FULL_HD1",
    "HD1",
    "SD1",
    "SD2",
)

# Accepts the three 抖音 live URL shapes TikTokDL recognises
# (``link/extractor.py``: ``live_link`` / ``live_link_self``) plus a
# bare numeric web_rid pasted from ``doubi search --type live``.
_LIVE_WEB_RID_RE = re.compile(
    r"(?:live\.douyin\.com/|webRid=)(\d+)"
)


def extract_live_web_rid(text: str) -> str:
    """Pull a 抖音 live ``web_rid`` out of a URL or a bare id.

    Accepts:

    * ``https://live.douyin.com/123456789``
    * ``https://live.douyin.com/123456789?enter_from=...``
    * ``https://www.douyin.com/follow?webRid=123456789``
    * ``123456789``

    Returns ``""`` when nothing matches — callers decide whether that
    is a hard error (the CLI does) or a fall-through.
    """
    value = (text or "").strip()
    if not value:
        return ""
    if value.isdigit():
        return value
    m = _LIVE_WEB_RID_RE.search(value)
    return m.group(1) if m else ""


def _live_quality_rows(
    flv_map: dict[str, Any],
    hls_map: dict[str, Any],
) -> list[dict[str, Any]]:
    """Merge the parallel FLV / HLS quality maps into display rows.

    Both maps use the same quality tokens, so we walk the union in
    :data:`LIVE_QUALITY_ORDER` first and then append any unknown keys
    in their original order.
    """
    keys: list[str] = [k for k in LIVE_QUALITY_ORDER if k in flv_map or k in hls_map]
    seen = set(keys)
    for source in (flv_map, hls_map):
        for key in source:
            if key not in seen:
                seen.add(key)
                keys.append(key)

    rows: list[dict[str, Any]] = []
    for key in keys:
        flv = flv_map.get(key)
        hls = hls_map.get(key)
        rows.append({
            "key": key,
            "name": LIVE_QUALITY_NAMES.get(key, key),
            "flv": flv if isinstance(flv, str) else None,
            "hls": hls if isinstance(hls, str) else None,
        })
    return rows


def _live_status_name(status: Any) -> str:
    """Human label for ``room.status``; unknown values stay visible."""
    if isinstance(status, bool) or not isinstance(status, int):
        return "未知"
    return LIVE_STATUS_NAMES.get(status, f"未知({status})")


def normalize_live_room(
    raw: Any,
    *,
    web_rid: str = "",
    room_id: str = "",
) -> dict[str, Any]:
    """Flatten an ``enter`` / ``reflow`` response into one flat record.

    Both endpoints wrap the room differently (``data.data[0]`` vs
    ``data.room``), which is why TikTokDL's extractor tries them in
    sequence — we do the same. Returns ``{}`` when neither shape is
    present (offline room, risk-control HTML, …).

    The returned dict is JSONL-ready: every value is a plain JSON type,
    so the CLI can ``json.dumps`` it without a custom encoder.
    """
    body = raw if isinstance(raw, dict) else {}
    payload = body.get("data")
    if not isinstance(payload, dict):
        payload = body

    room: Any = None
    rooms = payload.get("data")
    if isinstance(rooms, list) and rooms:
        room = rooms[0]
    if not isinstance(room, dict):
        room = payload.get("room")
    if not isinstance(room, dict):
        return {}

    stream = room.get("stream_url")
    stream = stream if isinstance(stream, dict) else {}
    flv_map = stream.get("flv_pull_url")
    flv_map = flv_map if isinstance(flv_map, dict) else {}
    hls_map = stream.get("hls_pull_url_map")
    hls_map = hls_map if isinstance(hls_map, dict) else {}

    owner = room.get("owner")
    owner = owner if isinstance(owner, dict) else {}
    stats = room.get("stats")
    stats = stats if isinstance(stats, dict) else {}
    covers = (room.get("cover") or {}).get("url_list") if isinstance(room.get("cover"), dict) else None
    # LIVE_COVER_INDEX == -1 upstream → the *last* url is the good one.
    cover = covers[-1] if isinstance(covers, list) and covers else None

    status = room.get("status")
    qualities = _live_quality_rows(flv_map, hls_map)
    return {
        "web_rid": web_rid or str(room.get("web_rid") or ""),
        "room_id": room_id or str(room.get("id_str") or room.get("id") or ""),
        "status": status if isinstance(status, int) else None,
        "status_name": _live_status_name(status),
        "title": str(room.get("title") or ""),
        "nickname": str(owner.get("nickname") or ""),
        "sec_uid": str(owner.get("sec_uid") or ""),
        "cover": cover,
        "total_user_str": str(stats.get("total_user_str") or ""),
        "user_count_str": str(stats.get("user_count_str") or ""),
        "flv_pull_url": {k: v for k, v in flv_map.items() if isinstance(v, str)},
        "hls_pull_url_map": {k: v for k, v in hls_map.items() if isinstance(v, str)},
        "qualities": qualities,
    }


def _set_error_sink(
    sink: MutableMapping[str, Any],
    *,
    reason: str,
    status_code: Optional[int],
) -> None:
    """Stamp a structured error into a caller-provided mutable mapping so
    UI surfaces can surface user-facing hints (e.g. 「需要登录抖音」).

    Keys written:
        * ``reason`` — short machine-friendly reason string
          (``HTTP 403`` / ``empty 200 (anti-bot)`` / ``ConnectError: ...``)
        * ``status_code`` — last HTTP status seen (``None`` on transport error)
        * ``hint`` — i18n-ready user-facing hint identifier (``"need_login"``)

    The mapping is mutated in place so concurrent calls each keep their own
    state (the sink is caller-provided, never an instance attribute).
    """
    sink.clear()
    sink["reason"] = reason
    sink["status_code"] = status_code
    # Status 403 with Argus / risk-control wording → 100% needs login.
    # Other failures get a generic "retryable" hint that the UI can map
    # to whatever makes sense (network blip, anti-bot, etc.).
    if status_code in _RISK_CONTROL_STATUSES or status_code == 461:
        sink["hint"] = "need_login"
    elif status_code is not None and status_code >= 500:
        sink["hint"] = "server_error"
    else:
        sink["hint"] = "transient"


def _false_ms_token() -> str:
    return "".join(random.choice(string.ascii_letters + string.digits) for _ in range(182)) + "=="


def _default_query(ms_token: str, uifid: str = "") -> dict[str, Any]:
    """Browser-like query params every web API call must carry.

    ``uifid`` (M6.48) is the visitor ID that binds the WebSign signature
    on protected endpoints. DouBie uses a stable per-session UUID4 hex —
    we don't have access to 抖音's real uifid, but a session-stable value
    is enough to make WebSign *signable* (an empty uifid would skip
    WebSign and the platform returns ``403 Uifid Not Found``).
    """
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
        "uifid": uifid,
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
        # M6.48 — second-layer protection (msToken 实抓 + WebSign)
        # ------------------------------------------------------------------
        #
        # DouBi previously sent ``a_bogus`` only. 抖音 protected endpoints
        # (``/aweme/v1/web/mix/aweme/``, ``/aweme/v1/web/aweme/post/``,
        # ``/aweme/v1/web/aweme/detail/``, …) reject requests that lack:
        #
        # * a real ``msToken`` cookie (mssdk bytedance.com can mint one;
        #   a 182-char random string is well-formed, hence accepted by
        #   *signature* checks, but rejected by *behaviour* checks via
        #   the Argus plugin returning ``403 Uifid Not Found``)
        # * a non-empty ``uifid`` query parameter (visitor ID that binds
        #   the WebSign signature)
        # * the WebSign signature itself
        #   (``md5(uifid + "_" + timestamp + "_" + SALT + "_" + canonical_query)``,
        #   appended as ``x-secsdk-web-signature`` + ``timestamp``)
        #
        # Both fetcher classes fail *soft* (return ``None`` on any
        # transport / parse error) — we fall back to the previous
        # fake-msToken behaviour rather than crashing the expansion.
        #
        # We use a stable per-session UUID4 hex as the uifid visitor
        # identifier (16 chars, 64 bits of entropy). TikTokDL's note:
        # "uifid is a visitor ID" — the platform doesn't validate its
        # structure, only that it's present and stable across the
        # signature. A session-stable UUID4 satisfies that contract.
        #
        self._ms_token_fetcher = MsTokenFetcher(
            timeout=min(timeout, 10.0),
        )
        self._tt_wid_fetcher = TtWidFetcher(
            timeout=min(timeout, 10.0),
        )
        self._uifid: str = uuid.uuid4().hex[:16]
        # Locks to prevent concurrent _ensure_tokens fan-out (single
        # session-cookie mint, then reused by the whole GUI session).
        self._tokens_ready: bool = False
        self._tokens_lock: asyncio.Lock | None = None

    # ------------------------------------------------------------------
    # signing + transport
    # ------------------------------------------------------------------

    def _signed_url(
        self,
        path: str,
        params: dict[str, Any],
        *,
        base_url: Optional[str] = None,
    ) -> str:
        """Build a fully-signed URL: ``a_bogus`` + (M6.48) WebSign.

        Returns ``{endpoint}?{a_bogus_signed_query}`` where the signed
        query additionally carries ``timestamp`` and
        ``x-secsdk-web-signature`` for endpoints in
        :data:`doubi.platforms.douyin.sign.DOUYIN_SIGNED_PATHS`.

        ``base_url`` (M6.55) overrides the hard-coded
        :attr:`BASE_URL` so cross-host endpoints (``live.douyin.com`` /
        ``webcast.amemv.com``) can reuse the whole signing pipeline.
        ``a_bogus`` is computed over ``query + user_agent`` and is
        host-agnostic, so it is still the correct signature there.

        WebSign is *only* appended when:

        * the URL path matches the protected whitelist (``is_sign_protected``)
        * ``params["uifid"]`` is non-empty (we always populate it from
          the stable per-session ``_uifid`` since M6.48, so this guard
          is effectively always True now)

        For unprotected paths we skip WebSign — over-signing is
        harmless to the server (it just ignores the extras) but wastes
        CPU per request. ``_signed_url`` runs on every retry attempt,
        so we keep the hot path tight.

        Signing never raises (M2.x guarantee) — a failed ``a_bogus``
        or ``websign`` returns the unsigned URL with a logged warning.
        """
        query = urlencode(params)
        endpoint = f"{base_url or self.BASE_URL}{path}"
        try:
            fp = BrowserFingerprintGenerator.generate_fingerprint("Chrome")
            signer = ABogus(fp=fp, user_agent=self.user_agent)
            params_with_ab, _ab, _ua, _body = signer.generate_abogus(query, "")
        except Exception:
            # Signing must not be fatal — an unsigned request usually
            # fails with risk-control, but that is still a better error
            # than crashing the expansion.
            logger.warning("a_bogus generation failed; sending unsigned", exc_info=True)
            return f"{endpoint}?{query}"
        try:
            if is_sign_protected(endpoint) and self._uifid:
                # WebSign binds over the bytes that go on the wire,
                # which means we must feed it the already-a_bogus-signed
                # query string (not the original).
                params_with_ab = websign_sign(
                    params_with_ab, self._uifid,
                )[0]
        except Exception:
            # WebSign must not be fatal either — protected paths that
            # fail WebSign still get a_bogus (which lets some requests
            # through); unprotected paths are unaffected.
            logger.warning("x-secsdk-web-signature failed; sending a_bogus only",
                          exc_info=True)
        return f"{endpoint}?{params_with_ab}"

    async def _ensure_tokens(self) -> None:
        """One-shot real-msToken + tt-wid fetch (M6.48).

        Idempotent: the first call performs the network round-trip;
        subsequent calls return immediately. We mint both tokens as a
        pair because they're the two pieces of ``bytedance web`` session
        cookies 抖音 expects to see together.

        Failure handling
        ----------------
        * Network error → log + carry on with fake msToken (the
          request will 403, error_sink will get ``hint=need_login`` —
          M6.46 already handles this UX).
        * Token already in cookie file → fetchers skip and we just use
          what's there (``MsTokenFetcher.cached`` is initialised to the
          loaded value below).
        # NB: cookie-file msToken is preferred over a fresh mssdk
        # fetch because the user already authenticated and 抖音 considers
        # that token "more trusted" than a brand-new mssdk-minted one.
        """
        if self._tokens_ready:
            return
        if self._tokens_lock is None:
            # Lazy-init the lock once we have an event loop running.
            self._tokens_lock = asyncio.Lock()
        async with self._tokens_lock:
            if self._tokens_ready:
                return
            try:
                # Mint msToken if we don't already have one.
                if not self.cookies.get("msToken") and self._ms_token_fetcher.cached is None:
                    token = await self._ms_token_fetcher.fetch(
                        proxy=self.proxy,
                        headers={"User-Agent": self.user_agent},
                    )
                    if token:
                        # Inject into the cookie jar so the request
                        # carries it as a real Cookie header AND
                        # the query-string ``msToken`` parameter picks
                        # it up on the next loop.
                        self.cookies["msToken"] = token
                # Mint tt_wid if we don't already have one.
                if not self.cookies.get("ttwid") and self._tt_wid_fetcher.cached is None:
                    tt = await self._tt_wid_fetcher.fetch(
                        proxy=self.proxy,
                        headers={"User-Agent": self.user_agent},
                    )
                    if tt:
                        self.cookies["ttwid"] = tt
            finally:
                # Always mark ready — we don't want to retry forever
                # on a broken network. The next request will use the
                # fake-msToken fallback until something else refreshes
                # the cache (a successful 200 response, or a manual
                # ``invalidate_tokens()`` call).
                self._tokens_ready = True

    def invalidate_tokens(self) -> None:
        """Drop cached msToken / tt_wid so the next request re-fetches."""
        self._ms_token_fetcher.invalidate()
        self._tt_wid_fetcher.invalidate()
        self._tokens_ready = False

    async def _request_json(
        self,
        path: str,
        params: dict[str, Any],
        *,
        max_retries: int = 3,
        error_sink: Optional[MutableMapping[str, Any]] = None,
        base_url: Optional[str] = None,
        extra_headers: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        """GET a signed URL and parse the JSON body. Returns ``{}`` on failure.

        ``error_sink`` (optional, caller-owned): on terminal failure the
        dict is populated with ``{reason, status_code, hint}`` keys so UI
        surfaces can show user-facing messages ("需要登录抖音"). Pass
        ``None`` to keep the legacy swallow-and-log behaviour.

        ``base_url`` / ``extra_headers`` (M6.55): cross-host endpoints.
        直播 lives on ``live.douyin.com`` / ``webcast.amemv.com`` and
        wants a different ``Referer`` (and, for the reflow endpoint, a
        ``Range`` header) than the video-feed APIs. ``extra_headers``
        *merges over* :data:`_HEADERS` rather than replacing it, so the
        browser-looking baseline is never accidentally dropped.

        M6.48: on first call this lazy-fetches a real ``msToken`` from
        bytedance mssdk and a real ``ttwid`` from bytedance ttwid. Both
        are best-effort; failure falls back to a per-call random fake
        (same UX as before M6.48, just with one extra hop on first
        request).
        """
        delays = [1, 2, 5]
        last_error = "unknown"
        last_status: Optional[int] = None
        headers = {**_HEADERS, **(extra_headers or {})}
        # M6.48: one-shot token fetch (best-effort, never raises).
        # Subsequent retries reuse the cached cookie.
        try:
            await self._ensure_tokens()
        except Exception:  # noqa: BLE001
            logger.info("token ensure failed; continuing with fake msToken",
                       exc_info=True)
        for attempt in range(max_retries):
            ms_token = (self.cookies.get("msToken") or "").strip() or _false_ms_token()
            query = _default_query(ms_token, uifid=self._uifid)
            query.update(params)
            url = self._signed_url(path, query, base_url=base_url)
            try:
                async with httpx.AsyncClient(
                    timeout=self.timeout,
                    cookies=self.cookies,
                    headers=headers,
                    proxy=self.proxy or None,
                    follow_redirects=True,
                ) as client:
                    resp = await client.get(url)
                last_status = resp.status_code
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
                    if error_sink is not None:
                        _set_error_sink(
                            error_sink,
                            reason=f"HTTP {resp.status_code}",
                            status_code=resp.status_code,
                        )
                    return {}
            except httpx.HTTPError as exc:
                last_status = None
                last_error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "douyin web API %s attempt %d/%d failed: %s",
                path, attempt + 1, max_retries, last_error,
            )
            if attempt < max_retries - 1:
                await asyncio.sleep(delays[min(attempt, len(delays) - 1)])
        logger.error("douyin web API %s exhausted retries: %s", path, last_error)
        if error_sink is not None:
            _set_error_sink(
                error_sink, reason=last_error, status_code=last_status,
            )
        return {}

    # ------------------------------------------------------------------
    # SMS second-factor endpoints (M6.42)
    # ------------------------------------------------------------------

    async def send_sms_code(self, phone: str) -> dict[str, Any]:
        """Ask 抖音 to send an SMS code to ``phone``.

        2026-09 抖音扫码登录后,如果平台风控检测到设备/IP 异常,会
        触发二次 SMS 验证(用户会看到抖音 App / 短信验证码)。
        我们走 ``/passport/web/aweme/sms/send/`` 端点(用 a_bogus
        签名,跟其他 douyin web API 一样)。

        Returns the parsed JSON body. On failure returns ``{}`` (mirrors
        :meth:`_request_json` semantics). The caller must inspect
        ``status_code`` / ``error_code`` inside the dict to know whether
        the send actually succeeded — the network may have succeeded
        but the platform may have rate-limited the phone number.
        """
        params = {
            "mobile": phone,
            "aid": "6383",
            "channel": "web_pc",
        }
        return await self._request_json(
            "/passport/web/aweme/sms/send/",
            params,
            max_retries=2,
        )

    async def verify_sms_code(self, phone: str, code: str) -> dict[str, Any]:
        """Submit the SMS code 抖音 sent to ``phone``.

        On success the platform typically re-issues / refreshes the
        ``sessionid`` cookie — the caller must re-read the cookie
        file afterwards and call :func:`doubi.platforms.douyin.auth.
        login_info_from_cookies_sync` to confirm the second factor
        landed.  On failure the dict contains ``error_code`` /
        ``description`` describing why (wrong code / expired / etc.).
        """
        params = {
            "mobile": phone,
            "code": code,
            "aid": "6383",
            "channel": "web_pc",
        }
        return await self._request_json(
            "/passport/web/aweme/sms/verify/",
            params,
            max_retries=2,
        )

    # ------------------------------------------------------------------
    # endpoints
    # ------------------------------------------------------------------

    async def get_video_detail(self, aweme_id: str) -> Optional[dict[str, Any]]:
        """Single aweme detail (contains ``mix_info`` when part of a 合集).

        M6.56 — the returned dict preserves ``mix_info`` **verbatim**.
        :meth:`collection_of` reads the 合集 name off it, and
        :func:`extract_mix_ref` is the single place that knows the
        field layout. Do not strip unknown keys here: ``aweme_to_media_item``
        also consumes this dict, and dropping fields would silently
        degrade child cards.
        """
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
        """``mix_info`` for a 合集 id (``/aweme/v1/web/mix/detail/``).

        M6.56 — wired into :meth:`resolve_mix_ref`. This endpoint is
        **often 403'd** by 抖音 risk control for anonymous sessions
        (TikTokDL's ``Mix.run`` never calls it either — see
        ``resolve_mix_ref`` for the strategy), so callers must treat
        ``None`` as "probe elsewhere", never as "no such 合集".
        """
        data = await self._request_json("/aweme/v1/web/mix/detail/", {"mix_id": mix_id})
        if not data:
            return None
        mix_info = data.get("mix_info") or data.get("mix_detail") or data
        return mix_info if isinstance(mix_info, dict) else None

    async def resolve_mix_ref(
        self,
        *,
        mix_id: str = "",
        aweme_id: str = "",
        error_sink: Optional[MutableMapping[str, Any]] = None,
    ) -> dict[str, str]:
        """Best-effort ``{mix_id, mix_name?, mix_desc?}`` for a 合集.

        Tries, in order, stopping at the first hit that carries a name:

        1. ``/mix/detail/`` via :meth:`get_mix_detail` — the direct,
           cheapest answer when risk control lets it through
        2. ``/mix/aweme/`` page 1 via :meth:`get_mix_aweme` — the same
           fallback DouBi has used since M6.45 (``adapter._probe_mix_title``),
           and the one that actually works in practice; page-1 awemes
           carry ``mix_info``

        When only ``aweme_id`` is given (a user pasted a single video of
        a 合集), the aweme detail we already need is the cheapest source
        of ``mix_id`` — mirroring TikTokDL ``Mix.__get_mix_id``
        (``src/interface/mix.py:86-88``) which resolves the id from a
        ``Detail`` call before enumerating.

        Returns ``{}`` when nothing resolved. ``error_sink`` is
        forwarded to the *last* request issued, so a caller that gets
        ``{}`` back can still distinguish "403 / need_login" from
        "platform says no name".
        """
        ref: dict[str, str] = {}

        if not mix_id and aweme_id:
            detail = await self.get_video_detail(aweme_id)
            if detail:
                ref = extract_mix_ref(detail)
                mix_id = ref.get("mix_id", "")
            if not mix_id:
                return {}

        if not mix_id:
            return {}

        ref.setdefault("mix_id", mix_id)
        if ref.get("mix_name"):
            return ref

        detail_info = await self.get_mix_detail(mix_id)
        if detail_info:
            named = extract_mix_ref({"mix_info": detail_info})
            if named.get("mix_name"):
                return named
            # id confirmed but still nameless — keep going to page 1

        page = await self.get_mix_aweme(mix_id, count=1, error_sink=error_sink)
        for raw in page["items"]:
            aweme = raw if raw.get("aweme_id") else (
                raw.get("aweme_info") or raw.get("aweme") or {}
            )
            found = extract_mix_ref(aweme)
            if found.get("mix_name"):
                return found
        return ref

    async def get_mix_aweme(
        self,
        mix_id: str,
        *,
        cursor: int = 0,
        count: int = 20,
        error_sink: Optional[MutableMapping[str, Any]] = None,
    ) -> dict[str, Any]:
        """One page of a 合集's videos.

        ``error_sink`` is forwarded to :meth:`_request_json` — see that
        method for the keys written on failure.
        """
        raw = await self._request_json(
            "/aweme/v1/web/mix/aweme/",
            {"mix_id": mix_id, "cursor": cursor, "count": count},
            error_sink=error_sink,
        )
        return _normalize_page(raw, item_keys=("aweme_list",))

    async def get_user_post(
        self,
        sec_uid: str,
        *,
        max_cursor: int = 0,
        count: int = 18,
        error_sink: Optional[MutableMapping[str, Any]] = None,
    ) -> dict[str, Any]:
        """One page of a user's published videos.

        ``error_sink`` is forwarded to :meth:`_request_json`.
        """
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
            error_sink=error_sink,
        )
        return _normalize_page(raw, item_keys=("aweme_list",))

    # ------------------------------------------------------------------
    # paginated enumerators
    # ------------------------------------------------------------------

    async def iter_mix_awemes(
        self,
        mix_id: str,
        *,
        max_count: int = 0,
        error_sink: Optional[MutableMapping[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """All (or the first ``max_count``) awemes of a 合集.

        ``error_sink`` (caller-owned mutable mapping) is populated with
        ``{reason, status_code, hint}`` on transport / risk-control
        failure so the caller can decide whether to surface "需要抖音登录"
        to the user. The mapping is *not* touched on the happy path.
        """
        awemes: list[dict[str, Any]] = []
        cursor = 0
        while True:
            page = await self.get_mix_aweme(
                mix_id, cursor=cursor, error_sink=error_sink,
            )
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

    async def iter_user_posts(
        self,
        sec_uid: str,
        *,
        max_count: int = 0,
        error_sink: Optional[MutableMapping[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """All (or the first ``max_count``) published awemes of a user.

        ``error_sink`` is forwarded to :meth:`_request_json` so callers
        see the same risk-control hint machinery as :meth:`iter_mix_awemes`.
        """
        awemes: list[dict[str, Any]] = []
        cursor = 0
        while True:
            page = await self.get_user_post(
                sec_uid, max_cursor=cursor, error_sink=error_sink,
            )
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

    # ------------------------------------------------------------------
    # M6.49 — search (general / video / user / live)
    # ------------------------------------------------------------------
    #
    # Adapted from Johnserf-Shell/TikTokDownloader src/interface/search.py
    # (MIT). The four endpoints share the same pagination model
    # (offset + search_id from response.log_pb.impr_id) but differ in:
    #   - path & data_key
    #   - filter payload (``filter_selected`` JSON URL-encoded vs
    #     ``search_filter_value``)
    #   - ``version_code`` / ``version_name`` (general = 19.6.0,
    #     others = 17.4.0)
    #
    # The endpoints are in the DOUYIN_SIGNED_PATHS whitelist, so the
    # M6.48 WebSign layer attaches automatically. We add 4 thin
    # methods here + one shared pagination helper. ``aweme_to_media_item``
    # adapts search result dicts to MediaItem so callers (CLI / future
    # GUI) don't need to learn the webapi schema.
    #

    async def _search_paginate(
        self,
        endpoint: str,
        *,
        data_key: str,
        extra_params: dict[str, Any],
        unwrap_lives: bool = False,
        count: int = 10,
        max_count: int = 0,
        max_pages: int = 50,
        error_sink: Optional[MutableMapping[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """Paginate a search endpoint via offset + search_id.

        - ``data_key``: top-level key holding the page items
          (``data`` / ``user_list``).
        - ``unwrap_lives``: True for live search where each page item
          is a wrapper holding a ``lives`` sub-list (TikTokDL
          ``append_response_video:395``); items are extracted raw so the
          caller's downstream consumer can decide.
        - ``max_pages``: hard stop regardless of ``max_count`` / ``has_more``.
          抖音 occasionally returns ``has_more=True`` forever; this
          prevents an infinite loop.

        Returns a flat list of dicts. Dedupes by ``aweme_id`` /
        ``user_id`` / ``room_id`` (whichever the response carries).
        """
        items: list[dict[str, Any]] = []
        offset = 0
        search_id: Optional[str] = None
        seen: set[str] = set()
        for _page in range(max_pages):
            params = dict(extra_params)
            params["offset"] = offset
            params["count"] = count
            if search_id:
                params["search_id"] = search_id
            data = await self._request_json(
                endpoint, params, error_sink=error_sink,
            )
            page_items = data.get(data_key) or []
            if not page_items:
                break
            # Live search wraps each row in {lives: [...]}; unwrap.
            if unwrap_lives:
                unwrapped: list[dict[str, Any]] = []
                for wrapper in page_items:
                    lives = wrapper.get("lives") if isinstance(wrapper, dict) else None
                    if isinstance(lives, list):
                        unwrapped.extend(lives)
                page_items = unwrapped
                if not page_items:
                    break
            # Update cursor before appending (TikTokDL line 376)
            offset = data.get("cursor", offset + count)
            log_pb = data.get("log_pb")
            if isinstance(log_pb, dict) and log_pb.get("impr_id"):
                search_id = log_pb["impr_id"]
            for item in page_items:
                if not isinstance(item, dict):
                    continue
                # Live search items have ``room_id``; user search has
                # ``user_id``; everything else has ``aweme_id``. We
                # can't use ``str(...) or str(...)`` here — ``str(None)``
                # is the literal string ``"None"`` which is truthy and
                # would mask the next key in the fallback chain.
                key = ""
                for k in ("aweme_id", "user_id", "room_id"):
                    v = item.get(k)
                    if v is not None:
                        key = str(v)
                        break
                if not key:
                    items.append(item)
                    continue
                if key in seen:
                    continue
                seen.add(key)
                items.append(item)
            if max_count and len(items) >= max_count:
                return items[:max_count]
            if not data.get("has_more"):
                break
            # Defensive: if cursor stuck, stop (TikTokDL doesn't but
            # we hit the loop in the wild).
            if not data.get("cursor"):
                break
        return items

    # ------------------------------------------------------------------
    # M6.51 — 收藏夹全家族（5 端点）
    # ------------------------------------------------------------------
    #
    # Adapted from Johnserf-Shell/TikTokDownloader ``src/interface/collects.py``
    # (MIT). Five classes / endpoints cover the user's "saved content"
    # surfaces:
    #
    #   iter_collects           /aweme/v1/web/collects/list/         data.collects_list
    #   iter_collects_videos    /aweme/v1/web/collects/video/list/   data.aweme_list    (+collects_id)
    #   iter_collects_mix       /aweme/v1/web/mix/listcollection/    data.mix_infos
    #   iter_collects_music     /aweme/v1/web/music/listcollection/  data.mc_list
    #   iter_collects_series    /aweme/v1/web/series/collections/    data.series_infos
    #
    # All 5 endpoints share the same cursor+count+has_more shape, so a
    # single ``_cursor_paginate`` helper handles the boilerplate; the
    # public iter_collects_* methods are thin wrappers that pin
    # endpoint + data_key + endpoint-specific extra_params.
    #
    # **Login dependency**: every endpoint's referer is
    # ``https://www.douyin.com/user/self?showTab=favorite_collection``
    # (TikTokDL ``collects.py`` line 41 etc.). Without a logged-in
    # session the platform returns ``401`` or empty ``collects_list``.
    # We surface this via the existing ``error_sink`` plumbing
    # (``hint="need_login"`` — M6.46 machinery), so the CLI prints
    # ``试试 --cookies-file ~/.doubi/cookies/douyin.txt`` like the
    # USER container does in M6.47. No cookie file → the client runs
    # unauthenticated; the user just sees an empty list or 401.

    async def _cursor_paginate(
        self,
        endpoint: str,
        *,
        data_key: str,
        extra_params: dict[str, Any],
        count: int = 10,
        max_count: int = 0,
        max_pages: int = 50,
        error_sink: Optional[MutableMapping[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """Paginate a ``cursor + count + has_more`` endpoint.

        - ``data_key``: top-level key holding the page items.
        - ``extra_params``: endpoint-specific params (merged with
          ``cursor`` / ``count`` every page; ``extra_params["cursor"]``
          is overridden by the loop cursor so callers don't have to
          think about it).
        - ``max_pages=50``: hard cap regardless of ``max_count`` /
          ``has_more`` — mirrors :meth:`_search_paginate`.
        - ``error_sink`` is forwarded to :meth:`_request_json`.

        Returns a flat list of dicts. No dedup: TikTokDL doesn't dedup
        here, and the platform typically doesn't echo rows on this
        family (each cursor advances monotonically).
        """
        items: list[dict[str, Any]] = []
        cursor = 0
        for _page in range(max_pages):
            params: dict[str, Any] = dict(extra_params)
            params["cursor"] = cursor
            params["count"] = count
            data = await self._request_json(
                endpoint, params, error_sink=error_sink,
            )
            page_items = data.get(data_key) if isinstance(data, dict) else None
            if not isinstance(page_items, list) or not page_items:
                break
            items.extend(
                row for row in page_items if isinstance(row, dict)
            )
            if max_count and len(items) >= max_count:
                return items[:max_count]
            if not (data.get("has_more") if isinstance(data, dict) else False):
                break
            next_cursor = data.get("cursor", 0)
            if next_cursor == cursor or not next_cursor:
                # Defensive: avoid infinite loop on stuck cursor.
                break
            cursor = next_cursor
        return items

    async def iter_collects(
        self,
        *,
        count: int = 10,
        max_count: int = 0,
        error_sink: Optional[MutableMapping[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """List my 收藏夹 folders.

        Returns one entry per collect (``collects_id`` / name / etc.).
        Login-gated — without cookies the platform returns ``401`` or an
        empty ``collects_list`` (TikTokDL ``collects.py:58`` surfaces
        「当前账号无收藏夹」).
        """
        return await self._cursor_paginate(
            "/aweme/v1/web/collects/list/",
            data_key="collects_list",
            extra_params={
                "version_code": "170400",
                "version_name": "17.4.0",
            },
            count=count,
            max_count=max_count,
            error_sink=error_sink,
        )

    async def iter_collects_videos(
        self,
        collects_id: str,
        *,
        count: int = 10,
        max_count: int = 0,
        error_sink: Optional[MutableMapping[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """Videos inside one 收藏夹 folder.

        ``collects_id`` is the value from :meth:`iter_collects`'s
        ``collects_id`` field. The platform returns ``aweme_list`` —
        plain aweme dicts identical in structure to ``mix_aweme`` and
        ``user_post`` pages, so existing ``_extract_awemes`` machinery
        handles the wrapping (``aweme`` / ``aweme_info`` keys).
        """
        if not collects_id:
            return []
        return await self._cursor_paginate(
            "/aweme/v1/web/collects/video/list/",
            data_key="aweme_list",
            extra_params={
                "collects_id": str(collects_id),
                "version_code": "170400",
                "version_name": "17.4.0",
            },
            count=count,
            max_count=max_count,
            error_sink=error_sink,
        )

    async def iter_collects_mix(
        self,
        *,
        count: int = 12,
        max_count: int = 0,
        error_sink: Optional[MutableMapping[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """List my 收藏合集 (saved 合集/MIX).

        Each row is a ``mix_info`` dict with ``mix_id`` / ``mix_name``
        / cover / etc. — same shape as ``get_mix_detail`` returns.
        To expand a saved mix, pass ``mix_id`` to ``iter_mix_awemes``.
        """
        return await self._cursor_paginate(
            "/aweme/v1/web/mix/listcollection/",
            data_key="mix_infos",
            extra_params={
                "version_code": "170400",
                "version_name": "17.4.0",
            },
            count=count,
            max_count=max_count,
            error_sink=error_sink,
        )

    async def iter_collects_music(
        self,
        *,
        count: int = 20,
        max_count: int = 0,
        error_sink: Optional[MutableMapping[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """List my 收藏音乐 (saved music collections).

        Each row carries ``mc_id`` / ``mc_name`` / ``mc_cover`` etc.
        — TikTokDL's ``mc_list`` payload (line 276). Music collection
        expansion is out of scope for M6.51; CLI just lists the rows.
        """
        return await self._cursor_paginate(
            "/aweme/v1/web/music/listcollection/",
            data_key="mc_list",
            extra_params={
                "version_code": "170400",
                "version_name": "17.4.0",
            },
            count=count,
            max_count=max_count,
            error_sink=error_sink,
        )

    async def iter_collects_series(
        self,
        *,
        count: int = 12,
        max_count: int = 0,
        error_sink: Optional[MutableMapping[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """List my 收藏短剧 (saved short-drama series).

        Each row is a ``series_info`` dict (``series_infos`` key).
        Series expansion is out of scope for M6.51; CLI just lists
        the rows.
        """
        return await self._cursor_paginate(
            "/aweme/v1/web/series/collections/",
            data_key="series_infos",
            extra_params={
                "version_code": "170400",
                "version_name": "17.4.0",
            },
            count=count,
            max_count=max_count,
            error_sink=error_sink,
        )

    # ------------------------------------------------------------------
    # M6.52 — 评论 + 回复
    # ------------------------------------------------------------------
    #
    # Adapted from Johnserf-Shell/TikTokDownloader ``src/interface/comment.py``
    # (MIT). Two endpoints share the same cursor+count+has_more shape:
    #
    #   iter_aweme_comments      /aweme/v1/web/comment/list/         data.comments
    #   iter_comment_replies     /aweme/v1/web/comment/list/reply/   data.comments
    #                                                            (+comment_id)
    #
    # Reuse the M6.51 ``_cursor_paginate`` helper (same shape). We
    # DON'T port TikTokDL's ``Extractor.extract_reply_ids`` + nested
    # ``run_reply`` callback: DouBi's iter pattern lets the caller
    # drive the second call explicitly (``iter_comment_replies(cid)``),
    # which is simpler than the callback-and-extract approach.
    #
    # Login gating is *softer* than the favorites family: public
    # comments on public videos are visible without login, but the
    # platform returns risk-control responses on higher volumes. The
    # error_sink machinery (M6.46) handles the same UX.

    async def iter_aweme_comments(
        self,
        aweme_id: str,
        *,
        count: int = 10,
        max_count: int = 0,
        error_sink: Optional[MutableMapping[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """All (or the first ``max_count``) top-level comments on a video.

        ``aweme_id`` is the standard ``aweme_id`` field (same value
        used by ``get_video_detail`` / ``iter_mix_awemes`` /
        ``iter_user_posts``).

        Each returned row is a comment dict with ``cid`` / ``text`` /
        ``user`` / ``create_time`` / ``reply_count`` etc. The
        ``reply_count`` field tells the caller how many replies exist
        on that comment — pass ``cid`` to :meth:`iter_comment_replies`
        to fetch them.
        """
        if not aweme_id:
            return []
        return await self._cursor_paginate(
            "/aweme/v1/web/comment/list/",
            data_key="comments",
            extra_params={
                "aweme_id": str(aweme_id),
                "pc_img_format": "webp",
                "item_type": "0",
                "insert_ids": "",
                "whale_cut_token": "",
                "cut_version": "1",
                "rcFT": "",
                "version_code": "170400",
                "version_name": "17.4.0",
            },
            count=count,
            max_count=max_count,
            error_sink=error_sink,
        )

    async def iter_comment_replies(
        self,
        aweme_id: str,
        comment_id: str,
        *,
        count: int = 3,
        max_count: int = 0,
        error_sink: Optional[MutableMapping[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """All (or the first ``max_count``) replies under one comment.

        ``aweme_id`` is the video id and ``comment_id`` is the parent
        comment's ``cid`` field. Both are required — TikTokDL
        ``comment.py:230`` and ``:240`` send ``item_id`` + ``comment_id``
        together.

        Each returned row has the same shape as a comment (same
        endpoint family uses ``data_key="comments"`` server-side).
        """
        if not aweme_id or not comment_id:
            return []
        return await self._cursor_paginate(
            "/aweme/v1/web/comment/list/reply/",
            data_key="comments",
            extra_params={
                "item_id": str(aweme_id),
                "comment_id": str(comment_id),
                "cut_version": "1",
                "item_type": "0",
                "version_code": "170400",
                "version_name": "17.4.0",
            },
            count=count,
            max_count=max_count,
            error_sink=error_sink,
        )

    # ------------------------------------------------------------------
    # M6.54 — 关注列表 + 粉丝列表
    # ------------------------------------------------------------------
    #
    # **TikTokDL 无源** — Survey §8.1 item 10 已标 ❌ 「TikTokDL 的
    # ``User`` 接口只拿个人资料（``profile/other``），没有 following /
    # follower 实现」。本里程碑是 DouBi 原生实现，遵循 M6.51
    # ``_cursor_paginate`` 模式 + 公开 Douyin web API 端点路径。
    #
    # 端点：
    #   iter_user_following   /aweme/v1/web/user/following/list/    data.followings
    #   iter_user_followers   /aweme/v1/web/user/follower/list/    data.followers
    #
    # 都是 cursor + count + has_more 翻页，data_key 区分。用户场景：
    #   - 「我关注的人」列表（关注列表）
    #   - 「关注我的人」列表（粉丝列表）
    # 都登录依赖（platform referer 不强制，但 server-side 校验 cookie 状态）。

    async def iter_user_following(
        self,
        sec_user_id: str,
        *,
        count: int = 20,
        max_count: int = 0,
        error_sink: Optional[MutableMapping[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """「我关注的人」列表 (the user identified by ``sec_user_id``).

        Each returned row is a user dict with ``sec_uid`` /
        ``nickname`` / ``avatar_url`` / etc. (same shape as
        ``search_user`` returns — caller can reuse UserAdapter if
        needed).
        """
        if not sec_user_id:
            return []
        return await self._cursor_paginate(
            "/aweme/v1/web/user/following/list/",
            data_key="followings",
            extra_params={
                "user_id": str(sec_user_id),
                "sec_user_id": str(sec_user_id),
                "count": count,  # caller-tunable; platform default 20
                "offset": 0,
                "source": "following",
                "version_code": "170400",
                "version_name": "17.4.0",
            },
            count=count,
            max_count=max_count,
            error_sink=error_sink,
        )

    async def iter_user_followers(
        self,
        sec_user_id: str,
        *,
        count: int = 20,
        max_count: int = 0,
        error_sink: Optional[MutableMapping[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """「关注我的人」列表 (followers of the user identified by ``sec_user_id``).

        Same shape as :meth:`iter_user_following`.
        """
        if not sec_user_id:
            return []
        return await self._cursor_paginate(
            "/aweme/v1/web/user/follower/list/",
            data_key="followers",
            extra_params={
                "user_id": str(sec_user_id),
                "sec_user_id": str(sec_user_id),
                "count": count,
                "offset": 0,
                "source": "follower",
                "version_code": "170400",
                "version_name": "17.4.0",
            },
            count=count,
            max_count=max_count,
            error_sink=error_sink,
        )

    # ------------------------------------------------------------------
    # 话题 / 挑战 (HashTag)
    #
    # **TikTokDL 无源** — Survey §8.1 item 13 已标 ❌ 且注明「即便是空壳：
    # ``src/interface/hashtag.py`` 的 ``run()`` 正文只有 ``pass``，连
    # ``self.api`` 都没声明」。所以本里程碑**不是移植**，是 DouBi 原生
    # 实现，端点为抖音 web 话题页的作品流路径。
    #
    # 端点：
    #   iter_challenge_awemes   /aweme/v1/web/challenge/aweme/   data.aweme_list
    #
    # 翻页是 cursor + count + has_more，复用 M6.51 的 ``_cursor_paginate``。
    # 话题 id（``ch_id``）来自话题页 URL ``/challenge/detail/{ch_id}``。
    # 公开话题不强制登录，但风控强度与搜索同级。
    # ------------------------------------------------------------------

    async def iter_challenge_awemes(
        self,
        ch_id: str,
        *,
        count: int = 20,
        max_count: int = 0,
        sort_type: int = 0,
        error_sink: Optional[MutableMapping[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """一个话题（challenge / HashTag）下的作品列表。

        Each row is a plain aweme dict — identical in structure to what
        :meth:`iter_mix_awemes` yields, so callers can feed them
        straight into (or through) ``aweme_to_media_item``.

        ``sort_type``: 0 = 综合排序, 1 = 最新发布. The platform silently
        ignores unknown values rather than erroring, so an out-of-range
        int degrades to 综合排序 instead of failing.

        Returns ``[]`` for a blank ``ch_id`` — a missing id is a caller
        bug, not a platform condition, and issuing a request with an
        empty ``ch_id`` would just burn a risk-control budget slot.
        """
        if not ch_id:
            return []
        return await self._cursor_paginate(
            "/aweme/v1/web/challenge/aweme/",
            data_key="aweme_list",
            extra_params={
                "ch_id": str(ch_id),
                "sort_type": int(sort_type),
                "count": count,
                "version_code": "170400",
                "version_name": "17.4.0",
            },
            count=count,
            max_count=max_count,
            error_sink=error_sink,
        )

    async def search_general(
        self,
        keyword: str,
        *,
        count: int = 10,
        max_count: int = 0,
        sort_type: int = 0,
        publish_time: int = 0,
        duration: int = 0,
        search_range: int = 0,
        content_type: int = 0,
        error_sink: Optional[MutableMapping[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """综合搜索 (general) — TikTokDL channel 0.

        Filter arguments all default to ``0`` (不限). See
        ``search.py:60-105`` for the meaning of each (e.g.
        ``sort_type=1`` = 最多点赞, ``publish_time=7`` = 一周内,
        ``duration=2`` = 1-5 分钟).
        """
        params: dict[str, Any] = {
            "pc_search_top_1_params": '{"enable_ai_search_top_1":1}',
            "search_channel": "aweme_general",
            "enable_history": "1",
            "keyword": keyword,
            "search_source": "switch_tab",
            "query_correct_type": "1",
            "is_filter_search": "0",
            "from_group_id": "",
            "disable_rs": "0",
            "need_filter_settings": "0",
            "list_type": "single",
            "version_code": "190600",
            "version_name": "19.6.0",
        }
        if any((sort_type, publish_time, duration, search_range, content_type)):
            filter_selected = json.dumps(
                {
                    "sort_type": f"{sort_type}",
                    "publish_time": f"{publish_time}",
                    "filter_duration": f"{duration}",
                    "search_range": f"{search_range}",
                    "content_type": f"{content_type}",
                },
                separators=(",", ":"),
            )
            params["filter_selected"] = quote(filter_selected)
            params["is_filter_search"] = "1"
        return await self._search_paginate(
            "/aweme/v1/web/general/search/single/",
            data_key="data",
            extra_params=params,
            count=count,
            max_count=max_count,
            error_sink=error_sink,
        )

    async def search_video(
        self,
        keyword: str,
        *,
        count: int = 10,
        max_count: int = 0,
        sort_type: int = 0,
        publish_time: int = 0,
        duration: int = 0,
        search_range: int = 0,
        error_sink: Optional[MutableMapping[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """视频搜索 (video) — TikTokDL channel 1.

        No ``content_type`` filter (TikTokDL doesn't expose it for
        video-only search). Other filter semantics match
        :meth:`search_general`.
        """
        params: dict[str, Any] = {
            "pc_search_top_1_params": '{"enable_ai_search_top_1":1}',
            "search_channel": "aweme_video_web",
            "enable_history": "1",
            "keyword": keyword,
            "search_source": "switch_tab",
            "query_correct_type": "1",
            "is_filter_search": "0",
            "from_group_id": "",
            "disable_rs": "0",
            "need_filter_settings": "0",
            "list_type": "single",
            "version_code": "170400",
            "version_name": "17.4.0",
        }
        if sort_type:
            params["sort_type"] = f"{sort_type}"
            params["is_filter_search"] = "1"
        if publish_time:
            params["publish_time"] = f"{publish_time}"
            params["is_filter_search"] = "1"
        if duration:
            params["filter_duration"] = f"{duration}"
            params["is_filter_search"] = "1"
        if search_range:
            params["search_range"] = f"{search_range}"
            params["is_filter_search"] = "1"
        return await self._search_paginate(
            "/aweme/v1/web/search/item/",
            data_key="data",
            extra_params=params,
            count=count,
            max_count=max_count,
            error_sink=error_sink,
        )

    async def search_user(
        self,
        keyword: str,
        *,
        count: int = 10,
        max_count: int = 0,
        fans: int = 0,
        user_type: int = 0,
        error_sink: Optional[MutableMapping[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """用户搜索 (user) — TikTokDL channel 2.

        ``fans`` and ``user_type`` map to TikTokDL's ``search_filter_value``
        (note: this endpoint uses a *different* filter payload than
        general/video — ``search_filter_value``, not
        ``filter_selected``). Possible values:
            ``fans``  : 0 不限 / 1 1000以下 / 2 1k-1w / 3 1w-10w / 4 10w-100w / 5 100w以上
            ``user_type``: 0 不限 / 1 普通用户 / 2 企业认证 / 3 个人认证
        """
        params: dict[str, Any] = {
            "pc_search_top_1_params": '{"enable_ai_search_top_1":1}',
            "search_channel": "aweme_user_web",
            "enable_history": "1",
            "keyword": keyword,
            "search_source": "switch_tab",
            "query_correct_type": "1",
            "is_filter_search": "0",
            "from_group_id": "",
            "disable_rs": "0",
            "need_filter_settings": "0",
            "list_type": "single",
            "version_code": "170400",
            "version_name": "17.4.0",
        }
        if fans or user_type:
            search_filter_value = json.dumps(
                {
                    "douyin_user_fans": [""],
                    "douyin_user_type": [""],
                },
                separators=(",", ":"),
            )
            # Replace the empty strings with the real selection lists
            # (TikTokDL's pattern: the JSON keys always carry a *list*
            # of values, even when "all" is the choice).
            if fans:
                search_filter_value = json.dumps(
                    {
                        "douyin_user_fans": _DOYIN_USER_FANS_MAP.get(fans, [""]),
                        "douyin_user_type": _DOYIN_USER_TYPE_MAP.get(user_type, [""]),
                    },
                    separators=(",", ":"),
                )
            params["search_filter_value"] = quote(search_filter_value)
            params["is_filter_search"] = "1"
        return await self._search_paginate(
            "/aweme/v1/web/discover/search/",
            data_key="user_list",
            extra_params=params,
            count=count,
            max_count=max_count,
            error_sink=error_sink,
        )

    async def search_live(
        self,
        keyword: str,
        *,
        count: int = 10,
        max_count: int = 0,
        error_sink: Optional[MutableMapping[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """直播搜索 (live) — TikTokDL channel 3.

        Live search has no filter arguments; each page item wraps the
        actual ``lives`` list (TikTokDL line 395 ``append_response_video``).
        """
        params: dict[str, Any] = {
            "pc_search_top_1_params": '{"enable_ai_search_top_1":1}',
            "search_channel": "aweme_live",
            "keyword": keyword,
            "search_source": "switch_tab",
            "query_correct_type": "1",
            "is_filter_search": "0",
            "from_group_id": "",
            "disable_rs": "0",
            "need_filter_settings": "0",
            "list_type": "single",
            "version_code": "170400",
            "version_name": "17.4.0",
        }
        return await self._search_paginate(
            "/aweme/v1/web/live/search/",
            data_key="data",
            extra_params=params,
            unwrap_lives=True,
            count=count,
            max_count=max_count,
            error_sink=error_sink,
        )

    # ------------------------------------------------------------------
    # M6.50 — hot 榜 (single board)
    # ------------------------------------------------------------------
    #
    # Adapted from Johnserf-Shell/TikTokDownloader ``src/interface/hot.py``
    # (MIT). Unlike the search endpoints, hot 榜 is *single-page* —
    # TikTokDL's hot.py explicitly passes ``single_page=True`` and the
    # endpoint returns the top-N hot words for the chosen board in one
    # shot (no cursor / search_id).
    #
    # Response shape: ``data.word_list`` is a list of *word* entries
    # (NOT videos). Each entry has ``word``, ``hot_value``, ``position``,
    # ``sentence_id``, ``video_count``, ``cover_url``. ``sentence_id`` is
    # the bridge to related videos — a separate search/feed call would
    # enumerate them. DouBi doesn't enumerate today; we surface what
    # the platform returns and let the user pick what to follow up on.
    #
    # The endpoint is in :data:`DOUYIN_SIGNED_PATHS` (added in M6.50)
    # so the M6.48 WebSign layer attaches automatically.
    #
    # No login dependency: TikTokDL's hot.py overrides ``Cookie: ""``
    # in __init__, which is exactly the unauthenticated path. DouBi
    # picks that up — no cookies means *no* cookies argument, which is
    # the same wire-level behaviour.

    async def get_hot_list(
        self,
        board: str = "positive",
        *,
        max_count: int = 0,
        error_sink: Optional[MutableMapping[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """Top hot words for one 抖音 hot board.

        ``board`` must be one of :data:`ALL_HOT_BOARDS`. Unknown boards
        return ``[]`` — the argparse ``choices`` constraint catches bad
        board names at the CLI level before we get here.

        ``max_count``: optional cap; ``0`` = "give me all the platform
        returned" (TikTokDL's tests show ~50 rows typical).

        ``error_sink`` is forwarded to :meth:`_request_json` so the
        same UX ("需要登录抖音" / 5xx / transient) lands in the CLI's
        stderr as the search family.

        Returned rows are platform word entries (NOT videos). Useful
        fields:

        * ``word`` — the hot phrase
        * ``hot_value`` — heat score (integer)
        * ``position`` — rank
        * ``sentence_id`` — bridge to related videos
        * ``video_count`` — how many videos are associated
        * ``cover_url`` — optional cover image
        """
        params = HOT_BOARD_PARAMS.get(board)
        if params is None:
            return []
        board_type, board_sub_type = params
        data = await self._request_json(
            "/aweme/v1/web/hot/search/list/",
            {
                "detail_list": "1",
                "source": "6",
                "board_type": board_type,
                "board_sub_type": board_sub_type,
                "version_code": "170400",
                "version_name": "17.4.0",
            },
            max_retries=2,
            error_sink=error_sink,
        )
        word_list = data.get("word_list") if isinstance(data, dict) else None
        if not isinstance(word_list, list):
            return []
        if max_count and len(word_list) > max_count:
            word_list = word_list[:max_count]
        return word_list

    # ------------------------------------------------------------------
    # 直播 detail + multi-quality (M6.55)
    # ------------------------------------------------------------------

    async def get_live_room(
        self,
        web_rid: str,
        *,
        error_sink: Optional[MutableMapping[str, Any]] = None,
    ) -> dict[str, Any]:
        """Live-room detail for a ``live.douyin.com/{web_rid}`` link.

        Adapted from TikTokDL ``interface/live.py:43-70``
        (``Live.with_web_rid``). Returns the flattened record from
        :func:`normalize_live_room`, or ``{}`` when the ``web_rid`` is
        unusable / the room payload is missing.

        This endpoint answers **without login** for public rooms — the
        main gating is 抖音's risk control, so a 403 here means the
        signature was rejected rather than the user being anonymous.
        ``error_sink`` still gets the usual ``hint`` so the CLI can
        print a coherent message either way.
        """
        rid = extract_live_web_rid(web_rid)
        if not rid:
            return {}
        params = dict(LIVE_ENTER_PARAMS)
        params["web_rid"] = rid
        data = await self._request_json(
            LIVE_ENTER_PATH,
            params,
            max_retries=2,
            error_sink=error_sink,
            base_url=LIVE_ENTER_BASE,
            extra_headers={"Referer": LIVE_REFERER},
        )
        return normalize_live_room(data, web_rid=rid)

    async def get_live_room_by_room_id(
        self,
        room_id: str,
        *,
        sec_user_id: str = "",
        error_sink: Optional[MutableMapping[str, Any]] = None,
    ) -> dict[str, Any]:
        """Live-room detail for an internal ``room_id``.

        Adapted from TikTokDL ``interface/live.py:72-84``
        (``Live.with_room_id``). Fills the gap left by
        :meth:`get_live_room`: ``doubi search --type live`` hands back
        ``aweme_id``, which on this endpoint *is* the ``room_id``, and
        the share/reflow host is the only one that accepts it.

        ``sec_user_id`` is optional upstream too (TikTokDL defaults it
        to ``""``) but passing the author's ``sec_uid`` from a search
        row makes the request look closer to the real client.
        """
        rid = (room_id or "").strip()
        if not rid:
            return {}
        data = await self._request_json(
            LIVE_REFLOW_PATH,
            {
                "type_id": "0",
                "live_id": "1",
                "room_id": rid,
                "sec_user_id": (sec_user_id or "").strip(),
                "app_id": "1128",
            },
            max_retries=2,
            error_sink=error_sink,
            base_url=LIVE_REFLOW_BASE,
            extra_headers=LIVE_REFLOW_HEADERS,
        )
        return normalize_live_room(data, room_id=rid)


def pick_live_quality(
    room: dict[str, Any],
    choice: Optional[str] = None,
    *,
    prefer: str = "flv",
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """Resolve a user's ``--quality`` choice against a room record.

    ``choice`` is matched, in order, against:

    * ``"best"`` / ``None`` / ``""`` → the first (highest) row
    * the raw platform key, case-insensitively (``"hd1"`` → ``HD1``)
    * the display label (``"高清"`` / ``"蓝光"``)
    * a 1-based index (``"2"``)

    Returns ``(row, url)`` where ``url`` is the ``prefer`` container's
    URL, falling back to the other container when only one is present.
    Returns ``(None, None)`` when nothing matches so callers can report
    "unknown quality" instead of silently recording the wrong stream.

    Kept as a module-level pure function (not a method) so the CLI,
    the tests, and any future MCP tool share one selection semantics.
    """
    rows = room.get("qualities")
    if not isinstance(rows, list) or not rows:
        return None, None

    wanted = (choice or "").strip()
    row: Optional[dict[str, Any]] = None
    if not wanted or wanted.lower() == "best":
        row = rows[0]
    else:
        low = wanted.lower()
        for candidate in rows:
            if str(candidate.get("key", "")).lower() == low:
                row = candidate
                break
        if row is None:
            row = next((c for c in rows if c.get("name") == wanted), None)
        if row is None and wanted.isdigit():
            idx = int(wanted) - 1
            if 0 <= idx < len(rows):
                row = rows[idx]
    if row is None:
        return None, None

    primary = "hls" if prefer == "hls" else "flv"
    secondary = "flv" if primary == "hls" else "hls"
    url = row.get(primary) or row.get(secondary)
    return row, url if isinstance(url, str) and url else None


# ---------------------------------------------------------------------------
# 合集 (MIX) reference helpers — M6.56
# ---------------------------------------------------------------------------


def extract_mix_ref(aweme: dict[str, Any]) -> dict[str, str]:
    """Pull the 合集 reference out of one aweme dict.

    Mirrors TikTokDL ``Extractor.extract_mix_id``
    (``src/extract/extractor.py:1546-1548``), which is literally
    ``safe_extract(data, "mix_info.mix_id")`` — a dotted lookup with an
    empty-string default. DouBi keeps the dict form instead of
    ``SimpleNamespace`` because our ``mix_info`` arrives as plain JSON.

    Returns ``{}`` when the aweme carries no usable ``mix_id`` (a video
    that is not part of any 合集 — the overwhelmingly common case), so
    callers can branch on truthiness. Keys when present:

    * ``mix_id``   — always a ``str`` (platform sends it as either str
      or int; callers compare it against URL path segments, so it is
      coerced here and nowhere else)
    * ``mix_name`` — only when the platform supplied a non-blank one
    * ``mix_desc`` — only when non-blank

    Note the deliberate difference from TikTokDL: upstream returns
    ``""`` for the missing case and its caller (``Mix.__get_mix_id``,
    ``src/interface/mix.py:86-88``) then falls back to a *second*
    network round-trip via ``Detail``. Here the caller already holds an
    aweme dict and does not need that request.
    """
    if not isinstance(aweme, dict):
        return {}
    mix_info = aweme.get("mix_info")
    if not isinstance(mix_info, dict):
        return {}
    mix_id = mix_info.get("mix_id")
    if mix_id is None or mix_id == "":
        return {}
    ref: dict[str, str] = {"mix_id": str(mix_id)}
    name = str(mix_info.get("mix_name") or "").strip()
    if name:
        ref["mix_name"] = name
    desc = str(mix_info.get("mix_desc") or "").strip()
    if desc:
        ref["mix_desc"] = desc
    return ref


def format_mix_title(ref: dict[str, Any], fallback_mix_id: str = "") -> str:
    """Render the user-facing container title for a 合集.

    ``抖音合集《名字》`` when a name is known, else the M6.45 behaviour
    (``抖音合集 {mix_id}``) with the id. ``fallback_mix_id`` is ignored
    once a name is present.
    """
    name = str((ref or {}).get("mix_name") or "").strip()
    if name:
        return f"抖音合集《{name}》"
    mix_id = str((ref or {}).get("mix_id") or fallback_mix_id or "").strip()
    return f"抖音合集 {mix_id}" if mix_id else "抖音合集"


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
    # 图集判据与 yt-dlp 路径（``api.py``）共用同一实现：``url.py`` 的
    # ``is_image_album_payload``。两条路径若各写一套，同一条链接在
    # 「解析」与「采集」下会得到不同的 media_type（ROADMAP P0-1）。
    is_image = is_image_album_payload(aweme)

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
