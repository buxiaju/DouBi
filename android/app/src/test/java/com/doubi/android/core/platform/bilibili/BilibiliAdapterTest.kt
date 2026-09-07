package com.doubi.android.core.platform.bilibili

import com.doubi.android.core.model.DownloadOptions
import com.doubi.android.core.model.DownloadResult
import com.doubi.android.core.model.MediaItem
import com.doubi.android.core.model.Platform
import com.doubi.android.core.platform.bilibili.dto.BilibiliPlayUrlResponse
import com.doubi.android.core.platform.bilibili.dto.BilibiliViewResponse
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
 * 阶段 17 v0.5.7 + 阶段 18 v0.5.8：[BilibiliAdapter] 单测（mockk BilibiliApiClient + YtDlpEngine）。
 *
 * **覆盖**（14 例）：
 *
 * v0.5.7 已有（9 例）：
 * 1. `name` = "bilibili"
 * 2. `supports` VIDEO URL 返 true
 * 3. `supports` SHORTS URL 返 true
 * 4. `supports` BANGUMI URL 返 true
 * 5. `supports` UNSUPPORTED URL（专栏）返 false
 * 6. `supports` 非 B 站域名 URL 返 false
 * 7. `probe` VIDEO URL 拿 MediaItem（title / duration / author）
 * 8. `probe` SHORTS URL → empty ownerName → null author
 * 9. `probe` UNSUPPORTED URL 抛 IOException
 *
 * v0.5.8 新增（5 例）：
 * 10. `download` 调 view() → playurl() → ytDlpEngine.download() 完整链路
 * 11. `download` view() 抛 IOException 透传
 * 12. `download` view() 返 cid=0 抛 IOException
 * 13. `download` playurl() 抛 IOException 透传（-352 风控）
 * 14. `download` ytDlpEngine.download() 返 DownloadResult.Failure 透传
 *
 * v0.5.7 的 `download throws IOException v0.5.7 placeholder` 测试**删除**（v0.5.8
 * download 是真路径，placeholder 不再存在）。
 */
class BilibiliAdapterTest {

    private val apiClient: BilibiliApiClient = mockk()
    private val ytDlpEngine: YtDlpEngine = mockk()
    private lateinit var adapter: BilibiliAdapter

    @Before
    fun setUp() {
        adapter = BilibiliAdapter(apiClient, ytDlpEngine)
    }

    @Test
    fun `name is bilibili`() {
        assertThat(adapter.name).isEqualTo("bilibili")
    }

    @Test
    fun `supports VIDEO URL returns true`() {
        val result = adapter.supports("https://www.bilibili.com/video/BV1xx411c7mD", DownloadOptions())
        assertThat(result).isTrue()
    }

    @Test
    fun `supports SHORTS URL returns true`() {
        val result = adapter.supports("https://www.bilibili.com/shorts/BV1Ab2Cd3Ef4", DownloadOptions())
        assertThat(result).isTrue()
    }

    @Test
    fun `supports BANGUMI URL returns true`() {
        val result = adapter.supports("https://www.bilibili.com/bangumi/play/ep12345", DownloadOptions())
        assertThat(result).isTrue()
    }

    @Test
    fun `supports UNSUPPORTED URL returns false`() {
        val result = adapter.supports("https://www.bilibili.com/read/cv12345", DownloadOptions())
        assertThat(result).isFalse()
    }

    @Test
    fun `supports non-bilibili URL returns false`() {
        val result = adapter.supports("https://www.example.com/video/BV1xx411c7mD", DownloadOptions())
        assertThat(result).isFalse()
    }

