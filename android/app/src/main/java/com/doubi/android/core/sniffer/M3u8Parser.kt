package com.doubi.android.core.sniffer

import java.net.URI
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 阶段 12 v0.5.2：m3u8 playlist 内容解析器。
 *
 * **背景**：v0.5.0 阶段 10 的 [WebViewHeadlessSniffer] 拦截到 m3u8 URL 直接返给
 * Engine (yt-dlp)——Engine 自己解析 m3u8 内容（yt-dlp 支持 HLS）。
 *
 * v0.5.2 增强：拦截到 m3u8 URL 后**额外**用 OkHttp 拉 body 解析：
 * - master playlist（`#EXT-X-STREAM-INF`）→ 拿第一个 variant 子 m3u8 URL
 * - media playlist（`.ts` / `.m4s`）→ 拿第一个 segment URL
 *
 * 把 m3u8 URL 进一步解析成 .ts URL 传给 Engine，让 Engine 直接下 .ts，**省一次
 * m3u8 body HTTP round-trip**。v0.5.2 范围只解析一层（master → 第一个 variant .m3u8 URL，
 * 不递归再下 body 解析子 m3u8）；递归留 v0.5.3+。
 *
 * **不支持**（v0.5.2 范围外）：
 * - m3u8 v7+ HLS encryption（`#EXT-X-KEY`）—— 保留原 m3u8 URL 让 Engine 解析
 * - EXT-X-MAP（init segment）—— 第一个非 # 行就是 segment，init 跳过
 * - 递归 master → media（一次只解析一层）
 * - 多 variant 选择（带宽/分辨率）—— v0.5.2 默认拿第一个（通常是最高带宽）
 *
 * **m3u8 格式快速参考**：
 * ```
 * #EXTM3U                                          ← 必须第一行
 * #EXT-X-VERSION:3
 *
 * # master playlist（多码率）                       ← 多个 #EXT-X-STREAM-INF
 * #EXT-X-STREAM-INF:BANDWIDTH=2000000,RESOLUTION=1280x720
 * 720p.m3u8                                        ← 第一个非 # 行 = variant URL
 * #EXT-X-STREAM-INF:BANDWIDTH=500000
 * 360p.m3u8
 *
 * # media playlist（单码率）                        ← 无 #EXT-X-STREAM-INF
 * #EXT-X-TARGETDURATION:6
 * #EXTINF:6.000,
 * segment0.ts                                      ← 第一个非 # 行 = segment URL
 * #EXTINF:6.000,
 * segment1.ts
 * ```
 */
@Singleton
class M3u8Parser @Inject constructor() {

    /**
     * 解析 m3u8 playlist body。
     *
     * @param body m3u8 playlist body（HTTP response text，gzip OkHttp 已自动解压）
     * @param baseUrl m3u8 playlist 自身的 URL——用于解析相对 URL 到绝对 URL
     * @return [M3u8Result.Variant] / [M3u8Result.Segment] / [M3u8Result.Passthrough]
     */
    fun parse(body: String, baseUrl: String): M3u8Result {
        // 空 body / 不以 #EXTM3U 开头 → 不是合法 m3u8
        if (body.isBlank() || !body.trimStart().startsWith(EXTM3U)) {
            return M3u8Result.Passthrough(baseUrl)
        }

        val lines = body.lines()
        val isMaster = lines.any { it.startsWith(EXT_X_STREAM_INF) }

        return if (isMaster) parseMaster(lines, baseUrl) else parseMedia(lines, baseUrl)
    }

