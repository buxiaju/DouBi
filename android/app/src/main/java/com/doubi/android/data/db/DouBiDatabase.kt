package com.doubi.android.data.db

import androidx.room.Database
import androidx.room.RoomDatabase
import androidx.room.TypeConverters
import com.doubi.android.data.db.dao.IncrementCheckpointDao
import com.doubi.android.data.db.dao.MediaItemDao
import com.doubi.android.data.db.dao.PendingTaskDao
import com.doubi.android.data.db.dao.TaskDao
import com.doubi.android.data.db.entity.IncrementCheckpointEntity
import com.doubi.android.data.db.entity.MediaItemEntity
import com.doubi.android.data.db.entity.PendingTaskEntity
import com.doubi.android.data.db.entity.TaskEntity

/**
 * DouBi Android 数据库。
 *
 * 桌面版对照：`src/doubi/core/storage/database.py:Database`
 *
 * 设计决定：
 * - `database_path` 那个老坑（`core/config.py:45` 相对路径 → 卸载残留）——
 *   Android 版**直接走绝对路径**（`Context.getDatabasePath()`），不复刻
 * - WAL 默认 Room 启用（`setJournalMode(WRITE_AHEAD_LOGGING)`）
 * - busyTimeout Room 不暴露参数，但底层 SQLite 默认 0——phase 1 不深入，先用默认
 * - 迁移：v0.1 是 schema version 1，没历史负担；后续 phase 加表时改 `version`
 *   并写 `Migration` 对象
 *
 * 阶段 7 加 `: RoomDatabase.Callback()` 在首次创建时跑 `INSERT OR IGNORE`
 * 之类的种子数据（如果需要的话）。
 */
@Database(
    entities = [
        MediaItemEntity::class,
        TaskEntity::class,
        PendingTaskEntity::class,
        IncrementCheckpointEntity::class,
    ],
    version = 1,
    exportSchema = true,
)
@TypeConverters(Converters::class)
abstract class DouBiDatabase : RoomDatabase() {
    abstract fun mediaItemDao(): MediaItemDao
    abstract fun taskDao(): TaskDao
    abstract fun pendingTaskDao(): PendingTaskDao
    abstract fun incrementCheckpointDao(): IncrementCheckpointDao

    companion object {
        const val DATABASE_NAME = "doubi.db"
    }
}
