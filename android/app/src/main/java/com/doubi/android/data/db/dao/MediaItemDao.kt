package com.doubi.android.data.db.dao

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import com.doubi.android.data.db.entity.MediaItemEntity
import kotlinx.coroutines.flow.Flow

/**
 * 桌面版对照：`src/doubi/core/storage/database.py:Database` 的
 * `is_downloaded` / `get_item` / `record_download` / `delete_item` /
 * `list_by_author` / `list_recent` / `count` 一组方法。
 *
 * 命名：snake_case 数据库列名 → camelCase Kotlin 字段；DAO 方法名保持英文。
 * 返回类型：`Optional[X]` → `X?`，列表 → `List<X>`，Flow 暴露给 UI 层订阅。
 */
@Dao
interface MediaItemDao {
    /** 桌面版 `is_downloaded()`。 */
    @Query("SELECT EXISTS(SELECT 1 FROM media_item WHERE platform = :platform AND item_id = :itemId)")
    suspend fun isDownloaded(platform: String, itemId: String): Boolean

    /** 桌面版 `is_downloaded()` 的 Flow 版本，给 UI 实时刷新用。 */
    @Query("SELECT EXISTS(SELECT 1 FROM media_item WHERE platform = :platform AND item_id = :itemId)")
    fun isDownloadedFlow(platform: String, itemId: String): Flow<Boolean>

    /** 桌面版 `get_item()`。 */
    @Query("SELECT * FROM media_item WHERE platform = :platform AND item_id = :itemId LIMIT 1")
    suspend fun getItem(platform: String, itemId: String): MediaItemEntity?

    @Query("SELECT * FROM media_item WHERE platform = :platform AND item_id = :itemId LIMIT 1")
    fun getItemFlow(platform: String, itemId: String): Flow<MediaItemEntity?>

    /**
     * 桌面版 `record_download()`：单条 upsert，冲突时替换。
     * `saveDir` 通过 `last_save_dir` 字段落库（桌面版用相对路径，
     * Android 端用绝对路径，避免重蹈 `database_path` 相对路径的卸载残留坑）。
     */
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(item: MediaItemEntity)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertAll(items: List<MediaItemEntity>)

    /** 桌面版 `delete_item()`。返回受影响行数。 */
    @Query("DELETE FROM media_item WHERE platform = :platform AND item_id = :itemId")
    suspend fun delete(platform: String, itemId: String): Int

    /** 桌面版 `list_by_author()`。 */
    @Query(
        """
        SELECT * FROM media_item
        WHERE platform = :platform AND author_id = :authorId
        ORDER BY last_download_time DESC
        LIMIT :limit
        """
    )
    suspend fun listByAuthor(platform: String, authorId: String, limit: Int = 200): List<MediaItemEntity>

    /** 桌面版 `list_recent()`。 */
    @Query("SELECT * FROM media_item ORDER BY last_download_time DESC LIMIT :limit")
    suspend fun listRecent(limit: Int = 200): List<MediaItemEntity>

    /** 桌面版 `list_recent()` 的 Flow 版本。UI 「历史」页订阅。 */
    @Query("SELECT * FROM media_item ORDER BY last_download_time DESC LIMIT :limit")
    fun listRecentFlow(limit: Int = 200): Flow<List<MediaItemEntity>>

    /** 桌面版 `count()`。 */
    @Query("SELECT COUNT(*) FROM media_item")
    suspend fun count(): Int

    @Query("SELECT COUNT(*) FROM media_item")
    fun countFlow(): Flow<Int>
}
