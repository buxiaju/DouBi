"""Unified SQLite storage for DouBi.

The :class:`Database` class owns a single ``doubi.db`` file with three
tables:

* :sql:`media_item`        — one row per (platform, item_id), the
                             primary dedup table
* :sql:`task`              — batch job history (CLI / REST submit)
* :sql:`pending_task`      — unfinished GUI tasks, so a restart can
                             offer to resume them (M6.10)
* :sql:`increment_checkpoint` — per-user incremental-download cursor
                                (used by douyin's "increase" mode
                                and similar M5+ features)

A row in :sql:`media_item` is created on a successful download; the
``is_downloaded()`` check is the source of truth for skip-or-download
decisions, with the on-disk file presence used as a secondary check
(see :func:`core.storage.file_layout.already_downloaded_on_disk`).

Why :sql:`pending_task` is a new table rather than extra columns on
:sql:`task`:

Every statement in :data:`SCHEMA` is ``CREATE TABLE IF NOT EXISTS``
and there is no schema-version mechanism (``PRAGMA user_version`` is
unused; :mod:`core.storage.migrate` only imports *foreign* legacy
formats). On a database that already exists, adding a column to
:sql:`task` would therefore be **silently skipped**, and every
subsequent INSERT would fail with ``no such column``. A brand-new
table is created correctly on old and new files alike, which is the
whole reason this is not "just add a column".

The two tables also mean different things: :sql:`task` is an
aggregate history row (total / succeeded / failed) written when a
batch *ends*, while :sql:`pending_task` is live per-task state
written *while* it runs and deleted when it completes.

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
import sqlite3
import threading
import time as _time
from dataclasses import (
    dataclass,
    fields as dataclass_fields,
    is_dataclass,
    replace as dataclass_replace,
)
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import aiosqlite

logger = logging.getLogger("doubi.core.storage.database")

# The sentinel aiosqlite's worker thread recognises as "stop after this".
# Reclaiming an abandoned connection (see ``Database._discard_orphan``) has
# to bypass ``Connection.stop()``, so we need the sentinel itself to retire
# the worker thread. It is private, hence the guarded lookup: if a future
# aiosqlite renames it we still close the handle correctly and merely leave
# one idle thread parked on its queue, which is a leak of a thread rather
# than of a database.
_AIOSQLITE_STOP = getattr(aiosqlite.core, "_STOP_RUNNING_SENTINEL", object())

# How long a connection waits for a lock before giving up. Passed to
# aiosqlite.connect() as ``timeout``.
_BUSY_TIMEOUT_S = 5.0


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
    CREATE TABLE IF NOT EXISTS pending_task (
        task_id      TEXT PRIMARY KEY,           -- the GUI's own "T0001" id
        platform     TEXT NOT NULL,
        item_id      TEXT,
        title        TEXT,
        source_url   TEXT NOT NULL,              -- enough to re-parse from scratch
        status       TEXT NOT NULL,              -- queued | downloading | paused | failed
        fraction     REAL DEFAULT 0,
        message      TEXT,
        options_snapshot TEXT,                   -- JSON DownloadOptions (see _options_to_json)
        item_snapshot    TEXT,                   -- JSON MediaItem, avoids a re-parse round trip
        created_at   INTEGER,
        updated_at   INTEGER
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_pending_created ON pending_task(created_at)",
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


@dataclass
class PendingTaskRow:
    """One unfinished download, durable across process restarts.

    ``source_url`` is the only strictly required payload: with it alone
    a restart can re-parse and rebuild. ``item_snapshot`` is an
    optimization that lets the resume skip the network round trip, and
    ``options_snapshot`` preserves the per-task overrides the user
    chose, which are *not* recoverable from ``AppConfig``.
    """

    task_id: str
    platform: str
    source_url: str
    status: str = "queued"
    item_id: Optional[str] = None
    title: Optional[str] = None
    fraction: float = 0.0
    message: Optional[str] = None
    options_snapshot: Optional[dict] = None
    item_snapshot: Optional[dict] = None
    created_at: Optional[int] = None
    updated_at: Optional[int] = None

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> "PendingTaskRow":
        d = dict(row)
        for k in ("options_snapshot", "item_snapshot"):
            v = d.get(k)
            if isinstance(v, str) and v:
                try:
                    d[k] = json.loads(v)
                except (ValueError, TypeError):
                    d[k] = None
            else:
                d[k] = None
        d["fraction"] = float(d.get("fraction") or 0.0)
        return cls(**d)


# ---------------------------------------------------------------------------
# Snapshot (de)serialization
# ---------------------------------------------------------------------------
#
# ``DownloadOptions`` is deliberately not JSON-native: it carries ``Path``
# objects and a ``cancel_check`` *callable*. ``dataclasses.asdict()`` piped
# into ``json.dumps`` raises on both, so the conversion is explicit in both
# directions. Keeping it here (next to the table that stores the result)
# rather than on the model keeps ``core.models`` free of storage concerns.

#: Fields that must never be persisted. ``cancel_check`` is a live
#: callable bound to the *previous* process's stop flag -- restoring it
#: would either fail to serialize or, worse, resurrect a dead flag.
_OPTIONS_SKIP_FIELDS = frozenset({"cancel_check"})

# Which fields are ``Path``-typed and must be rebuilt as ``Path`` on the
# way back in. A plain ``str`` survives ``json.dumps`` but then breaks the
# first ``/`` join inside ``file_layout``.
#
# Computed from the dataclass annotations rather than hand-listed: a
# hand-written name list is exactly the kind of thing that silently rots
# when someone adds a new ``Path`` option -- the snapshot would round-trip
# that field as ``str`` and only blow up much later, deep inside path
# joining. ``test_storage`` pins the derived set against the real model so
# a rename cannot quietly slip through either.
def _path_typed_fields(cls: Any) -> frozenset[str]:
    names = set()
    for f in dataclass_fields(cls):
        # ``from __future__ import annotations`` makes ``f.type`` a
        # string here, so this is a substring test by necessity, not by
        # laziness -- ``typing.get_type_hints`` would need the defining
        # module's namespace and would import-cycle back into models.
        ann = f.type if isinstance(f.type, str) else str(f.type)
        if "Path" in ann:
            names.add(f.name)
    return frozenset(names)



def options_to_json(options: Any) -> dict:
    """Reduce a :class:`DownloadOptions` to a JSON-safe dict."""
    out: dict[str, Any] = {}
    for f in dataclass_fields(options):
        if f.name in _OPTIONS_SKIP_FIELDS:
            continue
        v = getattr(options, f.name)
        if isinstance(v, Path):
            out[f.name] = str(v)
        elif isinstance(v, (str, int, float, bool, type(None), list, dict)):
            out[f.name] = v
        else:
            # Enum or any other exotic value: fall back to its string
            # form rather than dropping the field silently.
            out[f.name] = getattr(v, "value", str(v))
    return out


def options_from_json(data: Optional[dict], base: Any) -> Any:
    """Rebuild a :class:`DownloadOptions` from :func:`options_to_json`.

    ``base`` supplies the defaults for anything the snapshot lacks --
    normally the surface's freshly-built options, so a snapshot written
    by an older version simply inherits today's values for new fields
    instead of raising ``TypeError: unexpected keyword argument``.
    """
    if not data:
        return base
    known = {f.name for f in dataclass_fields(base)}
    path_fields = _path_typed_fields(base)
    patch: dict[str, Any] = {}
    for k, v in data.items():
        if k not in known or k in _OPTIONS_SKIP_FIELDS:
            continue
        if k in path_fields:
            patch[k] = Path(v) if v is not None else None
        else:
            patch[k] = v
    return dataclass_replace(base, **patch)


# Fields deliberately NOT persisted in an item snapshot.
#
# ``streams`` holds resolved, often signed and short-lived media URLs. A
# snapshot exists precisely to be reloaded *later* -- possibly days later,
# in another process -- by which time those URLs have expired. Keeping them
# would make a restored task look ready while actually pointing at dead
# links. Nothing reads ``item.streams`` anywhere in this codebase; the
# yt-dlp engine downloads ``item.source_url``, so dropping them costs
# nothing and re-resolution happens naturally.
#
# ``children`` is excluded because a container is never a download target
# (``download_item`` refuses one outright); only expanded leaves reach
# TaskManager, so a persisted child list would be dead weight at best.
#
# ``output_template`` is excluded because the pipeline recomputes it from
# per-item metadata right before download. Freezing one version's rendering
# into the database would make a restored task ignore a template the user
# has since changed.
_ITEM_SKIP_FIELDS = frozenset({"streams", "children", "output_template"})


def item_to_json(item: Any) -> dict:
    """Serialize a :class:`MediaItem` down to what a restart really needs.

    Enough must survive to (a) hand the engine a URL and (b) land the file
    in the *same* directory as before -- ``resolve_save_dir`` renders the
    path from ``title`` / ``author`` / ``publish_time`` / ``extra``, so
    losing any of those would silently scatter a resumed download into a
    different folder and orphan its ``.part`` file.
    """
    out: dict[str, Any] = {}
    for f in dataclass_fields(item):
        if f.name in _ITEM_SKIP_FIELDS:
            continue
        v = getattr(item, f.name)
        if isinstance(v, Enum):
            out[f.name] = v.value
        elif isinstance(v, datetime):
            out[f.name] = v.isoformat()
        elif is_dataclass(v):
            out[f.name] = {
                sub.name: getattr(v, sub.name) for sub in dataclass_fields(v)
            }
        elif isinstance(v, (str, int, float, bool, type(None), list, dict)):
            out[f.name] = v
        else:
            out[f.name] = str(v)
    return out


def item_from_json(data: Optional[dict]) -> Any:
    """Rebuild a :class:`MediaItem` from :func:`item_to_json`.

    Imported lazily: :mod:`doubi.core.models` is the layer *above* storage,
    so a module-level import would close a cycle.

    Unknown keys are dropped rather than raising, mirroring
    :func:`options_from_json` -- a database written by a newer build must
    not crash an older one on startup, which is the one moment a user has
    no way to recover from an exception.
    """
    if not data:
        return None
    from ..models import Author, MediaItem, MediaType, Platform

    known = {f.name for f in dataclass_fields(MediaItem)}
    kwargs: dict[str, Any] = {}
    for k, v in data.items():
        if k not in known or k in _ITEM_SKIP_FIELDS:
            continue
        kwargs[k] = v

    kwargs["platform"] = Platform.from_str(str(kwargs.get("platform") or ""))
    raw_type = kwargs.get("media_type")
    try:
        kwargs["media_type"] = MediaType(raw_type) if raw_type else MediaType.VIDEO
    except ValueError:
        kwargs["media_type"] = MediaType.VIDEO

    author = kwargs.get("author")
    if isinstance(author, dict):
        fields_of = {f.name for f in dataclass_fields(Author)}
        kwargs["author"] = Author(
            **{k: v for k, v in author.items() if k in fields_of}
        )
    elif author is not None:
        kwargs.pop("author", None)

    published = kwargs.get("publish_time")
    if isinstance(published, str):
        try:
            kwargs["publish_time"] = datetime.fromisoformat(published)
        except ValueError:
            kwargs["publish_time"] = None

    kwargs.setdefault("item_id", "")
    kwargs.setdefault("title", "")
    return MediaItem(**kwargs)


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
            # ``timeout`` is the busy timeout, and it has to be passed to
            # connect() rather than set by a later PRAGMA: SQLite's default
            # is 0, so the very first statement of an overlapping open
            # would already have lost the race. The GUI's pending-row
            # bookkeeping opens a short-lived connection per state
            # transition, so overlap is the normal case here, not an edge
            # case -- and those writes are fire-and-forget with their
            # errors swallowed, meaning a lock collision would silently
            # lose a row that a restart needs.
            # Opening has to survive cancellation. ``aiosqlite.connect()``
            # is synchronous: it hands back a wrapper object, and only
            # awaiting that wrapper starts the worker thread which runs the
            # real ``sqlite3.connect``. Below, that await is a task we hold
            # a name for, shielded so a cancellation aimed at us does not
            # reach into it -- the open therefore finishes and the wrapper
            # legitimately owns a live handle.
            #
            # The leak is subtler than "the handle is lost": our own await
            # still raises, so the assignment below never happens and
            # nobody ever awaits the finished task again. The wrapper
            # simply becomes garbage while still holding its handle. When
            # the GC eventually reaps it, ``Connection.__del__`` warns
            # ("was deleted before being closed") and queues a stop onto
            # the loop that created it -- which by then is usually closed,
            # so aiosqlite's worker thread raises ``Event loop is closed``
            # from a thread nobody is watching, and the blame lands on
            # whatever code happens to be running at GC time.
            #
            # This is not a test-only hazard: the GUI cancels these very
            # tasks on exit (``MainWindow.closeEvent``), and every
            # pending-row write goes through ``TaskManager._run_db``, which
            # is cancellable by design.
            #
            # ``shield`` alone does *not* fix it -- it is what keeps the
            # open running, but it does nothing about the abandoned result.
            # Ownership is the missing half: if our await is interrupted,
            # go back for the result and close it before honouring the
            # cancellation.
            #
            # And ``shield`` does not even keep its own promise when the
            # *loop* is what shuts us down. A runner teardown cancels every
            # task in ``asyncio.all_tasks()``, and the inner task below is
            # on that list, so it is cancelled directly; ``shield`` only
            # severs cancellation arriving through our await. If that
            # happens before the connector reached the worker thread, the
            # worker still runs it afterwards and produces a live handle
            # that nothing owns: the cleanup path already ran and found
            # nothing to reclaim, aiosqlite's own cleanup found
            # ``_connection`` still ``None`` and closed nothing, and
            # ``Connection.__del__`` stays silent for the same reason. The
            # handle survives as a bare ``sqlite3`` object that only
            # CPython's finalizer ever mentions ("unclosed database").
            # Hence the abandonment flag below: giving up has to be
            # *declared*, so that a connector which has not run yet knows
            # not to open, and one already in flight knows to close.
            #
            # Nothing outside the worker thread can clean that up:
            # ``sqlite3`` rejects cross-thread use, and a close queued
            # behind the connector never runs, because the worker dies
            # first trying to deliver the result to a loop that has since
            # closed. The one reliable moment is the instant the handle is
            # created, on the thread creating it -- so the guard goes
            # inside the connector.
            #
            # Which means the open is driven by hand rather than by
            # ``await wrapper``. Awaiting the wrapper makes aiosqlite pair
            # the open with a future on *our* loop, and that pairing is the
            # second half of the problem: whatever the connector then
            # returns or raises, the worker tries to deliver it to a loop
            # that may be closed, and reports the resulting failure by
            # posting to the very same closed loop -- an unhandled thread
            # exception blamed on whoever happens to be running. Enqueueing
            # the open ourselves with an empty future slot is aiosqlite's
            # own "this call must not touch the loop" convention, so that
            # path becomes structurally impossible. Delivering the result
            # is then our job, and ours can be guarded.
            loop = asyncio.get_running_loop()
            landed: asyncio.Future[None] = loop.create_future()
            abandoned = False
            abandon_guard = threading.Lock()

            wrapper = aiosqlite.connect(str(self.db_path), timeout=_BUSY_TIMEOUT_S)
            open_raw = wrapper._connector

            def _settle() -> None:
                # Runs on the loop thread, so it is serialised against the
                # await below: either that await is still pending and we
                # hand the connection over, or it has already given up and
                # we are the last owner, in which case retirement goes back
                # to the worker thread -- the only thread allowed to close
                # this handle.
                if landed.done():
                    self._discard_orphan(wrapper)
                else:
                    landed.set_result(None)

            def _fail(exc: BaseException) -> None:
                if not landed.done():
                    landed.set_exception(exc)

            def _to_loop(fn: Any, *args: Any) -> bool:
                try:
                    loop.call_soon_threadsafe(fn, *args)
                except RuntimeError:
                    return False
                return True

            def _guarded_open() -> object:
                # Runs on aiosqlite's worker thread. The flag is checked
                # twice: before, so an open we have already given up on is
                # never performed at all, and after, because the
                # abandonment can be declared while ``sqlite3.connect`` is
                # still in flight. Both checks hold the lock, which is what
                # makes the outcome unambiguous for the caller below.
                #
                # Returning the stop sentinel retires the worker; returning
                # ``None`` leaves it running to serve the connection.
                with abandon_guard:
                    if abandoned:
                        return _AIOSQLITE_STOP
                try:
                    raw = open_raw()
                except BaseException as exc:
                    _to_loop(_fail, exc)
                    return _AIOSQLITE_STOP
                with abandon_guard:
                    if abandoned:
                        raw.close()
                        return _AIOSQLITE_STOP
                    # Published before the handover so that a caller who
                    # gives up between here and ``_settle`` still finds the
                    # handle to reclaim.
                    wrapper._connection = raw
                    if not _to_loop(_settle):
                        # The loop died without cancelling us -- nobody will
                        # ever take ownership, so close it while we are
                        # still on the thread permitted to do so.
                        wrapper._connection = None
                        raw.close()
                        return _AIOSQLITE_STOP
                return None

            wrapper._connector = _guarded_open
            wrapper._thread.start()
            wrapper._tx.put_nowait((None, _guarded_open))
            try:
                await landed
            except BaseException:
                with abandon_guard:
                    abandoned = True
                # Past this point the connector's decision is final: it
                # either has not published a handle yet and never will, or
                # it published one and left it for us.
                self._discard_orphan(wrapper)
                raise
            conn = wrapper
            try:
                conn.row_factory = aiosqlite.Row
                self._conn = conn
                await self._set_journal_mode_wal()
                await conn.execute("PRAGMA synchronous=NORMAL")
                for stmt in SCHEMA:
                    await conn.execute(stmt)
                await conn.commit()
            except BaseException:
                # Same leak, other cause: if any statement above fails or
                # is cancelled, ``__aenter__`` propagates and ``__aexit__``
                # never runs, so nothing would close what we just opened.
                # Shield the close too -- a cancellation arriving here must
                # not abandon the handle a second time.
                self._conn = None
                try:
                    await asyncio.shield(conn.close())
                except Exception as exc:  # pragma: no cover - defensive
                    logger.debug(
                        "discarding a half-open connection to %s failed: %s",
                        self.db_path,
                        exc,
                    )
                raise
            logger.info("Database ready: %s", self.db_path)

    @staticmethod
    def _discard_orphan(wrapper: aiosqlite.Connection) -> None:
        """Close a connection nobody is left to own.

        Deliberately synchronous. We are called while a cancellation is
        already in flight, and any ``await`` here would either re-raise it
        immediately or need shielding to dodge it -- both of which risk
        abandoning the very handle we are trying to reclaim.

        Two callers, one contract. Either the opener gave up and raised the
        abandonment flag first, or the handover arrived after it gave up. In
        both cases the guarded connector has already made its decision under
        the lock, so ``_connection`` answers the only question that matters:
        a handle is sitting there for us, or there never will be one. When
        there is none the worker thread also needs nothing from us -- it
        retires itself the moment it reads that flag.

        We queue the close onto aiosqlite's worker thread by hand rather than
        calling ``Connection.stop()``, because ``stop()`` pairs the request
        with a future created on the *current* loop. That loop is usually
        about to close -- shutdown is why we are here -- and by the time the
        worker runs the close, delivering the result to it raises
        ``Event loop is closed``. Worse, aiosqlite's worker reports that
        failure by posting to the same dead loop again, so the second raise
        escapes as an unhandled thread exception, blamed on whatever happens
        to be running at the time.

        aiosqlite's queue protocol is ``(future, function)`` and it guards
        every delivery with ``if future:``, so passing ``None`` closes the
        handle with no loop interaction whatsoever. Returning the stop
        sentinel also retires the worker thread. Clearing ``_connection`` is
        what keeps ``__del__`` quiet, and doing it here -- not in the worker
        -- means it is already true when this call returns, which is also
        what makes a second call a no-op.
        """
        try:
            raw = wrapper._connection
            wrapper._connection = None
            wrapper._running = False
            if raw is None:
                return

            def _close_and_stop() -> object:
                raw.close()
                return _AIOSQLITE_STOP

            wrapper._tx.put_nowait((None, _close_and_stop))
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("discarding an orphaned connection failed: %s", exc)

    async def _set_journal_mode_wal(self) -> None:
        """Switch the file to WAL, tolerating a concurrent opener.

        Journal mode is a property of the *file*, not of the connection,
        so it only has to be set once -- but switching it needs a brief
        exclusive lock, and that is the one operation the busy timeout
        does **not** cover: ``PRAGMA journal_mode`` fails immediately
        with "database is locked" rather than waiting. Two processes (or
        two of our own short-lived connections) opening the same fresh
        database at the same time will therefore race here.

        Losing that race is harmless: either the other opener already
        set WAL, or the file stays in the default rollback journal mode,
        which is slower under concurrency but perfectly correct. Failing
        the whole open over it would take down a download for the sake
        of a performance tweak.
        """
        assert self._conn is not None
        try:
            await self._conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError as exc:
            logger.debug("journal_mode=WAL skipped (%s): %s", self.db_path, exc)

    async def close(self) -> None:
        # The reference is dropped *before* the await, not after. Closing is
        # cancellable, but it is not abortable: ``Connection.close()`` queues
        # the real ``sqlite3.close`` onto the worker thread and clears its own
        # ``_connection`` in a ``finally``, so a cancellation passing through
        # our await does not call any of that back. The handle still gets
        # closed and the worker still retires -- measured, not assumed.
        #
        # What a cancellation *did* destroy was the ``self._conn = None`` that
        # used to sit after the await. That left this object pointing at a
        # corpse, and pointing at one permanently: ``initialize()`` returns
        # early while ``_conn is not None``, so it could never heal, and every
        # later query raised ``ValueError: no active connection`` forever.
        # Clearing first means a cancelled close is merely early, never fatal.
        conn = self._conn
        if conn is None:
            return
        self._conn = None
        await conn.close()

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

    # ---- pending_task (cross-process resume) ------------------------

    async def upsert_pending_task(self, row: PendingTaskRow) -> None:
        """Insert or refresh one unfinished task.

        Called on every meaningful state change, so it must stay cheap:
        a single upsert, no read-modify-write. ``created_at`` is
        preserved across updates (``COALESCE`` on the existing value) so
        the resume list can be ordered by original submission time.
        """
        conn = await self._conn_required()
        now = int(_time.time())
        await conn.execute(
            """
            INSERT INTO pending_task
                (task_id, platform, item_id, title, source_url, status,
                 fraction, message, options_snapshot, item_snapshot,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                platform     = excluded.platform,
                item_id      = excluded.item_id,
                title        = COALESCE(NULLIF(excluded.title, ''), pending_task.title),
                source_url   = excluded.source_url,
                status       = excluded.status,
                fraction     = excluded.fraction,
                message      = excluded.message,
                options_snapshot = COALESCE(excluded.options_snapshot,
                                            pending_task.options_snapshot),
                item_snapshot    = COALESCE(excluded.item_snapshot,
                                            pending_task.item_snapshot),
                created_at   = COALESCE(pending_task.created_at, excluded.created_at),
                updated_at   = excluded.updated_at
            """,
            (
                row.task_id, row.platform, row.item_id, row.title,
                row.source_url, row.status, float(row.fraction or 0.0), row.message,
                json.dumps(row.options_snapshot, ensure_ascii=False)
                    if row.options_snapshot is not None else None,
                json.dumps(row.item_snapshot, ensure_ascii=False)
                    if row.item_snapshot is not None else None,
                row.created_at or now, now,
            ),
        )
        await conn.commit()

    async def delete_pending_task(self, task_id: str) -> bool:
        """Forget a task. Called when it completes or the user removes it."""
        conn = await self._conn_required()
        async with conn.execute(
            "DELETE FROM pending_task WHERE task_id = ?", (task_id,)
        ) as cur:
            await conn.commit()
            return cur.rowcount > 0

    async def list_unfinished(self, *, limit: int = 500) -> list[PendingTaskRow]:
        """Every task that was still outstanding when we last exited.

        Ordered oldest-first so a restored queue keeps the order the
        user originally submitted in. Note that a row is only written
        for tasks that are *not* terminal, so no status filter is
        needed here -- completion deletes the row instead of updating
        it, which keeps the table small and makes "what's left?" a
        table scan of exactly the interesting rows.
        """
        conn = await self._conn_required()
        async with conn.execute(
            "SELECT * FROM pending_task ORDER BY created_at ASC, task_id ASC LIMIT ?",
            (max(1, int(limit)),),
        ) as cur:
            rows = await cur.fetchall()
        return [PendingTaskRow.from_row(r) for r in rows]

    async def clear_pending_tasks(self) -> int:
        """Drop all pending rows. Returns how many were removed."""
        conn = await self._conn_required()
        async with conn.execute("DELETE FROM pending_task") as cur:
            await conn.commit()
            return cur.rowcount

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
