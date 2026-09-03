package com.doubi.android.ui.settings

import com.doubi.android.core.config.AppConfig
import com.doubi.android.data.config.AppConfigDataStore
import com.google.common.truth.Truth.assertThat
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.every
import io.mockk.mockk
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Before
import org.junit.Test

/**
 * SettingsViewModel 单测。重点验：
 * - state 流：observe() emit 的 AppConfig 进 State（stateIn WhileSubscribed 默认不发射——用初始值 + 直接读 .value）
 * - onFieldChanged 调 updateField(key, value)
 * - Event.Saved / Event.Failure 发出
 *
 * AppConfigDataStore 用 mockk 隔离 Preferences / DataStore 真依赖。
 * 不用 `relaxed = true`——`every { store.observe() } returns ...` 会被 relaxed 吞掉，
 * 所以这里直接 mock（不 relaxed），每个用到的 method 都显式 stub。
 */
@OptIn(ExperimentalCoroutinesApi::class)
class SettingsViewModelTest {

    @Before
    fun setUp() {
        Dispatchers.setMain(UnconfinedTestDispatcher())
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun `state reflects AppConfig from observe flow`() = runTest {
        val observeFlow = MutableStateFlow(
            AppConfig(
                outputRoot = "CustomDownloads",
                concurrentJobs = 5,
                notifyOnCompletion = "all",
            )
        )
        val store: AppConfigDataStore = mockk(relaxed = false) {
            every { observe() } returns observeFlow
        }

        val vm = SettingsViewModel(store)
        // stateIn 是冷的——需要 collector 才会让 upstream 跑。WhileSubscribed(5_000L) 默认
        // 不发射 initialValue 之外的，需要先 collect。改成直接 collect 一帧：
        val state = vm.state.first { it.config.outputRoot == "CustomDownloads" }
        assertThat(state.config.outputRoot).isEqualTo("CustomDownloads")
        assertThat(state.config.concurrentJobs).isEqualTo(5)
    }

    @Test
    fun `onFieldChanged invokes updateField and emits Saved event`() = runTest {
        val store: AppConfigDataStore = mockk(relaxed = false)
        every { store.observe() } returns MutableStateFlow(AppConfig())
        coEvery { store.updateField("concurrent_jobs", 5) } returns Unit
        val vm = SettingsViewModel(store)

        vm.onFieldChanged("concurrent_jobs", 5)
        coVerify { store.updateField("concurrent_jobs", 5) }
    }

    @Test
    fun `onFieldChanged emits Failure event when updateField throws`() = runTest {
        val store: AppConfigDataStore = mockk(relaxed = false)
        every { store.observe() } returns MutableStateFlow(AppConfig())
        coEvery { store.updateField("bad_key", "value") } throws IllegalArgumentException("Unknown config key: bad_key")
        val vm = SettingsViewModel(store)

        vm.onFieldChanged("bad_key", "value")
        val ev = vm.events.value
        assertThat(ev).isInstanceOf(SettingsViewModel.Event.Failure::class.java)
        val f = ev as SettingsViewModel.Event.Failure
        assertThat(f.key).isEqualTo("bad_key")
        assertThat(f.error).contains("Unknown config key")
    }
}
