package com.doubi.android.engine

import com.doubi.android.core.model.DownloadOptions
import com.doubi.android.core.model.DownloadResult
import com.doubi.android.core.model.MediaItem
import com.doubi.android.core.model.Progress

/**
 * 下载引擎抽象。1:1 对拍桌面版 `src/doubi/engines/__init__.py:Engine` ABC。
 *
 * 桌面版用 ABC（abstract base class）+ asyncio；Android 端用 `interface` +
 * coroutines（`suspend fun`）。心智模型完全一致：
 * 1. `name` 标识（"yt-dlp" / "ffmpeg" / "aria2"），Worker 写到 PendingTask.engine 字段
 * 2. `supports(url, options)` 预判该引擎能否处理这条 URL
 * 3. `probe(url, options)` 嗅探出 MediaItem（标题 / 时长 / 缩略图 URL）
 * 4. `download(item, options, onProgress)` 真下载，进度回调 + 返回最终结果
 *
 * **线程模型**：`probe` / `download` 都是 `suspend`，调用方负责在协程里跑。
 * 实现里 `suspendCancellableCoroutine` + 引擎的 callback API 包成挂起函数。
 */
interface Engine {
    /** 引擎名，匹配 `AppConfig.engine` 取值。 */
    val name: String

    /**
     * 该引擎能否处理这条 URL。
     * 桌面版：`Engine.supports(url, options) -> bool`
     * v0.1 Android：简单 URL 模式匹配（YouTube 看域名 / generic 永远 true）。
     */
    fun supports(url: String, options: DownloadOptions): Boolean

    /**
     * 嗅探——给 URL 拿 MediaItem（id / title / author / duration）。
     * 桌面版：`async def probe(url, options) -> MediaItem`
     * 失败抛异常（callers wrap in try/catch）。
     */
    suspend fun probe(url: String, options: DownloadOptions): MediaItem

    /**
     * 下载。`onProgress` 是挂起函数，调用方在协程里 await。
     * 桌面版：`async def download(item, options, on_progress) -> DownloadResult`
     */
    suspend fun download(
        item: MediaItem,
        options: DownloadOptions,
        onProgress: suspend (Progress) -> Unit,
    ): DownloadResult
}
