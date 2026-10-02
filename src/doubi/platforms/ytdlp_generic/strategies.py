"""yt-dlp InfoDict → MediaItem conversion for ``YtDlpGenericAdapter``.

yt-dlp 的不同 extractor 返回的 InfoDict 字段差异很大：Twitter 没
``duration``、Reddit 没 ``uploader`` 只有 ``channel``、Vimeo 把作者
放在 ``creator``、Pixiv 在 ``artist``。这一模块做归一化，把所有可能
命名的字段映射到 doubi 统一的 :class:`MediaItem` 字段上。

设计要点：

* **字段归一化不是「找所有可能键」**：只覆盖 yt-dlp 主流 extractor 实际
  使用的命名。罕见的私有 extractor 漏掉的字段会留空——engine 下载时
  yt-dlp 自己会再 fetch 一次拿完整元数据。
* **entries 拍平**：yt-dlp playlist 返回 ``entries`` list，entries 自己
  又是 InfoDict（可能是 ``url`` 型即只有 id+url，需要二次 extract）。
  我们递归拍平，但**只下钻一层**——深层私有 extractor 留给上层 expand。
* **失败一律返回 None**：这是「兜底适配器」语义，单条失败不能让整个
  collection 解析崩。
"""

from __future__ import annotations

from typing import Any, Optional

from ...core.models import (
    Author,
    MediaItem,
    MediaType,
    Platform,
)
from ..douyin.api import _parse_timestamp  # 复用现有时间戳解析

#: yt-dlp InfoDict 中「作者」字段的可能命名。
#: 按 yt-dlp 源码 ``YoutubeDL._search_dict`` 的常见命名集合整理。
_UPLOADER_KEYS = ("uploader", "channel", "creator", "artist", "uploader_name")
_UPLOADER_ID_KEYS = ("uploader_id", "channel_id", "creator_id", "uploader_url")
_AVATAR_KEYS = ("uploader_avatar", "channel_thumbnail", "avatar", "thumbnails")

#: yt-dlp InfoDict 中「容器」类型（playlist / multi_video / url 三态）。
#: 命中这些 _type 时构造容器 MediaItem。
_PLAYLIST_TYPES = {"playlist", "multi_video"}


def info_to_author(info: dict) -> Author:
    """从 InfoDict 抽作者字段。

    按 ``_UPLOADER_KEYS`` 顺序挑第一个非空值；头像从 ``_AVATAR_KEYS`` 中
    第一个非空 dict 列表取最大的那一张的 url。
    """
    name = ""
    for key in _UPLOADER_KEYS:
        val = info.get(key)
        if val:
            name = str(val)
            break

    author_id = ""
    for key in _UPLOADER_ID_KEYS:
        val = info.get(key)
        if val:
            author_id = str(val)
            break

    avatar_url: Optional[str] = None
    for key in _AVATAR_KEYS:
        val = info.get(key)
        if isinstance(val, str) and val:
            avatar_url = val
            break
        if isinstance(val, list) and val:
            # yt-dlp 的 thumbnails list 是 [{url, width, height, ...}, ...]
            best = max(
                (t for t in val if isinstance(t, dict) and t.get("url")),
                key=lambda t: t.get("height") or t.get("width") or 0,
                default=None,
            )
            if best:
                avatar_url = best.get("url")
                break

    return Author(id=author_id, name=name, avatar_url=avatar_url)


def info_to_cover(info: dict) -> Optional[str]:
    """挑 InfoDict 里最大的缩略图 URL。"""
    thumbs = info.get("thumbnails") or []
    if isinstance(thumbs, list) and thumbs:
        valid = [t for t in thumbs if isinstance(t, dict) and t.get("url")]
        if valid:
            best = max(valid, key=lambda t: t.get("height") or t.get("width") or 0)
            return best.get("url")
    thumb = info.get("thumbnail")
    return str(thumb) if thumb else None


