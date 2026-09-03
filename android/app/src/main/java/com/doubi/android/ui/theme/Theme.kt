package com.doubi.android.ui.theme

import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.platform.LocalContext

/**
 * 应用主主题。
 *
 * 桌面版对照：`ui/theme.py:ThemeManager`。
 * - 桌面版 7 套主题（default_light / default_dark / doubi / 深海 / 莫兰迪 / 护眼 / 高对比）
 * - Android v0.1 先做 2 套（Material 3 默认亮/暗 + Android 12+ Dynamic Color 兜底）
 * - 阶段 9 v0.4.1：暴露 `themeSetting` 参数让 [com.doubi.android.MainActivity] 从
 *   [com.doubi.android.core.config.AppConfig.theme] 读取，UI 切主题立即生效
 *
 * **themeSetting 合法值**（与 [com.doubi.android.core.config.AppConfig.theme] 字段约束一致）：
 * - `"default_light"` 强制亮色
 * - `"default_dark"` 强制暗色
 * - `"system"` 跟系统（`isSystemInDarkTheme()`）
 * - 其它值（v0.1 老配置 / 用户瞎写）回退 `"system"`
 */
@Composable
fun DouBiTheme(
    themeSetting: String = "system",
    // v0.1 阶段 3 默认开 dynamicColor，Android 12+ 用系统主题色
    dynamicColor: Boolean = true,
    content: @Composable () -> Unit
) {
    val darkTheme = when (themeSetting) {
        "default_light" -> false
        "default_dark" -> true
        else -> isSystemInDarkTheme()
    }

    val colorScheme = when {
        dynamicColor && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S -> {
            val context = LocalContext.current
            if (darkTheme) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
        }

        darkTheme -> darkColorScheme(
            primary = DefaultDarkPrimary,
            onPrimary = DefaultDarkOnPrimary,
            background = DefaultDarkBackground,
            surface = DefaultDarkSurface
        )

        else -> lightColorScheme(
            primary = DefaultLightPrimary,
            onPrimary = DefaultLightOnPrimary,
            background = DefaultLightBackground,
            surface = DefaultLightSurface
        )
    }

    MaterialTheme(
        colorScheme = colorScheme,
        typography = DouBiTypography,
        content = content
    )
}
