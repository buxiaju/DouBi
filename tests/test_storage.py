"""Tests for M4: Database, file_layout, manifest, migration."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import sqlite3
import sys
import threading
from pathlib import Path

import aiosqlite
import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from doubi.core.models import (  # noqa: E402
    Author,
    DownloadOptions,
    MediaItem,
    MediaType,
    Platform,
    Stream,
)
from doubi.core.storage.database import (  # noqa: E402
    Database,
    MediaItemRow,
    PendingTaskRow,
    TaskRow,
    _path_typed_fields,
    item_from_json,
    item_to_json,
    options_from_json,
    options_to_json,
)
from doubi.core.storage.file_layout import (  # noqa: E402
    DEFAULT_DIR_TEMPLATE,
    already_downloaded_on_disk,
    render_dir,
    resolve_item_dir,
    resolve_save_dir,
)
from doubi.core.storage.manifest import (  # noqa: E402
    ManifestRecord,
    ManifestWriter,
)
from doubi.core.storage.migrate import migrate_douyin_to_doubi, migrate_bili23_to_doubi  # noqa: E402


# ---------------------------------------------------------------------------
# file_layout
# ---------------------------------------------------------------------------


def test_render_dir_default_template():
    item = MediaItem(
        platform=Platform.DOUYIN, item_id="7123456789012345678",
        title="测试视频", author=Author(name="张三"),
        publish_time=dt.datetime(2026, 1, 15),
        media_type=MediaType.VIDEO,
        source_url="https://www.douyin.com/video/7123456789012345678",
    )
    d = render_dir(item, DEFAULT_DIR_TEMPLATE)
    assert d == "douyin/张三/video"


def test_render_dir_bilibili():
    item = MediaItem(
        platform=Platform.BILIBILI, item_id="BV1xx",
        title="测试", author=Author(name="测试UP主"),
        publish_time=dt.datetime(2026, 3, 1),
        media_type=MediaType.VIDEO,
        source_url="https://www.bilibili.com/video/BV1xx",
    )
    d = render_dir(item, DEFAULT_DIR_TEMPLATE)
    assert d == "bilibili/测试UP主/video"


def test_render_dir_unknown_author_falls_back():
    item = MediaItem(
        platform=Platform.DOUYIN, item_id="1", title="t",
        author=Author(), media_type=MediaType.VIDEO, source_url="x",
    )
    d = render_dir(item, DEFAULT_DIR_TEMPLATE)
    assert "unknown_author" in d


def test_render_dir_sanitizes_illegal_chars_in_author():
    item = MediaItem(
        platform=Platform.DOUYIN, item_id="1", title="t",
        author=Author(name='a/b\\c:d?e"f'),
        media_type=MediaType.VIDEO, source_url="x",
    )
    d = render_dir(item, DEFAULT_DIR_TEMPLATE)
    # Split into path components and check each one
    parts = d.split("/")
    for part in parts:
        for ch in '<>:"\\|?*':
            assert ch not in part
    # The author name (sanitized) appears as a single component
    assert "a_b_c_d_e_f" in parts


def test_render_dir_custom_template():
    item = MediaItem(
        platform=Platform.DOUYIN, item_id="1", title="t",
        author=Author(name="张三"), media_type=MediaType.MIX,
        source_url="x", publish_time=dt.datetime(2026, 5, 1),
    )
    d = render_dir(item, "{platform}/{media_type}/{date}")
    assert d == "douyin/mix/2026-05"


def test_render_dir_preserves_unknown_tokens():
    item = MediaItem(platform=Platform.DOUYIN, item_id="1", title="t",
                     author=Author(name="张三"), media_type=MediaType.VIDEO,
                     source_url="x")
    d = render_dir(item, "{platform}/{nope}/{author}")
    assert "{nope}" in d


def test_render_dir_no_publish_time_uses_0000():
    item = MediaItem(platform=Platform.DOUYIN, item_id="1", title="t",
                     author=Author(name="张三"), media_type=MediaType.VIDEO,
                     source_url="x", publish_time=None)
    d = render_dir(item, DEFAULT_DIR_TEMPLATE)
    # author and media_type still resolve; no date component in default
    assert d == "douyin/张三/video"


def test_resolve_save_dir_returns_path(tmp_path):
    """resolve_save_dir returns the path; leaf creation is the engine's job."""
    item = MediaItem(platform=Platform.DOUYIN, item_id="1", title="t",
                     author=Author(name="张三"), media_type=MediaType.VIDEO,
                     source_url="x", publish_time=dt.datetime(2026, 1, 1))
    options = DownloadOptions(output_root=tmp_path)
    save_dir = resolve_save_dir(item, options)
    rel = str(save_dir.relative_to(tmp_path)).replace("\\", "/")
    assert rel == "douyin/张三/video"
    # root should exist (mkdir(parents=True))
    assert tmp_path.exists()


def test_resolve_item_dir_standalone_no_leaf_subdir(tmp_path):
    """Standalone videos do NOT create a title-named subdir.

    Historically we used to nest under ``{video_title}/``, but that
    duplicated the title already present in the ``{title}_{id}``
    basename and routinely blew past MAX_PATH on Windows for long
    YouTube titles.  See ``Errno 2 "No such file or directory"``.
    """
    item = MediaItem(platform=Platform.DOUYIN, item_id="1", title="t",
                     author=Author(name="张三"), media_type=MediaType.VIDEO,
                     source_url="x", publish_time=dt.datetime(2026, 1, 15))
    options = DownloadOptions(output_root=tmp_path)
    item_dir = resolve_item_dir(item, options)
    assert item_dir.exists()
    # For standalone items the "item dir" IS the shared save_dir.
    assert item_dir == resolve_save_dir(item, options)
    assert item_dir.name == "video"


def test_resolve_item_dir_collection_episodes_share_one_folder(tmp_path):
    """All episodes of a collection land in a single folder named after it."""
    options = DownloadOptions(output_root=tmp_path)

    def _episode(item_id: str, title: str) -> MediaItem:
        return MediaItem(
            platform=Platform.BILIBILI, item_id=item_id, title=title,
            author=Author(name="UP主"), media_type=MediaType.VIDEO,
            source_url="https://www.bilibili.com/video/BV1",
            extra={"collection_title": "鸿蒙开发教程"},
        )

    d1 = resolve_item_dir(_episode("BV1_p1", "第1集 入门"), options)
    d2 = resolve_item_dir(_episode("BV1_p2", "第2集 进阶"), options)
    assert d1 == d2
    assert d1.name == "鸿蒙开发教程"


