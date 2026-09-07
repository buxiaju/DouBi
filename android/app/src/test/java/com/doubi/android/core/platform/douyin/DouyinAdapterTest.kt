package com.doubi.android.core.platform.douyin

import com.doubi.android.core.model.DownloadOptions
import com.doubi.android.core.model.DownloadResult
import com.doubi.android.core.model.MediaItem
import com.doubi.android.core.model.Platform
import com.doubi.android.core.platform.douyin.dto.DouyinAwemeItem
import com.doubi.android.engine.ytdlp.YtDlpEngine
import com.google.common.truth.Truth.assertThat
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.coVerifyOrder
import io.mockk.mockk
import kotlinx.coroutines.test.runTest
import org.junit.Before
import org.junit.Test
import java.io.IOException

/**
 * 阶段 17 v0.5.7 + 阶段 18 v0.5.8：[DouyinAdapter] 单测（mockk DouyinApiClient + YtDlpEngine）。
 *
 * **覆盖**（12 例）：
 *
 * v0.5.7 已有（8 例）：
 * 1. `name` = "douyin"
 * 2. `supports` VIDEO URL 返 true
 * 3. `supports` SHORT_LINK URL 返 true
 * 4. `supports` 非抖音域名 URL 返 false
 * 5. `probe` VIDEO URL 拿 MediaItem（desc / duration / author / cover）
 * 6. `probe` SHORT_LINK URL uses short id as itemId (v0_5_7 simplification)
 * 7. `probe` 非抖音 URL 抛 IOException
 * 8. `download` v0.5.7 placeholder 抛 IOException（v0.5.8+ 才有）
 *
 * v0.5.8 新增（4 例）：
 * 9. `download` 调 awemeItemInfo → YtDlpEngine.download() 完整链路
 * 10. `download` awemeItemInfo 抛 IOException 透传
 * 11. `download` awemeItemInfo 返 playUrl 空 → 抛 IOException（X-Bogus stub chaos）
 * 12. `download` YtDlpEngine.download() 返 DownloadResult.Failure 透传
 *
 * v0.5.7 的 `download throws IOException v0.5.7 placeholder` 测试**删除**（v0.5.8
 * download 是真路径，placeholder 不再存在）。
 */
class DouyinAdapterTest {

    private val apiClient: DouyinApiClient = mockk()
    private val ytDlpEngine: YtDlpEngine = mockk()
    private lateinit var adapter: DouyinAdapter

    @Before
    fun setUp() {
        adapter = DouyinAdapter(apiClient, ytDlpEngine)
    }

    @Test
    fun `name is douyin`() {
        assertThat(adapter.name).isEqualTo("douyin")
    }

    @Test
    fun `supports VIDEO URL returns true`() {
        val result = adapter.supports("https://www.douyin.com/video/7234567890123456789", DownloadOptions())
        assertThat(result).isTrue()
    }

    @Test
    fun `supports SHORT_LINK URL returns true`() {
        val result = adapter.supports("https://v.douyin.com/abcdef12/", DownloadOptions())
        assertThat(result).isTrue()
    }

    @Test
    fun `supports non-douyin URL returns false`() {
        val result = adapter.supports("https://www.example.com/video/123", DownloadOptions())
        assertThat(result).isFalse()
    }

    @Test
    fun `probe VIDEO URL returns MediaItem with API metadata`() = runTest {
        coEvery { apiClient.awemeItemInfo("7234567890123456789") } returns DouyinAwemeItem(
            awemeId = "7234567890123456789",
            desc = "测试视频",
            durationSec = 30,
            authorNickname = "测试作者",
            authorSecUid = "MS4wLjABAAAA12345",
            playUrl = "https://example.com/play",
            coverUrl = "https://example.com/cover",
        )

        val item = adapter.probe("https://www.douyin.com/video/7234567890123456789", DownloadOptions())

        assertThat(item.platform).isEqualTo(Platform.DOUYIN)
        assertThat(item.itemId).isEqualTo("7234567890123456789")
        assertThat(item.title).isEqualTo("测试视频")
        assertThat(item.duration).isEqualTo(30.0)
        assertThat(item.author?.name).isEqualTo("测试作者")
        assertThat(item.author?.id).isEqualTo("MS4wLjABAAAA12345")
        assertThat(item.coverUrl).isEqualTo("https://example.com/cover")
        coVerify(exactly = 1) { apiClient.awemeItemInfo("7234567890123456789") }
    }

    @Test
    fun `probe SHORT_LINK URL uses short id as itemId (v0_5_7 simplification)`() = runTest {
        coEvery { apiClient.awemeItemInfo("abcdef12") } returns DouyinAwemeItem(
            awemeId = "abcdef12",
            desc = "短链视频",
            durationSec = 15,
            authorNickname = "",
            authorSecUid = "",
            playUrl = "",
            coverUrl = "",
        )

        val item = adapter.probe("https://v.douyin.com/abcdef12/", DownloadOptions())

        // v0.5.7 简化：短链 id 直接当 itemId（v0.5.8+ 解析 short_link → video_id）
        assertThat(item.itemId).isEqualTo("abcdef12")
        assertThat(item.title).isEqualTo("短链视频")
        assertThat(item.author).isNull()  // empty nickname → null author
        assertThat(item.coverUrl).isNull()  // empty coverUrl → null
    }