    @Test
    fun `probe VIDEO URL returns MediaItem with API metadata`() = runTest {
        coEvery { apiClient.view("BV1xx411c7mD") } returns BilibiliViewResponse(
            bvid = "BV1xx411c7mD",
            aid = 170001L,
            title = "测试视频",
            duration = 300,
            cid = 12345L,
            ownerName = "测试UP",
            ownerMid = 100L,
            pageCount = 1,
        )

        val item = adapter.probe("https://www.bilibili.com/video/BV1xx411c7mD", DownloadOptions())

        assertThat(item.platform).isEqualTo(Platform.BILIBILI)
        assertThat(item.itemId).isEqualTo("BV1xx411c7mD")
        assertThat(item.title).isEqualTo("测试视频")
        assertThat(item.duration).isEqualTo(300.0)
        assertThat(item.author?.name).isEqualTo("测试UP")
        assertThat(item.author?.id).isEqualTo("100")
        coVerify(exactly = 1) { apiClient.view("BV1xx411c7mD") }
    }

    @Test
    fun `probe SHORTS URL calls API with BV id`() = runTest {
        coEvery { apiClient.view("BV1Ab2Cd3Ef4") } returns BilibiliViewResponse(
            bvid = "BV1Ab2Cd3Ef4",
            aid = 0L,
            title = "短片",
            duration = 60,
            cid = 1L,
            ownerName = "",
            ownerMid = 0L,
            pageCount = 0,
        )

        val item = adapter.probe("https://www.bilibili.com/shorts/BV1Ab2Cd3Ef4", DownloadOptions())

        assertThat(item.itemId).isEqualTo("BV1Ab2Cd3Ef4")
        assertThat(item.title).isEqualTo("短片")
        assertThat(item.author).isNull()  // empty ownerName → null author
    }

    @Test
    fun `probe UNSUPPORTED URL throws IOException`() = runTest {
        val ex = runCatching {
            adapter.probe("https://www.bilibili.com/read/cv12345", DownloadOptions())
        }.exceptionOrNull()
        assertThat(ex).isInstanceOf(IOException::class.java)
        assertThat(ex!!.message!!).contains("unsupported B 站 URL")
    }

    // ---- v0.5.8 download 真路径 ----

