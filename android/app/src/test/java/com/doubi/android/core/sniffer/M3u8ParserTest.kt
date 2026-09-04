package com.doubi.android.core.sniffer

import com.google.common.truth.Truth.assertThat
import org.junit.Test

/**
 * 阶段 12 v0.5.2：[M3u8Parser] 单测。
 *
 * **覆盖**（8 例）：
 * 1. Master playlist 绝对 URL → first variant 绝对 URL
 * 2. Master playlist 相对 URL → resolved 绝对 URL
 * 3. Media playlist → first .ts segment URL
 * 4. Media playlist .m4s segment → first .m4s URL
 * 5. 空 body → Passthrough（保留 baseUrl）
 * 6. 不以 `#EXTM3U` 开头 → Passthrough
 * 7. Comments-only m3u8（无 segment）→ Passthrough
 * 8. URL 带 query params 保留（相对 URL + query 拼接到 baseUrl 的 query）
 */
class M3u8ParserTest {

    private val parser = M3u8Parser()

    @Test
    fun `master playlist with absolute URLs returns first variant`() {
        val body = """
            #EXTM3U
            #EXT-X-VERSION:3
            #EXT-X-STREAM-INF:BANDWIDTH=2000000,RESOLUTION=1280x720
            https://cdn.example.com/720p.m3u8
            #EXT-X-STREAM-INF:BANDWIDTH=500000,RESOLUTION=640x360
            https://cdn.example.com/360p.m3u8
        """.trimIndent()

        val result = parser.parse(body, "https://example.com/master.m3u8")

        assertThat(result).isInstanceOf(M3u8Result.Variant::class.java)
        assertThat((result as M3u8Result.Variant).url).isEqualTo("https://cdn.example.com/720p.m3u8")
    }

    @Test
    fun `master playlist with relative URLs resolves against baseUrl`() {
        val body = """
            #EXTM3U
            #EXT-X-VERSION:3
            #EXT-X-STREAM-INF:BANDWIDTH=2000000
            720p/index.m3u8
            #EXT-X-STREAM-INF:BANDWIDTH=500000
            360p/index.m3u8
        """.trimIndent()

        val result = parser.parse(body, "https://cdn.example.com/streams/master.m3u8")

        assertThat(result).isInstanceOf(M3u8Result.Variant::class.java)
        assertThat((result as M3u8Result.Variant).url)
            .isEqualTo("https://cdn.example.com/streams/720p/index.m3u8")
    }

    @Test
    fun `media playlist returns first ts segment`() {
        val body = """
            #EXTM3U
            #EXT-X-VERSION:3
            #EXT-X-TARGETDURATION:6
            #EXT-X-MEDIA-SEQUENCE:0
            #EXTINF:6.000,
            segment0.ts
            #EXTINF:6.000,
            segment1.ts
            #EXT-X-ENDLIST
        """.trimIndent()

        val result = parser.parse(body, "https://cdn.example.com/streams/720p/index.m3u8")

        assertThat(result).isInstanceOf(M3u8Result.Segment::class.java)
        assertThat((result as M3u8Result.Segment).url)
            .isEqualTo("https://cdn.example.com/streams/720p/segment0.ts")
    }

    @Test
    fun `media playlist with m4s segments returns first m4s URL`() {
        // fmp4 (fragmented MP4) 模式：segment 是 .m4s 而非 .ts
        val body = """
            #EXTM3U
            #EXT-X-VERSION:6
            #EXT-X-TARGETDURATION:6
            #EXT-X-MAP:URI="init.mp4"
            #EXTINF:6.000,
            segment0.m4s
            #EXTINF:6.000,
            segment1.m4s
        """.trimIndent()

        val result = parser.parse(body, "https://cdn.example.com/streams/720p/index.m3u8")

        assertThat(result).isInstanceOf(M3u8Result.Segment::class.java)
        // EXT-X-MAP（init.mp4）被当 # 注释跳过，segment0.m4s 是第一个非 # 行
        assertThat((result as M3u8Result.Segment).url)
            .isEqualTo("https://cdn.example.com/streams/720p/segment0.m4s")
    }

    @Test
    fun `empty body returns Passthrough with baseUrl`() {
        val result = parser.parse("", "https://cdn.example.com/master.m3u8")

        assertThat(result).isInstanceOf(M3u8Result.Passthrough::class.java)
        assertThat((result as M3u8Result.Passthrough).url)
            .isEqualTo("https://cdn.example.com/master.m3u8")
    }

    @Test
    fun `body without EXTM3U header returns Passthrough`() {
        val body = """
            <html>
            <body>This is an HTML page, not a playlist</body>
            </html>
        """.trimIndent()

        val result = parser.parse(body, "https://example.com/page.html")

        assertThat(result).isInstanceOf(M3u8Result.Passthrough::class.java)
        assertThat((result as M3u8Result.Passthrough).url)
            .isEqualTo("https://example.com/page.html")
    }

    @Test
    fun `comments-only m3u8 returns Passthrough`() {
        val body = """
            #EXTM3U
            #EXT-X-VERSION:3
            #EXT-X-TARGETDURATION:6
        """.trimIndent()
        // 没有 segment 行 —— EXT-X-ENDLIST 也没

        val result = parser.parse(body, "https://cdn.example.com/streams/720p/index.m3u8")

        assertThat(result).isInstanceOf(M3u8Result.Passthrough::class.java)
        assertThat((result as M3u8Result.Passthrough).url)
            .isEqualTo("https://cdn.example.com/streams/720p/index.m3u8")
    }

    @Test
    fun `relative segment URL with query params preserves them`() {
        val body = """
            #EXTM3U
            #EXT-X-VERSION:3
            #EXT-X-TARGETDURATION:6
            #EXTINF:6.000,
            segment0.ts?token=abc&exp=12345
        """.trimIndent()

        val result = parser.parse(body, "https://cdn.example.com/streams/720p/index.m3u8?token=ROOT")

        assertThat(result).isInstanceOf(M3u8Result.Segment::class.java)
        // URI.resolve 行为：相对 URL 整体替换 baseUrl 的 path 部分，保留 baseUrl 的 query？
        // 实际 Java URI.resolve 行为：相对 URL 自带 query → 用自带的；不带 → 用 baseUrl 的
        // 这里 segment 自带 ?token=abc&exp=12345 → 解析后用自带的 query
        val url = (result as M3u8Result.Segment).url
        assertThat(url).startsWith("https://cdn.example.com/streams/720p/segment0.ts")
        assertThat(url).contains("token=abc")
        assertThat(url).contains("exp=12345")
    }
}
