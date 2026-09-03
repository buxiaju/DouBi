package com.doubi.android.core.sniffer.di

import com.doubi.android.core.sniffer.CompositeSniffer
import com.doubi.android.core.sniffer.HttpContentTypeSniffer
import com.doubi.android.core.sniffer.Sniffer
import com.doubi.android.core.sniffer.WebViewHeadlessSniffer
import dagger.Binds
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import okhttp3.OkHttpClient
import java.util.concurrent.TimeUnit
import javax.inject.Named
import javax.inject.Singleton

/**
 * 阶段 8/10 Sniffer 的 Hilt 装配。
 *
 * v0.4.0 阶段 8：HttpContentTypeSniffer（OkHttp HEAD，10s connect / 10s read），
 *   用 `@Named("http")` 绑到 [Sniffer] interface。覆盖直链 m3u8/mp4/webm。
 * v0.5.0 阶段 10：WebViewHeadlessSniffer（WebView 集成，覆盖 B 站/抖音/微博
 *   主页"JS 异步加载"网站），用 `@Named("headless")` 绑到 [Sniffer] interface。
 *
 * **装配策略**：[CompositeSniffer] 用 `@Binds` 绑到无 @Named 的 [Sniffer]
 * interface——ParseAndExpandUseCase 不用动。CompositeSniffer 内部根据
 * `AppConfig.sniffHeadless` 选 http / headless 之一。
 *
 * **v0.5.0 默认**：`AppConfig.sniffHeadless = true`（用户改 Settings 可关）。
 */
@Module
@InstallIn(SingletonComponent::class)
object SnifferModule {

    @Provides
    @Singleton
    fun provideOkHttpClient(): OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(10, TimeUnit.SECONDS)
        .followRedirects(true)
        .followSslRedirects(true)
        .build()
}

@Module
@InstallIn(SingletonComponent::class)
abstract class SnifferBindingModule {
    /**
     * v0.4.0 阶段 8 通用 HTTP 嗅探：OkHttp HEAD，识别直链 m3u8/mp4/webm。
     * CompositeSniffer 内部 `@Named("http")` 注入。
     */
    @Binds
    @Singleton
    @Named("http")
    abstract fun bindHttpSniffer(impl: HttpContentTypeSniffer): Sniffer

    /**
     * v0.5.0 阶段 10 headless browser 嗅探：WebView 集成，覆盖 B 站/抖音/微博主页
     * "JS 异步加载"网站。CompositeSniffer 内部 `@Named("headless")` 注入。
     */
    @Binds
    @Singleton
    @Named("headless")
    abstract fun bindHeadlessSniffer(impl: WebViewHeadlessSniffer): Sniffer

    /**
     * v0.5.0 阶段 10 阶段 10：Composite Sniffer 按 `AppConfig.sniffHeadless`
     * 动态选 http / headless。ParseAndExpandUseCase 端只接无 @Named 的
     * [Sniffer] interface——v0.4.0 阶段 8 写好的 contract 不动。
     */
    @Binds
    @Singleton
    abstract fun bindCompositeSniffer(impl: CompositeSniffer): Sniffer
}
