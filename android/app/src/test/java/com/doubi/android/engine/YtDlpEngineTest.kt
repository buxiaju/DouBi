package com.doubi.android.engine

import com.doubi.android.core.config.toDownloadOptions
import com.doubi.android.core.model.Author
import com.doubi.android.core.model.DownloadOptions
import com.doubi.android.core.model.DownloadResult
import com.doubi.android.core.model.MediaItem
import com.doubi.android.core.model.MediaType
import com.doubi.android.core.model.Platform
import com.doubi.android.engine.ytdlp.YtDlpEngine
import com.google.common.truth.Truth.assertThat
import kotlinx.coroutines.test.runTest
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

/**
 * YtDlpEngine 单测。
 *
 * v0.2 兑底：JunkFood02/yt-dlp-android 已集成到 build.gradle.kts。
 * `supports()` 仍是纯 URL 匹配（不调 yt-dlp-android）—— 测这个；
 * `probe()` / `download()` 会真调 native 库，单测环境没网络/没 init，
 * 期望返回 catch 块里的兜底（probe 返 URL 当标题，download 返 Failure）。
 * 真实端到端得用 instrumented test + 模拟器 + 网络。
 */
class YtDlpEngineTest {

    @get:Rule
    val tmp = TemporaryFolder()

    private val engine = YtDlpEngine(File("/tmp/dummy"))

    // ---------- supports (stub 行为) ----------

    @Test
    fun `supports YouTube watch URL`() {
        assertThat(engine.supports("https://www.youtube.com/watch?v=dQw4w9WgXcQ", defaultOptions())).isTrue()
    }

    @Test
    fun `supports YouTube short URL`() {
        assertThat(engine.supports("https://youtu.be/dQw4w9WgXcQ", defaultOptions())).isTrue()
    }

    @Test
    fun `supports YouTube URL case insensitive`() {
        assertThat(engine.supports("HTTPS://WWW.YOUTUBE.COM/WATCH", defaultOptions())).isTrue()
    }

    @Test
    fun `supports generic http URL`() {
        assertThat(engine.supports("https://example.com/video.mp4", defaultOptions())).isTrue()
        assertThat(engine.supports("http://example.com/stream.m3u8", defaultOptions())).isTrue()
    }

    @Test
    fun `rejects non-URL input`() {
        assertThat(engine.supports("not a url", defaultOptions())).isFalse()
        assertThat(engine.supports("", defaultOptions())).isFalse()
        assertThat(engine.supports("file:///local/path", defaultOptions())).isFalse()
    }

    @Test
    fun `engine name is yt-dlp`() {
        assertThat(engine.name).isEqualTo("yt-dlp")
    }

    // ---------- probe（v0.2 真调，单元测无网络走 catch 兜底） ----------

    @Test
    fun `probe returns minimal MediaItem with URL as title when yt-dlp unavailable`() = runTest {
        // 单测环境 YoutubeDL.getInstance() 未 init 或网络不可达，catch 块返回 URL 当标题
        val item = engine.probe("https://www.youtube.com/watch?v=abc", defaultOptions())
        assertThat(item.platform.key).isEqualTo("youtube")
        assertThat(item.sourceUrl).isEqualTo("https://www.youtube.com/watch?v=abc")
        assertThat(item.title).isEqualTo("https://www.youtube.com/watch?v=abc")
        assertThat(item.itemId).isNotEmpty()
    }

    @Test
    fun `probe of non-YouTube URL uses generic platform`() = runTest {
        val item = engine.probe("https://example.com/video.mp4", defaultOptions())
        assertThat(item.platform.key).isEqualTo("generic")
    }

    // ---------- download（v0.2 真调，单测期望 Failure） ----------

    @Test
    fun `download returns Failure when yt-dlp not initialized in unit test`() = runTest {
        // 单测没 Application 上下文，YoutubeDL.getInstance() 抛异常 → 走 catch
        val item = engine.probe("https://www.youtube.com/watch?v=abc", defaultOptions())
        val result = engine.download(item, defaultOptions()) { /* progress callback */ }
        assertThat(result).isInstanceOf(DownloadResult.Failure::class.java)
        // 不再断言 reason 文本——真引擎的错误信息依赖底层实现，只验 Failure 类型
    }

    // ---------- AppConfig → DownloadOptions 转换（不依赖引擎） ----------

