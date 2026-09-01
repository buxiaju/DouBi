package com.doubi.android.data.repository

import android.content.Context
import androidx.work.Constraints
import androidx.work.Data
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import com.doubi.android.data.config.AppConfigDataStore
import com.doubi.android.data.db.dao.PendingTaskDao
import com.doubi.android.data.db.entity.PendingTaskEntity
import com.doubi.android.download.DownloadWorker
import com.doubi.android.engine.Engine
import com.doubi.android.engine.ytdlp.YtDlpEngine
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.map
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 下载仓库——Worker ↔ DAO ↔ AppConfig 三方粘合层。
 *
 * 桌面版对应：`src/doubi/ui/task_manager.py:TaskManager`（live 状态 + 入队）。
 * Android 端把 TaskManager 的「内存态 + 持久态」用 Room PendingTaskDao +
 * WorkManager 合体替代：
 * - 入队 → `WorkManager.enqueue(DownloadWorker)` + `PendingTaskDao.upsert`
 * - 进度 → Worker `setProgress` → UI / 通知订阅 `WorkInfo`
 * - 状态变更 → Worker 回调 `PendingTaskDao.updateProgress`
 *
 * Hilt 自动注入，单例。UI 层（阶段 3）拿 `DownloadRepository` 直接调。
 */
@Singleton
class DownloadRepository @Inject constructor(
    @ApplicationContext private val context: Context,
    private val pendingTaskDao: PendingTaskDao,
    private val appConfigDataStore: AppConfigDataStore,
) {
    /**
     * 实时任务列表（Flow），给 UI 订阅。
     * 桌面版 `TaskManager.tasks` 是个 dict，Android 端直接给 `Flow<List<PendingTaskEntity>>`。
     */
    val activeTasks: Flow<List<PendingTaskEntity>> = pendingTaskDao.listUnfinishedFlow()

    /**
     * 注入给 YtDlpEngine 用的 baseOutputDir。app 私有 files/downloads。
     * 不放 Worker 内部——Engine 不该有 Context 依赖。
     */
    val baseOutputDir: java.io.File
        get() = java.io.File(context.filesDir, "downloads")

    /**
     * 入队一个下载任务。
     * @param sourceUrl 视频 URL（YouTube / 直链 / m3u8）
     * @param taskId 业务 id（桌面版 GUI 自己发 T0001 那种）；null 则自动生成
     * @return 入队的 WorkManager requestId
     */
    suspend fun enqueue(
        sourceUrl: String,
        platform: String = "generic",
        itemId: String? = null,
        title: String? = null,
        taskId: String? = null,
    ): String {
        val finalTaskId = taskId ?: "T${System.currentTimeMillis()}"
        val nowSec = System.currentTimeMillis() / 1000L

        // 1. 落 PendingTaskDao（live 状态）
        val entity = PendingTaskEntity(
            taskId = finalTaskId,
            platform = platform,
            itemId = itemId,
            title = title ?: sourceUrl,
            sourceUrl = sourceUrl,
            status = "queued",
            fraction = 0f,
            message = null,
            optionsSnapshot = null,  // v0.1 不持久化 options（直接从 AppConfig 派生）
            itemSnapshot = null,
            createdAt = nowSec,
            updatedAt = nowSec,
        )
        pendingTaskDao.upsert(entity)

        // 2. 入 WorkManager
        val data = Data.Builder()
            .putString(DownloadWorker.KEY_TASK_ID, finalTaskId)
            .putString(DownloadWorker.KEY_SOURCE_URL, sourceUrl)
            .putString(DownloadWorker.KEY_PLATFORM, platform)
            .build()
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()
        val request = OneTimeWorkRequestBuilder<DownloadWorker>()
            .setInputData(data)
            .setConstraints(constraints)
            .addTag("download")
            .addTag(finalTaskId)
            .build()
        WorkManager.getInstance(context).enqueueUniqueWork(
            "download_$finalTaskId",
            ExistingWorkPolicy.KEEP,  // 同一 taskId 不重复入队
            request,
        )
        return finalTaskId
    }

    /**
     * 取消一个任务。
     * 桌面版：TaskManager.remove(taskId) + engine 进程 kill。Android 端：
     * WorkManager.cancelUniqueWork 会触发 CoroutineWorker 的 cancel()，
     * 我们的 DownloadWorker 协程里能感知到 cont.isCancelled。
     */
    fun cancel(taskId: String) {
        WorkManager.getInstance(context).cancelUniqueWork("download_$taskId")
    }
}
