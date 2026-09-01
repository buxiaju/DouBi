package com.doubi.android.data.db.entity

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

/**
 * 桌面版对照：`src/doubi/core/storage/database.py:MediaItemRow`
 * `src/doubi/core/storage/database.py:SCHEMA` 中 `media_item` 表的 Kotlin 镜像。
 *
 * 字段名 snake → camel；JSON 列（payload / extra）以 String 形式落库，
 * 由 [com.doubi.android.data.db.Converters] 透传，Repository 层做 Map ↔ JSON 转换。
 */
@Entity(
    tableName = "media_item",
    primaryKeys = ["platform", "item_id"],
    indices = [
        Index(value = ["platform", "author_id"], name = "idx_media_author"),
        Index(value = ["last_download_time"], name = "idx_media_time"),
        Index(value = ["platform", "publish_time"], name = "idx_media_publish"),
    ],
)
data class MediaItemEntity(
    @ColumnInfo(name = "platform") val platform: String,
    @ColumnInfo(name = "item_id") val itemId: String,
    @ColumnInfo(name = "title") val title: String? = null,
    @ColumnInfo(name = "author_id") val authorId: String? = null,
    @ColumnInfo(name = "author_name") val authorName: String? = null,
    @ColumnInfo(name = "cover_url") val coverUrl: String? = null,
    @ColumnInfo(name = "duration") val duration: Double? = null,
    /** Unix timestamp in seconds. */
    @ColumnInfo(name = "publish_time") val publishTime: Long? = null,
    @ColumnInfo(name = "media_type") val mediaType: String? = null,
    /** Raw JSON blob (yt-dlp info dict). */
    @ColumnInfo(name = "payload") val payload: String? = null,
    /** Unix timestamp. */
    @ColumnInfo(name = "last_download_time") val lastDownloadTime: Long? = null,
    @ColumnInfo(name = "last_save_dir") val lastSaveDir: String? = null,
    /** JSON blob for platform-specific fields. */
    @ColumnInfo(name = "extra") val extra: String? = null,
)
