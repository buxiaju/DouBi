package com.doubi.android

import com.google.common.truth.Truth.assertThat
import org.junit.Test

/**
 * 阶段 0 烟雾测试——确认 JUnit + Truth 工具链通。
 * 阶段 1 起会被真实测试覆盖（见 ../docs/REUSE-MAP.md 测试用例数估算）。
 */
class ExampleUnitTest {
    @Test
    fun `version name is set`() {
        assertThat(BuildConfig.VERSION_NAME).isNotEmpty()
        // 阶段 0 锁 v0.1.0；阶段 7 升到 v0.3.0；阶段 8 升到 v0.4.0；阶段 9 升到 v0.4.1；阶段 10 升到 v0.5.0
        // 改 asserts 测当前 major.minor——v0.5.0 阶段是 0.5
        assertThat(BuildConfig.VERSION_NAME).startsWith("0.5")
    }
}
