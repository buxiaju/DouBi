package com.doubi.android.ui.navigation

/**
 * 阶段 3 路由表。
 *
 * 4 个底栏 tab + 1 个跳出去的下载详情路由：
 * - **pasting**：粘贴 URL（首页/「下载」tab）
 * - **parsing**：解析中（v0.1 占位，阶段 4 真正实现）
 * - **downloading**：下载中列表（live 任务，订阅 `DownloadRepository.activeTasks` Flow）
 * - **history**：历史（已完成 + 失败的下载）
 *
 * **不用 enum**，用 `object` + `const val` 字符串。Navigation Compose 推荐用 string route
 * 直接拼参数（`?key={value}`），enum 写起来反而绕。
 *
 * 桌面版对照：`ui/main_window.py:MainWindow` 用 QStackedWidget 切 4 个 page，
 * Android 版这里用 NavController 切 4 个 Composable。
 */
object NavRoutes {
    // ---- 底栏 4 个一级路由 ----
    const val PASTING = "pasting"
    const val PARSING = "parsing"
    const val DOWNLOADING = "downloading"
    const val HISTORY = "history"

    // ---- 二级路由（阶段 5+ 才有）----
    const val DOWNLOAD_DETAIL = "download/{taskId}"
    fun downloadDetail(taskId: String): String = "download/$taskId"

    // ---- 当前阶段 3 入口路由（避免单 tab 时底栏空）----
    const val START = PASTING

    /** 4 个底栏 tab 的固定顺序（BottomNav 用这个 list 渲染）。 */
    val BOTTOM_NAV_ROUTES = listOf(PASTING, PARSING, DOWNLOADING, HISTORY)
}
