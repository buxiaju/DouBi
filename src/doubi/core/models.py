"""Core data models — platform- and engine-agnostic.

These types are the lingua franca between platform adapters, the
pipeline, engines, and any UI surface (CLI / GUI / REST / MCP).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

if TYPE_CHECKING:
    from .pipeline import ProgressEvent


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class Platform(str, Enum):
    """Identifier for a supported platform."""

    DOUYIN = "douyin"
    BILIBILI = "bilibili"
    YOUTUBE = "youtube"
    TIKTOK = "tiktok"
    XIAOHONGSHU = "xiaohongshu"
    WEIBO = "weibo"
    UNKNOWN = "unknown"

    @classmethod
    def from_str(cls, value: str) -> "Platform":
        if not value:
            return cls.UNKNOWN
        v = value.strip().lower()
        for member in cls:
            if member.value == v:
                return member
        return cls.UNKNOWN


class MediaType(str, Enum):
    """Logical media category. Each platform maps its native types to one of these."""

    VIDEO = "video"
    IMAGE_ALBUM = "image_album"
    AUDIO = "audio"
    LIVE = "live"
    LIVE_REPLAY = "live_replay"
    BANGUMI = "bangumi"          # 番剧
    COURSE = "course"            # 课程
    FAVLIST = "favlist"          # 收藏夹
    MIX = "mix"                  # 合集
    MUSIC = "music"              # 音乐原声
    USER = "user"                # 用户主页（容器）
    COLLECTION = "collection"    # 通用容器


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------


@dataclass
class Author:
    """A piece of content's creator / uploader."""

    id: str = ""
    name: str = ""
    avatar_url: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Stream:
    """A single downloadable media stream (video track / audio track / image)."""

    stream_id: str                       # unique within a MediaItem
    kind: str                            # "video" | "audio" | "image" | "subtitle" | ...
    quality: str = "best"                # human-readable: "1080p" | "lossless" | "original"
    codec: Optional[str] = None          # "h264" | "hevc" | "av1" | "aac" | "opus" | ...
    bitrate: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    duration: Optional[float] = None
    filesize: Optional[int] = None
    container: str = "mp4"               # output container hint
    url: Optional[str] = None            # direct URL if engine provides one
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class MediaItem:
    """A unit of work for the pipeline.

    A MediaItem may represent a single video, a note, an album, a live
    room, OR a container (user / favlist / mix / collection) holding
    children. Callers should check :meth:`is_container` and recurse into
    :attr:`children` when present.
    """

    platform: Platform
    item_id: str                                  # aweme_id / bvid / epid / mix_id ...
    title: str
    author: Author = field(default_factory=Author)
    cover_url: Optional[str] = None
    duration: Optional[float] = None              # seconds
    publish_time: Optional[datetime] = None
    media_type: MediaType = MediaType.VIDEO
    source_url: str = ""                          # the original URL the user gave us
    streams: list[Stream] = field(default_factory=list)
    children: list["MediaItem"] = field(default_factory=list)  # populated for containers
    extra: dict[str, Any] = field(default_factory=dict)

    #: Pre-rendered filename template (without extension). If set, the
    #: engine uses this as the basename instead of ``options.filename_template``.
    #: The pipeline sets this right before download so per-item metadata
    #: (title / author / date) is honored.
    output_template: Optional[str] = None

    def is_container(self) -> bool:
        return bool(self.children)

    def total_duration(self) -> Optional[float]:
        if not self.is_container():
            return self.duration
        subs = [c.total_duration() for c in self.children]
        subs = [d for d in subs if d is not None]
        return sum(subs) if subs else None


@dataclass
class DownloadOptions:
    """User-facing download configuration.

    This is the normalized options bag passed from UI / CLI / REST down
    to the engine. Each field is engine-portable; engine-specific
    knobs live in :attr:`extra`.
    """

    #: Top-level directory under which all downloads are placed.
    #: (M4: renamed from ``output_dir`` for clarity — ``output_dir``
    #: is now the *per-item* computed directory returned by
    #: :func:`doubi.core.storage.file_layout.resolve_item_dir`.)
    output_root: Path = Path("./Downloaded")
    #: Directory layout template (relative to ``output_root``). Tokens:
    #: ``{platform} {author} {author_id} {media_type} {date} {title} {item_id}``.
    output_dir_template: str = "{platform}/{author}/{media_type}"
    #: Per-item filename template (without extension). Tokens:
    #: ``{title} {item_id} {author} {date} {platform} {quality} {index}``.
    filename_template: str = "{title}_{item_id}"
    container: str = "mp4"                        # "mp4" | "mkv"
    max_quality: str = "best"                     # "8k" | "4k" | "1080p" | "best"
    format_id: Optional[str] = None               # engine-native format selector

    write_thumbnail: bool = False
    write_metadata_json: bool = False
    write_nfo: bool = False
    write_danmaku: bool = False
    write_subtitles: bool = False

    concurrent_fragments: int = 4
    rate_limit: Optional[str] = None              # e.g. "5M"
    proxy: Optional[str] = None
    cookies_file: Optional[Path] = None
    user_agent: Optional[str] = None

    #: SQLite database path. Set to ``None`` to disable DB-based dedup.
    database: Optional[Path] = None
    #: Path to the JSONL manifest (relative or absolute). Set to ``None`` to skip.
    manifest: Optional[Path] = None

    extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Job tracking
# ---------------------------------------------------------------------------


@dataclass
class DownloadJob:
    """A batch of MediaItems to be processed together."""

    job_id: str
    items: list[MediaItem] = field(default_factory=list)
    options: Optional[DownloadOptions] = None

    status: str = "pending"          # pending | running | completed | failed | cancelled
    progress: float = 0.0            # 0.0 - 1.0
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    def completed_count(self) -> int:
        return sum(1 for _ in self.items)  # placeholder, populated by manager

    def failed_count(self) -> int:
        return 0


# ---------------------------------------------------------------------------
# Progress callback type — kept as a string alias to avoid runtime cycles
# ---------------------------------------------------------------------------


#: Signature: (event: ProgressEvent) -> None
ProgressCallback = Callable[["ProgressEvent"], None]
