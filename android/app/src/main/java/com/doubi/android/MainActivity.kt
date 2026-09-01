package com.doubi.android

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Scaffold
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.doubi.android.ui.home.HomeScreen
import com.doubi.android.ui.theme.DouBiTheme
import dagger.hilt.android.AndroidEntryPoint

/**
 * 单 Activity 入口。所有页面通过 Compose Navigation 切换（阶段 3 引入）。
 *
 * 桌面版对照：
 * - `ui/main_window.py:MainWindow.__init__()` 创建主窗口 + 4 个 page widget
 * - Android 版这里只挂 `HomeScreen` 占位（阶段 0），阶段 3 切到 `NavHost`
 */
@AndroidEntryPoint
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            DouBiTheme {
                AppScaffold()
            }
        }
    }
}

@Composable
private fun AppScaffold() {
    Scaffold(
        modifier = Modifier.fillMaxSize()
    ) { innerPadding ->
        HomeScreen(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
        )
    }
}
