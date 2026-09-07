package com.doubi.android.core.platform

import com.doubi.android.core.model.Platform
import com.google.common.truth.Truth.assertThat
import org.junit.Test

/**
 * 阶段 14 v0.5.4：[PlatformRegistry] 单测。
 *
 * **覆盖**（5 例）：
 * 1. B 站 video URL → BILIBILI
 * 2. B 站 bangumi URL → BILIBILI
 * 3. 抖音主站 video URL → DOUYIN
 * 4. YouTube watch URL → YOUTUBE
 * 5. 其它 URL → GENERIC
 */
class PlatformRegistryTest {

    private val registry = PlatformRegistry()

    @Test
    fun `classify bilibili video url returns BILIBILI`() {
        val result = registry.classify("https://www.bilibili.com/video/BV1xx411c7mD")
        assertThat(result).isEqualTo(Platform.BILIBILI)
    }

    @Test
    fun `classify bilibili bangumi url returns BILIBILI`() {
        val result = registry.classify("https://www.bilibili.com/bangumi/play/ep12345")
        assertThat(result).isEqualTo(Platform.BILIBILI)
    }

    @Test
    fun `classify douyin video url returns DOUYIN`() {
        val result = registry.classify("https://www.douyin.com/video/7234567890123456789")
        assertThat(result).isEqualTo(Platform.DOUYIN)
    }

    @Test
    fun `classify douyin short link returns DOUYIN`() {
        val result = registry.classify("https://v.douyin.com/abcdef12/")
        assertThat(result).isEqualTo(Platform.DOUYIN)
    }

    @Test
    fun `classify youtube watch url returns YOUTUBE`() {
        val result = registry.classify("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        assertThat(result).isEqualTo(Platform.YOUTUBE)
    }

    @Test
    fun `classify generic url returns GENERIC`() {
        val result = registry.classify("https://www.example.com/some-video.mp4")
        assertThat(result).isEqualTo(Platform.GENERIC)
    }

    @Test
    fun `classify empty url returns GENERIC`() {
        val result = registry.classify("")
        assertThat(result).isEqualTo(Platform.GENERIC)
    }
}
