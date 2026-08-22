"""Unified SQLite storage for DouBi.

The :class:`Database` class owns a single ``doubi.db`` file with three
tables:

* :sql:`media_item`        — one row per (platform, item_id), the
                             primary dedup table
* :sql:`task`              — batch job history (CLI / REST submit)
* :sql:`increment_checkpoint` — per-user incremental-download cursor
                                (used by douyin's "increase" mode
                                and similar M5+ features)

A row in :sql:`media_item` is created on a successful download; the
``is_downloaded()`` check is the source of truth for skip-or-download
decisions, with the on-disk file presence used as a secondary check
(see :func:`core.storage.file_layout.already_downloaded_on_disk`).

Migration:

The :mod:`core.storage.migrate` module knows how to read a
``dy_downloader.db`` (the old douyin-downloader format) and a Bili23
``task.db`` (best-effort) and write the rows into ``media_item``.
Call :func:`Database.migrate_from_legacy` from the CLI's one-shot
``doubi migrate`` command, or the database is created empty if no
legacy file is present.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time as _time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import aiosqlite

logger = logging.getLogger("doubi.core.storage.database")


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


SCHEMA: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS media_item (
        platform          TEXT NOT NULL,
        item_id           TEXT NOT NULL,
        title             TEXT,
        author_id         TEXT,
        author_name       TEXT,
        cover_url         TEXT,
        duration          REAL,
        publish_time      INTEGER,            -- unix timestamp (seconds)
        media_type        TEXT,
        payload           TEXT,                -- raw JSON blob (yt-dlp info dict)
        last_download_time INTEGER,            -- unix timestamp
        last_save_dir     TEXT,                -- relative path under output_root
        extra             TEXT,                -- JSON blob for platform-specific fields
        PRIMARY KEY (platform, item_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_media_author ON media_item(platform, author_id)",
    "CREATE INDEX IF NOT EXISTS idx_media_time ON media_item(last_download_time)",
    "CREATE INDEX IF NOT EXISTS idx_media_publish ON media_item(platform, publish_time)",
    """
    CREATE TABLE IF NOT EXISTS task (
        task_id      TEXT PRIMARY KEY,
        platform     TEXT,
        status       TEXT,                     -- pending | running | completed | failed
        total        INTEGER DEFAULT 0,
        succeeded    INTEGER DEFAULT 0,
        failed       INTEGER DEFAULT 0,
        started_at   INTEGER,
        finished_at  INTEGER,
        config_snapshot TEXT                   -- JSON snapshot of options
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_task_started ON task(started_at)",
    """
    CREATE TABLE IF NOT EXISTS increment_checkpoint (
        platform         TEXT NOT NULL,
        user_id          TEXT NOT NULL,
        mode             TEXT NOT NULL,
        last_item_id     TEXT,
        last_check_time  INTEGER,
        PRIMARY KEY (platform, user_id, mode)
    )
    """,
]


# ---------------------------------------------------------------------------
# Row dataclasses
# ---------------------------------------------------------------------------


@dataclass
class MediaItemRow:
    """DB-backed representation of a media item."""

    platform: str
    item_id: str
    title: Optional[str] = None
    author_id: Optional[str] = None
    author_name: Optional[str] = None
    cover_url: Optional[str] = None
    duration: Optional[float] = None
    publish_time: Optional[int] = None      # unix seconds
    media_type: Optional[str] = None
    payload: Optional[dict] = None
    last_download_time: Optional[int] = None
    last_save_dir: Optional[str] = None
    extra: Optional[dict] = None

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> "MediaItemRow":
        d = dict(row)
        # JSON columns back to dicts
        for k in ("payload", "extra"):
            v = d.get(k)
            if isinstance(v, str) and v:
                try:
                    d[k] = json.loads(v)
                except (ValueError, TypeError):
                    d[k] = None
            elif v is None or v == "":
                d[k] = None
        return cls(**d)


@dataclass
class TaskRow:
    task_id: str
    platform: Optional[str] = None
    status: str = "pending"
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    started_at: Optional[int] = None
    finished_at: Optional[int] = None
    config_snapshot: Optional[dict] = None


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------


