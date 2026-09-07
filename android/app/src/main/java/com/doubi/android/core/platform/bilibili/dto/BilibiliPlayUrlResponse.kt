package com.doubi.android.core.platform.bilibili.dto

/**
 * 阶段 18 v0.5.8：`/x/player/playurl` 响应 DTO。
 *
 * **v0.5.8 范围**：核心字段——`url`（真实下载直链）+ `size`（字节，0 = 未知）。
 * v0.5.9+ 考虑加 `format`（flv / mp4 / dash）/ `quality`（qn 清晰度映射）/ `acceptQuality`（支持的清晰度列表）/
 * `duration`（冗余字段，二次校验用）。
 *
 * **v0.5.8 简化**：
 * - 只取 `durl[0].url`（FLV/MP4 直链），**不**取 `dash.video[].baseUrl`（DASH 流，需要
 *   MP4Box / ffmpeg 合并）——v0.5.8 范围单条直链，yt-dlp 跑下载
 * - 单一清晰度 `qn=80`（1080p），v0.5.9+ 让用户选
 * - 不处理 4K / HDR / 杜比视界（fnver=0 / fourk=1 走默认）
 */
data class BilibiliPlayUrlResponse(
    /**
     * 真实下载 URL（FLV / MP4 / m3u8 直链）。
     *
     * 桌面版 1:1 对拍 [BilibiliPlayUrlResponse.url] —— 桌面版在 `BilibiliStrategy.download()`
     * 里直接 `requests.get(this.url, stream=True)` 跑下载；Android 端 v0.5.8 走
     * [com.doubi.android.engine.ytdlp.YtDlpEngine.download]（拿到 URL 后包成 MediaItem 喂 yt-dlp）。
     */
    val url: String,
    /**
     * 文件大小（字节），0 = 未知。
     *
     * 从 `durl[0].size` 拿——B 站单 P 视频通常有 size 字段，多 P 视频 size 可能是 0（每 P 单独
     * 一个 durl 对象）。v0.5.8 拿 [size] 仅作日志/UI 显示用，**不**用于下载校验。
     */
    val size: Long,
)
