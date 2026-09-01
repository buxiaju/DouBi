package com.doubi.android.engine.ytdlp

import com.doubi.android.core.model.DownloadOptions
import com.doubi.android.core.model.DownloadResult
import com.doubi.android.core.model.MediaItem
import com.doubi.android.core.model.Platform
import com.doubi.android.core.model.Progress
import com.doubi.android.engine.Engine

/**
 * yt-dlp 引擎——**当前是占位 stub**。
 *
 * **状态（v0.1，2026-09-02）**：`yausername/yt-dlp-android:core:2024.10.27` 在
 * JitPack 上 401 Unauthorized，无法解析依赖。完整实现版本被 stash 到
 * `.scratch/phase2_ytdlp_unused/YtDlpEngine.kt.bak` 作参考。
 *
 * **stub 行为**：
 * - `supports()` 返回 true（让 UI 看起来「支持 YouTube」）
 * - `probe()` 返回一个最小可用 `MediaItem`（id = URL hash，title = URL）
 * - `download()` 立即返回 `Failure("yt-dlp-android 集成未启用")`
 *
 * **v0.2 恢复路径**（按推荐顺序）：
 * 1. 试 Maven Central 是否有 yausername 镜像：`io.github.yausername.*`
 * 2. 用 fork：[JunkFood02/yt-dlp-android](https://github.com/junkfood02/yt-dlp-android)
 *    （Maven Central 可用，持续维护）
 * 3. 退到 yt-dlp 子进程方案：自己下 yt-dlp 静态二进制 + `Runtime.exec()`
 * 4. 极端：自研 OkHttp + M3U8 解析，仅 YouTube 走 token 嗅探
 *
 * 任何方案恢复后，**把 `.bak` 文件覆盖回原位 + 取消 build.gradle.kts 里
 * `ytdlp-android` 依赖的注释**即可，无需改其他文件。
 */
class YtDlpEngine(
    @Suppress("UNUSED_PARAMETER") private val baseOutputDir: java.io.File,
) : Engine {

    override val name: String = "yt-dlp"

    override fun supports(url: String, options: DownloadOptions): Boolean {
        val u = url.lowercase()
        return u.contains("youtube.com") || u.contains("youtu.be") ||
            u.startsWith("http://") || u.startsWith("https://")
    }

    override suspend fun probe(url: String, options: DownloadOptions): MediaItem =
        MediaItem(
            platform = if (url.contains("youtu")) Platform.YOUTUBE else Platform.GENERIC,
            itemId = url.hashCode().toString(),
            sourceUrl = url,
            title = url,  // 嗅探不可用——UI 显示 URL
        )

    override suspend fun download(
        item: MediaItem,
        options: DownloadOptions,
        onProgress: suspend (Progress) -> Unit,
    ): DownloadResult = DownloadResult.Failure(
        "yt-dlp-android 集成未启用：JitPack 401 Unauthorized。详见 android/docs/phases/phase-2.md"
    )
}
