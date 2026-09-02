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
import timber.log.Timber

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
 * **重试策略**（欠账 #1，v0.1 已还）：WorkManager 自带退避由 [DownloadRepository.enqueue] 配的
 * `setBackoffCriteria` 控制（指数 / 30s 起步，10 次封顶）。每次 `Result.retry()` 触发的「自动重试」
 * **与桌面版语义兼容**——桌面版 `TaskManager.retry()` 是用户手动点，Android 端的自动重试是底层
 * WorkManager 机制；二者都允许「失败后由用户在历史页点 retry 再入新 enqueue」。
 * 区分原则：网络类瞬时错误（DNS、连接重置、超时、5xx）→ `retry()`；语义错误（404、磁盘满、
 * 解析失败、URL 非法）→ `failure()`。判据见 [isTransientFailure]。
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
        val attempt = runAttemptCount + 1  // 1-based

        // 0. 重试尝试打点（写到 message 字段，UI 看到「第 N 次重试」）
        if (attempt > 1) {
            pendingTaskDao.updateProgress(
                taskId = taskId,
                status = "downloading",
                fraction = 0f,
                message = "第 $attempt 次尝试…",
                updatedAt = System.currentTimeMillis() / 1000L,
            )
            Timber.i("DownloadWorker[%s] attempt %d/%d", taskId, attempt, MAX_ATTEMPTS)
        }

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
            // message 用 Progress.statusLine()——带速度和 ETA，历史页直接展示（欠账 #4）。
            // 不落 speed/eta 独立字段：那要改 Room schema + 写 migration，超出本轮范围；
            // 结构化数值走 setProgress()（下面）给正在观察这个 Work 的 UI。
            val line = progress.statusLine()
            pendingTaskDao.updateProgress(
                taskId = taskId,
                status = "downloading",
                fraction = progress.fraction,
                message = line,
                updatedAt = System.currentTimeMillis() / 1000L,
            )
            // 刷新前台 Service 通知
            val updated = notificationHelper.buildProgressNotification(
                taskId = taskId,
                title = displayTitle,
                progress = progress,
            )
            setProgress(
                workDataOf(
                    KEY_PROGRESS to progress.fraction,
                    // 未知统一写 -1，跟 yt-dlp 自己的约定一致；读侧 <=0 当没有
                    KEY_SPEED to (progress.speedBytesPerSec ?: -1L),
                    KEY_ETA to (progress.etaSeconds ?: -1L),
                )
            )
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
        // 阶段 5：通知走 notifyByCompletionMode 按 AppConfig.notifyOnCompletion 三档
        val notifyMode = config.notifyOnCompletion
        return when (result) {
            is DownloadResult.Success -> {
                pendingTaskDao.updateProgress(
                    taskId, "completed", 1f,
                    "完成：${result.localPath}",
                    System.currentTimeMillis() / 1000L,
                )
                notificationHelper.notifyByCompletionMode(
                    mode = notifyMode,
                    taskId = taskId,
                    title = displayTitle,
                    success = true,
                    localPath = result.localPath,
                )
                Result.success(workDataOf(KEY_LOCAL_PATH to result.localPath))
            }
            is DownloadResult.Failure -> {
                val transient = isTransientFailure(result.reason)
                pendingTaskDao.updateProgress(
                    taskId,
                    if (transient) "downloading" else "failed",
                    0f,
                    if (transient) "失败（将自动重试）：${result.reason}"
                    else "失败：${result.reason}",
                    System.currentTimeMillis() / 1000L,
                )
                if (transient) {
                    Timber.w("DownloadWorker[%s] transient failure, will retry (attempt %d): %s",
                        taskId, attempt, result.reason)
                    // WorkManager 退避策略在 enqueue 时设，runAttemptCount 到达 MAX_ATTEMPTS
                    // 之前 Result.retry() 都会触发重试
                    Result.retry()
                } else {
                    Timber.e("DownloadWorker[%s] permanent failure: %s", taskId, result.reason)
                    notificationHelper.notifyByCompletionMode(
                        mode = notifyMode,
                        taskId = taskId,
                        title = displayTitle,
                        success = false,
                    )
                    Result.failure(workDataOf(KEY_ERROR to result.reason))
                }
            }
            is DownloadResult.Cancelled -> {
                pendingTaskDao.updateProgress(
                    taskId, "paused", 0f, "已取消",
                    System.currentTimeMillis() / 1000L,
                )
                // Cancelled 不发通知——用户主动取消
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

        /** setProgress 里的瞬时速度（字节/秒）。未知写 -1。 */
        const val KEY_SPEED = "speed_bytes_per_sec"

        /** setProgress 里的预计剩余秒数。未知写 -1。 */
        const val KEY_ETA = "eta_seconds"

        /**
         * WorkManager 允许的最大 attempt 数。WorkManager 默认就支持到 10，
         * 超过后 Result.retry() 也会被转成 failure——我们显式声明，让意图清晰。
         */
        const val MAX_ATTEMPTS = 10

        /**
         * 判断失败原因是否值得自动重试。
         *
         * 桌面版 `TaskManager` 没自动重试，全部失败交由用户在 UI 点 retry。
         * Android 端我们用 WorkManager 的指数退避 + Result.retry() 做自动重试（仅对瞬时错误），
         * 永久错误直接 failure，让用户在历史页手动 retry。
         */
        val TRANSIENT_PATTERNS: List<Regex> = listOf(
            Regex("""(?i)\b(timeout|connection|connect|network|reset|reset by peer|unreachable|host|5\d\d|503|429|EOFException|SSLException|UnknownHostException)\b"""),
            Regex("""(?i)\b(yt-dlp|network|download)\b.*\b(timed out|reset|refused|unreachable)"""),
        )

        fun isTransientFailure(reason: String): Boolean =
            TRANSIENT_PATTERNS.any { it.containsMatchIn(reason) }
    }
}
