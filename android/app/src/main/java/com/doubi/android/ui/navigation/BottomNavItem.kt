package com.doubi.android.ui.navigation

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.ContentPaste
import androidx.compose.material.icons.outlined.History
import androidx.compose.material.icons.outlined.PlayArrow
import androidx.compose.material.icons.outlined.Search
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.ui.graphics.vector.ImageVector

/**
 * 底栏 tab 的渲染数据。v0.1 阶段 3 4 个 → v0.2.1 阶段 6 加 settings 5 个。
 *
 * 桌面版对照：`ui/main_window.py:MainWindow` 的 5 个 QAction / 顶栏菜单
 * （桌面版设置在「设置」page，不在主窗口；Android 端放底栏更顺手——v0.1 阶段 6）。
 */
internal data class BottomNavItem(
    val route: String,
    val labelRes: Int,
    val icon: ImageVector,
)

/** 5 个底栏入口。icon 用 Outlined 风格，符合 Material 3 默认调性。 */
internal val BottomNavItems: List<BottomNavItem> = listOf(
    BottomNavItem(NavRoutes.PASTING, com.doubi.android.R.string.nav_paste, Icons.Outlined.ContentPaste),
    BottomNavItem(NavRoutes.PARSING, com.doubi.android.R.string.nav_parse, Icons.Outlined.Search),
    BottomNavItem(NavRoutes.DOWNLOADING, com.doubi.android.R.string.nav_download, Icons.Outlined.PlayArrow),
    BottomNavItem(NavRoutes.HISTORY, com.doubi.android.R.string.nav_history, Icons.Outlined.History),
    BottomNavItem(NavRoutes.SETTINGS, com.doubi.android.R.string.nav_settings, Icons.Outlined.Settings),
)
