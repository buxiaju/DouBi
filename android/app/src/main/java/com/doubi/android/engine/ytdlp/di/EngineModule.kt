package com.doubi.android.engine.ytdlp.di

import android.content.Context
import com.doubi.android.engine.ytdlp.YtDlpEngine
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import java.io.File
import javax.inject.Named
import javax.inject.Singleton

/**
 * YtDlpEngine 的 Hilt 装配。
 *
 * v0.1 只用 yt-dlp-android 这一个引擎，构造器需要 `baseOutputDir: File`——
 * 桌面版 Engine ABC 在构造时拿不到 baseOutputDir（运行时从 AppConfig 读），
 * Android 端改用构造时注入，避免 Worker 内部访问 Context。
 *
 * `baseOutputDir` = app 私有 `files/downloads`——跟 [com.doubi.android.data.repository.DownloadRepository.baseOutputDir]
 * 保持一致（Hilt 走同一个 `@ApplicationContext`，单例内调用 `filesDir` 每次都是
 * 同一个路径）。
 *
 * v0.1 阶段 4：**不引入完整的 `Engine` interface 注册**——`Engine` interface 暂时只
 * 有 `YtDlpEngine` 一个实现，`ParseAndExpandUseCase` 注入具体类。如果未来加 aria2
 * / ffmpeg，再把 `Engine` interface 装成 `@Binds`，让 use case 注入 `Engine`。
 */
@Module
@InstallIn(SingletonComponent::class)
object EngineModule {

    private const val DOWNLOADS_DIR_NAME = "downloads"

    @Provides
    @Singleton
    @Named("baseOutputDir")
    fun provideBaseOutputDir(
        @ApplicationContext context: Context,
    ): File = File(context.filesDir, DOWNLOADS_DIR_NAME)

    @Provides
    @Singleton
    fun provideYtDlpEngine(
        @Named("baseOutputDir") baseOutputDir: File,
    ): YtDlpEngine = YtDlpEngine(baseOutputDir)
}
