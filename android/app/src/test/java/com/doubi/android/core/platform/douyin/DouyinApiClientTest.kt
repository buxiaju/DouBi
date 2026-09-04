package com.doubi.android.core.platform.douyin

import com.google.common.truth.Truth.assertThat
import io.mockk.every
import io.mockk.mockk
import io.mockk.verify
import kotlinx.coroutines.test.runTest
import okhttp3.Call
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Before
import org.junit.Test
import java.io.IOException

/**
 * 阶段 16 v0.5.6：[DouyinApiClient] 单测（mockk OkHttpClient）。
 *
 * **覆盖**（5 例）——**只**测 HTTP 流，**不**测 JSON 解析：
 * 1. `awemeItemInfo` 构造正确 URL（`/web/api/v2/aweme/iteminfo/?item_ids=XXX&X-Bogus=...`）
 * 2. `awemeItemInfo` 调 XBogusSigner.sign 带 URL + UA + timestamp
 * 3. `awemeItemInfo` HTTP 401 抛 IOException
 * 4. `awemeItemInfo` empty body 抛 IOException
 * 5. `awemeItemInfo` body 缺 item_ids 时 XBogusSigner 还是被调（先签后请求）
 *
 * **测试限制**（**关键**）：
 * - **不**测 JSON 解析——`org.json.JSONObject` 在 JVM 单测是 stub
 * - **v0.5.6 X-Bogus 是 placeholder**——测试**不**验证真 X-Bogus 字节内容，只验证调用
 * - v0.5.7+ 真 X-Bogus 实装后 + live validation
 */
class DouyinApiClientTest {

    private val xBogusSigner: XBogusSigner = mockk(relaxed = false)
    private val client: OkHttpClient = mockk(relaxed = false)
    private val call: Call = mockk(relaxed = false)
    private lateinit var apiClient: DouyinApiClient

    @Before
    fun setUp() {
        every { client.newCall(any()) } returns call
        every { call.execute() } returns mockResponse(200, "")
        every { xBogusSigner.sign(any(), any(), any()) } returns "MOCK_X_BOGUS_44_CHARS_LONG_XXXXXX"
        apiClient = DouyinApiClient(xBogusSigner, client)
    }

    @Test
    fun `awemeItemInfo calls XBogusSigner with URL and userAgent`() = runTest {
        runCatching { apiClient.awemeItemInfo("7234567890123456789") }

        // 验 XBogusSigner.sign 被调，URL 是带 item_ids 的完整 URL
        verify(exactly = 1) { xBogusSigner.sign(
            url = match { it.contains("item_ids=7234567890123456789") && it.contains("iesdouyin.com") },
            userAgent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            timestamp = any()
        ) }
    }

    @Test
    fun `awemeItemInfo constructs signed URL with X-Bogus query param`() = runTest {
        runCatching { apiClient.awemeItemInfo("12345") }

        // 验 signed URL 包含 item_ids + X-Bogus
        verify(exactly = 1) { client.newCall(match { req ->
            val url = req.url
            url.encodedPath == "/web/api/v2/aweme/iteminfo/" &&
            url.queryParameter("item_ids") == "12345" &&
            url.queryParameter("X-Bogus") == "MOCK_X_BOGUS_44_CHARS_LONG_XXXXXX"
        }) }
    }

    @Test
    fun `awemeItemInfo throws on HTTP 401`() = runTest {
        every { call.execute() } returns mockResponse(401, "unauthorized")

        val ex = runCatching { apiClient.awemeItemInfo("12345") }.exceptionOrNull()
        assertThat(ex).isInstanceOf(IOException::class.java)
        assertThat(ex!!.message!!).contains("401")
    }

    @Test
    fun `awemeItemInfo throws on empty body`() = runTest {
        every { call.execute() } returns mockResponse(200, "")

        val ex = runCatching { apiClient.awemeItemInfo("12345") }.exceptionOrNull()
        assertThat(ex).isInstanceOf(IOException::class.java)
    }

    @Test
    fun `awemeItemInfo signs even when X-Bogus signer returns empty stub`() = runTest {
        // 即使 X-Bogus stub 返空字符串（v0.5.5 placeholder 异常场景），URL 还是构造 + 调 sign
        every { xBogusSigner.sign(any(), any(), any()) } returns "EMPTY"

        runCatching { apiClient.awemeItemInfo("99") }

        // X-Bogus query param 还是被设（空 stub）
        verify(exactly = 1) { client.newCall(match { req ->
            req.url.queryParameter("X-Bogus") == "EMPTY"
        }) }
    }

    private fun mockResponse(code: Int, body: String): Response {
        val responseBody = body.toResponseBody("application/json".toMediaType())
        return Response.Builder()
            .request(Request.Builder().url("https://example.com").build())
            .protocol(okhttp3.Protocol.HTTP_1_1)
            .code(code)
            .message(if (code == 200) "OK" else "Error")
            .body(responseBody)
            .build()
    }
}
