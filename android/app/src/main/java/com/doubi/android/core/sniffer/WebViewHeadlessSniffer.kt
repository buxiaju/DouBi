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
 * 阶段 10 v0.5.0 / 阶段 12 v0.5.2 / 阶段 13 v0.5.3：headless browser 嗅探（WebView 集成）。
 *
 * **v0.5.0 阶段 10 baseline**：
 * - `WebView.loadUrl(url)` + 临时 `WebViewClient.shouldInterceptRequest` 拦截
 *   m3u8/mp4/webm/mpd/m4s URL
 * - 5s 超时（写死，v0.4.0 阶段 8 加的 `sniffDurationSec` 配置 v0.5.0 没用上）
 * - 命中 → `SniffResult.Media(finalUrl=interceptedUrl, contentType=推 .ext)`
 * - 5s 内未命中 → `NotMedia(reason="WebView 5s 内未拦截到 m3u8/mp4/webm")`
 * - 异常 → `Error(message, cause)`
 *
 * **v0.5.2 阶段 12 增强**（m3u8 内容解析，单层）：
 * - 拦截到 m3u8 URL 后，**额外**调 [M3u8Parser.parse] 解析：master playlist 拿第一个
 *   variant 子 m3u8 URL，media playlist 拿第一个 .ts/.m4s segment URL
 * - 把 finalUrl 替换成解析后的 URL —— Engine (yt-dlp) 直接下 .ts，**省一次 m3u8 body
 *   HTTP round-trip**
 * - m3u8 解析失败 / 非 m3u8 媒体（mp4 / webm）→ 保留原 URL
 * - 解析流程是 `withContext(Dispatchers.IO)` 跑 OkHttp GET，避免阻塞 Main 线程
 *
 * **v0.5.3 阶段 13 增强**（递归 master → media）：
 * - v0.5.2 只解析一层：master → 第一个 variant m3u8 URL（仍要 Engine 再下 body 解析）
 * - v0.5.3 改用 [M3u8Parser.parseRecursive]：master → variant m3u8 → media playlist
 *   → .ts 一路递归下来，把 finalUrl 替换成 .ts segment URL
 * - 递归上限 [M3u8Parser.MAX_RECURSION_DEPTH]=5，循环引用（master1 → master2 → master1）
 *   自然终止
 * - 跟 v0.5.2 一样 fail-safe：任何环节失败保留当前 URL
 *
 * **v0.5.0 简化保留**（v0.5.3 不做）：
 * - 单例共享 WebView（v0.5.1 阶段 11 做的 idle 30s release）
 * - 拦截策略：URL 路径含 `.m3u8` / `.mp4` / `.webm` / `.mpd` / `.m4s` + query 形如
 *   `type=mp4` / `mime=video`
 * - 不解析 m3u8 v7+ HLS encryption（`#EXT-X-KEY`）—— 保留原 m3u8 URL 让 Engine 解析
 * - 不实现多 variant 选择 UI（带宽/分辨率）—— v0.5.3 仍默认拿第一个 variant
 *
 * **风险**：
 * - 10s OkHttp timeout（[SnifferModule] 共享 client）+ 5s WebView sniff 窗口 = 15s 最坏
 *   单层；递归场景 master + variant + media 三层，**最坏 30s+**——实测 HLS 通常 < 5s，
 *   但极端情况需要兜底
 * - fail-safe 完备：fetch 失败 / 解析失败 / 循环引用 → 全部保留当前 finalUrl
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
     * v0.5.2 阶段 12 m3u8 内容解析增强（v0.5.3 阶段 13 升级为递归）。
     *
     * 仅对 [SniffResult.Media] 且 `isHls = true` 的结果生效——其它类型原样返回。
     *
     * **v0.5.3 升级**：从 v0.5.2 的 `m3u8Parser.parse`（单层）改为
     * `m3u8Parser.parseRecursive`（递归 master → variant → media → segment）。
     *
     * 流程：
     * 1. 拿原始 finalUrl（m3u8 URL）
     * 2. [M3u8Parser.parseRecursive] 传入 lambda 作为 `fetchBody`——
     *    lambda 用 `withContext(Dispatchers.IO)` 跑 OkHttp GET 拉 m3u8 body
     * 3. parseRecursive 递归：master → variant → media → segment
     * 4. Segment / Variant → 替换 finalUrl；Passthrough / 异常 → 保留原 finalUrl
     *
     * **降级**（fail-safe，跟 v0.5.2 一致）：
     * - 任何层级 fetch 失败 → 保留当前层 URL（**不**抛异常）
     * - 达到 [M3u8Parser.MAX_RECURSION_DEPTH]（5 层）→ 返 Passthrough 保留当前 URL
     * - 整个 enhance 抛异常 → 保留原 finalUrl
     */
    private suspend fun enhanceM3u8IfNeeded(result: SniffResult): SniffResult {
        if (result !is SniffResult.Media || !result.isHls) return result

        return try {
            // 第一次 fetch 原始 m3u8 body；fetchBody 失败 → 降级保留原 finalUrl
            val initialBody = fetchM3u8Body(result.finalUrl) ?: return result
            // fetchBody lambda：M3u8Parser.parseRecursive 在 Variant 时回调拉子 m3u8 body
            // （suspend lambda —— parseRecursive 签名是 suspend (String) -> String?）
            val fetchBody: suspend (String) -> String? = { url -> fetchM3u8Body(url) }
            when (val parsed = m3u8Parser.parseRecursive(initialBody, result.finalUrl, fetchBody)) {
                is M3u8Result.Segment -> {
                    Timber.d("m3u8 recursive → segment: %s", parsed.url)
                    result.copy(finalUrl = parsed.url)
                }
                is M3u8Result.Variant -> {
                    // fetchBody 返 null（网络失败）→ 保留当前 variant URL 作为 finalUrl
                    // Engine (yt-dlp) 拿到这个 .m3u8 URL 后自己再下 body 解析
                    Timber.d("m3u8 recursive fetchBody null → variant: %s", parsed.url)
                    result.copy(finalUrl = parsed.url)
                }
                is M3u8Result.Passthrough -> {
                    Timber.d("m3u8 recursive → passthrough: keep original %s", result.finalUrl)
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
