package com.doubi.android.core.platform.bilibili

import com.google.common.truth.Truth.assertThat
import org.junit.Test

/**
 * 阶段 14 v0.5.4：[BilibiliUrl] 单测。
 *
 * **覆盖**（8 例）：
 * 1. /video/BVxxx → VIDEO + BV ID
 * 2. /video/avNNN → VIDEO + AV ID（legacy）
 * 3. /shorts/BVxxx → SHORTS + BV ID
 * 4. /bangumi/play/epNNN → BANGUMI + "ep:NNN"
 * 5. /bangumi/play/ssNNN → BANGUMI + "ss:NNN"
 * 6. /bangumi/media/mdNNN → BANGUMI + "md:NNN"
 * 7. /live/NNN → LIVE + "room:NNN"
 * 8. 不像 B 站 URL（google.com）→ UNSUPPORTED + 空 id
 */
class BilibiliUrlTest {

    @Test
    fun `classify video with BV id returns VIDEO`() {
        val result = BilibiliUrl.classify("https://www.bilibili.com/video/BV1xx411c7mD")

        assertThat(result.type).isEqualTo(BilibiliUrlType.VIDEO)
        assertThat(result.id).isEqualTo("BV1xx411c7mD")
    }

    @Test
    fun `classify video with legacy av id returns VIDEO`() {
        val result = BilibiliUrl.classify("https://www.bilibili.com/video/av170001")

        assertThat(result.type).isEqualTo(BilibiliUrlType.VIDEO)
        assertThat(result.id).isEqualTo("av170001")
    }

    @Test
    fun `classify shorts returns SHORTS`() {
        val result = BilibiliUrl.classify("https://www.bilibili.com/shorts/BV1Ab2Cd3Ef4")

        assertThat(result.type).isEqualTo(BilibiliUrlType.SHORTS)
        assertThat(result.id).isEqualTo("BV1Ab2Cd3Ef4")
    }

    @Test
    fun `classify bangumi play ep returns BANGUMI with ep prefix`() {
        val result = BilibiliUrl.classify("https://www.bilibili.com/bangumi/play/ep12345")

        assertThat(result.type).isEqualTo(BilibiliUrlType.BANGUMI)
        assertThat(result.id).isEqualTo("ep:12345")
    }

    @Test
    fun `classify bangumi play ss returns BANGUMI with ss prefix`() {
        val result = BilibiliUrl.classify("https://www.bilibili.com/bangumi/play/ss67890")

        assertThat(result.type).isEqualTo(BilibiliUrlType.BANGUMI)
        assertThat(result.id).isEqualTo("ss:67890")
    }

    @Test
    fun `classify bangumi media returns BANGUMI with md prefix`() {
        val result = BilibiliUrl.classify("https://www.bilibili.com/bangumi/media/md28234099")

        assertThat(result.type).isEqualTo(BilibiliUrlType.BANGUMI)
        assertThat(result.id).isEqualTo("md:28234099")
    }

    @Test
    fun `classify live room returns LIVE with room prefix`() {
        val result = BilibiliUrl.classify("https://live.bilibili.com/12345")

        assertThat(result.type).isEqualTo(BilibiliUrlType.LIVE)
        assertThat(result.id).isEqualTo("room:12345")
    }

    @Test
    fun `classify non-bilibili url returns UNSUPPORTED`() {
        val result = BilibiliUrl.classify("https://www.google.com/")

        assertThat(result.type).isEqualTo(BilibiliUrlType.UNSUPPORTED)
        assertThat(result.id).isEqualTo("")
    }

    // toCanonicalUrl 补充 2 例

    @Test
    fun `toCanonicalUrl for BV video returns canonical url`() {
        val classified = BilibiliUrl.classify("https://www.bilibili.com/video/BV1xx411c7mD")
        assertThat(BilibiliUrl.toCanonicalUrl(classified))
            .isEqualTo("https://www.bilibili.com/video/BV1xx411c7mD")
    }

    @Test
    fun `toCanonicalUrl for UNSUPPORTED returns null`() {
        val classified = BilibiliUrl.classify("https://www.google.com/")
        assertThat(BilibiliUrl.toCanonicalUrl(classified)).isNull()
    }
}
