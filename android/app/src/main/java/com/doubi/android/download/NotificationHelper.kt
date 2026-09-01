package com.doubi.android.download

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import com.doubi.android.MainActivity
import com.doubi.android.R

/**
 * 通知助手——前台 Service 进度通知 + 完成通知。
 *
 * 桌面版对应：`src/doubi/ui/tray.py:TrayController.notify_completion` + 系统通知。
 * Android 端：
 * - **进度通知**：DownloadWorker.runWorker() 里调用 `setForeground(async)` 维持前台 Service，
 *   OS 不会因内存压力杀 Worker
 * - **完成通知**：Worker 退出时根据 `notifyOnCompletion` 配置（success / all / summary）
 *   决定要不要发桌面版三档
 *
 * 阶段 2 只做「success 档：成功就发通知」——UI 设置页（阶段 6）会接 all / summary。
 */
class NotificationHelper(private val context: Context) {

    init {
        ensureChannel()
    }

    /**
     * 前台 Service 通知。WorkManager `setForeground()` 调它，30 秒内必须调一次
     * 否则 OS 杀进程。
     */
    fun buildProgressNotification(
        taskId: String,
        title: String,
        fraction: Float,
        message: String? = null,
    ): android.app.Notification {
        val openIntent = Intent(context, MainActivity::class.java)
        val pendingIntent = PendingIntent.getActivity(
            context, 0, openIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val progress = (fraction * 100).toInt().coerceIn(0, 100)
        return NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_launcher_foreground)
            .setContentTitle(title)
            .setContentText(message ?: "下载中 $progress%")
            .setProgress(100, progress, false)
            .setOngoing(true)
            .setContentIntent(pendingIntent)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
    }

    /**
     * 完成通知（success 档）。v0.1：单个任务完成就发。
     * v0.2 阶段 6 接入 notifyOnCompletion 三个档（success / all / summary）。
     */
    fun buildCompleteNotification(
        taskId: String,
        title: String,
        success: Boolean,
        localPath: String? = null,
    ): android.app.Notification {
        val text = if (success) {
            "完成：$title${localPath?.let { "\n$it" } ?: ""}"
        } else {
            "失败：$title"
        }
        return NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_launcher_foreground)
            .setContentTitle(if (success) "下载完成" else "下载失败")
            .setContentText(text)
            .setAutoCancel(true)
            .setPriority(NotificationCompat.PRIORITY_DEFAULT)
            .build()
    }

    fun notifyComplete(taskId: String, title: String, success: Boolean, localPath: String? = null) {
        val n = buildCompleteNotification(taskId, title, success, localPath)
        try {
            NotificationManagerCompat.from(context).notify(taskId.hashCode(), n)
        } catch (_: SecurityException) {
            // Android 13+ 需要 POST_NOTIFICATIONS 权限；阶段 5 加 Manifest 权限后正常
        }
    }

    private fun ensureChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val nm = context.getSystemService(NotificationManager::class.java) ?: return
        if (nm.getNotificationChannel(CHANNEL_ID) != null) return
        val channel = NotificationChannel(
            CHANNEL_ID,
            "下载进度",
            NotificationManager.IMPORTANCE_LOW,
        ).apply { description = "前台下载进度通知" }
        nm.createNotificationChannel(channel)
    }

    companion object {
        const val CHANNEL_ID = "doubi_download"
        const val PROGRESS_NOTIFICATION_ID = 1
    }
}