def test_resolve_item_dir_sanitizes_illegal_chars_in_collection_leaf(tmp_path):
    """Collection dir name (not standalone) must still be sanitised."""
    item = MediaItem(
        platform=Platform.BILIBILI, item_id="1",
        title='ep title', author=Author(name="UP主"),
        media_type=MediaType.VIDEO, source_url="x",
        extra={"collection_title": 'a/b:c*d?e'},   # illegal chars in COLLECTION
    )
    options = DownloadOptions(output_root=tmp_path)
    item_dir = resolve_item_dir(item, options)
    assert item_dir.exists()
    # The shared collection dir is what carries the sanitised name; the
    # standalone case deliberately uses no title leaf dir at all.
    assert item_dir.name == "a_b_c_d_e"
    assert item_dir.parent.name == "video"


def test_already_downloaded_on_disk_basename_scopes_shared_folder(tmp_path):
    """In a shared collection folder, ep1's file must not mask ep2."""
    d = tmp_path / "collection"
    d.mkdir()
    (d / "第1集_BV1_p1.mp4").write_bytes(b"x")
    assert already_downloaded_on_disk(d, "第1集_BV1_p1") is True
    assert already_downloaded_on_disk(d, "第2集_BV1_p2") is False
    # without a basename it degrades to "any file present"
    assert already_downloaded_on_disk(d) is True


def test_resolve_item_dir_categorised_collection_nests_section(tmp_path):
    """A ugc_season with categories nests 合集名/分类名/分集名."""
    options = DownloadOptions(output_root=tmp_path)

    def _episode(item_id: str, title: str, section: str) -> MediaItem:
        return MediaItem(
            platform=Platform.BILIBILI, item_id=item_id, title=title,
            author=Author(name="UP主"), media_type=MediaType.VIDEO,
            source_url=f"https://www.bilibili.com/video/{item_id}",
            extra={"collection_title": "高分必备660！", "section_title": section},
        )

    d1 = resolve_item_dir(_episode("BV1", "1-2章", "模拟电子技术"), options)
    d2 = resolve_item_dir(_episode("BV2", "3-5章", "模拟电子技术"), options)
    d3 = resolve_item_dir(_episode("BV3", "第3章", "信号与系统"), options)

    # Each episode gets its own folder ...
    assert d1 != d2
    # ... but siblings of the same category share the category folder.
    assert d1.parent == d2.parent
    assert d1.parent.name == "模拟电子技术"
    assert d1.name == "1-2章"
    # ... and all categories live under one collection folder.
    assert d1.parent.parent == d3.parent.parent
    assert d1.parent.parent.name == "高分必备660！"
    assert d3.parent.name == "信号与系统"
    assert d1.parent.parent.parent == resolve_save_dir(
        _episode("BV1", "1-2章", "模拟电子技术"), options
    )
    for d in (d1, d2, d3):
        assert d.exists()


def test_resolve_item_dir_page_row_nests_under_episode(tmp_path):
    """A 分P page inside a categorised episode nests as
    合集名/分类名/分集名/Px. Episode title comes from
    ``extra['episode_title']`` so the file_layout layer can build the
    3-level path even when the page row's own ``title`` is just ``Px``.
    """
    from doubi.core.storage.file_layout import episode_title_of, item_leaf_parts
    item = MediaItem(platform=Platform.BILIBILI, item_id="BV1oxdwBBE3B#p3",
                     title="3-1", author=Author(name="UP"), media_type=MediaType.VIDEO,
                     source_url="x",
                     extra={
                         "collection_title": "高分必备660！",
                         "section_title": "模拟电子技术",
                         "episode_title": "1-2章",
                     })
    assert episode_title_of(item) == "1-2章"
    assert item_leaf_parts(item) == ["高分必备660！", "模拟电子技术", "1-2章", "3-1"]

    options = DownloadOptions(output_root=tmp_path)
    item_dir = resolve_item_dir(item, options)
    rel = item_dir.relative_to(tmp_path).parts
    assert rel[-4:] == ("高分必备660！", "模拟电子技术", "1-2章", "3-1")


def test_resolve_item_dir_blank_section_falls_back_to_flat_collection(tmp_path):
    """An empty section_title must not create an empty directory level."""
    options = DownloadOptions(output_root=tmp_path)
    item = MediaItem(
        platform=Platform.BILIBILI, item_id="BV1", title="第1集",
        author=Author(name="UP主"), media_type=MediaType.VIDEO,
        source_url="x",
        extra={"collection_title": "鸿蒙开发教程", "section_title": "   "},
    )
    item_dir = resolve_item_dir(item, options)
    assert item_dir.name == "鸿蒙开发教程"
    assert item_dir.parent == resolve_save_dir(item, options)


def test_already_downloaded_on_disk_matches_part_suffixed_files(tmp_path):
    """The engine's ``_P007`` per-part suffix still counts as this item."""
    d = tmp_path / "episode"
    d.mkdir()
    (d / "第1集_BV1_P003.mp4").write_bytes(b"x")
    assert already_downloaded_on_disk(d, "第1集_BV1") is True
    assert already_downloaded_on_disk(d, "第2集_BV2") is False


def test_already_downloaded_on_disk(tmp_path):
    d = tmp_path / "fake"
    assert already_downloaded_on_disk(d) is False
    d.mkdir()
    assert already_downloaded_on_disk(d) is False  # empty
    (d / "video.mp4").write_bytes(b"x")
    assert already_downloaded_on_disk(d) is True
    # hidden file alone doesn't count
    d2 = tmp_path / "h"
    d2.mkdir()
    (d2 / ".hidden").write_text("h")
    assert already_downloaded_on_disk(d2) is False


# ---------------------------------------------------------------------------
# manifest
# ---------------------------------------------------------------------------


