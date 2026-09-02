package com.doubi.android.download

import com.google.common.truth.Truth.assertThat
import org.junit.Test

/**
 * DownloadWorker 纯函数单测。
 *
 * 欠账 #1 已还：`isTransientFailure()` 是 companion 上的纯函数（无 Context / 无 Worker），
 * 单元测只覆盖判据。Worker 的实际 retry 行为由 `setBackoffCriteria(EXPONENTIAL, 30s, …)`
 * 控制，需 instrumented test 才能完整验证（见 [com.doubi.android.data.db.MigrationTest] 那一类）。
 */
class DownloadWorkerTest {

    // ---------- 网络类瞬时错误 → 重试 ----------

    @Test
    fun `transient - network timeout`() {
        assertThat(DownloadWorker.isTransientFailure("yt-dlp exit=1: connection timed out"))
            .isTrue()
    }

    @Test
    fun `transient - connection reset`() {
        assertThat(DownloadWorker.isTransientFailure("Connection reset by peer"))
            .isTrue()
    }

    @Test
    fun `transient - 503 service unavailable`() {
        assertThat(DownloadWorker.isTransientFailure("HTTP Error 503: Service Unavailable"))
            .isTrue()
    }

    @Test
    fun `transient - 429 rate limit`() {
        assertThat(DownloadWorker.isTransientFailure("Got error 429 from server"))
            .isTrue()
    }

    @Test
    fun `transient - UnknownHostException`() {
        assertThat(DownloadWorker.isTransientFailure("java.net.UnknownHostException: youtube.com"))
            .isTrue()
    }

    @Test
    fun `transient - SSLException`() {
        assertThat(DownloadWorker.isTransientFailure("SSLException: trust anchor not found"))
            .isTrue()
    }

    // ---------- 永久错误 → 不重试 ----------

    @Test
    fun `permanent - 404 not found`() {
        assertThat(DownloadWorker.isTransientFailure("HTTP Error 404: Not Found")).isFalse()
    }

    @Test
    fun `permanent - 403 forbidden (signed URL expired)`() {
        assertThat(DownloadWorker.isTransientFailure("HTTP Error 403: Forbidden")).isFalse()
    }

    @Test
    fun `permanent - invalid URL`() {
        assertThat(DownloadWorker.isTransientFailure("yt-dlp: Unsupported URL: not a real url"))
            .isFalse()
    }

    @Test
    fun `permanent - disk full`() {
        assertThat(DownloadWorker.isTransientFailure("No space left on device")).isFalse()
    }

    @Test
    fun `permanent - empty reason is not retried`() {
        assertThat(DownloadWorker.isTransientFailure("")).isFalse()
    }

    // ---------- 边界 ----------

    @Test
    fun `case insensitive - uppercase NETWORK still retryable`() {
        assertThat(DownloadWorker.isTransientFailure("NETWORK FAILURE")).isTrue()
    }

    @Test
    fun `partial keyword match - the word network inside a longer string`() {
        assertThat(DownloadWorker.isTransientFailure("Some non-network error mentioning network in a sentence"))
            .isTrue()
    }
}
