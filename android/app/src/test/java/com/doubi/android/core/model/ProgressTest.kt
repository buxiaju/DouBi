package com.doubi.android.core.model

import com.google.common.truth.Truth.assertThat
import org.junit.Test

/**
 * [Progress] 单测（欠账 #4）。
 *
 * 重点验三件事：
 * 1. `speedBytesPerSec` / `etaSeconds` 的「非正数视为未知」约定——yt-dlp 未知时报 -1，
 *    绝不能显示成 "-1 B/s" 或 "剩 -00:01"。
 * 2. 格式化用 1024 进制 + `Locale.US`（中文/德语环境下小数点不能变逗号）。
 * 3. `statusLine()` 在字段缺失时逐级退化，永远不留悬空分隔符。
 */
class ProgressTest {

    // ---------- percent ----------

    @Test
    fun `percent rounds down from fraction`() {
        assertThat(Progress(fraction = 0.452f).percent).isEqualTo(45)
    }

    @Test
    fun `percent clamps negative fraction to zero`() {
        // 引擎未知时给 -1f，YtDlpEngine 会 /100 后 clamp，但双保险
        assertThat(Progress(fraction = -0.01f).percent).isEqualTo(0)
    }

    @Test
    fun `percent clamps overflow to hundred`() {
        assertThat(Progress(fraction = 1.5f).percent).isEqualTo(100)
    }

    // ---------- formatSpeed ----------

    @Test
    fun `formatSpeed keeps bytes without decimals`() {
        assertThat(Progress.formatSpeed(512L)).isEqualTo("512 B/s")
    }

    @Test
    fun `formatSpeed switches to KB at 1024`() {
        assertThat(Progress.formatSpeed(1024L)).isEqualTo("1.0 KB/s")
    }

    @Test
    fun `formatSpeed uses one decimal for KB`() {
        assertThat(Progress.formatSpeed(1536L)).isEqualTo("1.5 KB/s")
    }

    @Test
    fun `formatSpeed switches to MB`() {
        assertThat(Progress.formatSpeed(1024L * 1024)).isEqualTo("1.0 MB/s")
    }

    @Test
    fun `formatSpeed switches to GB`() {
        assertThat(Progress.formatSpeed(1024L * 1024 * 1024)).isEqualTo("1.0 GB/s")
    }

    @Test
    fun `formatSpeed caps at TB instead of overflowing units`() {
        // 1 PB/s 没有对应单位，应该停在 TB/s 而不是数组越界
        val onePetabyte = 1024L * 1024 * 1024 * 1024 * 1024
        assertThat(Progress.formatSpeed(onePetabyte)).isEqualTo("1024.0 TB/s")
    }

    @Test
    fun `formatSpeed treats zero and negative as zero`() {
        assertThat(Progress.formatSpeed(0L)).isEqualTo("0 B/s")
        assertThat(Progress.formatSpeed(-1L)).isEqualTo("0 B/s")
    }

    // ---------- formatEta ----------

    @Test
    fun `formatEta pads seconds under a minute`() {
        assertThat(Progress.formatEta(5L)).isEqualTo("00:05")
    }

    @Test
    fun `formatEta shows minutes and seconds`() {
        assertThat(Progress.formatEta(65L)).isEqualTo("01:05")
    }

    @Test
    fun `formatEta switches to hours at 3600`() {
        assertThat(Progress.formatEta(3600L)).isEqualTo("1:00:00")
    }

    @Test
    fun `formatEta keeps hour minute second order`() {
        assertThat(Progress.formatEta(3661L)).isEqualTo("1:01:01")
    }

    @Test
    fun `formatEta treats zero and negative as zero`() {
        assertThat(Progress.formatEta(0L)).isEqualTo("00:00")
        assertThat(Progress.formatEta(-1L)).isEqualTo("00:00")
    }

    // ---------- speedText / etaText 的「未知」约定 ----------

    @Test
    fun `speedText is null when engine reports nothing`() {
        assertThat(Progress(fraction = 0.5f).speedText).isNull()
    }

    @Test
    fun `speedText is null for the yt-dlp unknown sentinel`() {
        // yt-dlp / youtubedl-android 未知时给 -1，不能渲染成 "-1 B/s"
        assertThat(Progress(fraction = 0.5f, speedBytesPerSec = -1L).speedText).isNull()
        assertThat(Progress(fraction = 0.5f, speedBytesPerSec = 0L).speedText).isNull()
    }

    @Test
    fun `etaText is null for the yt-dlp unknown sentinel`() {
        assertThat(Progress(fraction = 0.5f, etaSeconds = -1L).etaText).isNull()
        assertThat(Progress(fraction = 0.5f, etaSeconds = 0L).etaText).isNull()
    }

    @Test
    fun `speedText and etaText format when present`() {
        val p = Progress(fraction = 0.5f, speedBytesPerSec = 1024L * 1024 * 2, etaSeconds = 201L)
        assertThat(p.speedText).isEqualTo("2.0 MB/s")
        assertThat(p.etaText).isEqualTo("03:21")
    }

    // ---------- statusLine 逐级退化 ----------

    @Test
    fun `statusLine joins percent speed and eta`() {
        val p = Progress(fraction = 0.452f, speedBytesPerSec = 1258291L, etaSeconds = 201L)
        assertThat(p.statusLine()).isEqualTo("下载中 45% · 1.2 MB/s · 剩 03:21")
    }

    @Test
    fun `statusLine drops eta when unknown`() {
        val p = Progress(fraction = 0.452f, speedBytesPerSec = 1258291L, etaSeconds = -1L)
        assertThat(p.statusLine()).isEqualTo("下载中 45% · 1.2 MB/s")
    }

    @Test
    fun `statusLine drops speed when unknown`() {
        val p = Progress(fraction = 0.452f, etaSeconds = 201L)
        assertThat(p.statusLine()).isEqualTo("下载中 45% · 剩 03:21")
    }

    @Test
    fun `statusLine degrades to percent only`() {
        assertThat(Progress(fraction = 0.452f).statusLine()).isEqualTo("下载中 45%")
    }

    @Test
    fun `statusLine honours custom prefix`() {
        assertThat(Progress(fraction = 0f).statusLine("嗅探中")).isEqualTo("嗅探中 0%")
    }

    // ---------- data class 契约 ----------

    @Test
    fun `new fields default to null so existing call sites keep compiling`() {
        val p = Progress(fraction = 0.1f)
        assertThat(p.speedBytesPerSec).isNull()
        assertThat(p.etaSeconds).isNull()
    }
}
