package com.doubi.android.ui.downloading

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.work.WorkInfo
import com.doubi.android.data.db.entity.PendingTaskEntity
import com.doubi.android.data.repository.DownloadRepository
import com.doubi.android.download.DownloadWorker
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import javax.inject.Inject

/**
 * 阶段 5 DownloadingScreen 的 ViewModel。
 *
 * 状态来源（双 flow 合并）：
 * - `downloadRepository.activeTasks` —— 持久化任务列表（Room，结构化字段）
 * - `downloadRepository.workInfosFlow` —— WorkManager 实时进度（带 speed/eta）
 *
 * 双 flow 合并策略：
 * - Room 的 taskId 是权威 key
 * - WorkInfo 按 taskId 索引，给每条 task 补 speed/eta/progress
 * - Status 字段：WorkInfo 状态 > Room 状态（WorkInfo 是实时态，Room 可能滞后）
 *
 * 1:1 对拍桌面版 `src/doubi/ui/pages/download.py:DownloadPage` 实时进度渲染。
 */
@HiltViewModel
class DownloadingViewModel @Inject constructor(
    private val downloadRepository: DownloadRepository,
) : ViewModel() {

    val state: StateFlow<State> = combine(
        downloadRepository.activeTasks,
        downloadRepository.workInfosFlow,
    ) { tasks, workInfos ->
        val workInfoByTaskId = workInfos.associateBy { workInfo ->
            // tag 列表里除去 "download" 之外的就是 taskId
            workInfo.tags.firstOrNull { it != "download" }
        }
        State(
            tasks = tasks.map { entity ->
                val info = workInfoByTaskId[entity.taskId]
                TaskUiState(
                    taskId = entity.taskId,
                    title = entity.title ?: entity.sourceUrl,
                    fraction = entity.fraction,
                    message = entity.message,
                    status = mapStatus(entity.status, info?.state),
                    speedBytesPerSec = info?.progress?.getLong(DownloadWorker.KEY_SPEED, -1L)
                        ?.takeIf { it > 0 },
                    etaSeconds = info?.progress?.getLong(DownloadWorker.KEY_ETA, -1L)
                        ?.takeIf { it > 0 },
                    isCancellable = info?.state == WorkInfo.State.RUNNING
                        || info?.state == WorkInfo.State.ENQUEUED
                        || info == null,  // Room 里有但 WorkInfo 没找到也允许取消
                )
            },
            activeCount = tasks.size,
        )
    }.stateIn(
        scope = viewModelScope,
        started = SharingStarted.WhileSubscribed(5_000L),
        initialValue = State(),
    )

    private val _events = MutableStateFlow<Event?>(null)
    val events: StateFlow<Event?> = _events

    fun onCancelClicked(taskId: String) {
        viewModelScope.launch {
            downloadRepository.cancel(taskId)
        }
    }

    fun onEventShown() {
        _events.value = null
    }

    data class State(
        val tasks: List<TaskUiState> = emptyList(),
        val activeCount: Int = 0,
    )

    data class TaskUiState(
        val taskId: String,
        val title: String,
        val fraction: Float,
        val message: String?,
        val status: DisplayStatus,
        val speedBytesPerSec: Long?,
        val etaSeconds: Long?,
        val isCancellable: Boolean,
    )

    enum class DisplayStatus {
        QUEUED, RUNNING, PAUSED, COMPLETED, FAILED, UNKNOWN
    }

    sealed class Event {
        data class Cancelled(val taskId: String) : Event()
    }

    private companion object {
        fun mapStatus(
            roomStatus: String,
            workInfoState: WorkInfo.State?,
        ): DisplayStatus {
            // WorkInfo 状态优先（实时态），Room 兜底
            return when (workInfoState) {
                WorkInfo.State.RUNNING -> DisplayStatus.RUNNING
                WorkInfo.State.ENQUEUED -> DisplayStatus.QUEUED
                WorkInfo.State.SUCCEEDED -> DisplayStatus.COMPLETED
                WorkInfo.State.FAILED -> DisplayStatus.FAILED
                WorkInfo.State.CANCELLED -> DisplayStatus.PAUSED
                WorkInfo.State.BLOCKED -> DisplayStatus.QUEUED
                null -> when (roomStatus) {
                    "queued" -> DisplayStatus.QUEUED
                    "downloading" -> DisplayStatus.RUNNING
                    "paused" -> DisplayStatus.PAUSED
                    "completed" -> DisplayStatus.COMPLETED
                    "failed" -> DisplayStatus.FAILED
                    else -> DisplayStatus.UNKNOWN
                }
            }
        }
    }
}
