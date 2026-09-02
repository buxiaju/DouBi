package com.doubi.android.core.pipeline

import com.doubi.android.core.model.MediaFormat
import com.doubi.android.core.model.MediaItem
import com.doubi.android.core.model.Platform
import com.doubi.android.core.platform.youtube.YouTubeUrl
import com.doubi.android.engine.ytdlp.YtDlpEngine
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 阶段 4：解析 + 展开 use case。1:1 对拍桌面版 `src/doubi/core/pipeline.py:DownloadPipeline.parse_and_expand`。
 *
 * **v0.1 范围**（PHASES.md L141-156）：
 * - YouTube 单一视频（普通 / Shorts / Live / embed）
 * - 通用 m3u8 / mp4 直链
 *
 * **v0.1 不做**：
 * - 容器展开（YouTube playlist / 抖音合集 / B 站收藏夹）—— v0.2+ 用 desktop 同样的
 *   `expand` 接口扩展
 * - 通用嗅探（headless browser 跑 15s 嗅探 m3u8）—— v0.2 单独 PR
 * - B 站 / 抖音 / 抖音 / Twitter 等具体平台 adapter —— v0.2+ 阶段 5/6 接
 *
 * **设计取舍**：
 * 桌面版 `DownloadPipeline` 是一个会做 6 件事的胖类（parse / expand / dedup /
 * download / progress / postprocess），Kotlin 端按"每个 use case 一个类"切，
 * 阶段 4 只切 [ParseAndExpandUseCase]，download 阶段由 `DownloadRepository` +
 * `DownloadWorker` 接管（已经在 phase-2 落地）。Kotlin 拆 use case 是
 * 阶段 4+ 唯一的新模式，desktop 端 v0.3.1 才有的"按阶段切 use case"。
 */
@Singleton
class ParseAndExpandUseCase @Inject constructor(
    private val ytDlpEngine: YtDlpEngine,
) {
    /**
     * 主入口。**suspend**——内部调 [YtDlpEngine.probeWithFormats]。
     *
     * @return [ParseResult]，调用方按 sealed 子类分支处理
     */
    suspend operator fun invoke(url: String): ParseResult {
        val trimmed = url.trim()
        if (trimmed.isEmpty()) {
            return ParseResult.Unsupported("空 URL")
        }
        if (!(trimmed.startsWith("http://") || trimmed.startsWith("https://"))) {
            return ParseResult.Unsupported("不是 http(s) URL：$trimmed")
        }

        // 1) 先看是不是 YouTube
        val watchUrl = YouTubeUrl.toWatchUrlOrNull(trimmed)
        if (watchUrl != null) {
            // YouTube 路径：先 getInfo 拿 title + formats
            val probe = ytDlpEngine.probeWithFormats(watchUrl)
            val classified = YouTubeUrl.classify(trimmed)
            val item = probe.item.copy(
                platform = Platform.YOUTUBE,
                itemId = classified.itemId.ifBlank { probe.item.itemId },
                sourceUrl = watchUrl,
            )
            return ParseResult.Youtube(item = item, formats = probe.formats)
        }

        // 2) youtube.com 域名但不是视频形态（CHANNEL / PLAYLIST / 杂项）→ 拒绝
        // 桌面版 YouTubeAdapter 也这么干：channel / playlist 走 yt-dlp --yes-playlist，
        // adapter 不抄一份列表展开逻辑。Android 端 v0.1 不实现该路径，直接拒。
        if (trimmed.contains("youtube.com", ignoreCase = true) ||
            trimmed.contains("youtu.be", ignoreCase = true)
        ) {
            return ParseResult.Unsupported("YouTube 频道 / 播放列表暂不支持")
        }

        // 3) 非 YouTube 走通用 m3u8 / mp4 直链路径
        val probe = ytDlpEngine.probeWithFormats(trimmed)
        val isFallback = probe.item.title.isBlank() || probe.item.title == trimmed
        val item = probe.item.copy(
            platform = Platform.GENERIC,
            // 兜底时 platform=GENERIC, itemId=URL hashCode；嗅探成功时用真实 itemId
            itemId = if (isFallback) trimmed.hashCode().toString() else probe.item.itemId,
        )
        // 直链场景：formats 列表 = 解析失败的空列表 / 解析成功的多 format
        // 给 UI 一个"默认 format"：第一个非 audio-only 的；都没有就让 UI 走"无 format"路径
        val defaultFormat = probe.formats.firstOrNull { !it.isAudioOnly }
            ?: probe.formats.firstOrNull()
        return ParseResult.DirectLink(item = item, format = defaultFormat)
    }
}

/**
 * 解析结果。sealed 让调用方必须显式处理每个分支——漏掉 Unsupported / Failure
 * 在编译期就能抓出来（vs desktop 端返回 `Optional[MediaItem]`、None / 异常 混合）。
 */
sealed class ParseResult {
    /**
     * YouTube 单一视频解析成功。`formats` 至少 1 个（YouTube 的 formats 列表
     * 几乎一定有内容；空列表视作 DirectLink 分支降级）。
     */
    data class Youtube(
        val item: MediaItem,
        val formats: List<MediaFormat>,
    ) : ParseResult()

    /**
     * 通用 m3u8 / mp4 直链。`format` 可能为 null（嗅探失败 / 没有 video stream），
     * 调用方走「无 format 选项」UI 路径（直接入队，让 yt-dlp 自己选最佳）。
     */
    data class DirectLink(
        val item: MediaItem,
        val format: MediaFormat?,
    ) : ParseResult()

    /**
     * 不支持的 URL（不是 http(s)、空串、YouTube 频道 / 播放列表）。UI 应该提示
     * 「该链接类型暂不支持」。
     */
    data class Unsupported(
        val reason: String,
    ) : ParseResult()
}
