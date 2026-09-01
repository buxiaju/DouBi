package com.doubi.android.core.model

/**
 * 下载选项。1:1 对拍桌面版 `src/doubi/core/models.py:DownloadOptions`（精简版）。
 *
 * v0.1 Android 端裁掉：`cancelCheck`（callable，跨进程不可序列化）、
 * `outputTemplate`（path 字段，单独算）—— 完整字段等 v0.2+ 加。
 *
 * 桌面版原始字段数 13，v0.1 保留 7 个真正影响下载行为的：
 * - 画质 / 容器 / 缩略图 / 字幕 / 断点续传
 * - 文件名模板 / 速率限制
 *
 * `proxy` / `rateLimit` / `aria2Secret` 走 `AppConfig`（DataStore），不重复存。
 */
data class DownloadOptions(
    /** 画质。桌面版 "best" / "1080p" / "720p" / ... */
    val maxQuality: String = "best",
    /** 容器。mp4 / mkv / webm。 */
    val container: String = "mp4",
    /** 是否写缩略图。 */
    val writeThumbnail: Boolean = false,
    /** 是否写字幕。 */
    val writeSubtitles: Boolean = false,
    /** 断点续传。 */
    val resume: Boolean = true,
    /** 文件名模板，`{title}_{item_id}` 之类。 */
    val filenameTemplate: String = "{title}_{item_id}",
    /** 速率限制，如 "1M" / "500K"，null 不限速。 */
    val rateLimit: String? = null,
    /** 代理 URL，null 直连。 */
    val proxy: String? = null,
)
