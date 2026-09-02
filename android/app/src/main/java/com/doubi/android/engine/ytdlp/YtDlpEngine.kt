package com.doubi.android.engine.ytdlp

import androidx.annotation.VisibleForTesting
import com.doubi.android.core.model.Author
import com.doubi.android.core.model.DownloadOptions
import com.doubi.android.core.model.DownloadResult
import com.doubi.android.core.model.MediaFormat
import com.doubi.android.core.model.MediaItem
import com.doubi.android.core.model.MediaType
import com.doubi.android.core.model.Platform
import com.doubi.android.core.model.Progress
import com.doubi.android.engine.Engine
import com.yausername.youtubedl_android.YoutubeDL
import com.yausername.youtubedl_android.YoutubeDLException
import com.yausername.youtubedl_android.YoutubeDLRequest
import com.yausername.youtubedl_android.mapper.VideoFormat
import com.yausername.youtubedl_android.mapper.VideoInfo
import kotlinx.coroutines.CancellableContinuation
import kotlinx.coroutines.suspendCancellableCoroutine
import java.io.File
import java.util.Locale
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

    /**
     * 阶段 4：嗅探 + 拿 formats 列表，给 PromptOptionsDialog 选清晰度。
     *
     * **不**走 Engine interface——`formats` 是 yt-dlp 特有的概念，aria2 / ffmpeg 没
     * 这层抽象。`ParseAndExpandUseCase` 注入 [YtDlpEngine] 具体类，调用此方法。
     *
     * 失败时 `formats` 返空列表（不让调用方崩溃），item 走 [fallbackMediaItem] 兜底。
     * YouTube / m3u8 直链都走同一路径——youtubedl-android 对 m3u8 直链也支持 getInfo。
     */
    suspend fun probeWithFormats(url: String): ProbeResult =
        suspendCancellableCoroutine { cont ->
            try {
                val info = YoutubeDL.getInstance().getInfo(url)
                val item = info.toMediaItem(url)
                val formats = info.formats.orEmpty().mapNotNull { it.toMediaFormatOrNull() }
                cont.resume(ProbeResult(item, formats))
            } catch (e: Throwable) {
                // 嗅探失败：item 走 URL 兜底，formats 空列表（直链场景就是 formats 空）
                cont.resume(ProbeResult(fallbackMediaItem(url), emptyList()))
            }
        }

    /** [probeWithFormats] 的返回值。formats 可能为空（解析失败 / 直链没 formats）。 */
    data class ProbeResult(
        val item: MediaItem,
        val formats: List<MediaFormat>,
    )

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
        // 欠账 #2 已还：路径由 outputRoot / outputDirTemplate / filenameTemplate 三个
        // 字段算出（v0.1 之前硬编 baseOutputDir/{platform}/{itemId}.%(ext)s）。
        // baseOutputDir 由 Hilt 注入（context.filesDir/downloads），永远是 app 私有目录。
        val outDir = resolveOutputDir(baseOutputDir, item, options)
        val filename = renderTemplate(
            options.filenameTemplate ?: DEFAULTS_FILENAME_TEMPLATE,
            item,
        )
        val outTemplate = File(outDir, "$filename.%(ext)s").absolutePath

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
                                // 库给的是 0-100 百分比（StreamProcessExtractor.getProgress 直接
                                // Float.parseFloat 百分号前的数字），未知时是 -1f。必须 /100 再 clamp，
                                // 否则任何 >1% 的进度都会被 coerceIn(0f,1f) 截成满格。
                                fraction = (progress / 100f).coerceIn(0f, 1f),
                                message = line.take(200),
                                // 库不给速度，自己从原始行的 `at 1.23MiB/s` 解析
                                speedBytesPerSec = parseSpeedBytesPerSec(line),
                                // 库未知时给 -1，Progress 约定非正数当未知
                                etaSeconds = etaSeconds.takeIf { it > 0 },
                            )
                        )
                    }
                } catch (_: Throwable) { /* progress 失败不阻塞下载 */ }
            }

            // 找文件：可能落在 outDir 也可能在 outputRoot 根下（yt-dlp 自动建子目录）
            // 用「outputRoot 以下的任意位置、文件名以渲染出的 basename 开头」来找
            val basenamePrefix = filename.take(40)  // 截前 40 字符避免长 title 截断
            val actual = findProducedFile(baseOutputDir, options.outputRoot, basenamePrefix)
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

    /**
     * 算输出目录：`baseOutputDir / outputRoot / <outputDirTemplate 展开>`。
     * 任一占位符为 null/空时降级为 `_`。不存在就 mkdirs。
     */
    internal fun resolveOutputDir(
        base: File,
        item: MediaItem,
        options: DownloadOptions,
    ): File {
        val root = options.outputRoot?.takeIf { it.isNotBlank() } ?: "Downloaded"
        val template = options.outputDirTemplate?.takeIf { it.isNotBlank() }
            ?: DEFAULTS_DIR_TEMPLATE
        val expanded = renderPathTemplate(template, item)
        val dir = File(base, root).let { File(it, expanded) }
        dir.mkdirs()
        return dir
    }

    /** 渲染文件名模板（{title}/{item_id}），做文件名安全字符过滤。 */
    private fun renderTemplate(template: String, item: MediaItem): String {
        val ctx = mapOf(
            "title" to (item.title.takeIf { it.isNotBlank() } ?: item.itemId),
            "item_id" to item.itemId,
        )
        val raw = ctx.entries.fold(template) { acc, (k, v) -> acc.replace("{$k}", v) }
        return sanitizeFilename(raw)
    }

    /** 渲染目录模板（{platform}/{author}/{media_type}）。段为 null/空时降级为 `_`。 */
    private fun renderPathTemplate(template: String, item: MediaItem): String {
        val ctx = mapOf(
            "platform" to item.platform.key,
            "author" to (item.author?.name?.takeIf { it.isNotBlank() } ?: "_"),
            "media_type" to item.mediaType.name,
        )
        return ctx.entries.fold(template) { acc, (k, v) -> acc.replace("{$k}", v) }
    }

    /**
     * 替换 Windows / Unix 文件系统都不允许的字符。规则跟桌面版
     * `src/doubi/core/util.py:sanitize_filename` 一致（要查 desktop 实现）。
     *
     * 字符类里**不能**有 `*?` 相邻——Java regex 会把 `*?` 解析为懒惰量词而非字面 `*` 和 `?`，
     * 导致 5 个非法字符里有 2 个不被替换。教训：字符类里就老老实实 `[abc]` 不用元字符。
     */
    private fun sanitizeFilename(name: String): String {
        val illegal = setOf('/', '\\', ':', '*', '?', '"', '<', '>', '|')
        val cleaned = name.map { c -> if (c in illegal) '_' else c }
            .joinToString("")
        return cleaned
            .replace(Regex("""\s+"""), " ")
            .trim()
            .ifBlank { "untitled" }
    }

    /**
     * 测试 hook：[sanitizeFilename] 是 private，但单测要验证非法字符替换。
     * 暴露成 `@VisibleForTesting internal`，生产代码不应直接调用。
     */
    @VisibleForTesting
    internal fun sanitizeFilenameForTest(name: String): String = sanitizeFilename(name)

    /**
     * 从 yt-dlp 的进度行里抠出瞬时速度，返回字节/秒；抠不出来返回 null（欠账 #4）。
     *
     * youtubedl-android 0.18.1 的回调只给 `(progress, etaInSeconds, line)`，**没有速度**，
     * 所以只能从原始行解析。能触发回调的行必然同时含 `%` 和 ` ETA mm:ss`
     * （库的 regex 是 `\[download\]\s+(\d+\.\d)% .* ETA (\d+):(\d+)`），形如：
     *
     * ```
     * [download]  45.2% of  10.50MiB at    1.23MiB/s ETA 00:05
     * [download]  45.2% of ~10.50MiB at  512.00KiB/s ETA 00:05
     * [download]  45.2% of  10.50MiB at  Unknown B/s ETA Unknown
     * ```
     *
     * 单位按 1024 进制换算（yt-dlp 输出的是 KiB/MiB/GiB）。`Unknown B/s` 匹配不到数字 → null。
     * aria2c 外部下载器的行（`DL:2.1MiB`，没 `/s`）解析不出来，降级为 null——项目没启用 aria2c。
     */
    internal fun parseSpeedBytesPerSec(line: String): Long? {
        val m = SPEED_REGEX.find(line) ?: return null
        val num = m.groupValues[1].toDoubleOrNull() ?: return null
        if (num <= 0.0) return null
        // groupValues[2] 是 "" / "K" / "Ki" / "M" / "Mi" / "G" / "Gi" / "T" / "Ti"
        val prefix = m.groupValues[2].uppercase(Locale.US).removeSuffix("I")
        val multiplier: Long = when (prefix) {
            "" -> 1L
            "K" -> 1024L
            "M" -> 1024L * 1024
            "G" -> 1024L * 1024 * 1024
            "T" -> 1024L * 1024 * 1024 * 1024
            else -> return null
        }
        return (num * multiplier).toLong().takeIf { it > 0 }
    }

    /**
     * 在 `base/outputRoot` 树下递归找「文件名以 `prefix` 开头、且大小 > 0」的文件。
     * yt-dlp 在我们指定的 outDir 里没产出（罕见，比如它自己改了下划线）时回退。
     * 深度限制 4 层避免扫到老的旧文件。
     */
    private fun findProducedFile(
        base: File,
        outputRoot: String?,
        prefix: String,
    ): File? {
        val root = File(base, outputRoot ?: "Downloaded")
        if (!root.exists()) return null
        val queue = ArrayDeque<File>().apply { add(root) }
        var depth = 0
        while (queue.isNotEmpty() && depth < 4) {
            val node = queue.removeFirst()
            node.listFiles()?.forEach { f ->
                if (f.isFile && f.length() > 0 && f.nameWithoutExtension.startsWith(prefix)) return f
                if (f.isDirectory) queue.add(f)
            }
            depth++
        }
        return null
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

    /**
     * VideoFormat → MediaFormat 转换。`formatId` 缺失或 `ext` 缺失 → null（脏数据丢弃）。
     * `fileSize == 0` 视为未知，用 `fileSizeApproximate` 兜底——YouTube 这俩经常是 0。
     */
    private fun VideoFormat.toMediaFormatOrNull(): MediaFormat? {
        val id = formatId ?: return null
        val e = ext ?: return null
        val audioOnly = (vcodec == "none" || vcodec == null) && acodec != null && acodec != "none"
        return MediaFormat(
            formatId = id,
            ext = e,
            height = height.takeIf { it > 0 },
            width = width.takeIf { it > 0 },
            vcodec = vcodec,
            acodec = acodec,
            tbr = tbr.takeIf { it > 0 },
            fileSize = fileSize.takeIf { it > 0 } ?: fileSizeApproximate.takeIf { it > 0 },
            isAudioOnly = audioOnly,
        )
    }

    companion object {
        // Engine 内部用的 fallback，避免直接 import core.config（造成 engine→core 循环）
        internal const val DEFAULTS_DIR_TEMPLATE = "{platform}/{author}/{media_type}"
        internal const val DEFAULTS_FILENAME_TEMPLATE = "{title}_{item_id}"

        /**
         * 匹配 yt-dlp 进度行的速度片段：`at 1.23MiB/s` / `at 512.00KiB/s` / `at 1024B/s`。
         *
         * group 1 = 数值，group 2 = 单位前缀（`""` / `K` / `Ki` / `M` / `Mi` / …）。
         * 注意字符类里只放字面字符 `[KMGT]`，量词 `?` 写在类外——上一轮踩过
         * 「字符类内 `*?` 被当懒惰量词」的坑（见 [sanitizeFilename] 注释）。
         */
        internal val SPEED_REGEX = Regex(
            """\bat\s+([0-9]+(?:\.[0-9]+)?)\s*([KMGT]?[iI]?)B/s""",
            RegexOption.IGNORE_CASE,
        )
    }
}
