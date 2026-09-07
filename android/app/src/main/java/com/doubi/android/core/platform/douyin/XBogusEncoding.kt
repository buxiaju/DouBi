package com.doubi.android.core.platform.douyin

/**
 * 阶段 19 v0.5.9：抖音 X-Bogus `_calculation` 编码工具。
 *
 * **v0.5.9 范围**：port Evil0ctal `Douyin_TikTok_Download_API/utils/xbogus.py:XBogus._calculation`
 * —— 3 字节 → 4 字符的标准 base64 算法（24 位拆 4×6 位索引 64 字符字母表）。
 *
 * **v0.5.5 阶段的 bug**（[XBogusSigner.A_BOGUS_ALPHABET] 写错）：
 * - v0.5.5 写的是 `Dkdpgh2ZmsQB80/MfvV36XI1R45-WUAlEixNLwoqYTOPuzKFjJnry79HbGcaStCe`
 *   —— 跟参考实现对比多处字符不同（`2 vs 4` / `Z vs K` / `m vs s` 等）
 * - **v0.5.9 修**：用参考实现的值 `Dkdpgh4ZKsQB80/Mfvw36XI1R25-WUAlEi7NLboqYTOPuzmFjJnryx9HVGcaStCe=`
 *
 * **架构**：
 * - 抽成独立 utility（**不**放 [XBogusSigner] 内）—— 单一职责 + 单元可测
 * - [_calculation] 是标准 base64 编码（3 byte → 4 char），**唯一**区别是字母表
 *   —— 标准 base64 用 `A-Za-z0-9+/=`，X-Bogus 用反编译的 64 字符字母表
 *
 * **位运算展开**（24 位拆 4 个 6 位）：
 * - 16515072 = 0xFC0000 (top 6 bits)
 * - 258048 = 0x3F000   (next 6 bits)
 * - 4032 = 0xFC0        (next 6 bits)
 * - 63 = 0x3F            (bottom 6 bits)
 */
object XBogusEncoding {

    /**
     * 抖音 X-Bogus 算法的 64 字符字母表（**v0.5.9 修正版**）。
     *
     * **v0.5.5 错误值**：`Dkdpgh2ZmsQB80/MfvV36XI1R45-WUAlEixNLwoqYTOPuzKFjJnry79HbGcaStCe`
     * （v0.5.5 阶段 15 写时跟参考实现对比字符有偏差——v0.5.9 改正）
     *
     * **v0.5.9 正确值**（反编译抖音 webmssdk.js 前 64 字符）：
     * `Dkdpgh4ZKsQB80/Mfvw36XI1R25-WUAlEi7NLboqYTOPuzmFjJnryx9HVGcaStCe`
     *
     * **v0.5.9 trim 说明**：Python 参考实现 `_character` 是 65 字符（含尾 `=`），
     * 但 `_calculation` 只用 0-63 索引——尾 `=` 是反编译多余字符，**不**参与算法。
     * Android 端按 64 字符存，索引 0='D' / 索引 63='C'。
     */
    const val A_BOGUS_ALPHABET =
        "Dkdpgh4ZKsQB80/Mfvw36XI1R25-WUAlEi7NLboqYTOPuzmFjJnryx9HVGcaStCe"

    /**
     * 24 位拆 4×6 位（标准 base64 编码算法）→ 返回 4 字符。
     *
     * @param a1 第一个字节（高 8 位）
     * @param a2 第二个字节（中 8 位）
     * @param a3 第三个字节（低 8 位）
     * @return 4 字符（X-Bogus 字母表的索引结果）
     */
    fun calculation(a1: Int, a2: Int, a3: Int): String {
        // 24 位 = (a1 << 16) | (a2 << 8) | a3
        val x3 = ((a1 and 0xFF) shl 16) or ((a2 and 0xFF) shl 8) or (a3 and 0xFF)
        // 拆 4 个 6 位索引字母表
        val c0 = A_BOGUS_ALPHABET[(x3 and 0xFC0000) shr 18]
        val c1 = A_BOGUS_ALPHABET[(x3 and 0x3F000) shr 12]
        val c2 = A_BOGUS_ALPHABET[(x3 and 0xFC0) shr 6]
        val c3 = A_BOGUS_ALPHABET[x3 and 0x3F]
        return "$c0$c1$c2$c3"
    }

    /**
     * 把整个字节数组按 3 字节一组切片，调用 [calculation] 拼成完整 X-Bogus 字符串。
     *
     * **v0.5.9 限制**：byte 数必须是 3 的倍数（X-Bogus 算法的输入是 `chr(2) + chr(255) + garbled`，
     * 长度固定 19+2=21 字节的倍数）。v0.5.9 用在 [XBogusSigner.build] 内部，输入保证对齐，
     * 不会触发 mod 3 != 0 的边界。
     */
    fun encodeAll(bytes: ByteArray): String {
        require(bytes.size % 3 == 0) {
            "byte array length must be multiple of 3, got ${bytes.size}"
        }
        val sb = StringBuilder()
        var i = 0
        while (i < bytes.size) {
            // 显式 toInt() 防 byte→int 符号扩展
            sb.append(
                calculation(
                    bytes[i].toInt() and 0xFF,
                    bytes[i + 1].toInt() and 0xFF,
                    bytes[i + 2].toInt() and 0xFF,
                ),
            )
            i += 3
        }
        return sb.toString()
    }
}
