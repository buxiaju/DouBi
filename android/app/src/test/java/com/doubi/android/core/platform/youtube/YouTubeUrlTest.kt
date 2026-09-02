package com.doubi.android.core.platform.youtube

import com.doubi.android.core.platform.youtube.YouTubeUrlType.EMBED
import com.doubi.android.core.platform.youtube.YouTubeUrlType.LIVE
import com.doubi.android.core.platform.youtube.YouTubeUrlType.SHORTS
import com.doubi.android.core.platform.youtube.YouTubeUrlType.UNSUPPORTED
import com.doubi.android.core.platform.youtube.YouTubeUrlType.VIDEO
import com.google.common.truth.Truth.assertThat
import org.junit.Test

/**
 * YouTubeUrl 单测。对拍桌面版 `tests/test_youtube_adapter.py` 的 URL 分类用例。
 */
class YouTubeUrlTest {

    // ---- VIDEO：watch?v=ID / youtu.be/ID 兜底 ----

    @Test
    fun `classify watch URL with id`() {
        val c = YouTubeUrl.classify("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        assertThat(c.type).isEqualTo(VIDEO)
        assertThat(c.itemId).isEqualTo("dQw4w9WgXcQ")
    }

    @Test
    fun `classify youtu be short link`() {
        val c = YouTubeUrl.classify("https://youtu.be/dQw4w9WgXcQ")
        assertThat(c.type).isEqualTo(VIDEO)
        assertThat(c.itemId).isEqualTo("dQw4w9WgXcQ")
    }

    @Test
    fun `classify watch URL with extra query params`() {
        // 11 字符 ID 后跟 & 应该是合法的
        val c = YouTubeUrl.classify("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s&list=PL123")
        assertThat(c.type).isEqualTo(VIDEO)
        assertThat(c.itemId).isEqualTo("dQw4w9WgXcQ")
    }

    @Test
    fun `classify watch URL with id at end`() {
        // 11 字符 ID 字符串结尾
        val c = YouTubeUrl.classify("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        assertThat(c.itemId).isEqualTo("dQw4w9WgXcQ")
    }

    @Test
    fun `classify watch URL with fragment`() {
        // 11 字符 ID 后跟 # 合法
        val c = YouTubeUrl.classify("https://www.youtube.com/watch?v=dQw4w9WgXcQ#t=30")
        assertThat(c.type).isEqualTo(VIDEO)
        assertThat(c.itemId).isEqualTo("dQw4w9WgXcQ")
    }

    @Test
    fun `reject watch URL with too-short id`() {
        // 少于 11 字符的 ID 应被拒
        val c = YouTubeUrl.classify("https://www.youtube.com/watch?v=short")
        assertThat(c.type).isEqualTo(UNSUPPORTED)
        assertThat(c.itemId).isEmpty()
    }

    @Test
    fun `reject watch URL with extra chars after id`() {
        // watch?v=IDextra 不应被误判（11 字符 ID 后必须 & # 或结尾）
        val c = YouTubeUrl.classify("https://www.youtube.com/watch?v=dQw4w9WgXcQextra")
        assertThat(c.type).isEqualTo(UNSUPPORTED)
    }

    @Test
    fun `reject m youtube variant is not classified`() {
        // 桌面版没匹配 m.youtube.com —— v0.1 Android 端也只认 www 跟 youtu.be
        val c = YouTubeUrl.classify("https://m.youtube.com/watch?v=dQw4w9WgXcQ")
        assertThat(c.type).isEqualTo(UNSUPPORTED)
    }

    // ---- SHORTS ----

    @Test
    fun `classify shorts URL`() {
        val c = YouTubeUrl.classify("https://www.youtube.com/shorts/dQw4w9WgXcQ")
        assertThat(c.type).isEqualTo(SHORTS)
        assertThat(c.itemId).isEqualTo("dQw4w9WgXcQ")
    }

    @Test
    fun `classify shorts URL with extra query`() {
        val c = YouTubeUrl.classify("https://www.youtube.com/shorts/dQw4w9WgXcQ?feature=share")
        assertThat(c.type).isEqualTo(SHORTS)
        assertThat(c.itemId).isEqualTo("dQw4w9WgXcQ")
    }

    // ---- LIVE ----

    @Test
    fun `classify live URL`() {
        val c = YouTubeUrl.classify("https://www.youtube.com/live/dQw4w9WgXcQ")
        assertThat(c.type).isEqualTo(LIVE)
        assertThat(c.itemId).isEqualTo("dQw4w9WgXcQ")
    }

    // ---- EMBED ----

    @Test
    fun `classify embed URL`() {
        val c = YouTubeUrl.classify("https://www.youtube.com/embed/dQw4w9WgXcQ")
        assertThat(c.type).isEqualTo(EMBED)
        assertThat(c.itemId).isEqualTo("dQw4w9WgXcQ")
    }

    // ---- UNSUPPORTED：CHANNEL / PLAYLIST / 杂项 ----

    @Test
    fun `classify channel at-handle URL as unsupported`() {
        val c = YouTubeUrl.classify("https://www.youtube.com/@LinusTechTips")
        assertThat(c.type).isEqualTo(UNSUPPORTED)
    }

    @Test
    fun `classify channel UC ID URL as unsupported`() {
        val c = YouTubeUrl.classify("https://www.youtube.com/channel/UC_a1a2b3c4d5e6f7g8h9")
        // 注意：UC 开头必须 24 字符（22 + UC），这里我们用 26 字符故意造一个匹配，
        // 实际期望 UNSUPPORTED
        // UC + 22 = 24
        // 让我们用 24 字符：
        val c2 = YouTubeUrl.classify("https://www.youtube.com/channel/UC_a1a2b3c4d5e6f7g8h9i0j")
        // 实际长度 24（UC + 22 字符）
        assertThat(c2.type).isEqualTo(UNSUPPORTED)
    }

    @Test
    fun `classify playlist URL as unsupported`() {
        val c = YouTubeUrl.classify("https://www.youtube.com/playlist?list=PLrAXtmRdnEQy6nuLMHjMZOz59OcA")
        assertThat(c.type).isEqualTo(UNSUPPORTED)
    }

    @Test
    fun `classify empty string as unsupported`() {
        val c = YouTubeUrl.classify("")
        assertThat(c.type).isEqualTo(UNSUPPORTED)
    }

    @Test
    fun `classify non-youtube URL as unsupported`() {
        val c = YouTubeUrl.classify("https://example.com/video.mp4")
        assertThat(c.type).isEqualTo(UNSUPPORTED)
    }

    @Test
    fun `classify blank whitespace as unsupported`() {
        val c = YouTubeUrl.classify("   ")
        assertThat(c.type).isEqualTo(UNSUPPORTED)
    }

    // ---- toWatchUrl / toWatchUrlOrNull 归一化 ----

    @Test
    fun `toWatchUrl normalizes shorts to watch`() {
        val c = YouTubeUrl.classify("https://www.youtube.com/shorts/dQw4w9WgXcQ")
        val url = YouTubeUrl.toWatchUrl(c)
        assertThat(url).isEqualTo("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    }

    @Test
    fun `toWatchUrl normalizes live to watch`() {
        val c = YouTubeUrl.classify("https://www.youtube.com/live/dQw4w9WgXcQ")
        val url = YouTubeUrl.toWatchUrl(c)
        assertThat(url).isEqualTo("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    }

    @Test
    fun `toWatchUrl normalizes embed to watch`() {
        val c = YouTubeUrl.classify("https://www.youtube.com/embed/dQw4w9WgXcQ")
        val url = YouTubeUrl.toWatchUrl(c)
        assertThat(url).isEqualTo("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    }

    @Test
    fun `toWatchUrl normalizes youtu be to watch`() {
        val c = YouTubeUrl.classify("https://youtu.be/dQw4w9WgXcQ")
        val url = YouTubeUrl.toWatchUrl(c)
        assertThat(url).isEqualTo("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    }

    @Test
    fun `toWatchUrl leaves unsupported as raw`() {
        val c = YouTubeUrl.classify("https://www.youtube.com/@LinusTechTips")
        val url = YouTubeUrl.toWatchUrl(c)
        assertThat(url).isEqualTo("https://www.youtube.com/@LinusTechTips")
    }

    @Test
    fun `toWatchUrlOrNull returns null for unsupported`() {
        assertThat(YouTubeUrl.toWatchUrlOrNull("https://example.com/foo")).isNull()
        assertThat(YouTubeUrl.toWatchUrlOrNull("https://www.youtube.com/playlist?list=PL123")).isNull()
        assertThat(YouTubeUrl.toWatchUrlOrNull("")).isNull()
    }

    @Test
    fun `toWatchUrlOrNull returns normalized URL for valid youtube`() {
        assertThat(YouTubeUrl.toWatchUrlOrNull("https://youtu.be/dQw4w9WgXcQ"))
            .isEqualTo("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        assertThat(YouTubeUrl.toWatchUrlOrNull("https://www.youtube.com/shorts/dQw4w9WgXcQ"))
            .isEqualTo("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    }
}
