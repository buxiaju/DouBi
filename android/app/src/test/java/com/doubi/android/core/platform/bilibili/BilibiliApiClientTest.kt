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

    // ---- v0.5.10 mixin_key 缓存 ----

    @Test
    fun `fetchMixinKey calls HTTP only once on multiple calls within TTL (cache hit)`() = runTest {
        // 第一次调用：缓存未命中 → HTTP 1 次
        val validJson = """{"code":0,"data":{"wbi_img":{"img_url":"https://i0.hdslb.com/bfs/wbi/abc.png?012345678901234567890123456789","sub_url":"https://i0.hdslb.com/bfs/wbi/def.png?abcdefghijabcdefghijabcdefghij"}}}"""
        every { call.execute() } returns mockResponse(200, validJson)
        every { wbiSigner.extractMixinKey(any(), any()) } returns "M".repeat(32)

        runCatching { apiClient.fetchMixinKey() }
        runCatching { apiClient.fetchMixinKey() }
        runCatching { apiClient.fetchMixinKey() }

        // 3 次调用**只**触发 1 次 HTTP（缓存命中）
        verify(exactly = 1) { client.newCall(any()) }
    }

    @Test
    fun `fetchMixinKey does not cache on failure (next call retries HTTP)`() = runTest {
        // 第一次：失败（HTTP 401）→ 缓存**不**被污染
        every { call.execute() } returns mockResponse(401, "unauthorized")

        val ex1 = runCatching { apiClient.fetchMixinKey() }.exceptionOrNull()
        assertThat(ex1).isInstanceOf(IOException::class.java)
        // 不应被缓存
        verify(exactly = 1) { client.newCall(any()) }

        // 第二次：仍然失败（**不**从缓存返过期值）→ 再次走 HTTP
        val ex2 = runCatching { apiClient.fetchMixinKey() }.exceptionOrNull()
        assertThat(ex2).isInstanceOf(IOException::class.java)
        // **新**的 HTTP 调用（**不**复用上次失败）
        verify(exactly = 2) { client.newCall(any()) }
    }

    // ---- v0.5.10 view 缓存 ----

    @Test
    fun `view calls HTTP only once on multiple calls with same bvid (cache hit)`() = runTest {
        val navJson = """{"code":0,"data":{"wbi_img":{"img_url":"https://i0.hdslb.com/bfs/wbi/abc.png?012345678901234567890123456789","sub_url":"https://i0.hdslb.com/bfs/wbi/def.png?abcdefghijabcdefghijabcdefghij"}}}"""
        val viewJson = """{"code":0,"data":{"bvid":"BV1xx","aid":1,"title":"t","duration":1,"cid":1}}"""
        // 第 1 次 mixin_key + 第 2 次 view = 2 次 HTTP；后续 view 都 cache hit
        every { call.execute() } returnsMany listOf(
            mockResponse(200, navJson),
            mockResponse(200, viewJson),
        )
        every { wbiSigner.extractMixinKey(any(), any()) } returns "MOCK_MIXIN_KEY_32_CHARS_LONG_XX"
        every { wbiSigner.sign(any(), any(), any()) } returns "MOCK_W_RID_32_CHARS_LONG_XXXXXXX"

        runCatching { apiClient.view("BV1xx411c7mD") }
        runCatching { apiClient.view("BV1xx411c7mD") }
        runCatching { apiClient.view("BV1xx411c7mD") }

        // 3 次 view 调用**只**触发 1 次 view HTTP（+ 1 次 mixin_key HTTP）= 2 次 newCall
        verify(exactly = 2) { client.newCall(any()) }
    }

    @Test
    fun `view uses different cache keys for different bvids`() = runTest {
        val navJson = """{"code":0,"data":{"wbi_img":{"img_url":"https://i0.hdslb.com/bfs/wbi/abc.png?012345678901234567890123456789","sub_url":"https://i0.hdslb.com/bfs/wbi/def.png?abcdefghijabcdefghijabcdefghij"}}}"""
        val viewJson1 = """{"code":0,"data":{"bvid":"BV1xx","aid":1,"title":"t1","duration":1,"cid":1}}"""
        val viewJson2 = """{"code":0,"data":{"bvid":"BV1yy","aid":2,"title":"t2","duration":2,"cid":2}}"""
        // 实际 HTTP 调用顺序：
        //   1) view(BV1xx) → mixin_key HTTP（cache miss） + view HTTP（cache miss）
        //   2) view(BV1yy) → mixin_key CACHE HIT（无 HTTP） + view HTTP（cache miss，新 bvid）
        //   3) view(BV1xx) → mixin_key CACHE HIT + view CACHE HIT（无 HTTP）
        // 共 3 次 HTTP：mixin_key × 1 + view × 2
        every { call.execute() } returnsMany listOf(
            mockResponse(200, navJson),
            mockResponse(200, viewJson1),
            mockResponse(200, viewJson2),
        )
        every { wbiSigner.extractMixinKey(any(), any()) } returns "MOCK_MIXIN_KEY_32_CHARS_LONG_XX"
        every { wbiSigner.sign(any(), any(), any()) } returns "MOCK_W_RID_32_CHARS_LONG_XXXXXXX"

        val r1 = apiClient.view("BV1xx411c7mD")
        val r2 = apiClient.view("BV1yy411c7mD")
        val r3 = apiClient.view("BV1xx411c7mD")  // 缓存命中

        assertThat(r1.title).isEqualTo("t1")
        assertThat(r2.title).isEqualTo("t2")
        assertThat(r3.title).isEqualTo("t1")  // 来自缓存

        // 2 个不同 bvid → 2 次 view HTTP 调用（+ 1 次 mixin_key）= 3 次 newCall
        verify(exactly = 3) { client.newCall(any()) }
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
