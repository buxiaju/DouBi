package com.doubi.android.core.platform.douyin

import java.security.MessageDigest
import java.util.Base64
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 阶段 14 v0.5.4：抖音 X-Bogus 签名算法。1:1 对拍桌面版 `src/doubi/platforms/douyin/xbogus.py`。
 *
 * **v0.5.4 placeholder 范围**：
 * - **接口落地**：`sign(url, userAgent, timestamp): String` 签名
 * - **结构验证**：单测验证输入参数敏感、确定性、输出长度
 * - **byte-for-byte 实现留 v0.5.5+** —— 公开反编译的 X-Bogus 算法涉及 RC4 加密 +
 *   MD5 + 自定义字节操作 + 复杂编码，**没有真抖音 web 响应作为 test vector** 没法
 *   验证 byte-for-byte 输出
 *
 * **算法背景**（v0.5.5+ 真的要实装时再看）：
 * 抖音 web API（`www.iesdouyin.com/web/api/v2/...`、`www.douyin.com/aweme/v1/web/...`）
 * 强制要求请求带 `X-Bogus` query param（19 字符），缺失返 -352 风控错误。
 * X-Bogus 算法是抖音前端 JS（`byted-acrawler`）的产物——公开反编译后有多个社区
 * 复刻项目（`Douyin_TikTok_Download_API`、`Johnserf-Seed/f2` 等）。
 *
 * **算法大致结构**（公开反编译，v0.5.5+ 复刻用）：
 * 1. 收集 inputs：URL path + sorted URL params + body + userAgent + timestamp
 * 2. 字节化拼接（特定分隔符）
 * 3. MD5 hash 部分
 * 4. RC4 加密（特定 key）
 * 5. XOR / byte 操作合成
 * 6. 编码成 19 字符字符串
 *
 * **v0.5.4 简化实现**（placeholder）：
 * - 用 SHA-256(UA + URL + timestamp) 取前 20 字符做 base64
 * - **不**等于真抖音 X-Bogus 输出——只是为了**结构对齐**（输入参数、输出格式）
 * - v0.5.5+ API 集成时换成真算法，**单测**保留（验证输入参数敏感性仍然有效）
 *
 * **风险**：
 * - v0.5.4 placeholder 直接拿去打抖音 web API 会被风控 -352
 * - v0.5.5+ 必须实装真算法才能用
 * - 抖音可能改前端 JS 让反编译算法失效——需 live validation
 */
@Singleton
class XBogusSigner @Inject constructor() {

    /**
     * 计算 X-Bogus 字符串。
     *
     * @param url 完整 URL（含 query string）
     * @param userAgent 浏览器 UA（桌面版从 `AppConfig.userAgent` 拿）
     * @param timestamp 当前时间戳（秒）
     * @return X-Bogus 字符串（v0.5.4 placeholder——**不**是抖音真算法输出）
     */
    fun sign(url: String, userAgent: String, timestamp: Long): String {
        // v0.5.4 placeholder：把输入拼一起做 SHA-256，前 20 字符做 base64
        // v0.5.5+ 实装真算法：MD5 + RC4 + 复杂字节操作
        val input = "$userAgent|$url|$timestamp"
        val sha256 = MessageDigest.getInstance("SHA-256").digest(input.toByteArray(Charsets.UTF_8))
        return Base64.getEncoder().withoutPadding().encodeToString(sha256).take(SIGNATURE_LENGTH)
    }

    companion object {
        /**
         * 真 X-Bogus 字符串长度 19 字符（公开文档）。
         * v0.5.4 placeholder 输出也是 20 字符（base64 前 20 位）——v0.5.5+ 实装
         * 真算法时改成 19。
         */
        const val SIGNATURE_LENGTH = 20
    }
}
