package com.doubi.android.core.platform.bilibili

import com.doubi.android.core.model.Author
import com.doubi.android.core.model.DownloadOptions
import com.doubi.android.core.model.DownloadResult
import com.doubi.android.core.model.MediaItem
import com.doubi.android.core.model.MediaType
import com.doubi.android.core.model.Platform
import com.doubi.android.core.model.Progress
import com.doubi.android.engine.Engine
import java.io.IOException
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 阶段 17 v0.5.7：B 站 [Engine] 实现。1:1 对拍桌面版 `src/doubi/platforms/bilibili/strategies.py:BilibiliStrategy`。
 *
 * **v0.5.7 范围**：
 * - `name = "bilibili"` —— 匹配 `AppConfig.engine` 取值
 * - `supports(url, ...)` —— 用 [BilibiliUrl.classify] 判断是否支持（VIDEO / SHORTS / BANGUMI 算支持；
 *   UNSUPPORTED 返 false）
 * - `probe(url, ...)` —— 调 [BilibiliApiClient.view] 拿 title / duration / cid / owner，构造
 *   [MediaItem]
 * - `download(item, ...)` —— v0.5.7 **placeholder**：`throw IOException("v0.5.8+ 才有")`——
 *   真下载（B 站 `playurl` 接口 + YtDlpEngine 跑真实下载）v0.5.8+ 单独 PR
 *
 * **架构**：
 * - `Engine` interface 在 v0.1 阶段 2 已落地（4 个成员：`name` / `supports` / `probe` / `download`）
 * - 桌面版 `BilibiliStrategy` 用 `auth.py` + `wbi.py` + `api.py` 三个文件
 * - Android 端 v0.5.4 / v0.5.5 / v0.5.6 分别落地 [WbiSigner] / [BilibiliApiClient]——v0.5.7 把
 *   三个文件**串起来**到 [Engine] interface
 *
 * **v0.5.7 简化**：
 * - **不**调用 B 站 `playurl` 接口（v0.5.8+）
 * - **不**拿真实 play URL（v0.5.8+ Engine 跑下载时拿）
 * - **不**调 YtDlpEngine 跑下载（v0.5.8+）
 * - 只做 **probe** 阶段（拿 metadata 填 MediaItem）
 * - `download` 直接抛 IOException 明确标记 v0.5.8+ 才有
 */
@Singleton
class BilibiliAdapter @Inject constructor(
    private val apiClient: BilibiliApiClient,
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
     * v0.5.7 placeholder：v0.5.8+ 才有 B 站 `playurl` 接口 + YtDlpEngine 跑真实下载。
     */
    override suspend fun download(
        item: MediaItem,
        options: DownloadOptions,
        onProgress: suspend (Progress) -> Unit,
    ): DownloadResult {
        throw IOException(
            "BilibiliAdapter.download not yet implemented (v0.5.8+: " +
                "B 站 playurl 接口 + YtDlpEngine 跑真实下载)"
        )
    }
}
