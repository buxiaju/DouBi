"""Filename template token substitution (platform-agnostic).

The user-facing ``filename_template`` (e.g. ``"{date}_{title}_{item_id}"``)
is rendered into a safe filesystem basename using :class:`MediaItem`
fields plus :class:`DownloadOptions` knobs. Filenames are sanitized
to remove characters illegal on Windows / macOS / Linux and capped at
200 chars to stay well under common FS limits.

Supported tokens:
    ``{title}``         item.title (sanitized)
    ``{item_id}``       item.item_id
    ``{author}``        item.author.name
    ``{date}``          item.publish_time as ``YYYY-MM-DD`` (empty if missing)
    ``{platform}``      item.platform.value
    ``{quality}``       options.max_quality
    ``{index}``         zero-padded index in a batch (3 digits)
    ``{ext}``           is **not** expanded here — the engine appends
                        ``.%(ext)s`` so yt-dlp can fill the container.

Collection grouping
-------------------
This module renders a **basename only** — it never emits directory
separators. Grouping episodes of a collection into one shared folder
is handled one level up by
:func:`doubi.core.storage.file_layout.resolve_item_dir`, which names the
per-item leaf directory after ``item.extra["collection_title"]`` when
present and after ``item.title`` otherwise.
"""

from __future__ import annotations

import re
from typing import Optional

from .models import DownloadOptions, MediaItem

__all__ = [
    "MAX_BASENAME",
    "render_filename",
    "set_item_output_template",
]

_TOKEN_RE = re.compile(r"\{(\w+)\}")

# Windows-reserved + path separators + control chars.
_ILLEGAL_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_TRAILING_DOTS_RE = re.compile(r"[\. ]+$")
_WHITESPACE_RE = re.compile(r"\s+")

# Maximum basename length. NTFS/HFS+/ext4 all support > 255 but common
# copy operations and shells break earlier, so we cap conservatively.
MAX_BASENAME = 200


def _sanitize(value: str) -> str:
    """Replace filesystem-unsafe characters and trim trailing junk."""
    if not value:
        return "_"
    s = _ILLEGAL_RE.sub("_", value)
    s = _WHITESPACE_RE.sub(" ", s).strip()
    s = _TRAILING_DOTS_RE.sub("", s)
    if not s or s in {".", ".."}:
        return "_"
    return s


def render_filename(
    item: MediaItem,
    options: DownloadOptions,
    *,
    index: int = 0,
) -> str:
    """Render ``options.filename_template`` for ``item`` into a safe basename.

    The returned string does NOT include the file extension; the engine
    is responsible for appending ``.mp4`` / ``.mkv`` / etc.
    """
    template = options.filename_template or "{title}_{item_id}"

    date_str = ""
    if item.publish_time is not None:
        date_str = item.publish_time.strftime("%Y-%m-%d")

    values = {
        "title":    _sanitize(item.title or "untitled"),
        "item_id":  _sanitize(item.item_id or "no_id"),
        "author":   _sanitize(item.author.name if item.author and item.author.name else "unknown"),
        "date":     date_str,
        "platform": item.platform.value if item.platform else "unknown",
        "quality":  _sanitize(options.max_quality or "best"),
        "index":    f"{max(0, index):03d}",
    }

    def _replace(m: re.Match) -> str:
        return values.get(m.group(1), m.group(0))   # leave unknown tokens literal

    rendered = _TOKEN_RE.sub(_replace, template)
    rendered = _sanitize(rendered)
    if len(rendered) > MAX_BASENAME:
        rendered = rendered[:MAX_BASENAME].rstrip(". ")
    return rendered or "_"


def set_item_output_template(
    item: MediaItem,
    options: DownloadOptions,
    *,
    index: int = 0,
) -> None:
    """Render and stash the basename on the item itself.

    The engine reads :attr:`MediaItem.output_template` and uses it as
    the basename if set, falling back to ``options.filename_template``.
    """
    item.output_template = render_filename(item, options, index=index)
