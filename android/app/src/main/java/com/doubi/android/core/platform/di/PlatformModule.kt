package com.doubi.android.core.platform.di

import com.doubi.android.core.platform.PlatformRegistry
import com.doubi.android.core.platform.bilibili.BilibiliUrl
import com.doubi.android.core.platform.bilibili.WbiSigner
import com.doubi.android.core.platform.douyin.DouyinUrl
import com.doubi.android.core.platform.douyin.XBogusSigner
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

/**
 * 阶段 14 v0.5.4：Platform 层 Hilt 装配。
 *
 * v0.5.4 落地的 4 个组件：
 * - [PlatformRegistry] —— URL → Platform 分发器
 * - [BilibiliUrl] / [DouyinUrl] —— URL 分类（object 单例，@Provides 提供）
 * - [WbiSigner] / [XBogusSigner] —— 签名算法（@Inject constructor + @Singleton）
 *
 * **v0.5.4 范围**：Hilt 只装配现有组件，**不**装配 [WbiSigner] / [XBogusSigner] 之外的
 * 任何 Engine / API 客户端。v0.5.5+ 加 API 客户端时这里补 binding。
 */
@Module
@InstallIn(SingletonComponent::class)
object PlatformModule {

    @Provides
    @Singleton
    fun providePlatformRegistry(): PlatformRegistry = PlatformRegistry()

    @Provides
    @Singleton
    fun provideBilibiliUrl(): BilibiliUrl = BilibiliUrl

    @Provides
    @Singleton
    fun provideDouyinUrl(): DouyinUrl = DouyinUrl

    // WbiSigner / XBogusSigner 用 @Inject constructor + @Singleton 注解，
    // Hilt 自动装配，不需要 @Provides
}
