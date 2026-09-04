package com.doubi.android.core.platform

import com.doubi.android.core.model.Platform
import com.doubi.android.core.platform.bilibili.BilibiliUrl
import com.doubi.android.core.platform.douyin.DouyinUrl
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 阶段 14 v0.5.4：平台 URL 分发器。1:1 对拍桌面版 `src/doubi/platforms/__init__.py:PlatformRegistry`。
 *
 * **职责**：给一个 URL，分类出属于哪个平台（B 站 / 抖音 / YouTube / 其它）。
 * 调用方 [ParseAndExpandUseCase] 用这个分发器决定走哪个 adapter 路径。
 *
 * **v0.5.4 范围**：分发 B 站 / 抖音 / YouTube / GENERIC 4 种。其它返 GENERIC
 * （Sniffer 兜底走通用 HTTP 嗅探，跟 v0.4.0 阶段 8 行为一致）。
 *
 * **桌面版 vs Android 端**：
 * 桌面版有 `classify_platform` 入口；Android 端走 object 单例 [PlatformRegistry.classify]
 * 函数式 API（更符合 Kotlin 习惯）。语义完全 1:1。
 */
@Singleton
class PlatformRegistry @Inject constructor() {

    /**
     * 分类 URL 到 [Platform]。
     *
     * **v0.5.4 范围**：返回的 [Platform] enum（4 种）：
     * - [Platform.YOUTUBE] —— `youtube.com` / `youtu.be`
     * - [Platform.BILIBILI] —— `bilibili.com` / `b23.tv`（v0.5.4 落 URL 分类 + 签名算法）
     * - [Platform.DOUYIN] —— `douyin.com` / `v.douyin.com`（v0.5.4 落 URL 分类 + X-Bogus placeholder）
     * - [Platform.GENERIC] —— 其它（兜底走 v0.4.0 阶段 8 Sniffer）
     *
     * **v0.5.4 行为**：
     * - 检查顺序：BILIBILI → DOUYIN → YOUTUBE → GENERIC
     * - B 站 / 抖音走各自的 [BilibiliUrl.classify] / [DouyinUrl.classify]
     *   如果 classify 返 UNSUPPORTED，**也**返该平台枚举（v0.5.5+ 平台 Engine 集成时
     *   拒绝 UNSUPPORTED 类型；v0.5.4 仅做 URL 分发，不做 unsupported 二次过滤）
     *
     * @param url 用户输入的 URL（已 trim 过）
     * @return [Platform] enum
     */
    fun classify(url: String): Platform {
        val trimmed = url.trim()

        // 1) B 站：先看是不是 bilibili.com / b23.tv
        if (isBilibiliHost(trimmed)) {
            // 走 BilibiliUrl.classify —— 即使 UNSUPPORTED 也返 BILIBILI
            BilibiliUrl.classify(trimmed)
            return Platform.BILIBILI
        }

        // 2) 抖音：先看是不是 douyin.com / v.douyin.com / iesdouyin.com
        if (isDouyinHost(trimmed)) {
            DouyinUrl.classify(trimmed)
            return Platform.DOUYIN
        }

        // 3) YouTube
        if (isYouTubeHost(trimmed)) {
            return Platform.YOUTUBE
        }

        // 4) 其它走 GENERIC
        return Platform.GENERIC
    }

    /**
     * 判断 URL 是不是 B 站域名。**v0.5.4 简化**：用 host substring 匹配。
     * 桌面版用 `urllib.parse.urlparse(url).netloc` 更精确；Android 端用
     * `url.contains` 简单粗暴但够用。
     */
    private fun isBilibiliHost(url: String): Boolean {
        return url.contains("bilibili.com", ignoreCase = true) ||
            url.contains("b23.tv", ignoreCase = true)
    }

    /**
     * 判断 URL 是不是抖音域名。
     */
    private fun isDouyinHost(url: String): Boolean {
        return url.contains("douyin.com", ignoreCase = true) ||
            url.contains("iesdouyin.com", ignoreCase = true)
    }

    /**
     * 判断 URL 是不是 YouTube 域名。跟 [com.doubi.android.core.platform.youtube.YouTubeUrl] 行为一致。
     */
    private fun isYouTubeHost(url: String): Boolean {
        return url.contains("youtube.com", ignoreCase = true) ||
            url.contains("youtu.be", ignoreCase = true)
    }
}
