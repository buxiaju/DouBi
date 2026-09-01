package com.doubi.android.data.db.entity

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

/**
 * 桌面版对照：`src/doubi/core/storage/database.py:TaskRow`。
 * 批量任务（CLI / REST 提交）结束后写入的历史记录。
 */
@Entity(
    tableName = "task",
    indices = [Index(value = ["started_at"], name = "idx_task_started")],
)
data class TaskEntity(
    @PrimaryKey
    @ColumnInfo(name = "task_id") val taskId: String,
    @ColumnInfo(name = "platform") val platform: String? = null,
    /** pending | running | completed | failed */
    @ColumnInfo(name = "status") val status: String = "pending",
    @ColumnInfo(name = "total") val total: Int = 0,
    @ColumnInfo(name = "succeeded") val succeeded: Int = 0,
    @ColumnInfo(name = "failed") val failed: Int = 0,
    @ColumnInfo(name = "started_at") val startedAt: Long? = null,
    @ColumnInfo(name = "finished_at") val finishedAt: Long? = null,
    /** JSON snapshot of options. */
    @ColumnInfo(name = "config_snapshot") val configSnapshot: String? = null,
)