def test_manifest_record_round_trip(tmp_path):
    item = MediaItem(platform=Platform.DOUYIN, item_id="1", title="t",
                     author=Author(name="张三"), media_type=MediaType.VIDEO,
                     publish_time=dt.datetime(2026, 1, 15),
                     cover_url="https://x/cover.jpg",
                     duration=120.0, source_url="x",
                     extra={"tags": ["a", "b"], "view_count": 100, "ignore": "x"})
    rec = ManifestRecord(
        platform="douyin", item_id="1", title="t",
        author_id="", author_name="张三",
        media_type="video", date="2026-01-15",
        tags=["a", "b"], view_count=100, duration=120.0,
        cover_url="https://x/cover.jpg", publish_timestamp=1736899200,
        file_names=["a.mp4"], file_paths=["douyin/张三/video/a.mp4"],
        download_time=1736899300,
    )
    j = rec.to_json()
    # tags / view_count survived; "ignore" not in extra
    d = json.loads(j)
    assert d["tags"] == ["a", "b"]
    assert d["view_count"] == 100
    assert "ignore" not in d["extra"]


def test_manifest_writer_appends(tmp_path):
    p = tmp_path / "manifest.jsonl"
    mw = ManifestWriter(p)
    item1 = MediaItem(platform=Platform.DOUYIN, item_id="1", title="v1",
                      author=Author(name="张三"), media_type=MediaType.VIDEO,
                      source_url="x", publish_time=dt.datetime(2026, 1, 1))
    item2 = MediaItem(platform=Platform.BILIBILI, item_id="BV1", title="v2",
                      author=Author(name="测试UP主"), media_type=MediaType.VIDEO,
                      source_url="x", publish_time=dt.datetime(2026, 2, 1))
    mw.record(item1, file_names=["a.mp4"], file_paths=["douyin/张三/video/a.mp4"])
    mw.record(item2, file_names=["b.mp4"], file_paths=["bilibili/测试UP主/video/b.mp4"])
    records = mw.read_all()
    assert len(records) == 2
    assert records[0]["platform"] == "douyin"
    assert records[1]["platform"] == "bilibili"
    assert records[1]["author_name"] == "测试UP主"


def test_manifest_writer_preserves_previous_content(tmp_path):
    """Sanity check: after a successful record(), previous content is intact."""
    p = tmp_path / "manifest.jsonl"
    p.write_text('{"first": 1}\n', encoding="utf-8")
    mw = ManifestWriter(p)
    item = MediaItem(platform=Platform.DOUYIN, item_id="2", title="t",
                     author=Author(), media_type=MediaType.VIDEO, source_url="x")
    mw.record(item, file_names=["a.mp4"], file_paths=["x/a.mp4"])
    content = p.read_text(encoding="utf-8")
    assert content.startswith('{"first": 1}\n')
    assert '"platform":"douyin"' in content


def test_manifest_writer_touches_file_on_init(tmp_path):
    p = tmp_path / "manifest.jsonl"
    assert not p.exists()
    ManifestWriter(p)
    assert p.exists()
    assert p.stat().st_size == 0


# ---------------------------------------------------------------------------
# database
# ---------------------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test.db"


@pytest.mark.asyncio
async def test_database_init_creates_tables(db_path):
    async with Database(db_path) as db:
        # Query sqlite_master for table list
        conn = await db._conn_required()
        async with conn.execute("SELECT name FROM sqlite_master WHERE type='table'") as cur:
            rows = await cur.fetchall()
        names = {r[0] for r in rows}
        assert "media_item" in names
        assert "task" in names
        assert "increment_checkpoint" in names


class _SelfReportingConnection(sqlite3.Connection):
    """A raw handle that records whether it was ever closed.

    Kept for diagnostics only -- see the test for why ``was_closed`` cannot
    be the assertion. sqlite3 has no ``closed`` flag, and its cross-thread
    guard fires *before* its closed check, so probing a handle created on
    aiosqlite's worker thread can never observe closedness from here.
    """

    was_closed = False

    def close(self) -> None:
        self.was_closed = True
        super().close()


@pytest.mark.asyncio
async def test_cancelling_an_open_does_not_orphan_the_connection(db_path, monkeypatch):
    """Cancelling ``initialize()`` mid-connect must not leak a handle.

    aiosqlite opens the file on a worker thread, and ``initialize()`` shields
    that open so a cancellation aimed at it does not abort a half-created
    database. The open therefore completes -- but our await already raised,
    so nothing ever collects the result and the wrapper becomes garbage
    while still holding a live handle. When the GC reaps it, aiosqlite
    queues a stop onto the event loop that created it, which by then is
    typically closed, and its worker thread raises ``Event loop is closed``
    where no one is listening.

    The GUI cancels exactly these tasks on exit, so this is a real leak and
    not a test artefact.

    Picking the right thing to assert on took some doing, so it is worth
    recording what does *not* work:

    * ``db._conn`` is ``None`` either way -- a cancelled open correctly
      yields no usable database -- so it says nothing about the leak.
    * Whether the raw handle got closed is also useless, because the GC
      closes it too: aiosqlite's ``__del__`` calls ``stop()``, which queues
      the close onto its worker thread. "It got closed eventually" is true
      of the broken code as well.

    What actually separates the two is *who* closed it, and the cleanest
    proxy is the aiosqlite wrapper's own ``_connection`` attribute: an
    orderly teardown clears it, and that is exactly what stops ``__del__``
    from complaining. A leaked wrapper still has a handle hanging off it.

    (Asserting on a ``ResourceWarning`` after ``gc.collect()`` looks
    tempting but does not work here: ``pytest.raises`` holds the
    ``CancelledError``, whose traceback keeps the ``initialize`` frame --
    and therefore the wrapper -- alive, so nothing is ever collected.)
    """
    opened: list[_SelfReportingConnection] = []
    real_connect = sqlite3.connect

    def _tracking_connect(*args, **kwargs):
        kwargs["factory"] = _SelfReportingConnection
        conn = real_connect(*args, **kwargs)
        opened.append(conn)
        return conn

    monkeypatch.setattr(sqlite3, "connect", _tracking_connect)

    wrappers: list[aiosqlite.Connection] = []
    real_aioconnect = aiosqlite.connect

    def _tracking_aioconnect(*args, **kwargs):
        wrapper = real_aioconnect(*args, **kwargs)
        wrappers.append(wrapper)
        return wrapper

    monkeypatch.setattr(aiosqlite, "connect", _tracking_aioconnect)

    db = Database(db_path)
    task = asyncio.ensure_future(db.initialize())
    await asyncio.sleep(0)  # let the connect reach the worker thread
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # The open was already in flight, so the worker thread completes it
    # regardless; wait for the handle to actually show up.
    for _ in range(100):
        if opened:
            break
        await asyncio.sleep(0.01)

    assert db._conn is None, "a cancelled open must not leave a usable connection"
    assert wrappers, "expected initialize() to have started an open"

    # Teardown is queued onto the worker thread, so give it a moment.
    for _ in range(100):
        if all(w._connection is None for w in wrappers):
            break
        await asyncio.sleep(0.01)

    leaked = [w for w in wrappers if w._connection is not None]
    assert not leaked, (
        f"{len(leaked)} connection(s) were abandoned still holding a live "
        "sqlite3 handle: nothing will close them until the GC intervenes, "
        "which is where the 'Event loop is closed' noise comes from"
    )

    # And the database is still perfectly usable afterwards.
    monkeypatch.setattr(sqlite3, "connect", real_connect)
    async with Database(db_path) as db2:
        conn = await db2._conn_required()
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ) as cur:
            rows = await cur.fetchall()
        assert "media_item" in {r[0] for r in rows}