class Database:
    """Async SQLite store for DouBi.

    Usage::

        async with Database("./doubi.db") as db:
            await db.record_download(item, "./path/to/save_dir")
            already = await db.is_downloaded("douyin", "7123456789012345678")

    Connections are opened lazily on first use; the same connection is
    reused for the lifetime of the instance. WAL mode is enabled for
    better concurrent read/write behavior.
    """

    def __init__(self, db_path: str | Path = "doubi.db"):
        self.db_path = Path(db_path)
        self._conn: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()

    # ---- context manager --------------------------------------------

    async def __aenter__(self) -> "Database":
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    # ---- lifecycle --------------------------------------------------

    async def initialize(self) -> None:
        """Open the connection, create tables, enable WAL."""
        if self._conn is not None:
            return
        async with self._lock:
            if self._conn is not None:
                return
            # Make sure the parent dir exists
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = await aiosqlite.connect(str(self.db_path))
            self._conn.row_factory = aiosqlite.Row
            # WAL is per-DB; safe to set on every open
            await self._conn.execute("PRAGMA journal_mode=WAL")
            await self._conn.execute("PRAGMA synchronous=NORMAL")
            for stmt in SCHEMA:
                await self._conn.execute(stmt)
            await self._conn.commit()
            logger.info("Database ready: %s", self.db_path)

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def _conn_required(self) -> aiosqlite.Connection:
        if self._conn is None:
            await self.initialize()
        assert self._conn is not None
        return self._conn

    # ---- media_item -------------------------------------------------

    async def is_downloaded(self, platform: str, item_id: str) -> bool:
        """True iff there's a media_item row for (platform, item_id)."""
        conn = await self._conn_required()
        async with conn.execute(
            "SELECT 1 FROM media_item WHERE platform = ? AND item_id = ? LIMIT 1",
            (platform, item_id),
        ) as cur:
            row = await cur.fetchone()
        return row is not None

    async def get_item(self, platform: str, item_id: str) -> Optional[MediaItemRow]:
        conn = await self._conn_required()
        async with conn.execute(
            "SELECT * FROM media_item WHERE platform = ? AND item_id = ?",
            (platform, item_id),
        ) as cur:
            row = await cur.fetchone()
        return MediaItemRow.from_row(row) if row else None

    async def record_download(
        self,
        *,
        platform: str,
        item_id: str,
        save_dir: str,
        title: Optional[str] = None,
        author_id: Optional[str] = None,
        author_name: Optional[str] = None,
        cover_url: Optional[str] = None,
        duration: Optional[float] = None,
        publish_time: Optional[int] = None,
        media_type: Optional[str] = None,
        payload: Optional[dict] = None,
        extra: Optional[dict] = None,
    ) -> None:
        """Upsert a media_item row. ``last_download_time`` is set to "now"."""
        conn = await self._conn_required()
        now = int(_time.time())
        await conn.execute(
            """
            INSERT INTO media_item
                (platform, item_id, title, author_id, author_name,
                 cover_url, duration, publish_time, media_type,
                 payload, last_download_time, last_save_dir, extra)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(platform, item_id) DO UPDATE SET
                title             = COALESCE(NULLIF(excluded.title, ''), media_item.title),
                author_id         = COALESCE(NULLIF(excluded.author_id, ''), media_item.author_id),
                author_name       = COALESCE(NULLIF(excluded.author_name, ''), media_item.author_name),
                cover_url         = COALESCE(NULLIF(excluded.cover_url, ''), media_item.cover_url),
                duration          = COALESCE(excluded.duration, media_item.duration),
                publish_time      = COALESCE(excluded.publish_time, media_item.publish_time),
                media_type        = COALESCE(NULLIF(excluded.media_type, ''), media_item.media_type),
                payload           = COALESCE(excluded.payload, media_item.payload),
                last_download_time = excluded.last_download_time,
                last_save_dir     = excluded.last_save_dir,
                extra             = COALESCE(excluded.extra, media_item.extra)
            """,
            (
                platform, item_id, title, author_id, author_name,
                cover_url, duration, publish_time, media_type,
                json.dumps(payload, ensure_ascii=False) if payload is not None else None,
                now, save_dir,
                json.dumps(extra, ensure_ascii=False) if extra is not None else None,
            ),
        )
        await conn.commit()

    async def delete_item(self, platform: str, item_id: str) -> bool:
        """Delete a media_item row. Returns True if a row was removed."""
        conn = await self._conn_required()
        async with conn.execute(
            "DELETE FROM media_item WHERE platform = ? AND item_id = ?",
            (platform, item_id),
        ) as cur:
            await conn.commit()
            return cur.rowcount > 0

    async def list_by_author(
        self, platform: str, author_id: str, *, limit: int = 100
    ) -> list[MediaItemRow]:
        conn = await self._conn_required()
        async with conn.execute(
            "SELECT * FROM media_item "
            "WHERE platform = ? AND author_id = ? "
            "ORDER BY last_download_time DESC LIMIT ?",
            (platform, author_id, limit),
        ) as cur:
            rows = await cur.fetchall()
        return [MediaItemRow.from_row(r) for r in rows]

    async def list_recent(self, *, limit: int = 200) -> list[MediaItemRow]:
        """Most recently downloaded items across all platforms."""
        conn = await self._conn_required()
        async with conn.execute(
            "SELECT * FROM media_item "
            "ORDER BY last_download_time DESC LIMIT ?",
            (max(1, int(limit)),),
        ) as cur:
            rows = await cur.fetchall()
        return [MediaItemRow.from_row(r) for r in rows]

    async def count(self) -> int:
        """Total number of recorded media items."""
        conn = await self._conn_required()
        async with conn.execute("SELECT COUNT(*) FROM media_item") as cur:
            row = await cur.fetchone()
        return int(row[0]) if row else 0

    # ---- task -------------------------------------------------------

    async def record_task(self, task: TaskRow) -> None:
        conn = await self._conn_required()
        await conn.execute(
            """
            INSERT INTO task
                (task_id, platform, status, total, succeeded, failed,
                 started_at, finished_at, config_snapshot)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                status        = excluded.status,
                total         = excluded.total,
                succeeded     = excluded.succeeded,
                failed        = excluded.failed,
                finished_at   = excluded.finished_at,
                config_snapshot = excluded.config_snapshot
            """,
            (
                task.task_id, task.platform, task.status,
                task.total, task.succeeded, task.failed,
                task.started_at, task.finished_at,
                json.dumps(task.config_snapshot, ensure_ascii=False)
                    if task.config_snapshot is not None else None,
            ),
        )
        await conn.commit()

    async def get_task(self, task_id: str) -> Optional[TaskRow]:
        conn = await self._conn_required()
        async with conn.execute(
            "SELECT * FROM task WHERE task_id = ?", (task_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        d = dict(row)
        snap = d.get("config_snapshot")
        if isinstance(snap, str) and snap:
            try:
                d["config_snapshot"] = json.loads(snap)
            except (ValueError, TypeError):
                d["config_snapshot"] = None
        return TaskRow(**d)

    # ---- increment_checkpoint ---------------------------------------

    async def get_checkpoint(
        self, platform: str, user_id: str, mode: str
    ) -> Optional[tuple[str, int]]:
        conn = await self._conn_required()
        async with conn.execute(
            "SELECT last_item_id, last_check_time FROM increment_checkpoint "
            "WHERE platform = ? AND user_id = ? AND mode = ?",
            (platform, user_id, mode),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        return row["last_item_id"], int(row["last_check_time"] or 0)

    async def set_checkpoint(
        self, platform: str, user_id: str, mode: str,
        last_item_id: str, last_check_time: Optional[int] = None,
    ) -> None:
        conn = await self._conn_required()
        ts = int(last_check_time or _time.time())
        await conn.execute(
            """
            INSERT INTO increment_checkpoint
                (platform, user_id, mode, last_item_id, last_check_time)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(platform, user_id, mode) DO UPDATE SET
                last_item_id    = excluded.last_item_id,
                last_check_time = excluded.last_check_time
            """,
            (platform, user_id, mode, last_item_id, ts),
        )
        await conn.commit()

    # ---- migration entry point --------------------------------------

    async def migrate_from_legacy(self, legacy_db_path: str | Path) -> int:
        """One-shot migration from a douyin-downloader ``dy_downloader.db``.

        Returns the number of rows written into ``media_item``. The
        legacy file is left untouched; the caller is expected to back
        it up before deleting.

        This method is intentionally self-contained: it opens its own
        connection to the legacy file, reads what's there, and writes
        into ``self``. See :mod:`core.storage.migrate` for the
        Bili23 / other source formats.
        """
        legacy = Path(legacy_db_path)
        if not legacy.exists():
            logger.warning("Legacy DB not found: %s", legacy)
            return 0

        # Local import to avoid a cycle (migrate imports models which
        # we don't need here; keep this method standalone).
        from .migrate import migrate_douyin_to_doubi
        return await migrate_douyin_to_doubi(legacy, self)
