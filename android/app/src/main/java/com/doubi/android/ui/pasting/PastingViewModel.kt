package com.doubi.android.ui.pasting

import androidx.lifecycle.ViewModel
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import javax.inject.Inject

/**
 * 阶段 3 PastingScreen 的 ViewModel。
 *
 * **v0.1 占位**：只存 `url`，解析按钮点了不真的入队——等阶段 4 接 Engine.probe。
 * 现在 4 个字段（url + 3 个 reserved）够用；接嗅探后这文件会扩到 ~50 行。
 *
 * Hilt 注入：标 `@HiltViewModel` + `@Inject` 构造器；UI 端用 `hiltViewModel()` 拿。
 */
@HiltViewModel
class PastingViewModel @Inject constructor(
    // 阶段 4 加 Engine（嗅探），阶段 5 加 DownloadRepository（入队）
) : ViewModel() {

    private val _state = MutableStateFlow(State())
    val state: StateFlow<State> = _state.asStateFlow()

    fun onUrlChanged(value: String) {
        _state.update { it.copy(url = value) }
    }

    /**
     * 阶段 3 占位：只更新 lastAction，**不真跳页、不真入队**。
     * 阶段 4 替换为「嗅探 → 跳 PARSING 带 url 参数」，阶段 5 替换为「直接入队下载」。
     */
    fun onParseClicked() {
        _state.update { it.copy(lastAction = System.currentTimeMillis()) }
    }

    data class State(
        val url: String = "",
        /** 记录最近一次「解析」按钮的点击时间，UI 用来显示反馈。 */
        val lastAction: Long = 0L,
    )
}
