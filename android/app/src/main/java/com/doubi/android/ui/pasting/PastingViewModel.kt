package com.doubi.android.ui.pasting

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.doubi.android.core.config.toDownloadOptions
import com.doubi.android.core.model.DownloadOptions
import com.doubi.android.core.model.MediaFormat
import com.doubi.android.core.model.MediaItem
import com.doubi.android.core.pipeline.ParseAndExpandUseCase
import com.doubi.android.core.pipeline.ParseResult
import com.doubi.android.data.config.AppConfigDataStore
import com.doubi.android.data.repository.DownloadRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import timber.log.Timber
import javax.inject.Inject

/**
 * 阶段 4 PastingScreen 的 ViewModel。接 `ParseAndExpandUseCase` 嗅探 + 弹
 * [com.doubi.android.ui.parse.PromptOptionsDialog] 选清晰度 + 走 [DownloadRepository.enqueue]
 * 入队。
 *
 * 状态机（[ParseStatus]）：
 * - `Idle`         —— 初始 / 反馈消息消费后
 * - `Parsing`      —— onParseClicked 调 use case 中
 * - `AwaitingConfirm(item, formats, seedOptions)` —— 解析成功，等用户在 Dialog 里选
 * - `Unsupported(reason)` —— 不支持的 URL（不是 http(s) / YouTube 频道 / 空串）
 * - `Enqueued(taskId)` —— 入队成功，UI 用 snackbar 一次性反馈
 * - `Failure(error)` —— use case 抛异常 / 入队失败
 *
 * 消息消费：`onMessageShown()` 把 Enqueued / Unsupported / Failure 重置回 Idle，
 * 让 snackbar 不会因为 recompose 反复显示。
 */
@HiltViewModel
class PastingViewModel @Inject constructor(
    private val parseAndExpand: ParseAndExpandUseCase,
    private val downloadRepo: DownloadRepository,
    private val configStore: AppConfigDataStore,
) : ViewModel() {

    private val _state = MutableStateFlow(State())
    val state: StateFlow<State> = _state.asStateFlow()

    fun onUrlChanged(value: String) {
        _state.update { it.copy(url = value) }
    }

    fun onParseClicked() {
        val url = _state.value.url.trim()
        if (url.isEmpty()) {
            _state.update {
                it.copy(parseStatus = ParseStatus.Unsupported("URL 为空"))
            }
            return
        }
        _state.update { it.copy(parseStatus = ParseStatus.Parsing) }
        viewModelScope.launch {
            try {
                val result = parseAndExpand(url)
                val currentSeed = configStore.get().toDownloadOptions()
                _state.update {
                    it.copy(
                        parseStatus = when (result) {
                            is ParseResult.Youtube -> ParseStatus.AwaitingConfirm(
                                item = result.item,
                                formats = result.formats,
                                seedOptions = currentSeed,
                            )
                            is ParseResult.DirectLink -> ParseStatus.AwaitingConfirm(
                                item = result.item,
                                formats = listOfNotNull(result.format),
                                seedOptions = currentSeed,
                            )
                            is ParseResult.Unsupported -> ParseStatus.Unsupported(result.reason)
                        },
                    )
                }
            } catch (e: Throwable) {
                Timber.e(e, "ParseAndExpandUseCase failed for %s", url)
                _state.update {
                    it.copy(parseStatus = ParseStatus.Failure(e.message ?: e.javaClass.simpleName))
                }
            }
        }
    }

    fun onDialogConfirm(
        item: MediaItem,
        format: MediaFormat?,
        options: DownloadOptions,
        titleTemplate: String?,
    ) {
        viewModelScope.launch {
            try {
                // 标题模板应用到 item.title（拷贝，不污染原值）—— desktop 端
                // apply_title_template 行为一致。
                val finalItem = if (titleTemplate.isNullOrBlank() || !titleTemplate.contains("{title}")) {
                    item
                } else {
                    item.copy(title = titleTemplate.replace("{title}", item.title))
                }
                // format 选定 → 把 formatId 写到 options.maxQuality（DownloadWorker 跟
                // Engine 都按 maxQuality 走），空 format 走默认。
                val finalOptions = if (format != null) {
                    options.copy(maxQuality = format.formatId)
                } else {
                    options
                }
                val requestId = downloadRepo.enqueue(
                    sourceUrl = finalItem.sourceUrl,
                    platform = finalItem.platform.key,
                    itemId = finalItem.itemId,
                    title = finalItem.title,
                )
                _state.update {
                    it.copy(
                        parseStatus = ParseStatus.Enqueued(
                            taskId = requestId,
                            title = finalItem.title,
                        ),
                    )
                }
            } catch (e: DownloadRepository.QueueFullException) {
                // 阶段 5：并发数已满，特殊分支走 QueueFull 状态让 UI 给专门提示
                Timber.w("Queue full: %d / %d", e.current, e.limit)
                _state.update {
                    it.copy(parseStatus = ParseStatus.QueueFull(current = e.current, limit = e.limit))
                }
            } catch (e: Throwable) {
                Timber.e(e, "enqueue failed")
                _state.update {
                    it.copy(parseStatus = ParseStatus.Failure(e.message ?: "enqueue failed"))
                }
            }
        }
    }

    fun onDialogDismiss() {
        _state.update { it.copy(parseStatus = ParseStatus.Idle) }
    }

    fun onMessageShown() {
        // 让 snackbar 只显示一次——消费后回 Idle
        _state.update { current ->
            if (current.parseStatus is ParseStatus.Enqueued
                || current.parseStatus is ParseStatus.Unsupported
                || current.parseStatus is ParseStatus.Failure
                || current.parseStatus is ParseStatus.QueueFull
            ) {
                current.copy(parseStatus = ParseStatus.Idle)
            } else {
                current
            }
        }
    }

    data class State(
        val url: String = "",
        val parseStatus: ParseStatus = ParseStatus.Idle,
    )

    /**
     * 解析状态。`AwaitingConfirm` 是触发 [com.doubi.android.ui.parse.PromptOptionsDialog]
     * 显示的入口；`Enqueued` / `Unsupported` / `Failure` / `QueueFull` 是一次性消息源。
     */
    sealed class ParseStatus {
        object Idle : ParseStatus()
        object Parsing : ParseStatus()
        data class AwaitingConfirm(
            val item: MediaItem,
            val formats: List<MediaFormat>,
            val seedOptions: DownloadOptions,
        ) : ParseStatus()
        data class Unsupported(val reason: String) : ParseStatus()
        data class Enqueued(val taskId: String, val title: String) : ParseStatus()
        /** 阶段 5：下载队列已满（当前 N / 上限 M） */
        data class QueueFull(val current: Int, val limit: Int) : ParseStatus()
        data class Failure(val error: String) : ParseStatus()
    }
}
