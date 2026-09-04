package com.doubi.android.core.platform.douyin

import com.doubi.android.core.platform.douyin.dto.DouyinAwemeItem
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
 * 阶段 16 v0.5.6：抖音 web API 客户端。1:1 对拍桌面版 `src/doubi/platforms/douyin/api.py`。
 *
 * **v0.5.6 范围**：
 * - `awemeItemInfo(itemIds)` —— `GET /web/api/v2/aweme/iteminfo/?item_ids=NNN` 拿视频
 *   info（aweme_id / desc / duration / author / play URL）
 * - **X-Bogus 签名**（[XBogusSigner]）—— v0.5.5 是 placeholder，v0.5.6+ 真 get_chaos 实装
 *   后才能打真抖音 web API
 *
 * **v0.5.6 简化**：
 * - **X-Bogus 是 v0.5.5 placeholder**（SHA-256 stub chaos → RC4 → a_bogus 字母表）——
 *   走抖音 web API 会被 -352 风控
 * - **不**缓存 X-Bogus（v0.5.7+ 真算法 + 缓存）
 * - **不**调用 playwm / playaddr 拿真实播放 URL（v0.5.7+ Engine 集成再做）
 * - **JSON 解析用 regex**——`org.json.JSONObject` 在 JVM 单测是 stub
 *   （[phase-9.md 修复段](phases/phase-9.md)）；用 regex 提取字段可测
 *
 * **桌面版对应字段**：
 * - `aweme_list[].aweme_id` —— 视频 ID（数字字符串）
 * - `aweme_list[].desc` —— 视频描述/标题
 * - `aweme_list[].duration` —— 视频时长（毫秒）
 * - `aweme_list[].author.nickname` —— 作者名
 * - `aweme_list[].video.play_addr.url_list[0]` —— 无水印播放 URL
 * - `aweme_list[].video.cover.url_list[0]` —— 封面 URL
 */
