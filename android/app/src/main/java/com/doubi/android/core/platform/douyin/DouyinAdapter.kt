package com.doubi.android.core.platform.douyin

import com.doubi.android.core.model.Author
import com.doubi.android.core.model.DownloadOptions
import com.doubi.android.core.model.DownloadResult
import com.doubi.android.core.model.MediaItem
import com.doubi.android.core.model.MediaType
import com.doubi.android.core.model.Platform
import com.doubi.android.core.model.Progress
import com.doubi.android.engine.Engine
import com.doubi.android.engine.ytdlp.YtDlpEngine
import timber.log.Timber
import java.io.IOException
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 阶段 17 v0.5.7 + 阶段 18 v0.5.8：抖音 [Engine] 实现。1:1 对拍桌面版 `src/doubi/platforms/douyin/strategies.py:DouyinStrategy`。
 *
 * **v0.5.7 范围**（probe 阶段）：
 * - `name = "douyin"` —— 匹配 `AppConfig.engine` 取值
 * - `supports(url, ...)` —— 用 [DouyinUrl.classify] 判断是否支持（VIDEO / SHORT_LINK 算支持；
 *   UNSUPPORTED 返 false）
 * - `probe(url, ...)` —— 调 [DouyinApiClient.awemeItemInfo] 拿 desc / duration / author /
 *   play URL，构造 [MediaItem]
 * - `download(item, ...)` —— v0.5.7 **placeholder**：`throw IOException("v0.5.8+ 才有")`
 *
 * **v0.5.8 范围新增**（download 真路径）：
 * - `download(item, ...)` —— 调 [DouyinApiClient.awemeItemInfo] 拿 `playUrl` 真实下载直链 → 委托
 *   [YtDlpEngine.download] 跑下载（**不**调 `playwm` / `playaddr` 接口——`awemeItemInfo` 已经在
 *   probe 阶段返了 `video.play_addr.url_list[0]` 作为无水印播放 URL）
 * - 进度回调 `onProgress` 透传到 YtDlpEngine
 * - 输出路径仍走 YtDlpEngine 的 `baseOutputDir` 模板
 *
 * **v0.5.7 → v0.5.8 限制**：
 * - **X-Bogus 仍 stub chaos**——v0.5.8 probe + download 走真抖音 web API 仍 -352 风控
 * - 抖音 adapter download 走 API 拿不到真 playUrl → 抛 IOException "playUrl is empty"
 * - 真 get_chaos 实装后 v0.5.9+ 才能真下抖音视频
 *
 * **架构**：
 * - `Engine` interface 在 v0.1 阶段 2 已落地
 * - 桌面版 `DouyinStrategy` 用 `auth.py` + `xbogus.py` + `api.py` 三个文件
 * - Android 端 v0.5.4 / v0.5.5 / v0.5.6 / v0.5.7 / v0.5.8 分别落地 [DouyinUrl] / [XBogusSigner] /
 *   [DouyinApiClient] / [DouyinAdapter] —— 本阶段把它们**串起来**到 [Engine] interface download 路径
 */
@Singleton
class DouyinAdapter @Inject constructor(
    private val apiClient: DouyinApiClient,
    private val ytDlpEngine: YtDlpEngine,
) : Engine {
    override val name: String = "douyin"

    /**
     * 抖音支持：VIDEO（`/video/NNN`）+ SHORT_LINK（`v.douyin.com/xxx/`）。
     * UNSUPPORTED（直播 / 用户主页 / 其它）返 false。
     */
    override fun supports(url: String, options: DownloadOptions): Boolean {
        val classified = DouyinUrl.classify(url)
        return classified.type != DouyinUrlType.UNSUPPORTED
    }

    /**
     * 调 [DouyinApiClient.awemeItemInfo] 拿 metadata，构造 [MediaItem]。
     *
     * **v0.5.7 不**拿 formats 列表（`playwm` / `playaddr` 接口 v0.5.8+）。
     * UI 端走「无 format 选项」路径。
     */
    override suspend fun probe(url: String, options: DownloadOptions): MediaItem {
        val classified = DouyinUrl.classify(url)
        val itemId = when (classified.type) {
            DouyinUrlType.VIDEO -> classified.id
            DouyinUrlType.SHORT_LINK -> classified.id  // v0.5.7 不解析 short_link → video_id
            DouyinUrlType.UNSUPPORTED -> throw IOException("unsupported 抖音 URL: $url")
        }
        val item = apiClient.awemeItemInfo(itemId)
        return MediaItem(
            platform = Platform.DOUYIN,
            itemId = item.awemeId,
            sourceUrl = url,
            title = item.desc,
            author = if (item.authorNickname.isNotBlank()) Author(
                id = item.authorSecUid,
                name = item.authorNickname,
                avatarUrl = null,
            ) else null,
            coverUrl = item.coverUrl.takeIf { it.isNotBlank() },
            duration = item.durationSec.toDouble(),
            mediaType = MediaType.VIDEO,
        )
    }

    /**
     * v0.5.8 真路径：
     * 1. 调 [DouyinApiClient.awemeItemInfo] 拿 `playUrl` 真实下载直链（**不**调 `playwm` /
     *   `playaddr` 接口——aweme_iteminfo 已经在 probe 阶段返了 `video.play_addr.url_list[0]`
     *   作为无水印播放 URL）
     * 2. 校验 `playUrl` 非空
     * 3. 复制 [MediaItem] 但把 `sourceUrl` 替换成 playUrl
     * 4. 委托 [YtDlpEngine.download] 跑下载
     *
     * **v0.5.8 简化**：
     * - **不**取 formats 列表（`playwm` / `playaddr` 接口，v0.5.9+ 让用户选）
     * - **不**缓存 awemeItemInfo 响应（每次调都重新拉，~300ms 延迟）—— v0.5.9+ 单独优化
     *
     * **错误处理**：
     * - `awemeItemInfo` 抛 IOException → 透传（X-Bogus stub chaos 走 API -352 / 视频不存在 / 地区限制）
     * - `awemeItemInfo` 返 `playUrl` 空 → 抛 IOException（v0.5.8 抖音仍 -352，playUrl 是空字符串）
     * - `YtDlpEngine.download` 抛异常 / 返 Failure → 透传
     */
    override suspend fun download(
        item: MediaItem,
        options: DownloadOptions,
        onProgress: suspend (Progress) -> Unit,
    ): DownloadResult {
        // 1. Re-fetch to get playUrl —— probe 阶段已经拿过，但 v0.5.8 不缓存 MetadataResponse
        val aweme = apiClient.awemeItemInfo(item.itemId)
        if (aweme.playUrl.isBlank()) {
            throw IOException(
                "Douyin ${item.itemId} playUrl is empty " +
                    "(X-Bogus stub chaos 走真 API 仍 -352 风控; v0.5.9+ 真 get_chaos 实装)",
            )
        }
        // 2. Delegate to YtDlpEngine with the real download URL
        val downloadItem = item.copy(sourceUrl = aweme.playUrl)
        Timber.d("DouyinAdapter.download itemId=%s url=%s", item.itemId, aweme.playUrl)
        return ytDlpEngine.download(downloadItem, options, onProgress)
    }
}
