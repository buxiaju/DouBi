package com.doubi.android.ui.navigation

import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.navigation.NavDestination.Companion.hierarchy
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.doubi.android.ui.downloading.DownloadingScreen
import com.doubi.android.ui.history.HistoryScreen
import com.doubi.android.ui.pasting.PastingScreen
import com.doubi.android.ui.parsing.ParsingScreen

/**
 * 阶段 3 主导航壳——4 个底栏 tab + NavHost。
 *
 * 用法：`MainActivity` 里 `setContent { DouBiTheme { AppNavigation() } }`。
 * 桌面版对照：`ui/main_window.py:MainWindow` 用 QStackedWidget 切 4 个 page widget；
 * Android 端用 NavController + 底栏实现，state 在 NavHostController 里。
 *
 * **底栏切换语义**：用 `popUpTo(graph.findStartDestination().id) { saveState = true }` +
 * `restoreState = true`——切 tab 不重新初始化，保留每个 tab 内部的滚动/输入框状态。
 */
@Composable
fun AppNavigation(
    navController: NavHostController = rememberNavController(),
) {
    val backStackEntry by navController.currentBackStackEntryAsState()
    val currentRoute = backStackEntry?.destination?.route

    Scaffold(
        bottomBar = {
            // 只在 4 个一级 tab 显示底栏——二级路由（DOWNLOAD_DETAIL）不显示
            if (currentRoute in NavRoutes.BOTTOM_NAV_ROUTES) {
                BottomNav(
                    currentRoute = currentRoute,
                    onNavigate = { route ->
                        navController.navigate(route) {
                            popUpTo(navController.graph.findStartDestination().id) {
                                saveState = true
                            }
                            launchSingleTop = true
                            restoreState = true
                        }
                    },
                )
            }
        },
    ) { innerPadding ->
        NavHost(
            navController = navController,
            startDestination = NavRoutes.START,
            modifier = Modifier.padding(innerPadding),
        ) {
            composable(NavRoutes.PASTING) { PastingScreen() }
            composable(NavRoutes.PARSING) { ParsingScreen() }
            composable(NavRoutes.DOWNLOADING) { DownloadingScreen() }
            composable(NavRoutes.HISTORY) { HistoryScreen() }
        }
    }
}

@Composable
private fun BottomNav(
    currentRoute: String?,
    onNavigate: (String) -> Unit,
) {
    NavigationBar {
        BottomNavItems.forEach { item ->
            val selected = currentRoute == item.route
            NavigationBarItem(
                selected = selected,
                onClick = { if (!selected) onNavigate(item.route) },
                icon = { Icon(item.icon, contentDescription = null) },
                label = { Text(stringResource(item.labelRes)) },
            )
        }
    }
}
