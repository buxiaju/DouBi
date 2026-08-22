"""Append-only JSONL manifest writer.

The manifest is a single line per download at::

    <output_root>/download_manifest.jsonl

Each line is a JSON object with a stable schema. The file is rotated
only when explicitly requested (M4.1+); for now it's append-only with
an atomic per-line write (write to ``*.tmp`` then rename) so a crash
mid-line never produces a half-written JSON object.

The manifest is the **user-facing** record — it's plain JSONL the user
can grep / pipe / load into Pandas. The :sql:`media_item` table is the
**machine-facing** record; the two are intentionally not the same
thing because the manifest is easier to read and the DB is faster to
query.
"""

from __future__ import annotations

import json
import logging
import os
import time as _time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from ..models import MediaItem

logger = logging.getLogger("doubi.core.storage.manifest")


@dataclass
class ManifestRecord:
    """One row in the JSONL manifest."""

    platform: str
    item_id: str
    title: str = ""
    author_id: str = ""
    author_name: str = ""
    media_type: str = ""
    date: str = ""                  # "YYYY-MM-DD" or "0000-00-00"
    tags: list[str] = field(default_factory=list)
    view_count: Optional[int] = None
    like_count: Optional[int] = None
    duration: Optional[float] = None
    cover_url: str = ""
    publish_timestamp: Optional[int] = None
    file_names: list[str] = field(default_factory=list)
    file_paths: list[str] = field(default_factory=list)   # relative to output_root
    download_time: int = 0          # unix seconds
    extra: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, separators=(",", ":"))


class ManifestWriter:
    """Append-only JSONL writer with atomic per-line writes.

    The file is opened in line-buffered append mode; each ``record()``
    call writes to a sibling ``.tmp`` and renames it on top of the
    target so a power loss / crash never leaves a half-written line.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Touch the file so the first record doesn't have to.
        if not self.path.exists():
            self.path.touch()

    def record(
        self,
        item: MediaItem,
        file_names: Iterable[str],
        file_paths: Iterable[str],
    ) -> ManifestRecord:
        """Append one record. Returns the written :class:`ManifestRecord`."""
        rec = _build_record(item, list(file_names), list(file_paths))
        line = rec.to_json() + "\n"
        # Open in append mode, write, flush, fsync. The previous contents
        # (if any) are preserved. Using os.replace here would clobber all
        # prior records.
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())
        logger.debug("manifest: %s (%d files)", item.item_id, len(rec.file_names))
        return rec

    def read_all(self) -> list[dict]:
        """Read all records (best-effort: blank lines are skipped)."""
        if not self.path.exists():
            return []
        out: list[dict] = []
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    out.append(json.loads(s))
                except json.JSONDecodeError:
                    logger.warning("manifest: skipping malformed line")
        return out


def _build_record(
    item: MediaItem, file_names: list[str], file_paths: list[str]
) -> ManifestRecord:
    extra = dict(item.extra or {})
    tags = extra.pop("tags", []) or []
    view_count = extra.pop("view_count", None)
    like_count = extra.pop("like_count", None)
    publish_ts: Optional[int] = None
    if item.publish_time is not None:
        publish_ts = int(item.publish_time.timestamp())

    date_str = ""
    if item.publish_time is not None:
        date_str = item.publish_time.strftime("%Y-%m-%d")

    return ManifestRecord(
        platform=item.platform.value if item.platform else "unknown",
        item_id=item.item_id,
        title=item.title or "",
        author_id=item.author.id if item.author else "",
        author_name=item.author.name if item.author else "",
        media_type=item.media_type.value if item.media_type else "",
        date=date_str,
        tags=list(tags) if tags else [],
        view_count=view_count,
        like_count=like_count,
        duration=item.duration,
        cover_url=item.cover_url or "",
        publish_timestamp=publish_ts,
        file_names=file_names,
        file_paths=file_paths,
        download_time=int(_time.time()),
        extra=extra,
    )
