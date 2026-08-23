"""Douyin URL pattern recognition.

This is the *only* URL logic the Douyin adapter needs in M1 — the
heavy lifting (watermark removal, format selection, signature
generation) is now done by yt-dlp. We keep a clean classification
function so platform-specific code (the M2 metadata API client, the
cookie fetcher, the GUI filter) can branch on the URL type without
re-parsing the URL itself.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class DouyinURLType(str, Enum):
    VIDEO = "video"               # /video/{aweme_id}
    NOTE = "note"                 # /note/{note_id}  (image post)
    GALLERY = "gallery"           # /gallery/{note_id}
    COLLECTION = "collection"     # /collection/{mix_id}
    MIX = "mix"                   # /mix/{mix_id}
    MUSIC = "music"               # /music/{music_id}
    USER = "user"                 # /user/{sec_uid}
    LIVE = "live"                 # live.douyin.com/{room_id}
    SHORT = "short"               # v.douyin.com/...
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Patterns — kept simple and tested independently of adapter logic
# ---------------------------------------------------------------------------

_PATTERNS: list[tuple[DouyinURLType, re.Pattern[str]]] = [
    (DouyinURLType.VIDEO,     re.compile(r"https?://(?:www\.)?douyin\.com/video/(?P<id>\d+)")),
    (DouyinURLType.NOTE,      re.compile(r"https?://(?:www\.)?douyin\.com/note/(?P<id>\d+)")),
    (DouyinURLType.GALLERY,   re.compile(r"https?://(?:www\.)?douyin\.com/gallery/(?P<id>\d+)")),
    (DouyinURLType.COLLECTION,re.compile(r"https?://(?:www\.)?douyin\.com/collection/(?P<id>\d+)")),
    (DouyinURLType.MIX,       re.compile(r"https?://(?:www\.)?douyin\.com/mix/(?P<id>\d+)")),
    # 合集分享链接（APP「分享合集」产生）：
    #   https://www.iesdouyin.com/share/mix/detail/{mix_id}/?...
    (DouyinURLType.COLLECTION,re.compile(r"https?://(?:www\.)?iesdouyin\.com/share/mix/detail/(?P<id>\d+)")),
    (DouyinURLType.MUSIC,     re.compile(r"https?://(?:www\.)?douyin\.com/music/(?P<id>\d+)")),
    (DouyinURLType.LIVE,      re.compile(r"https?://live\.douyin\.com/(?P<id>\d+)")),
    (DouyinURLType.SHORT,     re.compile(r"https?://v\.douyin\.com/(?P<id>[\w\-]+)")),
    # Feed pages that open a video in a modal, e.g.
    #   /jingxuan?modal_id=7676517073484352822
    #   /discover?foo=1&modal_id=...
    # The modal_id *is* the aweme_id, so these classify as VIDEO.
    # This MUST be checked before USER: a user-profile URL that carries
    # modal_id (video opened from the profile's 合集/compilation tab,
    # e.g. /user/{sec_uid}?...&modal_id=...&vid=...) points at ONE
    # video, not at the user's post list — matching USER first would
    # trigger whole-profile container expansion instead.
    (DouyinURLType.VIDEO,     re.compile(r"https?://(?:www\.)?douyin\.com/[^?\s]*[?&][^\s]*?modal_id=(?P<id>\d+)")),
    # Compilation-tab share variants sometimes carry only ``vid=``
    # (same value as modal_id / aweme_id).
    (DouyinURLType.VIDEO,     re.compile(r"https?://(?:www\.)?douyin\.com/[^?\s]*[?&][^\s]*?\bvid=(?P<id>\d+)")),
    (DouyinURLType.USER,      re.compile(r"https?://(?:www\.)?douyin\.com/user/(?P<id>[\w\-]+)")),
]


@dataclass(frozen=True)
class ClassifiedURL:
    type: DouyinURLType
    item_id: str
    raw: str


def classify_douyin_url(url: str) -> ClassifiedURL:
    """Classify a Douyin URL. Falls back to (UNKNOWN, "", url)."""
    if not url:
        return ClassifiedURL(DouyinURLType.UNKNOWN, "", url)
    for url_type, pat in _PATTERNS:
        m = pat.search(url)
        if m:
            return ClassifiedURL(url_type, m.group("id"), url)
    return ClassifiedURL(DouyinURLType.UNKNOWN, "", url)
