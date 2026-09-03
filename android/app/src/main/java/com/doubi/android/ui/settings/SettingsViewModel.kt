package com.doubi.android.ui.settings

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.doubi.android.core.config.AppConfig
import com.doubi.android.data.config.AppConfigDataStore
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import timber.log.Timber
import javax.inject.Inject

/**
 * 阶段 6 SettingsScreen 的 ViewModel。1:1 对拍桌面版
 * `src/doubi/ui/pages/settings.py:SettingsPage`。
 *
 * 数据流：
 * - `AppConfigDataStore.observe()` —— DataStore Preferences 实时 emit，UI 订阅
 * - `updateField(key, value)` —— 单字段原子写，DataStore reactive 立刻回写到 observe()
 *
 * 桌面版「需重启」限制：改 `output_root` / `database_path` 等需要重启生效；
 * Android 端 DataStore 是 reactive 的，**所有字段改完立即生效**，**例外是并发数
 * 在跑的 worker 不感知**——这是 v0.2.1 跟桌面版的差异（v0.2.2 阶段 7 用 Process kill
 * 已入队 worker 让新并发数生效）。
 */
@HiltViewModel
class SettingsViewModel @Inject constructor(
    private val configStore: AppConfigDataStore,
) : ViewModel() {

    val state: StateFlow<State> = configStore.observe()
        .map { config -> State(config = config) }
        .stateIn(
            scope = viewModelScope,
            started = SharingStarted.WhileSubscribed(5_000L),
            initialValue = State(),
        )

    private val _events = MutableStateFlow<Event?>(null)
    val events: StateFlow<Event?> = _events.asStateFlow()

    fun onFieldChanged(key: String, value: Any?) {
        viewModelScope.launch {
            try {
                configStore.updateField(key, value)
                _events.value = Event.Saved(key)
            } catch (e: Throwable) {
                Timber.e(e, "updateField failed for %s", key)
                _events.value = Event.Failure(key, e.message ?: "save failed")
            }
        }
    }

    fun onEventShown() {
        _events.value = null
    }

    data class State(
        val config: AppConfig = AppConfig(),
    )

    sealed class Event {
        data class Saved(val key: String) : Event()
        data class Failure(val key: String, val error: String) : Event()
    }
}
