package com.doubi.android.core.platform.bilibili

import com.doubi.android.core.platform.bilibili.dto.BilibiliPlayUrlResponse
import com.doubi.android.core.platform.bilibili.dto.BilibiliViewResponse
import com.doubi.android.core.util.TimeBasedCache
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
 * **v0.5.8 新增**：
 * - `playurl(bvid, cid, qn)` —— `GET /x/player/playurl?bvid=XXX&cid=NNN&qn=80&wts=NNN&w_rid=YYY`
 *   拿真实下载直链（`durl[0].url`）—— Engine 集成 download 阶段需要
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
     * v0.5.10 mixin_key 缓存：5min TTL，进程内共享。key 用 "global" 因为 mixin_key 是
     * 全局单值（B 站 nav 端点返的服务端 wbi_img 当前值，所有 endpoint 共用）。
     */
    private val mixinKeyCache = TimeBasedCache<String, String>(
        ttlMillis = 5 * 60 * 1000L,
    )

    /**
     * v0.5.10 view 缓存：5min TTL，**按 bvid 分 key**。B 站视频 metadata
     * （title / duration / cid / owner）短时间（< 5min）内**不**变 —— 重复粘贴同一 B 站
     * URL 时省 1 次 view HTTP 调用（~200ms）。
     *
     * **缓存策略**：
     * - key = bvid（12 字符 BV ID 唯一）
     * - 缓存 value = `BilibiliViewResponse`（**不**含 wts / w_rid——这些是请求侧的
     *   瞬态值，每秒变化，**不**进缓存）
     * - 5min 后过期，下次 fetch 重新拉
     */
    private val viewCache = TimeBasedCache<String, BilibiliViewResponse>(
        ttlMillis = 5 * 60 * 1000L,
    )

    /**
     * v0.5.10 playurl 缓存：5min TTL，**按 `"$bvid:$cid:$qn"` 分 key**。B 站 playurl 接口
     * 返真实下载直链，**短时间（< 5min）内对同一 (bvid, cid, qn) 不变** —— 重复下载同一
     * 视频时省 1 次 playurl HTTP 调用（~200ms）。
     *
     * **缓存策略**：
     * - key = `"$bvid:$cid:$qn"`（3 元组——bvid 12 字符 + cid 数字 + qn 清晰度）
     * - **qn 必**进 key——不同清晰度返不同 URL，**不**能共享缓存
     * - 缓存 value = `BilibiliPlayUrlResponse`（url + size）
     * - 5min 后过期，下次 fetch 重新拉
     */
    private val playurlCache = TimeBasedCache<String, BilibiliPlayUrlResponse>(
        ttlMillis = 5 * 60 * 1000L,
    )

    /**
     * Fetch mixin_key from `/x/web-interface/nav`.
     *
     * **v0.5.10 加缓存**：5min TTL 内存缓存（[mixinKeyCache]）—— 避免 [view] / [playurl]
     * 每次都 fetch nav（~200ms HTTP 延迟）。多次调用 [view] / [playurl] 共享同一个 mixin_key。
     *
     * **缓存策略**：
     * - 缓存**只**存"成功结果"（[checkNotNull] 防御 null 污染）
     * - 失败（IOException / parse 错）**不**缓存（loader 抛错不写缓存）
     * - 5min 后过期，下次 fetch 重新拉
     *
     * @return 32 字符 mixin_key
     * @throws IOException HTTP / parse 错误
     */
    suspend fun fetchMixinKey(): String = mixinKeyCache.getOrLoad("global") {
        withContext(Dispatchers.IO) {
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
    }

    /**
     * Fetch video info with WBI signing.
     *
     * **v0.5.10 加缓存**：5min TTL 按 bvid 缓存（[viewCache]）—— B 站视频 metadata
     * 短时间内**不**变，重复粘贴同一 URL 省 1 次 view HTTP 调用（~200ms）。
     *
     * **注意**：缓存**只**存 `BilibiliViewResponse`，**不**存 wts / w_rid（这些是请求侧
     * 瞬态值，每秒变化）。每次调用都**重新**计算 wts + w_rid——cache hit 时**不**再发
     * HTTP 但**仍**用当前 timestamp 算 w_rid（**不**影响——response 已缓存）。
     *
     * @param bvid 12 字符 BV ID（如 `BV1xx411c7mD`）
     * @return [BilibiliViewResponse] 包含 title / duration / cid / owner
     * @throws IOException HTTP / parse / WBI signing 错误
     */
    suspend fun view(bvid: String): BilibiliViewResponse = viewCache.getOrLoad(bvid) {
        withContext(Dispatchers.IO) {
            // 1. Fetch mixin_key（v0.5.10 Commit 2 加缓存）
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
    }

    /**
     * 阶段 18 v0.5.8 + 阶段 20 v0.5.10：Fetch real download URL via `/x/player/playurl`。
     *
     * **v0.5.10 加缓存**：5min TTL 按 `"$bvid:$cid:$qn"` 缓存（[playurlCache]）—— B 站
     * playurl 短时间**不**变，重复下载同一视频省 1 次 HTTP（~200ms）。
     *
     * **注意**：缓存**只**存 url + size，**不**存 wts / w_rid（请求侧瞬态值）。
     * 每次调用都**重新**计算 wts + w_rid——cache hit 时**不**再发 HTTP 但**仍**用当前
     * timestamp 算 w_rid（**不**影响——response 已缓存）。
     *
     * **qn 进 cache key**：不同清晰度返不同 URL，**不**能共享缓存。
     *
     * @param bvid 12 字符 BV ID（如 `BV1xx411c7mD`）
     * @param cid Client ID（从 [view] 响应里拿）
     * @param qn 清晰度代码（默认 80 = 1080p 高清；其它常见值：16=360p / 32=480p / 64=720p / 80=1080p / 112=1080p+ / 116=1080p60）
     * @return [BilibiliPlayUrlResponse] 含真实下载直链（FLV / MP4 / m3u8）+ 文件大小
     * @throws IOException HTTP / parse / WBI signing / 业务 code != 0 错误
     */
    suspend fun playurl(bvid: String, cid: Long, qn: Int = 80): BilibiliPlayUrlResponse =
        playurlCache.getOrLoad("$bvid:$cid:$qn") {
            withContext(Dispatchers.IO) {
                // 1. Fetch mixin_key（v0.5.10 Commit 2 加缓存）
                val mixinKey = fetchMixinKey()
                // 2. Compute w_rid
                val wts = System.currentTimeMillis() / 1000
                val wRid = wbiSigner.sign(
                    mapOf("bvid" to bvid, "cid" to cid.toString(), "qn" to qn.toString()),
                    mixinKey,
                    wts,
                )
                // 3. Build signed URL
                val url = "$baseUrl/x/player/playurl?bvid=$bvid&cid=$cid&qn=$qn&wts=$wts&w_rid=$wRid"
                Timber.d(
                    "BilibiliApi.playurl bvid=%s cid=%d qn=%d wts=%d w_rid=%s",
                    bvid, cid, qn, wts, wRid,
                )
                val request = Request.Builder()
                    .url(url)
                    .get()
                    .header("User-Agent", USER_AGENT)
                    .build()

                client.newCall(request).execute().use { resp ->
                    if (!resp.isSuccessful) {
                        throw IOException("playurl failed: HTTP ${resp.code}")
                    }
                    val body = resp.body?.string()
                        ?: throw IOException("playurl body empty")
                    parsePlayUrlResponse(body)
                }
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
     * 用 regex 提取 playurl 响应里的 `durl[0].url` + `durl[0].size`。
     *
     * **v0.5.8 简化**：
     * - 优先取 `durl[0].url`（FLV / MP4 直链），fallback `dash.video[0].baseUrl`（DASH 流）
     * - **不**解析 `accept_quality` / `accept_description`（v0.5.9+ 清晰度选择用）
     * - size 0 视为未知（多 P 视频常见，**不**报错）
     *
     * 响应结构示例：
     * ```
     * {
     *   "code": 0,
     *   "message": "0",
     *   "data": {
     *     "from": "local",
     *     "quality": 80,
     *     "format": "flv",
     *     "timelength": 300000,
     *     "durl": [
     *       {
     *         "order": 1,
     *         "length": 30000,
     *         "size": 12345678,
     *         "url": "https://cn-jsnt-cu-04-12.bilivideo.com/...?bvid=..."
     *       }
     *     ]
     *   }
     * }
     * ```
     */
    private fun parsePlayUrlResponse(body: String): BilibiliPlayUrlResponse {
        // code != 0 抛错（业务错误）
        val codeMatch = CODE_REGEX.find(body)?.groupValues?.get(1)?.toIntOrNull()
        if (codeMatch != null && codeMatch != 0) {
            val message = MESSAGE_REGEX.find(body)?.groupValues?.get(1) ?: "unknown"
            throw IOException("playurl returned code=$codeMatch message=$message")
        }
        // 优先 durl[0].url（FLV/MP4 直链），fallback dash.video[0].baseUrl（DASH 流）
        val durlUrl = DURL_URL_REGEX.find(body)?.groupValues?.get(1)
        val dashUrl = DASH_VIDEO_URL_REGEX.find(body)?.groupValues?.get(1)
        val url = durlUrl ?: dashUrl
            ?: throw IOException("playurl no durl/dash URL found in response")
        val size = DURL_SIZE_REGEX.find(body)?.groupValues?.get(1)?.toLongOrNull() ?: 0L
        return BilibiliPlayUrlResponse(url = url, size = size)
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

        // ---- v0.5.8 playurl 响应字段 ----

        /**
         * 提取 `durl` 数组里第一个 `{"order":1,"size":NNN,"url":"..."}` 的 `url` 字段。
         *
         * 简化算法：找 `"durl":[{` 后的第一个 `"url":"..."` 出现的位置——通常是 `durl[0]`
         * （[parsePlayUrlResponse] 拿这条 url 给 [YtDlpEngine.download] 跑下载）。
         *
         * **v0.5.8 限制**：如果 `durl[0]` 是分 P 视频片段（非分 P 整段），regex 仍能拿
         * 到——但实际下载时 yt-dlp 会按 m3u8 / 单段 FLV 处理。v0.5.9+ 解析 `durl.length` 字段做校验。
         */
        private val DURL_URL_REGEX = Regex(""""durl"\s*:\s*\[\s*\{[^}]*?"url"\s*:\s*"([^"]+)"""")

        /**
         * 提取 `durl[0].size` 整数值（字节，0 = 未知）。
         *
         * 同样找 `"durl":[{` 后的第一个 `"size":NNN` 出现的位置——简化算法
         * 不严格匹配 `size` 一定在 `url` 之前（B 站 JSON 字段顺序固定：order / length / size / url，
         * 但万一有变化 regex 仍能匹配到 size）。
         */
        private val DURL_SIZE_REGEX = Regex(""""durl"\s*:\s*\[\s*\{[^}]*?"size"\s*:\s*(\d+)""")

        /**
         * Fallback 提取 `dash.video[0].baseUrl` 字段值。
         *
         * 当 B 站返 dash 流（fnval=16 时常见）时，`durl` 是空数组，**不**走 `durl[0].url`。
         * 这种场景 regex 退到 `dash.video[0].baseUrl`（DASH 流需要 MP4Box / ffmpeg 合并，
         * v0.5.8 范围 yt-dlp 跑会失败——v0.5.9+ 单独处理）。
         */
        private val DASH_VIDEO_URL_REGEX =
            Regex(""""dash"\s*:\s*\{[^}]*?"video"\s*:\s*\[\s*\{[^}]*?"baseUrl"\s*:\s*"([^"]+)"""")
    }
}
