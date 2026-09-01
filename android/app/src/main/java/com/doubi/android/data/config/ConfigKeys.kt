package com.doubi.android.data.config

import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.core.stringSetPreferencesKey

/**
 * DataStore Preferences Keys。
 *
 * 桌面版对照：`src/doubi/core/config.py:DEFAULTS`。
 * Key 字符串保留**桌面版字段名**（snake_case）——这样以后写跨平台诊断工具
 * （比如「桌面版 / Android 版配置对比」脚本）能直接 key 1:1 对拍。
 * Kotlin 端访问用 camelCase 字段（AppConfig 的属性名）。
 */
object ConfigKeys {
    // ---- 路径 / 输出 ----
    val OUTPUT_ROOT = stringPreferencesKey("output_root")
    val OUTPUT_DIR_TEMPLATE = stringPreferencesKey("output_dir_template")
    val CONCURRENT_JOBS = intPreferencesKey("concurrent_jobs")
    val CONTAINER = stringPreferencesKey("container")
    val MAX_QUALITY = stringPreferencesKey("max_quality")

    // ---- 文件附件 ----
    val WRITE_THUMBNAIL = booleanPreferencesKey("write_thumbnail")
    val WRITE_METADATA_JSON = booleanPreferencesKey("write_metadata_json")
    val WRITE_NFO = booleanPreferencesKey("write_nfo")
    val WRITE_DANMAKU = booleanPreferencesKey("write_danmaku")
    val WRITE_SUBTITLES = booleanPreferencesKey("write_subtitles")

    // ---- 行为 ----
    val RESUME = booleanPreferencesKey("resume")
    val FILENAME_TEMPLATE = stringPreferencesKey("filename_template")
    val RATE_LIMIT = stringPreferencesKey("rate_limit")          // 空串表示 null
    val PROXY = stringPreferencesKey("proxy")                    // 空串表示 null

    // ---- 路径配置（Android 端不消费）----
    val DATABASE = booleanPreferencesKey("database")
    val DATABASE_PATH = stringPreferencesKey("database_path")
    val MANIFEST_PATH = stringPreferencesKey("manifest_path")

    // ---- 主题 ----
    val THEME = stringPreferencesKey("theme")

    // ---- GUI 偏好 ----
    val PROMPT_BEFORE_DOWNLOAD = booleanPreferencesKey("prompt_before_download")
    val DUPLICATE_POLICY = stringPreferencesKey("duplicate_policy")
    val LANGUAGE = stringPreferencesKey("language")

    // ---- 引擎 ----
    val ENGINE = stringPreferencesKey("engine")
    val ARIA2_RPC_URL = stringPreferencesKey("aria2_rpc_url")
    val ARIA2_SECRET = stringPreferencesKey("aria2_secret")      // 空串表示 null

    // ---- 通用嗅探 ----
    val SNIFF_ENABLED = booleanPreferencesKey("sniff_enabled")
    val SNIFF_DURATION_SEC = intPreferencesKey("sniff_duration_sec")
    val SNIFF_HEADLESS = booleanPreferencesKey("sniff_headless")
    val SNIFF_USER_AGENT = stringPreferencesKey("sniff_user_agent")
    val SNIFF_AUTO_PLAY = booleanPreferencesKey("sniff_auto_play")
    /**
     * Set<String> 形式——比 newline-separated String 更原生。
     * 注意：DataStore Set 没有顺序保证，存读可能顺序不同。
     * 桌面版用 tuple（有序），Android 端用 sortedSet 读出来再变 List 即可。
     */
    val SNIFF_CAPTURE_TYPES = stringSetPreferencesKey("sniff_capture_types")

    // ---- 通知 ----
    val NOTIFY_ON_COMPLETION = stringPreferencesKey("notify_on_completion")
}
