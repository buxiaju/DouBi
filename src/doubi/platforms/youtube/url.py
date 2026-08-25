"""YouTube URL pattern recognition.

yt-dlp 原生支持所有 YouTube URL 形态（普通视频 / Shorts / embed / youtu.be 短链），
所以这个文件**只**做一件事：把任意合法 YouTube URL 归一化成 ``watch?v=ID``
形态并提取 11 字符 video ID。adapter 把它转成 ``MediaItem.item_id``——
后续所有元数据由 yt-dlp 在下载阶段拉（adapter 在此阶段也会调一次
``extract_info(download=False)`` 拿标题，但失败时**不阻塞**）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class YouTubeURLType(str, Enum):
    VIDEO = "video"               # /watch?v=ID 或 youtu.be/ID
    SHORTS = "shorts"             # /shorts/ID
    EMBED = "embed"               # /embed/ID
    CHANNEL = "channel"           # /@handle, /channel/UC..., /c/Name
    PLAYLIST = "playlist"         # /playlist?list=PL...
    LIVE = "live"                 # /live/ID
    UNKNOWN = "unknown"


# ---- 匹配模式 ---------------------------------------------------------
# 顺序很重要——更具体的（带 path 的）排在更宽泛的（仅 host 的）之前。

_PATTERNS: list[tuple[YouTubeURLType, re.Pattern[str]]] = [
    # Shorts 必须先于 VIDEO——/shorts/ID 的 host 也匹配 VIDEO 的正则，
    # 但 shorts 是不同形态，分类要明确。
    (YouTubeURLType.SHORTS, re.compile(
        r"https?://(?:www\.)?youtube\.com/shorts/(?P<id>[A-Za-z0-9_\-]{11})"
    )),
    # /live/ID 同样独立形态。
    (YouTubeURLType.LIVE, re.compile(
        r"https?://(?:www\.)?youtube\.com/live/(?P<id>[A-Za-z0-9_\-]{11})"
    )),
    # /embed/ID —— 不显示在 UI 但粘贴进「嵌入代码」时会出现。
    (YouTubeURLType.EMBED, re.compile(
        r"https?://(?:www\.)?youtube\.com/embed/(?P<id>[A-Za-z0-9_\-]{11})"
    )),
    # 你管频道三种形态：/@handle 是新式，/channel/UC... 是最老式，/c/Name 是中间形态。
    (YouTubeURLType.CHANNEL, re.compile(
        r"https?://(?:www\.)?youtube\.com/(?:@[^/?&\s]+|channel/(?P<id>UC[A-Za-z0-9_\-]{22})|c/[^/?&\s]+)"
    )),
    # 播放列表：路径 /playlist 且 ?list=PL...；单独路径 /watch 也能带 list=。
    (YouTubeURLType.PLAYLIST, re.compile(
        r"https?://(?:www\.)?youtube\.com/playlist\?[^?\s]*list=(?P<id>[A-Za-z0-9_\-]+)"
    )),
    # 普通 watch?v=ID —— 兜底最宽，必须排在最后（任何 youtube.com URL 都会
    # 落到这里，但前面的模式会先抢走）。``v=`` 后面是 11 字符视频 ID，再
    # 之后必须是 ``&``（参数分隔）、``#``（fragment 起点）或字符串结束——
    # 不允许再多字符，否则 ``watch?v=IDextra`` 这种 URL 会被错认为合法。
    (YouTubeURLType.VIDEO, re.compile(
        r"https?://(?:www\.)?youtube\.com/watch\?[^?\s]*v=(?P<id>[A-Za-z0-9_\-]{11})(?:[&#]|$)"
    )),
    # youtu.be 短链 —— 注意 host 不同（youtu.be 而非 youtube.com）。
    # 短链后必须是 ``?``、``#`` 或字符串结束，不允许跟多余字符。
    (YouTubeURLType.VIDEO, re.compile(
        r"https?://youtu\.be/(?P<id>[A-Za-z0-9_\-]{11})(?:[?#]|$)"
    )),
]


@dataclass(frozen=True)
class ClassifiedURL:
    type: YouTubeURLType
    item_id: str
    raw: str


def _normalize_watch_url(video_id: str) -> str:
    """Canonical ``https://www.youtube.com/watch?v=ID`` — what yt-dlp prefers.

    短链、embed、shorts 都归一化到这里。Title 是从 ``watch?v=ID`` 取的，
    Shorts URL 取的 title 是「#Shorts » VIDEO_TITLE」之类，归一化后输出
    干净。
    """
    return f"https://www.youtube.com/watch?v={video_id}"


def classify_youtube_url(url: str) -> ClassifiedURL:
    """Classify a YouTube URL. Falls back to (UNKNOWN, "", url)."""
    if not url:
        return ClassifiedURL(YouTubeURLType.UNKNOWN, "", url)
    for url_type, pat in _PATTERNS:
        m = pat.search(url)
        if m:
            item_id = m.group("id") if "id" in m.groupdict() and m.group("id") else ""
            return ClassifiedURL(url_type, item_id, url)
    return ClassifiedURL(YouTubeURLType.UNKNOWN, "", url)


def to_watch_url(classified: ClassifiedURL) -> str:
    """Convert a ClassifiedURL into a canonical ``watch?v=ID`` form.

    Channel / playlist URLs aren't convertible — those aren't videos. The
    caller (``adapter.parse``) should branch on ``classified.type`` and
    refuse to feed a non-video URL to the engine.
    """
    if classified.type in (
        YouTubeURLType.CHANNEL, YouTubeURLType.PLAYLIST, YouTubeURLType.UNKNOWN,
    ):
        return classified.raw
    return _normalize_watch_url(classified.item_id)
