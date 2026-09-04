package com.doubi.android.core.sniffer

import android.content.Context
import android.webkit.WebView
import com.google.common.truth.Truth.assertThat
import io.mockk.coVerify
import io.mockk.every
import io.mockk.mockk
import io.mockk.verify
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Before
import org.junit.Test

/**
 * 阶段 11 v0.5.1：[WebViewHolder] 单测（idle release 契约）。
 *
 * **覆盖**（5 例）：
 * 1. 第一次 [WebViewHolder.withLock] 调 [WebViewFactory.create] 创建一个 WebView
 * 2. 连续多次 [WebViewHolder.withLock] 复用同一个 WebView（不重复创建）
 * 3. [WebViewHolder.releaseNow] 立即销毁 WebView 并清空 current
 * 4. 单次 [WebViewHolder.withLock] 退出后 [IDLE_TIMEOUT_MS] 自动 release
 * 5. 新 [WebViewHolder.withLock] 在 idle 窗口内取消挂起的 release（保留 WebView 复用）
 *
 * **不测**（v0.5.1 范围外）：
 * - WebView 自身 0 size / GONE / JS enabled 配置——这些是 Android framework 行为，
 *   单测 mockk 出的 WebView 不走真实代码。需要 Robolectric 或真机验证（v0.5.1+ 留欠账）
 * - 并发 [WebViewHolder.withLock] 串行化——kotlinx-coroutines 的 Mutex 已被
 *   自身测试覆盖，重复测无价值
 *
 * **Dispatchers.Main 设置**：
 * [WebViewHolder] 的 release 协程用 `Dispatchers.Main.immediate`。单测用
 * [StandardTestDispatcher] setMain 替换 Main，[delay] 用虚拟时间，可调 [advanceTimeBy]
 * 模拟 30s 流逝。
 */
@OptIn(ExperimentalCoroutinesApi::class)
class WebViewHolderTest {

    private val testDispatcher = StandardTestDispatcher()
    private val mockContext: Context = mockk(relaxed = true)
    private val mockFactory: WebViewFactory = mockk(relaxed = false)
    private val mockWebView: WebView = mockk(relaxed = true)

    private lateinit var holder: WebViewHolder

    @Before
    fun setUp() {
        Dispatchers.setMain(testDispatcher)
        holder = WebViewHolder(mockContext, mockFactory)
        every { mockFactory.create(mockContext) } returns mockWebView
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun `withLock creates WebView on first call`() = runTest(testDispatcher) {
        assertThat(holder.isCreated()).isFalse()

        holder.withLock { /* nothing */ }

        assertThat(holder.isCreated()).isTrue()
        verify(exactly = 1) { mockFactory.create(mockContext) }
    }

    @Test
    fun `withLock reuses existing WebView on subsequent calls`() = runTest(testDispatcher) {
        holder.withLock { /* first */ }
        holder.withLock { /* second */ }
        holder.withLock { /* third */ }
        // 注意：不能调 advanceUntilIdle() —— 它会快进时间到 30s 触发 release，破坏复用契约
        // release job 的 delay(30_000) 还在等虚拟时间前进，本例不验证 timeout 行为

        assertThat(holder.isCreated()).isTrue()
        verify(exactly = 1) { mockFactory.create(mockContext) }
    }

    @Test
    fun `releaseNow destroys WebView and clears current`() = runTest(testDispatcher) {
        holder.withLock { /* creates */ }
        assertThat(holder.isCreated()).isTrue()

        holder.releaseNow()
        advanceUntilIdle()

        assertThat(holder.isCreated()).isFalse()
        verify(exactly = 1) { mockWebView.stopLoading() }
        verify(exactly = 1) { mockWebView.loadUrl("about:blank") }
        verify(exactly = 1) { mockWebView.destroy() }
    }

    @Test
    fun `WebView is released after IDLE_TIMEOUT_MS of inactivity`() = runTest(testDispatcher) {
        holder.withLock { /* creates */ }
        assertThat(holder.isCreated()).isTrue()
        assertThat(holder.hasPendingRelease()).isTrue()

        // 30s 计时：前进 30s 触发 release
        advanceTimeBy(WebViewHolder.IDLE_TIMEOUT_MS)
        runCurrent()

        assertThat(holder.isCreated()).isFalse()
        verify(exactly = 1) { mockWebView.destroy() }
    }

    @Test
    fun `new withLock within idle window cancels pending release`() = runTest(testDispatcher) {
        holder.withLock { /* first call creates + schedules release */ }
        assertThat(holder.isCreated()).isTrue()
        assertThat(holder.hasPendingRelease()).isTrue()

        // 10s 后新 sniff 到来——还在 30s 窗口内
        advanceTimeBy(10_000L)
        runCurrent()
        assertThat(holder.isCreated()).isTrue()  // 没被 release

        // 新 sniff 进来——会取消 release
        holder.withLock { /* second call reuses WebView */ }
        assertThat(holder.hasPendingRelease()).isTrue()  // 又调度了一个 release

        // 复用 WebView，没新创建
        verify(exactly = 1) { mockFactory.create(mockContext) }
        // destroy 一次也没调用——两个 release 都被取消了
        verify(exactly = 0) { mockWebView.destroy() }
    }
}
