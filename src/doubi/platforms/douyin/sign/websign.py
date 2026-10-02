"""WebSign (x-secsdk-web-signature) signing for Douyin web API.

M6.48 - adapted from Johnserf-Shell/TikTokDownloader
``src/encrypt/websign.py`` (MIT, originating from Evil0ctal /
Douyin_TikTok_Download_API, Apache-2.0). DouBie only reuses the pure-
Python ``md5 + canonical-query-encoding`` algorithm and the salt value;
the JS reverse-engineering work stays attributed to the original
projects via the header preserved in this file.

Why this matters
----------------
The platform ``webSignUrl`` is the *second* protection layer on top
of ``a_bogus``: every protected interface (see
:data:`DOUYIN_SIGNED_PATHS`) must additionally carry
``timestamp`` + ``x-secsdk-web-signature`` query parameters. The
platform returns ``403 Uifid Not Found`` if the signature is missing
or the bound ``uifid`` is empty.

Algorithm (TikTokDL comments verbatim, paraphrased)::

    stamp = str(int(time()))
    pairs = decode(query)              # split on '&', unquote name + value
    if no uifid in pairs: append (uifid, uifid)
    pairs.append((timestamp, stamp))
    hashed = encode(pairs)             # canonical percent-encoding
    signature = md5(f"{uifid}_{stamp}_{SALT}_{hashed}").hexdigest()
    return f"{hashed}&x-secsdk-web-signature={signature}"

Failure modes - none: pure-Python ``md5``, no I/O. The signature is
deterministic for a given ``(query, uifid, timestamp)`` tuple; tests
pin known-output vectors to detect any drift in the canonical encoding.
"""

from __future__ import annotations

from hashlib import md5
from time import time
from typing import Optional
from urllib.parse import quote, unquote

# TikTokDL ``websign.py`` line 31 - salt extracted from
# ``runtime_bundler_34.js``'s ``webSignUrl``. May rotate if the
# platform pushes a new secsdk bundle; tests pin this constant.
SALT = "A96D855A08C0A9707F8BEF0D9A527E4E"

# Query parameter names. ``UIFID_PARAM`` must match what the platform
# secdk-strategy binds the signature against (line 33-35).
SIGNATURE_PARAM = "x-secsdk-web-signature"
UIFID_PARAM = "uifid"
TIMESTAMP_PARAM = "timestamp"


# ---------------------------------------------------------------
# Platform protected paths list (DOUYIN_SIGNED_PATHS)
# ---------------------------------------------------------------
#
# TikTokDL ``douyin_params.py`` lines 31-65: the platform
# runtime_bundler config declares these exact paths as requiring
# ``x-secsdk-web-signature``. POST endpoints are a subset of GET
# endpoints, so we apply the rule based on path only (over-signing is
# harmless - TikTokDL's own note).
#
# Empirical evidence from TikTokDL's release notes (2026-09-08): with
# the protected whitelist, their 8-shot regression went from 3/8 success
# (with a_bogus alone) to 8/8 success (with a_bogus + WebSign).
#
# DouBi's webapi uses three of these paths:
#   - /aweme/v1/web/aweme/detail/   (single parse)
#   - /aweme/v1/web/mix/aweme/      (MIX expand)
#   - /aweme/v1/web/aweme/post/     (USER expand via PostStrategy)
# /aweme/v1/web/mix/listcollection/ and /aweme/v1/web/collects/list/
# are reserved for M6.50 (Collects family).
#
DOUYIN_SIGNED_PATHS: frozenset[str] = frozenset(
    {
        "/aweme/v1/web/aweme/detail/",
        "/aweme/v1/web/aweme/post/",
        "/aweme/v1/web/aweme/favorite/",
        "/aweme/v1/web/aweme/listcollection/",
        "/aweme/v1/web/mix/aweme/",
        "/aweme/v1/web/tab/feed/",
        "/aweme/v1/web/mix/list/",
        "/aweme/v1/web/music/aweme/",
        "/aweme/v1/web/music/list/",
        "/aweme/v1/web/mix/detail/",
        "/aweme/v1/web/mix/listcollection/",
        "/aweme/v1/web/music/detail/",
        "/aweme/v1/web/collects/list/",
        "/aweme/v1/web/collects/video/list/",
        # M6.49 — search endpoints. TikTokDL's empirical list (2026-09-08)
        # only covered detail/post; search endpoints may or may not
        # require WebSign depending on when the platform added them to
        # the secsdk protectedHost table. Over-signing is harmless
        # (TikTokDL note), so we include all four to be defensive.
        "/aweme/v1/web/general/search/single/",
        "/aweme/v1/web/search/item/",
        "/aweme/v1/web/discover/search/",
        "/aweme/v1/web/live/search/",
        # M6.50 — hot 榜 endpoint. TikTokDL's ``src/interface/hot.py``
        # doesn't add WebSign explicitly (the framework's run_single
        # pipeline auto-attaches it when the path matches the whitelist),
        # so this *probably* needs the signature. We follow the same
        # defensive over-sign pattern used for the search endpoints.
        "/aweme/v1/web/hot/search/list/",
        # M6.51 — 收藏夹短剧 endpoint. TikTokDL ``src/interface/collects.py``
        # ``CollectsSeries:215`` uses the same protected-list lookup as
        # ``/aweme/v1/web/mix/listcollection/`` (already whitelisted at
        # line 86), so /aweme/v1/web/series/collections/ almost certainly
        # needs the signature too. Over-signing is harmless.
        "/aweme/v1/web/series/collections/",
        # M6.51 — 收藏夹音乐 endpoint. TikTokDL ``src/interface/collects.py``
        # ``CollectsMusic:269`` uses ``/aweme/v1/web/music/listcollection/``;
        # M6.48 whitelisted ``music/aweme/`` + ``music/list/`` +
        # ``music/detail/`` but missed this one. Adding now.
        "/aweme/v1/web/music/listcollection/",
        # M6.52 — 评论 + 回复 endpoints. TikTokDL ``src/interface/comment.py``
        # ``Comment:34`` uses ``/aweme/v1/web/comment/list/`` and
        # ``Reply:230`` uses ``/aweme/v1/web/comment/list/reply/``. Both
        # endpoints are accessed via ``web/user`` referer; the secsdk
        # protectedHost table may have added them since TikTokDL's 2026-09
        # snapshot. Over-signing is harmless — we include both.
        "/aweme/v1/web/comment/list/",
        "/aweme/v1/web/comment/list/reply/",
        # M6.54 — 关注列表 + 粉丝列表. TikTokDL 无源（``User`` 接口只
        # 拿个人资料），DouBi 原生实现跟随 M6.51 ``_cursor_paginate`` 模式。
        # 端点是公开 Douyin web API，路径在 secsdk protectedHost 表里
        # 可能新增 WebSign 要求。Over-signing 无害。
        "/aweme/v1/web/user/following/list/",
        "/aweme/v1/web/user/follower/list/",
        # M6.57 — 话题/挑战（HashTag）作品列表. **TikTokDL 无源**：
        # ``src/interface/hashtag.py`` 的 ``run()`` 正文只有 ``pass``，
        # 连 ``self.api`` 都没声明，无任何端点可抄。此处端点为 DouBi
        # 原生确定（抖音 web 话题页 ``/challenge/detail/{cid}`` 的作品
        # 流）。与 M6.51/M6.54 同一判断：发布在抖音 web API 下、走
        # 同一套 secsdk protectedHost 逻辑，over-signing 无害。
        "/aweme/v1/web/challenge/aweme/",
    }
)


