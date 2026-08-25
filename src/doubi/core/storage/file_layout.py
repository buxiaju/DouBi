"""Unified output directory layout.

Default layout::

    <output_root>/
    ├── {platform}/
    │   └── {author}/
    │       └── {media_type}/
    │           ├── {collection_title}/      # flat collection
    │           │   ├── ep1_title_ep1id.mp4
    │           │   └── ep2_title_ep2id.mp4
    │           ├── {collection_title}/      # categorised collection
    │           │   └── {section_title}/     # ← the site's category tabs
    │           │       └── {episode_title}/
    │           │           └── ep_title_epid_P001.mp4
    │           └── standalone_title_id.mp4  # standalone, no subdir

The leaf directory is named after ``item.extra["collection_title"]``
for flat collections (all episodes share one folder) and
``collection/section/episode[/page]`` for categorised ugc seasons.

**Standalone videos intentionally have no per-item leaf subdir.**
Their basename already carries the full sanitised title plus the
unique item id, so removing the redundant same-named subdir halves
the title footprint on disk and avoids the classic Windows
``[Errno 2] No such file or directory`` MAX_PATH failure seen when a
long YouTube title is duplicated across both a subdir and the
filename (e.g. ``Garden design … / Garden design …_id.mp4.part``).

Sidecar files (thumbnail / NFO / JSON / subtitles / danmaku) are
opt-in and fall next to the main media file, sharing the basename
prefix so the filesystem itself naturally groups them per item even
without a dedicated subfolder.

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

# Maximum length for any single relative path component. NTFS caps at
# 255 unicode chars; we stay well under so the sum of the default
# template + a long video title never tips past MAX_PATH on Windows.
#
# Historical note: was 120. Reduced to 80 after a YouTube standalone
# video with a ~95-char title hit ``[Errno 2] No such file or directory``
# because the old layout placed the title both as a per-item leaf dir
# AND as the filename prefix — doubling it. The layout no longer nests
# standalone titles under a same-named dir, but keeping the component
# cap at 80 still guards against collection/section/episode cascades
# of three 120-char dir names adding ~360 chars on their own.
MAX_COMPONENT = 80

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
    * **Standalone video → ``[]`` (no extra leaf dir).**

    The standalone case deliberately avoids a ``{title}/`` subdir because
    the basename rendered by :mod:`naming` already contains the full
    title (``{title}_{item_id}.%(ext)s``). Adding an identically-named
    directory would double the title in the final path and easily blow
    past Windows' ``MAX_PATH`` (260 chars) for long titles — producing
    ``[Errno 2] No such file or directory: '...<title>/<title>_id.mp4'``
    at yt-dlp open-for-write time.
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
    # Standalone video: no leaf dir.  The filenames already embed the
    # sanitised title (plus item_id for collision safety), so sidecar
    # files (thumbnail / NFO / JSON / subtitles / danmaku) stay naturally
    # grouped by the common basename prefix even inside the shared
    # <platform>/<author>/<media_type> folder.
    return []


def item_leaf_name(item: MediaItem) -> str:
    """Name of the innermost per-item directory.

    Equivalent to the last component of :func:`item_leaf_parts`. Falls
    back to the sanitised title when the standalone-video case yields no
    explicit per-item leaf directory.
    """
    parts = item_leaf_parts(item)
    if parts:
        return parts[-1]
    return _sanitize_component(item.title, fallback="untitled")


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
