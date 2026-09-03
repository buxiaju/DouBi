package com.doubi.android.core.sniffer

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import timber.log.Timber
import javax.inject.Inject
import javax.inject.Singleton

/**
 * HTTP Content-Type 嗅探器。1:1 对拍桌面版
 * `src/doubi/core/sniffer.py:HttpContentTypeSniffer`（v0.4.0 简版）。
 *
 * **不做 headless browser**（v0.4.0 范围）—— 只发 HEAD 请求看 Content-Type。
 * 识别为 m3u8 / mp4 / webm / octet-stream → 算 Media，其他 → NotMedia。
 *
 * **302 重定向** 跟到底（OkHttp 默认 followRedirects=true），拿 finalUrl 喂
 * Engine 下载——避免 URL 短链 / 鉴权 redirect 链断在中间。
 *
 * **超时 / 重定向 / SSL 重定向** 全部由 [com.doubi.android.core.sniffer.di.SnifferModule]
 * 提供的 [OkHttpClient] 配置（10s connect / 10s read / followRedirects=true）——本类
 * 不再 `.newBuilder()` 改写，避免测试环境 mock 注入时 `newBuilder()` 需额外 stub 的坑。
 */
@Singleton
class HttpContentTypeSniffer @Inject constructor(
    private val client: OkHttpClient,
) : Sniffer {

    override suspend fun sniff(url: String): SniffResult = withContext(Dispatchers.IO) {
        try {
            // 优先 HEAD：省流量 / 不下载 body
            val headReq = Request.Builder().head().url(url).build()
            val headResp = client.newCall(headReq).execute()
            try {
                val ct = headResp.header("Content-Type")?.lowercase()
                val len = headResp.header("Content-Length")?.toLongOrNull()

                if (headResp.isSuccessful && ct != null && isMediaContentType(ct)) {
                    return@withContext SniffResult.Media(
                        contentType = ct,
                        finalUrl = headResp.request.url.toString(),
                        contentLength = len,
                    )
                }
                if (headResp.isSuccessful) {
                    return@withContext SniffResult.NotMedia(
                        statusCode = headResp.code,
                        contentType = ct,
                        reason = "HEAD Content-Type is not media: $ct",
                    )
                }
                return@withContext SniffResult.NotMedia(
                    statusCode = headResp.code,
                    contentType = ct,
                    reason = "HTTP ${headResp.code}",
                )
            } finally {
                // null-safe close：HEAD 响应没 body，OkHttp `body?.close()` 静默 no-op；
                // 但 `Response.close()` 自身在 body == null 跟某些 protocol 组合下会抛
                // "response is not eligible for a body and must not be closed"——我们
                // 用 ?.close() 绕过这个 invariant 错误。
                headResp.body?.close()
            }
        } catch (e: java.net.SocketTimeoutException) {
            Timber.w(e, "sniff timeout: %s", url)
            SniffResult.Error("嗅探超时：${e.message ?: "10s connect / 10s read"}", e)
        } catch (e: java.net.UnknownHostException) {
            Timber.w(e, "sniff DNS fail: %s", url)
            SniffResult.Error("DNS 解析失败：${e.message ?: ""}", e)
        } catch (e: java.io.IOException) {
            Timber.w(e, "sniff IO error: %s", url)
            SniffResult.Error("网络错误：${e.message ?: ""}", e)
        } catch (e: Throwable) {
            Timber.w(e, "sniff unknown error: %s", url)
            SniffResult.Error("嗅探失败：${e.message ?: e.javaClass.simpleName}", e)
        }
    }

    /**
     * 判断 Content-Type 是不是 media。
     *
     * 桌面版 `is_video_content_type` 1:1 对拍——主 mime type 是 video_(any) / audio_(any) /
     * application/vnd.apple.mpegurl / application/octet-stream + size 阈值（≥ 1MB）。
     * 简化：v0.4.0 不做 size 阈值（HEAD 拿到的 Content-Length 经常是 chunked 流的 -1），
     * 任何 video_(any) / audio_(any) / m3u8 / octet-stream 都算 media。
     */
    private fun isMediaContentType(contentType: String): Boolean {
        val ct = contentType.substringBefore(';').trim().lowercase()
        return when {
            ct.startsWith("video/") -> true
            ct.startsWith("audio/") -> true
            ct == "application/vnd.apple.mpegurl" -> true      // m3u8
            ct == "application/x-mpegurl" -> true             // m3u8 (variant)
            ct == "application/octet-stream" -> true          // 直链文件
            ct == "binary/octet-stream" -> true               // alias
            else -> false
        }
    }
}
