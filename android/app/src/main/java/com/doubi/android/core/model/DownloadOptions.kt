package com.doubi.android.core.model

/**
 * 下载选项。1:1 对拍桌面版 `src/doubi/core/models.py:DownloadOptions`（精简版）。
 *
 * v0.1 Android 端裁掉：`cancelCheck`（callable，跨进程不可序列化）。
 *
 * 桌面版原始字段数 13，v0.1 保留 9 个真正影响下载行为的：
 * - 画质 / 容器 / 缩略图 / 字幕 / 断点续传
 * - 文件名模板 / 速率限制 / 代理
 * - **输出根 + 目录模板**（欠账 #2 已还：Engine 真正消费，不再空转）
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
    /**
     * 文件名模板，`{title}_{item_id}` 之类。`null` = 用平台默认（与桌面版一致）。
     * **欠账 #2 已还**：v0.1 之前 `YtDlpEngine` 没消费这个字段，文件名硬编 `{itemId}.{ext}`。
     * 现在 [com.doubi.android.engine.ytdlp.YtDlpEngine] 用它做 yt-dlp `-o` 模板。
     */
    val filenameTemplate: String? = "{title}_{item_id}",
    /**
     * 速率限制，如 "1M" / "500K"，null 不限速。
     */
    val rateLimit: String? = null,
    /** 代理 URL，null 直连。 */
    val proxy: String? = null,
    /**
     * 输出根目录的**子路径**（相对 `baseOutputDir`），如 `Downloaded` / `MyVideos`。
     * 桌面版 `AppConfig.output_root` 是直接路径（`./Downloaded`），Android 端把它当
     * `baseOutputDir` 的子目录，**永远不写在 `context.filesDir` 外面**（那会需要
     * `WRITE_EXTERNAL_STORAGE` 权限，阶段 5 之前不开）。
     * **欠账 #2 已还**：v0.1 之前 Worker 直接拿 `baseOutputDir/platform/{itemId}.{ext}`，
     * 完全忽略这个字段。Engine 现在拼成 `baseOutputDir/outputRoot/<dirTemplate>/<filename>`。
     */
    val outputRoot: String? = "Downloaded",
    /**
     * 目录模板，相对 `outputRoot`。`{platform}` / `{author}` / `{media_type}` 占位符。
     * 例：`{platform}/{author}/{media_type}` → `youtube/Smith/VIDEO/`。
     * 任意段为 null/空时该段降级为 `_`。
     */
    val outputDirTemplate: String? = "{platform}/{author}/{media_type}",
)
