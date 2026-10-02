"""Douyin URL signing (a-bogus / x-bogus / ms-token / tt-wid).

Ported verbatim from douyin-downloader-main (MIT) which itself vendors
the algorithms from Douyin_TikTok_Download_API (Apache-2.0, Evil0ctal).
License headers are preserved in the individual modules.

Douyin's web API (``/aweme/v1/web/...``) rejects unsigned requests;
every query must carry an ``a_bogus`` parameter computed from the query
string, the User-Agent and a synthetic browser fingerprint. M6.48 adds
``msToken`` (real fetch from bytedance mssdk) + ``ttwid`` (real fetch
from bytedance ttwid) + ``x-secsdk-web-signature`` (MD5 over canonical
query) — the second-layer protection on top of ``a_bogus``.
"""

from .abogus import ABogus, BrowserFingerprintGenerator
from .ms_token import MsTokenFetcher
from .tt_wid import TtWidFetcher
from .websign import (
    DOUYIN_SIGNED_PATHS,
    SALT,
    SIGNATURE_PARAM,
    TIMESTAMP_PARAM,
    UIFID_PARAM,
    is_sign_protected,
    normalize_query,
    sign as websign_sign,
)
from .xbogus import XBogus

__all__ = [
    "ABogus",
    "BrowserFingerprintGenerator",
    "DOUYIN_SIGNED_PATHS",
    "MsTokenFetcher",
    "SALT",
    "SIGNATURE_PARAM",
    "TIMESTAMP_PARAM",
    "TtWidFetcher",
    "UIFID_PARAM",
    "XBogus",
    "is_sign_protected",
    "normalize_query",
    "websign_sign",
]
