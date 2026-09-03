package com.doubi.android.core.pipeline

import com.doubi.android.core.model.MediaFormat
import com.doubi.android.core.model.MediaItem
import com.doubi.android.core.model.Platform
import com.doubi.android.core.platform.youtube.YouTubeUrl
import com.doubi.android.core.sniffer.SniffResult
import com.doubi.android.core.sniffer.Sniffer
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
 * **v0.4.0 范围新增**（通用嗅探）：
 * - 任意 http(s) URL 走 [Sniffer.sniff] 看 Content-Type，识别为 m3u8 / mp4 / webm
 *   → 走 DirectLink 让 Engine 下载
 * - 嗅探不到 media → Unsupported（"该链接不是 m3u8 / mp4"）
 *
 * **v0.4.0 不做**：
 * - 容器展开（YouTube playlist / 抖音合集 / B 站收藏夹）—— v0.5.0+ 用 desktop 同样的
 *   `expand` 接口扩展
 * - **headless browser 嗅探**（WebView load URL + 拦截 m3u8 请求）—— v0.5.0 单独 PR
 *   跟 B 站 / 抖音 adapter 一起做
 * - B 站 / 抖音 / Twitter 等具体平台 adapter —— v0.5.0
 *
 * **设计取舍**：
 * 桌面版 `DownloadPipeline` 是一个会做 6 件事的胖类（parse / expand / dedup /
 * download / progress / postprocess），Kotlin 端按"每个 use case 一个类"切，
 * 阶段 4 只切 [ParseAndExpandUseCase]，download 阶段由 `DownloadRepository` +
 * `DownloadWorker` 接管（已经在 phase-2 落地）。Kotlin 拆 use case 是
 * 阶段 4+ 唯一的新模式，desktop 端 v0.3.1 才有的"按阶段切 use case"。
 *
 * **v0.4.0 集成 Sniffer 的取舍**：
 * - Sniffer 在 use case 内部调（不在 YtDlpEngine 内部）—— Sniffer 是"判定直链能不能下"
 *   的辅助，Engine 是"真下"的执行者，分层清晰
 * - v0.4.0 路径：YouTube ❌ → youtube 域名但非视频 ❌ → **Sniffer 嗅探** → DirectLink
 *   或 Unsupported；**Sniffer ❌** → 走原 v0.1 兜底 ytDlpEngine.probeWithFormats
 *   （让 yt-dlp 自己嗅探，能下就 DirectLink，不能就 fallback MediaItem title=url）
 */
@Singleton
class ParseAndExpandUseCase @Inject constructor(
    private val ytDlpEngine: YtDlpEngine,
    private val sniffer: Sniffer,
) {
    /**
     * 主入口。**suspend**——内部调 [YtDlpEngine.probeWithFormats] / [Sniffer.sniff]。
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

        // 3) v0.4.0 通用嗅探：先 HEAD 看 Content-Type 是不是 m3u8 / mp4 / webm
        // 命中 → 走 DirectLink 简化路径（v0.1 的 probeWithFormats 二次确认也调，
        // 避免 Sniffer 误判把 HTML 页面当 mp4）
        // 不命中 → 兜底走 v0.1 路径 ytDlpEngine.probeWithFormats（让 yt-dlp 嗅探）
        return when (val sniff = sniffer.sniff(trimmed)) {
            is SniffResult.Media -> {
                // Sniffer 识别为 media：跑 yt-dlp 二次确认 + 拿 title
                val probe = ytDlpEngine.probeWithFormats(sniff.finalUrl)
                val item = probe.item.copy(
                    platform = Platform.GENERIC,
                    sourceUrl = sniff.finalUrl,
                    itemId = trimmed.hashCode().toString(),
                )
                val defaultFormat = probe.formats.firstOrNull { !it.isAudioOnly }
                    ?: probe.formats.firstOrNull()
                ParseResult.DirectLink(item = item, format = defaultFormat)
            }
            is SniffResult.NotMedia -> {
                // Sniffer 明确说不是 media：返回 Unsupported（避免 yt-dlp 拿
                // HTML 页面去嗅探浪费 15s+）
                ParseResult.Unsupported("链接不是 m3u8 / mp4：HTTP ${sniff.statusCode} ${sniff.contentType ?: ""}")
            }
            is SniffResult.Error -> {
                // Sniffer 出错（网络 / DNS / SSL）：**降级**让 yt-dlp 自己嗅探，不直接拒
                // ——v0.1 阶段 4 的兜底路径给机会
                runYtDlpFallback(trimmed)
            }
        }
    }

    /**
     * v0.1 阶段 4 的兜底路径：让 yt-dlp 自己嗅探（Sniffer 出错时降级调用）。
     */
    private suspend fun runYtDlpFallback(url: String): ParseResult {
        val probe = ytDlpEngine.probeWithFormats(url)
        val isFallback = probe.item.title.isBlank() || probe.item.title == url
        val item = probe.item.copy(
            platform = Platform.GENERIC,
            itemId = if (isFallback) url.hashCode().toString() else probe.item.itemId,
        )
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
