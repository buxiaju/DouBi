package com.doubi.android.core.platform.bilibili

import com.doubi.android.core.model.DownloadOptions
import com.doubi.android.core.model.Platform
import com.google.common.truth.Truth.assertThat
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.mockk
import kotlinx.coroutines.test.runTest
import org.junit.Before
import org.junit.Test
import java.io.IOException

/**
 * 阶段 17 v0.5.7：[BilibiliAdapter] 单测（mockk BilibiliApiClient）。
 *
 * **覆盖**（5 例）：
 * 1. `name` = "bilibili"
 * 2. `supports` VIDEO URL 返 true
 * 3. `supports` UNSUPPORTED URL（专栏/动态/列表）返 false
 * 4. `probe` VIDEO URL 拿 MediaItem（title / duration / author）
 * 5. `probe` UNSUPPORTED URL 抛 IOException
 * 6. `download` v0.5.7 placeholder 抛 IOException（v0.5.8+ 才有）
 */
class BilibiliAdapterTest {

    private val apiClient: BilibiliApiClient = mockk(relaxed = false)
    private lateinit var adapter: BilibiliAdapter

    @Before
    fun setUp() {
        adapter = BilibiliAdapter(apiClient)
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
        coEvery { apiClient.view("BV1xx411c7mD") } returns com.doubi.android.core.platform.bilibili.dto.BilibiliViewResponse(
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
        coEvery { apiClient.view("BV1Ab2Cd3Ef4") } returns com.doubi.android.core.platform.bilibili.dto.BilibiliViewResponse(
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

    @Test
    fun `download throws IOException v0_5_7 placeholder`() = runTest {
        val item = com.doubi.android.core.model.MediaItem(
            platform = Platform.BILIBILI,
            itemId = "BV1xx411c7mD",
            sourceUrl = "https://www.bilibili.com/video/BV1xx411c7mD",
            title = "t",
        )
        val ex = runCatching {
            adapter.download(item, DownloadOptions()) { /* progress */ }
        }.exceptionOrNull()
        assertThat(ex).isInstanceOf(IOException::class.java)
        assertThat(ex!!.message!!).contains("v0.5.8+")
    }
}
