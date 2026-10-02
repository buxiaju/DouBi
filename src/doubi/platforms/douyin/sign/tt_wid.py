"""Real ttWid fetcher for Douyin web API.

M6.48 - adapted from Johnserf-Shell/TikTokDownloader
``src/encrypt/ttWid.py`` (MIT). The TikTokDL implementation POSTs a
small JSON body to ``ttwid.bytedance.com/ttwid/union/register/`` and
extracts the ``ttwid`` cookie out of the ``Set-Cookie`` response header.

Why this matters
----------------
``ttwid`` is the platform tenant-id cookie. Without it, every request
that expects ``webid`` / ``ttwid`` headers returns ``403 Forbidden``.
DouBie never sent it before M6.48 because we relied on yt-dlp to keep
the ``webid`` cookie alive on its own session; now that we own the
HTTP layer (M2.x's webapi, M6.45's MIX expand, etc.) we have to mint
it ourselves.

Failure handling
----------------
Network failure / non-200 / empty Set-Cookie -> returns ``None``;
caller falls back to no-ttwid (HTTP requests proceed but lack the
expected cookie - slightly higher 403 risk; never crashes).
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx

logger = logging.getLogger("doubi.platforms.douyin.sign.tt_wid")

# bytedance ttwid public register endpoint. ``union/register/`` is
# documented in TikTokDL's ``TtWid.DATA`` payload (line 21).
_API = "https://ttwid.bytedance.com/ttwid/union/register/"

# TikTokDL ``TtWid.DATA`` (line 21-23) - the body never changes;
# aid=1768 is for Douyin / Xigua video. The ``service`` field points
# to ixigua.com because ttwid is shared across bytedance web products.
_PAYLOAD = (
    '''{"region":"cn","aid":1768,"needFid":false,"service":"www.ixigua.com",'''
    '''"migrate_info":{"ticket":"","source":"node"},'''
    '''"cbUrlProtocol":"https","union":true}'''
)


def _extract_set_cookie_tt_wid(headers: httpx.Headers) -> Optional[str]:
    """Pull ``ttwid=...`` out of a (possibly multi-value) Set-Cookie."""
    from http.cookies import SimpleCookie

    for raw in headers.get_list("set-cookie"):
        jar = SimpleCookie()
        try:
            jar.load(raw)
        except Exception:  # noqa: BLE001
            continue
        morsel = jar.get("ttwid")
        if morsel is not None and morsel.value:
            return morsel.value
    return None


class TtWidFetcher:
    """Async fetcher + cache for the platform ``ttwid`` cookie."""

    def __init__(self, *, timeout: float = 10.0) -> None:
        self.timeout = timeout
        self._cached: Optional[str] = None

    @property
    def cached(self) -> Optional[str]:
        return self._cached

    def invalidate(self) -> None:
        self._cached = None

    async def fetch(
        self,
        *,
        proxy: Optional[str] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> Optional[str]:
        """POST to ttwid.bytedance.com, extract ttwid from Set-Cookie.

        Returns the cookie value on success, ``None`` on any failure.
        """
        req_headers = dict(headers or {})
        req_headers.setdefault(
            "Content-Type", "application/json; charset=utf-8",
        )
        req_headers.setdefault("User-Agent", _DEFAULT_USER_AGENT)

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                proxy=proxy or None,
                follow_redirects=True,
            ) as client:
                resp = await client.post(
                    _API,
                    content=_PAYLOAD,
                    headers=req_headers,
                )
        except httpx.HTTPError as exc:
            logger.info("ttwid POST HTTP error: %s", exc)
            return None

        if resp.status_code != 200:
            logger.info(
                "ttwid POST returned HTTP %s", resp.status_code,
            )
            return None

        token = _extract_set_cookie_tt_wid(resp.headers)
        if token is None:
            logger.info(
                "ttwid POST 200 but no ttwid Set-Cookie: %s",
                resp.headers.get_list("set-cookie"),
            )
            return None

        self._cached = token
        logger.debug("ttwid fetched (%d chars)", len(token))
        return token


_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
)