    @Test
    fun `download calls view then playurl then delegates to YtDlpEngine with real download URL`() = runTest {
        // view() 拿 cid
        coEvery { apiClient.view("BV1xx411c7mD") } returns BilibiliViewResponse(
            bvid = "BV1xx411c7mD",
            aid = 170001L,
            title = "测试视频",
            duration = 300,
            cid = 12345L,
            ownerName = "测试UP",
            ownerMid = 100L,
            pageCount = 1,
        )
        // playurl() 拿真实下载直链
        coEvery { apiClient.playurl("BV1xx411c7mD", 12345L, 80) } returns BilibiliPlayUrlResponse(
            url = "https://cn-jsnt-cu.bilivideo.com/12345?bvid=BV1xx",
            size = 12345678L,
        )
        // YtDlpEngine.download 返成功
        coEvery { ytDlpEngine.download(any(), any(), any()) } returns DownloadResult.Success("/data/output.mp4")

        val item = MediaItem(
            platform = Platform.BILIBILI,
            itemId = "BV1xx411c7mD",
            sourceUrl = "https://www.bilibili.com/video/BV1xx411c7mD",
            title = "测试视频",
        )
        val result = adapter.download(item, DownloadOptions()) { /* progress */ }

        // 验证调用顺序：view → playurl → YtDlpEngine.download
        coVerifyOrder {
            apiClient.view("BV1xx411c7mD")
            apiClient.playurl("BV1xx411c7mD", 12345L, 80)
            ytDlpEngine.download(
                match { it.sourceUrl == "https://cn-jsnt-cu.bilivideo.com/12345?bvid=BV1xx" },
                any(),
                any(),
            )
        }
        // 验平台 / itemId / title 在 downloadItem 透传
        coVerify(exactly = 1) {
            ytDlpEngine.download(
                match {
                    it.platform == Platform.BILIBILI &&
                        it.itemId == "BV1xx411c7mD" &&
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
    fun `download propagates IOException from view API failure`() = runTest {
        // view() 抛 IOException（B 站 -352 风控 / 视频不存在 / 网络错误）
        coEvery { apiClient.view("BV1xx411c7mD") } throws IOException("view failed: HTTP 403")

        val item = MediaItem(
            platform = Platform.BILIBILI,
            itemId = "BV1xx411c7mD",
            sourceUrl = "https://www.bilibili.com/video/BV1xx411c7mD",
            title = "t",
        )
        val ex = runCatching { adapter.download(item, DownloadOptions()) { } }.exceptionOrNull()
        assertThat(ex).isInstanceOf(IOException::class.java)
        assertThat(ex!!.message!!).contains("view failed")
        // 不应调 playurl / YtDlpEngine
        coVerify(exactly = 0) { apiClient.playurl(any(), any(), any()) }
        coVerify(exactly = 0) { ytDlpEngine.download(any(), any(), any()) }
    }

    @Test
    fun `download throws IOException when view returns cid zero`() = runTest {
        // view() 返 cid=0（B 站理论上不会，但 view 失败 / cid 字段缺失可能）
        coEvery { apiClient.view("BV1xx411c7mD") } returns BilibiliViewResponse(
            bvid = "BV1xx411c7mD",
            aid = 0L,
            title = "t",
            duration = 0,
            cid = 0L,  // 异常
            ownerName = "",
            ownerMid = 0L,
            pageCount = 0,
        )

        val item = MediaItem(
            platform = Platform.BILIBILI,
            itemId = "BV1xx411c7mD",
            sourceUrl = "https://www.bilibili.com/video/BV1xx411c7mD",
            title = "t",
        )
        val ex = runCatching { adapter.download(item, DownloadOptions()) { } }.exceptionOrNull()
        assertThat(ex).isInstanceOf(IOException::class.java)
        assertThat(ex!!.message!!).contains("cid=0")
        coVerify(exactly = 0) { apiClient.playurl(any(), any(), any()) }
    }

    @Test
    fun `download propagates IOException from playurl API failure (e g minus 352)`() = runTest {
        coEvery { apiClient.view("BV1xx411c7mD") } returns BilibiliViewResponse(
            bvid = "BV1xx411c7mD",
            aid = 170001L,
            title = "测试视频",
            duration = 300,
            cid = 12345L,
            ownerName = "测试UP",
            ownerMid = 100L,
            pageCount = 1,
        )
        // playurl 抛 IOException（-352 风控）
        coEvery { apiClient.playurl(any(), any(), any()) } throws IOException("playurl returned code=-352 message=风控校验失败")

        val item = MediaItem(
            platform = Platform.BILIBILI,
            itemId = "BV1xx411c7mD",
            sourceUrl = "https://www.bilibili.com/video/BV1xx411c7mD",
            title = "t",
        )
        val ex = runCatching { adapter.download(item, DownloadOptions()) { } }.exceptionOrNull()
        assertThat(ex).isInstanceOf(IOException::class.java)
        assertThat(ex!!.message!!).contains("-352")
        coVerify(exactly = 0) { ytDlpEngine.download(any(), any(), any()) }
    }

    @Test
    fun `download propagates DownloadResult Failure from YtDlpEngine`() = runTest {
        coEvery { apiClient.view("BV1xx411c7mD") } returns BilibiliViewResponse(
            bvid = "BV1xx411c7mD",
            aid = 170001L,
            title = "t",
            duration = 300,
            cid = 12345L,
            ownerName = "u",
            ownerMid = 100L,
            pageCount = 1,
        )
        coEvery { apiClient.playurl(any(), any(), any()) } returns BilibiliPlayUrlResponse(
            url = "https://example.com/video.flv",
            size = 12345L,
        )
        // YtDlpEngine 返 Failure
        coEvery { ytDlpEngine.download(any(), any(), any()) } returns DownloadResult.Failure("yt-dlp exit=1: ...")

        val item = MediaItem(
            platform = Platform.BILIBILI,
            itemId = "BV1xx411c7mD",
            sourceUrl = "https://www.bilibili.com/video/BV1xx411c7mD",
            title = "t",
        )
        val result = adapter.download(item, DownloadOptions()) { }
        assertThat(result).isInstanceOf(DownloadResult.Failure::class.java)
        assertThat((result as DownloadResult.Failure).reason).contains("yt-dlp exit=1")
    }
}