@pytest.mark.asyncio
async def test_a_cancelled_close_does_not_poison_the_database(db_path):
    """A cancelled ``close()`` must leave the object reusable, not bricked.

    Closing is cancellable but not abortable. ``aiosqlite.Connection.close()``
    hands the real ``sqlite3.close`` to its worker thread and clears its own
    ``_connection`` in a ``finally``, so a cancellation arriving at our await
    cannot call any of that back: the handle is closed and the worker retires
    either way. That is why this test does *not* look for a leaked handle --
    there isn't one, in either ordering of the race.

    The damage was subtler and strictly worse than an error. ``self._conn``
    used to be cleared *after* the await, so a cancellation skipped it and left
    this object holding a reference to a connection that was already dead. And
    it could never recover: ``initialize()`` returns early while ``_conn is not
    None``, so re-opening was a silent no-op and every subsequent query raised
    ``ValueError: no active connection`` -- for the rest of the object's life.

    The assertion therefore has to be about *reuse*, because that is the only
    place the poisoning is observable. Checking the handle, the worker thread,
    or warnings would pass just as happily before the fix as after it.
    """
    db = Database(db_path)
    await db.initialize()

    task = asyncio.ensure_future(db.close())
    await asyncio.sleep(0)  # started, but nowhere near finished
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert db._conn is None, (
        "a cancelled close left the object pointing at a connection that is "
        "already being torn down"
    )

    # The real proof: the object heals. Before the fix this re-open was a
    # no-op and the query below raised ValueError instead.
    await db.initialize()
    assert await db.count() == 0

    await db.close()
    assert db._conn is None


@pytest.mark.asyncio
async def test_a_handle_born_after_the_cancellation_is_still_closed(
    db_path, monkeypatch
):
    """The nastier half of the same leak: the handle is created *after* we quit.

    The test above cancels an open that has already produced a handle. This
    one pins down the opposite order, which is the one that actually escaped
    into production: the cancellation lands first, and only then does
    aiosqlite's worker thread get around to calling ``sqlite3.connect``.

    That order is not exotic -- it is what a loop shutdown produces. A runner
    teardown cancels *every* task in ``asyncio.all_tasks()``, so an
    ``asyncio.shield`` around the open buys nothing: the shielded task is on
    that list too and is cancelled directly. Meanwhile the connector is still
    sitting in aiosqlite's queue, and the worker thread will happily run it
    afterwards.

    What made it invisible is that every layer had a reason to stay quiet.
    aiosqlite's own cleanup guards its close with
    ``if self._connection is not None`` -- and at that moment it is still
    ``None``, so it closes nothing. ``Connection.__del__`` returns early for
    exactly the same reason, so not even a ``ResourceWarning`` is emitted. A
    close queued behind the connector never runs either, because the worker
    dies first trying to deliver the result to a loop that has since closed.
    The only trace left is CPython's own "unclosed database".

    Nothing outside that worker thread can fix it -- ``sqlite3`` rejects
    cross-thread use, and its cross-thread check fires *before* its closed
    check, so we cannot even ask. Hence the assertion here is again the
    wrapper's ``_connection``, and hence the fix has to live inside the
    connector itself.

    The ordering is forced rather than raced: the connector is held *inside*
    ``sqlite3.connect`` until the cancellation has fully landed, and we wait
    for it to actually get there before cancelling -- otherwise the abandoned
    flag could be raised while the connector is still sitting in the queue,
    which is a different (and much easier) branch.
    """
    entered = threading.Event()
    gate = threading.Event()
    opened: list[sqlite3.Connection] = []
    real_connect = sqlite3.connect

    def _gated_connect(*args, **kwargs):
        # Runs on aiosqlite's worker thread. Blocking here is what makes the
        # cancellation win the race deterministically.
        entered.set()
        gate.wait(5.0)
        conn = real_connect(*args, **kwargs)
        opened.append(conn)
        return conn

    monkeypatch.setattr(sqlite3, "connect", _gated_connect)

    wrappers: list[aiosqlite.Connection] = []
    real_aioconnect = aiosqlite.connect

    def _tracking_aioconnect(*args, **kwargs):
        wrapper = real_aioconnect(*args, **kwargs)
        wrappers.append(wrapper)
        return wrapper

    monkeypatch.setattr(aiosqlite, "connect", _tracking_aioconnect)

    db = Database(db_path)
    task = asyncio.ensure_future(db.initialize())
    for _ in range(500):
        if entered.is_set():
            break
        await asyncio.sleep(0.01)
    assert entered.is_set(), "the open never reached the worker thread"

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert wrappers, "expected initialize() to have started an open"
    assert not opened, "the gate should still be holding the open"

    # Only now let the worker thread proceed. Everything it does from here
    # happens with no one waiting for it -- which is the whole point.
    gate.set()

    for _ in range(100):
        if all(w._connection is None for w in wrappers) and not any(
            w._thread.is_alive() for w in wrappers
        ):
            break
        await asyncio.sleep(0.01)

    assert db._conn is None, "a cancelled open must not leave a usable connection"

    leaked = [w for w in wrappers if w._connection is not None]
    assert not leaked, (
        f"{len(leaked)} connection(s) opened after the cancellation were left "
        "holding a live sqlite3 handle that nothing will ever close: not "
        "aiosqlite's cleanup, not __del__, only CPython's finalizer "
        "complaining about an 'unclosed database'"
    )

    for wrapper in wrappers:
        assert not wrapper._thread.is_alive(), (
            "the worker thread outlived the open it was created for"
        )

    # And the database is still perfectly usable afterwards.
    monkeypatch.setattr(sqlite3, "connect", real_connect)
    async with Database(db_path) as db2:
        conn = await db2._conn_required()
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ) as cur:
            rows = await cur.fetchall()
        assert "media_item" in {r[0] for r in rows}


