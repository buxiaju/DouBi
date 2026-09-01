package com.doubi.android.engine.ytdlp

import com.doubi.android.core.model.Author
import com.doubi.android.core.model.DownloadOptions
import com.doubi.android.core.model.DownloadResult
import com.doubi.android.core.model.MediaItem
import com.doubi.android.core.model.MediaType
import com.doubi.android.core.model.Platform
import com.doubi.android.core.model.Progress
import com.doubi.android.engine.Engine
import com.yausername.youtubedl_android.YoutubeDL
import com.yausername.youtubedl_android.YoutubeDLException
import com.yausername.youtubedl_android.YoutubeDLRequest
import com.yausername.youtubedl_android.mapper.VideoInfo
import kotlinx.coroutines.CancellableContinuation
import kotlinx.coroutines.suspendCancellableCoroutine
import java.io.File
import kotlin.coroutines.resume

/**
 * yt-dlp 引擎。1:1 对拍桌面版 `src/doubi/engines/yt_dlp.py`。
 *
 * 桌面版用 Python `yt_dlp` + `asyncio.to_thread` 包装 sync API；
 * Android 端用 [JunkFood02/yausername/youtubedl-android] fork（Maven Central
 * 稳定发布），把 callback API 用 `suspendCancellableCoroutine` 包成挂起函数。
 *
 * **包名纠正**：fork 0.18.1 实际包名是 `com.yausername.youtubedl_android.*`
 * （不是 `com.yausername.ytdlp.*`）。README 没明说，编译会报
 * Unresolved reference 'ytdlp'，靠 javap -p 看 AAR 实际类路径才能定。
 *
 * **callback 形式**：新版是 Kotlin `Function3<Float, Long, String, Unit>`
 * (progress, etaSeconds, line)，不是老版的 `YoutubeDLCallback.onYoutubeDLProgress`。
 *
 * **VideoInfo.duration 是 Int（秒），0 = 未知**，需要 `toDouble() ?: null` 转换。
 *
 * 输出目录在构造时注入（`baseOutputDir`），由 Hilt 提供 `context.filesDir`。
 * 不写 `java.io.tmpdir`——Android 可能在低存储时清理。
 */
class YtDlpEngine(
    private val baseOutputDir: File,
) : Engine {

    override val name: String = "yt-dlp"

    override fun supports(url: String, options: DownloadOptions): Boolean {
        val u = url.lowercase()
        return when {
            u.contains("youtube.com") || u.contains("youtu.be") -> true
            u.startsWith("http://") || u.startsWith("https://") -> true  // 通用兜底
            else -> false
        }
    }

    override suspend fun probe(url: String, options: DownloadOptions): MediaItem =
        suspendCancellableCoroutine { cont ->
            try {
                val info = YoutubeDL.getInstance().getInfo(url)
                cont.resume(info.toMediaItem(url))
            } catch (e: YoutubeDLException) {
                // 嗅探失败也不致命——返回 URL 当标题，下载流程仍可走
                cont.resume(fallbackMediaItem(url))
            } catch (e: Throwable) {
                cont.resume(fallbackMediaItem(url))
            }
        }

    /** 嗅探失败时的兜底 MediaItem——从 URL 推断平台。 */
    private fun fallbackMediaItem(url: String): MediaItem = MediaItem(
        platform = if (url.contains("youtu")) Platform.YOUTUBE else Platform.GENERIC,
        itemId = url.hashCode().toString(),
        sourceUrl = url,
        title = url,
    )

    override suspend fun download(
        item: MediaItem,
        options: DownloadOptions,
        onProgress: suspend (Progress) -> Unit,
    ): DownloadResult = suspendCancellableCoroutine { cont: CancellableContinuation<DownloadResult> ->
        val outDir = File(baseOutputDir, item.platform.key).apply { mkdirs() }
        val outTemplate = File(outDir, "${item.itemId}.%(ext)s").absolutePath

        val request = YoutubeDLRequest(item.sourceUrl).apply {
            addOption("-o", outTemplate)
            addOption("--no-playlist")
            addOption("--no-mtime")
            // 容器（yt-dlp 的 --merge-output-format 在下载后合并视频/音频流）
            when (options.container) {
                "mp4" -> {
                    addOption("--merge-output-format", "mp4")
                    addOption("--remux-video", "mp4")
                }
                "mkv" -> {
                    addOption("--merge-output-format", "mkv")
                    addOption("--remux-video", "mkv")
                }
            }
            // 画质
            when {
                options.maxQuality == "best" -> {
                    addOption("-f", "bestvideo*+bestaudio/best")
                }
                options.maxQuality.endsWith("p") -> {
                    val h = options.maxQuality.dropLast(1)
                    addOption("-f", "bestvideo[height<=$h]+bestaudio/best[height<=$h]")
                }
                else -> {
                    addOption("-f", options.maxQuality)
                }
            }
            if (options.writeThumbnail) addOption("--write-thumbnail")
            if (options.writeSubtitles) addOption("--write-subs")
            if (!options.resume) addOption("--no-continue")
            options.proxy?.let { addOption("--proxy", it) }
            options.rateLimit?.let { addOption("--limit-rate", it) }
        }

        try {
            val response = YoutubeDL.getInstance().execute(request, item.itemId) { progress, etaSeconds, line ->
                if (cont.isCancelled) return@execute
                // progress callback 异步转 sync（onProgress 是 suspend，execute 的 lambda 是 sync）
                // 协程上下文里再调 onProgress——通过 runBlocking 桥接
                try {
                    kotlinx.coroutines.runBlocking {
                        onProgress(
                            Progress(
                                fraction = progress.coerceIn(0f, 1f),
                                message = line.take(200),
                            )
                        )
                    }
                } catch (_: Throwable) { /* progress 失败不阻塞下载 */ }
            }

            val actual = outDir.listFiles { f -> f.name.startsWith(item.itemId) }?.firstOrNull()
            if (response.exitCode == 0 && actual != null && actual.length() > 0) {
                cont.resume(DownloadResult.Success(actual.absolutePath))
            } else if (actual != null && actual.length() > 0) {
                // exitCode != 0 但文件落地了——yt-dlp 部分场景会这样（warn 但成功）
                cont.resume(DownloadResult.Success(actual.absolutePath))
            } else {
                val errTail = response.err.takeLast(300)
                cont.resume(DownloadResult.Failure("yt-dlp exit=${response.exitCode}: $errTail"))
            }
        } catch (e: YoutubeDLException) {
            cont.resume(DownloadResult.Failure("yt-dlp: ${e.message ?: e.javaClass.simpleName}"))
        } catch (e: Throwable) {
            cont.resume(DownloadResult.Failure("Unexpected: ${e.message ?: e.javaClass.simpleName}"))
        }
    }

    /** VideoInfo → MediaItem 转换。`duration: int` 0 视为未知。 */
    private fun VideoInfo.toMediaItem(sourceUrl: String): MediaItem = MediaItem(
        platform = if (sourceUrl.contains("youtu")) Platform.YOUTUBE else Platform.GENERIC,
        itemId = id ?: sourceUrl.hashCode().toString(),
        sourceUrl = sourceUrl,
        title = title ?: "",
        author = uploader?.let { Author(name = it) },
        coverUrl = thumbnail,
        duration = if (duration > 0) duration.toDouble() else null,
        mediaType = if (duration > 0) MediaType.VIDEO else MediaType.AUDIO,
    )
}
