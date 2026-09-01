package com.doubi.android.data.db.entity

import androidx.room.ColumnInfo
import androidx.room.Entity

/**
 * 桌面版对照：`src/doubi/core/storage/database.py:SCHEMA` 中 `increment_checkpoint` 表。
 * 按用户的增量下载游标（抖音「增量」模式等 M5+ 功能用）。
 */
@Entity(
    tableName = "increment_checkpoint",
    primaryKeys = ["platform", "user_id", "mode"],
)
data class IncrementCheckpointEntity(
    @ColumnInfo(name = "platform") val platform: String,
    @ColumnInfo(name = "user_id") val userId: String,
    @ColumnInfo(name = "mode") val mode: String,
    @ColumnInfo(name = "last_item_id") val lastItemId: String? = null,
    @ColumnInfo(name = "last_check_time") val lastCheckTime: Long? = null,
)
