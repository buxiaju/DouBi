package com.doubi.android.core.platform.douyin

import com.doubi.android.core.model.DownloadOptions
import com.doubi.android.core.model.Platform
import com.doubi.android.core.platform.douyin.dto.DouyinAwemeItem
import com.google.common.truth.Truth.assertThat
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.mockk
import kotlinx.coroutines.test.runTest
import org.junit.Before
import org.junit.Test
import java.io.IOException

/**
 * 阶段 17 v0.5.7：[DouyinAdapter] 单测（mockk DouyinApiClient）。
 *
 * **覆盖**（6 例）：
 * 1. `name` = "douyin"
 * 2. `supports` VIDEO URL 返 true
 * 3. `supports` SHORT_LINK URL 返 true
 * 4. `supports` UNSUPPORTED URL 返 false
 * 5. `probe` VIDEO URL 拿 MediaItem（desc / duration / author / cover）
 * 6. `probe` UNSUPPORTED URL 抛 IOException
 * 7. `download` v0.5.7 placeholder 抛 IOException
 */
class DouyinAdapterTest {

    private val apiClient: DouyinApiClient = mockk(relaxed = false)
    private lateinit var adapter: DouyinAdapter

    @Before
    fun setUp() {
        adapter = DouyinAdapter(apiClient)
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

    @Test
    fun `download throws IOException v0_5_7 placeholder`() = runTest {
        val item = com.doubi.android.core.model.MediaItem(
            platform = Platform.DOUYIN,
            itemId = "7234567890123456789",
            sourceUrl = "https://www.douyin.com/video/7234567890123456789",
            title = "t",
        )
        val ex = runCatching {
            adapter.download(item, DownloadOptions()) { /* progress */ }
        }.exceptionOrNull()
        assertThat(ex).isInstanceOf(IOException::class.java)
        assertThat(ex!!.message!!).contains("v0.5.8+")
    }
}
