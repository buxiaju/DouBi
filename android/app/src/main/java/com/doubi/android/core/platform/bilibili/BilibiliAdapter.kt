package com.doubi.android.core.platform.bilibili

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
 * 阶段 17 v0.5.7 + 阶段 18 v0.5.8：B 站 [Engine] 实现。1:1 对拍桌面版 `src/doubi/platforms/bilibili/strategies.py:BilibiliStrategy`。
 *
 * **v0.5.7 范围**（probe 阶段）：
 * - `name = "bilibili"` —— 匹配 `AppConfig.engine` 取值
 * - `supports(url, ...)` —— 用 [BilibiliUrl.classify] 判断是否支持（VIDEO / SHORTS / BANGUMI 算支持；
 *   UNSUPPORTED 返 false）
 * - `probe(url, ...)` —— 调 [BilibiliApiClient.view] 拿 title / duration / cid / owner，构造
 *   [MediaItem]
 * - `download(item, ...)` —— v0.5.7 **placeholder**：`throw IOException("v0.5.8+ 才有")`
 *
 * **v0.5.8 范围新增**（download 真路径）：
 * - `download(item, ...)` —— 调 [BilibiliApiClient.view] 拿 `cid` → 调 [BilibiliApiClient.playurl]
 *   拿 `durl[0].url` 真实下载直链 → 委托 [YtDlpEngine.download] 跑下载
 * - 进度回调 `onProgress` 透传到 YtDlpEngine
 * - 输出路径仍走 YtDlpEngine 的 `baseOutputDir` 模板（`{platform}/{author}/{media_type}/{title}_{item_id}.%(ext)s`）
 *
 * **架构**：
 * - `Engine` interface 在 v0.1 阶段 2 已落地（4 个成员：`name` / `supports` / `probe` / `download`）
 * - 桌面版 `BilibiliStrategy` 用 `auth.py` + `wbi.py` + `api.py` + `playurl` 四个文件
 * - Android 端 v0.5.4 / v0.5.5 / v0.5.6 / v0.5.7 / v0.5.8 分别落地 [WbiSigner] / [BilibiliApiClient] /
 *   [BilibiliAdapter] / [BilibiliApiClient.playurl] —— 本阶段把 playurl 串进 download 路径
 */
@Singleton
class BilibiliAdapter @Inject constructor(
    private val apiClient: BilibiliApiClient,
    private val ytDlpEngine: YtDlpEngine,
) : Engine {
    override val name: String = "bilibili"

    /**
     * B 站支持：VIDEO / SHORTS / BANGUMI。
     * UNSUPPORTED（专栏 / 动态 / 列表 / 课程 / 活动 / 黑板 / H5）返 false。
     */
    override fun supports(url: String, options: DownloadOptions): Boolean {
        val classified = BilibiliUrl.classify(url)
        return classified.type != BilibiliUrlType.UNSUPPORTED
    }

    /**
     * 调 [BilibiliApiClient.view] 拿 metadata，构造 [MediaItem]。
     *
     * **v0.5.7 不**拿 formats 列表（`playurl` 接口 + 解析返的 [MediaFormat] 列表 v0.5.8+）。
     * UI 端走「无 format 选项」路径（v0.5.7 简化版 UI）。
     */
    override suspend fun probe(url: String, options: DownloadOptions): MediaItem {
        val classified = BilibiliUrl.classify(url)
        val bvid = when (classified.type) {
            BilibiliUrlType.VIDEO -> classified.id.removePrefix("av")
            BilibiliUrlType.SHORTS -> classified.id
            BilibiliUrlType.BANGUMI -> classified.id
            BilibiliUrlType.UNSUPPORTED,
            BilibiliUrlType.AUDIO,
            BilibiliUrlType.LIVE -> throw IOException("unsupported B 站 URL: $url (${classified.type})")
        }
        val view = apiClient.view(bvid)
        return MediaItem(
            platform = Platform.BILIBILI,
            itemId = view.bvid,
            sourceUrl = url,
            title = view.title,
            author = if (view.ownerName.isNotBlank()) Author(
                id = view.ownerMid.toString(),
                name = view.ownerName,
                avatarUrl = null,
            ) else null,
            duration = view.duration.toDouble(),
            mediaType = MediaType.VIDEO,
        )
    }

    /**
     * v0.5.8 真路径：
     * 1. 调 [BilibiliApiClient.view] 拿 `cid`（v0.5.7 拿的 metadata 不含 cid，**只** [view] 返）
     * 2. 调 [BilibiliApiClient.playurl] 拿 `durl[0].url` 真实下载直链（FLV / MP4 / m3u8）
     * 3. 复制 [MediaItem] 但把 `sourceUrl` 替换成 playurl 拿到的直链
     * 4. 委托 [YtDlpEngine.download] 跑下载——output path 走 yt-dlp 模板（`{platform}/{author}/{media_type}/{title}_{item_id}.%(ext)s`）
     *
     * **v0.5.8 简化**：
     * - 单一清晰度 `qn=80`（硬编码），v0.5.9+ 接 [AppConfig.bilibiliQuality] 配置
     * - 不取 dash 流（v0.5.8 fallback 到 `dash.video[0].baseUrl` 但 yt-dlp 跑 DASH 需要 MP4Box / ffmpeg 合并，超出范围）
     * - 不缓存 mixin_key（每次调都重新 fetch nav，~200ms 延迟）
     *
     * **错误处理**：
     * - `view` 抛 IOException → 上传（API 失败 / 视频不存在 / 风控）
     * - `view` 返 `cid=0` → 抛 IOException（理论上不会，B站任何视频都有 cid）
     * - `playurl` 抛 IOException → 上传（业务 -352 风控 / 视频付费 / 地区限制）
     * - `playurl` 返空 url（regex 没匹配到 durl / dash）→ 抛 IOException
     * - `YtDlpEngine.download` 抛异常 → 透传
     */
    override suspend fun download(
        item: MediaItem,
        options: DownloadOptions,
        onProgress: suspend (Progress) -> Unit,
    ): DownloadResult {
        // 1. Get cid via view() —— metadata 可能没填 cid（probe 早期版本）
        val view = apiClient.view(item.itemId)
        if (view.cid == 0L) {
            throw IOException("Bilibili ${item.itemId} cid=0 (view API 没返 cid)")
        }
        // 2. Get play URL via playurl() —— 默认 qn=80 (1080p 高清)
        val playResp = apiClient.playurl(item.itemId, view.cid)
        if (playResp.url.isBlank()) {
            throw IOException("Bilibili ${item.itemId} playurl 返空 url")
        }
        // 3. Delegate to YtDlpEngine with the real download URL
        val downloadItem = item.copy(sourceUrl = playResp.url)
        Timber.d("BilibiliAdapter.download bvid=%s cid=%d url=%s", item.itemId, view.cid, playResp.url)
        return ytDlpEngine.download(downloadItem, options, onProgress)
    }
}
