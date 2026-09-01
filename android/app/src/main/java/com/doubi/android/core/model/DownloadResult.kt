package com.doubi.android.core.model

/**
 * 下载结果。sealed class——成功 / 失败 / 取消 三态。
 *
 * 桌面版对应：`src/doubi/core/pipeline.py:DownloadResult`（隐式返回 Optional[str] / 抛异常）。
 * Android 端用 sealed class 显式建模，Worker / UI 都用 `when` 处理穷尽。
 */
sealed class DownloadResult {
    /** 成功：本地文件绝对路径。 */
    data class Success(val localPath: String) : DownloadResult()

    /**
     * 失败：原因 + 可选的部分文件路径（如果下了半截没清）。
     * 桌面版错误类型散落在各 Engine，v0.1 简单归一。
     */
    data class Failure(
        val reason: String,
        val partialPath: String? = null,
    ) : DownloadResult()

    /** 用户主动取消。 */
    data object Cancelled : DownloadResult()
}
