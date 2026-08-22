"""Unified output directory layout.

Default layout::

    <output_root>/
    ├── {platform}/
    │   └── {author}/
    │       └── {media_type}/
    │           ├── {collection_title}/      # one folder per collection
    │           │   ├── ep1.mp4
    │           │   └── ep2.mp4
    │           ├── {collection_title}/      # categorised collection
    │           │   └── {section_title}/     # ← the site's category tabs
    │           │       └── {episode_title}/
    │           │           └── {episode_title}_P001.mp4
    │           └── {video_title}/           # standalone video
    │               └── {video_title}.mp4

The leaf directory is named after ``item.extra["collection_title"]``
when the item belongs to a collection (so all episodes share a single
folder) and after ``item.title`` otherwise. Collections that group
their episodes into categories additionally carry
``item.extra["section_title"]``, which inserts the category level and
gives every episode its own folder. Only the media files are kept
there; thumbnails / metadata sidecars are opt-in.

The directory template and the per-item filename template are
configurable. Tokens use the same ``{name}`` syntax as the filename
template in :mod:`doubi.core.naming`.

Sanitization is shared with the filename sanitizer: characters illegal
on Windows / macOS / Linux are replaced with ``_``, trailing dots
and whitespace are trimmed, and the basename is length-capped.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from ..models import DownloadOptions, MediaItem
from .. import naming

# Maximum path length for any single relative path component. NTFS
# allows 255; we cap at 120 to stay under even exotic path schemes.
MAX_COMPONENT = 120

#: Default directory template.
DEFAULT_DIR_TEMPLATE = "{platform}/{author}/{media_type}"

_DIR_TOKEN_RE = re.compile(r"\{(\w+)\}")

# Reuse naming's illegal-char regex
_ILLEGAL_RE = naming._ILLEGAL_RE
_TRAILING_DOTS_RE = naming._TRAILING_DOTS_RE
_WHITESPACE_RE = naming._WHITESPACE_RE


def _sanitize_component(value: str, *, fallback: str = "_unknown") -> str:
    if not value:
        return fallback
    s = _ILLEGAL_RE.sub("_", str(value))
    s = _WHITESPACE_RE.sub(" ", s).strip()
    s = _TRAILING_DOTS_RE.sub("", s)
    if not s or s in {".", ".."}:
        return fallback
    if len(s) > MAX_COMPONENT:
        s = s[:MAX_COMPONENT].rstrip(". ")
        if not s:
            return fallback
    return s


def _date_string(item: MediaItem) -> str:
    if item.publish_time is None:
        return "0000-00-00"
    return item.publish_time.strftime("%Y-%m")


def _build_values(item: MediaItem) -> dict[str, str]:
    """Build the substitution table for the directory template."""
    return {
        "platform":   item.platform.value if item.platform else "unknown",
        "author":     _sanitize_component(item.author.name, fallback="unknown_author")
                       if item.author else "unknown_author",
        "author_id":  _sanitize_component(item.author.id) if item.author and item.author.id else "",
        "media_type": item.media_type.value if item.media_type else "video",
        "date":       _date_string(item),
        "title":      _sanitize_component(item.title, fallback="untitled"),
        "item_id":    _sanitize_component(item.item_id, fallback="no_id"),
    }


def render_dir(item: MediaItem, template: str) -> str:
    """Render a *relative* directory path for ``item`` per ``template``.

    Returns a string like ``"douyin/张三/video"``. Backslashes are
    converted to forward slashes for cross-platform consistency. The
    returned path does NOT include the output root.
    """
    template = template or DEFAULT_DIR_TEMPLATE
    values = _build_values(item)

    def _replace(m: re.Match) -> str:
        return values.get(m.group(1), m.group(0))   # leave unknown tokens literal

    out = _DIR_TOKEN_RE.sub(_replace, template)
    # Normalize separators + collapse doubles
    out = out.replace("\\", "/")
    out = re.sub(r"/+", "/", out)
    return out.strip("/")


def resolve_save_dir(
    item: MediaItem,
    options: DownloadOptions,
    *,
    root: Optional[Path] = None,
) -> Path:
    """Compute the absolute directory the engine should write into.

    The result is ``root / render_dir(item, options.output_dir_template)``
    with each intermediate directory created. This does **not** include
    the per-item leaf directory — see :func:`resolve_item_dir`.
    """
    base = Path(root or options.output_root).expanduser()
    base.mkdir(parents=True, exist_ok=True)
    rel = render_dir(item, options.output_dir_template)
    return base / rel


def collection_title_of(item: MediaItem) -> Optional[str]:
    """Return the collection (playlist) title recorded on the item, if any.

    Platform adapters put it into ``item.extra["collection_title"]`` when the
    item is one episode of a multi-part video / collection.
    """
    extra = getattr(item, "extra", None) or {}
    value = extra.get("collection_title")
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def section_title_of(item: MediaItem) -> Optional[str]:
    """Return the section (category) title recorded on the item, if any.

    Bilibili "ugc_season" collections may group their episodes into
    sections (the horizontal tabs on the web page). Adapters put the
    section name into ``item.extra["section_title"]``; it is only present
    for collections that really are categorised.
    """
    extra = getattr(item, "extra", None) or {}
    value = extra.get("section_title")
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def episode_title_of(item: MediaItem) -> Optional[str]:
    """Return the *episode* title recorded on a page row, if any.

    B站 ugc_season pages are 3-level deep:

        season ▸ section ▸ episode (BV) ▸ page

    When the user expands an episode down to its 分P pages (each page
    is a separate download target) we want the on-disk path to be

        合集名/分类名/分集名/P1/

    instead of the bare ``P1/``. Adapters store the episode's title
    into ``item.extra["episode_title"]`` for these page rows; this
    helper reads it.
    """
    extra = getattr(item, "extra", None) or {}
    value = extra.get("episode_title")
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def item_leaf_parts(item: MediaItem) -> list[str]:
    """Relative directory components below :func:`resolve_save_dir`.

    Four shapes, in order of specificity:

    * Page of a *categorised* episode (collection + section +
      episode_title + a non-empty item.title) → ``[collection, section,
      episode, page_title]``.
    * Episode of a *categorised* collection (both ``collection_title``
      and ``section_title`` present) →
      ``[collection, section, episode]`` so the on-disk tree mirrors the
      collection ▸ category ▸ episode hierarchy.
    * Episode of a flat collection (``collection_title`` only) →
      ``[collection]``, i.e. every episode shares one folder.
    * Standalone video → ``[title]``.
    """
    collection = collection_title_of(item)
    section = section_title_of(item)
    episode = episode_title_of(item)
    if collection and section and episode:
        return [
            _sanitize_component(collection, fallback="collection"),
            _sanitize_component(section, fallback="section"),
            _sanitize_component(episode, fallback="untitled"),
            _sanitize_component(item.title, fallback="untitled"),
        ]
    if collection and section:
        return [
            _sanitize_component(collection, fallback="collection"),
            _sanitize_component(section, fallback="section"),
            _sanitize_component(item.title, fallback="untitled"),
        ]
    if collection:
        return [_sanitize_component(collection, fallback="collection")]
    return [_sanitize_component(item.title, fallback="untitled")]


def item_leaf_name(item: MediaItem) -> str:
    """Name of the innermost per-item directory.

    Equivalent to the last component of :func:`item_leaf_parts`.
    """
    return item_leaf_parts(item)[-1]


def resolve_item_dir(
    item: MediaItem,
    options: DownloadOptions,
    *,
    root: Optional[Path] = None,
) -> Path:
    """Like :func:`resolve_save_dir` but appends the per-item leaf dirs.

    The leaf is ``合集名/分类名/分集名`` for episodes of a categorised
    collection, the collection title alone for flat collections (so every
    episode shares one folder) and the video title otherwise. The
    engine's ``outtmpl`` can then just use the basename.
    """
    save_dir = resolve_save_dir(item, options, root=root)
    target = save_dir
    for part in item_leaf_parts(item):
        target = target / part
    target.mkdir(parents=True, exist_ok=True)
    return target


def already_downloaded_on_disk(save_dir: Path, basename: Optional[str] = None) -> bool:
    """Heuristic: True if this item's media already sits in ``save_dir``.

    Used as the second line of defense against duplicates (DB is the
    first; the filesystem is the second because the user can manually
    delete the DB row but keep the files).

    ``basename`` is the rendered filename stem for **one** item (see
    :func:`doubi.core.naming.render_filename`). It must be passed when
    ``save_dir`` may be shared by several items — which is the case for
    collection folders — otherwise episode 1's file would make every
    later episode look already-downloaded. Without it the check falls
    back to "any non-hidden file in the directory".

    The comparison is a prefix match so that the engine's per-part
    suffix (``{basename}_P007.mp4``, see
    :data:`doubi.engines.yt_dlp.PART_INDEX_SUFFIX`) still counts as this
    item's output.
    """
    if not save_dir.exists() or not save_dir.is_dir():
        return False
    for p in save_dir.iterdir():
        if not p.is_file() or p.name.startswith("."):
            continue
        if basename is None or p.name.startswith(basename):
            return True
    return False