@pytest.mark.asyncio
async def test_database_record_and_query_download(db_path):
    async with Database(db_path) as db:
        await db.record_download(
            platform="douyin", item_id="abc",
            save_dir="douyin/张三/video/2026-01-01_标题_abc",
            title="标题", author_id="MS4w", author_name="张三",
            cover_url="https://x/c.jpg", duration=120.0,
            publish_time=1735689600, media_type="video",
        )
        assert await db.is_downloaded("douyin", "abc") is True
        assert await db.is_downloaded("douyin", "missing") is False
        assert await db.is_downloaded("bilibili", "abc") is False

        row = await db.get_item("douyin", "abc")
        assert row is not None
        assert row.title == "标题"
        assert row.author_name == "张三"
        assert row.last_save_dir == "douyin/张三/video/2026-01-01_标题_abc"


@pytest.mark.asyncio
async def test_database_record_upsert_preserves_missing_fields(db_path):
    async with Database(db_path) as db:
        # First record: full
        await db.record_download(
            platform="douyin", item_id="abc", save_dir="x",
            title="标题", author_name="张三",
        )
        # Second record: partial — should NOT clobber title/author_name
        await db.record_download(platform="douyin", item_id="abc", save_dir="y")
        row = await db.get_item("douyin", "abc")
        assert row is not None
        assert row.title == "标题"
        assert row.author_name == "张三"
        assert row.last_save_dir == "y"  # this is overwritten


@pytest.mark.asyncio
async def test_database_delete_item(db_path):
    async with Database(db_path) as db:
        await db.record_download(platform="douyin", item_id="abc", save_dir="x")
        assert await db.is_downloaded("douyin", "abc") is True
        removed = await db.delete_item("douyin", "abc")
        assert removed is True
        assert await db.is_downloaded("douyin", "abc") is False
        # Deleting again returns False
        assert await db.delete_item("douyin", "abc") is False


@pytest.mark.asyncio
async def test_database_list_by_author(db_path):
    async with Database(db_path) as db:
        for i in range(3):
            await db.record_download(
                platform="douyin", item_id=str(i), save_dir="x",
                author_id="A1", author_name="张三",
            )
        await db.record_download(
            platform="douyin", item_id="other", save_dir="x",
            author_id="B2", author_name="其他",
        )
        rows = await db.list_by_author("douyin", "A1")
        assert len(rows) == 3
        assert all(r.author_name == "张三" for r in rows)


@pytest.mark.asyncio
async def test_database_list_recent_and_count(db_path):
    async with Database(db_path) as db:
        assert await db.count() == 0
        for i in range(5):
            await db.record_download(
                platform="douyin" if i % 2 == 0 else "bilibili",
                item_id=f"id{i}", save_dir=f"dir{i}",
                title=f"标题{i}",
            )
        assert await db.count() == 5
        recent = await db.list_recent(limit=3)
        assert len(recent) == 3
        # Sorted newest-first (last inserted has the newest timestamp;
        # timestamps can be equal within the same second, so just check
        # the count and that all rows come from the set we inserted)
        assert {r.item_id for r in recent} <= {f"id{i}" for i in range(5)}
        # limit=0 is clamped to >= 1
        one = await db.list_recent(limit=0)
        assert len(one) == 1


@pytest.mark.asyncio
async def test_database_task_record_and_get(db_path):
    async with Database(db_path) as db:
        await db.record_task(TaskRow(
            task_id="t1", platform="douyin", status="completed",
            total=10, succeeded=8, failed=2,
            started_at=1735689600, finished_at=1735689700,
            config_snapshot={"foo": "bar"},
        ))
        t = await db.get_task("t1")
        assert t is not None
        assert t.status == "completed"
        assert t.total == 10
        assert t.succeeded == 8
        assert t.config_snapshot == {"foo": "bar"}


@pytest.mark.asyncio
async def test_database_checkpoint(db_path):
    async with Database(db_path) as db:
        cp = await db.get_checkpoint("douyin", "user1", "post")
        assert cp is None
        await db.set_checkpoint("douyin", "user1", "post", "last_aweme", 1735689600)
        cp = await db.get_checkpoint("douyin", "user1", "post")
        assert cp == ("last_aweme", 1735689600)
        # Overwrite
        await db.set_checkpoint("douyin", "user1", "post", "newer", 1735689700)
        cp = await db.get_checkpoint("douyin", "user1", "post")
        assert cp == ("newer", 1735689700)


# ---------------------------------------------------------------------------
# pending_task (cross-process resume)
# ---------------------------------------------------------------------------


def _path_fields_via_typing() -> set[str]:
    """Independent oracle for :func:`_path_typed_fields`.

    Deliberately uses a *different* mechanism (resolved type hints) than
    the implementation (annotation substring match). If the two ever
    disagree, the cheap heuristic has drifted from reality.
    """
    import typing

    hints = typing.get_type_hints(DownloadOptions)
    out = set()
    for name, hint in hints.items():
        if hint is Path or Path in typing.get_args(hint):
            out.add(name)
    return out


def test_path_typed_fields_matches_the_real_model():
    derived = set(_path_typed_fields(DownloadOptions))
    assert derived == _path_fields_via_typing()
    # Pinned explicitly too: adding a new Path option must break this and
    # force a look at the snapshot round trip.
    assert derived == {"output_root", "cookies_file", "database", "manifest"}


