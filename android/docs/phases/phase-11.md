# 阶段 11 复盘：WebViewHolder idle 30s release（✅ 完成 → v0.5.1-android）

> **最终状态**：阶段 11 收官。**WebViewHolder 单例常驻 ~30-50MB 内存问题修掉**——v0.5.0 阶段 10 留下的「`@Singleton` 常驻」风险（phase-10 决定 1 / 决定 5）落地：抽出 [WebViewFactory] interface + idle 30s 计时器 + 测试探针三件套。209/209 单测全绿（v0.5.0 204 + 5 新增），`assembleDebug` 通过。
> **v0.5.0-android tag 已发**（阶段 10 收官），本阶段成果属 v0.5.1-android tag。

## 一句话总结

本阶段做了 **3 类事情**（按 commit 顺序）：

1. **抽 [WebViewFactory] interface** + **[DefaultWebViewFactory] 实现**——把 v0.5.0 阶段 10 写死的 `WebView(context).apply { ... }` 配置块从 `WebViewHolder` 拆出来，让 holder 单测可以 mockk 工厂验证「创建时机 / 复用 / release 触发 destroy」契约
2. **WebViewHolder idle release 重构**——`by lazy` 换成手动 `var current: WebView? = null` + `getOrCreate()` 模式 + CoroutineScope 30s 计时器 + `cancelAndJoin` 取消挂起 release + `releaseNow()` 紧急释放
3. **WebViewHolderTest 5 例**——首次创建 / 多次复用 / `releaseNow` 立即释放 / 30s 自动释放 / 窗口内 cancel

**没做**（v0.5.2+ 单独 PR）：
- WebView 自身 0 size / GONE / JS enabled 配置的单测覆盖——这些是 Android framework 行为，单测 mockk 出的 WebView 不走真实代码，需要 Robolectric 或真机验证
- WebViewHeadlessSniffer 自身单测（v0.5.0 留的欠账，需要 Robolectric）
- m3u8 内容解析（v0.5.0 留的欠账）
- ANR 风险测试（v0.5.0 留的欠账）
- BilibiliAdapter / 抖音 adapter（新功能）

---

## 一、改了什么

### 新增文件

| 路径 | 作用 |
|---|---|
| `app/src/main/java/com/doubi/android/core/sniffer/WebViewFactory.kt` | `fun interface` 工厂接口，单元测试可 mockk |
| `app/src/main/java/com/doubi/android/core/sniffer/DefaultWebViewFactory.kt` | 工厂默认实现——v0.5.0 阶段 10 写死的 WebView 配置（0 size / GONE / JS / DOM / cache mode）挪到这里 |
| `app/src/test/java/com/doubi/android/core/sniffer/WebViewHolderTest.kt` | 5 例单测（创建 / 复用 / releaseNow / 30s 自动 / 窗口内 cancel） |

### 修改文件

| 路径 | 变化 |
|---|---|
| `app/src/main/java/com/doubi/android/core/sniffer/WebViewHolder.kt` | 重构：`by lazy` 拆掉；加 `@Volatile current: WebView?` + `releaseJob: Job?` + `CoroutineScope(SupervisorJob() + Main.immediate)`；`withLock` 入口 `cancelAndJoin` 旧 release；`finally { scheduleRelease() }` 调度新 release；`@VisibleForTesting` 加 `releaseNow()` / `isCreated()` / `hasPendingRelease()`；`IDLE_TIMEOUT_MS = 30_000L` |
| `app/src/main/java/com/doubi/android/core/sniffer/di/SnifferModule.kt` | + `@Binds bindWebViewFactory(impl: DefaultWebViewFactory): WebViewFactory` |
| `app/build.gradle.kts` | versionCode 8→9；versionName "0.5.0"→"0.5.1" |
| `app/src/test/java/com/doubi/android/ExampleUnitTest.kt` | 注释加「阶段 11 升到 v0.5.1」一行；startsWith 保持 `"0.5"`（v0.5.0 / v0.5.1 都 0.5 prefix） |

### 桌面版 → Android 版

```
桌面版 `src/doubi/core/sniffer.py:WebViewHeadlessSniffer`（Playwright 真 headless）
  ─────────────────────────────────────────────────
  → 阶段 10 v0.5.0：WebViewHeadlessSniffer 用 Android WebView 简化方案
  → 阶段 11 v0.5.1：WebViewHolder 加 idle release——单例常驻 ~30-50MB
    在最后一次 sniff 结束 30s 后释放，下一次 sniff 重新创建
```

