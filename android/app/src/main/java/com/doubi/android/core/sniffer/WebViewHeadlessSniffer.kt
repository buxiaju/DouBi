package com.doubi.android.core.sniffer

import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import timber.log.Timber
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 阶段 10 v0.5.0 headless browser 嗅探（WebView 集成）。
 *
 * **思路**：WebView loadUrl → JS 异步加载 → `shouldInterceptRequest` 拦截
 * 所有 .m3u8 / .mp4 / .webm 请求 → 第一个命中即返回 `SniffResult.Media(finalUrl, ...)`。
 * v0.4.0 阶段 8 阶段 [HttpContentTypeSniffer] 只能嗅探"直链"
 * （m3u8/mp4 在 HTTP response 头部直接暴露），v0.5.0 WebViewHeadlessSniffer
 * 覆盖"B 站 / 抖音 / Twitter 主页 / Vue SPA"等"JS 异步加载"网站。
 *
 * **不是真正 headless**（Android 端 WebView 必须在 Main 线程 + attach 到
 * view hierarchy）—— 实际是"invisible WebView"。桌面版
 * `src/doubi/core/sniffer.py:WebViewHeadlessSniffer` 用 Playwright 真
 * headless（Python），Android 端 v0.5.0 走 WebView 简化方案。
 *
 * **超时**：5s 默认（`AppConfig.sniffDurationSec` 5-60s）。5s 内任意
 * m3u8/mp4 命中 → Media；5s 啥都没拦截到 → NotMedia；异常 → Error。
 *
 * **v0.5.0 简化**：
 * - 单例共享 WebView（[WebViewHolder]）—— 多个 sniff 任务串行排队
 * - 拦截策略：URL 路径含 `.m3u8` / `.mp4` / `.webm` / `.mpd` / `.m4s` / 任意 query 形如 `type=mp4` 命中
 * - **不解析 m3u8 内容**（v0.5.0 只返回第一个 m3u8 URL；m3u8 → mp4 解析留 v0.5.1+）
 * - **不拿 title**（WebView 拿到 title 后再调 yt-dlp 拿 title，v0.5.0 简化直接用 URL 当 title）
 *
 * **风险**：
 * - WebView 第一次创建加载 Chromium native lib 慢（~30MB APK 增量）——
 *   v0.5.0 范围接受，v0.5.1+ 测冷启动影响
 * - 单例常驻 ~30-50MB 内存——v0.5.0 简化方案，v0.5.1+ idle release
 * - shouldInterceptRequest 是同步阻塞回调——复杂页面可能 1-3s 阻塞 Main 线程，
 *   v0.5.0 接受，v0.5.1+ 测 ANR 风险
 */
@Singleton
class WebViewHeadlessSniffer @Inject constructor(
    private val holder: WebViewHolder,
) : Sniffer {

    override suspend fun sniff(url: String): SniffResult = withContext(Dispatchers.Main) {
        try {
            holder.withLock { webView ->
                sniffOnMainThread(webView, url)
            }
        } catch (e: Throwable) {
            Timber.w(e, "WebViewHeadlessSniffer failed: %s", url)
            SniffResult.Error("WebView 嗅探失败：${e.message ?: e.javaClass.simpleName}", e)
        }
    }

    /**
     * 在 Main 线程执行。WebView 必须 Main 线程。
     *
     * 流程：
     * 1. 临时 WebViewClient 拦截 shouldInterceptRequest 收集 m3u8/mp4 URL
     * 2. loadUrl(url) 触发
     * 3. 等 5s（或 onPageFinished + 1s 缓冲）
     * 4. 取 captured 第一个 → Media；空 → NotMedia
     */
    private suspend fun sniffOnMainThread(webView: WebView, url: String): SniffResult {
        val captured = mutableListOf<String>()
        var pageFinished = false

        // 临时 WebViewClient 拦截
        webView.webViewClient = object : WebViewClient() {
            override fun shouldInterceptRequest(
                view: WebView?,
                request: WebResourceRequest?,
            ): WebResourceResponse? {
                val u = request?.url?.toString() ?: return super.shouldInterceptRequest(view, request)
                if (isMediaUrl(u) && u !in captured) {
                    Timber.d("WebViewHeadlessSniffer intercepted media: %s", u)
                    captured.add(u)
                }
                return super.shouldInterceptRequest(view, request)
            }

            override fun onPageFinished(view: WebView?, finishedUrl: String?) {
                pageFinished = true
            }
        }

        // 启动 loadUrl
        webView.loadUrl(url)

        // 轮询等 5s（或 pageFinished + 1s 缓冲）
        val timeoutMs = 5_000L
        val elapsed = 0L
        val startTime = System.currentTimeMillis()
        while (System.currentTimeMillis() - startTime < timeoutMs) {
            kotlinx.coroutines.delay(100L)
            if (captured.isNotEmpty()) {
                // 第一个 media 立即返回
                break
            }
            if (pageFinished) {
                // 页面加载完 + 1s 缓冲（JS 异步拦截）
                kotlinx.coroutines.delay(1_000L)
                break
            }
        }

        return if (captured.isNotEmpty()) {
            val finalUrl = captured.first()
            // 简化：contentType 跟 .ext 推
            val contentType = when {
                finalUrl.contains(".m3u8", ignoreCase = true) -> "application/vnd.apple.mpegurl"
                finalUrl.contains(".webm", ignoreCase = true) -> "video/webm"
                else -> "video/mp4"
            }
            SniffResult.Media(
                contentType = contentType,
                finalUrl = finalUrl,
                contentLength = null,  // WebView 拦截拿不到 Content-Length
                isHls = contentType.contains("mpegurl"),
            )
        } else {
            SniffResult.NotMedia(
                statusCode = 200,
                contentType = "text/html",
                reason = "WebView 5s 内未拦截到 m3u8/mp4/webm（页面 JS 加载或非 media）",
            )
        }
    }

    /**
     * 判断 URL 是不是 media。**v0.5.0 简化**：用 URL 后缀 + query 参数。
     * 桌面版 Python 走 mimetypes.guess_type + 完整 Content-Type header（更准）。
     *
     * 命中规则（任一即可）：
     * - 路径含 `.m3u8` / `.mp4` / `.webm` / `.mpd` / `.m4s`
     * - query 含 `type=mp4` / `mime=video` / `contenttype=video`
     *
     * 不命中：m3u8 里的 .ts 分片（v0.5.0 不解析 m3u8 内容；v0.5.1+ 解析）
     */
    private fun isMediaUrl(url: String): Boolean {
        val path = url.substringBefore('?').lowercase()
        if (path.endsWith(".m3u8") || path.endsWith(".mp4") ||
            path.endsWith(".webm") || path.endsWith(".mpd") || path.endsWith(".m4s")
        ) {
            return true
        }
        val query = url.substringAfter('?', missingDelimiterValue = "").lowercase()
        return query.contains("type=mp4") || query.contains("mime=video") ||
            query.contains("contenttype=video")
    }
}