def test_options_snapshot_round_trip():
    opts = DownloadOptions(
        output_root=Path("D:/dl"),
        cookies_file=Path("cookies.txt"),
        max_quality="1080p",
        write_nfo=True,
        rate_limit="2M",
        cancel_check=lambda: True,
    )
    data = options_to_json(opts)

    # Must survive real serialization, not just look plausible.
    json.dumps(data)

    # The live callable is bound to *this* process's stop flag; persisting
    # it would either fail or resurrect a dead flag after restart.
    assert "cancel_check" not in data
    assert isinstance(data["output_root"], str)

    back = options_from_json(data, DownloadOptions(output_root=Path(".")))
    assert isinstance(back.output_root, Path)
    assert back.output_root == Path("D:/dl")
    assert isinstance(back.cookies_file, Path)
    assert back.max_quality == "1080p"
    assert back.write_nfo is True
    assert back.rate_limit == "2M"
    assert back.cancel_check is None


def test_options_from_json_tolerates_stale_and_unknown_keys():
    base = DownloadOptions(output_root=Path("/base"), max_quality="720p")
    # A snapshot written by another version: one field we no longer have,
    # and one we do. The unknown key must not raise.
    restored = options_from_json({"nope_removed": 1, "max_quality": "4k"}, base)
    assert restored.max_quality == "4k"
    assert restored.output_root == Path("/base")
    # Missing fields fall back to the caller's freshly built options.
    assert restored.container == base.container


def test_options_from_json_empty_returns_base():
    base = DownloadOptions(output_root=Path("/base"))
    assert options_from_json(None, base) is base
    assert options_from_json({}, base) is base


def test_options_from_json_keeps_none_paths_none():
    data = options_to_json(DownloadOptions(output_root=Path("/o")))
    assert data["cookies_file"] is None
    back = options_from_json(data, DownloadOptions(output_root=Path(".")))
    assert back.cookies_file is None


def _snapshot_item() -> MediaItem:
    return MediaItem(
        platform=Platform.BILIBILI,
        item_id="BV1xx",
        title="标题/带非法字符",
        author=Author(id="u9", name="UP主"),
        publish_time=dt.datetime(2024, 5, 6, 7, 8, 9),
        media_type=MediaType.VIDEO,
        source_url="https://example.com/BV1xx",
        streams=[
            Stream(
                stream_id="s1",
                kind="video",
                url="https://signed.example/expires-soon",
            )
        ],
        extra={"collection_title": "Season 1"},
    )


def test_item_snapshot_round_trip():
    data = item_to_json(_snapshot_item())

    # Must survive real serialization, not merely look plausible.
    json.dumps(data)

    back = item_from_json(data)
    assert isinstance(back.platform, Platform) and back.platform is Platform.BILIBILI
    assert isinstance(back.media_type, MediaType) and back.media_type is MediaType.VIDEO
    assert back.publish_time == dt.datetime(2024, 5, 6, 7, 8, 9)
    assert isinstance(back.author, Author) and back.author.name == "UP主"
    assert back.source_url == "https://example.com/BV1xx"
    assert back.extra == {"collection_title": "Season 1"}


def test_item_snapshot_drops_expiring_streams():
    data = item_to_json(_snapshot_item())
    # Stream URLs are signed and short-lived; a snapshot is reloaded *later*,
    # so persisting them would restore a task pointing at dead links. Nothing
    # in the codebase reads item.streams -- source_url is what gets downloaded.
    assert "streams" not in data
    assert "children" not in data
    assert "output_template" not in data
    assert item_from_json(data).streams == []


def test_item_snapshot_resolves_to_the_same_save_dir(tmp_path):
    # The property that makes resume work at all: if a round trip changed the
    # rendered directory, the restored task would download into a *different*
    # folder and orphan the .part file left behind by the previous process.
    item = _snapshot_item()
    opts = DownloadOptions(output_root=tmp_path)
    before = resolve_save_dir(item, opts)
    after = resolve_save_dir(item_from_json(item_to_json(item)), opts)
    assert before == after


def test_item_from_json_tolerates_unknown_and_garbage():
    # Runs at GUI startup -- the one moment a user cannot recover from an
    # exception -- so a database written by a newer build must not crash here.
    back = item_from_json(
        {
            "platform": "not-a-platform",
            "media_type": "not-a-type",
            "publish_time": "yesterday",
            "author": "a bare string, not a dict",
            "field_from_the_future": 1,
        }
    )
    assert back.platform is Platform.UNKNOWN
    assert back.media_type is MediaType.VIDEO
    assert back.publish_time is None
    assert isinstance(back.author, Author)
    assert back.item_id == "" and back.title == ""


def test_item_from_json_empty_returns_none():
    assert item_from_json(None) is None
    assert item_from_json({}) is None


@pytest.mark.asyncio
async def test_pending_task_insert_list_delete(db_path):
    async with Database(db_path) as db:
        assert await db.list_unfinished() == []
        await db.upsert_pending_task(PendingTaskRow(
            task_id="T0001", platform="bilibili", source_url="https://x/1",
            item_id="BV1", title="first",
        ))
        rows = await db.list_unfinished()
        assert len(rows) == 1
        assert rows[0].task_id == "T0001"
        assert rows[0].item_id == "BV1"
        assert rows[0].status == "queued"
        assert rows[0].created_at is not None

        assert await db.delete_pending_task("T0001") is True
        assert await db.list_unfinished() == []
        # Deleting something already gone is not an error, just False.
        assert await db.delete_pending_task("T0001") is False


@pytest.mark.asyncio
async def test_pending_task_progress_update_preserves_snapshot(db_path):
    """A progress tick must not erase what only the submit path knows."""
    snap = options_to_json(DownloadOptions(output_root=Path("D:/dl")))
    async with Database(db_path) as db:
        await db.upsert_pending_task(PendingTaskRow(
            task_id="T0001", platform="bilibili", source_url="https://x/1",
            title="real title", options_snapshot=snap,
            item_snapshot={"id": "BV1"},
        ))
        first = (await db.list_unfinished())[0]

        # The progress path only knows id/status/fraction -- it passes no
        # title and no snapshots.
        await db.upsert_pending_task(PendingTaskRow(
            task_id="T0001", platform="bilibili", source_url="https://x/1",
            status="downloading", fraction=0.42, title="", message="42%",
        ))
        row = (await db.list_unfinished())[0]
        assert row.fraction == pytest.approx(0.42)
        assert row.status == "downloading"
        assert row.message == "42%"
        assert row.title == "real title"
        assert row.options_snapshot == snap
        assert row.item_snapshot == {"id": "BV1"}
        # Ordering by submission time depends on this staying put.
        assert row.created_at == first.created_at
        # Still exactly one row -- upsert, not append.
        assert len(await db.list_unfinished()) == 1


