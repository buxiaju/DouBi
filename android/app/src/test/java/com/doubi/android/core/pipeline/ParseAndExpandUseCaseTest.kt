package com.doubi.android.core.pipeline

import com.doubi.android.core.model.Author
import com.doubi.android.core.model.MediaFormat
import com.doubi.android.core.model.MediaItem
import com.doubi.android.core.model.MediaType
import com.doubi.android.core.model.Platform
import com.doubi.android.core.sniffer.SniffResult
import com.doubi.android.core.sniffer.Sniffer
import com.doubi.android.engine.ytdlp.YtDlpEngine
import com.doubi.android.engine.ytdlp.YtDlpEngine.ProbeResult
import com.google.common.truth.Truth.assertThat
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.mockk
import io.mockk.slot
import kotlinx.coroutines.test.runTest
import org.junit.Test

/**
 * ParseAndExpandUseCase 单测。`YtDlpEngine` 用 mockk 隔离 native 调用。
 *
 * 覆盖：
 * - YouTube 三种形态（普通 / Shorts / Live）→ Youtube 分支
 * - YouTube 频道 → Unsupported
 * - 通用直链（m3u8/mp4）→ DirectLink 分支
 * - 非 http(s) URL → Unsupported
 * - 空 URL → Unsupported
 * - 嗅探失败 → 兜底 DirectLink
 */
class ParseAndExpandUseCaseTest {

    private val engine: YtDlpEngine = mockk()
    // v0.4.0 新增：Sniffer 注入。mockk(relaxed = false) 显式 stub 避免 v0.2.2 阶段 6
    // 修过的 "relaxed 模式 every 块被忽略" 的坑。
    private val sniffer: Sniffer = mockk()
    private val useCase = ParseAndExpandUseCase(engine, sniffer)

    // ---- YouTube ----

