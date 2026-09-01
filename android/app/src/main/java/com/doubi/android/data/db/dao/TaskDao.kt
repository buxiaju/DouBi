package com.doubi.android.data.db.dao

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import com.doubi.android.data.db.entity.TaskEntity
import kotlinx.coroutines.flow.Flow

/**
 * 桌面版对照：`src/doubi/core/storage/database.py:Database` 的
 * `record_task` / `get_task` 一组方法。
 *
 * task 表是批量任务结束后的历史快照，不是 live 状态——live 状态在 `pending_task` 表。
 */
@Dao
interface TaskDao {
    /** 桌面版 `record_task()`。 */
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(task: TaskEntity)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertAll(tasks: List<TaskEntity>)

    /** 桌面版 `get_task()`。 */
    @Query("SELECT * FROM task WHERE task_id = :taskId LIMIT 1")
    suspend fun get(taskId: String): TaskEntity?

    /** 任务列表（按 started_at 倒序）。给「历史」页用。 */
    @Query("SELECT * FROM task ORDER BY started_at DESC LIMIT :limit")
    suspend fun listRecent(limit: Int = 200): List<TaskEntity>

    @Query("SELECT * FROM task ORDER BY started_at DESC LIMIT :limit")
    fun listRecentFlow(limit: Int = 200): Flow<List<TaskEntity>>

    /** 更新单字段——批量完成时累加 succeeded / failed 计数。 */
    @Query(
        """
        UPDATE task
        SET status = :status, succeeded = :succeeded, failed = :failed,
            finished_at = :finishedAt
        WHERE task_id = :taskId
        """
    )
    suspend fun updateProgress(
        taskId: String,
        status: String,
        succeeded: Int,
        failed: Int,
        finishedAt: Long?,
    )
}
