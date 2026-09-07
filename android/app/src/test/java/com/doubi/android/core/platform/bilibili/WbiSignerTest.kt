package com.doubi.android.core.platform.bilibili

import com.google.common.truth.Truth.assertThat
import org.junit.Test

/**
 * 阶段 14 v0.5.4：[WbiSigner] 单测。
 *
 * **覆盖**（6 例）：
 * 1. extractMixinKey 返 32 字符
 * 2. extractMixinKey 对相同输入返相同输出（确定性）
 * 3. extractMixinKey 输入过短抛 IllegalArgumentException
 * 4. sign 返 32 字符 MD5 hex
 * 5. sign 对 wts / mixinKey / query 任一参数敏感（不同输入 → 不同输出）
 * 6. sign 是确定性的（同输入 → 同输出）
 *
 * **测试限制**：v0.5.4 没有真 B 站 nav 响应作为 test vector，**不**验证 byte-for-byte
 * 输出。算法结构（字符数、表替换、MD5 长度、确定性、参数敏感性）通过合成输入验证。
 * v0.5.5+ API 集成时用真 B 站 nav 响应验证 byte-for-byte。
 */
class WbiSignerTest {

    private val signer = WbiSigner()

    // 60 字符合成的 img_url + sub_url query 段，过滤 !'()* 后 59 字符足够走表
    // 真 B 站 nav 接口返的 img_url / sub_url 形如 `https://i0.hdslb.com/bfs/wbi/{hash}.png?{query}`
    // 这里合成 30 字符 query x 2 = 60 字符（无 !'()* 特殊字符）
    private val imgUrl = "https://i0.hdslb.com/bfs/wbi/abc123.png?012345678901234567890123456789"
    private val subUrl = "https://i0.hdslb.com/bfs/wbi/def456.png?abcdefghijabcdefghijabcdefghij"

    @Test
    fun `extractMixinKey returns 32-character string`() {
        val mixinKey = signer.extractMixinKey(imgUrl, subUrl)
        assertThat(mixinKey.length).isEqualTo(32)
    }

    @Test
    fun `extractMixinKey is deterministic for same input`() {
        val key1 = signer.extractMixinKey(imgUrl, subUrl)
        val key2 = signer.extractMixinKey(imgUrl, subUrl)
        assertThat(key1).isEqualTo(key2)
    }

    @Test
    fun `extractMixinKey throws when filtered input is too short`() {
        // img_url + sub_url query 段过滤 !'()* 后 < 59 字符
        val shortImg = "https://example.com/?abc"
        val shortSub = "https://example.com/?xyz"
        val exception = runCatching { signer.extractMixinKey(shortImg, shortSub) }.exceptionOrNull()
        assertThat(exception).isInstanceOf(IllegalArgumentException::class.java)
    }

    @Test
    fun `sign returns 32-character MD5 hex string`() {
        val query = mapOf("bvid" to "BV1xx411c7mD")
        val mixinKey = signer.extractMixinKey(imgUrl, subUrl)
        val wts = 1700000000L
        val signature = signer.sign(query, mixinKey, wts)
        assertThat(signature.length).isEqualTo(32)
        // MD5 hex 只含 0-9 a-f
        assertThat(signature).matches("^[0-9a-f]{32}$")
    }

    @Test
    fun `sign is sensitive to wts mixinKey and query`() {
        val query = mapOf("bvid" to "BV1xx411c7mD")
        val mixinKey = signer.extractMixinKey(imgUrl, subUrl)
        val baseWts = 1700000000L

        val baseSignature = signer.sign(query, mixinKey, baseWts)
        val differentWts = signer.sign(query, mixinKey, baseWts + 1)
        val differentMixKey = signer.sign(query, "X".repeat(32), baseWts)
        val differentQuery = signer.sign(
            query + ("aid" to "12345"),
            mixinKey,
            baseWts
        )

        assertThat(differentWts).isNotEqualTo(baseSignature)
        assertThat(differentMixKey).isNotEqualTo(baseSignature)
        assertThat(differentQuery).isNotEqualTo(baseSignature)
    }

    @Test
    fun `sign is deterministic for same input`() {
        val query = mapOf("bvid" to "BV1xx411c7mD", "aid" to "12345")
        val mixinKey = signer.extractMixinKey(imgUrl, subUrl)
        val wts = 1700000000L

        val sig1 = signer.sign(query, mixinKey, wts)
        val sig2 = signer.sign(query, mixinKey, wts)
        assertThat(sig1).isEqualTo(sig2)
    }
}
