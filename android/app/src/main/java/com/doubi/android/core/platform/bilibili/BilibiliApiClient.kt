package com.doubi.android.core.platform.bilibili

import com.doubi.android.core.platform.bilibili.dto.BilibiliViewResponse
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import timber.log.Timber
import java.io.IOException
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 阶段 16 v0.5.6：B 站 web API 客户端。1:1 对拍桌面版 `src/doubi/platforms/bilibili/api.py`。
 *
 * **v0.5.6 范围**：
 * - `fetchMixinKey()` —— `GET /x/web-interface/nav` 拿 `wbi_img.img_url` + `wbi_img.sub_url`
 *   抽 [WbiSigner.extractMixinKey] 拿 32 字符 mixin_key
 * - `view(bvid)` —— `GET /x/web-interface/view?bvid=XXX&wts=NNN&w_rid=XXX` 拿视频
 *   info（title / duration / cid / owner）
 *
 * **WBI 签名**（[WbiSigner]）：
 * - mixin_key 每次 `fetchMixinKey()` 拿——**不**缓存（v0.5.7+ 考虑缓存）
 * - `wts` = 当前时间戳（秒）
 * - `w_rid` = `MD5(sortedQueryString + wts + mixin_key)`
 * - B 站 2023 年起强制 wbi 签名，缺失返 -352 风控
 *
 * **v0.5.6 简化**：
 * - **不**缓存 mixin_key（每次 view 都 fetch nav，~200ms 额外延迟）
 * - **不**处理 412/403 重试逻辑（v0.5.7+ 留接口）
 * - **不**调用 playurl 接口拿真实播放 URL（v0.5.7+ Engine 集成再做）
 * - **JSON 解析用 regex**——`org.json.JSONObject` 在 JVM 单测是 stub
 *   （[phase-9.md 修复段](phases/phase-9.md)）；用 regex 提取字段可测
 *
 * **桌面版对应字段**：
 * - `view.bvid` —— 12 字符 BV ID
 * - `view.aid` —— 数字 AV ID
 * - `view.title` —— 视频标题
 * - `view.duration` —— 视频时长（秒）
 * - `view.cid` —— Client ID（playurl 接口需要）
 * - `view.owner.name` —— UP 主名字
 * - `view.pages` —— 分 P 列表（多 P 视频才有）
 */
