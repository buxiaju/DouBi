package com.doubi.android.core.sniffer.di

import com.doubi.android.core.sniffer.HttpContentTypeSniffer
import com.doubi.android.core.sniffer.Sniffer
import dagger.Binds
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import okhttp3.OkHttpClient
import java.util.concurrent.TimeUnit
import javax.inject.Singleton

/**
 * 阶段 8 Sniffer 的 Hilt 装配。
 *
 * v0.1 阶段 1 把 OkHttp / Retrofit 加进 dependencies 但**没用上**——v0.4.0 通用嗅探
 * 第一次真用 OkHttpClient（HttpContentTypeSniffer.sniff()）。
 *
 * 装配：Sniffer interface ↔ HttpContentTypeSniffer 实现（@Binds）+ 提供专用
 * OkHttpClient（10s connect / 10s read，跟桌面版 `is_video_content_type` 行为一致）。
 *
 * v0.5.0 会加 `WebViewHeadlessSniffer`（headless browser 嗅探），那时这个 module 加
 * 一个 `@Provides @Named("headless") fun provideWebViewSniffer(...)` 即可。
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
    @Binds
    @Singleton
    abstract fun bindSniffer(impl: HttpContentTypeSniffer): Sniffer
}
