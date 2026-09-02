package com.doubi.android.core.model

/**
 * 媒体格式选项。1:1 对拍桌面版 `src/doubi/core/models.py:FormatSpec`（精简版）。
 *
 * 来源：`youtubedl-android 0.18.1` 的 `YoutubeDL.getInfo()` 返回的
 * `VideoInfo.formats: List<VideoFormat>`，里面每个元素有
 * `formatId` / `ext` / `height` / `width` / `vcodec` / `acodec` / `tbr` /
 * `fileSize` 等字段（反编译 `com.yausername.youtubedl_android.mapper.VideoFormat`
 * 字节码确认）。
 *
 * v0.1 Android 端只在 YouTube 单一视频场景下使用，**不做**抖音 / B 站 formats
 * 拉取（那两家平台要走各自 adapter 的 Web API，阶段 5+ 才补）。
 */
data class MediaFormat(
    /**
     * yt-dlp `formatId`，例如 `137+140`、`22`、`best`。**给 yt-dlp `-f` 选项用**——
     * 不解析成桌面版那种 1080p 标签，直接透传 `formatId` 让 yt-dlp 自己决定。
     */
    val formatId: String,

    /** 扩展名，mp4 / webm / m4a。 */
    val ext: String,

    /** 高度（像素）。音频流为 null。 */
    val height: Int? = null,

    /** 宽度（像素）。音频流为 null。 */
    val width: Int? = null,

    /** 视频编码，avc1 / vp9 / av01。音频流为 none。 */
    val vcodec: String? = null,

    /** 音频编码，mp4a / opus / none（视频流无音轨）。 */
    val acodec: String? = null,

    /** 总码率 kbps。YouTube 实际多在 50-60000 之间，0 / -1 视为未知。 */
    val tbr: Int? = null,

    /**
     * 文件字节数。YouTube 给的 `fileSize` 经常是 0（未探测），用
     * `fileSizeApproximate` 兜底。**两个都 0 / -1 视为未知**，UI 展示"未知"。
     */
    val fileSize: Long? = null,

    /** 是否纯音频（视频流无 / vcodec=none）。 */
    val isAudioOnly: Boolean = false,
) {
    /**
     * 人类可读标签，给 PromptOptionsDialog 列表展示用。
     * 例：`"1080p mp4 (avc1 + mp4a) · 2.3 MB"` / `"audio only (opus) · 未知"`
     */
    val label: String
        get() = buildString {
            if (isAudioOnly) {
                append("audio only")
            } else {
                val h = height
                when {
                    h == null -> append("video")
                    h >= 2160 -> append("4K")
                    h >= 1440 -> append("2K")
                    h >= 1080 -> append("1080p")
                    h >= 720 -> append("720p")
                    h >= 480 -> append("480p")
                    h >= 360 -> append("360p")
                    h >= 240 -> append("240p")
                    h >= 144 -> append("144p")
                    else -> append("${h}p")
                }
            }
            append(' ').append(ext)
            val codecPair = listOfNotNull(vcodec?.takeIf { it != "none" }, acodec?.takeIf { it != "none" })
                .joinToString(" + ")
            if (codecPair.isNotEmpty()) {
                append(" (").append(codecPair).append(')')
            }
            val size = fileSize?.takeIf { it > 0 }
            if (size != null) {
                append(" · ").append(formatSize(size))
            } else {
                append(" · 未知")
            }
        }

    companion object {
        private fun formatSize(bytes: Long): String {
            if (bytes <= 0) return "0 B"
            val units = listOf("B", "KB", "MB", "GB", "TB")
            var v = bytes.toDouble()
            var i = 0
            while (v >= 1024.0 && i < units.lastIndex) {
                v /= 1024.0
                i++
            }
            return if (i == 0) {
                "${v.toLong()} ${units[i]}"
            } else {
                String.format(java.util.Locale.US, "%.1f %s", v, units[i])
            }
        }
    }
}
