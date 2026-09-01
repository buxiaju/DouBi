package com.doubi.android.core.model

/**
 * 平台枚举。1:1 对拍桌面版 `src/doubi/core/models.py:Platform`。
 *
 * v0.1 Android 端只用 `YOUTUBE` + `GENERIC`（直链）。其他平台 v0.2+ 适配。
 * `fromString` 跟桌面版 `Platform.from_str` 行为一致：未知值回退 `GENERIC`。
 */
enum class Platform(val key: String) {
    YOUTUBE("youtube"),
    BILIBILI("bilibili"),
    DOUYIN("douyin"),
    GENERIC("generic");

    companion object {
        fun fromString(value: String?): Platform =
            entries.firstOrNull { it.key == value } ?: GENERIC
    }
}
