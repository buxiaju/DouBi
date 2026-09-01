package com.doubi.android.core.model

/**
 * 下载进度。WorkManager Worker → NotificationHelper → Compose UI 三方共用。
 *
 * 桌面版对应：`src/doubi/core/pipeline.py:ProgressCallback`（Callable[[Progress], None]）。
 * v0.1 Android 端只保留 3 个必要字段；其他（speed / eta）留 v0.2+。
 */
data class Progress(
    /** 0.0 - 1.0。 */
    val fraction: Float,
    /** 已经下载的字节数，optional（部分引擎不报）。 */
    val downloadedBytes: Long? = null,
    /** 总字节数，optional。 */
    val totalBytes: Long? = null,
    /** 引擎自己的状态文本，如 "Downloading video..."。 */
    val message: String? = null,
)