桌面版 Playwright 进程由 Playwright 自己管（关闭浏览器自动清理），
不需要手动 idle release。Android 端 WebView 是 Chromium 多进程架构，
没有自动清理机制——v0.5.1 手动实现。

---

## 二、核心设计决定

### 决定 1：抽 [WebViewFactory] interface 是单测可写的必要条件

**问题**：v0.5.0 阶段 10 写的 `WebViewHolder` 是 `class WebViewHolder @Inject constructor(context: Context)`，
里面 `val webView: WebView by lazy { WebView(context).apply { ... } }`。WebView 是 Android framework 真实组件，没法 mockk（要 Robolectric），
所以 [WebViewHolder.withLock] 的「创建时机 / 复用 / release 触发 destroy」契约完全没法测。

**v0.5.1 方案对比**：
- A) 接 Robolectric 框架 + `@Config(sdk = ...)` 跑真实 WebView——v0.5.0 阶段 10 决定 4 明确拒绝
  （自用环境没装 Robolectric）
- B) **抽 [WebViewFactory] interface + [WebViewHolder] 依赖工厂**——单测 mockk 工厂 ✅
- C) 把 `WebView` 整个换成 sealed class / 自建 wrapper——scope 太大

**选 B**：最干净——`WebViewHolder` 只关心"什么时候创建 / 什么时候释放 / 怎么串行化"，
不关心"怎么创建"。

**风险**：抽出后 WebView 创建配置（0 size / GONE / JS enabled / DOM Storage / cache mode）挪到 [DefaultWebViewFactory]，
单测**不能**直接覆盖这些配置（mockk 出的 WebView 不走真实 apply 块）。
需要 Robolectric 或真机验证。v0.5.1+ 留欠账。

### 决定 2：idle 30s 是经验值，不是数学推导

**30s 的依据**：
- 单次 sniff 任务 ≤ 5s 超时（v0.5.0 阶段 10 写死 `timeoutMs = 5_000L`）
- 连续嗅探间隔通常 < 5s（用户连点 URL 列表 / 自动测试场景）
- 30s 远大于单次 sniff 时间，覆盖所有"短时间高频嗅探"场景
- WebView 重建冷启动 ~100-300ms（首次创建加载 Chromium native lib），30s 内连续 sniff
  可以完全复用 WebView，零重建开销
- 长 idle 场景（用户离开 App 5 分钟再回来）会自动释放 ~50MB，足够回血

**对比方案**：
- 60s：太保守，长 idle 场景内存浪费更久
- 10s：太激进，可能让连点 URL 列表的用户频繁触发 WebView 重建
- **30s 是 sweet spot**——既覆盖高频嗅探，又不会让长 idle 场景内存常驻太久

**风险**：极端场景（用户连点 20 个 URL 后停 35s 再点 1 个）会触发 1 次 WebView 重建
（~100-300ms 延迟）。可接受。

### 决定 3：release 用 `Mutex.withLock` 二次拿锁，不是裸 destroy

**问题**：release 流程需要销毁 WebView + 清空 `current` 字段。
如果在 [withLock] 退出后直接 `destroy()`，可能跟下一个 sniff 抢 WebView：
- sniff A 退出，release 启动 destroy
- sniff B 进入 `withLock`，看到 `current != null`，复用 WebView
- release 还在 destroy 同一个 WebView
- **race condition**

**方案对比**：
- A) `withLock` 退出后裸 `destroy()` + `current = null`——race condition
- B) **release 协程自己 `Mutex.withLock` 二次拿锁**——destroy 期间任何 sniff 都阻塞 ✅
- C) 用 `AtomicReference<WebView>` 配合 CAS 原子替换——过度设计

**选 B**：[Mutex] 已经在用，二次拿锁天然避免 race。destroy 期间 sniff 阻塞，等 destroy 完成
`current = null`，sniff 看到 null 触发 `factory.create` 重新建。sniff 0 reuse 但不 race。

**优化（v0.5.1+ 留欠账）**：
- B 方案的代价是：sniff 阻塞几十 ms（chromium teardown）
- 真要优化：release 流程前先 `cancelAndJoin` 检查"有没有新 sniff 等在 mutex 上"——
  如果有就保留 WebView。但这增加复杂度，v0.5.1 简化方案接受 race-free + 偶尔重建。

### 决定 4：`current` 字段 `@Volatile` 是防御性写法

**问题**：[current] 字段在 [withLock] 入口读、在 `release` 流程中写、在 [isCreated] 测试探针中读。
理论上所有操作都在 Main 线程（`withLock` 调 `withContext(Dispatchers.Main)` 之前 / release 协程用 Main.immediate），
不需要 `@Volatile`。

