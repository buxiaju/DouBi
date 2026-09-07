package com.doubi.android.core.util

import com.google.common.truth.Truth.assertThat
import kotlinx.coroutines.test.runTest
import org.junit.Test

/**
 * 阶段 20 v0.5.10：[TimeBasedCache] 单测。
 *
 * **覆盖**（6 例）：
 * 1. `getOrLoad` 缓存未命中 → 调 loader，缓存新值
 * 2. `getOrLoad` 缓存命中且未过期 → 不调 loader，返缓存值
 * 3. `getOrLoad` 缓存已过期 → 重新调 loader，刷新缓存
 * 4. `getOrLoad` loader 返 null → 抛 IllegalStateException
 * 5. `invalidate` 强制下次 getOrLoad 重新加载
 * 6. `clear` 清空所有缓存 + `size()` 反映条目数
 *
 * **v0.5.10 设计决定**：[getOrLoad] 是 `suspend`（loader 是 `suspend () -> V`）—— 配合
 * `withContext(Dispatchers.IO)` 跑阻塞 HTTP / disk I/O，**不**阻塞调用方协程。
 * 单测用 `runTest` 包装所有 [getOrLoad] 调用。
 */
class TimeBasedCacheTest {

    /**
     * 可控时间 clock 辅助——手动驱动时间推进，**不**用 sleep。
     */
    private class FakeClock {
        var now: Long = 0L
        operator fun invoke(): Long = now
        fun advance(millis: Long) { now += millis }
    }

    @Test
    fun `getOrLoad calls loader on cache miss and caches the result`() = runTest {
        val cache = TimeBasedCache<String, String>(ttlMillis = 5_000, clock = { 0L })
        var callCount = 0
        val loader: suspend () -> String = { callCount++; "value" }

        val result = cache.getOrLoad("key", loader)

        assertThat(result).isEqualTo("value")
        assertThat(callCount).isEqualTo(1)
        assertThat(cache.size()).isEqualTo(1)
    }

    @Test
    fun `getOrLoad returns cached value without calling loader on cache hit`() = runTest {
        val clock = FakeClock()
        val cache = TimeBasedCache<String, String>(ttlMillis = 5_000, clock = { clock() })
        var callCount = 0
        val loader: suspend () -> String = { callCount++; "value" }

        // 首次：缓存未命中
        cache.getOrLoad("key", loader)
        assertThat(callCount).isEqualTo(1)

        // 时间推进 1s（**未**过 5s TTL）—— 缓存命中
        clock.advance(1_000)
        val result = cache.getOrLoad("key", loader)
        assertThat(result).isEqualTo("value")
        // loader **不**被调第二次
        assertThat(callCount).isEqualTo(1)
    }

    @Test
    fun `getOrLoad reloads when cache has expired past TTL`() = runTest {
        val clock = FakeClock()
        val cache = TimeBasedCache<String, String>(ttlMillis = 5_000, clock = { clock() })
        var callCount = 0
        val loader: suspend () -> String = { callCount++; "value-$callCount" }

        // 首次：缓存未命中
        val first = cache.getOrLoad("key", loader)
        assertThat(first).isEqualTo("value-1")
        assertThat(callCount).isEqualTo(1)

        // 时间推进 6s（**过** 5s TTL）—— 缓存过期
        clock.advance(6_000)
        val second = cache.getOrLoad("key", loader)
        // loader **被**调第二次，返新值
        assertThat(second).isEqualTo("value-2")
        assertThat(callCount).isEqualTo(2)
    }

    @Test
    fun `getOrLoad throws IllegalStateException when loader returns null`() = runTest {
        // Kotlin `checkNotNull` 抛 IllegalStateException（**不**是 NullPointerException）
        val cache = TimeBasedCache<String, String?>(ttlMillis = 5_000, clock = { 0L })
        val loader: suspend () -> String? = { null }

        val ex = runCatching { cache.getOrLoad("key", loader) }.exceptionOrNull()
        assertThat(ex).isInstanceOf(IllegalStateException::class.java)
        assertThat(ex!!.message!!).contains("loader returned null")
        // 缓存**不**被污染
        assertThat(cache.size()).isEqualTo(0)
    }

    @Test
    fun `invalidate forces next getOrLoad to reload`() = runTest {
        val clock = FakeClock()
        val cache = TimeBasedCache<String, String>(ttlMillis = 5_000, clock = { clock() })
        var callCount = 0
        val loader: suspend () -> String = { callCount++; "value-$callCount" }

        cache.getOrLoad("key", loader)
        assertThat(callCount).isEqualTo(1)

        // **不**推进时间，直接 invalidate → 缓存被清
        cache.invalidate("key")
        val result = cache.getOrLoad("key", loader)
        // 重新调 loader
        assertThat(result).isEqualTo("value-2")
        assertThat(callCount).isEqualTo(2)
    }

    @Test
    fun `clear removes all entries and size reflects remaining count`() = runTest {
        val cache = TimeBasedCache<String, String>(ttlMillis = 5_000, clock = { 0L })

        // 3 个 key
        cache.getOrLoad("key1") { "v1" }
        cache.getOrLoad("key2") { "v2" }
        cache.getOrLoad("key3") { "v3" }
        assertThat(cache.size()).isEqualTo(3)

        cache.clear()
        assertThat(cache.size()).isEqualTo(0)

        // clear 后调 loader 重新加载
        var callCount = 0
        val loader: suspend () -> String = { callCount++; "v" }
        cache.getOrLoad("key1", loader)
        assertThat(callCount).isEqualTo(1)
    }
}
