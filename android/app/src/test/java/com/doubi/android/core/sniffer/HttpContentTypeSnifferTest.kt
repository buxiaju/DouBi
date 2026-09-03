package com.doubi.android.core.sniffer

import com.google.common.truth.Truth.assertThat
import io.mockk.every
import io.mockk.mockk
import kotlinx.coroutines.test.runTest
import okhttp3.Call
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Test
import java.net.SocketTimeoutException
import java.net.UnknownHostException

/**
 * HttpContentTypeSniffer 单测。OkHttpClient 用 mockk 隔离（不真发 HTTP 请求）。
 *
 * 覆盖：
 * - mp4 直链 → Media
 * - m3u8 → Media(isHls = true)
 * - webm → Media
 * - octet-stream → Media
 * - HTML 页面 → NotMedia (statusCode=200, contentType="text/html")
 * - 404 → NotMedia (statusCode=404)
 * - 网络超时 (SocketTimeoutException) → Error
 * - DNS 失败 (UnknownHostException) → Error
 * - URL 重定向链：OkHttp 默认 followRedirects=true，finalUrl 用 resp.request.url
 * - 混合大小写 Content-Type（"Video/MP4"）→ Media（lowercase 处理）
 * - Content-Type 带 charset（"application/vnd.apple.mpegurl; charset=utf-8"）→ Media
 */
class HttpContentTypeSnifferTest {

    private val client: OkHttpClient = mockk(relaxed = true)
    private val call: Call = mockk(relaxed = true)
    private val sniffer = HttpContentTypeSniffer(client)

    // ---- Media 分支 ----

    @Test
    fun `mp4 Content-Type returns Media with finalUrl`() = runTest {
        val resp = mockResponse(
            url = "https://example.com/video.mp4",
            code = 200,
            contentType = "video/mp4",
            contentLength = 12345678L,
        )
        stubClient(resp)

        val r = sniffer.sniff("https://example.com/video.mp4")
        assertThat(r).isInstanceOf(SniffResult.Media::class.java)
        val m = r as SniffResult.Media
        assertThat(m.contentType).isEqualTo("video/mp4")
        assertThat(m.finalUrl).isEqualTo("https://example.com/video.mp4")
        assertThat(m.contentLength).isEqualTo(12345678L)
        assertThat(m.isHls).isFalse()
    }

    @Test
    fun `m3u8 Content-Type returns Media with isHls true`() = runTest {
        val resp = mockResponse(
            url = "https://example.com/stream.m3u8",
            code = 200,
            contentType = "application/vnd.apple.mpegurl",
            contentLength = 1024L,
        )
        stubClient(resp)

        val r = sniffer.sniff("https://example.com/stream.m3u8")
        val m = r as SniffResult.Media
        assertThat(m.contentType).isEqualTo("application/vnd.apple.mpegurl")
        assertThat(m.isHls).isTrue()
    }

    @Test
    fun `x-mpegurl variant returns Media with isHls true`() = runTest {
        val resp = mockResponse(
            url = "https://example.com/stream.m3u8",
            code = 200,
            contentType = "application/x-mpegurl",
            contentLength = null,
        )
        stubClient(resp)

        val r = sniffer.sniff("https://example.com/stream.m3u8")
        val m = r as SniffResult.Media
        assertThat(m.isHls).isTrue()
    }

    @Test
    fun `webm Content-Type returns Media`() = runTest {
        val resp = mockResponse(
            url = "https://example.com/video.webm",
            code = 200,
            contentType = "video/webm",
            contentLength = null,
        )
        stubClient(resp)

        val r = sniffer.sniff("https://example.com/video.webm")
        val m = r as SniffResult.Media
        assertThat(m.contentType).isEqualTo("video/webm")
    }

    @Test
    fun `octet-stream Content-Type returns Media`() = runTest {
        val resp = mockResponse(
            url = "https://example.com/blob",
            code = 200,
            contentType = "application/octet-stream",
            contentLength = 999L,
        )
        stubClient(resp)

        val r = sniffer.sniff("https://example.com/blob")
        assertThat(r).isInstanceOf(SniffResult.Media::class.java)
    }

    @Test
    fun `audio Content-Type returns Media`() = runTest {
        val resp = mockResponse(
            url = "https://example.com/song.mp3",
            code = 200,
            contentType = "audio/mpeg",
            contentLength = 4096L,
        )
        stubClient(resp)

        val r = sniffer.sniff("https://example.com/song.mp3")
        assertThat(r).isInstanceOf(SniffResult.Media::class.java)
    }

    @Test
    fun `mixed case Content-Type is normalized to lowercase and matches`() = runTest {
        // 服务器偶尔返回 "Video/MP4;charset=utf-8"——lowercase + strip ; 后是 "video/mp4"
        val resp = mockResponse(
            url = "https://example.com/video.mp4",
            code = 200,
            contentType = "Video/MP4; charset=utf-8",
            contentLength = null,
        )
        stubClient(resp)

        val r = sniffer.sniff("https://example.com/video.mp4")
        // isMediaContentType 先 substringBefore(';') 再 lowercase ——"video/mp4" 命中
        val m = r as SniffResult.Media
        // contentType 字段保留 lowercase 后的原始字符串
        assertThat(m.contentType).isEqualTo("video/mp4; charset=utf-8")
    }

