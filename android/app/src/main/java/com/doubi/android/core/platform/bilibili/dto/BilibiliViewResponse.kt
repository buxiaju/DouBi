package com.doubi.android.core.platform.bilibili.dto

/**
 * 阶段 16 v0.5.6：`/x/web-interface/view` 响应 DTO。
 *
 * **v0.5.6 范围**：核心字段——bvid / aid / title / duration / cid / owner。
 * **v0.5.7+ 加**：pages (分 P) / pic (封面) / pubdate / desc / tname / stat.
 */
data class BilibiliViewResponse(
    /** 12 字符 BV ID（如 `BV1xx411c7mD`） */
    val bvid: String,
    /** 数字 AV ID（legacy 字段，**不**用作主键） */
    val aid: Long,
    /** 视频标题 */
    val title: String,
    /** 视频时长（秒） */
    val duration: Int,
    /** Client ID（[com.doubi.android.core.platform.bilibili.BilibiliApiClient] 拿播放 URL 需要） */
    val cid: Long,
    /** UP 主名（**不**是登录态用户名，是显示名） */
    val ownerName: String,
    /** UP 主 mid（B 站内部 ID） */
    val ownerMid: Long,
    /** 分 P 数量（0 = 单 P 视频） */
    val pageCount: Int,
)
