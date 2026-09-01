package com.doubi.android.engine

import com.doubi.android.core.model.DownloadOptions
import com.doubi.android.engine.ytdlp.YtDlpEngine
import com.google.common.truth.Truth.assertThat
import org.junit.Test
import java.io.File

/**
 * YtDlpEngine 单测。`supports()` 是纯 URL 匹配（不调 yt-dlp-android），
 * 能离线测；`probe` / `download` 调 `YoutubeDL.getInstance()` 实际跑 yt-dlp，
 * 单测里跳过（instrumented test 或手动跑）。
 */
class YtDlpEngineTest {

    private val engine = YtDlpEngine(File("/tmp/dummy"))

    // ---------- supports ----------

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
        // v0.1：所有 http/https 都接受（让通用嗅探 v0.2+ 接管细化）
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

    // ---------- AppConfig → DownloadOptions 转换 ----------

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
