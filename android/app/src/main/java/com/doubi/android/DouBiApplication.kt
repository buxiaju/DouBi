package com.doubi.android

import android.app.Application
import dagger.hilt.android.HiltAndroidApp
import timber.log.Timber

/**
 * DouBi Android 应用入口。
 *
 * 与桌面版 `ui/app.py:create_app()` 角色一致——Hilt 容器初始化 + 全局配置。
 *
 * 桌面版对照：
 * - `__version__` 来自 `src/doubi/__init__.py`，Android 版用 `BuildConfig.VERSION_NAME`。
 * - 日志初始化对应 `core/logger.py:setup_logging()`，阶段 0 只装 Timber；阶段 1 接 DataStore 后再决定写文件。
 */
@HiltAndroidApp
class DouBiApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        if (BuildConfig.DEBUG) {
            Timber.plant(Timber.DebugTree())
        }
        Timber.i("DouBi Android %s (debug=%s) 启动", BuildConfig.VERSION_NAME, BuildConfig.DEBUG)
    }
}
