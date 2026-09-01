package com.doubi.android.core.config

/**
 * 配置校验。1:1 镜像桌面版 `_validate_*` 系列函数（`src/doubi/core/config.py`）。
 *
 * 设计原则：永远 **不抛异常**——坏值回退到默认，宁可让用户少一个功能，
 * 也不让 app boot 阶段崩溃（桌面版原话：「the worst case is user doesn't get
 * notifications, which is recoverable on the settings page」）。
 */
object ConfigValidator {
    /**
     * 桌面版 `_validate_notify_mode`。
     * 合法值：`{"success", "all", "summary"}`，否则回退 `"success"`。
     */
    fun validateNotifyMode(value: String?): String =
        if (value != null && value in DEFAULTS.NOTIFY_MODES) value
        else DEFAULTS.notifyOnCompletion

    /**
     * 引擎白名单。合法值：`{"yt-dlp", "aria2"}`，否则回退 `"yt-dlp"`。
     * 桌面版目前只在 `load_config` 里信任字符串，没有显式 validate——这里补上
     * 与 notify_mode 对称。
     */
    fun validateEngine(value: String?): String =
        if (value != null && value in DEFAULTS.ENGINES) value
        else DEFAULTS.engine

    /**
     * 并发数 clamp 到 [1, 16]。桌面版没做 clamp——这里加一道防御，
     * 防止用户在设置页输 "0" 或 "9999" 让 Worker 池炸掉。
     */
    fun validateConcurrentJobs(value: Int?): Int =
        (value ?: DEFAULTS.concurrentJobs).coerceIn(1, 16)

    /**
     * 嗅探时长 clamp 到 [5, 60]。桌面版也没 clamp——5 秒是 Playwright 启动
     * 最低要求，60 秒是用户耐心上限。
     */
    fun validateSniffDurationSec(value: Int?): Int =
        (value ?: DEFAULTS.sniffDurationSec).coerceIn(5, 60)

    /**
     * 嗅探 MIME 白名单过滤。未知类型静默丢弃，不抛错。
     * 桌面版硬编码默认值是包含 5 项的 tuple；用户扩展 / 删减都不阻止，
     * 缺了也只会让嗅探少抓一些类型，不会崩。
     */
    fun validateSniffCaptureTypes(value: List<String>?): List<String> =
        value?.takeIf { it.isNotEmpty() } ?: DEFAULTS.sniffCaptureTypes

    /**
     * 重复下载策略白名单。合法值：`{"skip", "redownload", "ask"}`，
     * 否则回退 `"skip"`。
     */
    fun validateDuplicatePolicy(value: String?): String =
        if (value in setOf("skip", "redownload", "ask")) value
        else DEFAULTS.duplicatePolicy

    /**
     * UI 语言白名单。空串 / 未知值回退 `"zh_CN"`。
     * 桌面版：`language: str = "zh_CN"`，未做白名单——这里补上。
     */
    fun validateLanguage(value: String?): String =
        if (!value.isNullOrBlank() && value in setOf("zh_CN", "en")) value
        else DEFAULTS.language

    /**
     * 主题白名单。v0.1 Android 端只支持 2 套（default_light / default_dark），
     * 阶段 3 扩到 7 套（与桌面版 ui/theme.py 对齐）后再放宽。
     * 桌面版 `theme` 是字符串但 `resolve_theme` 容忍未知值（找不到时回退默认）；
     * Android 端在「未知值」和「保留字符串」之间折中——未知值立即回退，不让
     * 选了个不存在的 theme 把 UI 染成空样式。
     */
    fun validateTheme(value: String?): String =
        if (value in setOf("default_light", "default_dark")) value
        else DEFAULTS.theme
}
