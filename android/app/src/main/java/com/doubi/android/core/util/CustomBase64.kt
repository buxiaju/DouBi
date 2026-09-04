package com.doubi.android.core.util

/**
 * 阶段 15 v0.5.5：自定义 Base64 编码。1:1 对拍桌面版 Python `base64` 库（用 `custom_alphabet` 参数）。
 *
 * **背景**：抖音 a_bogus / X-Bogus 算法用**自定义** Base64 字母表（**不**是标准
 * Base64）。公开反编译得到的字母表：
 * ```
 * "Dkdpgh2ZmsQB80/MfvV36XI1R45-WUAlEixNLwoqYTOPuzKFjJnry79HbGcaStCe"
 * ```
 * 长度 64（标准 Base64 也是 64）—— 顺序不同。
 *
 * **算法**（公开反编译）：
 * ```
 * base_str = "Dkdpgh2ZmsQB80/MfvV36XI1R45-WUAlEixNLwoqYTOPuzKFjJnry79HbGcaStCe"
 * and_list = [16515072, 258048, 4032, 63]  # = 0xFC0000, 0x3F000, 0xFC0, 0x3F
 *
 * for i in range(0, len(chaos_str), 3):
 *     num0, num1, num2 = ord(chaos_str[i]), ord(chaos_str[i+1]), ord(chaos_str[i+2])
 *     number = num2 | (num1 << 8) | (num0 << 16)
 *     for j, and_num in enumerate(and_list):
 *         result += base_str[(number & and_num) >> (6 * (3 - j))]
 * ```
 *
 * **v0.5.5 范围**：
 * - 纯算法 `encode(data: ByteArray, alphabet: String): String`
 * - 字母表参数化（**不**写死，方便测试 + 未来 a_bogus 字母表改了只需要换参数）
 * - 单测用合成 test vector 验证
 */
object CustomBase64 {

    /**
     * 自定义 Base64 编码（无 padding）。
     *
     * **跟标准 Base64 的差异**：
     * - 字母表自定义（[a_bogus] 用 `"Dkdpgh2ZmsQB80/MfvV36XI1R45-WUAlEixNLwoqYTOPuzKFjJnry79HbGcaStCe"`）
     * - **不**加 `=` padding（a_bogus 输出不带 padding）
     *
     * @param data 要编码的字节
     * @param alphabet 64 字符的字母表（顺序任意）
     * @return 编码后的字符串（无 padding）
     * @throws IllegalArgumentException 字母表长度 ≠ 64
     */
    fun encode(data: ByteArray, alphabet: String): String {
        require(alphabet.length == 64) {
            "CustomBase64 alphabet must be 64 chars, got ${alphabet.length}"
        }

        if (data.isEmpty()) return ""

        val sb = StringBuilder()
        // and_list = [0xFC0000, 0x3F000, 0xFC0, 0x3F] — 4 段 6-bit 掩码
        val andMasks = intArrayOf(0xFC_0000, 0x03_F000, 0x00_0FC0, 0x00_003F)
        val andShifts = intArrayOf(18, 12, 6, 0)

        var i = 0
        while (i < data.size) {
            val num0 = data[i].toInt() and 0xFF
            val num1 = if (i + 1 < data.size) data[i + 1].toInt() and 0xFF else 0
            val num2 = if (i + 2 < data.size) data[i + 2].toInt() and 0xFF else 0

            // 3 字节 → 4 个 6-bit group
            val number = num0.shl(16) or num1.shl(8) or num2

            for (j in 0..3) {
                val index = (number and andMasks[j]) ushr andShifts[j]
                sb.append(alphabet[index])
            }

            i += 3
        }

        return sb.toString()
    }
}
