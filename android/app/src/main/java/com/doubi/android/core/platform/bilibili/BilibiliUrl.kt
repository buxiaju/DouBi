package com.doubi.android.core.platform.bilibili

/**
 * 阶段 14 v0.5.4：B 站 URL 形态。1:1 对拍桌面版 `src/doubi/platforms/bilibili/url.py:BilibiliURLType`。
 *
 * **v0.5.4 范围**：识别 **VIDEO / SHORTS / BANGUMI / AUDIO / LIVE / UNSUPPORTED** 6 种形态。
 * 其中：
 * - VIDEO（普通投稿）+ SHORTS（短片）—— v0.5.4 主路径
 * - BANGUMI（番剧 ep/ss/md）—— v0.5.4 主路径
 * - AUDIO（音频）—— v0.5.5+ 留接口，不在 v0.5.4 实现
 * - LIVE（直播）—— v0.5.4 拒绝（直播下载在 B 站风控下基本不可行）
 * - UNSUPPORTED（专栏 / 动态 / 列表 / 课程 / 活动等）—— 拒绝
 *
 * **桌面版 vs Android 端**：
 * 桌面版有完整 11+ 种 URL 形态支持（VIDEO / SHORTS / BANGUMI / LIVE / ARTICLE /
 * DYNAMIC / LIST / AUDIO / CHEESE / FESTIVAL / H5 / BLACKBOARD 等），Android 端
 * v0.5.4 只覆盖主路径，其它留 v0.5.5+。
 *
 * **桌面版对应字段**：
 * - `bvid` —— 12 字符 BV ID（VIDEO / SHORTS）
 * - `avid` —— 数字 AV ID（legacy）
 * - `ep_id` / `ss_id` / `md_id` —— 番剧 ID
 * - `room_id` —— 直播间 ID
 * - `au_id` —— 音频 ID
 */
enum class BilibiliUrlType {
    /** /video/BVxxxxxxxx 或 /video/avNNNN */
    VIDEO,
    /** /shorts/BVxxxxxxxx */
    SHORTS,
    /** /bangumi/play/epNNNNN 或 /bangumi/play/ssNNNN 或 /bangumi/media/mdNNNN */
    BANGUMI,
    /** /audio/auNNNNNN —— v0.5.5+ 留接口 */
    AUDIO,
    /** /live/roomId —— v0.5.4 拒绝（直播不可行） */
    LIVE,
    /** 专栏 / 动态 / 列表 / 课程 / 活动 / 黑板 / H5 / 无法识别 */
    UNSUPPORTED,
}

/**
 * 分类结果。`id` 字段：
 * - VIDEO / SHORTS → BV ID（12 字符）优先，没有 BV 才用 AV ID（数字）
 * - BANGUMI → "ep:NNN" / "ss:NNN" / "md:NNN"（带前缀区分类型）
 * - AUDIO → "au:NNN"（带前缀）
 * - LIVE → "room:NNN"（带前缀）
 * - UNSUPPORTED → 空串
 *
 * `raw` 保留原始 URL 用于报错展示。
 */
data class ClassifiedBilibiliUrl(
    val type: BilibiliUrlType,
    val id: String,
    val raw: String,
)

/**
 * B 站 URL 分类 + 归一化。1:1 对拍桌面版 `classify_bilibili_url` + `to_watch_url`。
 *
 * **正则匹配顺序**（重要）：
 * 1. /bangumi/ 系列（ep/ss/md）—— 番剧路径
 * 2. /shorts/ —— 短片（必须先于 /video/，因为 /shorts/ 路径下也可能用 BV ID）
 * 3. /video/ —— 普通投稿（BV / AV）
 * 4. /live/ —— 直播
 * 5. /audio/ —— 音频
 * 6. UNSUPPORTED 兜底
 *
 * **归一化（toCanonicalUrl）**：
 * - VIDEO：BV/AV → `https://www.bilibili.com/video/{BV}`（AV 暂保留，桌面版会
 *   调 API 拿 BV；v0.5.4 简单直接用 ID）
 * - SHORTS：→ `https://www.bilibili.com/shorts/{BV}`
 * - BANGUMI：保持原 URL
 * - LIVE / AUDIO：保持原 URL
 * - UNSUPPORTED：保持原 URL
 */
object BilibiliUrl {

    // BV ID: BV + 10 字符 base58
    // 字符集：大小写字母（除 I、O、l）+ 数字
    private const val BV_ID = "BV[A-Za-z0-9]{10}"

    // AV ID: av + 纯数字（legacy）
    private const val AV_ID = "av\\d+"

    // 番剧 ID
    private const val EP_ID = "ep\\d+"
    private const val SS_ID = "ss\\d+"
    private const val MD_ID = "md\\d+"

