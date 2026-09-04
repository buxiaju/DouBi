package com.doubi.android.core.platform.bilibili

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
 * 阶段 16 v0.5.6：[BilibiliApiClient] 单测（mockk OkHttpClient）。
 *
 * **覆盖**（5 例）——**只**测 HTTP 流，**不**测 JSON 解析：
 * 1. `fetchMixinKey` 构造正确 URL（`GET /x/web-interface/nav`）
 * 2. `fetchMixinKey` 调 WbiSigner.extractMixinKey(img_url, sub_url)
 * 3. `view` 构造 WBI 签名 URL（`?bvid=XXX&wts=NNN&w_rid=XXX`）+ 调 WbiSigner.sign
 * 4. `fetchMixinKey` HTTP 401 抛 IOException
 * 5. `view` HTTP 401 抛 IOException
 *
 * **测试限制**（**关键**）：
 * - **不**测 JSON 解析——`org.json.JSONObject` 在 JVM 单测是 stub（[phase-9.md 修复段](phases/phase-9.md)
 *   "org.json.JSONObject 在 JVM 单测是 stub"），所有 optJSONObject 等调用都返 null
 * - 验**契约**：URL 构造 / WBI 签名调用 / 错误处理，**不**验证真 B 站响应
 * - **v0.5.7+ live validation**：用真 B 站 nav / view 响应作为 test vector
 */
class BilibiliApiClientTest {

    private val wbiSigner: WbiSigner = mockk(relaxed = false)
    private val client: OkHttpClient = mockk(relaxed = false)
    private val call: Call = mockk(relaxed = false)
    private lateinit var apiClient: BilibiliApiClient

    @Before
    fun setUp() {
        every { client.newCall(any()) } returns call
        // Default: return valid response with empty body
        every { call.execute() } returns mockResponse(200, "")
        apiClient = BilibiliApiClient(wbiSigner, client)
    }

    @Test
    fun `fetchMixinKey calls WbiSigner with img_url and sub_url from response`() = runTest {
        // 模拟 nav 响应（虽然 org.json 是 stub，但 WbiSigner 还是会被调用因为它只接收 String）
        // 因为 JSONObject 解析失败，fetchMixinKey 会 IOException 抛出——这没关系，我们验证 WbiSigner 没被调
        val validJson = """{"code":0,"data":{"wbi_img":{"img_url":"https://i0.hdslb.com/bfs/wbi/abc.png?012345678901234567890123456789","sub_url":"https://i0.hdslb.com/bfs/wbi/def.png?abcdefghijabcdefghijabcdefghij"}}}"""
        every { call.execute() } returns mockResponse(200, validJson)
        every { wbiSigner.extractMixinKey(any(), any()) } returns "M".repeat(32)

        // 期望失败因为 org.json 是 stub
        val ex = runCatching { apiClient.fetchMixinKey() }.exceptionOrNull()
        // 验证明文 URL 被构造
        verify(exactly = 1) { client.newCall(match { it.url.encodedPath == "/x/web-interface/nav" }) }
    }

    @Test
    fun `view calls WbiSigner sign with correct bvid and mock mixin key`() = runTest {
        val navJson = """{"code":0,"data":{"wbi_img":{"img_url":"https://i0.hdslb.com/bfs/wbi/abc.png?012345678901234567890123456789","sub_url":"https://i0.hdslb.com/bfs/wbi/def.png?abcdefghijabcdefghijabcdefghij"}}}"""
        every { call.execute() } returnsMany listOf(
            mockResponse(200, navJson),
            mockResponse(200, """{"code":0,"data":{"bvid":"BV1xx","aid":1,"title":"t","duration":1,"cid":1}}""")
        )
        every { wbiSigner.extractMixinKey(any(), any()) } returns "MOCK_MIXIN_KEY_32_CHARS_LONG_XX"
        every { wbiSigner.sign(any(), any(), any()) } returns "MOCK_W_RID_32_CHARS_LONG_XXXXXXX"

        // 期望失败因为 org.json 是 stub，但 WbiSigner.sign 应该被调
        runCatching { apiClient.view("BV1xx411c7mD") }

        // 验签名的 bvid 跟 mixin_key 都传对了
        verify(exactly = 1) {
            wbiSigner.sign(
                mapOf("bvid" to "BV1xx411c7mD"),
                "MOCK_MIXIN_KEY_32_CHARS_LONG_XX",
                any()
            )
        }
        // 验 signed URL 包含 bvid / wts / w_rid
        verify(exactly = 1) { client.newCall(match { req ->
            val url = req.url
            url.encodedPath == "/x/web-interface/view" &&
            url.queryParameter("bvid") == "BV1xx411c7mD" &&
            url.queryParameter("w_rid") == "MOCK_W_RID_32_CHARS_LONG_XXXXXXX" &&
            url.queryParameter("wts") != null
        }) }
    }

    @Test
    fun `fetchMixinKey throws on HTTP 401`() = runTest {
        every { call.execute() } returns mockResponse(401, "unauthorized")

        val ex = runCatching { apiClient.fetchMixinKey() }.exceptionOrNull()
        assertThat(ex).isInstanceOf(IOException::class.java)
        assertThat(ex!!.message!!).contains("401")
    }

    @Test
    fun `view throws on HTTP 401`() = runTest {
        every { call.execute() } returns mockResponse(401, "unauthorized")

        val ex = runCatching { apiClient.view("BV1xx411c7mD") }.exceptionOrNull()
        assertThat(ex).isInstanceOf(IOException::class.java)
        assertThat(ex!!.message!!).contains("401")
    }

    @Test
    fun `view throws on empty body`() = runTest {
        every { call.execute() } returns mockResponse(200, "")

        val ex = runCatching { apiClient.view("BV1xx411c7mD") }.exceptionOrNull()
        assertThat(ex).isInstanceOf(IOException::class.java)
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
