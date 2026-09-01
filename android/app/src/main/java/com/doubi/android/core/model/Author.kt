package com.doubi.android.core.model

/**
 * 作者信息。1:1 对拍桌面版 `src/doubi/core/models.py:Author`。
 *
 * 字段全部 nullable——嗅探失败 / 隐私站点都可能缺字段。
 */
data class Author(
    val id: String? = null,
    val name: String? = null,
    val avatarUrl: String? = null,
)