@Singleton
class DouyinApiClient @Inject constructor(
    private val xBogusSigner: XBogusSigner,
    private val client: OkHttpClient = defaultClient(),
) {
    private val baseUrl = "https://www.iesdouyin.com"

    /**
     * Fetch aweme (video) item info.
     *
     * @param itemIds 抖音 video ID（数字字符串，多个用逗号分隔）
     * @return [DouyinAwemeItem] 第一个匹配的 aweme
     * @throws IOException HTTP / parse / X-Bogus signing 错误
     *
     * **v0.5.6 限制**：X-Bogus 是 placeholder，**不能**打真抖音 web API（-352 风控）
     */
    suspend fun awemeItemInfo(itemIds: String): DouyinAwemeItem = withContext(Dispatchers.IO) {
        // 1. 构造 URL
        val path = "/web/api/v2/aweme/iteminfo/"
        val urlParams = mapOf("item_ids" to itemIds)
        val xBogus = xBogusSigner.sign(
            url = "$baseUrl$path?item_ids=$itemIds",
            userAgent = USER_AGENT,
            timestamp = System.currentTimeMillis() / 1000,
        )
        val url = "$baseUrl$path?item_ids=$itemIds&X-Bogus=$xBogus"
        Timber.d("DouyinApi.awemeItemInfo itemIds=%s X-Bogus=%s", itemIds, xBogus)

        val request = Request.Builder()
            .url(url)
            .get()
            .header("User-Agent", USER_AGENT)
            .build()

        client.newCall(request).execute().use { resp ->
            if (!resp.isSuccessful) {
                throw IOException("aweme_iteminfo failed: HTTP ${resp.code}")
            }
            val body = resp.body?.string()
                ?: throw IOException("aweme_iteminfo body empty")
            parseAwemeItemInfoResponse(body)
                ?: throw IOException("aweme_iteminfo returned no aweme_list")
        }
    }

    /**
     * 用 regex 提取 aweme_iteminfo 响应里的第一个 aweme。
     *
     * 不用 `org.json.JSONObject` 是因为它在 JVM 单测是 stub。
     * 抖音响应结构固定（`{"status_code":0,"aweme_list":[{...}]}`），
     * regex 提取稳定可靠。
     */
    private fun parseAwemeItemInfoResponse(body: String): DouyinAwemeItem? {
        // 0 = 成功
        val statusCode = STATUS_CODE_REGEX.find(body)?.groupValues?.get(1)?.toIntOrNull() ?: 0
        if (statusCode != 0) return null

        // 提取第一个 aweme_list 元素
        val firstAweme = extractFirstAwemeFromArray(body, "\"aweme_list\":[", "]") ?: return null

        val awemeId = STRING_REGEX_DEF("aweme_id").find(firstAweme)?.groupValues?.get(1) ?: ""
        val desc = STRING_REGEX_DEF("desc").find(firstAweme)?.groupValues?.get(1) ?: ""
        // duration 在抖音响应里是毫秒
        val duration = INT_REGEX_DEF("duration").find(firstAweme)?.groupValues?.get(1)?.toIntOrNull() ?: 0
        // 视频时长（秒）= 毫秒 / 1000
        val durationSec = duration / 1000
        val author = extractAuthorObject(firstAweme)
        val video = extractVideoObject(firstAweme)
        return DouyinAwemeItem(
            awemeId = awemeId,
            desc = desc,
            durationSec = durationSec,
            authorNickname = author?.nickname ?: "",
            authorSecUid = author?.secUid ?: "",
            playUrl = video?.playUrl ?: "",
            coverUrl = video?.coverUrl ?: "",
        )
    }

    private fun extractFirstAwemeFromArray(body: String, startKey: String, endKey: String): String? {
        val start = body.indexOf(startKey)
        if (start < 0) return null
        val arrStart = start + startKey.length
        val end = body.indexOf(endKey, arrStart)
        if (end < 0) return null
        val arr = body.substring(arrStart, end)
        // 找第一个顶层 { ... } 对象
        val depth0 = arr.indexOf('{')
        if (depth0 < 0) return null
        var depth = 0
        for (i in depth0 until arr.length) {
            when (arr[i]) {
                '{' -> depth++
                '}' -> {
                    depth--
                    if (depth == 0) return arr.substring(depth0, i + 1)
                }
            }
        }
        return null
    }

    private fun extractAuthorObject(aweme: String): AuthorFields? {
        val authorBlock = extractFirstObjectByKey(aweme, "\"author\":") ?: return null
        val nickname = STRING_REGEX_DEF("nickname").find(authorBlock)?.groupValues?.get(1) ?: ""
        val secUid = STRING_REGEX_DEF("sec_uid").find(authorBlock)?.groupValues?.get(1) ?: ""
        return AuthorFields(nickname, secUid)
    }

    private fun extractVideoObject(aweme: String): VideoFields? {
        val videoBlock = extractFirstObjectByKey(aweme, "\"video\":") ?: return null
        // play_addr.url_list[0] = 无水印 URL
        val playUrl = extractFirstStringFromArray(videoBlock, "\"play_addr\":", "\"url_list\":[", "]") ?: ""
        // cover.url_list[0] = 封面 URL
        val coverUrl = extractFirstStringFromArray(videoBlock, "\"cover\":", "\"url_list\":[", "]") ?: ""
        return VideoFields(playUrl, coverUrl)
    }

    private fun extractFirstObjectByKey(body: String, key: String): String? {
        val start = body.indexOf(key)
        if (start < 0) return null
        val objStart = body.indexOf('{', start + key.length)
        if (objStart < 0) return null
        var depth = 0
        for (i in objStart until body.length) {
            when (body[i]) {
                '{' -> depth++
                '}' -> {
                    depth--
                    if (depth == 0) return body.substring(objStart, i + 1)
                }
            }
        }
        return null
    }

    /**
     * 从 `"X":` 后到下一个 `]` 之前的数组，提取第一个字符串。
     *
     * 用法：`extractFirstStringFromArray(aweme, "\"play_addr\":", "\"url_list\":[", "]")` 找
     * 嵌套的 `"play_addr":{...,"url_list":["第一个","第二个",...]...}`。
     */
    private fun extractFirstStringFromArray(
        body: String,
        outerKey: String,
        arrayKey: String,
        arrayEndKey: String,
    ): String? {
        val outerStart = body.indexOf(outerKey)
        if (outerStart < 0) return null
        val arrStart = body.indexOf(arrayKey, outerStart + outerKey.length)
        if (arrStart < 0) return null
        val end = body.indexOf(arrayEndKey, arrStart + arrayKey.length)
        if (end < 0) return null
        val arr = body.substring(arrStart + arrayKey.length, end)
        // 找第一个 "..." 字符串
        val firstStr = STRING_VALUE_REGEX.find(arr.trimStart())?.groupValues?.get(1) ?: return null
        return unescapeJsonString(firstStr)
    }

    private fun unescapeJsonString(s: String): String {
        // 简化：只处理 \" \\ \/ \n \r \t \b \f
        return s.replace("\\\"", "\"")
            .replace("\\\\", "\\")
            .replace("\\/", "/")
            .replace("\\n", "\n")
            .replace("\\r", "\r")
            .replace("\\t", "\t")
    }

    private fun STRING_REGEX_DEF(key: String): Regex {
        return Regex("""$key"\s*:\s*"((?:[^"\\]|\\.)*)"""")
    }

    private fun INT_REGEX_DEF(key: String): Regex {
        return Regex("""$key"\s*:\s*(\d+)""")
    }

    private data class AuthorFields(val nickname: String, val secUid: String)
    private data class VideoFields(val playUrl: String, val coverUrl: String)

    companion object {
        /**
         * v0.5.6 默认 OkHttpClient——10s connect / 10s read timeout。
         *
         * **v0.5.6 简化**：用 [DouyinApiClient] 内部默认 client——v0.5.7+ 改用
         * Hilt 注入共享 client（[com.doubi.android.core.sniffer.di.SnifferModule.provideOkHttpClient]）。
         */
        @JvmStatic
        fun defaultClient(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(10, TimeUnit.SECONDS)
            .build()

        /**
         * 桌面版 Chrome 128 的标准 User-Agent。
         *
         * **v0.5.6 简化**：写死一个常用 UA——v0.5.7+ 接 [AppConfig.userAgent] 配置
         */
        const val USER_AGENT =
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"

        /** Regex: 提取顶层 `"status_code":NNN` 整数值 */
        private val STATUS_CODE_REGEX = Regex(""""status_code"\s*:\s*(\d+)""")

        /** Regex: 提取 JSON 字符串值（支持 \" \\ 转义） */
        private val STRING_VALUE_REGEX = Regex(""""((?:[^"\\]|\\.)*)"""")
    }
}