**实际选择**：`@Volatile`。

**理由**：
- 单测里 [isCreated] / [hasPendingRelease] 是测试代码从 JVM 任意线程读
- [WebViewHeadlessSniffer.sniff] 调 `withContext(Dispatchers.Main)` 切到 Main 后才调 [withLock]
  ——但 [isCreated] 在 `withContext` 之前调用的话不在 Main
- `@Volatile` 零成本（现代 JVM 对 volatile 读 ≈ 普通读），避免潜在内存可见性 bug

**风险**：理论上不必要的同步——但写 `volatile` 成本极低，防御性写法是惯例。

### 决定 5：v0.5.1 不做 WebView 自身 0 size / GONE / JS enabled 配置的单测

**问题**：[DefaultWebViewFactory.create] 里的 `WebView(context).apply { ... }` 配置块是 v0.5.0 阶段 10
写死的，单测 mockk 出的 WebView 不走真实 apply 块——单测**不能**直接验证
`layoutParams = ViewGroup.LayoutParams(0, 0)` 真的设置进去了。

**v0.5.1 范围**：只测 [WebViewHolder] 的"创建时机 / 复用 / release 契约"——5 例。
[DefaultWebViewFactory] 的真实配置需要 Robolectric 或真机验证。

**风险**：v0.5.0 阶段 10 决定的「0 size + GONE 不可见」配置如果被改坏（比如误改成 `wrap_content`），
单测**抓不到**——用户会看到一个 0×0 黑色 WebView 短暂出现在屏幕上（< 100ms）。
v0.5.2+ 走 Robolectric 或真机 sideload 跑 instrumented test 覆盖。

---

## 三、坑 & 决策

### 坑 1：`@Synchronized` 不能用在 lazy property delegate

> **这是 v0.5.0 阶段 10 坑 2 复述**——v0.5.1 改造 [WebViewHolder] 时又遇到。

**症状**：v0.5.1 起步时想给 `val current: WebView? by lazy { ... }` 加 `@Synchronized`，
编译报：
```
This annotation is not applicable to target 'member property with delegate'
```

**根因**：Kotlin 的 `@Synchronized` annotation target 是 `function` / `property accessor`，
不能是 `property with delegate`。

**修法**：v0.5.1 直接放弃 `by lazy` 改用手动 `var current: WebView? = null` + `getOrCreate()` 模式——
[决定 1] 抽工厂的同时拆 lazy，顺手把同步问题也解决了。

**教训**：v0.5.0 阶段 10 已经踩过这个坑（@SuppressLint）——v0.5.1 又踩一次（@Synchronized）。
**任何 "property + delegate + annotation" 的组合都要警惕**。

### 坑 2：测试里 `advanceUntilIdle()` 快进时间到 30s 触发 release

**症状**：`withLock reuses existing WebView on subsequent calls` 测试第一次跑挂：
```
expected to be true
  at WebViewHolderTest.kt:83
```

**根因**：测试里调了 `advanceUntilIdle()`——它会把虚拟时间**快进到没有 pending task**，
但 release 协程里有 `delay(30_000)`，所以快进到 30s 后 release 触发，WebView 被销毁。
`isCreated()` 返回 false，断言失败。

**修法**：删掉 `advanceUntilIdle()`——本例只验证"复用 WebView 不重新创建"，
**不**验证 timeout 行为（timeout 行为在 `WebView is released after IDLE_TIMEOUT_MS`
例里独立测）。注释里加"不能调 advanceUntilIdle()——它会快进时间到 30s 触发 release，破坏复用契约"。

**教训**：`StandardTestDispatcher` + `advanceUntilIdle` / `advanceTimeBy` 的组合**是双刃剑**——
`advanceUntilIdle` 会快进到"再没任务"，而 release 任务的 `delay(30_000)` 是
"30s 后触发"的任务，会被快进触发。**写测试时**要先想清楚"快进后哪些任务会被 fire"。

### 坑 3：Dispatchers.Main 必须 setMain 才能让 release 协程跑

**症状**：第一次跑测试，release 协程的 `scope.launch` 报：
```
Module with the Main dispatcher had failed to initialize
```

**根因**：`Dispatchers.Main.immediate` 在 JVM 单测环境没有默认实现——Android 设备的 Looper
不存在。

**修法**：`@Before Dispatchers.setMain(StandardTestDispatcher())` + `@After Dispatchers.resetMain()`——
`StandardTestDispatcher` 接管 Main，release 协程的 `delay(30_000)` 用虚拟时间，
可调 [advanceTimeBy] 模拟 30s 流逝。

