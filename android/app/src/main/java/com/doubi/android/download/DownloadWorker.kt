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
import com.doubi.android.engine.Engine
import com.doubi.android.core.model.MediaItem
import com.doubi.android.core.model.Platform
import com.doubi.android.core.model.DownloadResult
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject

/**
 * 下载 Worker。WorkManager + Hilt 集成。
 *
 * 桌面版对应：`src/doubi/ui/task_manager.py:TaskManager._run_task` 的协程。
 * Android 端用 CoroutineWorker（WorkManager 的协程化版本），所有 IO 都在
 * `coroutineContext = Dispatchers.IO` 上跑。
 *
 * 流程：
 * 1. 读 WorkManager inputData（task_id / source_url / platform）
 * 2. 拉 `AppConfig` → `DownloadOptions`
 * 3. 用 `setForeground()` 维持前台 Service（30 秒内必须调一次，否则 OS 杀）
 * 4. Engine.probe() 嗅探 → Engine.download() 落盘
 * 5. 进度回调：写 PendingTaskDao + 刷新前台通知
 * 6. 退出：清前台通知 + 写完成状态 + 发桌面通知
 *
 * Hilt 自动注入 `AppConfigDataStore` / `PendingTaskDao` / `DownloadRepository`。
 * 任务级 worker 必须有 `@HiltWorker` 注解 + `@AssistedInject` 构造器。
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

        // 1. 拉 AppConfig → DownloadOptions
        val config = configStore.get()
        val options = config.toDownloadOptions()
        val engine: Engine = YtDlpEngine(downloadRepo.baseOutputDir)

        // 2. 标记 running
        pendingTaskDao.updateProgress(
            taskId = taskId,
            status = "downloading",
            fraction = 0f,
            message = "嗅探中…",
            updatedAt = System.currentTimeMillis() / 1000L,
        )

        // 3. 嗅探（失败也不致命——直接拿 URL 走下载）
        val item: MediaItem = try {
            engine.probe(sourceUrl, options)
        } catch (e: Throwable) {
            MediaItem(
                platform = Platform.fromString(platformKey),
                itemId = sourceUrl.hashCode().toString(),
                sourceUrl = sourceUrl,
                title = sourceUrl,
            )
        }
        // 标题从嗅探结果拿，没拿到就用 URL 当标题
        val displayTitle = item.title.ifBlank { sourceUrl }

        // 4. 前台 Service 通知（WorkManager 要求 10s 内调一次，30s 周期保活）
        val progressNotification = notificationHelper.buildProgressNotification(
            taskId = taskId, title = displayTitle, fraction = 0f, message = "下载中…",
        )
        setForeground(
            ForegroundInfo(
                NotificationHelper.PROGRESS_NOTIFICATION_ID,
                progressNotification,
            )
        )

        // 5. 下载（带进度回调）
        val result = engine.download(item, options) { progress ->
            pendingTaskDao.updateProgress(
                taskId = taskId,
                status = "downloading",
                fraction = progress.fraction,
                message = progress.message,
                updatedAt = System.currentTimeMillis() / 1000L,
            )
            // 刷新前台 Service 通知
            val updated = notificationHelper.buildProgressNotification(
                taskId = taskId,
                title = displayTitle,
                fraction = progress.fraction,
                message = progress.message,
            )
            setProgress(workDataOf(KEY_PROGRESS to progress.fraction))
            try {
                setForeground(
                    ForegroundInfo(
                        NotificationHelper.PROGRESS_NOTIFICATION_ID,
                        updated,
                    )
                )  // 30s 内必须调一次
            } catch (_: Throwable) { /* setForeground 在 done 状态下无效，忽略 */ }
        }

        // 6. 退出：清前台 / 写终态 / 发桌面通知
        return when (result) {
            is DownloadResult.Success -> {
                pendingTaskDao.updateProgress(
                    taskId, "completed", 1f,
                    "完成：${result.localPath}",
                    System.currentTimeMillis() / 1000L,
                )
                // 阶段 6 接 notifyOnCompletion 三档
                notificationHelper.notifyComplete(taskId, displayTitle, success = true, localPath = result.localPath)
                Result.success(workDataOf(KEY_LOCAL_PATH to result.localPath))
            }
            is DownloadResult.Failure -> {
                pendingTaskDao.updateProgress(
                    taskId, "failed", 0f, "失败：${result.reason}",
                    System.currentTimeMillis() / 1000L,
                )
                notificationHelper.notifyComplete(taskId, displayTitle, success = false)
                Result.failure(workDataOf(KEY_ERROR to result.reason))
            }
            is DownloadResult.Cancelled -> {
                pendingTaskDao.updateProgress(
                    taskId, "paused", 0f, "已取消",
                    System.currentTimeMillis() / 1000L,
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
