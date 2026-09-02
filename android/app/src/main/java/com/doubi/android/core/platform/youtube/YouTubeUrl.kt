package com.doubi.android.core.platform.youtube

/**
 * YouTube URL 形态。1:1 对拍桌面版 `src/doubi/platforms/youtube/url.py:YouTubeURLType`。
 *
 * v0.1 Android 端只支持单视频形态（VIDEO / SHORTS / EMBED / LIVE），CHANNEL / PLAYLIST
 * 一律拒绝（桌面版也是这种策略——CHANNEL/PLAYLIST 让用户直接用 yt-dlp --yes-playlist
 * 处理，不在 adapter 里抄一份列表展开逻辑）。
 */
enum class YouTubeUrlType {
    /** /watch?v=ID 或 youtu.be/ID */
    VIDEO,
    /** /shorts/ID */
    SHORTS,
    /** /embed/ID */
    EMBED,
    /** /live/ID */
    LIVE,
    /** 频道 / 播放列表 / 无法识别 */
    UNSUPPORTED,
}

/**
 * 分类结果。`itemId` 是 11 字符 video ID，UNSUPPORTED 时为空串。
 * `raw` 保留原始 URL 用于报错展示。
 */
data class ClassifiedYouTubeUrl(
    val type: YouTubeUrlType,
    val itemId: String,
    val raw: String,
)

/**
 * YouTube URL 分类 + 归一化。1:1 对拍桌面版 `classify_youtube_url` + `to_watch_url`。
 *
 * 桌面版 patterns 是 Python `re.Pattern`，Android 端用 `kotlin.text.Regex`——行为
 * 一致（都是 PCRE 派生的回溯引擎）。id 11 字符的语义来自 YouTube 自身规则。
 *
 * 顺序很重要：更具体的（带 path 的）排在更宽泛的（仅 host 的）之前。
 * - SHORTS 必须先于 VIDEO——/shorts/ID 的 host 也匹配 VIDEO 的 regex
 * - LIVE 同样独立形态
 * - EMBED 独立形态
 * - VIDEO 兜底最宽
 * - youtu.be 短链 host 不同
 */
object YouTubeUrl {

    // 11 字符 video ID 字符集：大小写字母 / 数字 / 下划线 / 横线。
    private const val VIDEO_ID = "[A-Za-z0-9_-]{11}"

    // UC 开头的 channel ID 24 字符（实际是 22 字符 + UC 前缀）
    private const val CHANNEL_ID = "UC[A-Za-z0-9_-]{22}"

    // 顺序：SHORTS → LIVE → EMBED → CHANNEL → PLAYLIST → VIDEO(watch) → VIDEO(youtu.be)
    // 任何 youtube.com URL 都会落到 VIDEO（兜底），但前面的模式会先抢走。
    private val patterns: List<Pair<YouTubeUrlType, Regex>> = listOf(
        YouTubeUrlType.SHORTS to Regex("""https?://(?:www\.)?youtube\.com/shorts/(?<id>$VIDEO_ID)"""),
        YouTubeUrlType.LIVE to Regex("""https?://(?:www\.)?youtube\.com/live/(?<id>$VIDEO_ID)"""),
        YouTubeUrlType.EMBED to Regex("""https?://(?:www\.)?youtube\.com/embed/(?<id>$VIDEO_ID)"""),
        YouTubeUrlType.UNSUPPORTED to Regex(
            """https?://(?:www\.)?youtube\.com/(?:@[^/?&\s]+|channel/(?<id>$CHANNEL_ID)|c/[^/?&\s]+)"""
        ),
        YouTubeUrlType.UNSUPPORTED to Regex(
            """https?://(?:www\.)?youtube\.com/playlist\?[^?\s]*list=[A-Za-z0-9_-]+"""
        ),
        // VIDEO watch?v=ID —— 11 字符 ID 后必须是 & # 或字符串结束，不允许跟多余字符
        // (避免 watch?v=IDextra 这种误判)
        YouTubeUrlType.VIDEO to Regex(
            """https?://(?:www\.)?youtube\.com/watch\?[^?\s]*v=(?<id>$VIDEO_ID)(?:[&#]|$)"""
        ),
        // youtu.be 短链：host 不同，ID 后必须是 ? # 或字符串结束
        YouTubeUrlType.VIDEO to Regex(
            """https?://youtu\.be/(?<id>$VIDEO_ID)(?:[?#]|$)"""
        ),
    )

    /**
     * 把任意 URL 分类成 YouTube 形态。空串 / 不匹配 → `(UNSUPPORTED, "", url)`。
     */
    fun classify(url: String): ClassifiedYouTubeUrl {
        if (url.isBlank()) return ClassifiedYouTubeUrl(YouTubeUrlType.UNSUPPORTED, "", url)
        for ((type, pat) in patterns) {
            val m = pat.find(url) ?: continue
            // UNSUPPORTED 的 pattern（CHANNEL / PLAYLIST）不带命名组 `id`，
            // groups["id"] 会抛 IllegalArgumentException——用 getOrDefault 兜底
            val id = runCatching { m.groups["id"]?.value }.getOrNull().orEmpty()
            return ClassifiedYouTubeUrl(type, id, url)
        }
        return ClassifiedYouTubeUrl(YouTubeUrlType.UNSUPPORTED, "", url)
    }

    /**
     * 把 ClassifiedYouTubeUrl 归一化成 `https://www.youtube.com/watch?v=ID`。
     * UNSUPPORTED 不归一化（不是视频，无意义），原样返回 raw。
     */
    fun toWatchUrl(c: ClassifiedYouTubeUrl): String {
        if (c.type == YouTubeUrlType.UNSUPPORTED) return c.raw
        return "https://www.youtube.com/watch?v=${c.itemId}"
    }

    /** 一站式：分类 + 归一化。返回 null = UNSUPPORTED / 不可处理。 */
    fun toWatchUrlOrNull(url: String): String? {
        val c = classify(url)
        return if (c.type == YouTubeUrlType.UNSUPPORTED) null else toWatchUrl(c)
    }
}
