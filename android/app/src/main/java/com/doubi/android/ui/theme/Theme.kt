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
 * - Android v0.1 先做 2 套（Material 3 默认亮/暗 + Android 12+ Dynamic Color 兜底），阶段 3 扩到与桌面版对齐
 */
@Composable
fun DouBiTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    // 阶段 3 改为从 DataStore 读 theme setting
    dynamicColor: Boolean = true,
    content: @Composable () -> Unit
) {
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
