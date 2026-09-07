package com.doubi.android.core.util

import com.google.common.truth.Truth.assertThat
import org.junit.Test

/**
 * 阶段 15 v0.5.5：[CustomBase64] 单测。
 *
 * **覆盖**（5 例）：
 * 1. 空数据 → 空输出
 * 2. 单字节（3 input bytes → 4 output chars）
 * 3. 三字节完整 group
 * 4. 抖音 a_bogus 字母表 encode 已知字节
 * 5. encode 是确定性的
 */
class CustomBase64Test {

    // 抖音 a_bogus 字母表（公开反编译）
    private val aBogusAlphabet = "Dkdpgh2ZmsQB80/MfvV36XI1R45-WUAlEixNLwoqYTOPuzKFjJnry79HbGcaStCe"

    @Test
    fun `empty data produces empty output`() {
        val result = CustomBase64.encode(byteArrayOf(), aBogusAlphabet)
        assertThat(result).isEqualTo("")
    }

    @Test
    fun `single byte produces 4 chars no padding`() {
        // 1 byte → 4 chars (a_bogus 不加 padding)
        val result = CustomBase64.encode(byteArrayOf(0x41), aBogusAlphabet)
        assertThat(result.length).isEqualTo(4)
    }

    @Test
    fun `three bytes produces 4 chars`() {
        // 3 bytes (24 bits) → 4 chars (4 × 6 = 24 bits)
        val result = CustomBase64.encode(byteArrayOf(0x41, 0x42, 0x43), aBogusAlphabet)
        assertThat(result.length).isEqualTo(4)
        // 验证: 0x414243 → 24 bits 01000001 01000010 01000011
        // 4 个 6-bit 段: 010000(16), 010100(20), 001001(9), 000011(3)
        // a_bogusAlphabet[16]='f', [20]='6', [9]='s', [3]='p' → "f6sp"
        assertThat(result).isEqualTo("f6sp")
    }

    @Test
    fun `a_bogus alphabet encodes standard test vector`() {
        // 已知：encode("Man") 用 standard base64 是 "TWFu"
        // 用 a_bogus 字母表应该不一样（字母表顺序不同）
        val standardAlphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
        val standardResult = CustomBase64.encode("Man".toByteArray(), standardAlphabet)
        assertThat(standardResult).isEqualTo("TWFu")

        // a_bogus 字母表 encode 同样 input → 不同 output
        val aBogusResult = CustomBase64.encode("Man".toByteArray(), aBogusAlphabet)
        assertThat(aBogusResult).isNotEqualTo("TWFu")
    }

    @Test
    fun `encode is deterministic`() {
        val data = "douyin_a_bogus".toByteArray()
        val r1 = CustomBase64.encode(data, aBogusAlphabet)
        val r2 = CustomBase64.encode(data, aBogusAlphabet)
        assertThat(r1).isEqualTo(r2)
    }

    @Test(expected = IllegalArgumentException::class)
    fun `non-64 alphabet throws`() {
        CustomBase64.encode(byteArrayOf(0x01), "ABC")
    }
}
