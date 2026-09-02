package com.doubi.android

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import com.doubi.android.ui.navigation.AppNavigation
import com.doubi.android.ui.theme.DouBiTheme
import dagger.hilt.android.AndroidEntryPoint

/**
 * 单 Activity 入口。所有页面通过 Compose Navigation 切换（阶段 3 引入）。
 *
 * 桌面版对照：
 * - `ui/main_window.py:MainWindow.__init__()` 创建主窗口 + 4 个 page widget
 * - Android 版这里挂 `AppNavigation`（阶段 3 引入），里面是 NavHost + 底栏 4 tab
 *
 * **阶段 0-2 演进**：阶段 0 挂 `HomeScreen`（文字占位）→ 阶段 1 仍 `HomeScreen` → 阶段 2 仍
 * `HomeScreen`（下载功能无 UI 入口）→ **阶段 3** 切到 `AppNavigation`。
 */
@AndroidEntryPoint
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            DouBiTheme {
                AppNavigation()
            }
        }
    }
}
