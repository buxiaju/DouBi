package com.doubi.android

import android.app.Application
import androidx.hilt.work.HiltWorkerFactory
import androidx.work.Configuration
import dagger.hilt.android.HiltAndroidApp
import javax.inject.Inject
import timber.log.Timber

/**
 * DouBi Android 应用入口。
 *
 * 与桌面版 `ui/app.py:create_app()` 角色一致——Hilt 容器初始化 + 全局配置。
 *
 * 阶段 2 起实现 `Configuration.Provider`——Hilt 集成 WorkManager 需要，
 * 让 `@HiltWorker` 注解的 Worker（`DownloadWorker` 等）能拿到 Hilt 注入的依赖。
 * 默认 WorkManager 初始化在 `AndroidManifest.xml` 关闭。
 */
@HiltAndroidApp
class DouBiApplication : Application(), Configuration.Provider {

    @Inject
    lateinit var workerFactory: HiltWorkerFactory

    override val workManagerConfiguration: Configuration
        get() = Configuration.Builder()
            .setWorkerFactory(workerFactory)
            .setMinimumLoggingLevel(if (BuildConfig.DEBUG) android.util.Log.DEBUG else android.util.Log.INFO)
            .build()

    override fun onCreate() {
        super.onCreate()
        if (BuildConfig.DEBUG) {
            Timber.plant(Timber.DebugTree())
        }
        Timber.i("DouBi Android %s (debug=%s) 启动", BuildConfig.VERSION_NAME, BuildConfig.DEBUG)
    }
}
