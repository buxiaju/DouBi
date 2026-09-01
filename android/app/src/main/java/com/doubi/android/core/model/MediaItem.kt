package com.doubi.android.core.model

/**
 * 媒体项。1:1 对拍桌面版 `src/doubi/core/models.py:MediaItem`（精简版）。
 *
 * v0.1 Android 端用最小字段集——`id` / `title` / `sourceUrl` 必填，其他可选。
 * 桌面版的 `streams` / `children` / `outputTemplate` 字段在 Android 端不持久化
 * （桌面版 `item_to_json` 也明确跳掉这 3 个，见
 * `src/doubi/core/storage/database.py:_ITEM_SKIP_FIELDS`）。
 */
data class MediaItem(
    val platform: Platform,
    val itemId: String,
    val sourceUrl: String,
    val title: String = "",
    val author: Author? = null,
    val coverUrl: String? = null,
    val duration: Double? = null,
    /** Unix seconds。 */
    val publishTime: Long? = null,
    val mediaType: MediaType = MediaType.VIDEO,
)
