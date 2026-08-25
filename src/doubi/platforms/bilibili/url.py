"""Bilibili URL pattern recognition.

Classifies Bilibili URLs into the kinds we handle. Patterns are kept
simple and ordered from most specific to least — a /bangumi/play/ss*
URL also matches the generic /play/* wildcard, so we put bangumi /
cheese first. Unknown URLs still classify as (UNKNOWN, "", url) so
callers can branch on ``type`` without re-parsing the URL string.

裸编号（``BV1GJ411x7h7`` / ``av170001`` / ``ep374668`` / ``ss34244`` /
``ml12345``）也被接受：用户在 B 站页面地址栏、分享文案、评论里复制的
常常只是编号本身。``classify_bilibili_url`` 把它们归一化成完整 URL，
``ClassifiedURL.raw`` 保留用户原始输入，``normalized_url`` 给 adapter
拿来 fetch。编号归一化是单点职责：只有此模块知道编号→URL 的映射，
adapter / pipeline / GUI 都不用关心。
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
    LIVE = "live"                 # live.bilibili.com/{room_id}
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
    # 直播：live.bilibili.com/{room_id}，可能带 h5/blanc 前缀或查询参数。
    # 房间号是纯数字，放在 SPACE（也是纯数字）之前以免被 /数字/ 吞掉。
    (BilibiliURLType.LIVE,       re.compile(r"https?://live\.bilibili\.com/(?:h5/|blanc/)?(?P<id>\d+)")),
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


# ---------------------------------------------------------------------------
# 裸编号归一化
# ---------------------------------------------------------------------------
#
# 用户从 B 站页面地址栏、分享文案、评论里复制的常常只是编号本身：
# ``BV1GJ411x7h7``、``av170001``、``ep374668``、``ss34244``、``ml12345``。
# 这些不是 URL，但 adapter 的 fetch / 策略全按完整 URL 工作。归一化在
# classify 这一层做掉，下游就能继续走老路径。
#
# 每条 (type, pattern, builder)：pattern 带命名组 ``id``，builder 把 id
# 拼回完整 URL。顺序从最长的前缀（``BV``）到最短（``av``）。
_BARE_ID_PATTERNS: list[tuple[BilibiliURLType, re.Pattern[str], re.Pattern[str] | None, str]] = [
    # BV 编号：BV + 10 chars。严格匹配（锚定首尾），避免把 URL 里的 BV 片段误判。
    (BilibiliURLType.VIDEO,   re.compile(rf"^(?P<id>{_BV_RE})$"), None,
     "https://www.bilibili.com/video/{id}"),
    # av 编号：av + 数字。前缀小写，和 B 站 URL 里的 ``/av...`` 一致。
    (BilibiliURLType.VIDEO,   re.compile(r"^(?P<id>av\d+)$"), None,
     "https://www.bilibili.com/video/{id}"),
    # ep 编号：番剧单集。``ep374668`` → /bangumi/play/ep374668
    (BilibiliURLType.BANGUMI, re.compile(r"^(?P<id>ep\d+)$"), None,
     "https://www.bilibili.com/bangumi/play/{id}"),
    # ss 编号：番剧季度。``ss34244`` → /bangumi/play/ss34244
    (BilibiliURLType.BANGUMI, re.compile(r"^(?P<id>ss\d+)$"), None,
     "https://www.bilibili.com/bangumi/play/{id}"),
    # ml 编号：合集（收藏夹）。``ml12345`` → /list/ml12345
    (BilibiliURLType.LIST,    re.compile(r"^(?P<id>ml\d+)$"), None,
     "https://www.bilibili.com/list/{id}"),
]


@dataclass(frozen=True)
class ClassifiedURL:
    type: BilibiliURLType
    item_id: str
    raw: str
    #: 归一化后的完整 URL。完整 URL 输入时与 ``raw`` 相同；
    #: 裸编号输入时是拼接出的 canonical URL，adapter 拿来 fetch。
    normalized_url: str = ""


def classify_bilibili_url(url: str) -> ClassifiedURL:
    """Classify a Bilibili URL or bare ID. Falls back to (UNKNOWN, "", url).

    接受完整 URL（``https://www.bilibili.com/video/BV...``）和裸编号
    （``BV1GJ411x7h7`` / ``av170001`` / ``ep374668`` / ``ss34244`` /
    ``ml12345``）。裸编号会被归一化成完整 URL，``normalized_url``
    字段供 adapter 用来 fetch。
    """
    if not url:
        return ClassifiedURL(BilibiliURLType.UNKNOWN, "", url)
    for url_type, pat in _PATTERNS:
        m = pat.search(url)
        if m:
            return ClassifiedURL(url_type, m.group("id"), url, normalized_url=url)
    # 裸编号归一化：strip 后整体匹配，避免在完整 URL 里误中片段。
    stripped = url.strip()
    for url_type, pat, _guard, builder in _BARE_ID_PATTERNS:
        m = pat.match(stripped)
        if m:
            item_id = m.group("id")
            normalized = builder.format(id=item_id)
            return ClassifiedURL(url_type, item_id, url, normalized_url=normalized)
    return ClassifiedURL(BilibiliURLType.UNKNOWN, "", url)
