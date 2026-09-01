package com.doubi.android.core.config

import com.doubi.android.core.model.DownloadOptions

/**
 * AppConfig → DownloadOptions 转换。
 *
 * 桌面版 `core/pipeline.py:DownloadPipeline` 在每次入队时构造 DownloadOptions，
 * 字段来自 `AppConfig` + 任务级 override。Android 端把「默认从 AppConfig 派生」
 * 的逻辑独立出来，UI 设置页（阶段 6）可以 override 单个字段。
 *
 * 字段映射：
 * | AppConfig | DownloadOptions |
 * |---|---|
 * | `maxQuality` | `maxQuality` |
 * | `container` | `container` |
 * | `writeThumbnail` | `writeThumbnail` |
 * | `writeSubtitles` | `writeSubtitles` |
 * | `resume` | `resume` |
 * | `filenameTemplate` | `filenameTemplate` |
 * | `rateLimit` | `rateLimit` |
 * | `proxy` | `proxy` |
 *
 * 不映射的（v0.1 不需要或 UI 没消费）：`writeNfo` / `writeDanmaku` /
 * `writeMetadataJson` / `outputDirTemplate`（路径模板另外算）。
 */
fun AppConfig.toDownloadOptions(): DownloadOptions = DownloadOptions(
    maxQuality = maxQuality,
    container = container,
    writeThumbnail = writeThumbnail,
    writeSubtitles = writeSubtitles,
    resume = resume,
    filenameTemplate = filenameTemplate,
    rateLimit = rateLimit,
    proxy = proxy,
)
