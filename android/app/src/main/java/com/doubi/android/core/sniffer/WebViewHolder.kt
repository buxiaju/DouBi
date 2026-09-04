package com.doubi.android.core.sniffer

import android.content.Context
import android.webkit.WebView
import androidx.annotation.VisibleForTesting
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 阶段 10 v0.5.0 / 阶段 11 v0.5.1：headless browser 嗅探（WebView 集成）——共享不可见 WebView 单例。
 *
 * **v0.5.0 阶段 10**（baseline）：
 * - `@ApplicationContext` 注入 + `@Singleton` 作用域
 * - 0 size `ViewGroup.LayoutParams(0, 0)` + `visibility = View.GONE`（attach 到
 *   view hierarchy 但实际不渲染——WebView 必须 attach 才能 loadUrl）
 * - `by lazy` 初始化（避免冷启动阻塞 Application.onCreate）
 * - `Mutex.withLock { ... }` 串行化多 sniff 任务（WebView 是单线程组件不能并发 loadUrl）
 * - 共享 WebView 常驻 ~30-50MB
 *
 * **v0.5.1 阶段 11**（idle release / re-create）：
 * - 抽出 [WebViewFactory] interface，WebView 创建由 [DefaultWebViewFactory] 负责
 *   ——单测可以 mockk 工厂验证创建/复用/release 契约
 * - 替换 `by lazy` 为手动 `var current: WebView? = null` + `getOrCreate()`
 * - 加 idle 计时：[withLock] 退出后启动 [IDLE_TIMEOUT_MS] 计时器，到期后释放 WebView
 * - 新 sniff 到来时 `cancelAndJoin` 取消挂起的 release（保留 WebView 复用）
 * - 加 [releaseNow] 立即释放（测试用 + 紧急内存压力场景）
 * - 加 [isCreated] / [hasPendingRelease] 测试探针
 *
 * **为什么 idle release**：
 * - 共享 WebView 常驻 ~30-50MB 不可忽视——自用场景下嗅探不频繁，idle 期内存浪费
 * - 30s 是经验值：sniff 任务本身 5s 超时，连续嗅探间隔通常 < 5s（用户连点 URL），30s 够用
 * - 真要频繁嗅探（自动化测试 / 后台爬虫）可通过继承 override [IDLE_TIMEOUT_MS] 调小
 *
 * **线程安全**：
 * - WebView 创建 / loadUrl / WebViewClient callback / `destroy()` 都必须在 Main 线程
 * - [withLock] 内部用 [Mutex] 串行化 sniff
 * - release 协程在 [CoroutineScope] 里跑（Main.immediate dispatcher）
 * - [releaseJob] 字段是单写多读模式：只在 [withLock] 入口 / [scheduleRelease] / [releaseNow] 写
 *
 * **v0.5.1 局限**：
 * - cancelAndJoin 在 release 已开始执行 `destroy()` 时会等待销毁完成（chromium
 *   teardown 几十 ms）——单用户自用可接受
 * - [current] 字段 `[Volatile]` 保证跨线程读可见性（虽然实际都在 Main，但 [isCreated]
 *   测试探针在非 Main 线程读）
 */