def info_to_media_type(info: dict) -> MediaType:
    """根据 InfoDict 信号推断 MediaType。

    规则（按优先级）：

    * ``is_live`` / ``live_status == 'is_live'`` → LIVE
    * formats 全是 ``vcodec=none`` 且有 thumbnails → IMAGE_ALBUM（罕见）
    * 默认 VIDEO
    """
    live = info.get("is_live") or info.get("live_status") == "is_live"
    if live:
        return MediaType.LIVE
    formats = info.get("formats") or []
    if formats and not any(f.get("vcodec") not in (None, "none") for f in formats):
        if info.get("thumbnails"):
            return MediaType.IMAGE_ALBUM
    return MediaType.VIDEO


def info_to_media_item(
    info: dict,
    source_url: str,
    *,
    platform: Platform = Platform.YT_DLP_GENERIC,
) -> MediaItem:
    """单条 InfoDict → :class:`MediaItem`（顶层或 container 都适用）。

    ``platform`` 默认为 YT_DLP_GENERIC；调用方在容器构造时也会传同一个值。
    """
    return MediaItem(
        platform=platform,
        item_id=str(info.get("id") or ""),
        title=str(info.get("title") or info.get("description") or ""),
        author=info_to_author(info),
        cover_url=info_to_cover(info),
        duration=info.get("duration"),
        publish_time=_parse_timestamp(info.get("timestamp") or info.get("release_timestamp")),
        media_type=info_to_media_type(info),
        source_url=source_url,
        extra={
            "extractor": info.get("extractor"),
            "extractor_key": info.get("extractor_key"),
            "webpage_url": info.get("webpage_url"),
            "view_count": info.get("view_count"),
            "like_count": info.get("like_count"),
            "description": (info.get("description") or "")[:500],
            "tags": info.get("tags") or [],
        },
    )


def is_playlist_info(info: dict) -> bool:
    """判断 InfoDict 是否表示一个容器（playlist / multi_video）。

    yt-dlp 用 ``_type`` 字段标识：``playlist``、``multi_video`` 是显式
    容器；``url`` 是「叶子 URL，指向子条目」——这种情况也按容器处理，
    让上层 expand 拉子项。
    """
    if not isinstance(info, dict):
        return False
    t = info.get("_type")
    if t in _PLAYLIST_TYPES:
        return True
    # 兜底：没 _type 但有 entries list 也是容器
    return isinstance(info.get("entries"), list) and bool(info.get("entries"))


def entries_to_children(
    entries: list[Any],
    fallback_url: str = "",
    *,
    platform: Platform = Platform.YT_DLP_GENERIC,
) -> list[MediaItem]:
    """拍平 yt-dlp playlist 的 entries → :class:`MediaItem` 列表。

    yt-dlp playlist 的 entries 元素通常是 ``url`` 型 InfoDict（只有 id +
    url），没有完整元数据；构造的 MediaItem 仅含 item_id / title / url，
    其他字段留空——engine 下载时 yt-dlp 会再 fetch。

    过滤掉 ``None``、空 dict、``_type == 'url'_transparent`` 等无用条目。
    """
    children: list[MediaItem] = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        # ``url_transparent`` 是 yt-dlp 内部传递标记，跳过避免重复
        if entry.get("_type") in {"url_transparent"}:
            continue
        url = entry.get("url") or entry.get("webpage_url") or fallback_url
        item_id = str(entry.get("id") or "")
        # 空 id + 空 url 的条目没用
        if not item_id and not url:
            continue
        children.append(
            MediaItem(
                platform=platform,
                item_id=item_id,
                title=str(entry.get("title") or ""),
                author=Author(name=str(entry.get("uploader") or entry.get("channel") or "")),
                cover_url=info_to_cover(entry),
                duration=entry.get("duration"),
                publish_time=_parse_timestamp(entry.get("timestamp")),
                media_type=MediaType.VIDEO,
                source_url=url,
                extra={"extractor": entry.get("extractor"), "_flat_entry": True},
            )
        )
    return children


# Re-export so tests can ``from ..ytdlp_generic.strategies import _parse_timestamp``.
__all__ = [
    "info_to_author",
    "info_to_cover",
    "info_to_media_item",
    "info_to_media_type",
    "is_playlist_info",
    "entries_to_children",
]
