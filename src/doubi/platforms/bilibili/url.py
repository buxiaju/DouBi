"""Bilibili URL pattern recognition.

Classifies Bilibili URLs into the kinds we handle. Patterns are kept
simple and ordered from most specific to least — a /bangumi/play/ss*
URL also matches the generic /play/* wildcard, so we put bangumi /
cheese first. Unknown URLs still classify as (UNKNOWN, "", url) so
callers can branch on ``type`` without re-parsing the URL string.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class BilibiliURLType(str, Enum):
    VIDEO = "video"               # /video/BV...  or /video/av...
    BANGUMI = "bangumi"           # /bangumi/play/ss... or ep...
    COURSE = "course"             # /cheese/play/ss...
    SPACE = "space"               # /space.bilibili.com/{uid} or /{uid}
    FAVLIST = "favlist"           # /favlist?fid=...
    WATCH_LATER = "watch_later"   # /watchlater
    HISTORY = "history"           # /history
    POPULAR = "popular"           # /v/popular
    LIST = "list"                 # /list/ml...  (合集)
    SHORT = "short"               # b23.tv/...
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# BV id is exactly 12 chars: BV + 1 (always '1') + 9 chars (the BTable alphabet
# excludes a few chars: I, O, l — easy to confuse with 1, 0, i).
_BV_RE = r"BV1[1-9A-HJ-NP-Za-km-z]{9}"
_AV_RE = r"av\d+"

_PATTERNS: list[tuple[BilibiliURLType, re.Pattern[str]]] = [
    # Most specific first
    (BilibiliURLType.BANGUMI,    re.compile(r"https?://(?:www\.)?bilibili\.com/bangumi/play/(?P<id>ss\d+|ep\d+)")),
    (BilibiliURLType.COURSE,     re.compile(r"https?://(?:www\.)?bilibili\.com/cheese/play/(?P<id>ss\d+)")),
    (BilibiliURLType.LIST,       re.compile(r"https?://(?:www\.)?bilibili\.com/list/(?P<id>ml\d+)")),
    (BilibiliURLType.SPACE,      re.compile(r"https?://space\.bilibili\.com/(?P<id>\d+)")),
    (BilibiliURLType.SPACE,      re.compile(r"https?://(?:www\.)?bilibili\.com/(?P<id>\d+)/?$")),
    (BilibiliURLType.FAVLIST,    re.compile(r"https?://(?:www\.)?bilibili\.com/favlist\?.*fid=(?P<id>\d+)")),
    (BilibiliURLType.WATCH_LATER,re.compile(r"https?://(?:www\.)?bilibili\.com/watchlater(?P<id>.*)")),
    (BilibiliURLType.HISTORY,    re.compile(r"https?://(?:www\.)?bilibili\.com/history(?P<id>.*)")),
    (BilibiliURLType.POPULAR,    re.compile(r"https?://(?:www\.)?bilibili\.com/v/popular(?P<id>.*)")),
    (BilibiliURLType.VIDEO,      re.compile(rf"https?://(?:www\.)?bilibili\.com/video/(?P<id>{_BV_RE}|{_AV_RE})")),
    (BilibiliURLType.VIDEO,      re.compile(rf"https?://(?:www\.)?bilibili\.com/(?P<id>{_BV_RE})/?(?:[?#].*)?$")),
    (BilibiliURLType.SHORT,      re.compile(r"https?://b23\.tv/(?P<id>[\w\-]+)")),
]


@dataclass(frozen=True)
class ClassifiedURL:
    type: BilibiliURLType
    item_id: str
    raw: str


def classify_bilibili_url(url: str) -> ClassifiedURL:
    """Classify a Bilibili URL. Falls back to (UNKNOWN, "", url)."""
    if not url:
        return ClassifiedURL(BilibiliURLType.UNKNOWN, "", url)
    for url_type, pat in _PATTERNS:
        m = pat.search(url)
        if m:
            return ClassifiedURL(url_type, m.group("id"), url)
    return ClassifiedURL(BilibiliURLType.UNKNOWN, "", url)
