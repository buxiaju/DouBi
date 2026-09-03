package com.doubi.android.core.sniffer

import com.doubi.android.core.config.AppConfig
import com.doubi.android.data.config.AppConfigDataStore
import com.google.common.truth.Truth.assertThat
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.every
import io.mockk.mockk
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.runTest
import org.junit.Test

/**
 * 阶段 10 v0.5.0：CompositeSniffer 单测。
 *
 * 覆盖：
 * - `sniffHeadless = true` 走 headless Sniffer（[WebViewHeadlessSniffer] 路径）
 * - `sniffHeadless = false` 走 http Sniffer（[HttpContentTypeSniffer] 路径）
 * - Error 跟 Media 透传
 *
 * **不测 [WebViewHeadlessSniffer] 自身**——WebView 是 Android framework
 * 真实组件，没法 mockk（要 Robolectric）。v0.5.0 范围只测 CompositeSniffer
 * 的切换契约。WebViewHeadlessSniffer 自身单测留 v0.5.1+ Robolectric 起来再补。
 */
@OptIn(ExperimentalCoroutinesApi::class)
class CompositeSnifferTest {

    @Test
    fun `sniff with sniffHeadless true invokes headless sniffer`() = runTest {
        val config = AppConfig(sniffHeadless = true)
        val configStore: AppConfigDataStore = mockk(relaxed = false) {
            coEvery { get() } returns config
        }
        val httpSniffer: Sniffer = mockk(relaxed = false)
        val headlessSniffer: Sniffer = mockk(relaxed = false)
        coEvery { headlessSniffer.sniff("https://www.bilibili.com/video/BV1xx") } returns
            SniffResult.Media("application/vnd.apple.mpegurl", "https://.../m3u8", null, true)

        val composite = CompositeSniffer(httpSniffer, headlessSniffer, configStore)
        val r = composite.sniff("https://www.bilibili.com/video/BV1xx")

        coVerify(exactly = 1) { headlessSniffer.sniff("https://www.bilibili.com/video/BV1xx") }
        coVerify(exactly = 0) { httpSniffer.sniff(any()) }
        assertThat(r).isInstanceOf(SniffResult.Media::class.java)
    }

    @Test
    fun `sniff with sniffHeadless false invokes http sniffer`() = runTest {
        val config = AppConfig(sniffHeadless = false)
        val configStore: AppConfigDataStore = mockk(relaxed = false) {
            coEvery { get() } returns config
        }
        val httpSniffer: Sniffer = mockk(relaxed = false)
        val headlessSniffer: Sniffer = mockk(relaxed = false)
        coEvery { httpSniffer.sniff("https://example.com/stream.m3u8") } returns
            SniffResult.Media("application/vnd.apple.mpegurl", "https://example.com/stream.m3u8", 1024L, true)

        val composite = CompositeSniffer(httpSniffer, headlessSniffer, configStore)
        val r = composite.sniff("https://example.com/stream.m3u8")

        coVerify(exactly = 1) { httpSniffer.sniff("https://example.com/stream.m3u8") }
        coVerify(exactly = 0) { headlessSniffer.sniff(any()) }
        assertThat(r).isInstanceOf(SniffResult.Media::class.java)
    }

    @Test
    fun `sniff propagates Error from headless sniffer when headless true`() = runTest {
        val config = AppConfig(sniffHeadless = true)
        val configStore: AppConfigDataStore = mockk(relaxed = false) {
            coEvery { get() } returns config
        }
        val httpSniffer: Sniffer = mockk(relaxed = false)
        val headlessSniffer: Sniffer = mockk(relaxed = false)
        coEvery { headlessSniffer.sniff(any()) } returns
            SniffResult.Error("WebView 嗅探失败", cause = null)

        val composite = CompositeSniffer(httpSniffer, headlessSniffer, configStore)
        val r = composite.sniff("https://example.com/page")

        assertThat(r).isInstanceOf(SniffResult.Error::class.java)
        val e = r as SniffResult.Error
        assertThat(e.message).contains("WebView 嗅探失败")
    }

    @Test
    fun `sniff propagates NotMedia from http sniffer when headless false`() = runTest {
        val config = AppConfig(sniffHeadless = false)
        val configStore: AppConfigDataStore = mockk(relaxed = false) {
            coEvery { get() } returns config
        }
        val httpSniffer: Sniffer = mockk(relaxed = false)
        val headlessSniffer: Sniffer = mockk(relaxed = false)
        coEvery { httpSniffer.sniff(any()) } returns
            SniffResult.NotMedia(200, "text/html", "HEAD Content-Type is not media")

        val composite = CompositeSniffer(httpSniffer, headlessSniffer, configStore)
        val r = composite.sniff("https://example.com/page.html")

        assertThat(r).isInstanceOf(SniffResult.NotMedia::class.java)
    }
}
