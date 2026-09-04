package com.doubi.android.core.sniffer

/**
 * 阶段 12 v0.5.2：[M3u8Parser] 解析 m3u8 playlist body 的结果。
 *
 * 三种返回：
 * - [Variant] master playlist 的第一个 variant 子 m3u8 URL（绝对 URL）
 * - [Segment] media playlist 的第一个 segment URL（.ts / .m4s 等，绝对 URL）
 * - [Passthrough] 解析不出 / 不是合法 m3u8 / 空 body —— 调用方保留原 m3u8 URL
 *
 * **为什么有 Passthrough**：m3u8 v7+ 有 HLS encryption / EXT-X-MAP /
 * EXT-X-PROGRAM-DATE-TIME 等高级特性，v0.5.2 解析不出来时降级保留原 m3u8 URL
 * 让 Engine (yt-dlp) 自己解析。`finalUrl` 始终是非空 string，调用方 [SniffResult.Media.finalUrl]
 * 不用 null-check。
 */
sealed class M3u8Result {
    /** Master playlist 第一个 variant 子 m3u8 URL。 */
    data class Variant(val url: String) : M3u8Result()

    /** Media playlist 第一个 segment URL（.ts / .m4s）。 */
    data class Segment(val url: String) : M3u8Result()

    /** 解析不出 —— 调用方保留原 m3u8 URL。`url` 等于传入 `baseUrl`。 */
    data class Passthrough(val url: String) : M3u8Result()
}
