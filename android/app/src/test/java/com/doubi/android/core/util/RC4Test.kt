package com.doubi.android.core.util

import com.google.common.truth.Truth.assertThat
import org.junit.Test

/**
 * 阶段 15 v0.5.5：[RC4] 单测。
 *
 * **覆盖**（5 例）：
 * 1. 空数据 → 空输出
 * 2. 单字节 key + 单字节 data
 * 3. 标准 test vector（RFC 6228 / "Key" → "BBF316E8D940AF0AD3")
 * 4. 抖音 a_bogus key=[131] 加密
 * 5. 加密解密 roundtrip（同函数）
 */
class RC4Test {

    @Test
    fun `empty data produces empty output`() {
        val result = RC4.encrypt(byteArrayOf(), byteArrayOf(1, 2, 3))
        assertThat(result.size).isEqualTo(0)
    }

    @Test
    fun `single byte key with single byte data produces non-zero output`() {
        val result = RC4.encrypt(byteArrayOf(0x41), byteArrayOf(0x42))
        // 不直接断言具体字节值（KSA 后 S-box 是 shuffle 过的）——只验证：
        // 1. 输出非 0（确实有 XOR 加密）
        // 2. 长度 = 1
        assertThat(result.size).isEqualTo(1)
        assertThat(result[0].toInt() and 0xFF).isNotEqualTo(0x41)
    }

    @Test
    fun `RC4 with Key and Plaintext produces known ciphertext`() {
        // 公开 RC4 test vector：key="Key", plaintext="Plaintext"
        // expected ciphertext = "BBF316E8D940AF0AD3" (hex)
        val key = "Key".toByteArray()
        val data = "Plaintext".toByteArray()
        val expected = byteArrayOf(
            0xBB.toByte(), 0xF3.toByte(), 0x16.toByte(), 0xE8.toByte(),
            0xD9.toByte(), 0x40.toByte(), 0xAF.toByte(), 0x0A.toByte(),
            0xD3.toByte()
        )
        val result = RC4.encrypt(data, key)
        assertThat(result.toList()).isEqualTo(expected.toList())
    }

    @Test
    fun `RC4 with a_bogus key 131 encrypts 抖音 chaos string`() {
        // 抖音 a_bogus 用 RC4 with key=[131] 加密 chaos_str
        // 这例只验证算法可运行 + 输出非空 + 确定性
        val key = byteArrayOf(131.toByte())
        val data = "douyin_a_bogus_test".toByteArray()
        val result = RC4.encrypt(data, key)
        // 同一输入 → 同一输出
        val result2 = RC4.encrypt(data, key)
        assertThat(result).isEqualTo(result2)
        // 输出非空
        assertThat(result.size).isEqualTo(data.size)
    }

    @Test
    fun `RC4 encrypt decrypt roundtrip using same function`() {
        // RC4 是对称密码：encrypt(encrypt(x)) = x
        val key = "SecretKey".toByteArray()
        val original = "Hello DouBi Android!".toByteArray()
        val encrypted = RC4.encrypt(original, key)
        val decrypted = RC4.encrypt(encrypted, key)
        assertThat(decrypted.toList()).isEqualTo(original.toList())
    }
}
