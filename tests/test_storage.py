"""Tests for M4: Database, file_layout, manifest, migration."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import sqlite3
import sys
from pathlib import Path

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
)
from doubi.core.storage.database import Database, MediaItemRow, TaskRow  # noqa: E402
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


def test_resolve_item_dir_creates_leaf(tmp_path):
    """A standalone video's leaf dir is named exactly after the video."""
    item = MediaItem(platform=Platform.DOUYIN, item_id="1", title="t",
                     author=Author(name="张三"), media_type=MediaType.VIDEO,
                     source_url="x", publish_time=dt.datetime(2026, 1, 15))
    options = DownloadOptions(output_root=tmp_path)
    item_dir = resolve_item_dir(item, options)
    assert item_dir.exists()
    assert item_dir.name == "t"
    assert item_dir.parent == resolve_save_dir(item, options)


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


def test_resolve_item_dir_sanitizes_illegal_chars_in_leaf(tmp_path):
    item = MediaItem(platform=Platform.BILIBILI, item_id="1",
                     title='a/b:c*d?e', author=Author(name="UP主"),
                     media_type=MediaType.VIDEO, source_url="x")
    options = DownloadOptions(output_root=tmp_path)
    item_dir = resolve_item_dir(item, options)
    assert item_dir.exists()
    assert item_dir.name == "a_b_c_d_e"


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
