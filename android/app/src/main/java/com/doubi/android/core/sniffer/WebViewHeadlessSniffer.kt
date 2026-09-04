package com.doubi.android.core.sniffer

import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import timber.log.Timber
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 阶段 10 v0.5.0 / 阶段 12 v0.5.2：headless browser 嗅探（WebView 集成）。
 *
 * **v0.5.0 阶段 10 baseline**：
 * - `WebView.loadUrl(url)` + 临时 `WebViewClient.shouldInterceptRequest` 拦截
 *   m3u8/mp4/webm/mpd/m4s URL
 * - 5s 超时（写死，v0.4.0 阶段 8 加的 `sniffDurationSec` 配置 v0.5.0 没用上）
 * - 命中 → `SniffResult.Media(finalUrl=interceptedUrl, contentType=推 .ext)`
 * - 5s 内未命中 → `NotMedia(reason="WebView 5s 内未拦截到 m3u8/mp4/webm")`
 * - 异常 → `Error(message, cause)`
 *
 * **v0.5.2 阶段 12 增强**（m3u8 内容解析）：
 * - 拦截到 m3u8 URL 后，**额外**调 [M3u8Parser] 解析：master playlist 拿第一个
 *   variant 子 m3u8 URL，media playlist 拿第一个 .ts/.m4s segment URL
 * - 把 finalUrl 替换成解析后的 URL —— Engine (yt-dlp) 直接下 .ts，**省一次 m3u8 body
 *   HTTP round-trip**
 * - m3u8 解析失败 / 非 m3u8 媒体（mp4 / webm）→ 保留原 URL
 * - 解析流程是 `withContext(Dispatchers.IO)` 跑 OkHttp GET，避免阻塞 Main 线程
 *
 * **v0.5.0 简化保留**（v0.5.2 不做）：
 * - 单例共享 WebView（v0.5.1 阶段 11 做的 idle 30s release）
 * - 拦截策略：URL 路径含 `.m3u8` / `.mp4` / `.webm` / `.mpd` / `.m4s` + query 形如
 *   `type=mp4` / `mime=video`
 * - 不递归解析 m3u8（master → 第一个 variant .m3u8 URL，不下 body 解析子 m3u8；
 *   递归留 v0.5.3+）
 * - 不解析 m3u8 v7+ HLS encryption（`#EXT-X-KEY`）—— 保留原 m3u8 URL 让 Engine 解析
 *
 * **风险**：
 * - 解析后的 URL 可能是子 m3u8（master playlist 的 variant）—— 仍要 Engine 再下 body
 *   解析。省的不是 m3u8 HTTP round-trip，是把"先下 m3u8 body 决定下啥"提前到 sniffer 阶段
 * - 10s OkHttp timeout（[SnifferModule] 共享 client）+ 5s WebView sniff 窗口 = 15s 最坏。
 *   m3u8 body 一般几 KB，10s timeout 远超实际需要
 */
@Singleton
class WebViewHeadlessSniffer @Inject constructor(
    private val holder: WebViewHolder,
    private val okHttpClient: OkHttpClient,
    private val m3u8Parser: M3u8Parser,
) : Sniffer {

    override suspend fun sniff(url: String): SniffResult = withContext(Dispatchers.Main) {
        val rawResult = try {
            holder.withLock { webView ->
                sniffOnMainThread(webView, url)
            }
        } catch (e: Throwable) {
            Timber.w(e, "WebViewHeadlessSniffer failed: %s", url)
            SniffResult.Error("WebView 嗅探失败：${e.message ?: e.javaClass.simpleName}", e)
        }

        // v0.5.2 阶段 12：m3u8 内容解析增强（只对 isHls 的 Media 走）
        enhanceM3u8IfNeeded(rawResult)
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
     * v0.5.2 阶段 12 m3u8 内容解析增强。
     *
     * 仅对 [SniffResult.Media] 且 `isHls = true` 的结果生效——其它类型原样返回。
     *
     * 流程：
     * 1. 拿原始 finalUrl（m3u8 URL）
     * 2. `Dispatchers.IO` 跑 OkHttp GET 拿 m3u8 body
     * 3. [M3u8Parser] 解析 → Variant / Segment / Passthrough
     * 4. Variant / Segment → 替换 finalUrl；Passthrough → 保留原 finalUrl
     *
     * **降级**：fetch 失败 / parse 抛异常 → 保留原 finalUrl，不影响 Media 返回。
     */
    private suspend fun enhanceM3u8IfNeeded(result: SniffResult): SniffResult {
        if (result !is SniffResult.Media || !result.isHls) return result

        return try {
            val body = fetchM3u8Body(result.finalUrl) ?: return result
            when (val parsed = m3u8Parser.parse(body, result.finalUrl)) {
                is M3u8Result.Variant -> {
                    Timber.d("m3u8 master → variant: %s", parsed.url)
                    result.copy(finalUrl = parsed.url)
                }
                is M3u8Result.Segment -> {
                    Timber.d("m3u8 media → segment: %s", parsed.url)
                    result.copy(finalUrl = parsed.url)
                }
                is M3u8Result.Passthrough -> {
                    Timber.d("m3u8 passthrough: keep original %s", result.finalUrl)
                    result
                }
            }
        } catch (e: Throwable) {
            Timber.w(e, "m3u8 enhance failed for %s, keep original", result.finalUrl)
            result  // 降级：保留原 finalUrl
        }
    }

    /**
     * 拉 m3u8 body。失败返 null。
     *
     * `withContext(Dispatchers.IO)` 切到 IO 线程——OkHttp `execute()` 是 blocking call，
     * 不能在 Main 线程跑。
     */
    private suspend fun fetchM3u8Body(url: String): String? = withContext(Dispatchers.IO) {
        try {
            val request = Request.Builder().url(url).build()
            okHttpClient.newCall(request).execute().use { resp ->
                if (!resp.isSuccessful) {
                    Timber.w("m3u8 body fetch not 2xx: %s %s", resp.code, url)
                    return@use null
                }
                resp.body?.string()
            }
        } catch (e: Throwable) {
            Timber.w(e, "m3u8 body fetch failed for %s", url)
            null
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
     * 不命中：m3u8 里的 .ts 分片（v0.5.0 不解析 m3u8 内容；v0.5.2 改为调 [M3u8Parser] 解析
     * 而不是拦截 .ts URL——见 [enhanceM3u8IfNeeded]）
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
