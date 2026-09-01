package com.doubi.android.core.model

/**
 * 媒体类型。1:1 对拍桌面版 `src/doubi/core/models.py:MediaType`。
 *
 * v0.1 Android 端只关心 VIDEO（AUDIO / IMAGE 留到 v0.2+）。
 */
enum class MediaType(val key: String) {
    VIDEO("video"),
    AUDIO("audio"),
    IMAGE("image");

    companion object {
        fun fromString(value: String?): MediaType =
            entries.firstOrNull { it.key == value } ?: VIDEO
    }
}
