package com.doubi.android.core.platform.douyin

import com.google.common.truth.Truth.assertThat
import org.junit.Test

/**
 * 阶段 14 v0.5.4：[XBogusSigner] 单测（**placeholder 范围**）。
 *
 * **覆盖**（5 例，验证结构**不**验证 byte-for-byte 真抖音 X-Bogus 输出）：
 * 1. sign 返 20 字符字符串（SIGNATURE_LENGTH）
 * 2. sign 对 url / userAgent / timestamp 任一参数敏感
 * 3. sign 是确定性的（同输入 → 同输出）
 * 4. sign 输出只含 base64 字符集
 * 5. 不同 URL 返不同输出（URL 是核心参数）
 *
 * **v0.5.4 placeholder 说明**：
 * - 当前实现是 SHA-256(UA + URL + timestamp) 简化版，**不**等于抖音真 X-Bogus 输出
 * - v0.5.5+ 实装真算法（公开反编译 + 真抖音 web 响应验证）时这些测试**仍然有效**
 *   ——它们验证的是"参数敏感性 + 确定性 + 输出长度"，不依赖具体算法
 * - 真算法实现后，**新加**byte-for-byte 测试用例（用真抖音 web 响应作为 test vector）
 */
class XBogusSignerTest {

    private val signer = XBogusSigner()

    @Test
    fun `sign returns 44-character string`() {
        // v0.5.5: SHA-256 (32 bytes) → RC4 (32 bytes) → custom base64 (44 chars no padding)
        val result = signer.sign(
            url = "https://www.iesdouyin.com/web/api/v2/aweme/iteminfo/?item_ids=12345",
            userAgent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            timestamp = 1700000000L
        )
        assertThat(result.length).isEqualTo(XBogusSigner.SIGNATURE_LENGTH)
        assertThat(result.length).isEqualTo(44)
    }

    @Test
    fun `sign is sensitive to url userAgent and timestamp`() {
        val baseResult = signer.sign(
            url = "https://www.iesdouyin.com/web/api/v2/aweme/iteminfo/?item_ids=12345",
            userAgent = "Mozilla/5.0",
            timestamp = 1700000000L
        )
        val differentUrl = signer.sign(
            url = "https://www.iesdouyin.com/web/api/v2/aweme/iteminfo/?item_ids=99999",
            userAgent = "Mozilla/5.0",
            timestamp = 1700000000L
        )
        val differentUserAgent = signer.sign(
            url = "https://www.iesdouyin.com/web/api/v2/aweme/iteminfo/?item_ids=12345",
            userAgent = "Mozilla/4.0",
            timestamp = 1700000000L
        )
        val differentTimestamp = signer.sign(
            url = "https://www.iesdouyin.com/web/api/v2/aweme/iteminfo/?item_ids=12345",
            userAgent = "Mozilla/5.0",
            timestamp = 1700000001L
        )

        assertThat(differentUrl).isNotEqualTo(baseResult)
        assertThat(differentUserAgent).isNotEqualTo(baseResult)
        assertThat(differentTimestamp).isNotEqualTo(baseResult)
    }

    @Test
    fun `sign is deterministic for same input`() {
        val url = "https://www.iesdouyin.com/web/api/v2/aweme/iteminfo/?item_ids=12345"
        val userAgent = "Mozilla/5.0"
        val timestamp = 1700000000L

        val sig1 = signer.sign(url, userAgent, timestamp)
        val sig2 = signer.sign(url, userAgent, timestamp)
        assertThat(sig1).isEqualTo(sig2)
    }

    @Test
    fun `sign output contains only a_bogus alphabet characters`() {
        // v0.5.5: 用 a_bogus 字母表编码（不是标准 base64）
        val result = signer.sign(
            url = "https://example.com/?a=1&b=2",
            userAgent = "TestAgent",
            timestamp = 1700000000L
        )
        // a_bogus 字母表字符集: Dkdpgh2ZmsQB80/MfvV36XI1R45-WUAlEixNLwoqYTOPuzKFjJnry79HbGcaStCe
        val aBogusAlphabet = "Dkdpgh2ZmsQB80/MfvV36XI1R45-WUAlEixNLwoqYTOPuzKFjJnry79HbGcaStCe"
        for (c in result) {
            assertThat(c in aBogusAlphabet).isTrue()
        }
    }

    @Test
    fun `sign different urls produce different outputs`() {
        val result1 = signer.sign(
            url = "https://www.iesdouyin.com/web/api/v2/aweme/iteminfo/?item_ids=111",
            userAgent = "Mozilla/5.0",
            timestamp = 1700000000L
        )
        val result2 = signer.sign(
            url = "https://www.iesdouyin.com/web/api/v2/aweme/iteminfo/?item_ids=222",
            userAgent = "Mozilla/5.0",
            timestamp = 1700000000L
        )
        assertThat(result1).isNotEqualTo(result2)
    }
}
