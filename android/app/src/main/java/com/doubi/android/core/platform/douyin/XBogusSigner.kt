package com.doubi.android.core.platform.douyin

import com.doubi.android.core.util.CustomBase64
import com.doubi.android.core.util.RC4
import java.security.MessageDigest
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 阶段 14/15 v0.5.4 / v0.5.5：抖音 X-Bogus 签名算法。1:1 对拍桌面版 `src/doubi/platforms/douyin/xbogus.py`。
 *
 * **v0.5.5 阶段 15 升级**（vs v0.5.4 placeholder）：
 * - 抽出 **RC4 加密**（[RC4.encrypt]）和 **自定义 Base64 编码**（[CustomBase64.encode]）作为
 *   独立 utility —— 都是公开反编译的 well-defined 算法
 * - [sign] 用 [RC4] 加密 chaos_str + [CustomBase64] 编码 final 字符串
 * - **get_chaos(params, ua)** 仍是 stub（v0.5.6+ 实装真 JS 执行 / 字节拼装）
 *
 * **公开反编译的 a_bogus 算法结构**（参考 https://blog.csdn.net/weixin_48673014 ）：
 * ```
 * def get_a_bogus(params, _ua):
 *     s1, s2 = get_chaos(params, _ua)     # 调 JS 黑盒拿两个 byte 字符串
 *     s2 = make_str_chaos(s2)             # RC4 with key=[131] 加密 s2
 *     a_bogus = chaos2result(s1 + s2)     # 自定义 base64 编码
 *     return a_bogus
 * ```
 *
 * **v0.5.5 实装的部分**：
 * - `make_str_chaos` → [RC4.encrypt] with key=[131] ✓
 * - `chaos2result` → [CustomBase64.encode] with a_bogus 字母表 ✓
 *
 * **v0.5.6+ 仍 stub 的部分**：
 * - `get_chaos(params, _ua)` —— 需要执行抖音前端 JS（`webmssdk.js`）+ 拼装 ~110 字节大数组
 * - v0.5.5 用 `SHA-256(params + ua + timestamp) → 32 字节` 作为 stub chaos
 * - **v0.5.5 输出** ≠ 抖音真 a_bogus，但**结构对齐**（经过 RC4 + 自定义 base64）
 *
 * **风险**：
 * - v0.5.5 stub chaos 走抖音 web API 仍会被 -352 风控
 * - 真 chaos 算法 v0.5.6+ 实装：要么用 Rhino / Nashorn 执行 JS（Android 端
 *   JavaScript 引擎集成），要么反编译算法后手写
 * - 抖音可能改前端 JS 让反编译算法失效——需 live validation
 */
@Singleton
class XBogusSigner @Inject constructor() {

    /**
     * 计算 a_bogus 字符串。
     *
     * @param url 完整 URL（含 query string）
     * @param userAgent 浏览器 UA
     * @param timestamp 当前时间戳（秒）
     * @return a_bogus 字符串（v0.5.5 结构对齐 + RC4 + 自定义 base64；**v0.5.6+ 才能 byte-for-byte 真**）
     */
    fun sign(url: String, userAgent: String, timestamp: Long): String {
        // v0.5.5 stub chaos：SHA-256(params + ua + timestamp) → 32 字节
        // 真实 get_chaos 需要调抖音 webmssdk.js 拿 ~110 字节大数组
        val stubChaos = generateStubChaos(url, userAgent, timestamp)
        // a_bogus 算法第二步：RC4 with key=[131] 加密 chaos
        val encrypted = RC4.encrypt(stubChaos, RC4_KEY)
        // a_bogus 算法第三步：自定义 base64 编码（a_bogus 字母表）
        return CustomBase64.encode(encrypted, A_BOGUS_ALPHABET)
    }

    /**
     * v0.5.5 stub chaos 生成 —— 用 SHA-256 拼 32 字节。
     *
     * **v0.5.6+ 必须替换**为真 `get_chaos` —— 这函数当前**不**等价抖音 a_bogus 输入。
     * 保留它是**为了**：
     * 1. **结构验证**——v0.5.5 output 确实经过 RC4 + 自定义 base64
     * 2. **代码骨架**——v0.5.6+ 替换 get_chaos 即可，无需改其它部分
     * 3. **测试可写**——stub 输出确定性，能跑单测
     */
    private fun generateStubChaos(url: String, userAgent: String, timestamp: Long): ByteArray {
        val input = "$userAgent|$url|$timestamp"
        return MessageDigest.getInstance("SHA-256").digest(input.toByteArray(Charsets.UTF_8))
    }

    companion object {
        /**
         * a_bogus 算法第二步用的 RC4 key（公开反编译固定值）。
         */
        private val RC4_KEY: ByteArray = byteArrayOf(131.toByte())

        /**
         * a_bogus 算法第三步用的自定义 Base64 字母表（公开反编译固定值）。
         * 64 字符，跟标准 Base64 同长度，**顺序不同**。
         */
        const val A_BOGUS_ALPHABET = "Dkdpgh2ZmsQB80/MfvV36XI1R45-WUAlEixNLwoqYTOPuzKFjJnry79HbGcaStCe"

        /**
         * v0.5.5 stub 输出长度 = SHA-256 32 字节 → base64 后 44 字符
         * （v0.5.5 placeholder v0.5.4 是 20 字符，v0.5.5 升级到完整 RC4 + base64 路径，
         * 输出从 20 → 44 字符）
         *
         * **真 a_bogus 输出约 168-172 字符**（公开反编译文档）——v0.5.6+ 实装真 get_chaos 后
         * 输出长度会变。
         */
        const val SIGNATURE_LENGTH = 44
    }
}
