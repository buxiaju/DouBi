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
        // 阶段 0 锁 v0.1.0
        assertThat(BuildConfig.VERSION_NAME).startsWith("0.1")
    }
}
