package com.doubi.android.core.platform.douyin.dto

/**
 * 阶段 16 v0.5.6：`/web/api/v2/aweme/iteminfo/` 响应 DTO（单个 aweme）。
 *
 * **v0.5.6 范围**：核心字段——aweme_id / desc / duration_sec / author.nickname / video.play_addr / video.cover。
 * **v0.5.7+ 加**：share_url（分享链接）/ create_time（创建时间）/ music（背景音乐）/ statistics（点赞评论数）等。
 */
data class DouyinAwemeItem(
    /** 抖音视频 ID（数字字符串） */
    val awemeId: String,
    /** 视频描述/标题 */
    val desc: String,
    /** 视频时长（**秒**——抖音 API 给的是毫秒，client 自动除以 1000） */
    val durationSec: Int,
    /** 作者显示名（**不**是登录态用户名） */
    val authorNickname: String,
    /** 作者 sec_uid（抖音内部 ID） */
    val authorSecUid: String,
    /** 无水印播放 URL（v0.5.6 是从 `video.play_addr.url_list[0]` 拿的） */
    val playUrl: String,
    /** 封面 URL（`video.cover.url_list[0]`） */
    val coverUrl: String,
)