@Singleton
class WebViewHolder @Inject constructor(
    @ApplicationContext private val context: Context,
    private val factory: WebViewFactory,
) {
    private val mutex = Mutex()

    /**
     * release 协程用的 scope。`Main.immediate` 保证 destroy() 在 Main 线程调用；
     * `SupervisorJob` 让单个 release 失败不影响其它 release。
     *
     * 生命周期 = Singleton 生命周期 = Application 生命周期——不显式 cancel。
     */
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)

    @Volatile
    private var current: WebView? = null

    /**
     * 当前挂起的 release 协程。`null` 表示没有挂起的 release。
     *
     * 三处写入：
     * 1. [withLock] 入口：`cancelAndJoin` + `releaseJob = null` 取消旧 release
     * 2. [scheduleRelease]：新 release 启动时赋值
     * 3. [releaseNow] / release job 自身销毁完成后：置 null
     */
    private var releaseJob: Job? = null

    /**
     * 串行化嗅探访问。WebView 是单线程组件，多个 sniff 并发时只能串行
     * 排队（等上一个 onPageFinished 完成才能 loadUrl 下一个）。
     *
     * 用 [Mutex]（不是 `@Synchronized`）——suspend lambda 允许 `delay` /
     * `withTimeout` 等协程操作。
     *
     * **流程**：
     * 1. 取消挂起的 release（`cancelAndJoin` 等待旧 release 销毁完成再继续）
     * 2. 拿 [Mutex] 串行化
     * 3. 当前 WebView 不存在就 [factory.create] 一个
     * 4. 跑 [block]
     * 5. `finally` 调度 [scheduleRelease]——[IDLE_TIMEOUT_MS] 后释放
     */
    suspend fun <T> withLock(block: suspend (WebView) -> T): T {
        // 取消挂起的 release 并等待其完成（避免旧 release 销毁 WebView 时新 sniff 复用）
        releaseJob?.cancelAndJoin()
        releaseJob = null

        return mutex.withLock {
            val wv = current ?: factory.create(context).also { current = it }
            try {
                block(wv)
            } finally {
                scheduleRelease()
            }
        }
    }

    /**
     * 调度 [IDLE_TIMEOUT_MS] 后释放当前 WebView。
     *
     * release 流程：
     * 1. `delay(IDLE_TIMEOUT_MS)`——这段时间内任何 sniff 都会 cancel 它
     * 2. 重新拿 [Mutex]（避免和并发 sniff 抢 WebView）
     * 3. `stopLoading()` + `loadUrl("about:blank")` + `destroy()`
     * 4. `current = null`，`releaseJob = null`
     *
     * **取消语义**：[delay] 是 suspend point，[CancellationException] 被 catch 吞掉，
     * release 协程静默退出，WebView 保留。
     */
    private fun scheduleRelease() {
        releaseJob = scope.launch {
            try {
                delay(IDLE_TIMEOUT_MS)
                // 重新拿锁——确保 destroy 期间没有 sniff 正在用
                mutex.withLock {
                    current?.let { wv ->
                        current = null
                        releaseJob = null
                        wv.stopLoading()
                        wv.loadUrl("about:blank")
                        wv.destroy()
                    }
                }
            } catch (_: CancellationException) {
                // 被下一个 sniff 取消——保留 WebView
            }
        }
    }

    /**
     * 立即释放 WebView（不等 idle 计时）。
     *
     * **测试用 + 紧急内存压力场景**。
     *
     * 流程：取消挂起 release → 拿锁 → 销毁 WebView → 清空 current。
     */
    @VisibleForTesting
    suspend fun releaseNow() {
        releaseJob?.cancelAndJoin()
        releaseJob = null
        mutex.withLock {
            current?.let { wv ->
                current = null
                wv.stopLoading()
                wv.loadUrl("about:blank")
                wv.destroy()
            }
        }
    }

    /**
     * WebView 是否已创建（且未被释放）。测试探针。
     */
    @VisibleForTesting
    fun isCreated(): Boolean = current != null

    /**
     * 是否有挂起的 idle release 任务。测试探针。
     */
    @VisibleForTesting
    fun hasPendingRelease(): Boolean = releaseJob?.isActive == true

    companion object {
        /**
         * idle 计时时长（ms）。最后一次 [withLock] 退出后等这么久释放 WebView。
         *
         * 经验值：sniff 单次 5s 超时，连续嗅探间隔通常 < 5s（用户连点 URL），
         * 30s 够覆盖高频嗅探场景，避免不必要的销毁/重建。
         */
        const val IDLE_TIMEOUT_MS = 30_000L
    }
}
