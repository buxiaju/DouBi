package com.doubi.android.data.repository

import android.content.Context
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.Data
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkInfo
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
import java.util.concurrent.TimeUnit
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
     * WorkManager 实时 WorkInfo 列表（Flow），按 "download" tag 过滤。阶段 5 用：
     * UI 把 `activeTasks` + `workInfosFlow` combine 起来，**实时进度 / 速度 / ETA**
     * 走 WorkInfo.progress（Worker 内 setProgress 推过来的），**持久化状态**走 Room。
     *
     * 注意：`getWorkInfosByTagFlow` 是 WorkManager 2.10.0 提供的 flow API，
     * 内部监听 WorkManager database 变化，对「SUCCEEDED / FAILED / CANCELLED」状态
     * 也会持续 emit（不在 `RUNNING / ENQUEUED` 时同样有 List 元素）——UI 端要做
     * 状态过滤。
     */
    val workInfosFlow: Flow<List<WorkInfo>> = WorkManager.getInstance(context)
        .getWorkInfosByTagFlow("download")

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
     * @throws QueueFullException 当 in-flight 任务数（queued + running）≥ `AppConfig.concurrentJobs` 时
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

        // 0. 阶段 5：并发数检查。activeTasks 数（Room 端 queued/downloading/paused）
        // + in-flight workInfos（WorkManager 端 ENQUEUED + RUNNING）去重后比 concurrentJobs。
        // 两者可能不完全一致（Room 入队时 WorkInfo 还没建出来），用合集保守估计。
        val concurrentJobs = appConfigDataStore.get().concurrentJobs
        val roomActive = pendingTaskDao.listUnfinished().map { it.taskId }.toSet()
        val workManagerActive = try {
            WorkManager.getInstance(context)
                .getWorkInfosByTag("download")
                .get()
                .filter { it.state == WorkInfo.State.ENQUEUED || it.state == WorkInfo.State.RUNNING }
                .mapNotNull { it.tags.firstOrNull { tag -> tag != "download" } }
                .toSet()
        } catch (_: Throwable) {
            emptySet()
        }
        val allActive = roomActive + workManagerActive
        if (allActive.size >= concurrentJobs) {
            throw QueueFullException(
                current = allActive.size,
                limit = concurrentJobs,
            )
        }

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
            // 欠账 #1 已还：失败时按指数退避 30s 重试，最多 DownloadWorker.MAX_ATTEMPTS 次
            // （由 Result.retry() 触发，WorkManager 内部把 runAttemptCount 推到上限后
            // 自动转 failure）。永久错误（404 / 磁盘满 / URL 非法）不重试，直接
            // failure，让用户在历史页手动 retry。
            .setBackoffCriteria(
                BackoffPolicy.EXPONENTIAL,
                WorkRequestBuilder_BACKOFF_SECONDS,
                TimeUnit.SECONDS,
            )
            .build()
        WorkManager.getInstance(context).enqueueUniqueWork(
            "download_$finalTaskId",
            ExistingWorkPolicy.KEEP,  // 同一 taskId 不重复入队
            request,
        )
        return finalTaskId
    }

    /**
     * 阶段 5：并发数已满。UI 收到后弹「队列已满（N/M）」toast 提示用户稍候。
     */
    class QueueFullException(
        val current: Int,
        val limit: Int,
    ) : Exception("下载队列已满：当前 $current / 上限 $limit")

    /**
     * 取消一个任务。
     * 桌面版：TaskManager.remove(taskId) + engine 进程 kill。Android 端：
     * WorkManager.cancelUniqueWork 会触发 CoroutineWorker 的 cancel()，
     * 我们的 DownloadWorker 协程里能感知到 cont.isCancelled。
     */
    fun cancel(taskId: String) {
        WorkManager.getInstance(context).cancelUniqueWork("download_$taskId")
    }

    companion object {
        /**
         * 退避初始延迟 30s（指数翻倍，最长 5 小时）。
         * WorkManager 指数退避公式：actual = initial * 2^runAttemptCount（带 ± jitter）。
         * DownloadWorker.MAX_ATTEMPTS=10：第 10 次重试的延迟 ≈ 30s * 2^9 ≈ 170 分钟。
         */
        const val WorkRequestBuilder_BACKOFF_SECONDS = 30L
    }
}