@pytest.mark.asyncio
async def test_pending_task_snapshot_survives_a_restart(db_path):
    """The whole point: a *different* connection must see the same state."""
    snap = options_to_json(DownloadOptions(
        output_root=Path("D:/dl"), cookies_file=Path("c.txt"), max_quality="1080p",
    ))
    async with Database(db_path) as db:
        await db.upsert_pending_task(PendingTaskRow(
            task_id="T0007", platform="douyin", source_url="https://y/7",
            status="downloading", fraction=0.8, options_snapshot=snap,
        ))

    async with Database(db_path) as db2:
        rows = await db2.list_unfinished()
        assert len(rows) == 1
        row = rows[0]
        assert row.fraction == pytest.approx(0.8)
        # from_row must hand back a decoded dict, not the raw JSON text.
        assert isinstance(row.options_snapshot, dict)
        rebuilt = options_from_json(
            row.options_snapshot, DownloadOptions(output_root=Path("."))
        )
        assert rebuilt.output_root == Path("D:/dl")
        assert rebuilt.cookies_file == Path("c.txt")
        assert rebuilt.max_quality == "1080p"


@pytest.mark.asyncio
async def test_pending_task_ordering_and_clear(db_path):
    async with Database(db_path) as db:
        # Same created_at on purpose: the task_id tiebreaker must make the
        # order deterministic anyway.
        for tid in ("T0003", "T0001", "T0002"):
            await db.upsert_pending_task(PendingTaskRow(
                task_id=tid, platform="bilibili", source_url="u" + tid,
                created_at=1735689600,
            ))
        assert [r.task_id for r in await db.list_unfinished()] == [
            "T0001", "T0002", "T0003",
        ]
        # limit=0 is clamped to >= 1, matching list_recent.
        assert len(await db.list_unfinished(limit=0)) == 1
        assert await db.clear_pending_tasks() == 3
        assert await db.list_unfinished() == []


@pytest.mark.asyncio
async def test_pending_task_table_created_on_a_preexisting_database(db_path):
    """Guards the reason this is a new table instead of new columns.

    Every SCHEMA statement is ``CREATE TABLE IF NOT EXISTS`` and there is
    no schema-version mechanism, so a *column* added to an existing table
    would be silently skipped and every later INSERT would fail with
    ``no such column``. A brand-new table is created on old files too.

    The "old" database is produced by the real ``Database`` and then has
    ``pending_task`` dropped, rather than by hand-copying an older schema
    -- a hand-written copy would rot the moment the real schema changes.
    """
    async with Database(db_path) as db:
        await db.record_download(
            platform="bilibili", item_id="BV1", save_dir="D:/dl/BV1",
            title="pre-existing",
        )

    conn = sqlite3.connect(str(db_path))
    conn.execute("DROP TABLE pending_task")
    conn.commit()
    cols = [r[1] for r in conn.execute("PRAGMA table_info(media_item)")]
    conn.close()
    assert cols, "the simulated old database should still have media_item"

    # Reopening must recreate only what is missing, and must not disturb
    # the rows that were already there.
    async with Database(db_path) as db:
        await db.upsert_pending_task(PendingTaskRow(
            task_id="T0001", platform="bilibili", source_url="https://x/1",
        ))
        assert len(await db.list_unfinished()) == 1
        assert await db.is_downloaded("bilibili", "BV1") is True


# ---------------------------------------------------------------------------
# migration
# ---------------------------------------------------------------------------


def _make_legacy_douyin_db(path: Path) -> None:
    """Create a minimal dy_downloader.db at ``path`` for migration tests."""
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE aweme (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            aweme_id TEXT UNIQUE NOT NULL,
            aweme_type TEXT NOT NULL,
            title TEXT,
            author_id TEXT,
            author_name TEXT,
            author_sec_uid TEXT,
            create_time INTEGER,
            download_time INTEGER,
            file_path TEXT,
            metadata TEXT,
            cover_urls TEXT,
            job_id TEXT
        );
    """)
    conn.executemany(
        "INSERT INTO aweme "
        "(aweme_id, aweme_type, title, author_id, author_name, "
        " author_sec_uid, create_time, download_time, file_path, metadata) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("7000000000000000001", "video", "标题1", "A1", "张三", "SEC1",
             1735689600, 1735689700, "/path/to/v1.mp4", '{"key": "v1"}'),
            ("7000000000000000002", "image_album", "标题2", "A2", "李四", "SEC2",
             1735799600, 1735799700, "/path/to/v2", '{"key": "v2"}'),
        ],
    )
    conn.commit()
    conn.close()


def _make_legacy_bili23_db(path: Path) -> None:
    """Create a minimal Bili23 task DB at ``path`` for migration tests."""
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE task (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bvid TEXT,
            title TEXT,
            up_name TEXT,
            up_id TEXT,
            save_dir TEXT
        );
    """)
    conn.executemany(
        "INSERT INTO task (bvid, title, up_name, up_id, save_dir) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            ("BV1xx1111xxxx", "测试视频A", "测试UP主", "12345", "/path/A"),
            ("BV1xx2222xxxx", "测试视频B", "其他UP", "67890", "/path/B"),
        ],
    )
    conn.commit()
    conn.close()


@pytest.mark.asyncio
async def test_migrate_douyin_basic(tmp_path):
    legacy = tmp_path / "dy.db"
    _make_legacy_douyin_db(legacy)
    dest = Database(tmp_path / "doubi.db")
    await dest.initialize()
    n = await dest.migrate_from_legacy(legacy)
    assert n == 2
    row1 = await dest.get_item("douyin", "7000000000000000001")
    assert row1 is not None
    assert row1.title == "标题1"
    assert row1.author_name == "张三"
    assert row1.author_id == "A1"
    assert row1.publish_time == 1735689600
    assert row1.last_save_dir == "/path/to/v1.mp4"
    assert row1.media_type == "video"
    assert row1.payload == {"key": "v1"}
    assert row1.extra["author_sec_uid"] == "SEC1"
    await dest.close()


