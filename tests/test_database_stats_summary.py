"""Tests for Database.stats_summary (0.3.14).

Borrowed-feature sanity: the history page's download-stats strip rides
on this aggregate query. These tests pin the counts so a schema or SQL
regression shows up as a test failure, not as an empty stats strip.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
import unittest

from doubi.core.storage.database import Database, MediaItemRow


class _StatsSummaryCase(unittest.TestCase):
    """Run one async DB scenario per test via a fresh temp database."""

    def _run(self, coro):
        return asyncio.run(coro)

    def _make_db(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        db = Database(os.path.join(td.name, "stats.db"))
        return db

    def test_counts_platforms_recents_and_authors(self):
        async def scenario():
            db = self._make_db()
            await db.initialize()
            try:
                # record_download 是 keyword-only 且自动盖 last_download_time
                # 为「现在」；老记录靠 direct SQL 回填时间戳。
                await db.record_download(
                    platform="bilibili", item_id="BV1", title="t1",
                    save_dir="bilibili/alice/video", author_name="alice")
                await db.record_download(
                    platform="bilibili", item_id="BV2", title="t2",
                    save_dir="bilibili/alice/video", author_name="alice")
                await db.record_download(
                    platform="douyin", item_id="d1", title="t3",
                    save_dir="douyin/bob/video", author_name="bob")
                conn = await db._conn_required()
                old_ts = int(time.time()) - 30 * 86400
                await conn.execute(
                    "UPDATE media_item SET last_download_time=? "
                    "WHERE item_id='d1'", (old_ts,))
                await conn.commit()
                return await db.stats_summary(recent_days=7)
            finally:
                await db.close()

        stats = self._run(scenario())
        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["by_platform"], {"bilibili": 2, "douyin": 1})
        self.assertEqual(stats["recent_count"], 2)
        self.assertEqual(stats["top_authors"][0], ("alice", 2))

    def test_empty_database_yields_zeroes(self):
        async def scenario():
            db = self._make_db()
            await db.initialize()
            try:
                return await db.stats_summary()
            finally:
                await db.close()

        stats = self._run(scenario())
        self.assertEqual(stats["total"], 0)
        self.assertEqual(stats["by_platform"], {})
        self.assertEqual(stats["recent_count"], 0)
        self.assertEqual(stats["top_authors"], [])


if __name__ == "__main__":
    unittest.main()
