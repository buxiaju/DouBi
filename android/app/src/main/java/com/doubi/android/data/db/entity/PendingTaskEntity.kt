package com.doubi.android.data.db.entity

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

/**
 * 桌面版对照：`src/doubi/core/storage/database.py:PendingTaskRow`。
 *
 * 跨进程未完成任务（M6.10 引入）。重启后 GUI 可询问是否恢复。
 * `sourceUrl` 是唯一严格必要载荷——有它就能重新解析；
 * `itemSnapshot` 是优化（避免网络往返）；
 * `optionsSnapshot` 保留用户对单任务的覆盖（`AppConfig` 推不回来）。
 */
@Entity(
    tableName = "pending_task",
    indices = [Index(value = ["created_at"], name = "idx_pending_created")],
)
data class PendingTaskEntity(
    @PrimaryKey
    @ColumnInfo(name = "task_id") val taskId: String,
    @ColumnInfo(name = "platform") val platform: String,
    @ColumnInfo(name = "item_id") val itemId: String? = null,
    @ColumnInfo(name = "title") val title: String? = null,
    @ColumnInfo(name = "source_url") val sourceUrl: String,
    /** queued | downloading | paused | failed */
    @ColumnInfo(name = "status") val status: String,
    @ColumnInfo(name = "fraction") val fraction: Float = 0f,
    @ColumnInfo(name = "message") val message: String? = null,
    /** JSON DownloadOptions snapshot. */
    @ColumnInfo(name = "options_snapshot") val optionsSnapshot: String? = null,
    /** JSON MediaItem snapshot. */
    @ColumnInfo(name = "item_snapshot") val itemSnapshot: String? = null,
    @ColumnInfo(name = "created_at") val createdAt: Long? = null,
    @ColumnInfo(name = "updated_at") val updatedAt: Long? = null,
)