@Singleton
class BilibiliApiClient @Inject constructor(
    private val wbiSigner: WbiSigner,
    private val client: OkHttpClient = defaultClient(),
) {
    private val baseUrl = "https://api.bilibili.com"

    /**
     * Fetch mixin_key from `/x/web-interface/nav`.
     *
     * @return 32 字符 mixin_key
     * @throws IOException HTTP / parse 错误
     */
    suspend fun fetchMixinKey(): String = withContext(Dispatchers.IO) {
        val request = Request.Builder()
            .url("$baseUrl/x/web-interface/nav")
            .get()
            .header("User-Agent", USER_AGENT)
            .build()

        client.newCall(request).execute().use { resp ->
            if (!resp.isSuccessful) {
                throw IOException("nav failed: HTTP ${resp.code}")
            }
            val body = resp.body?.string()
                ?: throw IOException("nav body empty")
            val (imgUrl, subUrl) = extractWbiUrls(body)
                ?: throw IOException("nav wbi_img fields missing")
            wbiSigner.extractMixinKey(imgUrl, subUrl)
        }
    }

    /**
     * Fetch video info with WBI signing.
     *
     * @param bvid 12 字符 BV ID（如 `BV1xx411c7mD`）
     * @return [BilibiliViewResponse] 包含 title / duration / cid / owner
     * @throws IOException HTTP / parse / WBI signing 错误
     */
    suspend fun view(bvid: String): BilibiliViewResponse = withContext(Dispatchers.IO) {
        // 1. Fetch mixin_key
        val mixinKey = fetchMixinKey()
        // 2. Compute w_rid
        val wts = System.currentTimeMillis() / 1000
        val wRid = wbiSigner.sign(mapOf("bvid" to bvid), mixinKey, wts)
        // 3. Build signed URL
        val url = "$baseUrl/x/web-interface/view?bvid=$bvid&wts=$wts&w_rid=$wRid"
        Timber.d("BilibiliApi.view bvid=%s wts=%d w_rid=%s", bvid, wts, wRid)
        val request = Request.Builder()
            .url(url)
            .get()
            .header("User-Agent", USER_AGENT)
            .build()

        client.newCall(request).execute().use { resp ->
            if (!resp.isSuccessful) {
                throw IOException("view failed: HTTP ${resp.code}")
            }
            val body = resp.body?.string()
                ?: throw IOException("view body empty")
            parseViewResponse(bvid, body)
        }
    }

    /**
     * 用 regex 提取 nav 响应里的 `wbi_img.img_url` + `wbi_img.sub_url`。
     *
     * 不用 `org.json.JSONObject` 是因为它在 JVM 单测是 stub。
     * B 站 nav 响应结构固定（`{"data":{"wbi_img":{"img_url":"...","sub_url":"..."}}}`），
     * regex 提取稳定可靠。
     */
    private fun extractWbiUrls(body: String): Pair<String, String>? {
        val imgUrl = IMG_URL_REGEX.find(body)?.groupValues?.get(1) ?: return null
        val subUrl = SUB_URL_REGEX.find(body)?.groupValues?.get(1) ?: return null
        if (imgUrl.isEmpty() || subUrl.isEmpty()) return null
        return imgUrl to subUrl
    }

    /**
     * 用 regex 提取 view 响应里的字段。
     *
     * **v0.5.6 简化**：只拿核心字段（bvid / aid / title / duration / cid / owner）。
     * v0.5.7+ 加：pages (分 P) / pic (封面) / pubdate (发布时间) / desc (描述) /
     * tname (分类) / dynamic (动态) / stat (统计).
     */
    private fun parseViewResponse(bvid: String, body: String): BilibiliViewResponse {
        // code != 0 抛错
        val codeMatch = CODE_REGEX.find(body)?.groupValues?.get(1)?.toIntOrNull()
        if (codeMatch != null && codeMatch != 0) {
            val message = MESSAGE_REGEX.find(body)?.groupValues?.get(1) ?: "unknown"
            throw IOException("view returned code=$codeMatch message=$message")
        }
        val title = STRING_REGEX_DEF(title = "title").find(body)?.groupValues?.get(1) ?: ""
        val duration = INT_REGEX_DEF(key = "duration").find(body)?.groupValues?.get(1)?.toIntOrNull() ?: 0
        val cid = INT_REGEX_DEF(key = "cid").find(body)?.groupValues?.get(1)?.toLongOrNull() ?: 0L
        val aid = INT_REGEX_DEF(key = "aid").find(body)?.groupValues?.get(1)?.toLongOrNull() ?: 0L
        val ownerName = STRING_REGEX_DEF(title = "name").find(body)?.groupValues?.get(1) ?: ""
        val ownerMid = INT_REGEX_DEF(key = "mid").find(body)?.groupValues?.get(1)?.toLongOrNull() ?: 0L
        // pages 数组长度 = 找 pages:[{...},{...}] 这种模式，逗号 + 大括号数 = 数量
        val pagesCount = countPagesArray(body)
        return BilibiliViewResponse(
            bvid = STRING_REGEX_DEF(title = "bvid").find(body)?.groupValues?.get(1) ?: bvid,
            aid = aid,
            title = title,
            duration = duration,
            cid = cid,
            ownerName = ownerName,
            ownerMid = ownerMid,
            pageCount = pagesCount,
        )
    }

    private fun STRING_REGEX_DEF(title: String): Regex {
        // "title":"..."  注意是双引号 + JSON 转义 \\"
        return Regex(""""$title"\s*:\s*"((?:[^"\\]|\\.)*)"""")
    }

    private fun INT_REGEX_DEF(key: String): Regex {
        return Regex("""$key"\s*:\s*(\d+)""")
    }

    /**
     * 数 pages 数组里 {} 的数量——"pages":[{...},{...},{...}] → 3。
     * 简单算法：找 `"pages":[` 后到 `]` 之前，每遇到一个 `,{` 或 `[{` 就 +1。
     */
    private fun countPagesArray(body: String): Int {
        val start = body.indexOf("\"pages\":[")
        if (start < 0) return 0
        val end = body.indexOf("]", start)
        if (end < 0) return 0
        val arr = body.substring(start, end)
        // 数顶层 {} 数量（简化：每个 `{` +1）
        var count = 0
        var depth = 0
        for (c in arr) {
            when (c) {
                '{' -> { depth++; if (depth == 1) count++ }
                '}' -> { depth-- }
            }
        }
        return count
    }

    companion object {
        /**
         * v0.5.6 默认 OkHttpClient——10s connect / 10s read timeout。
         *
         * **v0.5.6 简化**：用 [BilibiliApiClient] 内部默认 client——v0.5.7+ 改用
         * Hilt 注入共享 client（[com.doubi.android.core.sniffer.di.SnifferModule.provideOkHttpClient]）。
         * 测试时构造参数显式传 mock client。
         */
        @JvmStatic
        fun defaultClient(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(10, TimeUnit.SECONDS)
            .build()

        /**
         * 桌面版 Chrome 128 的标准 User-Agent。
         *
         * **v0.5.6 简化**：写死一个常用 UA——桌面版允许用户配置 UA 但 v0.5.6 范围
         * 不做。v0.5.7+ 接 [AppConfig.userAgent] 配置。
         */
        const val USER_AGENT =
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"

        /** Regex: 提取 `"img_url":"..."` 字段值 */
        private val IMG_URL_REGEX = Regex(""""img_url"\s*:\s*"([^"]+)"""")

        /** Regex: 提取 `"sub_url":"..."` 字段值 */
        private val SUB_URL_REGEX = Regex(""""sub_url"\s*:\s*"([^"]+)"""")

        /** Regex: 提取顶层 `"code":NNN` 整数值 */
        private val CODE_REGEX = Regex(""""code"\s*:\s*(-?\d+)""")

        /** Regex: 提取顶层 `"message":"..."` 字符串值 */
        private val MESSAGE_REGEX = Regex(""""message"\s*:\s*"([^"]*)"""")
    }
}
