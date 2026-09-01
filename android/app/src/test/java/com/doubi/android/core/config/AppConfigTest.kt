package com.doubi.android.core.config

import com.google.common.truth.Truth.assertThat
import org.junit.Test

/**
 * 桌面版对照：`tests/test_config_theme.py`。
 *
 * 这一组单测只验两个东西：
 * 1. 默认值（`DEFAULTS`）跟桌面版 `core/config.py:DEFAULTS` 1:1
 * 2. `ConfigValidator` 各类白名单/边界/回退与桌面版 `_validate_*` 系列等价
 *
 * DataStore 读写往返测试在 [AppConfigDataStoreTest]（单独文件，
 * 因为需要真实 `DataStore<Preferences>` 实例和协程作用域）。
 */
class AppConfigTest {

    // ---------------------------------------------------------------------
    // 默认值对拍
    // ---------------------------------------------------------------------

    @Test
    fun `defaults match desktop core config py DEFAULTS`() {
        val d = DEFAULTS
        // 路径 / 输出
        assertThat(d.outputRoot).isEqualTo("./Downloaded")
        assertThat(d.outputDirTemplate).isEqualTo("{platform}/{author}/{media_type}")
        assertThat(d.concurrentJobs).isEqualTo(3)
        assertThat(d.container).isEqualTo("mp4")
        assertThat(d.maxQuality).isEqualTo("best")
        // 文件附件
        assertThat(d.writeThumbnail).isFalse()
        assertThat(d.writeMetadataJson).isFalse()
        assertThat(d.writeNfo).isFalse()
        assertThat(d.writeDanmaku).isFalse()
        assertThat(d.writeSubtitles).isFalse()
        // 行为
        assertThat(d.resume).isTrue()
        assertThat(d.filenameTemplate).isEqualTo("{title}_{item_id}")
        assertThat(d.rateLimit).isNull()
        assertThat(d.proxy).isNull()
        // 路径配置
        assertThat(d.database).isTrue()
        assertThat(d.databasePath).isEqualTo("doubi.db")
        assertThat(d.manifestPath).isEqualTo("download_manifest.jsonl")
        // 主题 / 偏好
        assertThat(d.theme).isEqualTo("default_light")
        assertThat(d.promptBeforeDownload).isFalse()
        assertThat(d.duplicatePolicy).isEqualTo("skip")
        assertThat(d.language).isEqualTo("zh_CN")
        // 引擎
        assertThat(d.engine).isEqualTo("yt-dlp")
        assertThat(d.aria2RpcUrl).isEqualTo("http://127.0.0.1:6800/jsonrpc")
        assertThat(d.aria2Secret).isNull()
        // 嗅探
        assertThat(d.sniffEnabled).isTrue()
        assertThat(d.sniffDurationSec).isEqualTo(15)
        assertThat(d.sniffHeadless).isTrue()
        assertThat(d.sniffUserAgent).isEqualTo("")
        assertThat(d.sniffAutoPlay).isTrue()
        assertThat(d.sniffCaptureTypes).containsExactly(
            "video/mp4", "video/webm", "video/mp2t",
            "application/vnd.apple.mpegurl", "application/dash+xml",
        ).inOrder()
        // 通知
        assertThat(d.notifyOnCompletion).isEqualTo("success")
    }

    @Test
    fun `default AppConfig instance has all defaults`() {
        val cfg = AppConfig()
        assertThat(cfg.concurrentJobs).isEqualTo(DEFAULTS.concurrentJobs)
        assertThat(cfg.theme).isEqualTo("default_light")
        assertThat(cfg.engine).isEqualTo("yt-dlp")
        assertThat(cfg.notifyOnCompletion).isEqualTo("success")
        assertThat(cfg.sniffCaptureTypes).hasSize(5)
    }

    // ---------------------------------------------------------------------
    // ConfigValidator 校验
    // ---------------------------------------------------------------------

    @Test
    fun `notify_on_completion whitelist accepts three values`() {
        // 桌面版 _validate_notify_mode: 合法值原样，非法值回退 "success"
        assertThat(ConfigValidator.validateNotifyMode("success")).isEqualTo("success")
        assertThat(ConfigValidator.validateNotifyMode("all")).isEqualTo("all")
        assertThat(ConfigValidator.validateNotifyMode("summary")).isEqualTo("summary")
    }

    @Test
    fun `notify_on_completion rejects unknown values silently`() {
        assertThat(ConfigValidator.validateNotifyMode("always")).isEqualTo("success")
        assertThat(ConfigValidator.validateNotifyMode("")).isEqualTo("success")
        assertThat(ConfigValidator.validateNotifyMode(null)).isEqualTo("success")
        // 大小写敏感
        assertThat(ConfigValidator.validateNotifyMode("Success")).isEqualTo("success")
    }

    @Test
    fun `engine whitelist accepts yt-dlp and aria2`() {
        assertThat(ConfigValidator.validateEngine("yt-dlp")).isEqualTo("yt-dlp")
        assertThat(ConfigValidator.validateEngine("aria2")).isEqualTo("aria2")
    }