    // 直播 / 音频 ID
    private const val ROOM_ID = "\\d+"
    private const val AU_ID = "au\\d+"

    private val patterns: List<Pair<BilibiliUrlType, Regex>> = listOf(
        // /bangumi/play/epNNN —— 番剧 EP（单集）
        BilibiliUrlType.BANGUMI to Regex(
            """https?://(?:www\.)?bilibili\.com/bangumi/play/(?<id>$EP_ID)"""
        ),
        // /bangumi/play/ssNNN —— 番剧 SS（整季）
        BilibiliUrlType.BANGUMI to Regex(
            """https?://(?:www\.)?bilibili\.com/bangumi/play/(?<id>$SS_ID)"""
        ),
        // /bangumi/media/mdNNN —— 番剧 media（整季入口）
        BilibiliUrlType.BANGUMI to Regex(
            """https?://(?:www\.)?bilibili\.com/bangumi/media/(?<id>$MD_ID)"""
        ),
        // /shorts/BVxxx —— 短片（先于 /video/，因路径前缀不同）
        BilibiliUrlType.SHORTS to Regex(
            """https?://(?:www\.)?bilibili\.com/shorts/(?<id>$BV_ID)"""
        ),
        // /video/BVxxx —— 普通投稿（BV）
        BilibiliUrlType.VIDEO to Regex(
            """https?://(?:www\.)?bilibili\.com/video/(?<id>$BV_ID)"""
        ),
        // /video/avNNN —— 普通投稿（AV legacy）
        BilibiliUrlType.VIDEO to Regex(
            """https?://(?:www\.)?bilibili\.com/video/(?<id>$AV_ID)"""
        ),
        // /live/NNN —— 直播
        BilibiliUrlType.LIVE to Regex(
            """https?://live\.bilibili\.com/(?<id>$ROOM_ID)"""
        ),
        // /audio/auNNN —— 音频
        BilibiliUrlType.AUDIO to Regex(
            """https?://(?:www\.)?bilibili\.com/audio/(?<id>$AU_ID)"""
        ),
    )

    /**
     * 分类 B 站 URL。返回 [ClassifiedBilibiliUrl] 包含 [BilibiliUrlType] + id + raw URL。
     *
     * **未识别** → 返 [BilibiliUrlType.UNSUPPORTED] + `id = ""`（跟 v0.1 YouTubeUrl
     * 行为对齐，UNSUPPORTED 的 `id` 永远是空串）。
     */
    fun classify(url: String): ClassifiedBilibiliUrl {
        val trimmed = url.trim()
        for ((type, regex) in patterns) {
            val match = regex.matchEntire(trimmed) ?: continue
            // 命名组可能在某些 pattern 不存在（如 BANGUMI 的 md_id 是纯数字，
            // 跟 ROOM_ID 冲突——靠 regex 优先级消歧）
            val id = runCatching { match.groups["id"]?.value }.getOrNull().orEmpty()
            // 番剧 ep / ss / md id 加前缀以保留类型（getOrNull 已处理 missing group）
            val prefixedId = when {
                type == BilibiliUrlType.BANGUMI && id.startsWith("ep") -> "ep:${id.removePrefix("ep")}"
                type == BilibiliUrlType.BANGUMI && id.startsWith("ss") -> "ss:${id.removePrefix("ss")}"
                type == BilibiliUrlType.BANGUMI && id.startsWith("md") -> "md:${id.removePrefix("md")}"
                type == BilibiliUrlType.AUDIO -> "au:${id.removePrefix("au")}"
                type == BilibiliUrlType.LIVE -> "room:$id"
                else -> id
            }
            return ClassifiedBilibiliUrl(type, prefixedId, trimmed)
        }
        return ClassifiedBilibiliUrl(BilibiliUrlType.UNSUPPORTED, "", trimmed)
    }

    /**
     * 归一化到 canonical URL。`null` = 无法归一化（UNSUPPORTED 等）。
     *
     * **v0.5.4 简化**：BV / AV 都直接拼路径，**不**调 API 把 AV 转 BV（v0.5.5+ 加
     * API 集成时再做）。
     */
    fun toCanonicalUrl(classified: ClassifiedBilibiliUrl): String? = when (classified.type) {
        BilibiliUrlType.VIDEO -> {
            val id = classified.id
            if (id.startsWith("BV")) "https://www.bilibili.com/video/$id"
            else if (id.startsWith("av")) "https://www.bilibili.com/video/$id"
            else null
        }
        BilibiliUrlType.SHORTS -> {
            if (classified.id.startsWith("BV")) "https://www.bilibili.com/shorts/${classified.id}"
            else null
        }
        BilibiliUrlType.BANGUMI, BilibiliUrlType.LIVE, BilibiliUrlType.AUDIO -> classified.raw
        BilibiliUrlType.UNSUPPORTED -> null
    }
}
