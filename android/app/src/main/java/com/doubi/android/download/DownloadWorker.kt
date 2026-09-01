package com.doubi.android.download

import android.content.Context
import androidx.hilt.work.HiltWorker
import androidx.work.CoroutineWorker
import androidx.work.ForegroundInfo
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import com.doubi.android.core.config.toDownloadOptions
import com.doubi.android.data.config.AppConfigDataStore
import com.doubi.android.data.db.dao.PendingTaskDao
import com.doubi.android.data.repository.DownloadRepository
import com.doubi.android.engine.ytdlp.YtDlpEngine
import com.doubi.android.core.model.DownloadResult
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject

/**
 * 下载 Worker——**当前是占位 stub**。
 *
 * **状态（v0.1）**：JitPack 401 阻止 yausername/yt-dlp-android 集成。
 * Worker 仍然能起来（`@HiltWorker` 注入 + HiltWorkerFactory 配置好了），
 * 但调用的 YtDlpEngine 是 stub 版，所以 `download()` 立即返回 `Failure`。
 *
 * **v0.2 恢复路径**：与 YtDlpEngine 同——恢复依赖 + 把 .bak 文件覆盖回原位。
 *
 * **桩行为**：
 * 1. 拉 AppConfig → DownloadOptions
 * 2. 调 YtDlpEngine.probe()（拿到 stub MediaItem）
 * 3. 调 YtDlpEngine.download()（立即返回 Failure）
 * 4. 写 PendingTaskDao 终态 = failed
 * 5. 发桌面通知（"失败：yt-dlp 集成未启用"）
 * 6. Result.failure()，WorkManager 标记任务失败
 */
@HiltWorker
class DownloadWorker @AssistedInject constructor(
    @Assisted appContext: Context,
    @Assisted params: WorkerParameters,
    private val configStore: AppConfigDataStore,
    private val pendingTaskDao: PendingTaskDao,
    private val downloadRepo: DownloadRepository,
) : CoroutineWorker(appContext, params) {

    private val notificationHelper = NotificationHelper(appContext)

    override suspend fun doWork(): Result {
        val taskId = inputData.getString(KEY_TASK_ID)
            ?: return Result.failure(workDataOf(KEY_ERROR to "Missing task_id"))
        val sourceUrl = inputData.getString(KEY_SOURCE_URL)
            ?: return Result.failure(workDataOf(KEY_ERROR to "Missing source_url"))
        val platformKey = inputData.getString(KEY_PLATFORM) ?: "generic"

        val config = configStore.get()
        val options = config.toDownloadOptions()
        val engine = YtDlpEngine(downloadRepo.baseOutputDir)
        val nowSec = System.currentTimeMillis() / 1000L

        // 1. 嗅探（stub 也能调——返回最小 MediaItem）
        val item = try { engine.probe(sourceUrl, options) } catch (e: Throwable) {
            com.doubi.android.core.model.MediaItem(
                platform = com.doubi.android.core.model.Platform.fromString(platformKey),
                itemId = sourceUrl.hashCode().toString(),
                sourceUrl = sourceUrl,
                title = sourceUrl,
            )
        }
        val displayTitle = item.title.ifBlank { sourceUrl }

        // 2. 前台 Service 通知
        val progressNotification = notificationHelper.buildProgressNotification(
            taskId = taskId, title = displayTitle, fraction = 0f, message = "下载中…",
        )
        setForeground(
            ForegroundInfo(
                NotificationHelper.PROGRESS_NOTIFICATION_ID,
                progressNotification,
            )
        )

        // 3. 标记 running
        pendingTaskDao.updateProgress(
            taskId = taskId, status = "downloading", fraction = 0f,
            message = "stub Worker 启动", updatedAt = nowSec,
        )

        // 4. 调引擎（stub 立即返回 Failure）
        val result = engine.download(item, options) { /* progress 永不触发 */ }

        // 5. 退出
        return when (result) {
            is DownloadResult.Success -> {
                pendingTaskDao.updateProgress(
                    taskId, "completed", 1f, "完成：${result.localPath}", nowSec,
                )
                notificationHelper.notifyComplete(taskId, displayTitle, success = true, result.localPath)
                Result.success(workDataOf(KEY_LOCAL_PATH to result.localPath))
            }
            is DownloadResult.Failure -> {
                pendingTaskDao.updateProgress(
                    taskId, "failed", 0f, "失败：${result.reason}", nowSec,
                )
                notificationHelper.notifyComplete(taskId, displayTitle, success = false)
                Result.failure(workDataOf(KEY_ERROR to result.reason))
            }
            is DownloadResult.Cancelled -> {
                pendingTaskDao.updateProgress(
                    taskId, "paused", 0f, "已取消", nowSec,
                )
                Result.failure(workDataOf(KEY_ERROR to "cancelled"))
            }
        }
    }

    companion object {
        const val KEY_TASK_ID = "task_id"
        const val KEY_SOURCE_URL = "source_url"
        const val KEY_PLATFORM = "platform"
        const val KEY_LOCAL_PATH = "local_path"
        const val KEY_ERROR = "error"
        const val KEY_PROGRESS = "progress"
    }
}
