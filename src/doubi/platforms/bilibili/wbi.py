"""Bilibili WBI signing.

WBI is B 站's URL-signing mechanism for the *web* API surface
(``/x/space/wbi/*`` endpoints, mostly). It's an md5 of a permuted
key derived from two fixed images returned by the ``/nav`` endpoint.

This module is **not used by the M3 download flow** — yt-dlp already
signs B 站 URLs internally, and we hand off to yt-dlp for everything
that needs network. The module exists so the future M3.2 "rich B 站
metadata" path can call ``/x/space/wbi/acc/info`` etc. for things
yt-dlp doesn't expose (粉丝数 / 关注数 / UP 主认证信息).

The algorithm:

1. GET ``/x/web-interface/nav`` → response contains
   ``data.wbi_img.img_url`` and ``data.wbi_img.sub_url``.
2. The "key" is the filename (without extension) of each URL.
3. Concatenate: ``raw = img_key + sub_key`` (32 chars).
4. Apply the 64-entry mixin table: for each position ``i``,
   replace ``raw[i]`` with ``raw[table[i]]``.
5. URL-encode the original request params, append ``wts=<unix>``,
   append ``w_rid=md5(joined_query)``.

References:
    * https://socialsisteryi.github.io/bilibili-API-collect/docs/misc/sign/wbi.html
"""

from __future__ import annotations

import hashlib
import logging
import time as _time
from typing import Optional
from urllib.parse import urlencode

logger = logging.getLogger("doubi.platforms.bilibili.wbi")


# Public so tests can verify the table
MIXIN_TABLE: list[int] = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]


def _filename_from_url(url: str) -> str:
    """Extract the filename (without extension) from a B 站 wbi_img URL.

    >>> _filename_from_url("https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077c.png")
    '7cd084941338484aae1ad9425b84077c'
    """
    # URL like /bfs/wbi/{key}.png
    if not url:
        return ""
    last = url.rsplit("/", 1)[-1]
    if "." in last:
        last = last.rsplit(".", 1)[0]
    return last


def _get_mixin_key(img_key: str, sub_key: str) -> str:
    """Apply the mixin table to ``img_key + sub_key``."""
    raw = (img_key + sub_key)[:64]              # exactly 64 chars
    if len(raw) < 64:
        raw = raw + "0" * (64 - len(raw))      # defensive pad
    return "".join(raw[i] for i in MIXIN_TABLE)


def compute_w_rid(params: dict, wbi_keys: tuple[str, str]) -> str:
    """Compute ``w_rid`` for the given params + (img_key, sub_key) pair.

    ``params`` should be the request's query parameters. ``wts`` will be
    added/overwritten automatically.
    """
    img_key, sub_key = wbi_keys
    mixin_key = _get_mixin_key(img_key, sub_key)
    enriched = dict(params)
    enriched["wts"] = str(int(_time.time()))
    # Sort by key, url-encode, then append mixin_key, then md5
    sorted_query = urlencode(sorted(enriched.items()))
    return hashlib.md5((sorted_query + mixin_key).encode("utf-8")).hexdigest()


def sign_query(params: dict, wbi_keys: tuple[str, str]) -> dict:
    """Return a copy of ``params`` with ``wts`` and ``w_rid`` added.

    This is the function callers actually use::

        signed = sign_query({"mid": 12345, "token": "..."}, wbi_keys)
        url = f"https://api.bilibili.com/x/space/wbi/acc/info?{urlencode(signed)}"
    """
    out = dict(params)
    out["wts"] = str(int(_time.time()))
    out["w_rid"] = compute_w_rid(out, wbi_keys)
    return out


async def fetch_wbi_keys(
    *,
    cookies: Optional[list] = None,
    timeout: float = 10.0,
) -> Optional[tuple[str, str]]:
    """Fetch the (img_key, sub_key) pair from ``/x/web-interface/nav``.

    Returns ``None`` on failure (network error, missing wbi_img field).
    Pass in cookies from a logged-in session if your account's
    ``wbi_img`` differs from the anonymous default (rare).
    """
    import httpx

    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            cookies=cookies or [],
            headers={"User-Agent": "Mozilla/5.0"},
        ) as client:
            resp = await client.get("https://api.bilibili.com/x/web-interface/nav")
            resp.raise_for_status()
            data = resp.json()
        wbi = (data.get("data") or {}).get("wbi_img") or {}
        img_url = wbi.get("img_url") or ""
        sub_url = wbi.get("sub_url") or ""
        if not img_url or not sub_url:
            return None
        return _filename_from_url(img_url), _filename_from_url(sub_url)
    except Exception as exc:
        logger.warning("fetch_wbi_keys failed: %s", exc)
        return None
