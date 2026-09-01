package com.doubi.android.core.config

/**
 * DouBi Android 应用配置。
 *
 * 桌面版对照：`src/doubi/core/config.py:AppConfig`（25 字段）。
 * 字段名 snake → camel，业务意义 1:1 一致。
 *
 * 字段分组（与桌面版 `DEFAULTS` 注释对齐）：
 * - 路径 / 输出控制：outputRoot / outputDirTemplate / concurrentJobs / container / maxQuality
 * - 文件附件：writeThumbnail / writeMetadataJson / writeNfo / writeDanmaku / writeSubtitles
 * - 行为：resume / filenameTemplate / rateLimit / proxy
 * - 路径配置（Android 端不再需要，保留字段名仅为文档对齐）：database / databasePath / manifestPath
 * - 主题：theme
 * - GUI 偏好：promptBeforeDownload / duplicatePolicy / language
 * - 引擎：engine / aria2RpcUrl / aria2Secret
 * - 通用嗅探：sniffEnabled / sniffDurationSec / sniffHeadless / sniffUserAgent / sniffAutoPlay / sniffCaptureTypes
 * - 通知：notifyOnCompletion
 *
 * 不可序列化的运行时字段（桌面版 `extra: dict[str, Any]`）放这里，DataStore 不写它——临时覆盖用
 * `core/config/ConfigRepository.putExtra(key, value)` 单独管理。
 *
 * 校验规则（与桌面版 `_validate_*` 系列函数对拍）：
 * - `notifyOnCompletion` 白名单 `{"success", "all", "summary"}`，非法值回退默认 "success"
 * - `engine` 白名单 `{"yt-dlp", "aria2"}`，非法值回退 "yt-dlp"
 * - `concurrentJobs` clamp 到 [1, 16]
 * - `sniffDurationSec` clamp 到 [5, 60]
 * - 详见 [ConfigValidator]
 */
