package com.doubi.android

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.getValue
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.doubi.android.core.config.AppConfig
import com.doubi.android.data.config.AppConfigDataStore
import com.doubi.android.ui.navigation.AppNavigation
import com.doubi.android.ui.theme.DouBiTheme
import dagger.hilt.android.AndroidEntryPoint
import javax.inject.Inject

/**
 * 单 Activity 入口。所有页面通过 Compose Navigation 切换（阶段 3 引入）。
 *
 * 桌面版对照：`ui/main_window.py:MainWindow.__init__()` 创建主窗口 + 4 个 page widget。
 * Android 版这里挂 `AppNavigation`（阶段 3 引入），里面是 NavHost + 底栏 4 tab。
 *
 * **阶段 0-2 演进**：阶段 0 挂 `HomeScreen`（文字占位）→ 阶段 1 仍 `HomeScreen` → 阶段 2
 * 仍 `HomeScreen`（下载功能无 UI 入口）→ **阶段 3** 切到 `AppNavigation`。
 *
 * **阶段 9 v0.4.1**：
 * - `installSplashScreen()` 在 super.onCreate() **之前** 调（Android 12+ 标准启屏）
 * - 主题方案从 `AppConfigDataStore.observe().theme` 注入 `DouBiTheme(themeSetting)`
 *   （v0.4.1 C4 落地，桌面版 7 套主题 → Android 端 3 套 default_light/default_dark/system）
 */
@AndroidEntryPoint
class MainActivity : ComponentActivity() {

    @Inject
    lateinit var configStore: AppConfigDataStore

    override fun onCreate(savedInstanceState: Bundle?) {
        // 阶段 9 v0.4.1：SplashScreen API。必须在 super.onCreate() 之前调，
        // 启屏生命周期才能接管 Activity。Android 12+ 圆形 icon + 背景色由
        // themes.xml 的 Theme.SplashScreen parent 配。
        installSplashScreen()
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            val config by configStore.observe().collectAsStateWithLifecycle(
                initialValue = AppConfig(),
            )
            DouBiTheme(themeSetting = config.theme) {
                AppNavigation()
            }
        }
    }
}
