package com.doubi.android.core.platform.douyin

import com.google.common.truth.Truth.assertThat
import org.junit.Test

/**
 * 阶段 14 v0.5.4：[DouyinUrl] 单测。
 *
 * **覆盖**（6 例）：
 * 1. /video/19 位 ID → VIDEO
 * 2. /video/ 短 ID（12 位）→ VIDEO（容差 12-22）
 * 3. v.douyin.com/shortId/ → SHORT_LINK
 * 4. live.douyin.com → UNSUPPORTED
 * 5. user/ 用户主页 → UNSUPPORTED
 * 6. toCanonicalUrl VIDEO 保持原 URL
 */
class DouyinUrlTest {

    @Test
    fun `classify main site video returns VIDEO with 19 digit id`() {
        val result = DouyinUrl.classify("https://www.douyin.com/video/7234567890123456789")

        assertThat(result.type).isEqualTo(DouyinUrlType.VIDEO)
        assertThat(result.id).isEqualTo("7234567890123456789")
    }

    @Test
    fun `classify main site video with shorter id still returns VIDEO`() {
        // 12 位 ID 在容差范围内（12-22）
        val result = DouyinUrl.classify("https://www.douyin.com/video/123456789012")

        assertThat(result.type).isEqualTo(DouyinUrlType.VIDEO)
        assertThat(result.id).isEqualTo("123456789012")
    }

    @Test
    fun `classify short link returns SHORT_LINK with short id`() {
        val result = DouyinUrl.classify("https://v.douyin.com/abcdef12/")

        assertThat(result.type).isEqualTo(DouyinUrlType.SHORT_LINK)
        assertThat(result.id).isEqualTo("abcdef12")
    }

    @Test
    fun `classify live douyin url returns UNSUPPORTED`() {
        val result = DouyinUrl.classify("https://live.douyin.com/12345")

        assertThat(result.type).isEqualTo(DouyinUrlType.UNSUPPORTED)
        assertThat(result.id).isEqualTo("")
    }

    @Test
    fun `classify user home page returns UNSUPPORTED`() {
        val result = DouyinUrl.classify("https://www.douyin.com/user/MS4wLjABAAAA1234567890")

        assertThat(result.type).isEqualTo(DouyinUrlType.UNSUPPORTED)
        assertThat(result.id).isEqualTo("")
    }

    @Test
    fun `classify non-douyin url returns UNSUPPORTED`() {
        val result = DouyinUrl.classify("https://www.google.com/")

        assertThat(result.type).isEqualTo(DouyinUrlType.UNSUPPORTED)
        assertThat(result.id).isEqualTo("")
    }

    @Test
    fun `toCanonicalUrl for VIDEO returns original url`() {
        val classified = DouyinUrl.classify("https://www.douyin.com/video/7234567890123456789")
        assertThat(DouyinUrl.toCanonicalUrl(classified))
            .isEqualTo("https://www.douyin.com/video/7234567890123456789")
    }

    @Test
    fun `toCanonicalUrl for SHORT_LINK returns original url`() {
        val classified = DouyinUrl.classify("https://v.douyin.com/abcdef12/")
        assertThat(DouyinUrl.toCanonicalUrl(classified))
            .isEqualTo("https://v.douyin.com/abcdef12/")
    }

    @Test
    fun `toCanonicalUrl for UNSUPPORTED returns null`() {
        val classified = DouyinUrl.classify("https://www.google.com/")
        assertThat(DouyinUrl.toCanonicalUrl(classified)).isNull()
    }
}
