"""Storage layer: SQLite database + filesystem layout + JSONL manifest."""

from __future__ import annotations

from .database import Database, MediaItemRow, TaskRow
from .file_layout import (
    DEFAULT_DIR_TEMPLATE,
    already_downloaded_on_disk,
    collection_title_of,
    episode_title_of,
    item_leaf_name,
    item_leaf_parts,
    render_dir,
    resolve_item_dir,
    resolve_save_dir,
    section_title_of,
)
from .manifest import ManifestRecord, ManifestWriter
from .nfo import NFO_SUFFIX, build_nfo_xml, write_nfo

__all__ = [
    "Database",
    "MediaItemRow",
    "TaskRow",
    "ManifestRecord",
    "ManifestWriter",
    "NFO_SUFFIX",
    "build_nfo_xml",
    "write_nfo",
    "DEFAULT_DIR_TEMPLATE",
    "render_dir",
    "resolve_item_dir",
    "resolve_save_dir",
    "already_downloaded_on_disk",
    "collection_title_of",
    "episode_title_of",
    "item_leaf_name",
    "item_leaf_parts",
    "section_title_of",
]
