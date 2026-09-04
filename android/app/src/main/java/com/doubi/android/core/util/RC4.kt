package com.doubi.android.core.util

/**
 * 阶段 15 v0.5.5：RC4 流密码。1:1 对拍桌面版 Python `arc4` 算法（用 `pycryptodome` 库
 * 或者手写 RC4 循环）。
 *
 * **背景**：抖音 a_bogus / X-Bogus 算法中两次用到 RC4：
 * 1. 用 `key = [131]` 对 `chaos_str` 加密 → `chaos_encrypted`
 * 2. 用 RC4-XOR 把 ua / params / timestamp 转字节数组
 *
 * **算法**（公开反编译）：
 * ```
 * 初始化 S-box：
 *   e = list(range(256))
 *   for r in range(256):
 *     d = (d + e[r] + a[r % len(a)]) % 256  # a 是 key 字节
 *     e[r], e[d] = e[d], e[r]
 *
 * PRGA（伪随机生成 + XOR）：
 *   d = 0
 *   for o in input_bytes:
 *     n += 1
 *     d = (d + e[n % 256]) % 256
 *     e[n], e[d] = e[d], e[n]
 *     t += chr(ord(o) ^ e[(e[n] + e[d]) % 256])
 * ```
 *
 * **v0.5.5 范围**：
 * - 纯算法 `encrypt(data, key): ByteArray` —— 字节数组进出（无字符串编码）
 * - 单测用合成 test vector 验证（公开 RC4 已知 answer）
 * - 字节序、字节数组长度跟公开 Python 实现 byte-for-byte 一致
 */
object RC4 {

    /**
     * RC4 加密 / 解密（同一函数 —— RC4 是对称密码，加密解密都用 `encrypt`）。
     *
     * @param data 要加密 / 解密的字节
     * @param key RC4 key（字节数组，1-256 字节；超过 256 字节取前 256）
     * @return 加密 / 解密后的字节
     */
    fun encrypt(data: ByteArray, key: ByteArray): ByteArray {
        require(key.isNotEmpty()) { "RC4 key must not be empty" }
        require(key.size <= 256) { "RC4 key length must be <= 256" }

        // 1. KSA（Key Scheduling Algorithm）：初始化 S-box
        val e = IntArray(256) { it }
        var d = 0
        for (r in 0 until 256) {
            d = (d + e[r] + key[r % key.size].toInt() and 0xFF) % 256
            val tmp = e[r]
            e[r] = e[d]
            e[d] = tmp
        }

        // 2. PRGA（Pseudo-Random Generation Algorithm）：生成 keystream + XOR
        val output = ByteArray(data.size)
        var n = 0
        d = 0
        for (i in data.indices) {
            n = (n + 1) % 256
            d = (d + e[n]) % 256
            val tmp = e[n]
            e[n] = e[d]
            e[d] = tmp
            val keystreamByte = e[(e[n] + e[d]) % 256]
            output[i] = ((data[i].toInt() and 0xFF) xor keystreamByte).toByte()
        }
        return output
    }
}