**教训**：单测里用 `Dispatchers.Main.immediate` 启动协程的代码必须 `@Before setMain`——
v0.5.0 阶段 3 SettingsViewModelTest 已经踩过（[phase-3.md](phase-3.md) 修复段）。
v0.5.1 [WebViewHolderTest] 重现这个 pattern。

---

## 四、验证

### 单测

| 测试类 | 例数 | 状态 |
|---|---|---|
| `AppConfigTest` | 13 | ✅ |
| `AppConfigDataStoreTest` | 11 | ✅ |
| `ModelTest` | 10 | ✅ |
| `ProgressTest` | 25 | ✅ |
| `MediaFormatTest` | 15 | ✅ |
| `YouTubeUrlTest` | 25 | ✅ |
| `ParseAndExpandUseCaseTest` | 17 | ✅ |
| `YtDlpEngineTest` | 26 | ✅ |
| `DownloadWorkerTest` | 13 | ✅ |
| `ExampleUnitTest` | 1 | ✅ |
| `DownloadingViewModelTest` | 5 | ✅ |
| `HistoryViewModelTest` | 10 | ✅ |
| `SettingsViewModelTest` | 16 | ✅ |
| `HttpContentTypeSnifferTest` | 13 | ✅ |
| `CompositeSnifferTest` | 4 | ✅ |
| **`WebViewHolderTest`** | **5**（v0.5.1 新增：创建 / 复用 / releaseNow / 30s 自动 / 窗口内 cancel）| ✅ |
| **总计** | **209**（v0.5.0 204 + 5 新增）| ✅ |

### APK 验证

```
$ ./gradlew assembleDebug
BUILD SUCCESSFUL in 8s
41 actionable tasks: 4 executed, 37 up-to-date

APK: app/build/outputs/apk/debug/app-debug.apk  ~78 MB（v0.5.0 不变）
- WebViewFactory + DefaultWebViewFactory 两个新类，但都是 0 size 字节码
- WebViewHolder 重构 inline 后字节码大小基本不变
```

### 静态检查

`./gradlew testDebugUnitTest --rerun` 全绿 209 例。

---

## 五、复盘清单

### 做了

- [x] **WebViewFactory interface** + **DefaultWebViewFactory 实现**——单测可 mockk
- [x] **WebViewHolder idle release 重构**：`by lazy` → `var current: WebView?` + `Mutex.withLock` 二次拿锁 + `CoroutineScope(SupervisorJob() + Main.immediate)` 计时器 + `cancelAndJoin` 取消挂起 release + `IDLE_TIMEOUT_MS = 30_000L`
- [x] **`@VisibleForTesting releaseNow()`** 紧急释放接口
- [x] **`@VisibleForTesting isCreated()`** / **`hasPendingRelease()`** 测试探针
- [x] **WebViewHolderTest 5 例**（v0.5.1 新增）
- [x] **SnifferModule** 加 `@Binds bindWebViewFactory(impl: DefaultWebViewFactory): WebViewFactory`
- [x] **versionCode 8→9** + versionName "0.5.0"→"0.5.1"
- [x] **209/209 单测全绿**
- [x] **`assembleDebug` 通过**
- [x] **阶段 11 复盘文档**（本文档）

### 没做（v0.5.2+ 单独 PR）

- [ ] **WebViewHeadlessSniffer 自身单测**（需要 Robolectric）
- [ ] **m3u8 内容解析**（拦截到 m3u8 URL 后拉 m3u8 body → 正则解析 #EXTINF / .ts）
- [ ] **WebViewHeadlessSniffer ANR 风险测试**（shouldInterceptRequest 1-3s 阻塞 Main 线程）
- [ ] **DefaultWebViewFactory 0 size / GONE / JS enabled 配置的 instrumented test 覆盖**（需要 Robolectric 或真机）
- [ ] **BilibiliAdapter**（WBI 签名 / click web API）
- [ ] **抖音 adapter**（X-Bogus）

### 文档同步

- [x] [PHASES.md](../PHASES.md) — 阶段 11 加
- [x] [CHANGELOG.md](../CHANGELOG.md) — + v0.5.1-android 段
- [x] [REUSE-MAP.md](../REUSE-MAP.md) — 同步 v0.5.1 WebViewFactory 映射
- [x] [README.md](../../README.md) — 阶段 11 标完成
- [x] [phase-11.md](phase-11.md) — 本文档
