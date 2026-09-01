package com.doubi.android.data.config

import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import androidx.datastore.preferences.core.Preferences
import com.doubi.android.core.config.AppConfig
import com.doubi.android.core.config.AppConfig.DEFAULTS
import com.google.common.truth.Truth.assertThat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import org.junit.After
import org.junit.Before
import org.junit.Test
import org.junit.rules.TemporaryFolder
import org.junit.Rule
import java.io.File

/**
 * AppConfigDataStore 单元测试。
 *
 * 桌面版对照：`tests/test_config_theme.py::TestConfigTheme::test_*`。
 * Android 端用临时目录 + 真实 DataStore 实例跑全链路（写 → 读 → 校验），
 * 不 mock 任何东西——DataStore 自身的写入/读取契约才是要验证的对象。
 */
class AppConfigDataStoreTest {

    @get:Rule
    val tempFolder = TemporaryFolder()

    private lateinit var scope: CoroutineScope
    private lateinit var dataStore: DataStore<Preferences>
    private lateinit var repo: AppConfigDataStore

    @Before
    fun setUp() {
        scope = CoroutineScope(Dispatchers.IO + Job())
        val file = File(tempFolder.newFolder(), "test_config.preferences_pb")
        dataStore = PreferenceDataStoreFactory.create(
            scope = scope,
            produceFile = { file },
        )
        repo = AppConfigDataStore(dataStore)
    }

    @After
    fun tearDown() {
        scope.cancel()
    }

    // ---------------------------------------------------------------------
    // 默认值
    // ---------------------------------------------------------------------

    @Test
    fun `empty datastore returns full default AppConfig`() = runTest {
        val cfg = repo.get()
        // 关键字段逐一对照 DEFAULTS（不写完所有 30 个，只抽几根台柱）
        assertThat(cfg.concurrentJobs).isEqualTo(DEFAULTS.concurrentJobs)
        assertThat(cfg.theme).isEqualTo(DEFAULTS.theme)
        assertThat(cfg.engine).isEqualTo(DEFAULTS.engine)
        assertThat(cfg.notifyOnCompletion).isEqualTo(DEFAULTS.notifyOnCompletion)
        assertThat(cfg.sniffEnabled).isEqualTo(DEFAULTS.sniffEnabled)
        assertThat(cfg.sniffDurationSec).isEqualTo(DEFAULTS.sniffDurationSec)
        assertThat(cfg.rateLimit).isNull()
        assertThat(cfg.proxy).isNull()
        assertThat(cfg.aria2Secret).isNull()
    }

    // ---------------------------------------------------------------------
    // 整体写入 + 读回
    // ---------------------------------------------------------------------

    @Test
    fun `save then get roundtrips all 30 fields`() = runTest {
        val custom = AppConfig(
            outputRoot = "/custom/dir",
            concurrentJobs = 8,
            theme = "default_dark",
            language = "en",
            engine = "yt-dlp",
            notifyOnCompletion = "all",
            sniffEnabled = false,
            sniffDurationSec = 30,
            proxy = "http://127.0.0.1:7890",
            aria2Secret = "my-secret",
            writeNfo = true,
        )
        repo.save(custom)
        val read = repo.get()
        assertThat(read).isEqualTo(custom)
    }

    @Test
    fun `nullable fields roundtrip null correctly`() = runTest {
        // 把 3 个 nullable string 都设 null，存空串，读回 null
        repo.save(AppConfig(rateLimit = null, proxy = null, aria2Secret = null))
        val read = repo.get()
        assertThat(read.rateLimit).isNull()
        assertThat(read.proxy).isNull()
        assertThat(read.aria2Secret).isNull()
    }

    @Test
    fun `sniff_capture_types roundtrips as set, ordered on read`() = runTest {
        // 桌面版 tuple 有序；DataStore Set 无序——读出时按字母排序
        val original = listOf("application/dash+xml", "video/mp4", "video/webm")
        repo.save(AppConfig(sniffCaptureTypes = original))
        val read = repo.get()
        // 写进去的 3 个，set 读出后 sorted，再变回 list——内容一致，顺序按字母
        assertThat(read.sniffCaptureTypes).containsExactly(
            "application/dash+xml", "video/mp4", "video/webm",
        )
    }

    // ---------------------------------------------------------------------
    // 校验与回退
    // ---------------------------------------------------------------------

    @Test
    fun `corrupt notify_on_completion falls back to default on read`() = runTest {
        // 模拟「脏数据」：直接用 updateField 写非法值
        repo.updateField("notify_on_completion", "always-shout")
        // 读出时被 ConfigValidator 改成默认
        val read = repo.get()
        assertThat(read.notifyOnCompletion).isEqualTo(DEFAULTS.notifyOnCompletion)
    }

    @Test
    fun `corrupt engine falls back to yt-dlp`() = runTest {
        repo.updateField("engine", "ffmpeg-cli")
        assertThat(repo.get().engine).isEqualTo("yt-dlp")
    }

    @Test
    fun `updateField concurrent_jobs clamps to 1-16`() = runTest {
        repo.updateField("concurrent_jobs", 9999)
        assertThat(repo.get().concurrentJobs).isEqualTo(16)
        repo.updateField("concurrent_jobs", 0)
        assertThat(repo.get().concurrentJobs).isEqualTo(1)
    }

    @Test
    fun `updateField sniff_duration_sec clamps to 5-60`() = runTest {
        repo.updateField("sniff_duration_sec", 999)
        assertThat(repo.get().sniffDurationSec).isEqualTo(60)
    }

    @Test
    fun `updateField proxy null becomes empty string in storage but null on read`() = runTest {
        // 桌面版 Optional[str] 在 YAML 里就是缺失；Android 端 Preferences 没有 nullable string，
        // 用空串当 sentinel。读出时 .takeIf { it.isNotEmpty() } 转回 null。
        repo.save(AppConfig(proxy = "http://foo:8080"))
        assertThat(repo.get().proxy).isEqualTo("http://foo:8080")
        repo.updateField("proxy", null)
        assertThat(repo.get().proxy).isNull()
    }

    // ---------------------------------------------------------------------
    // 观察流
    // ---------------------------------------------------------------------

    @Test
    fun `observe emits on change`() = runTest {
        repo.updateField("concurrent_jobs", 5)
        val cfg = repo.observe().first()
        assertThat(cfg.concurrentJobs).isEqualTo(5)
    }

    @Test(expected = IllegalArgumentException::class)
    fun `updateField unknown key throws`() = runTest {
        repo.updateField("nonexistent_key", "x")
    }
}
