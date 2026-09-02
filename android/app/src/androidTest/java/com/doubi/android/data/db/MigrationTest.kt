package com.doubi.android.data.db

import androidx.room.testing.MigrationTestHelper
import androidx.sqlite.db.framework.FrameworkSQLiteOpenHelperFactory
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.google.common.truth.Truth.assertThat
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Room Migration 仪器测试。
 *
 * 欠账 #3 已还：v0.1.0 起，每次升 `DouBiDatabase.version` 必须在同 commit 加一个测试
 * 方法，调用 `runMigrationsAndValidate` 验证 `Migrations.ALL` 能从老版本升到当前版本。
 *
 * **如何加新测试**：当 [Migrations.ALL] 新增 `Migration(1, 2)` 时：
 * 1. 写 `migrate1To2()` 单独验证
 * 2. 同时给下面的 `migrateAll()` 加进 ALL_MIGRATIONS
 *
 * 桌面版对照：SQLAlchemy 时代的 `test_migrations.py` 用 `op.get_bind()` 跑 upgrade。
 * Android 端这层是 Room 提供的 MigrationTestHelper。
 */
@RunWith(AndroidJUnit4::class)
class MigrationTest {
    @get:Rule
    val helper = MigrationTestHelper(
        InstrumentationRegistry.getInstrumentation(),
        DouBiDatabase::class.java.canonicalName,
        FrameworkSQLiteOpenHelperFactory(),
    )

    @Test
    fun v1_createAndQueryMediaItem() {
        // 验证 v1 起步的 schema：media_item 表存在、能 insert + read
        helper.createDatabase(TEST_DB, 1).apply {
            // media_item 主键 (platform, item_id) + 全 nullable 字段
            execSQL(
                "INSERT INTO media_item(platform, item_id, title) VALUES (?, ?, ?)",
                arrayOf("youtube", "m1", "Test"),
            )
            close()
        }
        val db = helper.runMigrationsAndValidate(TEST_DB, 1, true)
        db.query("SELECT title FROM media_item WHERE platform='youtube' AND item_id='m1'").use { c ->
            assertThat(c.moveToFirst()).isTrue()
            assertThat(c.getString(0)).isEqualTo("Test")
        }
    }

    @Test
    fun migrateAll_emptyChain_keepsAllTables() {
        // 当前 v0.1.0 提交时 Migrations.ALL 是空数组——验证空数组不会破坏 v1 启动
        helper.createDatabase(TEST_DB, 1).close()
        val db = helper.runMigrationsAndValidate(TEST_DB, 1, true, *Migrations.ALL)
        db.query("SELECT name FROM sqlite_master WHERE type='table'").use { c ->
            val tables = mutableListOf<String>()
            while (c.moveToNext()) tables += c.getString(0)
            // 4 张 entity 表必须存在
            assertThat(tables).contains("media_item")
            assertThat(tables).contains("pending_task")
            assertThat(tables).contains("task")
            assertThat(tables).contains("increment_checkpoint")
        }
    }

    /**
     * 「全链路迁移」测试：把所有 Migrations.ALL 跑一遍，确保新加的 Migration
     * 不会破坏前序。v0.1.0 时 Migrations.ALL=[]，这个测试会跑出空跑。
     * 一旦 v0.2.0 加 MIGRATION_1_2，下面需要写
     * `helper.runMigrationsAndValidate(TEST_DB, 2, true, MIGRATION_1_2)` 的同等检查。
     */
    @Test
    fun migrateAll_chainIsConsistent() {
        helper.createDatabase(TEST_DB, 1).close()
        val db = helper.runMigrationsAndValidate(TEST_DB, 1, true, *Migrations.ALL)
        // 跑完不崩 + 能查 media_item = 当前 schema 与 v1 一致（因为 Migrations.ALL 是空）
        db.query("SELECT COUNT(*) FROM media_item").use { c ->
            assertThat(c.moveToFirst()).isTrue()
            assertThat(c.getInt(0)).isEqualTo(0)
        }
    }

    companion object {
        const val TEST_DB = "doubi-migration-test.db"
    }
}
