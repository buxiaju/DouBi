package com.doubi.android.core.platform.douyin

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
 * 阶段 17 v0.5.7：抖音 [Engine] 实现。1:1 对拍桌面版 `src/doubi/platforms/douyin/strategies.py:DouyinStrategy`。
 *
 * **v0.5.7 范围**：
 * - `name = "douyin"` —— 匹配 `AppConfig.engine` 取值
 * - `supports(url, ...)` —— 用 [DouyinUrl.classify] 判断是否支持（VIDEO / SHORT_LINK 算支持；
 *   UNSUPPORTED 返 false）
 * - `probe(url, ...)` —— 调 [DouyinApiClient.awemeItemInfo] 拿 desc / duration / author /
 *   play URL，构造 [MediaItem]
 * - `download(item, ...)` —— v0.5.7 **placeholder**：`throw IOException("v0.5.8+ 才有")`——
 *   真下载（抖音 `playwm` / `playaddr` 接口 + YtDlpEngine 跑真实下载）v0.5.8+ 单独 PR
 *
 * **v0.5.7 限制**：
 * - **X-Bogus 是 v0.5.5 placeholder**——v0.5.7 走真抖音 web API 仍 -352 风控
 * - 真 get_chaos 实装后 v0.5.8+ 才能真下抖音视频
 *
 * **架构**：
 * - `Engine` interface 在 v0.1 阶段 2 已落地
 * - 桌面版 `DouyinStrategy` 用 `auth.py` + `xbogus.py` + `api.py` 三个文件
 * - Android 端 v0.5.4 / v0.5.5 / v0.5.6 / v0.5.7 分别落地 [DouyinUrl] / [XBogusSigner] /
 *   [DouyinApiClient]——本阶段把它们**串起来**到 [Engine] interface
 */
@Singleton
class DouyinAdapter @Inject constructor(
    private val apiClient: DouyinApiClient,
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
     * v0.5.7 placeholder：v0.5.8+ 才有抖音 `playwm` / `playaddr` 接口 + YtDlpEngine 跑真实下载。
     */
    override suspend fun download(
        item: MediaItem,
        options: DownloadOptions,
        onProgress: suspend (Progress) -> Unit,
    ): DownloadResult {
        throw IOException(
            "DouyinAdapter.download not yet implemented (v0.5.8+: " +
                "抖音 playwm/playaddr 接口 + YtDlpEngine 跑真实下载)"
        )
    }
}