    @Test
    fun `engine rejects unknown values silently`() {
        assertThat(ConfigValidator.validateEngine("ffmpeg")).isEqualTo("yt-dlp")
        assertThat(ConfigValidator.validateEngine(null)).isEqualTo("yt-dlp")
    }

    @Test
    fun `concurrent_jobs clamped to 1-16 range`() {
        assertThat(ConfigValidator.validateConcurrentJobs(null)).isEqualTo(3)
        assertThat(ConfigValidator.validateConcurrentJobs(0)).isEqualTo(1)
        assertThat(ConfigValidator.validateConcurrentJobs(1)).isEqualTo(1)
        assertThat(ConfigValidator.validateConcurrentJobs(8)).isEqualTo(8)
        assertThat(ConfigValidator.validateConcurrentJobs(16)).isEqualTo(16)
        assertThat(ConfigValidator.validateConcurrentJobs(17)).isEqualTo(16)
        assertThat(ConfigValidator.validateConcurrentJobs(9999)).isEqualTo(16)
        // 负数也会被 clamp 到 1
        assertThat(ConfigValidator.validateConcurrentJobs(-5)).isEqualTo(1)
    }

    @Test
    fun `sniff_duration_sec clamped to 5-60 range`() {
        assertThat(ConfigValidator.validateSniffDurationSec(null)).isEqualTo(15)
        assertThat(ConfigValidator.validateSniffDurationSec(0)).isEqualTo(5)
        assertThat(ConfigValidator.validateSniffDurationSec(5)).isEqualTo(5)
        assertThat(ConfigValidator.validateSniffDurationSec(30)).isEqualTo(30)
        assertThat(ConfigValidator.validateSniffDurationSec(60)).isEqualTo(60)
        assertThat(ConfigValidator.validateSniffDurationSec(61)).isEqualTo(60)
    }

    @Test
    fun `sniff_capture_types falls back to default when null or empty`() {
        assertThat(ConfigValidator.validateSniffCaptureTypes(null))
            .isEqualTo(DEFAULTS.sniffCaptureTypes)
        assertThat(ConfigValidator.validateSniffCaptureTypes(emptyList()))
            .isEqualTo(DEFAULTS.sniffCaptureTypes)
        // 非空保留（不做白名单过滤——用户可扩展）
        val custom = listOf("video/x-matroska", "application/x-mpegURL")
        assertThat(ConfigValidator.validateSniffCaptureTypes(custom)).isEqualTo(custom)
    }

    @Test
    fun `duplicate_policy whitelist`() {
        assertThat(ConfigValidator.validateDuplicatePolicy("skip")).isEqualTo("skip")
        assertThat(ConfigValidator.validateDuplicatePolicy("redownload")).isEqualTo("redownload")
        assertThat(ConfigValidator.validateDuplicatePolicy("ask")).isEqualTo("ask")
        assertThat(ConfigValidator.validateDuplicatePolicy("ask-user")).isEqualTo("skip")
        assertThat(ConfigValidator.validateDuplicatePolicy(null)).isEqualTo("skip")
    }

    @Test
    fun `language whitelist accepts zh_CN and en`() {
        assertThat(ConfigValidator.validateLanguage("zh_CN")).isEqualTo("zh_CN")
        assertThat(ConfigValidator.validateLanguage("en")).isEqualTo("en")
        assertThat(ConfigValidator.validateLanguage("")).isEqualTo("zh_CN")
        assertThat(ConfigValidator.validateLanguage(null)).isEqualTo("zh_CN")
        assertThat(ConfigValidator.validateLanguage("zh")).isEqualTo("zh_CN")  // zh 不在白名单
    }

    @Test
    fun `theme whitelist accepts v0_1 themes`() {
        assertThat(ConfigValidator.validateTheme("default_light")).isEqualTo("default_light")
        assertThat(ConfigValidator.validateTheme("default_dark")).isEqualTo("default_dark")
        // 阶段 3 扩到 7 套（doubi / 深海 / 莫兰迪 / 护眼 / 高对比）后这里要放宽
        assertThat(ConfigValidator.validateTheme("doubi")).isEqualTo("default_light")
    }

    // ---------------------------------------------------------------------
    // AppConfig.toMap 字段名 1:1 对拍桌面版
    // ---------------------------------------------------------------------

    @Test
    fun `toMap keys match desktop field names exactly`() {
        val keys = AppConfig().toMap().keys
        // 这 30 个 key 必须在（YAML 兼容字段，跨平台诊断用）
        val required = setOf(
            "output_root", "output_dir_template", "concurrent_jobs", "container", "max_quality",
            "write_thumbnail", "write_metadata_json", "write_nfo", "write_danmaku", "write_subtitles",
            "resume", "filename_template", "rate_limit", "proxy",
            "database", "database_path", "manifest_path",
            "theme", "prompt_before_download", "duplicate_policy", "language",
            "engine", "aria2_rpc_url", "aria2_secret",
            "sniff_enabled", "sniff_duration_sec", "sniff_headless",
            "sniff_user_agent", "sniff_auto_play", "sniff_capture_types",
            "notify_on_completion",
        )
        assertThat(keys).containsAtLeastElementsIn(required)
    }
}
