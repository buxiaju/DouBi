"""Douyin URL signing (a-bogus / x-bogus).

Ported verbatim from douyin-downloader-main (MIT) which itself vendors
the algorithms from Douyin_TikTok_Download_API (Apache-2.0, Evil0ctal).
License headers are preserved in the individual modules.

Douyin's web API (``/aweme/v1/web/...``) rejects unsigned requests;
every query must carry an ``a_bogus`` parameter computed from the query
string, the User-Agent and a synthetic browser fingerprint.
"""

from .abogus import ABogus, BrowserFingerprintGenerator
from .xbogus import XBogus

__all__ = ["ABogus", "BrowserFingerprintGenerator", "XBogus"]
