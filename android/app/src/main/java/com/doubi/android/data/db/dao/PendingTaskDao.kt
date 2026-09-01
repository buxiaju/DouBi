package com.doubi.android.data.db.dao

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import com.doubi.android.data.db.entity.PendingTaskEntity
import kotlinx.coroutines.flow.Flow

/**
 * 桌面版对照：`src/doubi/core/storage/database.py:Database` 的
 * `upsert_pending_task` / `delete_pending_task` / `list_unfinished` / `clear_pending_tasks`。
 *
 * pending_task 是 live 状态：每个下载任务一条，下载完成时删。
 * 跨进程恢复（M6.10 桌面版引入，Android 端在阶段 2 Worker 集成时落地）。
 */
@Dao
interface PendingTaskDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(task: PendingTaskEntity)

    @Query("SELECT * FROM pending_task WHERE task_id = :taskId LIMIT 1")
    suspend fun get(taskId: String): PendingTaskEntity?

    @Query("SELECT * FROM pending_task WHERE task_id = :taskId LIMIT 1")
    fun getFlow(taskId: String): Flow<PendingTaskEntity?>

    /** 进度更新——给 WorkManager Worker 每帧调用。 */
    @Query(
        """
        UPDATE pending_task
        SET status = :status, fraction = :fraction, message = :message, updated_at = :updatedAt
        WHERE task_id = :taskId
        """
    )
    suspend fun updateProgress(
        taskId: String,
        status: String,
        fraction: Float,
        message: String?,
        updatedAt: Long,
    )

    /** 桌面版 `delete_pending_task()`。 */
    @Query("DELETE FROM pending_task WHERE task_id = :taskId")
    suspend fun delete(taskId: String): Int

    /** 桌面版 `list_unfinished()`。 */
    @Query(
        """
        SELECT * FROM pending_task
        WHERE status IN ('queued', 'downloading', 'paused')
        ORDER BY created_at ASC
        LIMIT :limit
        """
    )
    suspend fun listUnfinished(limit: Int = 500): List<PendingTaskEntity>

    @Query(
        """
        SELECT * FROM pending_task
        WHERE status IN ('queued', 'downloading', 'paused')
        ORDER BY created_at ASC
        LIMIT :limit
        """
    )
    fun listUnfinishedFlow(limit: Int = 500): Flow<List<PendingTaskEntity>>

    /** 桌面版 `clear_pending_tasks()`。 */
    @Query("DELETE FROM pending_task")
    suspend fun clear(): Int
}