    @Test
    fun `probe non-douyin URL throws IOException`() = runTest {
        val ex = runCatching {
            adapter.probe("https://www.example.com/video/123", DownloadOptions())
        }.exceptionOrNull()
        assertThat(ex).isInstanceOf(IOException::class.java)
        assertThat(ex!!.message!!).contains("unsupported 抖音 URL")
    }

    // ---- v0.5.8 download 真路径 ----

    @Test
    fun `download calls awemeItemInfo then delegates to YtDlpEngine with real playUrl`() = runTest {
        // awemeItemInfo 返真实 playUrl
        coEvery { apiClient.awemeItemInfo("7234567890123456789") } returns DouyinAwemeItem(
            awemeId = "7234567890123456789",
            desc = "测试视频",
            durationSec = 30,
            authorNickname = "测试作者",
            authorSecUid = "MS4wLjABAAAA12345",
            playUrl = "https://v26-cold.douyinvod.com/xxx.mp4",
            coverUrl = "https://example.com/cover",
        )
        // YtDlpEngine 返成功
        coEvery { ytDlpEngine.download(any(), any(), any()) } returns DownloadResult.Success("/data/output.mp4")

        val item = MediaItem(
            platform = Platform.DOUYIN,
            itemId = "7234567890123456789",
            sourceUrl = "https://www.douyin.com/video/7234567890123456789",
            title = "测试视频",
        )
        val result = adapter.download(item, DownloadOptions()) { /* progress */ }

        // 验证调用顺序：awemeItemInfo → YtDlpEngine.download
        coVerifyOrder {
            apiClient.awemeItemInfo("7234567890123456789")
            ytDlpEngine.download(
                match { it.sourceUrl == "https://v26-cold.douyinvod.com/xxx.mp4" },
                any(),
                any(),
            )
        }
        // 验平台 / itemId / title 在 downloadItem 透传
        coVerify(exactly = 1) {
            ytDlpEngine.download(
                match {
                    it.platform == Platform.DOUYIN &&
                        it.itemId == "7234567890123456789" &&
                        it.title == "测试视频"
                },
                any(),
                any(),
            )
        }
        assertThat(result).isInstanceOf(DownloadResult.Success::class.java)
        assertThat((result as DownloadResult.Success).localPath).isEqualTo("/data/output.mp4")
    }

    @Test
    fun `download propagates IOException from awemeItemInfo API failure`() = runTest {
        // 模拟抖音 -352 风控 / 视频不存在 / 网络错误
        coEvery { apiClient.awemeItemInfo("7234567890123456789") } throws
            IOException("awemeItemInfo failed: -352 风控")

        val item = MediaItem(
            platform = Platform.DOUYIN,
            itemId = "7234567890123456789",
            sourceUrl = "https://www.douyin.com/video/7234567890123456789",
            title = "t",
        )
        val ex = runCatching { adapter.download(item, DownloadOptions()) { } }.exceptionOrNull()
        assertThat(ex).isInstanceOf(IOException::class.java)
        assertThat(ex!!.message!!).contains("-352")
        // 不应调 YtDlpEngine
        coVerify(exactly = 0) { ytDlpEngine.download(any(), any(), any()) }
    }

    @Test
    fun `download throws IOException when awemeItemInfo returns empty playUrl (X-Bogus stub chaos)`() = runTest {
        // 模拟 X-Bogus stub chaos 走真 API 返 -352 → playUrl 是空字符串
        coEvery { apiClient.awemeItemInfo("7234567890123456789") } returns DouyinAwemeItem(
            awemeId = "7234567890123456789",
            desc = "t",
            durationSec = 30,
            authorNickname = "",
            authorSecUid = "",
            playUrl = "",  // 关键：空 playUrl
            coverUrl = "",
        )

        val item = MediaItem(
            platform = Platform.DOUYIN,
            itemId = "7234567890123456789",
            sourceUrl = "https://www.douyin.com/video/7234567890123456789",
            title = "t",
        )
        val ex = runCatching { adapter.download(item, DownloadOptions()) { } }.exceptionOrNull()
        assertThat(ex).isInstanceOf(IOException::class.java)
        assertThat(ex!!.message!!).contains("playUrl is empty")
        assertThat(ex!!.message!!).contains("v0.5.9+")
        coVerify(exactly = 0) { ytDlpEngine.download(any(), any(), any()) }
    }

    @Test
    fun `download propagates DownloadResult Failure from YtDlpEngine`() = runTest {
        coEvery { apiClient.awemeItemInfo("7234567890123456789") } returns DouyinAwemeItem(
            awemeId = "7234567890123456789",
            desc = "t",
            durationSec = 30,
            authorNickname = "",
            authorSecUid = "",
            playUrl = "https://v26-cold.douyinvod.com/xxx.mp4",
            coverUrl = "",
        )
        // YtDlpEngine 返 Failure
        coEvery { ytDlpEngine.download(any(), any(), any()) } returns
            DownloadResult.Failure("yt-dlp exit=1: 403 Forbidden")

        val item = MediaItem(
            platform = Platform.DOUYIN,
            itemId = "7234567890123456789",
            sourceUrl = "https://www.douyin.com/video/7234567890123456789",
            title = "t",
        )
        val result = adapter.download(item, DownloadOptions()) { }
        assertThat(result).isInstanceOf(DownloadResult.Failure::class.java)
        assertThat((result as DownloadResult.Failure).reason).contains("yt-dlp exit=1")
    }
}
