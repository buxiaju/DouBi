package com.doubi.android.data.db.dao

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import com.doubi.android.data.db.entity.IncrementCheckpointEntity

/**
 * 桌面版对照：`src/doubi/core/storage/database.py:Database` 的
 * `get_checkpoint` / `set_checkpoint`。
 *
 * 增量下载游标（抖音「增量」模式）。v0.1 Android 端用不到，
 * 但表先建好，免得到时改 schema。
 */
@Dao
interface IncrementCheckpointDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(checkpoint: IncrementCheckpointEntity)

    @Query(
        """
        SELECT * FROM increment_checkpoint
        WHERE platform = :platform AND user_id = :userId AND mode = :mode
        LIMIT 1
        """
    )
    suspend fun get(platform: String, userId: String, mode: String): IncrementCheckpointEntity?

    @Query("DELETE FROM increment_checkpoint WHERE platform = :platform AND user_id = :userId")
    suspend fun clearForUser(platform: String, userId: String): Int
}
