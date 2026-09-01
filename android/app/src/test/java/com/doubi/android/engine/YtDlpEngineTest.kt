package com.doubi.android.engine

import com.doubi.android.core.config.toDownloadOptions
import com.doubi.android.core.model.DownloadOptions
import com.doubi.android.core.model.DownloadResult
import com.doubi.android.engine.ytdlp.YtDlpEngine
import com.google.common.truth.Truth.assertThat
import kotlinx.coroutines.test.runTest
import org.junit.Test
import java.io.File

/**
 * YtDlpEngine 单测。
 *
 * v0.1：当前是 stub 实现（yausername/yt-dlp-android 在 JitPack 401）。
 * `supports()` 是纯 URL 匹配（不调 yt-dlp-android）—— 测这个；
 * `probe()` stub 也返回最小 MediaItem —— 测这个；
 * `download()` stub 立即返回 Failure —— 测这个。
 *
 * v0.2（依赖恢复后）补：
 * - `probe` 真嗅探：拿测试 YouTube URL 验证 id / title 字段
 * - `download` 端到端：需要 instrumented test 或网络环境
 */
class YtDlpEngineTest {

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

    // ---------- probe (stub 行为) ----------

    @Test
    fun `probe returns minimal MediaItem with URL as title`() = runTest {
        val item = engine.probe("https://www.youtube.com/watch?v=abc", defaultOptions())
        assertThat(item.platform.key).isEqualTo("youtube")
        assertThat(item.sourceUrl).isEqualTo("https://www.youtube.com/watch?v=abc")
        assertThat(item.title).isEqualTo("https://www.youtube.com/watch?v=abc")  // stub：URL 当标题
        assertThat(item.itemId).isNotEmpty()
    }

    @Test
    fun `probe of non-YouTube URL uses generic platform`() = runTest {
        val item = engine.probe("https://example.com/video.mp4", defaultOptions())
        assertThat(item.platform.key).isEqualTo("generic")
    }

    // ---------- download (stub 行为) ----------

    @Test
    fun `download immediately returns Failure in stub mode`() = runTest {
        val item = engine.probe("https://www.youtube.com/watch?v=abc", defaultOptions())
        var progressCalled = false
        val result = engine.download(item, defaultOptions()) { progressCalled = true }
        assertThat(result).isInstanceOf(DownloadResult.Failure::class.java)
        assertThat((result as DownloadResult.Failure).reason).contains("yt-dlp-android")
        assertThat(progressCalled).isFalse()  // stub 不调 progress
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

    private fun defaultOptions() = DownloadOptions()
}
