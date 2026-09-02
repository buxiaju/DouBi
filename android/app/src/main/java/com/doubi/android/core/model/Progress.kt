package com.doubi.android.core.model

import java.util.Locale

/**
 * 下载进度。WorkManager Worker → NotificationHelper → Compose UI 三方共用。
 *
 * 桌面版对应：`src/doubi/core/pipeline.py:ProgressCallback`（Callable[[Progress], None]）。
 *
 * **速度 / ETA 来源**（欠账 #4，v0.1 已还）：
 * youtubedl-android 0.18.1 的 `StreamProcessExtractor` 用
 * `\[download\]\s+(\d+\.\d)% .* ETA (\d+):(\d+)` 解析 yt-dlp stdout，
 * 回调签名是 `(progress: Float /* 0-100 */, etaInSeconds: Long /* 未知为 -1 */, line: String)`。
 * 它**不给速度**，所以 [speedBytesPerSec] 由 [com.doubi.android.engine.ytdlp.YtDlpEngine]
 * 从原始行的 `at 1.23MiB/s` 片段自己解析。
 *
 * 两个字段都可空，且约定「非正数视为未知」——引擎报 -1 / 0 时上层统一当没有。
 */
data class Progress(
    /** 0.0 - 1.0。注意引擎侧回调是 0-100，转换在 YtDlpEngine 里做。 */
    val fraction: Float,
    /** 已经下载的字节数，optional（部分引擎不报）。 */
    val downloadedBytes: Long? = null,
    /** 总字节数，optional。 */
    val totalBytes: Long? = null,
    /** 引擎自己的状态文本，如 "Downloading video..."。 */
    val message: String? = null,
    /** 瞬时下载速度，字节/秒。null 或非正数 = 引擎没报。 */
    val speedBytesPerSec: Long? = null,
    /** 预计剩余秒数。null 或非正数 = 引擎没报（yt-dlp 未知时给 -1）。 */
    val etaSeconds: Long? = null,
) {
    /** 0 - 100 的整数百分比，给通知栏 `setProgress` 和 UI 文案用。 */
    val percent: Int get() = (fraction * 100).toInt().coerceIn(0, 100)

    /** 人类可读速度，如 "1.2 MB/s"；未知返回 null。 */
    val speedText: String? get() = speedBytesPerSec?.takeIf { it > 0 }?.let { formatSpeed(it) }

    /** 人类可读剩余时间，如 "03:21" / "1:02:03"；未知返回 null。 */
    val etaText: String? get() = etaSeconds?.takeIf { it > 0 }?.let { formatEta(it) }

    /**
     * 一行式状态文本，通知栏和历史页共用。
     * 有速度和 ETA 时形如 `下载中 45% · 1.2 MB/s · 剩 03:21`；
     * 都没有就退化成 `下载中 45%`。
     */
    fun statusLine(prefix: String = "下载中"): String {
        val parts = mutableListOf("$prefix $percent%")
        speedText?.let { parts += it }
        etaText?.let { parts += "剩 $it" }
        return parts.joinToString(" · ")
    }

    companion object {
        /**
         * 字节/秒 → 人类可读。用 1024 进制（跟 yt-dlp 的 KiB/MiB 一致），
         * 但标签写成 KB/MB——跟桌面版 `format_speed()` 的显示习惯对齐。
         */
        fun formatSpeed(bytesPerSec: Long): String {
            if (bytesPerSec <= 0) return "0 B/s"
            val units = listOf("B/s", "KB/s", "MB/s", "GB/s", "TB/s")
            var value = bytesPerSec.toDouble()
            var idx = 0
            while (value >= 1024.0 && idx < units.lastIndex) {
                value /= 1024.0
                idx++
            }
            return if (idx == 0) {
                "${value.toLong()} ${units[idx]}"
            } else {
                String.format(Locale.US, "%.1f %s", value, units[idx])
            }
        }

        /** 秒 → `mm:ss`，超过 1 小时用 `h:mm:ss`。 */
        fun formatEta(seconds: Long): String {
            if (seconds <= 0) return "00:00"
            val h = seconds / 3600
            val m = (seconds % 3600) / 60
            val s = seconds % 60
            return if (h > 0) {
                String.format(Locale.US, "%d:%02d:%02d", h, m, s)
            } else {
                String.format(Locale.US, "%02d:%02d", m, s)
            }
        }
    }
}
