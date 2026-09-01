package com.doubi.android.data.config

import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import com.doubi.android.core.config.AppConfig
import com.doubi.android.core.config.ConfigValidator
import com.doubi.android.core.config.DEFAULTS
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

/**
 * AppConfig 持久化层（DataStore Preferences 实现）。
 *
 * 桌面版对照：`src/doubi/core/config.py:load_config` / `save_config`。
 *
 * **设计要点**：
 * 1. **空串 → null**：`rate_limit` / `proxy` / `aria2_secret` 在 DataStore 里
 *    用 `""` 表示 None（Preferences 没有 nullable string）。读出时转换回 `null`。
 * 2. **校验统一走 [ConfigValidator]**：所有字段读出来都过一遍白名单，坏值
 *    回退默认，不抛异常——与桌面版「bad value in config.yml should never break
 *    the app boot path」原则一致。
 * 3. **单 Preferences 原子写**：`edit { it[...] = ... }` 整个事务一起写，
 *    不会出现「写了一半一半」的状态。
 * 4. **观察者友好**：暴露 `Flow<AppConfig>`，UI 层 `collectAsStateWithLifecycle()`。
 */
class AppConfigDataStore(
    private val dataStore: DataStore<Preferences>,
) {
    /** 当前配置一次性读。给非响应式场景用（如启动时一次性取）。 */
    suspend fun get(): AppConfig = dataStore.data.first().toAppConfig()

    /** 配置观察流。桌面版没有等价物（YAML 文件监听是文件系统层的事）。 */
    fun observe(): Flow<AppConfig> = dataStore.data.map { it.toAppConfig() }

    /**
     * 整体替换。原子写——调用方应只在「导入备份 / 重置」场景用，
     * 单字段更新走 [updateField]。
     */
    suspend fun save(config: AppConfig) {
        dataStore.edit { prefs ->
            prefs[ConfigKeys.OUTPUT_ROOT] = config.outputRoot
            prefs[ConfigKeys.OUTPUT_DIR_TEMPLATE] = config.outputDirTemplate
            prefs[ConfigKeys.CONCURRENT_JOBS] = config.concurrentJobs
            prefs[ConfigKeys.CONTAINER] = config.container
            prefs[ConfigKeys.MAX_QUALITY] = config.maxQuality
            prefs[ConfigKeys.WRITE_THUMBNAIL] = config.writeThumbnail
            prefs[ConfigKeys.WRITE_METADATA_JSON] = config.writeMetadataJson
            prefs[ConfigKeys.WRITE_NFO] = config.writeNfo
            prefs[ConfigKeys.WRITE_DANMAKU] = config.writeDanmaku
            prefs[ConfigKeys.WRITE_SUBTITLES] = config.writeSubtitles
            prefs[ConfigKeys.RESUME] = config.resume
            prefs[ConfigKeys.FILENAME_TEMPLATE] = config.filenameTemplate
            prefs[ConfigKeys.RATE_LIMIT] = config.rateLimit ?: ""
            prefs[ConfigKeys.PROXY] = config.proxy ?: ""
            prefs[ConfigKeys.DATABASE] = config.database
            prefs[ConfigKeys.DATABASE_PATH] = config.databasePath
            prefs[ConfigKeys.MANIFEST_PATH] = config.manifestPath
            prefs[ConfigKeys.THEME] = config.theme
            prefs[ConfigKeys.PROMPT_BEFORE_DOWNLOAD] = config.promptBeforeDownload
            prefs[ConfigKeys.DUPLICATE_POLICY] = config.duplicatePolicy
            prefs[ConfigKeys.LANGUAGE] = config.language
            prefs[ConfigKeys.ENGINE] = config.engine
            prefs[ConfigKeys.ARIA2_RPC_URL] = config.aria2RpcUrl
            prefs[ConfigKeys.ARIA2_SECRET] = config.aria2Secret ?: ""
            prefs[ConfigKeys.SNIFF_ENABLED] = config.sniffEnabled
            prefs[ConfigKeys.SNIFF_DURATION_SEC] = config.sniffDurationSec
            prefs[ConfigKeys.SNIFF_HEADLESS] = config.sniffHeadless
            prefs[ConfigKeys.SNIFF_USER_AGENT] = config.sniffUserAgent
            prefs[ConfigKeys.SNIFF_AUTO_PLAY] = config.sniffAutoPlay
            prefs[ConfigKeys.SNIFF_CAPTURE_TYPES] = config.sniffCaptureTypes.toSet()
            prefs[ConfigKeys.NOTIFY_ON_COMPLETION] = config.notifyOnCompletion
        }
    }

    /**
     * 单字段更新。设置页「保存一项改一项」时用，避免重写整个 config
     * 触发其他字段的写入竞争。
     *
     * `value: Any?`——nullable 字段（proxy / rate_limit / aria2_secret）需要传 null
     * 表示「清空」。非 nullable 字段传 null 会在 cast 阶段抛 CCE（程序员错误），
     * 不静默吞。
     */
    suspend fun updateField(key: String, value: Any?) {
        dataStore.edit { prefs ->
            when (key) {
                "concurrent_jobs" -> prefs[ConfigKeys.CONCURRENT_JOBS] =
                    ConfigValidator.validateConcurrentJobs(value as Int?)
                "theme" -> prefs[ConfigKeys.THEME] = ConfigValidator.validateTheme(value as String?)
                "language" -> prefs[ConfigKeys.LANGUAGE] = ConfigValidator.validateLanguage(value as String?)
                "engine" -> prefs[ConfigKeys.ENGINE] = ConfigValidator.validateEngine(value as String?)
                "notify_on_completion" -> prefs[ConfigKeys.NOTIFY_ON_COMPLETION] =
                    ConfigValidator.validateNotifyMode(value as String?)
                "duplicate_policy" -> prefs[ConfigKeys.DUPLICATE_POLICY] =
                    ConfigValidator.validateDuplicatePolicy(value as String?)
                "sniff_duration_sec" -> prefs[ConfigKeys.SNIFF_DURATION_SEC] =
                    ConfigValidator.validateSniffDurationSec(value as Int?)
                "proxy" -> prefs[ConfigKeys.PROXY] = (value as? String) ?: ""
                "rate_limit" -> prefs[ConfigKeys.RATE_LIMIT] = (value as? String) ?: ""
                "aria2_secret" -> prefs[ConfigKeys.ARIA2_SECRET] = (value as? String) ?: ""
                "sniff_capture_types" -> {
                    @Suppress("UNCHECKED_CAST")
                    prefs[ConfigKeys.SNIFF_CAPTURE_TYPES] =
                        ConfigValidator.validateSniffCaptureTypes(value as? List<String>).toSet()
                }
                "sniff_enabled" -> prefs[ConfigKeys.SNIFF_ENABLED] = value as Boolean
                "sniff_headless" -> prefs[ConfigKeys.SNIFF_HEADLESS] = value as Boolean
                "sniff_auto_play" -> prefs[ConfigKeys.SNIFF_AUTO_PLAY] = value as Boolean
                "write_thumbnail" -> prefs[ConfigKeys.WRITE_THUMBNAIL] = value as Boolean
                "write_nfo" -> prefs[ConfigKeys.WRITE_NFO] = value as Boolean
                "write_danmaku" -> prefs[ConfigKeys.WRITE_DANMAKU] = value as Boolean
                "write_subtitles" -> prefs[ConfigKeys.WRITE_SUBTITLES] = value as Boolean
                "write_metadata_json" -> prefs[ConfigKeys.WRITE_METADATA_JSON] = value as Boolean
                "prompt_before_download" -> prefs[ConfigKeys.PROMPT_BEFORE_DOWNLOAD] = value as Boolean
                "resume" -> prefs[ConfigKeys.RESUME] = value as Boolean
                else -> throw IllegalArgumentException("Unknown config key: $key")
            }
        }
    }

    /**
     * Preferences → AppConfig 转换。所有字段过 [ConfigValidator]，
     * 坏值回退默认。
     */
    private fun Preferences.toAppConfig(): AppConfig = AppConfig(
        outputRoot = this[ConfigKeys.OUTPUT_ROOT] ?: DEFAULTS.outputRoot,
        outputDirTemplate = this[ConfigKeys.OUTPUT_DIR_TEMPLATE] ?: DEFAULTS.outputDirTemplate,
        concurrentJobs = ConfigValidator.validateConcurrentJobs(this[ConfigKeys.CONCURRENT_JOBS]),
        container = this[ConfigKeys.CONTAINER] ?: DEFAULTS.container,
        maxQuality = this[ConfigKeys.MAX_QUALITY] ?: DEFAULTS.maxQuality,
        writeThumbnail = this[ConfigKeys.WRITE_THUMBNAIL] ?: DEFAULTS.writeThumbnail,
        writeMetadataJson = this[ConfigKeys.WRITE_METADATA_JSON] ?: DEFAULTS.writeMetadataJson,
        writeNfo = this[ConfigKeys.WRITE_NFO] ?: DEFAULTS.writeNfo,
        writeDanmaku = this[ConfigKeys.WRITE_DANMAKU] ?: DEFAULTS.writeDanmaku,
        writeSubtitles = this[ConfigKeys.WRITE_SUBTITLES] ?: DEFAULTS.writeSubtitles,
        resume = this[ConfigKeys.RESUME] ?: DEFAULTS.resume,
        filenameTemplate = this[ConfigKeys.FILENAME_TEMPLATE] ?: DEFAULTS.filenameTemplate,
        rateLimit = this[ConfigKeys.RATE_LIMIT]?.takeIf { it.isNotEmpty() },
        proxy = this[ConfigKeys.PROXY]?.takeIf { it.isNotEmpty() },
        database = this[ConfigKeys.DATABASE] ?: DEFAULTS.database,
        databasePath = this[ConfigKeys.DATABASE_PATH] ?: DEFAULTS.databasePath,
        manifestPath = this[ConfigKeys.MANIFEST_PATH] ?: DEFAULTS.manifestPath,
        theme = ConfigValidator.validateTheme(this[ConfigKeys.THEME]),
        promptBeforeDownload = this[ConfigKeys.PROMPT_BEFORE_DOWNLOAD] ?: DEFAULTS.promptBeforeDownload,
        duplicatePolicy = ConfigValidator.validateDuplicatePolicy(this[ConfigKeys.DUPLICATE_POLICY]),
        language = ConfigValidator.validateLanguage(this[ConfigKeys.LANGUAGE]),
        engine = ConfigValidator.validateEngine(this[ConfigKeys.ENGINE]),
        aria2RpcUrl = this[ConfigKeys.ARIA2_RPC_URL] ?: DEFAULTS.aria2RpcUrl,
        aria2Secret = this[ConfigKeys.ARIA2_SECRET]?.takeIf { it.isNotEmpty() },
        sniffEnabled = this[ConfigKeys.SNIFF_ENABLED] ?: DEFAULTS.sniffEnabled,
        sniffDurationSec = ConfigValidator.validateSniffDurationSec(this[ConfigKeys.SNIFF_DURATION_SEC]),
        sniffHeadless = this[ConfigKeys.SNIFF_HEADLESS] ?: DEFAULTS.sniffHeadless,
        sniffUserAgent = this[ConfigKeys.SNIFF_USER_AGENT] ?: DEFAULTS.sniffUserAgent,
        sniffAutoPlay = this[ConfigKeys.SNIFF_AUTO_PLAY] ?: DEFAULTS.sniffAutoPlay,
        sniffCaptureTypes = ConfigValidator.validateSniffCaptureTypes(
            // LinkedHashSet 保留写入顺序——不 sorted，roundtrip 才能保序
            this[ConfigKeys.SNIFF_CAPTURE_TYPES]?.toList(),
        ),
        notifyOnCompletion = ConfigValidator.validateNotifyMode(this[ConfigKeys.NOTIFY_ON_COMPLETION]),
    )
}
