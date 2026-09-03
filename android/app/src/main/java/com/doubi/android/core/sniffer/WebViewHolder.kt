package com.doubi.android.core.sniffer

import android.annotation.SuppressLint
import android.content.Context
import android.view.View
import android.view.ViewGroup
import android.webkit.WebSettings
import android.webkit.WebView
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 阶段 10 v0.5.0 headless browser 嗅探（WebView 集成）：共享不可见 WebView 单例。
 *
 * **为什么单例**：
 * - WebView 创建慢（首次 100-300ms）——任务频繁时反复创建会卡
 * - WebView 持有 1 个 Chromium 进程 + GPU 资源（~30-50MB）——单例复用以减少
 *   内存抖动
 *
 * **为什么不可见**：
 * - WebView 必须 attach 到 view hierarchy 才能渲染（否则 loadUrl 抛
 *   "WebView not attached to window"）
 * - 但用户不需要看到浏览器——v0.5.0 headless Sniffer 走后台嗅探路径
 * - 用 0 size ViewGroup layoutParams + visibility=GONE 让 WebView 占用空间但
 *   实际不渲染（也不会收到 onDraw）
 *
 * **线程安全**：
 * - WebView 创建 / loadUrl / WebViewClient callback 都必须在 Main 线程
 * - `webView` lazy 初始化避免冷启动阻塞（Application.onCreate 不调 loadUrl，
 *   WebView 不会真启动 Chromium 进程——只是 inflate 资源）
 * - **多个 sniff 并发**用 [Mutex] 串行化（WebView 是单线程组件）。
 *   v0.5.0 简化用 `Mutex.withLock { ... }`——v0.5.1+ 优化时可改 actor 模式
 *
 * **v0.5.0 局限**：
 * - 单例常驻内存（~30-50MB），v0.5.1+ 优化：idle 30s 后 release / re-create
 * - Mutex.withLock 在 sniff 期间阻塞其他 sniff——v0.5.0 单线程串行是简化方案
 */
@Singleton
class WebViewHolder @Inject constructor(
    @ApplicationContext private val context: Context,
) {
    private val mutex = Mutex()

    /**
     * 共享 WebView。lazy 初始化避免冷启动阻塞（Application.onCreate 不调 loadUrl，
     * WebView 不会真启动 Chromium 进程——只是 inflate 资源）。
     *
     * `@SuppressLint` 不能用在 lazy property delegate 上——所以用
     * `init { ... }` 块在构造器内 apply，WebView 创建后立刻设置。
     */
    val webView: WebView by lazy {
        @SuppressLint("SetJavaScriptEnabled")
        WebView(context).apply {
            // 0 size + GONE：attach 到 view hierarchy 但实际不显示
            layoutParams = ViewGroup.LayoutParams(0, 0)
            visibility = View.GONE

            // JS 必需（B 站 / 抖音主页靠 JS 加载 m3u8 URL）
            settings.javaScriptEnabled = true
            // DOM Storage（部分网站用 localStorage 存 token）
            settings.domStorageEnabled = true
            // 禁用 view port / overview mode（headless 嗅探不需要）
            settings.useWideViewPort = false
            settings.loadWithOverviewMode = false
            // 不缓存（嗅探是单向 read，不要污染磁盘缓存）
            settings.cacheMode = WebSettings.LOAD_NO_CACHE
            // UA 标识：默认即可，user 可在 AppConfig.sniffUserAgent 配置
            settings.userAgentString = settings.userAgentString
        }
    }

    /**
     * 串行化嗅探访问。WebView 是单线程组件，多个 sniff 并发时只能串行
     * 排队（等上一个 onPageFinished 完成才能 loadUrl 下一个）。
     *
     * 用 [Mutex]（不是 `@Synchronized`）——suspend lambda 允许 `delay` /
     * `withTimeout` 等协程操作。
     */
    suspend fun <T> withLock(block: suspend (WebView) -> T): T = mutex.withLock {
        block(webView)
    }
}