    // ---- NotMedia 分支 ----

    @Test
    fun `HTML page returns NotMedia with statusCode 200`() = runTest {
        val resp = mockResponse(
            url = "https://example.com/page.html",
            code = 200,
            contentType = "text/html; charset=utf-8",
            contentLength = 4096L,
        )
        stubClient(resp)

        val r = sniffer.sniff("https://example.com/page.html")
        assertThat(r).isInstanceOf(SniffResult.NotMedia::class.java)
        val n = r as SniffResult.NotMedia
        assertThat(n.statusCode).isEqualTo(200)
        assertThat(n.contentType).isEqualTo("text/html; charset=utf-8")
        assertThat(n.reason).contains("text/html")
    }

    @Test
    fun `404 NotFound returns NotMedia with statusCode 404`() = runTest {
        val resp = mockResponse(
            url = "https://example.com/missing.m3u8",
            code = 404,
            contentType = null,
            contentLength = null,
        )
        stubClient(resp)

        val r = sniffer.sniff("https://example.com/missing.m3u8")
        val n = r as SniffResult.NotMedia
        assertThat(n.statusCode).isEqualTo(404)
        assertThat(n.reason).contains("404")
    }

    @Test
    fun `500 Server Error returns NotMedia with statusCode 500`() = runTest {
        val resp = mockResponse(
            url = "https://example.com/error",
            code = 500,
            contentType = "text/html",
            contentLength = null,
        )
        stubClient(resp)

        val r = sniffer.sniff("https://example.com/error")
        val n = r as SniffResult.NotMedia
        assertThat(n.statusCode).isEqualTo(500)
    }

    // ---- Error 分支 ----

    @Test
    fun `SocketTimeoutException returns Error with timeout message`() = runTest {
        every { client.newCall(any()) } returns call
        every { call.execute() } throws SocketTimeoutException("connect timed out")

        val r = sniffer.sniff("https://example.com/slow.m3u8")
        assertThat(r).isInstanceOf(SniffResult.Error::class.java)
        val e = r as SniffResult.Error
        assertThat(e.message).contains("超时")
    }

    @Test
    fun `UnknownHostException returns Error with DNS message`() = runTest {
        every { client.newCall(any()) } returns call
        every { call.execute() } throws UnknownHostException("no such host")

        val r = sniffer.sniff("https://nonexistent.example.com/video.mp4")
        assertThat(r).isInstanceOf(SniffResult.Error::class.java)
        val e = r as SniffResult.Error
        assertThat(e.message).contains("DNS")
    }

    // ---- 重定向链（OkHttp 默认 followRedirects=true）----

    @Test
    fun `redirect chain finalUrl is resp request url after follow`() = runTest {
        // 模拟重定向后 finalUrl 变成 https://cdn.example.com/video.mp4
        val resp = mockResponse(
            url = "https://cdn.example.com/video.mp4",
            code = 200,
            contentType = "video/mp4",
            contentLength = 1234L,
        )
        stubClient(resp)

        val r = sniffer.sniff("https://example.com/redirect?to=video.mp4")
        val m = r as SniffResult.Media
        // resp.request.url 是 OkHttp followRedirects 后的最终 URL
        assertThat(m.finalUrl).isEqualTo("https://cdn.example.com/video.mp4")
    }

    // ---- helpers ----

    private fun stubResponse(resp: Response) {
        every { client.newCall(any()) } returns call
        every { call.execute() } returns resp
    }

    /**
     * 兼容新旧 API：sniffer 里用的是 `client.newCall(req).execute()`，需要 stub
     * 整个调用链。Sniffer 内部 finally 块调 `headResp.body?.close()`，body 是
     * Response 的 final field，OkHttp 4.x 不允许在 builder 阶段没设 body 时 close()——
     * 我们让 builder 不设 body，sniffer 的 `body?.close()` 走 null 分支 no-op 即可。
     *
     * 注意：不能写 `every { resp.close() } returns Unit`——mockk 的 every 会真执行一次
     * close() 测返回值，OkHttp Response.close() 在 body=null 时抛
     * "response is not eligible for a body and must not be closed"。
     */
    private fun stubClient(resp: Response) {
        stubResponse(resp)
    }

    private fun mockResponse(
        url: String,
        code: Int,
        contentType: String?,
        contentLength: Long?,
    ): Response {
        val req = Request.Builder().url(url).build()
        val builder = Response.Builder()
            .request(req)
            .protocol(Protocol.HTTP_1_1)
            .code(code)
            .message(if (code in 200..299) "OK" else "ERR")
        if (contentType != null) builder.header("Content-Type", contentType)
        if (contentLength != null) builder.header("Content-Length", contentLength.toString())
        return builder.build()
    }
}
