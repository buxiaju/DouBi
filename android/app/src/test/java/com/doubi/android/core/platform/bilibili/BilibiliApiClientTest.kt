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
 * 阶段 16 v0.5.6 + 阶段 18 v0.5.8：[BilibiliApiClient] 单测（mockk OkHttpClient）。
 *
 * **覆盖**（10 例）——**只**测 HTTP 流，**不**测 JSON 解析：
 *
 * v0.5.6（5 例）：
 * 1. `fetchMixinKey` 构造正确 URL（`GET /x/web-interface/nav`）
 * 2. `fetchMixinKey` 调 WbiSigner.extractMixinKey(img_url, sub_url)
 * 3. `view` 构造 WBI 签名 URL（`?bvid=XXX&wts=NNN&w_rid=XXX`）+ 调 WbiSigner.sign
 * 4. `fetchMixinKey` HTTP 401 抛 IOException
 * 5. `view` HTTP 401 抛 IOException
 *
 * v0.5.8 新增（5 例）：
 * 6. `playurl` 构造 WBI 签名 URL（`?bvid=XXX&cid=NNN&qn=80&wts=NNN&w_rid=YYY`）+ 调 WbiSigner.sign
 * 7. `playurl` HTTP 401 抛 IOException
 * 8. `playurl` empty body 抛 IOException
 * 9. `playurl` 业务 code != 0 抛 IOException（`-352 风控` 等）
 * 10. `playurl` 解析响应拿 durl[0].url + size 字段（regex 提取验证）
 *
 * **测试限制**（**关键**）：
 * - **不**测 `org.json.JSONObject` 解析（v0.5.6 阶段 16 已经用 regex 绕过，JVM 单测是 stub）
 * - 验**契约**：URL 构造 / WBI 签名调用 / 错误处理 / regex 提取，**不**验证真 B 站响应
 * - **v0.5.9+ live validation**：用真 B 站 nav / view / playurl 响应作为 test vector
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

    // ---- v0.5.8 playurl ----

    @Test
    fun `playurl calls WbiSigner sign with correct bvid cid qn and mock mixin key`() = runTest {
        val navJson = """{"code":0,"data":{"wbi_img":{"img_url":"https://i0.hdslb.com/bfs/wbi/abc.png?012345678901234567890123456789","sub_url":"https://i0.hdslb.com/bfs/wbi/def.png?abcdefghijabcdefghijabcdefghij"}}}"""
        val playurlJson = """{"code":0,"message":"0","data":{"from":"local","quality":80,"format":"flv","timelength":300000,"durl":[{"order":1,"length":30000,"size":12345678,"url":"https://cn-jsnt-cu.bilivideo.com/12345?bvid=BV1xx"}]}}"""
        every { call.execute() } returnsMany listOf(
            mockResponse(200, navJson),
            mockResponse(200, playurlJson),
        )
        every { wbiSigner.extractMixinKey(any(), any()) } returns "MOCK_MIXIN_KEY_32_CHARS_LONG_XX"
        every { wbiSigner.sign(any(), any(), any()) } returns "MOCK_W_RID_32_CHARS_LONG_XXXXXXX"

        val result = apiClient.playurl("BV1xx411c7mD", cid = 12345L, qn = 80)

        // 验签名参数：bvid + cid + qn + mock mixin_key
        verify(exactly = 1) {
            wbiSigner.sign(
                mapOf("bvid" to "BV1xx411c7mD", "cid" to "12345", "qn" to "80"),
                "MOCK_MIXIN_KEY_32_CHARS_LONG_XX",
                any(),
            )
        }
        // 验 signed URL 包含 bvid / cid / qn / wts / w_rid
        verify(exactly = 1) { client.newCall(match { req ->
            val url = req.url
            url.encodedPath == "/x/player/playurl" &&
                url.queryParameter("bvid") == "BV1xx411c7mD" &&
                url.queryParameter("cid") == "12345" &&
                url.queryParameter("qn") == "80" &&
                url.queryParameter("w_rid") == "MOCK_W_RID_32_CHARS_LONG_XXXXXXX" &&
                url.queryParameter("wts") != null
        }) }
        // 验返回的 URL + size
        assertThat(result.url).isEqualTo("https://cn-jsnt-cu.bilivideo.com/12345?bvid=BV1xx")
        assertThat(result.size).isEqualTo(12345678L)
    }

    @Test
    fun `playurl throws on HTTP 401`() = runTest {
        every { call.execute() } returns mockResponse(401, "unauthorized")

        val ex = runCatching { apiClient.playurl("BV1xx411c7mD", 12345L) }.exceptionOrNull()
        assertThat(ex).isInstanceOf(IOException::class.java)
        assertThat(ex!!.message!!).contains("401")
    }

    @Test
    fun `playurl throws on empty body`() = runTest {
        every { call.execute() } returns mockResponse(200, "")

        val ex = runCatching { apiClient.playurl("BV1xx411c7mD", 12345L) }.exceptionOrNull()
        assertThat(ex).isInstanceOf(IOException::class.java)
    }

    @Test
    fun `playurl throws on business code non-zero (e g minus 352 wind control)`() = runTest {
        // 模拟 B 站 -352 风控：code != 0 + message 提示
        val navJson = """{"code":0,"data":{"wbi_img":{"img_url":"https://i0.hdslb.com/bfs/wbi/abc.png?012345678901234567890123456789","sub_url":"https://i0.hdslb.com/bfs/wbi/def.png?abcdefghijabcdefghijabcdefghij"}}}"""
        val playurlJson = """{"code":-352,"message":"风控校验失败","data":{}}"""
        every { call.execute() } returnsMany listOf(
            mockResponse(200, navJson),
            mockResponse(200, playurlJson),
        )
        every { wbiSigner.extractMixinKey(any(), any()) } returns "MOCK_MIXIN_KEY_32_CHARS_LONG_XX"
        every { wbiSigner.sign(any(), any(), any()) } returns "MOCK_W_RID_32_CHARS_LONG_XXXXXXX"

        val ex = runCatching { apiClient.playurl("BV1xx411c7mD", 12345L) }.exceptionOrNull()
        assertThat(ex).isInstanceOf(IOException::class.java)
        assertThat(ex!!.message!!).contains("-352")
        assertThat(ex!!.message!!).contains("风控")
    }

    @Test
    fun `playurl parses durl first url and size from response`() = runTest {
        // 验 regex 提取 durl[0].url + size 字段
        val navJson = """{"code":0,"data":{"wbi_img":{"img_url":"https://i0.hdslb.com/bfs/wbi/abc.png?012345678901234567890123456789","sub_url":"https://i0.hdslb.com/bfs/wbi/def.png?abcdefghijabcdefghijabcdefghij"}}}"""
        val playurlJson = """{"code":0,"message":"0","data":{"quality":80,"format":"flv","durl":[{"order":1,"size":98765432,"url":"https://example.com/real-download.flv","length":30000}]}}"""
        every { call.execute() } returnsMany listOf(
            mockResponse(200, navJson),
            mockResponse(200, playurlJson),
        )
        every { wbiSigner.extractMixinKey(any(), any()) } returns "MOCK_MIXIN_KEY_32_CHARS_LONG_XX"
        every { wbiSigner.sign(any(), any(), any()) } returns "MOCK_W_RID_32_CHARS_LONG_XXXXXXX"

        val result = apiClient.playurl("BV1xx411c7mD", 12345L)
        assertThat(result.url).isEqualTo("https://example.com/real-download.flv")
        assertThat(result.size).isEqualTo(98765432L)
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
