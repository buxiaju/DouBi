package com.doubi.android.data.db

import androidx.room.TypeConverter

/**
 * Room TypeConverters。
 *
 * 桌面版对照：`src/doubi/core/storage/database.py:options_to_json` / `item_to_json`
 * —— JSON 字段落库用 String，由 Repository 层用 kotlinx.serialization 做 Map ↔ JSON。
 * 这里只放极简的「值类型 ↔ String」转换器（如 LongList），不在这层做 Map ↔ JSON。
 *
 * 设计取舍：TypeConverter 是 Room 的硬性胶水，JSON 解析放这一层会让所有
 * 不需要 JSON 的查询都付一次解析代价——违背「按需付费」。所以保持轻量。
 */
class Converters {
    /**
     * `sniff_capture_types` 之类用 `tuple[str, ...]` 存的字段在 Android 端
     * 用 `List<String>`，落库时用 newline 分隔（不依赖 JSON 解析）。
     * 单测可与桌面版 YAML 序列化对拍。
     */
    @TypeConverter
    fun stringListToString(value: List<String>?): String? = value?.joinToString("\n")

    @TypeConverter
    fun stringToStringList(value: String?): List<String>? =
        value?.takeIf { it.isNotEmpty() }?.split("\n")
}
