package com.doubi.android.core.sniffer

import android.annotation.SuppressLint
import android.content.Context
import android.view.View
import android.view.ViewGroup
import android.webkit.WebSettings
import android.webkit.WebView
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 阶段 11 v0.5.1：[WebViewFactory] 的默认实现。
 *
 * **v0.5.0 阶段 10 写死的 WebView 配置**（从 `WebViewHolder` 的 `by lazy` 块里抽出来）：
 * - 0 size `ViewGroup.LayoutParams(0, 0)` + `visibility = View.GONE`——attach 到 view
 *   hierarchy 但不渲染（WebView 必须 attach 才能 loadUrl）
 * - JS 必需——B 站 / 抖音主页靠 JS 加载 m3u8 URL
 * - DOM Storage 启用——部分网站用 localStorage 存 token
 * - 禁用 view port / overview mode——headless 嗅探不需要
 * - `cacheMode = LOAD_NO_CACHE`——嗅探是单向 read，不污染磁盘缓存
 * - UA 用默认（用户可在 `AppConfig.sniffUserAgent` 配置）
 *
 * **为什么独立成类**（而不是 [WebViewFactory] 的默认方法）：
 * - 单元测试可以 mockk [WebViewFactory] 验证 [WebViewHolder] 的创建/复用/release 契约
 * - 配置改动只影响这一个类，不影响 [WebViewHolder] 的并发原语（Mutex、idle 计时）
 */
@Singleton
class DefaultWebViewFactory @Inject constructor() : WebViewFactory {

    @SuppressLint("SetJavaScriptEnabled")
    override fun create(context: Context): WebView {
        return WebView(context).apply {
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
}
