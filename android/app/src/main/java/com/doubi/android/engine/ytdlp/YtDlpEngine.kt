package com.doubi.android.engine.ytdlp

import com.doubi.android.core.model.Author
import com.doubi.android.core.model.DownloadOptions
import com.doubi.android.core.model.DownloadResult
import com.doubi.android.core.model.MediaItem
import com.doubi.android.core.model.MediaType
import com.doubi.android.core.model.Platform
import com.doubi.android.core.model.Progress
import com.doubi.android.engine.Engine
import com.yausername.ytdlp.YoutubeDL
import com.yausername.ytdlp.YoutubeDLCallback
import com.yausername.ytdlp.YoutubeDLException
import com.yausername.ytdlp.YoutubeDLRequest
import kotlinx.coroutines.CancellableContinuation
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.suspendCancellableCoroutine
import java.io.File
import kotlin.coroutines.resume

/**
 * yt-dlp 引擎。1:1 对拍桌面版 `src/doubi/engines/yt_dlp.py`。
 *
 * 桌面版用 Python `yt_dlp` + `asyncio.to_thread` 包装 sync API；
 * Android 端用 [yausername/yt-dlp-android]（同源，下载/嗅探 API 几乎一致），
 * 把 callback API 用 `suspendCancellableCoroutine` 包成挂起函数。
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
            val request = YoutubeDLRequest(url, listOf("--skip-download"))
            val callback = object : YoutubeDLCallback {
                override fun onYoutubeDLProgress(percent: Float, etaSeconds: Long, line: String) {
                    // 嗅探阶段不报进度
                }
                override fun onYoutubeDLLine(line: String, outputType: Int) {
                    // yt-dlp-android 嗅探成功时 onSuccess 触发
                }
            }
            try {
                val info = YoutubeDL.getInstance().getInfo(request, callback)
                val platform = if (url.contains("youtu")) Platform.YOUTUBE else Platform.GENERIC
                cont.resume(
                    MediaItem(
                        platform = platform,
                        itemId = info.id ?: url.hashCode().toString(),
                        sourceUrl = url,
                        title = info.title ?: "",
                        author = info.uploader?.let { Author(name = it) },
                        coverUrl = info.thumbnail,
                        duration = info.duration?.toDouble(),
                        mediaType = if (info.duration != null) MediaType.VIDEO else MediaType.AUDIO,
                    )
                )
            } catch (e: YoutubeDLException) {
                cont.resume(
                    MediaItem(
                        platform = Platform.GENERIC,
                        itemId = url.hashCode().toString(),
                        sourceUrl = url,
                        title = url,
                    )
                )
            } catch (e: Throwable) {
                cont.resume(
                    MediaItem(
                        platform = Platform.GENERIC,
                        itemId = url.hashCode().toString(),
                        sourceUrl = url,
                        title = url,
                    )
                )
            }
        }

    override suspend fun download(
        item: MediaItem,
        options: DownloadOptions,
        onProgress: suspend (Progress) -> Unit,
    ): DownloadResult = suspendCancellableCoroutine { cont: CancellableContinuation<DownloadResult> ->
        val outDir = File(baseOutputDir, item.platform.key).apply { mkdirs() }
        val outTemplate = File(outDir, "${item.itemId}.%(ext)s").absolutePath

        val args = buildList {
            add("-o"); add(outTemplate)
            add("--no-playlist")
            add("--no-mtime")
            // 容器（yt-dlp 的 --merge-output-format 在下载后合并视频/音频流）
            when (options.container) {
                "mp4" -> { add("--merge-output-format"); add("mp4") }
                "mkv" -> { add("--merge-output-format"); add("mkv") }
            }
            // 画质
            when {
                options.maxQuality == "best" -> {
                    add("-f"); add("bestvideo*+bestaudio/best")
                }
                options.maxQuality.endsWith("p") -> {
                    val h = options.maxQuality.dropLast(1)
                    add("-f"); add("bestvideo[height<=$h]+bestaudio/best[height<=$h]")
                }
                else -> {
                    add("-f"); add(options.maxQuality)
                }
            }
            if (options.writeThumbnail) add("--write-thumbnail")
            if (options.writeSubtitles) add("--write-subs")
            if (!options.resume) add("--no-continue")
            options.proxy?.let { add("--proxy"); add(it) }
            options.rateLimit?.let { add("--limit-rate"); add(it) }
        }

        val request = YoutubeDLRequest(item.sourceUrl, args)
        val callback = object : YoutubeDLCallback {
            override fun onYoutubeDLProgress(percent: Float, etaSeconds: Long, line: String) {
                if (cont.isCancelled) return  // 协程已取消，停止回调（yt-dlp-android 不支持外中断，会自然结束）
                try {
                    runBlocking {
                        onProgress(
                            Progress(
                                fraction = percent.coerceIn(0f, 1f),
                                message = line.take(200),
                            )
                        )
                    }
                } catch (_: Throwable) { /* progress 失败不阻塞下载 */ }
            }
        }

        try {
            YoutubeDL.getInstance().execute(request, callback)
            val actual = outDir.listFiles { f -> f.name.startsWith(item.itemId) }?.firstOrNull()
            if (actual != null && actual.length() > 0) {
                cont.resume(DownloadResult.Success(actual.absolutePath))
            } else {
                cont.resume(DownloadResult.Failure("Output file not found in ${outDir.absolutePath}"))
            }
        } catch (e: YoutubeDLException) {
            cont.resume(DownloadResult.Failure("yt-dlp: ${e.message ?: e.javaClass.simpleName}"))
        } catch (e: Throwable) {
            cont.resume(DownloadResult.Failure("Unexpected: ${e.message ?: e.javaClass.simpleName}"))
        }
    }
}
