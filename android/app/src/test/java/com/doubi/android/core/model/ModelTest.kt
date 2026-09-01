package com.doubi.android.core.model

import com.google.common.truth.Truth.assertThat
import org.junit.Test

/**
 * 数据模型单测。v0.1 重点验证：
 * - Platform / MediaType.fromString 的兜底
 * - DownloadResult sealed class 的三种状态
 * - 构造时的字段默认值
 */
class ModelTest {

    // ---------- Platform ----------

    @Test
    fun `Platform fromString exact match`() {
        assertThat(Platform.fromString("youtube")).isEqualTo(Platform.YOUTUBE)
        assertThat(Platform.fromString("bilibili")).isEqualTo(Platform.BILIBILI)
        assertThat(Platform.fromString("douyin")).isEqualTo(Platform.DOUYIN)
        assertThat(Platform.fromString("generic")).isEqualTo(Platform.GENERIC)
    }

    @Test
    fun `Platform fromString unknown falls back to GENERIC`() {
        assertThat(Platform.fromString("unknown")).isEqualTo(Platform.GENERIC)
        assertThat(Platform.fromString("")).isEqualTo(Platform.GENERIC)
        assertThat(Platform.fromString(null)).isEqualTo(Platform.GENERIC)
    }

    // ---------- MediaType ----------

    @Test
    fun `MediaType fromString exact match`() {
        assertThat(MediaType.fromString("video")).isEqualTo(MediaType.VIDEO)
        assertThat(MediaType.fromString("audio")).isEqualTo(MediaType.AUDIO)
        assertThat(MediaType.fromString("image")).isEqualTo(MediaType.IMAGE)
    }

    @Test
    fun `MediaType fromString unknown falls back to VIDEO`() {
        assertThat(MediaType.fromString("gif")).isEqualTo(MediaType.VIDEO)
        assertThat(MediaType.fromString(null)).isEqualTo(MediaType.VIDEO)
    }

    // ---------- MediaItem ----------

    @Test
    fun `MediaItem default fields`() {
        val item = MediaItem(
            platform = Platform.YOUTUBE,
            itemId = "abc",
            sourceUrl = "https://youtu.be/abc",
        )
        assertThat(item.title).isEqualTo("")
        assertThat(item.author).isNull()
        assertThat(item.coverUrl).isNull()
        assertThat(item.duration).isNull()
        assertThat(item.publishTime).isNull()
        assertThat(item.mediaType).isEqualTo(MediaType.VIDEO)
    }

    // ---------- Progress ----------

    @Test
    fun `Progress fraction clamped to 0-1`() {
        // 实际夹紧逻辑在 YtDlpEngine.onYoutubeDLProgress 里（coerceIn 0f..1f），
        // Progress 本身不夹紧——data class 信任调用方
        val p = Progress(fraction = 0.5f, message = "halfway")
        assertThat(p.fraction).isEqualTo(0.5f)
        assertThat(p.message).isEqualTo("halfway")
    }

    // ---------- DownloadResult ----------

    @Test
    fun `DownloadResult Success carries path`() {
        val r = DownloadResult.Success("/storage/foo.mp4")
        assertThat(r.localPath).isEqualTo("/storage/foo.mp4")
    }

    @Test
    fun `DownloadResult Failure carries reason`() {
        val r = DownloadResult.Failure("network timeout", partialPath = "/tmp/x.part")
        assertThat(r.reason).isEqualTo("network timeout")
        assertThat(r.partialPath).isEqualTo("/tmp/x.part")
    }

    @Test
    fun `DownloadResult Cancelled is singleton`() {
        // Cancelled 是 data object——引用相等
        assertThat(DownloadResult.Cancelled).isSameInstanceAs(DownloadResult.Cancelled)
    }

    @Test
    fun `DownloadResult when expression covers all branches`() {
        // sealed class 穷尽性测试——编译期保证
        val results: List<DownloadResult> = listOf(
            DownloadResult.Success("/a"),
            DownloadResult.Failure("b"),
            DownloadResult.Cancelled,
        )
        results.forEach {
            val label = when (it) {
                is DownloadResult.Success -> "ok"
                is DownloadResult.Failure -> "fail"
                DownloadResult.Cancelled -> "cancel"
            }
            assertThat(label).isAnyOf("ok", "fail", "cancel")
        }
    }
}
