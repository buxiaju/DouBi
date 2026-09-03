package com.doubi.android.core.sniffer

/**
 * 阶段 8 嗅探结果。sealed 让 ParseAndExpandUseCase 显式处理每个分支。
 *
 * 跟 [com.doubi.android.core.pipeline.ParseResult] 不同：
 * - ParseResult 是「用户 URL → 嗅探后整体结果」（含 Youtube / DirectLink / Unsupported）
 * - SniffResult 是「Sniffer 内部 嗅探的 HTTP 响应特征」（含 Media / NotMedia / Error）
 *
 * ParseAndExpandUseCase 收到非 YouTube URL 时调 Sniffer.sniff()，把 SniffResult
 * 映射成 ParseResult：
 * - Media → DirectLink（item.coverUrl = SniffResult.Media.contentType）
 * - NotMedia → Unsupported（"不是 m3u8 / mp4"）
 * - Error → Unsupported（"嗅探失败"）
 */
sealed class SniffResult {
    /**
     * 嗅探到可下载的 media。`contentType` 给 YtDlpEngine / SettingsScreen 用。
     *
     * m3u8 还会附 `isHls = true` 标记（v0.5.0 YtDlpEngine 加 ffmpeg 后用 HLS 走原生下载）。
     */
    data class Media(
        val contentType: String,
        val finalUrl: String,
        val contentLength: Long?,
        val isHls: Boolean = contentType.contains("mpegurl") || contentType.contains("vnd.apple.mpegurl"),
    ) : SniffResult()

    /**
     * 响应不是 media（HTML 页面 / 404 / 403 / 重定向到登录页）。
     * `statusCode` 留作 UI 提示用（"404 资源不存在"vs"403 鉴权失败"）。
     */
    data class NotMedia(
        val statusCode: Int,
        val contentType: String?,
        val reason: String = "response is not media",
    ) : SniffResult()

    /**
     * 网络错误 / 超时 / DNS 失败 / SSL 错误。`cause` 留作 Timber log。
     */
    data class Error(
        val message: String,
        val cause: Throwable? = null,
    ) : SniffResult()
}