    @Test
    fun `YouTube watch URL goes to Youtube branch with watch normalized`() = runTest {
        val sample = sampleItem("Sample Title", platform = Platform.YOUTUBE, sourceUrl = "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        val formats = listOf(
            formatOf("137", height = 1080, ext = "mp4"),
            formatOf("22", height = 720, ext = "mp4"),
        )
        coEvery { engine.probeWithFormats("https://www.youtube.com/watch?v=dQw4w9WgXcQ") } returns
            ProbeResult(sample, formats)

        val r = useCase("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        assertThat(r).isInstanceOf(ParseResult.Youtube::class.java)
        val y = r as ParseResult.Youtube
        assertThat(y.item.title).isEqualTo("Sample Title")
        assertThat(y.item.sourceUrl).isEqualTo("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        assertThat(y.formats).hasSize(2)
    }

    @Test
    fun `YouTube Shorts URL is normalized to watch URL in sourceUrl`() = runTest {
        val sample = sampleItem("Shorts", platform = Platform.YOUTUBE, sourceUrl = "https://www.youtube.com/shorts/dQw4w9WgXcQ")
        coEvery { engine.probeWithFormats("https://www.youtube.com/watch?v=dQw4w9WgXcQ") } returns
            ProbeResult(sample, listOf(formatOf("18", height = 360)))

        val r = useCase("https://www.youtube.com/shorts/dQw4w9WgXcQ")
        assertThat(r).isInstanceOf(ParseResult.Youtube::class.java)
        val y = r as ParseResult.Youtube
        // 归一化后 sourceUrl 一定是 watch 形态
        assertThat(y.item.sourceUrl).isEqualTo("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        // itemId 用原始 URL 分类的 ID（保持 11 字符）
        assertThat(y.item.itemId).isEqualTo("dQw4w9WgXcQ")
    }

    @Test
    fun `YouTube live URL is normalized to watch`() = runTest {
        val sample = sampleItem("Live", platform = Platform.YOUTUBE, sourceUrl = "https://www.youtube.com/live/dQw4w9WgXcQ")
        coEvery { engine.probeWithFormats("https://www.youtube.com/watch?v=dQw4w9WgXcQ") } returns
            ProbeResult(sample, listOf(formatOf("96", height = 720)))

        val r = useCase("https://www.youtube.com/live/dQw4w9WgXcQ")
        assertThat(r).isInstanceOf(ParseResult.Youtube::class.java)
        assertThat((r as ParseResult.Youtube).item.sourceUrl).isEqualTo("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    }

    @Test
    fun `YouTube channel URL returns Unsupported without calling engine`() = runTest {
        // 频道 / 播放列表不调 engine，直接拒
        val r = useCase("https://www.youtube.com/@LinusTechTips")
        assertThat(r).isInstanceOf(ParseResult.Unsupported::class.java)
        assertThat((r as ParseResult.Unsupported).reason).contains("不支持")
    }

    @Test
    fun `YouTube playlist URL returns Unsupported`() = runTest {
        val r = useCase("https://www.youtube.com/playlist?list=PL123abc")
        assertThat(r).isInstanceOf(ParseResult.Unsupported::class.java)
    }

    // ---- 通用直链 ----

    @Test
    fun `direct m3u8 URL goes to DirectLink branch`() = runTest {
        val sample = sampleItem(
            title = "https://example.com/stream.m3u8",
            platform = Platform.GENERIC,
            sourceUrl = "https://example.com/stream.m3u8",
        )
        val formats = listOf(formatOf("best", height = 1080, ext = "mp4"))
        coEvery { engine.probeWithFormats("https://example.com/stream.m3u8") } returns
            ProbeResult(sample, formats)
        coEvery { sniffer.sniff("https://example.com/stream.m3u8") } returns
            SniffResult.Media(
                contentType = "application/vnd.apple.mpegurl",
                finalUrl = "https://example.com/stream.m3u8",
                contentLength = 1234L,
                isHls = true,
            )

        val r = useCase("https://example.com/stream.m3u8")
        assertThat(r).isInstanceOf(ParseResult.DirectLink::class.java)
        val d = r as ParseResult.DirectLink
        assertThat(d.item.platform).isEqualTo(Platform.GENERIC)
        assertThat(d.format).isNotNull()
    }

    @Test
    fun `direct mp4 URL with no formats falls back to DirectLink with null format`() = runTest {
        // 直链嗅探成功（sniffer 识别为 mp4）→ item 是 fallback，formats 是空
        val fallback = sampleItem(
            title = "https://example.com/video.mp4",  // 兜底：title == url
            platform = Platform.GENERIC,
            sourceUrl = "https://example.com/video.mp4",
        )
        coEvery { engine.probeWithFormats("https://example.com/video.mp4") } returns
            ProbeResult(fallback, emptyList())
        coEvery { sniffer.sniff("https://example.com/video.mp4") } returns
            SniffResult.Media(
                contentType = "video/mp4",
                finalUrl = "https://example.com/video.mp4",
                contentLength = null,
            )

        val r = useCase("https://example.com/video.mp4")
        assertThat(r).isInstanceOf(ParseResult.DirectLink::class.java)
        assertThat((r as ParseResult.DirectLink).format).isNull()
    }

    @Test
    fun `direct URL with audio-only formats picks video preferred`() = runTest {
        // formats 全是 audio-only，应该用第一个（audio-only 兜底）
        val sample = sampleItem("Title", platform = Platform.GENERIC, sourceUrl = "https://example.com/stream")
        val audioOnly = listOf(
            formatOf("140", height = null, ext = "m4a", isAudioOnly = true),
            formatOf("141", height = null, ext = "m4a", isAudioOnly = true),
        )
        coEvery { engine.probeWithFormats("https://example.com/stream") } returns
            ProbeResult(sample, audioOnly)
        coEvery { sniffer.sniff("https://example.com/stream") } returns
            SniffResult.Media(
                contentType = "video/mp4",
                finalUrl = "https://example.com/stream",
                contentLength = null,
            )

        val r = useCase("https://example.com/stream")
        assertThat(r).isInstanceOf(ParseResult.DirectLink::class.java)
        val d = r as ParseResult.DirectLink
        // DirectLink 在 use case 内 firstOrNull{!isAudioOnly} ?: firstOrNull()——audio-only 全是
        // 兜底到第一个
        assertThat(d.format?.formatId).isEqualTo("140")
    }

    @Test
    fun `direct URL with mixed formats picks first non-audio`() = runTest {
        val sample = sampleItem("Title", platform = Platform.GENERIC, sourceUrl = "https://example.com/stream")
        val mixed = listOf(
            formatOf("140", height = null, ext = "m4a", isAudioOnly = true),
            formatOf("137", height = 1080, ext = "mp4"),
            formatOf("22", height = 720, ext = "mp4"),
        )
        coEvery { engine.probeWithFormats("https://example.com/stream") } returns
            ProbeResult(sample, mixed)
        coEvery { sniffer.sniff("https://example.com/stream") } returns
            SniffResult.Media(
                contentType = "video/mp4",
                finalUrl = "https://example.com/stream",
                contentLength = null,
            )

        val r = useCase("https://example.com/stream")
        val d = r as ParseResult.DirectLink
        assertThat(d.format?.formatId).isEqualTo("137")
    }

    @Test
    fun `fallback direct link uses URL hashCode as itemId when probe returns URL as title`() = runTest {
        // 嗅探成功（mp4）→ item.title == url（fallbackMediaItem 的行为）
        val fallback = sampleItem(
            title = "https://example.com/video.mp4",
            platform = Platform.GENERIC,
            sourceUrl = "https://example.com/video.mp4",
            itemId = "https://example.com/video.mp4".hashCode().toString(),
        )
        coEvery { engine.probeWithFormats("https://example.com/video.mp4") } returns
            ProbeResult(fallback, emptyList())
        coEvery { sniffer.sniff("https://example.com/video.mp4") } returns
            SniffResult.Media(
                contentType = "video/mp4",
                finalUrl = "https://example.com/video.mp4",
                contentLength = null,
            )

        val r = useCase("https://example.com/video.mp4")
        val d = r as ParseResult.DirectLink
        // 兜底分支：itemId 是 url hashCode
        assertThat(d.item.itemId).isEqualTo("https://example.com/video.mp4".hashCode().toString())
    }

    // ---- v0.4.0 Sniffer 行为 ----

    @Test
    fun `sniffer NotMedia (HTML page) returns Unsupported without yt-dlp fallback`() = runTest {
        // Sniffer 明确说不是 media（HTML 页面）→ 直接 Unsupported，不调 yt-dlp
        coEvery { sniffer.sniff("https://example.com/page.html") } returns
            SniffResult.NotMedia(
                statusCode = 200,
                contentType = "text/html",
                reason = "HEAD Content-Type is not media: text/html",
            )

        val r = useCase("https://example.com/page.html")
        assertThat(r).isInstanceOf(ParseResult.Unsupported::class.java)
        val u = r as ParseResult.Unsupported
        assertThat(u.reason).contains("text/html")
        // 不应该调 yt-dlp
        coVerify(exactly = 0) { engine.probeWithFormats(any()) }
    }

    @Test
    fun `sniffer Error (network failure) falls back to yt-dlp probe`() = runTest {
        // Sniffer 网络错误（DNS / SSL / 超时）→ 降级让 yt-dlp 自己嗅探
        coEvery { sniffer.sniff("https://example.com/stream.m3u8") } returns
            SniffResult.Error("DNS 解析失败", cause = null)
        val sample = sampleItem(
            title = "https://example.com/stream.m3u8",
            platform = Platform.GENERIC,
            sourceUrl = "https://example.com/stream.m3u8",
        )
        coEvery { engine.probeWithFormats("https://example.com/stream.m3u8") } returns
            ProbeResult(sample, listOf(formatOf("best", height = 1080)))

        val r = useCase("https://example.com/stream.m3u8")
        // 降级路径 → DirectLink
        assertThat(r).isInstanceOf(ParseResult.DirectLink::class.java)
    }

    @Test
    fun `sniffer 404 NotMedia returns Unsupported with status code in reason`() = runTest {
        coEvery { sniffer.sniff("https://example.com/missing.m3u8") } returns
            SniffResult.NotMedia(
                statusCode = 404,
                contentType = null,
                reason = "HTTP 404",
            )

        val r = useCase("https://example.com/missing.m3u8")
        assertThat(r).isInstanceOf(ParseResult.Unsupported::class.java)
        assertThat((r as ParseResult.Unsupported).reason).contains("404")
    }

    // ---- Unsupported / 边界 ----

    @Test
    fun `empty URL returns Unsupported`() = runTest {
        val r = useCase("")
        assertThat(r).isInstanceOf(ParseResult.Unsupported::class.java)
    }

    @Test
    fun `whitespace URL returns Unsupported`() = runTest {
        val r = useCase("   ")
        assertThat(r).isInstanceOf(ParseResult.Unsupported::class.java)
    }

    @Test
    fun `non-http URL returns Unsupported`() = runTest {
        val r = useCase("ftp://example.com/video.mp4")
        assertThat(r).isInstanceOf(ParseResult.Unsupported::class.java)
    }

    @Test
    fun `trims whitespace around URL before parse`() = runTest {
        // 前后空格应被 trim
        val sample = sampleItem("Title", platform = Platform.YOUTUBE, sourceUrl = "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        coEvery { engine.probeWithFormats("https://www.youtube.com/watch?v=dQw4w9WgXcQ") } returns
            ProbeResult(sample, emptyList())

        val r = useCase("  https://www.youtube.com/watch?v=dQw4w9WgXcQ\n")
        assertThat(r).isInstanceOf(ParseResult.Youtube::class.java)
    }

    // ---- helpers ----

    private fun sampleItem(
        title: String,
        platform: Platform,
        sourceUrl: String,
        itemId: String = "dQw4w9WgXcQ",
    ): MediaItem = MediaItem(
        platform = platform,
        itemId = itemId,
        sourceUrl = sourceUrl,
        title = title,
        author = Author(name = "Author"),
        mediaType = MediaType.VIDEO,
    )

    private fun formatOf(
        id: String,
        height: Int? = 1080,
        ext: String = "mp4",
        isAudioOnly: Boolean = false,
    ): MediaFormat = MediaFormat(
        formatId = id,
        ext = ext,
        height = height,
        width = if (height != null) height * 16 / 9 else null,
        vcodec = if (isAudioOnly) "none" else "avc1",
        acodec = if (isAudioOnly) "mp4a" else "mp4a",
        tbr = 1000,
        fileSize = 1024L * 1024 * 100,
        isAudioOnly = isAudioOnly,
    )
}
