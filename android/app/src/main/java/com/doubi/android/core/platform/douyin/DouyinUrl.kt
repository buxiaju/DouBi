package com.doubi.android.core.platform.douyin

/**
 * 阶段 14 v0.5.4：抖音 URL 形态。1:1 对拍桌面版 `src/doubi/platforms/douyin/url.py`。
 *
 * **v0.5.4 范围**：识别 **VIDEO / SHORT_LINK / UNSUPPORTED** 3 种形态。
 * - **VIDEO**：`https://www.douyin.com/video/{video_id}`（19 位纯数字 ID）
 * - **SHORT_LINK**：`https://v.douyin.com/{short_id}/` 短链 —— v0.5.4 范围，解析后
 *   需 HTTP 302 跟随拿真实 URL 再 classify —— v0.5.4 只识别形态，**不**解析 short_id
 *   到 video_id（HTTP 跟随留 v0.5.5+ API 集成）
 * - **UNSUPPORTED**：live.douyin.com（直播）/ user/（用户主页）/ discover（推荐页）等
 *
 * **桌面版 vs Android 端**：
 * 桌面版完整支持 VIDEO / SHORT_LINK / LIVE / DISCOVER / NOTE，Android 端 v0.5.4
 * 只覆盖主路径 VIDEO + SHORT_LINK，LIVE/NOTE 留 v0.5.5+。
 *
 * **抖音 video_id 格式**：纯数字，19 位（少数早期 16/17 位）。
 * 例：`https://www.douyin.com/video/7234567890123456789`
 */
enum class DouyinUrlType {
    /** /video/NNN（19 位纯数字 video_id） */
    VIDEO,
    /** v.douyin.com 短链 —— 需 HTTP 302 跟随 */
    SHORT_LINK,
    /** live / user / discover / 无法识别 */
    UNSUPPORTED,
}

/**
 * 分类结果。
 * - VIDEO → `id` = 19 位 video_id 字符串
 * - SHORT_LINK → `id` = short_id 字符串
 * - UNSUPPORTED → `id` = "" 空串
 */
data class ClassifiedDouyinUrl(
    val type: DouyinUrlType,
    val id: String,
    val raw: String,
)

/**
 * 抖音 URL 分类 + 归一化。1:1 对拍桌面版 `classify_douyin_url`。
 *
 * **正则匹配顺序**（重要）：
 * 1. /video/NNN —— 主站视频
 * 2. v.douyin.com/NNN —— 短链
 * 3. UNSUPPORTED 兜底
 *
 * **归一化（toCanonicalUrl）**：
 * - VIDEO：保持原 URL（19 位 ID 已经在路径里）
 * - SHORT_LINK：保持原 URL（**不**解析 short_id → video_id，留 v0.5.5+ API 集成）
 * - UNSUPPORTED：null
 */
object DouyinUrl {

    // 抖音 video_id：19 位纯数字（少数早期 16-18 位 — 这里用 12-22 容差）
    private const val VIDEO_ID = "\\d{12,22}"

    // 短链 ID：6-12 位字母数字（实际 6 位左右）
    private const val SHORT_ID = "[A-Za-z0-9_-]{6,12}"

    private val patterns: List<Pair<DouyinUrlType, Regex>> = listOf(
        // /video/NNN —— 主站视频（19 位 ID，容差 12-22）
        DouyinUrlType.VIDEO to Regex(
            """https?://(?:www\.)?douyin\.com/video/(?<id>$VIDEO_ID)"""
        ),
        // v.douyin.com/shortId/ —— 短链（6-12 位 ID）
        DouyinUrlType.SHORT_LINK to Regex(
            """https?://v\.douyin\.com/(?<id>$SHORT_ID)/?"""
        ),
    )

    /**
     * 分类抖音 URL。返回 [ClassifiedDouyinUrl] 包含 [DouyinUrlType] + id + raw URL。
     *
     * **未识别** → 返 [DouyinUrlType.UNSUPPORTED] + `id = ""`（跟 v0.1 YouTubeUrl / v0.5.4
     * BilibiliUrl 行为对齐）。
     */
    fun classify(url: String): ClassifiedDouyinUrl {
        val trimmed = url.trim()
        for ((type, regex) in patterns) {
            val match = regex.matchEntire(trimmed) ?: continue
            val id = runCatching { match.groups["id"]?.value }.getOrNull().orEmpty()
            return ClassifiedDouyinUrl(type, id, trimmed)
        }
        return ClassifiedDouyinUrl(DouyinUrlType.UNSUPPORTED, "", trimmed)
    }

    /**
     * 归一化到 canonical URL。`null` = 无法归一化（UNSUPPORTED）。
     *
     * **v0.5.4 简化**：
     * - VIDEO：原 URL 已含 19 位 ID，保持
     * - SHORT_LINK：原 URL 已含 short_id，**不**解析 short_id → video_id
     *   （HTTP 302 跟随拿真实 URL 留 v0.5.5+ API 集成）
     */
    fun toCanonicalUrl(classified: ClassifiedDouyinUrl): String? = when (classified.type) {
        DouyinUrlType.VIDEO, DouyinUrlType.SHORT_LINK -> classified.raw
        DouyinUrlType.UNSUPPORTED -> null
    }
}
