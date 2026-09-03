package com.doubi.android.core.sniffer

import com.doubi.android.data.config.AppConfigDataStore
import javax.inject.Inject
import javax.inject.Named
import javax.inject.Singleton

/**
 * 阶段 10 v0.5.0：Composite Sniffer。
 *
 * **目的**：ParseAndExpandUseCase / PastingViewModel 仍然只接一个 [Sniffer]
 * interface（v0.4.0 阶段 8 写好的 contract 不动），但**内部**根据
 * `AppConfig.sniffHeadless` 动态选 [HttpContentTypeSniffer]（HTTP HEAD）
 * 跟 [WebViewHeadlessSniffer]（WebView 集成）其中一个。
 *
 * **决策**：
 * - `AppConfig.sniffHeadless = true`（v0.5.0 默认）→ [WebViewHeadlessSniffer]
 *   覆盖"B 站 / 抖音 / 微博主页"等 JS 异步加载网站
 * - `AppConfig.sniffHeadless = false`（v0.4.0 行为）→ [HttpContentTypeSniffer]
 *   直链 m3u8/mp4/webm 嗅探
 *
 * **Hilt 装配**（[com.doubi.android.core.sniffer.di.SnifferModule]）：
 * - [HttpContentTypeSniffer] 用 `@Named("http")` 注入
 * - [WebViewHeadlessSniffer] 用 `@Named("headless")` 注入
 * - [CompositeSniffer] 用 `@Binds` 绑到无 @Named 的 [Sniffer] interface
 *
 * **v0.5.0 简化**：
 * - `configStore.get()` 每次 sniff 调一次——读 DataStore 是 IO 操作，10-50ms 开销
 *   可接受（v0.5.1+ 优化：cache AppConfig 30s）
 */
@Singleton
class CompositeSniffer @Inject constructor(
    @Named("http") private val httpSniffer: Sniffer,
    @Named("headless") private val headlessSniffer: Sniffer,
    private val configStore: AppConfigDataStore,
) : Sniffer {

    override suspend fun sniff(url: String): SniffResult {
        val useHeadless = configStore.get().sniffHeadless
        return (if (useHeadless) headlessSniffer else httpSniffer).sniff(url)
    }
}
