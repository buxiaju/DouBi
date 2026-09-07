package com.doubi.android.core.platform.douyin

import com.google.common.truth.Truth.assertThat
import org.junit.Test

/**
 * 阶段 19 v0.5.9：[XBogusEncoding] 单测。
 *
 * **覆盖**（5 例）：
 * 1. `_calculation` 3 字节 → 4 字符（位运算拆 4×6 位）
 * 2. `_calculation` 全 0 字节 → 全 `D`（字母表第 0 个字符）
 * 3. `_calculation` 全 0xFF 字节 → `=`（字母表第 63 个字符）
 * 4. `[A_BOGUS_ALPHABET]` 长度 = 64 字符
 * 5. `[A_BOGUS_ALPHABET]` v0.5.9 修正值与 v0.5.5 错误值**不**同（防回归）
 * 6. `[encodeAll]` 整字节数组按 3 字节一组编码
 * 7. `[encodeAll]` 长度不是 3 的倍数抛 IllegalArgumentException
 */
class XBogusEncodingTest {

    @Test
    fun `calculation takes 3 bytes and returns 4 alphabet characters`() {
        // 24-bit = 0x123456 → 4 段 6-bit = 0x04 / 0x23 / 0x11 / 0x16
        //   0x123456 = 000100 100011 010001 010110
        // 索引到 A_BOGUS_ALPHABET[4] / [35] / [17] / [22]
        // 字母表: Dkdpgh4ZKsQB80/Mfvw36XI1R25-WUAlEi7NLboqYTOPuzmFjJnryx9HVGcaStCe
        //   index 4  = g  (D-k-d-p-**g**...)
        //   index 35 = N  (...Ei**7**N... → 注意是 34='7' 35='N'，不是反过来)
        //   index 17 = v  (...M**f**v w... → 16='f' 17='v')
        //   index 22 = I  (...XI**1**R25 → 21='X' 22='I' 23='1')
        val result = XBogusEncoding.calculation(0x12, 0x34, 0x56)
        assertThat(result).isEqualTo("gNvI")
        // 字符必须从 A_BOGUS_ALPHABET 中
        for (c in result) {
            assertThat(XBogusEncoding.A_BOGUS_ALPHABET.contains(c)).isTrue()
        }
    }

    @Test
    fun `calculation with all zero bytes returns alphabet index 0 character D`() {
        // 0x000000 → 4 段都 0 → 4 个字母表[0] = "DDDD"
        val result = XBogusEncoding.calculation(0x00, 0x00, 0x00)
        assertThat(result).isEqualTo("DDDD")
    }

    @Test
    fun `calculation with all 0xFF bytes returns alphabet index 63 character e`() {
        // 0xFFFFFF → 4 段都 63 → 4 个字母表[63]
        // v0.5.9 字母表索引 63 = 'e'（Python 参考尾 '=' 是反编译多余字符，**不**参与算法）
        val result = XBogusEncoding.calculation(0xFF, 0xFF, 0xFF)
        // 字符必须从 A_BOGUS_ALPHABET 索引 63 拿
        val expectedChar = XBogusEncoding.A_BOGUS_ALPHABET[63]
        assertThat(result).isEqualTo("$expectedChar$expectedChar$expectedChar$expectedChar")
        // 索引 63 必须是 'e'（v0.5.9 修正版）
        assertThat(expectedChar).isEqualTo('e')
    }

    @Test
    fun `A_BOGUS_ALPHABET has 64 characters`() {
        // 标准 base64 字母表 = 64 字符（无 padding）
        assertThat(XBogusEncoding.A_BOGUS_ALPHABET).hasLength(64)
    }

    @Test
    fun `A_BOGUS_ALPHABET v0_5_9 corrected value differs from v0_5_5 wrong value (regression guard)`() {
        // v0.5.5 写错的字母表（多处字符不同）
        val v057BuggyAlphabet =
            "Dkdpgh2ZmsQB80/MfvV36XI1R45-WUAlEixNLwoqYTOPuzKFjJnry79HbGcaStCe"
        // v0.5.9 修正后值（64 字符，trim Python 参考尾 '='）
        val v059CorrectAlphabet = XBogusEncoding.A_BOGUS_ALPHABET
        // **不能**相等——v0.5.5 写错时碰巧能跑通 stub chaos，但真算法下输出全错
        assertThat(v059CorrectAlphabet).isNotEqualTo(v057BuggyAlphabet)
        // 修正值以索引 0 开头 = 'D'，以索引 63 结尾 = 'e'（**不**是 v0.5.5 错误的 '='，也不是 Python 参考尾 '='）
        assertThat(v059CorrectAlphabet[0]).isEqualTo('D')
        assertThat(v059CorrectAlphabet[63]).isEqualTo('e')
    }

    @Test
    fun `encodeAll groups 3 bytes and concatenates 4 chars per group`() {
        // 6 字节 = 2 组 3 字节 → 8 字符
        val bytes = byteArrayOf(0x00, 0x00, 0x00, 0xFF.toByte(), 0xFF.toByte(), 0xFF.toByte())
        val result = XBogusEncoding.encodeAll(bytes)
        // 第 1 组 3 字节 0x00 → 4 个 'D'（索引 0）；第 2 组 3 字节 0xFF → 4 个 'e'（索引 63）
        val char0 = XBogusEncoding.A_BOGUS_ALPHABET[0]  // 'D'
        val char63 = XBogusEncoding.A_BOGUS_ALPHABET[63]  // 'e'
        assertThat(result).isEqualTo("$char0$char0$char0$char0$char63$char63$char63$char63")
    }

    @Test
    fun `encodeAll throws IllegalArgumentException when length is not multiple of 3`() {
        // 4 字节（mod 3 != 0）→ 抛错
        val bytes = byteArrayOf(0x00, 0x00, 0x00, 0x00)
        val ex = runCatching { XBogusEncoding.encodeAll(bytes) }.exceptionOrNull()
        assertThat(ex).isInstanceOf(IllegalArgumentException::class.java)
        assertThat(ex!!.message!!).contains("multiple of 3")
    }
}
