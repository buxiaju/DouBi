package com.doubi.android.core.platform.douyin

import com.google.common.truth.Truth.assertThat
import org.junit.Test

/**
 * 阶段 19 v0.5.9：[XBogusMd5] 单测。
 *
 * **覆盖**（5 例）：
 * 1. `md5StrToArray` 32 字符 hex → 16 字节（验证首个 byte = 0xd4）
 * 2. `md5StrToArray` 长度奇数抛 IllegalArgumentException
 * 3. `md5` 空串 → 标准 MD5 `d41d8cd98f00b204e9800998ecf8427e`
 * 4. `md5` "abc" → 标准 MD5 `900150983cd24fb0d6963f7d28e17f72`
 * 5. `md5Encrypt` 双层 MD5 → 16 字节
 * 6. `toHexString` 16 字节 → 32 字符小写 hex（round-trip）
 */
class XBogusMd5Test {

    @Test
    fun `md5StrToArray parses 32-char hex string to 16 bytes`() {
        // MD5 空串的 hex 表示
        val hex = "d41d8cd98f00b204e9800998ecf8427e"
        val bytes = XBogusMd5.md5StrToArray(hex)
        assertThat(bytes.size).isEqualTo(16)
        // 验证每个 byte（验证前 4 个 + 后 2 个）
        // d4=212, 1d=29, 8c=140, d9=217, ..., 42=66, 7e=126
        assertThat(bytes[0].toInt() and 0xFF).isEqualTo(0xd4)
        assertThat(bytes[1].toInt() and 0xFF).isEqualTo(0x1d)
        assertThat(bytes[2].toInt() and 0xFF).isEqualTo(0x8c)
        assertThat(bytes[3].toInt() and 0xFF).isEqualTo(0xd9)
        assertThat(bytes[14].toInt() and 0xFF).isEqualTo(0x42)
        assertThat(bytes[15].toInt() and 0xFF).isEqualTo(0x7e)
    }

    @Test
    fun `md5StrToArray throws IllegalArgumentException when length is odd`() {
        val ex = runCatching { XBogusMd5.md5StrToArray("d41") }.exceptionOrNull()
        assertThat(ex).isInstanceOf(IllegalArgumentException::class.java)
        assertThat(ex!!.message!!).contains("even")
    }

    @Test
    fun `md5 of empty string matches standard digest d41d8cd98f00b204e9800998ecf8427e`() {
        // 标准 MD5 空串 = "d41d8cd98f00b204e9800998ecf8427e"（RFC 1321 已知值）
        val bytes = XBogusMd5.md5("")
        assertThat(bytes.size).isEqualTo(16)
        assertThat(XBogusMd5.toHexString(bytes)).isEqualTo("d41d8cd98f00b204e9800998ecf8427e")
    }

    @Test
    fun `md5 of abc matches standard digest 900150983cd24fb0d6963f7d28e17f72`() {
        // 标准 MD5 "abc" = "900150983cd24fb0d6963f7d28e17f72"（RFC 1321 已知值）
        val bytes = XBogusMd5.md5("abc")
        assertThat(XBogusMd5.toHexString(bytes)).isEqualTo("900150983cd24fb0d6963f7d28e17f72")
    }

    @Test
    fun `md5Encrypt applies double MD5 to url path and returns 16 bytes`() {
        // 双层 MD5 = MD5(MD5(url) as bytes)
        val result = XBogusMd5.md5Encrypt("https://www.douyin.com/aweme/v1/web/aweme/detail/")
        assertThat(result.size).isEqualTo(16)
        // 验证**不**等于单层 MD5（双层 ≠ 单层）
        val singleLayer = XBogusMd5.md5("https://www.douyin.com/aweme/v1/web/aweme/detail/")
        assertThat(result).isNotEqualTo(singleLayer)
    }

    @Test
    fun `toHexString round-trips bytes to 32-char lowercase hex`() {
        // 已知 MD5 "hello" = "5d41402abc4b2a76b9719d911017c592"
        val original = XBogusMd5.md5("hello")
        val hex = XBogusMd5.toHexString(original)
        assertThat(hex).isEqualTo("5d41402abc4b2a76b9719d911017c592")
        // 验证小写
        assertThat(hex).isEqualTo(hex.lowercase())
        // 验证长度 32
        assertThat(hex).hasLength(32)
    }
}