    @Test
    fun `ConfigToOptions maps all relevant fields`() {
        val config = com.doubi.android.core.config.AppConfig(
            maxQuality = "1080p",
            container = "mkv",
            writeThumbnail = true,
            writeSubtitles = true,
            resume = false,
            filenameTemplate = "{author}_{title}",
            rateLimit = "2M",
            proxy = "http://127.0.0.1:7890",
        )
        val options = config.toDownloadOptions()
        assertThat(options.maxQuality).isEqualTo("1080p")
        assertThat(options.container).isEqualTo("mkv")
        assertThat(options.writeThumbnail).isTrue()
        assertThat(options.writeSubtitles).isTrue()
        assertThat(options.resume).isFalse()
        assertThat(options.filenameTemplate).isEqualTo("{author}_{title}")
        assertThat(options.rateLimit).isEqualTo("2M")
        assertThat(options.proxy).isEqualTo("http://127.0.0.1:7890")
    }

    @Test
    fun `ConfigToOptions defaults from AppConfig DEFAULTS`() {
        val options = com.doubi.android.core.config.AppConfig().toDownloadOptions()
        assertThat(options.maxQuality).isEqualTo("best")
        assertThat(options.container).isEqualTo("mp4")
        assertThat(options.writeThumbnail).isFalse()
        assertThat(options.resume).isTrue()
        assertThat(options.filenameTemplate).isEqualTo("{title}_{item_id}")
    }

    // ---------- 欠账 #2：路径模板（outputRoot / outputDirTemplate / filenameTemplate） ----------

    @Test
    fun `resolveOutputDir creates directory under outputRoot with full template`() {
        val base = tmp.newFolder("base")
        val item = sampleYouTubeItem()
        val options = DownloadOptions(
            outputRoot = "Downloaded",
            outputDirTemplate = "{platform}/{author}/{media_type}",
        )
        val dir = engine.resolveOutputDir(base, item, options)
        // 路径断言用 normalized 正斜杠（File.absolutePath 在 Windows 是反斜杠）
        val expected = File(base, "Downloaded/youtube/Smith/VIDEO").path.replace('\\', '/')
        assertThat(dir.path.replace('\\', '/')).isEqualTo(expected)
        assertThat(dir.exists()).isTrue()
        assertThat(dir.isDirectory).isTrue()
    }

    @Test
    fun `resolveOutputDir downgrades missing author to underscore`() {
        val base = tmp.newFolder("base")
        val item = sampleYouTubeItem(author = null)
        val options = DownloadOptions(
            outputRoot = "Downloaded",
            outputDirTemplate = "{platform}/{author}/{media_type}",
        )
        val dir = engine.resolveOutputDir(base, item, options)
        // 正斜杠化后再 contains
        assertThat(dir.path.replace('\\', '/')).contains("youtube/_/VIDEO")
    }

    @Test
    fun `resolveOutputDir falls back to DEFAULTS when template is null`() {
        val base = tmp.newFolder("base")
        val item = sampleYouTubeItem()
        val options = DownloadOptions(outputRoot = "MyVideos", outputDirTemplate = null)
        val dir = engine.resolveOutputDir(base, item, options)
        // 默认 {platform}/{author}/{media_type} → youtube/Smith/VIDEO
        assertThat(dir.path.replace('\\', '/')).contains("MyVideos/youtube/Smith/VIDEO")
    }

    @Test
    fun `resolveOutputDir falls back to Downloaded when outputRoot is blank`() {
        val base = tmp.newFolder("base")
        val item = sampleYouTubeItem()
        val options = DownloadOptions(outputRoot = "  ", outputDirTemplate = "{platform}")
        val dir = engine.resolveOutputDir(base, item, options)
        assertThat(dir.path.replace('\\', '/')).contains("Downloaded/youtube")
    }

    // ---------- filenameTemplate 间接验证：sanitize 后冒号/斜杠都成下划线 ----------

    @Test
    fun `filename template sanitizes special characters`() {
        // 单字符逐一验证 set 里的 9 个非法字符都能被替
        val cases = mapOf(
            "/" to "_",
            "\\" to "_",
            ":" to "_",
            "*" to "_",
            "?" to "_",
            "\"" to "_",
            "<" to "_",
            ">" to "_",
            "|" to "_",
            "a" to "a",
            "Foo Bar" to "Foo Bar",
            "Foo/Bar" to "Foo_Bar",
            "Foo:Bar" to "Foo_Bar",
        )
        for ((input, expected) in cases) {
            val got = engine.sanitizeFilenameForTest(input)
            assertThat(got).isEqualTo(expected)
        }
    }