data class AppConfig(
    // ---- 路径 / 输出 ----
    val outputRoot: String = DEFAULTS.outputRoot,
    val outputDirTemplate: String = DEFAULTS.outputDirTemplate,
    val concurrentJobs: Int = DEFAULTS.concurrentJobs,
    val container: String = DEFAULTS.container,
    val maxQuality: String = DEFAULTS.maxQuality,

    // ---- 文件附件 ----
    val writeThumbnail: Boolean = DEFAULTS.writeThumbnail,
    val writeMetadataJson: Boolean = DEFAULTS.writeMetadataJson,
    val writeNfo: Boolean = DEFAULTS.writeNfo,
    val writeDanmaku: Boolean = DEFAULTS.writeDanmaku,
    val writeSubtitles: Boolean = DEFAULTS.writeSubtitles,

    // ---- 行为 ----
    val resume: Boolean = DEFAULTS.resume,
    val filenameTemplate: String = DEFAULTS.filenameTemplate,
    val rateLimit: String? = DEFAULTS.rateLimit,
    val proxy: String? = DEFAULTS.proxy,

    // ---- 路径配置（Android 端不消费，保留仅为 schema 对齐）----
    val database: Boolean = DEFAULTS.database,
    val databasePath: String = DEFAULTS.databasePath,
    val manifestPath: String = DEFAULTS.manifestPath,

    // ---- 主题 ----
    val theme: String = DEFAULTS.theme,

    // ---- GUI 偏好 ----
    val promptBeforeDownload: Boolean = DEFAULTS.promptBeforeDownload,
    val duplicatePolicy: String = DEFAULTS.duplicatePolicy,
    val language: String = DEFAULTS.language,

    // ---- 引擎 ----
    val engine: String = DEFAULTS.engine,
    val aria2RpcUrl: String = DEFAULTS.aria2RpcUrl,
    val aria2Secret: String? = DEFAULTS.aria2Secret,

    // ---- 通用嗅探 ----
    val sniffEnabled: Boolean = DEFAULTS.sniffEnabled,
    val sniffDurationSec: Int = DEFAULTS.sniffDurationSec,
    val sniffHeadless: Boolean = DEFAULTS.sniffHeadless,
    val sniffUserAgent: String = DEFAULTS.sniffUserAgent,
    val sniffAutoPlay: Boolean = DEFAULTS.sniffAutoPlay,
    val sniffCaptureTypes: List<String> = DEFAULTS.sniffCaptureTypes,

    // ---- 通知 ----
    val notifyOnCompletion: String = DEFAULTS.notifyOnCompletion,
) {
    /**
     * 桌面版对照：`src/doubi/core/config.py:AppConfig.to_dict()`。
     * Android 端不需要——DataStore 走 Preferences Keys 一项一项写，不用 dict 序列化。
     * 保留方法仅为 API 完整 + 给「导出诊断」之类的工具用。
     */
    fun toMap(): Map<String, Any> = mapOf(
        "output_root" to outputRoot,
        "output_dir_template" to outputDirTemplate,
        "concurrent_jobs" to concurrentJobs,
        "container" to container,
        "max_quality" to maxQuality,
        "write_thumbnail" to writeThumbnail,
        "write_metadata_json" to writeMetadataJson,
        "write_nfo" to writeNfo,
        "write_danmaku" to writeDanmaku,
        "write_subtitles" to writeSubtitles,
        "resume" to resume,
        "filename_template" to filenameTemplate,
        "rate_limit" to (rateLimit ?: ""),
        "proxy" to (proxy ?: ""),
        "database" to database,
        "database_path" to databasePath,
        "manifest_path" to manifestPath,
        "theme" to theme,
        "prompt_before_download" to promptBeforeDownload,
        "duplicate_policy" to duplicatePolicy,
        "language" to language,
        "engine" to engine,
        "aria2_rpc_url" to aria2RpcUrl,
        "aria2_secret" to (aria2Secret ?: ""),
        "sniff_enabled" to sniffEnabled,
        "sniff_duration_sec" to sniffDurationSec,
        "sniff_headless" to sniffHeadless,
        "sniff_user_agent" to sniffUserAgent,
        "sniff_auto_play" to sniffAutoPlay,
        "sniff_capture_types" to sniffCaptureTypes.joinToString("\n"),
        "notify_on_completion" to notifyOnCompletion,
    )

    companion object {
        /** 桌面版 `core/config.py:DEFAULTS` 的 1:1 镜像。 */
        object DEFAULTS {
            const val outputRoot: String = "./Downloaded"
            const val outputDirTemplate: String = "{platform}/{author}/{media_type}"
            const val concurrentJobs: Int = 3
            const val container: String = "mp4"
            const val maxQuality: String = "best"
            const val writeThumbnail: Boolean = false
            const val writeMetadataJson: Boolean = false
            const val writeNfo: Boolean = false
            const val writeDanmaku: Boolean = false
            const val writeSubtitles: Boolean = false
            const val resume: Boolean = true
            const val filenameTemplate: String = "{title}_{item_id}"
            val rateLimit: String? = null
            val proxy: String? = null
            const val database: Boolean = true
            const val databasePath: String = "doubi.db"
            const val manifestPath: String = "download_manifest.jsonl"
            const val theme: String = "default_light"
            const val promptBeforeDownload: Boolean = false
            const val duplicatePolicy: String = "skip"
            const val language: String = "zh_CN"
            const val engine: String = "yt-dlp"
            const val aria2RpcUrl: String = "http://127.0.0.1:6800/jsonrpc"
            val aria2Secret: String? = null
            const val sniffEnabled: Boolean = true
            const val sniffDurationSec: Int = 15
            const val sniffHeadless: Boolean = true
            const val sniffUserAgent: String = ""
            const val sniffAutoPlay: Boolean = true
            val sniffCaptureTypes: List<String> = listOf(
                "video/mp4",
                "video/webm",
                "video/mp2t",
                "application/vnd.apple.mpegurl",
                "application/dash+xml",
            )
            const val notifyOnCompletion: String = "success"

            /** 通知白名单。桌面版 `_validate_notify_mode` 用 set 字面量；这里 Kotlin 用 setOf。 */
            val NOTIFY_MODES: Set<String> = setOf("success", "all", "summary")

            /** 引擎白名单。 */
            val ENGINES: Set<String> = setOf("yt-dlp", "aria2")
        }
    }
}
