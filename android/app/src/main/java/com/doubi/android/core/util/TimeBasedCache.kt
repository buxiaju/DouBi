package com.doubi.android.core.util

import java.util.concurrent.ConcurrentHashMap

/**
 * 阶段 20 v0.5.10：通用 TTL 内存缓存。
 *
 * **v0.5.10 范围**：5min TTL 内存缓存，线程安全（[ConcurrentHashMap]），用于 B 站 API
 * 客户端的 mixin_key / view / playurl 三个端点——避免重复 HTTP 调用。
 *
 * **架构**：
 * - 抽成独立 utility（**不**放 [com.doubi.android.core.platform.bilibili.BilibiliApiClient] 内）——
 *   单一职责 + 单元可测
 * - 用 Kotlin [ConcurrentHashMap] 保证线程安全（协程多并发读 / 单写场景）
 * - 注入 [clock] 函数（默认 [System.currentTimeMillis]）—— 单测可控时间
 *
 * **设计取舍**：
 * - **不**做主动清理（lazy expiry on read 足够）—— 5min TTL + 3-5 个 key 内存占用可忽略
 * - **不**做持久化——缓存**仅**在进程生命周期内有效（应用重启缓存清空，符合"5min TTL"语义）
 * - **不**做 LRU 淘汰——5min TTL + 单进程 3-5 个 key 的场景**不**需要
 * - **不**支持 null V（[getOrLoad] 抛 [NullPointerException]）—— 缓存**只**缓存"成功结果"，
 *   失败由调用方 retry / fallback
 *
 * **vs ConcurrentHashMap with expire**：
 * - 不用 `Caffeine` / `Guava Cache`——外部依赖重，Kotlin 标准库足够
 * - 不用 `androidx.collection.LruCache`——**不**支持 TTL（**只**支持 size-based 淘汰）
 * - 手写 30 行 Kotlin 实现——可读、可测、零依赖
 *
 * **使用示例**（[BilibiliApiClient.fetchMixinKey]）：
 * ```kotlin
 * private val mixinKeyCache = TimeBasedCache<String>(ttlMillis = 5 * 60 * 1000)
 *
 * suspend fun fetchMixinKey(): String = withContext(Dispatchers.IO) {
 *     mixinKeyCache.getOrLoad("global") {
 *         // HTTP 调用 + parse
 *     }
 * }
 * ```
 */
class TimeBasedCache<K, V>(
    private val ttlMillis: Long,
    private val clock: () -> Long = { System.currentTimeMillis() },
) {
    private data class Entry<V>(val value: V, val expiresAt: Long)

    private val map = ConcurrentHashMap<K, Entry<V>>()

    /**
     * Get-or-load 模式：缓存命中且未过期返缓存值；否则调 [loader] 重新加载并缓存。
     *
     * **suspend 设计**：[loader] 是挂起函数（`suspend () -> V`）—— 配合 `withContext(Dispatchers.IO)`
     * 跑阻塞 HTTP / disk I/O，**不**阻塞调用方协程。
     *
     * **线程安全**：[ConcurrentHashMap] 原子——并发首次访问只调一次 [loader]。
     *
     * @param key 缓存键（任意可哈希类型）
     * @param loader 缓存未命中时调用的加载函数（**suspend**——可调 HTTP / disk I/O）
     * @return 缓存值或新加载值
     */
    suspend fun getOrLoad(key: K, loader: suspend () -> V): V {
        val now = clock()
        val entry = map[key]
        if (entry != null && entry.expiresAt > now) {
            return entry.value
        }
        // 缓存未命中 / 已过期——调 loader
        val value = loader()
        // 防御性编程：loader 返 null → 抛 ISE 避免污染缓存（缓存**只**存成功值）
        checkNotNull(value) { "TimeBasedCache loader returned null for key=$key" }
        map[key] = Entry(value, now + ttlMillis)
        return value
    }

    /**
     * 显式失效某个 key（force re-load 下次 getOrLoad）。
     *
     * **使用场景**：
     * - B 站 API 返 -352 风控（mixin_key 失效）→ 立即失效缓存
     * - 用户手动刷新（settings 改 UserAgent）→ 失效依赖 UA 的缓存
     */
    fun invalidate(key: K) {
        map.remove(key)
    }

    /**
     * 清空所有缓存（force re-load 所有 key）。
     *
     * **使用场景**：测试 / debug 时强制刷新所有缓存。
     */
    fun clear() {
        map.clear()
    }

    /**
     * 当前缓存条目数（含已过期条目——lazy expiry 不主动清理）。
     */
    fun size(): Int = map.size
}
