"""Douyin URL pattern recognition.

This is the *only* URL logic the Douyin adapter needs in M1 — the
heavy lifting (watermark removal, format selection, signature
generation) is now done by yt-dlp. We keep a clean classification
function so platform-specific code (the M2 metadata API client, the
cookie fetcher, the GUI filter) can branch on the URL type without
re-parsing the URL itself.

合集（collection/mix）URL 支持两种形态：

* ``/collection/{mix_id}`` — 整个合集页（MIX 容器，pipeline 触发 expand）
* ``/collection/{mix_id}/{seq}`` — 合集里第 ``seq`` 个视频（单条 VIDEO）

后者是用户在 抖音 web  选中某条视频时复制出来的链接——``seq`` 后缀让
adapter 知道"我想要这个，不是整个合集"。``classify`` 把 ``seq`` 写进
``ClassifiedURL.seq``，``adapter.parse`` 据此切换行为。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional


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
# 图集（图文）判定 —— 单一真源
# ---------------------------------------------------------------------------
#
# 抖音有两条互不相通的元数据路径，都会产出 ``MediaType``：
#
#   1. ``api.py``    —— yt-dlp 的 ``extract_info`` info dict（下载/解析路径）
#   2. ``webapi.py`` —— 自建签名管线拿到的 aweme dict（采集路径）
#
# 两条路径曾经各写一套判据，导致同一条图文链接在「解析」与「采集」下得到
# 不同的 ``media_type``（ROADMAP P0-1）。下面的常量与判据函数放在这里作为
# 唯一真源：``url.py`` 是抖音包内唯一不依赖 httpx / yt_dlp 的底层模块，
# 两边都能安全导入，不会引入循环依赖或把 yt_dlp 拖进 webapi 的导入链。

#: 抖音「图集 / 图文」的 ``aweme_type`` 类型码。
IMAGE_AWEME_TYPES: frozenset[int] = frozenset({68, 150})

#: aweme / info dict 上「出现即说明是图集」的字段名。
#:
#: ``api.py`` 那边用 ``images`` / ``image_url`` / ``thumbnails_list``
#: （yt-dlp 的图集偏移表示）；``webapi.py`` 用 ``images`` 为主，后两个
#: 一并接受，保证同口径。
IMAGE_ALBUM_FIELDS: tuple[str, ...] = (
    "images",           # 图集图片列表（两条路径共有的主信号）
    "image_url",        # 部分 yt-dlp 版本只给单张图
    "thumbnails_list",  # 图文帖的图片集合（区别于视频封面 thumbnails）
)


def is_image_album_payload(data: dict) -> bool:
    """Return ``True`` when ``data`` describes a 抖音 图集 / 图文 post.

    ``data`` 既可以是 yt-dlp 的 info dict，也可以是 web-API 的 aweme dict
    ——两者在这几个字段上的语义一致，因此共用一套判据。

    判据（任一命中即为图集）：

    1. 出现 :data:`IMAGE_ALBUM_FIELDS` 中任意一个字段且其值非空；
    2. ``aweme_type`` ∈ :data:`IMAGE_AWEME_TYPES`。

    **刻意不看的字段**：``formats`` / ``video`` / ``duration``。图文帖常带
    一条纯音频流（背景音乐），若用「没有任何音视频流」来判定就会漏判——
    这正是 P0-1 的根因。

    ``bool`` 是 ``int`` 的子类，这里显式排除，避免 ``aweme_type=True``
    被当成类型码参与比较。
    """
    if any(data.get(field) for field in IMAGE_ALBUM_FIELDS):
        return True
    aweme_type = data.get("aweme_type")
    if isinstance(aweme_type, bool):
        return False
    return aweme_type in IMAGE_AWEME_TYPES


# ---------------------------------------------------------------------------
# Patterns — kept simple and tested independently of adapter logic
# ---------------------------------------------------------------------------

_PATTERNS: list[tuple[DouyinURLType, re.Pattern[str]]] = [
    (DouyinURLType.VIDEO,     re.compile(r"https?://(?:www\.)?douyin\.com/video/(?P<id>\d+)")),
    (DouyinURLType.NOTE,      re.compile(r"https?://(?:www\.)?douyin\.com/note/(?P<id>\d+)")),
    (DouyinURLType.GALLERY,   re.compile(r"https?://(?:www\.)?douyin\.com/gallery/(?P<id>\d+)")),
    # 合集 + seq 后缀（"合集里第 N 个视频"）：M6.45+ 单独识别。
    # 必须在通用 `/collection/{id}` 之前——否则 seq 被静默吞掉。
    # ``seq`` 从 URL 抽出来放进 ClassifiedURL.seq（int），不是 ``id`` 的一部分。
    (DouyinURLType.COLLECTION,re.compile(r"https?://(?:www\.)?douyin\.com/collection/(?P<id>\d+)/(?P<seq>\d+)(?:[/?#]|$)")),
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
    #: 合集里第几个个视频（``/collection/{mix_id}/{seq}``）；``None`` 时
    #: 表示整个合集。``adapter.parse`` 据此切单条 / 容器两种模式。
    seq: Optional[int] = None


def classify_douyin_url(url: str) -> ClassifiedURL:
    """Classify a Douyin URL. Falls back to (UNKNOWN, "", url).

    对合集 URL：``/collection/{mix_id}`` 返回 ``seq=None``（整个合集），
    ``/collection/{mix_id}/{seq}`` 返回 ``seq=int``（合集里第 seq 个视频）。
    通用 `seq` 提取走 ``_seq_from_match``，跟模式位置无关——以后再加
    新 URL 形态（iesdouyin mix detail + seq 等）直接复用。
    """
    if not url:
        return ClassifiedURL(DouyinURLType.UNKNOWN, "", url)
    for url_type, pat in _PATTERNS:
        m = pat.search(url)
        if m:
            seq_str = m.groupdict().get("seq")
            seq = int(seq_str) if seq_str else None
            return ClassifiedURL(url_type, m.group("id"), url, seq=seq)
    return ClassifiedURL(DouyinURLType.UNKNOWN, "", url)
