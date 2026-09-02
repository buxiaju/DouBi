package com.doubi.android.core.model

import com.google.common.truth.Truth.assertThat
import org.junit.Test

/**
 * MediaFormat 单测。重点验 [MediaFormat.label] 的人类可读格式化。
 */
class MediaFormatTest {

    @Test
    fun `label formats 4K height with file size`() {
        val f = MediaFormat(
            formatId = "137",
            ext = "mp4",
            height = 2160,
            width = 3840,
            vcodec = "avc1",
            acodec = "mp4a",
            tbr = 5000,
            fileSize = 1024L * 1024 * 1024 * 2,  // 2 GB
        )
        assertThat(f.label).startsWith("4K mp4 (avc1 + mp4a)")
        assertThat(f.label).contains("2.0 GB")
    }

    @Test
    fun `label formats 1080p`() {
        val f = MediaFormat("137", "mp4", height = 1080, width = 1920, vcodec = "avc1", acodec = "mp4a")
        assertThat(f.label).startsWith("1080p mp4 (avc1 + mp4a)")
    }

    @Test
    fun `label formats 720p`() {
        val f = MediaFormat("22", "mp4", height = 720, width = 1280, vcodec = "avc1", acodec = "mp4a")
        assertThat(f.label).startsWith("720p mp4 (avc1 + mp4a)")
    }

    @Test
    fun `label formats 480p`() {
        val f = MediaFormat("135", "mp4", height = 480, width = 854, vcodec = "avc1", acodec = "mp4a")
        assertThat(f.label).startsWith("480p mp4 (avc1 + mp4a)")
    }

    @Test
    fun `label formats 360p`() {
        val f = MediaFormat("134", "mp4", height = 360, width = 640, vcodec = "avc1", acodec = "mp4a")
        assertThat(f.label).startsWith("360p mp4 (avc1 + mp4a)")
    }

    @Test
    fun `label formats 240p`() {
        val f = MediaFormat("133", "mp4", height = 240, width = 426, vcodec = "avc1", acodec = "mp4a")
        assertThat(f.label).startsWith("240p mp4 (avc1 + mp4a)")
    }

    @Test
    fun `label formats 144p`() {
        val f = MediaFormat("160", "mp4", height = 144, width = 256, vcodec = "avc1", acodec = "mp4a")
        assertThat(f.label).startsWith("144p mp4 (avc1 + mp4a)")
    }

    @Test
    fun `label formats audio only with unknown size`() {
        val f = MediaFormat(
            formatId = "140",
            ext = "m4a",
            height = null,
            width = null,
            vcodec = "none",
            acodec = "mp4a",
            tbr = 128,
            fileSize = 0L,
            isAudioOnly = true,
        )
        assertThat(f.label).isEqualTo("audio only m4a (mp4a) · 未知")
    }

    @Test
    fun `label falls back to video when height is null but not audio only`() {
        val f = MediaFormat(
            formatId = "999",
            ext = "mp4",
            height = null,
            width = null,
            vcodec = "avc1",
            acodec = "mp4a",
        )
        assertThat(f.label).startsWith("video mp4 (avc1 + mp4a)")
    }

    @Test
    fun `label omits codec pair when both are none`() {
        val f = MediaFormat(
            formatId = "0",
            ext = "mp4",
            height = 1080,
            width = 1920,
            vcodec = "none",
            acodec = "none",
        )
        assertThat(f.label).startsWith("1080p mp4 ")
        assertThat(f.label).doesNotContain("none")
    }

    @Test
    fun `label omits video codec when none and audio present`() {
        val f = MediaFormat(
            formatId = "140",
            ext = "m4a",
            height = null,
            width = null,
            vcodec = "none",
            acodec = "mp4a",
            isAudioOnly = true,
        )
        // audio only + 单一有效 codec (mp4a)
        assertThat(f.label).isEqualTo("audio only m4a (mp4a) · 未知")
    }

    @Test
    fun `label shows bytes for small files`() {
        val f = MediaFormat(
            formatId = "0",
            ext = "mp4",
            height = 240,
            width = 426,
            vcodec = "avc1",
            acodec = "mp4a",
            fileSize = 512L,
        )
        assertThat(f.label).contains("512 B")
    }

    @Test
    fun `label shows KB for medium files`() {
        val f = MediaFormat(
            formatId = "0",
            ext = "mp4",
            height = 480,
            width = 854,
            vcodec = "avc1",
            acodec = "mp4a",
            fileSize = 1024L * 5,
        )
        assertThat(f.label).contains("5.0 KB")
    }

    @Test
    fun `label caps at TB without array overflow`() {
        val f = MediaFormat(
            formatId = "0",
            ext = "mp4",
            height = 2160,
            width = 3840,
            vcodec = "avc1",
            acodec = "mp4a",
            fileSize = 1024L * 1024 * 1024 * 1024 * 1024,  // 1 PB
        )
        // 应停在 TB/s，不数组越界
        assertThat(f.label).contains("1024.0 TB")
    }

    @Test
    fun `data class default fields are null and false`() {
        val f = MediaFormat(formatId = "0", ext = "mp4")
        assertThat(f.height).isNull()
        assertThat(f.width).isNull()
        assertThat(f.vcodec).isNull()
        assertThat(f.acodec).isNull()
        assertThat(f.tbr).isNull()
        assertThat(f.fileSize).isNull()
        assertThat(f.isAudioOnly).isFalse()
    }
}
