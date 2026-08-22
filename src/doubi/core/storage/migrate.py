"""One-shot migration scripts from legacy databases.

Currently supports:

* **douyin-downloader** ``dy_downloader.db``  → ``media_item`` (full)
* **Bili23 task database** (best-effort)       → ``media_item`` (partial)

The migrators are intentionally standalone functions: they open their
own connection to the source DB, read what they need, and call into
the destination :class:`~doubi.core.storage.database.Database`.

Run from the CLI: ``doubi migrate --from douyin /path/to/dy_downloader.db``.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from .database import Database

logger = logging.getLogger("doubi.core.storage.migrate")


# ---------------------------------------------------------------------------
# douyin-downloader
# ---------------------------------------------------------------------------


async def migrate_douyin_to_doubi(legacy_db: Path, dest: Database) -> int:
    """Read every row from a ``dy_downloader.db`` and write into ``dest``.

    Mapping (douyin columns → doubi columns):

        aweme_id          → item_id
        title             → title
        author_id         → author_id
        author_name       → author_name
        author_sec_uid    → extra.author_sec_uid
        create_time       → publish_time
        file_path         → last_save_dir  (basename only; legacy saves
                                           the absolute file path of the
                                           first media file)
        metadata          → payload  (raw JSON blob, kept verbatim)
        cover_urls        → extra.cover_urls
        download_time     → last_download_time
        job_id            → extra.job_id

    Returns the number of rows written.
    """
    if not legacy_db.exists():
        logger.warning("legacy DB not found: %s", legacy_db)
        return 0

    # Read the legacy DB synchronously (sqlite3) — it's a one-shot
    # import, no need to pay the aiosqlite tax.
    conn = sqlite3.connect(str(legacy_db))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r[0] for r in cur.fetchall()}
        if "aweme" not in tables:
            logger.warning("legacy DB has no 'aweme' table: %s", legacy_db)
            return 0

        # Get the column set defensively
        info = conn.execute("PRAGMA table_info(aweme)").fetchall()
        cols = {row[1] for row in info}

        cur = conn.execute("SELECT * FROM aweme")
        rows = cur.fetchall()
    finally:
        conn.close()

    written = 0
    for r in rows:
        d = dict(r)
        aweme_id = d.get("aweme_id") or ""
        if not aweme_id:
            continue
        # Extract first media path as save_dir
        file_path = d.get("file_path") or ""
        save_dir = file_path  # legacy stored a single path; treat as save_dir

        # Build payload from the raw metadata JSON
        metadata_str = d.get("metadata") or ""
        payload: dict[str, Any] | None = None
        if metadata_str:
            try:
                payload = json.loads(metadata_str)
            except (ValueError, TypeError):
                payload = None

        # Build extra dict for platform-specific leftovers
        extra: dict[str, Any] = {}
        if "author_sec_uid" in cols and d.get("author_sec_uid"):
            extra["author_sec_uid"] = d["author_sec_uid"]
        if "cover_urls" in cols and d.get("cover_urls"):
            try:
                extra["cover_urls"] = json.loads(d["cover_urls"])
            except (ValueError, TypeError):
                extra["cover_urls"] = d["cover_urls"]
        if "job_id" in cols and d.get("job_id"):
            extra["job_id"] = d["job_id"]
        if "aweme_type" in cols and d.get("aweme_type"):
            extra["aweme_type"] = d["aweme_type"]

        await dest.record_download(
            platform="douyin",
            item_id=str(aweme_id),
            save_dir=save_dir,
            title=d.get("title"),
            author_id=d.get("author_id"),
            author_name=d.get("author_name"),
            cover_url=None,        # legacy stored mirrors in metadata
            duration=None,         # not stored in legacy aweme row
            publish_time=int(d["create_time"]) if d.get("create_time") else None,
            media_type=d.get("aweme_type") or "video",
            payload=payload,
            extra=extra or None,
        )
        written += 1

    logger.info("Migrated %d douyin rows from %s", written, legacy_db)
    return written


# ---------------------------------------------------------------------------
# Bili23 (best-effort)
# ---------------------------------------------------------------------------


async def migrate_bili23_to_doubi(legacy_db: Path, dest: Database) -> int:
    """Best-effort migration from a Bili23 task database.

    Bili23's schema is private to the project (we only know it from
    reading the source). We attempt to read the most common column
    names; rows that don't match are skipped.

    Returns the number of rows written.
    """
    if not legacy_db.exists():
        return 0
    conn = sqlite3.connect(str(legacy_db))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r[0] for r in cur.fetchall()}
        # Bili23 uses one of: tasks / task / download_tasks
        table = next((t for t in ("tasks", "task", "download_tasks") if t in tables), None)
        if not table:
            logger.warning("Bili23 DB has no recognizable task table: %s", legacy_db)
            return 0
        info = conn.execute(f"PRAGMA table_info({table})").fetchall()
        cols = {row[1] for row in info}
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()
    finally:
        conn.close()

    written = 0
    for r in rows:
        d = dict(r)
        # Try common id / title column names
        item_id = (
            d.get("bvid")
            or d.get("avid")
            or d.get("id")
            or d.get("task_id")
        )
        if not item_id:
            continue
        title = d.get("title") or d.get("name") or ""
        author = d.get("up_name") or d.get("uploader") or d.get("author") or ""
        author_id = d.get("up_id") or d.get("mid") or d.get("uploader_id") or ""
        save_dir = d.get("save_dir") or d.get("output_path") or ""

        await dest.record_download(
            platform="bilibili",
            item_id=str(item_id),
            save_dir=save_dir,
            title=title,
            author_id=str(author_id) if author_id else None,
            author_name=author or None,
            publish_time=None,
            media_type="video",
        )
        written += 1

    logger.info("Migrated %d bilibili rows from %s", written, legacy_db)
    return written