    /**
     * v0.5.3 阶段 13 递归解析 master → media。
     *
     * [parse] 只解析一层（master → 第一个 variant m3u8 URL，**不**下 body 解析子 m3u8）。
     * v0.5.3 加 [parseRecursive]：当 [parse] 返 [M3u8Result.Variant] 时，用 [fetchBody]
     * 拉变体子 m3u8 body 再调 [parse]，直到返 [M3u8Result.Segment] /
     * [M3u8Result.Passthrough] / 达到 [MAX_RECURSION_DEPTH] 上限。
     *
     * **典型场景**：
     * ```
     * master.m3u8        #EXT-X-STREAM-INF BANDWIDTH=2000000 → 720p/index.m3u8
     *                      ↓ fetchBody("...720p/index.m3u8")
     *                      ↓ body
     *                      ↓ parse 返 Segment → segment0.ts
     * ```
     *
     * **降级语义**（fail-safe，跟 [parse] 一致）：
     * - [fetchBody] 返 null（网络失败 / 404）→ 保留当前 variant URL，**不**递归
     * - 达到 [MAX_RECURSION_DEPTH]（5 层）→ 返 [M3u8Result.Passthrough]，保留当前 URL
     * - 循环引用（master1 → master2 → master1）→ 达到 depth 上限自然终止
     *
     * **fetchBody 契约**：suspend 函数，传入 URL 返 body 字符串（或 null）。调用方
     * （[WebViewHeadlessSniffer]）用 OkHttp 实现（`withContext(Dispatchers.IO)` 跑 GET）；
     * 测试用 stub 函数（需 `runBlocking` 包）。
     */
    suspend fun parseRecursive(
        body: String,
        baseUrl: String,
        fetchBody: suspend (String) -> String?,
    ): M3u8Result {
        var currentBody = body
        var currentUrl = baseUrl

        repeat(MAX_RECURSION_DEPTH) {
            when (val parsed = parse(currentBody, currentUrl)) {
                is M3u8Result.Segment -> return parsed
                is M3u8Result.Passthrough -> return parsed
                is M3u8Result.Variant -> {
                    val nextBody = fetchBody(parsed.url) ?: return parsed
                    currentBody = nextBody
                    currentUrl = parsed.url
                }
            }
        }

        // depth 耗尽 —— 防止循环引用 / 异常深度的 master
        return M3u8Result.Passthrough(currentUrl)
    }

    /**
     * 解析 master playlist：找第一个 `#EXT-X-STREAM-INF` 后面跟着的非 # 行（variant URL）。
     */
    private fun parseMaster(lines: List<String>, baseUrl: String): M3u8Result {
        var i = 0
        while (i < lines.size - 1) {
            if (lines[i].startsWith(EXT_X_STREAM_INF)) {
                val candidate = lines[i + 1].trim()
                if (candidate.isNotEmpty() && !candidate.startsWith("#")) {
                    return M3u8Result.Variant(resolveUrl(candidate, baseUrl))
                }
            }
            i++
        }
        return M3u8Result.Passthrough(baseUrl)
    }

    /**
     * 解析 media playlist：第一个非 # 非空行 = 第一个 segment URL。
     */
    private fun parseMedia(lines: List<String>, baseUrl: String): M3u8Result {
        for (line in lines) {
            val trimmed = line.trim()
            if (trimmed.isEmpty() || trimmed.startsWith("#")) continue
            return M3u8Result.Segment(resolveUrl(trimmed, baseUrl))
        }
        return M3u8Result.Passthrough(baseUrl)
    }

    /**
     * 解析相对 URL 到绝对 URL。绝对 URL 原样返回；解析失败时返回原 URL（不抛异常）。
     */
    private fun resolveUrl(url: String, baseUrl: String): String = try {
        URI(baseUrl).resolve(url).toString()
    } catch (e: Exception) {
        url
    }

    private companion object {
        const val EXTM3U = "#EXTM3U"
        const val EXT_X_STREAM_INF = "#EXT-X-STREAM-INF"

        /**
         * v0.5.3 阶段 13：递归解析 master → media 的最大深度。
         *
         * 真实场景下 master → media 是 **2 层**（master.m3u8 → variant.m3u8 → media.m3u8
         * → .ts）；少数场景多层（intermediate master + variant list）。5 层足够覆盖
         * 99%+ 真实情况，也防循环引用死循环。
         */
        const val MAX_RECURSION_DEPTH = 5
    }
}
