package com.doubi.android.core.platform.bilibili

import java.net.URLEncoder
import java.security.MessageDigest
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 阶段 14 v0.5.4：B 站 WBI 签名算法。1:1 对拍桌面版 `src/doubi/platforms/bilibili/wbi.py`。
 *
 * **背景**：B 站的 web API（`api.bilibili.com`）在 2023 年开始强制 wbi 签名——请求
 * 需带 `w_rid`（32 字符 MD5 签名）跟 `wts`（时间戳），否则返 -352 风控错误。
 *
 * **算法来源**：B 站前端 JS 代码公开（反编译后公开），社区多个开源项目复刻。
 * Android 端 v0.5.4 走同样的算法（Kotlin 重写）。
 *
 * **两步签名**：
 * 1. **`extractMixinKey(imgUrl, subUrl)`** —— 从 B 站 `nav` 接口返回的
 *    `wbi_img.img_url` + `wbi_img.sub_url` 提取 32 字符 `mixin_key`
 * 2. **`sign(query, mixinKey, wts)`** —— 用 mixin_key 签 query params 拿 `w_rid`
 *
 * **算法结构**（公开反编译）：
 * - mixinKeyEncTab = [46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
 *   27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13]（32 个下标）
 * - mixin_key = ''.join(filtered[i] for i in mixinKeyEncTab)
 *   其中 filtered 是 img_url + sub_url query 串过滤 `!'()*` 后的字符串
 * - w_rid = MD5( sortedUrlEncodedParams + wts + mixin_key )
 *
 * **v0.5.4 范围**：
 * - 实现两个核心函数（pure logic，不依赖网络）
 * - 单测用合成的 test vector 验证算法结构（字符数、表替换正确性、MD5 长度）
 * - **v0.5.5+ API 集成时用真 B 站 nav 响应验证 byte-for-byte 输出**
 *
 * **风险**：
 * - 公开反编译的算法如果 B 站前端 JS 改了，签名会失败——v0.5.5+ 需要真 API 验证
 * - 桌面版同样算法，1:1 对拍 + 同样的 live validation 需求
 */
@Singleton
class WbiSigner @Inject constructor() {

    /**
     * 从 nav 接口返回的 img_url + sub_url 提取 32 字符 mixin_key。
     *
     * @param imgUrl 来自 `wbi_img.img_url` 字段
     * @param subUrl 来自 `wbi_img.sub_url` 字段
     * @return 32 字符的 mixin_key
     * @throws IllegalArgumentException 输入字符串过滤特殊字符后不足 59 字符
     */
    fun extractMixinKey(imgUrl: String, subUrl: String): String {
        // 拼接 query 段（img_url 和 sub_url 通常都带 ?query=... 形式）
        val rawQuery = (imgUrl.substringAfter("?", missingDelimiterValue = "") +
            subUrl.substringAfter("?", missingDelimiterValue = ""))
        // 过滤 !'()* 特殊字符（B 站算法要求）
        val filtered = rawQuery.filterNot { it in "!'()*" }
        require(filtered.length >= MAX_INDEX + 1) {
            "filtered raw too short: ${filtered.length} chars (need ≥ ${MAX_INDEX + 1})"
        }
        // 应用 mixin_key 表替换：32 字符的 mixin_key
        return buildString(MIXIN_KEY_ENC_TAB.size) {
            for (i in MIXIN_KEY_ENC_TAB) {
                append(filtered[i])
            }
        }
    }

    /**
     * 计算 w_rid 签名。
     *
     * @param query 要签名的 query params（**不**含 wts / w_rid，函数自己加 wts）
     * @param mixinKey 32 字符的 mixin_key（从 [extractMixinKey] 拿）
     * @param wts 当前时间戳（秒）
     * @return 32 字符的 MD5 hex 签名（作为 `w_rid` 值）
     */
    fun sign(query: Map<String, String>, mixinKey: String, wts: Long): String {
        // 1. 加上 wts，按 key 排序
        val withWts = (query + ("wts" to wts.toString())).toSortedMap()
        // 2. URL-encode 每个 key + value，去掉 !'()* 特殊字符，拼接
        val joined = buildString {
            for ((k, v) in withWts) {
                append(urlEncodeAndFilter(k))
                append(urlEncodeAndFilter(v))
            }
        }
        // 3. 拼接 mixin_key，MD5
        val md5Input = joined + mixinKey
        return md5Hex(md5Input)
    }

    /**
     * URL-encode（`application/x-www-form-urlencoded` 风格）后过滤 `!'()*` 字符。
     *
     * 用 `URLEncoder.encode(str, "UTF-8")`（Java 标准库）+ 替换空格为 `%20`
     * （B 站算法要求，`URLEncoder` 默认是 `+`）。
     */
    private fun urlEncodeAndFilter(s: String): String {
        return URLEncoder.encode(s, "UTF-8")
            .replace("+", "%20")  // B 站算法用 %20 不用 +
            .filterNot { it in "!'()*" }
    }

    /**
     * 计算字符串的 MD5 hex（小写）。
     */
    private fun md5Hex(s: String): String {
        val bytes = MessageDigest.getInstance("MD5").digest(s.toByteArray(Charsets.UTF_8))
        return buildString(bytes.size * 2) {
            for (b in bytes) {
                val v = b.toInt() and 0xFF
                append(HEX_CHARS[v ushr 4])
                append(HEX_CHARS[v and 0x0F])
            }
        }
    }

    companion object {
        /**
         * mixin_key 替换表。32 个下标，每个 0-58，对应 32 字符 mixin_key。
         * 来源：B 站前端 JS 反编译（公开）。
         */
        private val MIXIN_KEY_ENC_TAB = intArrayOf(
            46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
            27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13
        )

        /**
         * MIXIN_KEY_ENC_TAB 的最大下标 + 1 = 59 = 过滤后 input 最小长度。
         */
        private const val MAX_INDEX = 58

        private val HEX_CHARS = "0123456789abcdef".toCharArray()
    }
}