    // ---------- parseSpeedBytesPerSec（欠账 #4） ----------
    //
    // 这些是 youtubedl-android 0.18.1 真实会回调的行格式：它的 regex 是
    // `\[download\]\s+(\d+\.\d)% .* ETA (\d+):(\d+)`，所以能触发回调的行
    // 必然同时含 `%` 和 ` ETA mm:ss`。库本身不给速度，只能从行里抠。

    @Test
    fun `parseSpeed reads MiB per second`() {
        val line = "[download]  45.2% of  10.50MiB at    1.23MiB/s ETA 00:05"
        // 1.23 * 1024 * 1024 = 1289748.48 → 截断
        assertThat(engine.parseSpeedBytesPerSec(line)).isEqualTo(1289748L)
    }

    @Test
    fun `parseSpeed reads KiB per second`() {
        val line = "[download]  45.2% of ~10.50MiB at  512.00KiB/s ETA 00:05"
        assertThat(engine.parseSpeedBytesPerSec(line)).isEqualTo(512L * 1024)
    }

    @Test
    fun `parseSpeed reads plain bytes per second`() {
        val line = "[download]   1.0% of  10.50MiB at    1024B/s ETA 02:59"
        assertThat(engine.parseSpeedBytesPerSec(line)).isEqualTo(1024L)
    }

    @Test
    fun `parseSpeed reads GiB per second`() {
        val line = "[download]  99.9% of  40.00GiB at    2.00GiB/s ETA 00:01"
        assertThat(engine.parseSpeedBytesPerSec(line)).isEqualTo(2L * 1024 * 1024 * 1024)
    }

    @Test
    fun `parseSpeed accepts non-binary unit spelling`() {
        // yt-dlp 某些版本 / --newline 模式下输出 MB/s 而不是 MiB/s，仍按 1024 进制换算
        val line = "[download]  50.0% of  10.00MB at 1.50MB/s ETA 00:03"
        assertThat(engine.parseSpeedBytesPerSec(line)).isEqualTo(1572864L)
    }

    @Test
    fun `parseSpeed returns null for unknown speed`() {
        val line = "[download]  45.2% of  10.50MiB at  Unknown B/s ETA Unknown"
        assertThat(engine.parseSpeedBytesPerSec(line)).isNull()
    }

    @Test
    fun `parseSpeed returns null for zero speed`() {
        val line = "[download]   0.0% of  10.50MiB at    0.00KiB/s ETA Unknown"
        assertThat(engine.parseSpeedBytesPerSec(line)).isNull()
    }

    @Test
    fun `parseSpeed returns null when line has no speed segment`() {
        assertThat(engine.parseSpeedBytesPerSec("[youtube] dQw4w9WgXcQ: Downloading webpage")).isNull()
        assertThat(engine.parseSpeedBytesPerSec("")).isNull()
    }

    @Test
    fun `parseSpeed returns null for aria2c style line`() {
        // aria2c 外部下载器写 `DL:2.1MiB`（没有 /s），本项目没启用它——降级为 null 而非误报
        val line = "[#7d9f2a 12MiB/50MiB(24%) CN:4 DL:2.1MiB ETA:18s]"
        assertThat(engine.parseSpeedBytesPerSec(line)).isNull()
    }

    @Test
    fun `parseSpeed handles the final summary line`() {
        // 收尾行没 ETA，库不会回调它，但函数本身要能解析（不崩、不误判）
        val line = "[download] 100% of 10.50MiB in 00:08 at 1.31MiB/s"
        assertThat(engine.parseSpeedBytesPerSec(line)).isEqualTo(1373634L)
    }

    private fun sampleYouTubeItem(
        title: String = "Sample Title",
        itemId: String = "dQw4w9WgXcQ",
        author: String? = "Smith",
    ) = MediaItem(
        platform = Platform.YOUTUBE,
        itemId = itemId,
        sourceUrl = "https://www.youtube.com/watch?v=$itemId",
        title = title,
        author = author?.let { Author(name = it) },
        mediaType = MediaType.VIDEO,
    )

    private fun defaultOptions() = DownloadOptions()
}
