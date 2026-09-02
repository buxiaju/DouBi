package com.doubi.android.ui.downloading

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.doubi.android.data.repository.DownloadRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

/**
 * 阶段 3 DownloadingScreen 的 ViewModel。
 *
 * v0.1 订阅 `DownloadRepository.activeTasks` 只取 count 渲染「活跃任务：N」。
 * 阶段 5 替换为「完整列表 + 进度条 + 取消按钮 + Worker 进度」实时渲染。
 *
 * Hilt 注入 `DownloadRepository`（阶段 2 已建好）。
 */
@HiltViewModel
class DownloadingViewModel @Inject constructor(
    private val downloadRepository: DownloadRepository,
) : ViewModel() {

    private val _state = MutableStateFlow(State())
    val state: StateFlow<State> = _state.asStateFlow()

    init {
        viewModelScope.launch {
            downloadRepository.activeTasks.collect { tasks ->
                _state.update { it.copy(activeCount = tasks.size) }
            }
        }
    }

    data class State(
        val activeCount: Int = 0,
    )
}
