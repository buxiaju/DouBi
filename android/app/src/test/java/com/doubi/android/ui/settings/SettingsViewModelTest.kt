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

    // ---- 阶段 9 v0.4.1 C2：补 13 个字段级 onFieldChanged 测试 ----
    // C2 范围原计划 Compose UI test，但自用环境没装真机/模拟器/Rolectric——单测只能
    // 走 ViewModel 字段级覆盖。SettingsScreen 新增 4 个 Section（13 字段）：
    // theme / duplicate_policy / engine / aria2_rpc_url / sniff_enabled / sniff_duration_sec
    // / sniff_headless / sniff_user_agent / sniff_auto_play / write_nfo / write_metadata_json
    // / write_danmaku 共 12 字段 + 原有 theme 单测 = 13 字段级 case。

    @Test
    fun `onFieldChanged theme with default_light invokes updateField and emits Saved`() = runTest {
        val store = mockStore()
        coEvery { store.updateField("theme", "default_light") } returns Unit
        val vm = SettingsViewModel(store)

        vm.onFieldChanged("theme", "default_light")
        coVerify { store.updateField("theme", "default_light") }
        assertThat(vm.events.value).isInstanceOf(SettingsViewModel.Event.Saved::class.java)
    }

    @Test
    fun `onFieldChanged theme with system invokes updateField`() = runTest {
        // v0.4.1 新增的"system"值——v0.1 阶段 0 仅有 default_light / default_dark
        val store = mockStore()
        coEvery { store.updateField("theme", "system") } returns Unit
        val vm = SettingsViewModel(store)

        vm.onFieldChanged("theme", "system")
        coVerify { store.updateField("theme", "system") }
    }

    @Test
    fun `onFieldChanged duplicate_policy with redownload`() = runTest {
        val store = mockStore()
        coEvery { store.updateField("duplicate_policy", "redownload") } returns Unit
        val vm = SettingsViewModel(store)

        vm.onFieldChanged("duplicate_policy", "redownload")
        coVerify { store.updateField("duplicate_policy", "redownload") }
    }

    @Test
    fun `onFieldChanged engine with aria2 invokes updateField`() = runTest {
        // v0.4.1 新增的 engine dropdown 选项
        val store = mockStore()
        coEvery { store.updateField("engine", "aria2") } returns Unit
        val vm = SettingsViewModel(store)

        vm.onFieldChanged("engine", "aria2")
        coVerify { store.updateField("engine", "aria2") }
    }

    @Test
    fun `onFieldChanged aria2_rpc_url invokes updateField with full URL`() = runTest {
        val store = mockStore()
        coEvery { store.updateField("aria2_rpc_url", "http://192.168.1.10:6800/jsonrpc") } returns Unit
        val vm = SettingsViewModel(store)

        vm.onFieldChanged("aria2_rpc_url", "http://192.168.1.10:6800/jsonrpc")
        coVerify { store.updateField("aria2_rpc_url", "http://192.168.1.10:6800/jsonrpc") }
    }

    @Test
    fun `onFieldChanged sniff_enabled boolean true invokes updateField`() = runTest {
        val store = mockStore()
        coEvery { store.updateField("sniff_enabled", true) } returns Unit
        val vm = SettingsViewModel(store)

        vm.onFieldChanged("sniff_enabled", true)
        coVerify { store.updateField("sniff_enabled", true) }
    }

    @Test
    fun `onFieldChanged sniff_duration_sec with 15`() = runTest {
        val store = mockStore()
        coEvery { store.updateField("sniff_duration_sec", 15) } returns Unit
        val vm = SettingsViewModel(store)

        vm.onFieldChanged("sniff_duration_sec", 15)
        coVerify { store.updateField("sniff_duration_sec", 15) }
    }

    @Test
    fun `onFieldChanged sniff_headless boolean`() = runTest {
        val store = mockStore()
        coEvery { store.updateField("sniff_headless", false) } returns Unit
        val vm = SettingsViewModel(store)

        vm.onFieldChanged("sniff_headless", false)
        coVerify { store.updateField("sniff_headless", false) }
    }

    @Test
    fun `onFieldChanged sniff_user_agent invokes updateField with full UA string`() = runTest {
        val store = mockStore()
        val ua = "Mozilla/5.0 (Linux; Android 14)"
        coEvery { store.updateField("sniff_user_agent", ua) } returns Unit
        val vm = SettingsViewModel(store)

        vm.onFieldChanged("sniff_user_agent", ua)
        coVerify { store.updateField("sniff_user_agent", ua) }
    }

    @Test
    fun `onFieldChanged sniff_auto_play boolean`() = runTest {
        val store = mockStore()
        coEvery { store.updateField("sniff_auto_play", true) } returns Unit
        val vm = SettingsViewModel(store)

        vm.onFieldChanged("sniff_auto_play", true)
        coVerify { store.updateField("sniff_auto_play", true) }
    }

    @Test
    fun `onFieldChanged write_nfo boolean`() = runTest {
        val store = mockStore()
        coEvery { store.updateField("write_nfo", true) } returns Unit
        val vm = SettingsViewModel(store)

        vm.onFieldChanged("write_nfo", true)
        coVerify { store.updateField("write_nfo", true) }
    }

    @Test
    fun `onFieldChanged write_metadata_json boolean`() = runTest {
        val store = mockStore()
        coEvery { store.updateField("write_metadata_json", true) } returns Unit
        val vm = SettingsViewModel(store)

        vm.onFieldChanged("write_metadata_json", true)
        coVerify { store.updateField("write_metadata_json", true) }
    }

    @Test
    fun `onFieldChanged write_danmaku boolean`() = runTest {
        val store = mockStore()
        coEvery { store.updateField("write_danmaku", false) } returns Unit
        val vm = SettingsViewModel(store)

        vm.onFieldChanged("write_danmaku", false)
        coVerify { store.updateField("write_danmaku", false) }
    }

    // ---- helpers ----

    private fun mockStore(): AppConfigDataStore {
        val store: AppConfigDataStore = mockk(relaxed = false)
        every { store.observe() } returns MutableStateFlow(AppConfig())
        return store
    }
}
