package com.doubi.android.core.platform.douyin

import java.security.MessageDigest

/**
 * 阶段 19 v0.5.9：抖音 X-Bogus `_md5_str_to_array` / `_md5` / `_md5_encrypt` MD5 工具。
 *
 * **v0.5.9 范围**：port Evil0ctal `Douyin_TikTok_Download_API/utils/xbogus.py:XBogus` 的 3 个 MD5 方法。
 *
 * **核心点**：XBogus 算法**不**直接用标准 `bytes(md5_str)` 转换 hex 字符串——
 * 它用 [_HEX_DIGIT_MAP]（0-15 反编译固定值）做转换，
 * 把 32 字符 hex 字符串转 16 个 byte 值（**符号位是 0-15 的 nibble 值**）。
 *
 * **为什么不用标准 hex parse**：
 * - Python `bytes("ab", "utf-8")` 拿 ASCII byte 值 (97, 98) —— **不**是 nibble 值
 * - Python `bytes.fromhex("ab")` 拿 nibble 值 (0xab = 171) —— 但 XBogus 用 nibble 对 (a=10, b=11) 拼成 0xab
 * - 标准 `bytes.fromhex` 是对的，但 `bytes(hex_str, "utf-8")` 错
 * - v0.5.9 抽 [_md5StrToArray] 替代 Python 写法
 *
 * **架构**：
 * - 抽成独立 utility（**不**放 [XBogusSigner] 内）—— 单一职责 + 单元可测
 * - Kotlin 用 [MessageDigest] 跑标准 MD5（Java 自带）
 *
 * **算法骨架**（对照 Python 参考）：
 * ```
 * ua_md5_array = md5StrToArray(md5(base64Encode(rc4(ua, key=0x00_01_0c))))
 * empty_md5_array = md5StrToArray(md5(md5StrToArray("d41d8cd98f00b204e9800998ecf8427e")))
 * url_md5_array = md5Encrypt(url_path)
 * ```
 */
object XBogusMd5 {

    /**
     * ASCII char → 4-bit nibble 映射表。索引 = char.toInt()。
     *
     * 反编译抖音 webmssdk.js 固定值（与 Python `_array` 同源）：
     * - 索引 48 ('0') → 0
     * - 索引 49 ('1') → 1
     * - ... 索引 57 ('9') → 9
     * - 索引 97 ('a') → 10
     * - 索引 98 ('b') → 11
     * - 索引 99 ('c') → 12
     * - 索引 100 ('d') → 13
     * - 索引 101 ('e') → 14
     * - 索引 102 ('f') → 15
     * - 其它 → 0（默认，**不**抛错——Python `_array` 对 invalid 用 `None`，
     *   但 Python `(None << 4) | None` 会抛 TypeError）
     *
     * Kotlin 实现简化：invalid char 返 0（实际算法中**不会**触发——输入是 MD5 hex
     * 字符串，只含 `0-9` 和 `a-f`）。
     *
     * 数组长度 128 = ASCII 范围（避免 char.toInt() >= 128 触发 IndexOutOfBounds）。
     */
    private val HEX_DIGIT_MAP: IntArray = IntArray(128).also { map ->
        // '0'..'9' → 0..9
        for (i in 0..9) {
            map['0'.code + i] = i
        }
        // 'a'..'f' → 10..15
        for (i in 0..5) {
            map['a'.code + i] = 10 + i
        }
        // 其它默认 0（**不**抛错）
    }

    /**
     * 把 32 字符 MD5 hex 字符串转 16 个 nibble-byte 值。
     *
     * 1:1 对拍 Python `_md5_str_to_array(md5_str)`：
     * ```python
     * array = []
     * idx = 0
     * while idx < len(md5_str):
     *     array.append((_array[ord(md5_str[idx])] << 4) | _array[ord(md5_str[idx + 1])])
     *     idx += 2
     * ```
     *
     * **输入约束**：md5Str 必须是**偶数**长度（每 2 字符拼一个 byte）。
     *
     * @param md5Str 32 字符 hex 字符串（如 "d41d8cd98f00b204e9800998ecf8427e"）
     * @return 长度为 `md5Str.length / 2` 的 [ByteArray]，每个值 0-255
     */
    fun md5StrToArray(md5Str: String): ByteArray {
        require(md5Str.length % 2 == 0) {
            "md5Str length must be even, got ${md5Str.length}"
        }
        val result = ByteArray(md5Str.length / 2)
        var i = 0
        while (i < md5Str.length) {
            val high = HEX_DIGIT_MAP[md5Str[i].code]
            val low = HEX_DIGIT_MAP[md5Str[i + 1].code]
            // (high << 4) | low → 0-255 byte
            result[i / 2] = ((high shl 4) or low).toByte()
            i += 2
        }
        return result
    }

    /**
     * 标准 MD5 哈希 → 16 字节数组（**不**是 hex 字符串）。
     *
     * 1:1 对拍 Python `_md5(input_data)`：
     * ```python
     * if isinstance(input_data, str):
     *     data = md5StrToArray(input_data)
     * else:
     *     data = input_data
     * md5_hash = hashlib.md5()
     * md5_hash.update(bytes(data))
     * return md5_hash.hexdigest()
     * ```
     *
     * **关键差异**：Python 返回 hex 字符串，Kotlin 返回 byte 数组。
     * 调用方需要 hex 时自己用 [toHexString]。
     *
     * @param input 标准 MD5 输入（任意长度）
     * @return 16 字节 MD5 哈希
     */
    fun md5(input: ByteArray): ByteArray {
        val digest = MessageDigest.getInstance("MD5")
        return digest.digest(input)
    }

    /**
     * 标准 MD5 哈希 → 16 字节数组（String 输入，自动 UTF-8 编码）。
     *
     * 对拍 Python `md5("some string".encode("utf-8"))`。
     */
    fun md5(input: String): ByteArray = md5(input.toByteArray(Charsets.UTF_8))

    /**
     * 双层 MD5：先 MD5 hex 字符串的 byte 数组，再 MD5 一次。
     *
     * 1:1 对拍 Python `_md5_encrypt(url_path)`：
     * ```python
     * def _md5_encrypt(self, url_path: str) -> List[int]:
     *     hashed = self._md5(self._md5_str_to_array(self._md5(url_path)))
     *     return self._md5_str_to_array(hashed)
     * ```
     *
     * 注意 Python 的 `_md5` 在传入 list[int] 时，先把 list 当 byte 数组 → MD5 → hex 字符串，
     * 第二步 `_md5_str_to_array(hex_str)` 转 byte 数组。这里**统一**返回 byte 数组（不转 hex）。
     *
     * @param urlPath URL 路径（任意字符串）
     * @return 16 字节双层 MD5 哈希
     */
    fun md5Encrypt(urlPath: String): ByteArray {
        // 第一层：MD5(URL) → 16 字节
        val firstLayer = md5(urlPath)
        // 第二层：MD5(firstLayer 作为 byte 数组) → 16 字节
        return md5(firstLayer)
    }

    /**
     * ByteArray 转 32 字符小写 hex 字符串。
     *
     * 1:1 对拍 Python `md5_hash.hexdigest()`。
     *
     * @return 32 字符小写 hex 字符串
     */
    fun toHexString(bytes: ByteArray): String {
        val sb = StringBuilder(bytes.size * 2)
        for (b in bytes) {
            val v = b.toInt() and 0xFF
            sb.append(HEX_CHARS[v ushr 4])
            sb.append(HEX_CHARS[v and 0x0F])
        }
        return sb.toString()
    }

    private val HEX_CHARS = "0123456789abcdef"
}