def is_sign_protected(url: str) -> bool:
    """Return ``True`` if ``url`` matches a path in :data:`DOUYIN_SIGNED_PATHS`.

    The match is on the URL path component (no query / fragment),
    normalized to ``/foo/bar/`` form (leading + trailing ``/``).
    """
    from urllib.parse import urlsplit

    path = urlsplit(url).path or "/"
    if not path.startswith("/"):
        path = "/" + path
    if not path.endswith("/"):
        path += "/"
    return path in DOUYIN_SIGNED_PATHS


# ---------------------------------------------------------------
# Canonical query byte sequence (TikTokDL ``_encode_pairs`` / line 50-56)
# ---------------------------------------------------------------


def _query_pairs(query: str) -> list[tuple[str, str]]:
    """Split ``query`` on ``&`` and decode percent escapes (``+`` stays)."""
    pairs: list[tuple[str, str]] = []
    for part in query.split("&"):
        if not part:
            continue
        name, _, value = part.partition("=")
        pairs.append((unquote(name), unquote(value)))
    return pairs


def _encode_pairs(pairs: list[tuple[str, str]]) -> str:
    """Serialize pairs with WebSign's percent-encoding rule (preserves ``*/._``)."""
    return "&".join(
        f"{quote(name, safe='*-._')}={quote(value, safe='*-._')}"
        for name, value in pairs
    )


def normalize_query(query: str) -> str:
    """Return the canonical query byte sequence emitted by WebSign."""
    return _encode_pairs(_query_pairs(query))


def sign(
    query: str,
    uifid: str,
    *,
    timestamp: Optional[int] = None,
) -> tuple[str, str]:
    """Compute ``x-secsdk-web-signature`` and return ``(signed_query, signature)``.

    Args:
        query: full query string, must already include ``uifid``. The
            signature is computed over this byte sequence plus the
            appended ``timestamp`` - so ``signed_query`` is what
            actually goes on the wire.
        uifid: visitor ID the signature is bound to.
        timestamp: seconds since epoch; defaults to current time. Tests
            pin a fixed value.

    Returns:
        ``(signed_query, signature)``. ``signed_query`` ends with
        ``&x-secsdk-web-signature={signature}`` and is ready to send.
    """
    if not uifid:
        raise ValueError(
            "uifid must be a non-empty string - empty uifid would produce a "
            "signature that the platform rejects as 'Uifid Not Found'.",
        )
    stamp = str(int(timestamp if timestamp is not None else time()))
    pairs = _query_pairs(query)
    if not any(name == UIFID_PARAM for name, _ in pairs):
        pairs.append((UIFID_PARAM, uifid))
    pairs.append((TIMESTAMP_PARAM, stamp))
    hashed = _encode_pairs(pairs)
    signature = md5(f"{uifid}_{stamp}_{SALT}_{hashed}".encode()).hexdigest()
    return f"{hashed}&{SIGNATURE_PARAM}={signature}", signature
