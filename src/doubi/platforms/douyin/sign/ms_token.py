"""Real msToken fetcher for Douyin web API.

M6.48 — adapted from Johnserf-Shell/TikTokDownloader ``src/encrypt/msToken.py``
(MIT). The TikTokDL implementation POSTs a fixed ``strData`` blob to the
bytedance mssdk service and parses the ``msToken`` cookie out of the
``Set-Cookie`` response header.

M6.53 — Survey §8.1 item #6 落地：把 TikTokDL 的完整 strData blob + TOKEN
装入 ``_MSSDK_STRDATA`` + ``_MSSDK_DEFAULT_TOKEN`` 作为模块级常量。M6.48
框架做对了但 ``strData=""`` 占位符，生产里发空 blob → mssdk 服务器要么
拒绝要么返回无效 token。这次把 blob 真实填上，配合 a_bogus + WebSign
形成完整 403 风控防御。blob 长度 ~3.5 KB base64，从
``runtime_bundler_34.js`` 逆向提取，TikTokDL 项目本身已 MIT 许可，
抖音二次开发（GPL-3.0）兼容。

Why this matters
----------------
Before M6.43 DouBie generated ``msToken`` with a 182-char random
``_false_ms_token()`` because we had no idea what shape the platform
expected. 抖音's mssdk bytedance.com is a **public** endpoint and accepts the
fixed ``strData`` blob TikTokDL extracted via reverse engineering. The
returned ``msToken`` cookie has a long enough validity window (~2 weeks
per TikTokDL's release notes) that a single fetch + reuse is fine
saving the bundle.

Failure handling (no obfuscation here)
---------------------------------------------------
* Network failure / non-200 -> returns ``None``; caller falls back to a
  per-call random fake (``_false_ms_token``). The 403 rate will be
  higher than with a real token, but it never crashes the expansion.
* mssdk returns empty Set-Cookie -> returns ``None``; same fallback.
* The cached token is reused for the lifetime of the
  ``MsTokenFetcher`` instance - M6.48 keeps it module-level so a single
  fetch serves the whole GUI session.

Versioning / rotation risk
--------------------------
抖音若升级 ``runtime_bundler_*.js``，strData blob 会过期——这时：
1. mssdk 返回 200 但 Set-Cookie 缺 ``msToken``（或 token 不被接受）
2. ``MsTokenFetcher`` 走 ``return None`` 路径
3. caller fallback 到 fake msToken → 403 概率回升
4. 重新逆向新 JS bundle 抓 blob 替换 ``_MSSDK_STRDATA`` 即可
测试 ``test_mstoken_default_strdata_is_populated`` 用 hash pin 锁住
blob 字节不变，被意外改动即红。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Optional

import httpx

logger = logging.getLogger("doubi.platforms.douyin.sign.ms_token")

# bytedance mssdk public endpoint - accepts the fixed ``strData`` blob
# (extracted by TikTokDL from ``runtime_bundler_34.js``). The blob is
# valid across all modern 抖音 web builds; rotating it requires reverse-
# engineering the new JS.
_MSSDK_API = "https://mssdk.bytedance.com/web/common"

# TikTokDL ``MsToken.DATA`` (line 26-74) - magic / version / dataType
# are constant; ``strData`` is the encrypted device-fingerprint blob
# extracted from ``runtime_bundler_34.js``.
#
# M6.53 落地：把完整 base64 blob 装入 ``_MSSDK_STRDATA``。之前 M6.48 用
# ``strData=""`` 占位，mssdk 服务器要么拒绝要么返回无效 token。blob
# ~3.5 KB，TikTokDL 项目自身 MIT 许可。
_MSSDK_STRDATA: str = (
    "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"
)

# ``MsToken.TOKEN`` (TikTokDL line 75-78) — pre-existing cookie token
# that mssdk can refresh. DouBi 装入这个常量，让 mssdk 在「refresh」
# 模式下回应而不是「first-time」模式（TikTokDL line 119-120 行为差异）。
_MSSDK_DEFAULT_TOKEN: str = (
    "9cguMjz4GIfQV50B_D49quM-cEyIvWMwWi0gj1bf"
    "-4YprIjt29ZrAxmDb5oIhmzEhwvcmcC4BR_kEZGmXdS1q7Ad3V94izdpXwtxgPPpozVUzQVm7KDrc5H9nfN3pLw="
)

# ``MsToken.DATA`` (TikTokDL line 26-74) — magic / version / dataType
# are constant; ``strData`` is filled from ``_MSSDK_STRDATA`` (M6.53);
# ``tspFromClient`` is set per-request; ``ulr`` stays 0.
_MSSDK_PAYLOAD_BASE: dict[str, object] = {
    "magic": 538969122,
    "version": 1,
    "dataType": 8,
    "strData": "",  # placeholder; fetch() rewrites from _MSSDK_STRDATA
    "tspFromClient": 0,
    "ulr": 0,
}


def _extract_set_cookie_ms_token(headers: httpx.Headers) -> Optional[str]:
    """Pull ``msToken=...`` out of a (possibly multi-value) Set-Cookie header.

    httpx gives us ``headers.get_list("set-cookie")`` - each item is the
    raw ``name=value; ...`` line. We use ``http.cookies.SimpleCookie``
    to do the actual parsing (handles quoted values, expired flags,
    path/domain attrs etc.).
    """
    from http.cookies import SimpleCookie

    for raw in headers.get_list("set-cookie"):
        jar = SimpleCookie()
        try:
            jar.load(raw)
        except Exception:  # noqa: BLE001 - malformed cookie line; skip
            continue
        morsel = jar.get("msToken")
        if morsel is not None and morsel.value:
            return morsel.value
    return None


class MsTokenFetcher:
    """Async fetcher + cache for the platform ``msToken`` cookie.

    Usage::

        fetcher = MsTokenFetcher(timeout=10.0)
        token = await fetcher.fetch(proxy=None)
        # token is None on failure -> caller falls back to a per-call fake.

    A single fetch is intended to cover the whole GUI session (token
    validity is documented as ~2 weeks in TikTokDL's release notes;
    the platform may rotate msToken sooner if the user clears cookies).
    The class does not auto-refresh - call ``await fetcher.fetch(...)``
    again to force a refresh.
    """

    def __init__(self, *, timeout: float = 10.0,
                str_data: Optional[str] = None,
                default_token: Optional[str] = None) -> None:
        self.timeout = timeout
        # M6.53: ``None`` means "use the module-level real blob" (TikTokDL
        # extract). Tests can still inject sentinel values by passing
        # an explicit string (or ``""`` to force empty strData).
        self._str_data_override = (
            str_data if str_data is not None else _MSSDK_STRDATA
        )
        self._token_override = (
            default_token if default_token is not None else _MSSDK_DEFAULT_TOKEN
        )
        self._cached: Optional[str] = None

    @property
    def cached(self) -> Optional[str]:
        """Return the cached token (``None`` if no successful fetch yet)."""
        return self._cached

    def invalidate(self) -> None:
        """Drop the cached value (e.g. on cookie refresh)."""
        self._cached = None

    async def fetch(
        self,
        *,
        proxy: Optional[str] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> Optional[str]:
        """POST to mssdk, extract msToken from Set-Cookie.

        Returns the token string on success, ``None`` on any failure
        (network / non-200 / empty Set-Cookie). Side effect: caches the
        token for subsequent ``cached`` reads.
        """
        payload = dict(_MSSDK_PAYLOAD_BASE)
        payload["tspFromClient"] = int(time.time() * 1000)
        if self._str_data_override:
            payload["strData"] = self._str_data_override

        req_headers = dict(headers or {})
        req_headers.setdefault(
            "Content-Type", "application/json; charset=utf-8",
        )
        req_headers.setdefault("User-Agent", _DEFAULT_USER_AGENT)
        # M6.53 — also send the pre-existing ``msToken`` cookie if any,
        # so mssdk treats the request as a "refresh" rather than
        # "first-time" (TikTokDL ``MsToken.get_real_ms_token:118-120``
        # sends ``headers |= {"Cookie": f"{NAME}={token}"}``). mssdk
        # responds with a refreshed Set-Cookie; without TOKEN the
        # server returns a shorter-lived first-issue token.
        if self._token_override and "Cookie" not in req_headers:
            req_headers["Cookie"] = f"msToken={self._token_override}"

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                proxy=proxy or None,
                follow_redirects=True,
            ) as client:
                resp = await client.post(
                    _MSSDK_API,
                    content=json.dumps(payload, separators=(",", ":")),
                    headers=req_headers,
                )
        except httpx.HTTPError as exc:
            logger.info("mssdk POST HTTP error: %s", exc)
            return None

        if resp.status_code != 200:
            logger.info(
                "mssdk POST returned HTTP %s (token refresh skipped)",
                resp.status_code,
            )
            return None

        token = _extract_set_cookie_ms_token(resp.headers)
        if token is None:
            logger.info(
                "mssdk POST 200 but no msToken Set-Cookie: %s",
                resp.headers.get_list("set-cookie"),
            )
            return None

        self._cached = token
        logger.debug("msToken fetched (%d chars)", len(token))
        return token


# Conservative UA matching the platform web (Chrome 139 + Windows 10).
# TikTokDL captured this from the mssdk POST headers in late 2025;
# DouBie already uses the same UA in ``engines/yt_dlp.py`` / ``webapi.py``.
_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
)