@pytest.mark.asyncio
async def test_migrate_douyin_missing_file(tmp_path):
    dest = Database(tmp_path / "doubi.db")
    await dest.initialize()
    n = await dest.migrate_from_legacy(tmp_path / "missing.db")
    assert n == 0
    await dest.close()


@pytest.mark.asyncio
async def test_migrate_douyin_no_aweme_table(tmp_path):
    """Legacy DB without 'aweme' table should return 0."""
    conn = sqlite3.connect(str(tmp_path / "empty.db"))
    conn.execute("CREATE TABLE other (id INTEGER)")
    conn.commit()
    conn.close()
    dest = Database(tmp_path / "doubi.db")
    await dest.initialize()
    n = await dest.migrate_from_legacy(tmp_path / "empty.db")
    assert n == 0
    await dest.close()


@pytest.mark.asyncio
async def test_migrate_bili23_basic(tmp_path):
    legacy = tmp_path / "bili23.db"
    _make_legacy_bili23_db(legacy)
    dest = Database(tmp_path / "doubi.db")
    await dest.initialize()
    n = await migrate_bili23_to_doubi(legacy, dest)
    assert n == 2
    row1 = await dest.get_item("bilibili", "BV1xx1111xxxx")
    assert row1 is not None
    assert row1.title == "测试视频A"
    assert row1.author_name == "测试UP主"
    assert row1.author_id == "12345"
    assert row1.last_save_dir == "/path/A"
    await dest.close()


@pytest.mark.asyncio
async def test_migrate_bili23_missing_file(tmp_path):
    dest = Database(tmp_path / "doubi.db")
    await dest.initialize()
    n = await migrate_bili23_to_doubi(tmp_path / "missing.db", dest)
    assert n == 0
    await dest.close()


# ---------------------------------------------------------------------------
# integration: pipeline writes DB + manifest on success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_records_download_in_db_and_manifest(monkeypatch, tmp_path):
    """End-to-end: spy engine returns True → pipeline writes to DB + manifest."""
    import doubi.core.pipeline as pipeline_mod

    class _SpyEngine:
        name = "spy"
        def supports(self, item): return True
        async def download(self, item, options, *, on_progress=None):
            # Simulate a file landing in the item dir
            resolve_item_dir(item, options)
            return True

    db_path = tmp_path / "test.db"
    manifest_path = tmp_path / "manifest.jsonl"
    options = DownloadOptions(
        output_root=tmp_path / "Downloaded",
        database=db_path,
        manifest=manifest_path,
    )

    item = MediaItem(
        platform=Platform.DOUYIN, item_id="7123456789012345678",
        title="测试视频", author=Author(name="张三"),
        publish_time=dt.datetime(2026, 1, 15),
        media_type=MediaType.VIDEO,
        source_url="https://www.douyin.com/video/7123456789012345678",
    )
    pipeline = pipeline_mod.DownloadPipeline(engine=_SpyEngine())

    async def _fake_parse(url): return item
    monkeypatch.setattr(pipeline, "parse", _fake_parse)

    result = await pipeline.process_url(item.source_url, options)
    assert result is not None

    # DB row created
    db = Database(db_path)
    await db.initialize()
    assert await db.is_downloaded("douyin", "7123456789012345678")
    row = await db.get_item("douyin", "7123456789012345678")
    assert row.title == "测试视频"
    assert row.author_name == "张三"
    await db.close()

    # Manifest entry
    assert manifest_path.exists()
    records = ManifestWriter(manifest_path).read_all()
    assert len(records) == 1
    assert records[0]["platform"] == "douyin"
    assert records[0]["item_id"] == "7123456789012345678"
    assert records[0]["title"] == "测试视频"


@pytest.mark.asyncio
async def test_pipeline_skips_already_downloaded(monkeypatch, tmp_path):
    """If the (platform, item_id) is in the DB, process_url returns True without calling the engine."""
    import doubi.core.pipeline as pipeline_mod

    db_path = tmp_path / "test.db"
    db = Database(db_path)
    await db.initialize()
    await db.record_download(platform="douyin", item_id="abc", save_dir="x")
    await db.close()

    called = {"n": 0}

    class _SpyEngine:
        name = "spy"
        def supports(self, item): return True
        async def download(self, item, options, *, on_progress=None):
            called["n"] += 1
            return True

    options = DownloadOptions(
        output_root=tmp_path / "Downloaded",
        database=db_path,
    )

    item = MediaItem(
        platform=Platform.DOUYIN, item_id="abc", title="t",
        author=Author(), media_type=MediaType.VIDEO, source_url="x",
    )
    pipeline = pipeline_mod.DownloadPipeline(engine=_SpyEngine())

    async def _fake_parse(url): return item
    monkeypatch.setattr(pipeline, "parse", _fake_parse)

    result = await pipeline.process_url("x", options)
    assert result is not None
    assert called["n"] == 0  # engine NOT called because DB hit


@pytest.mark.asyncio
async def test_pipeline_continues_on_db_failure(monkeypatch, tmp_path):
    """If the DB write fails, the pipeline doesn't fail the download — just logs."""
    import doubi.core.pipeline as pipeline_mod
    import doubi.core.storage.database as db_mod

    class _BoomDb:
        async def initialize(self): pass
        async def is_downloaded(self, *a, **kw): return False
        async def record_download(self, **kw): raise RuntimeError("db down")
        async def close(self): pass

    def _boom_factory(p):
        return _BoomDb()

    monkeypatch.setattr(db_mod, "Database", _boom_factory)

    class _SpyEngine:
        name = "spy"
        def supports(self, item): return True
        async def download(self, item, options, *, on_progress=None): return True

    options = DownloadOptions(output_root=tmp_path, database=tmp_path / "x.db")
    item = MediaItem(platform=Platform.DOUYIN, item_id="1", title="t",
                     author=Author(), media_type=MediaType.VIDEO, source_url="x")
    pipeline = pipeline_mod.DownloadPipeline(engine=_SpyEngine())
    async def _fake_parse(url): return item
    monkeypatch.setattr(pipeline, "parse", _fake_parse)
    result = await pipeline.process_url("x", options)
    assert result is not None   # pipeline should still report success
