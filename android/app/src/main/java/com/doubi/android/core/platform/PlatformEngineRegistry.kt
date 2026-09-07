package com.doubi.android.core.platform

import com.doubi.android.core.model.Platform
import com.doubi.android.core.platform.bilibili.BilibiliAdapter
import com.doubi.android.core.platform.douyin.DouyinAdapter
import com.doubi.android.engine.Engine
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 阶段 17 v0.5.7：平台 Engine 路由表。1:1 对拍桌面版
 * `src/doubi/platforms/__init__.py:PlatformRegistry`（同 v0.5.4 Android 端
 * [PlatformRegistry] 但**只**返已落地 Engine 的平台）。
 *
 * **职责**：给一个 URL，路由到对应的 [Engine] 实现（B 站 / 抖音）。
 * 调用方 [com.doubi.android.core.pipeline.ParseAndExpandUseCase] 用它
 * 决定走哪个 adapter 的 `probe` 路径。
 *
 * **v0.5.7 范围**：
 * - 已落地 [Engine] 实现：**BilibiliAdapter**（v0.5.7 Commit 1）+ **DouyinAdapter**（v0.5.7 Commit 2）
 * - 未落地：YouTube（桌面版 YouTubeAdapter，Android 端 v0.1 阶段 4 走 `YtDlpEngine.probeWithFormats`
 *   不需要单独 adapter）→ 返 `null`，让 use case 走原 YouTube / 通用嗅探路径
 *
 * **v0.5.7 不做**：
 * - 不**自动**注册（虽然 Hilt @Inject + @Singleton 能让容器发现所有 Engine 实现，但当前
 *   显式注入最简单可读——v0.5.8+ Engine 数量增长再考虑 reflective discovery）
 * - 不**缓存** URL → Engine 映射（v0.5.7 每次 classify + 一次 when 很快，省缓存）
 *
 * **架构**：
 * - 跟 [PlatformRegistry] 区分：[PlatformRegistry] 只做 URL → Platform 分类（无依赖），
 *   本类做 URL → Engine 路由（依赖具体 adapter 实现）
 * - desktop 端两者合并成一个；Android 端按"分类 vs 路由"两个职责切开更清晰
 */
@Singleton
class PlatformEngineRegistry @Inject constructor(
    private val platformRegistry: PlatformRegistry,
    private val bilibiliAdapter: BilibiliAdapter,
    private val douyinAdapter: DouyinAdapter,
) {
    /**
     * 路由 URL 到已落地的 [Engine] 实现。
     *
     * **v0.5.7 路由表**：
     * - [Platform.BILIBILI] → [BilibiliAdapter]（v0.5.7 Commit 1）
     * - [Platform.DOUYIN] → [DouyinAdapter]（v0.5.7 Commit 2）
     * - [Platform.YOUTUBE] / [Platform.GENERIC] → `null`（YouTube 走 use case 原 YouTube 路径，
     *   GENERIC 走 Sniffer；不**进** adapter 路由）
     *
     * @param url 用户输入的 URL（已 trim 过）
     * @return 命中的 [Engine] 实现；无命中返 `null` 让调用方走原路径
     */
    fun getEngine(url: String): Engine? {
        val trimmed = url.trim()
        return when (platformRegistry.classify(trimmed)) {
            Platform.BILIBILI -> bilibiliAdapter
            Platform.DOUYIN -> douyinAdapter
            Platform.YOUTUBE,
            Platform.GENERIC -> null
        }
    }
}
