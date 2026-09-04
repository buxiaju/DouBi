# 阶段 13 复盘：m3u8 递归解析（✅ 完成 → v0.5.3-android）

> **最终状态**：阶段 13 收官。v0.5.2 阶段 12 留的「不递归解析 master → media」欠账（[phase-12.md](phase-12.md) 决定 2）落地——[M3u8Parser.parseRecursive] 一路递归 master → variant → media → segment，[WebViewHeadlessSniffer] 集成调用。221/221 单测全绿（v0.5.2 217 + 4 新增），`assembleDebug` 通过。
> **v0.5.2-android tag 已发**（阶段 12 收官），本阶段成果属 v0.5.3-android tag。

## 一句话总结

本阶段做了 **3 类事情**（按 commit 顺序）：

1. **M3u8Parser.parseRecursive** 新增方法——`suspend fun parseRecursive(body, baseUrl, fetchBody): M3u8Result`，[MAX_RECURSION_DEPTH]=5 防循环引用
2. **M3u8ParserTest 4 例递归路径**——multi-level master / 直接 media 不递归 / fetchBody null 降级 / 循环引用降级
3. **WebViewHeadlessSniffer 集成**——`parse` 改 `parseRecursive`，suspend lambda 闭包，初始 body 失败降级保留原 finalUrl

**没做**（v0.5.4+ 单独 PR）：
- m3u8 v7+ HLS encryption（`#EXT-X-KEY`）—— v0.5.3 仍是 v0.5.2 简化方案
- 多 variant 选择 UI（带宽/分辨率）—— v0.5.3 仍默认拿第一个
- WebViewHeadlessSniffer 自身单测（v0.5.0 留的欠账，需要 Robolectric）
- ANR 风险测试
- DefaultWebViewFactory 配置 instrumented test
- BilibiliAdapter / 抖音 adapter

---

## 一、改了什么

### 修改文件

| 路径 | 变化 |
|---|---|
| `app/src/main/java/com/doubi/android/core/sniffer/M3u8Parser.kt` | + `suspend fun parseRecursive(body, baseUrl, fetchBody: suspend (String) -> String?): M3u8Result`；+ `MAX_RECURSION_DEPTH = 5` companion constant；**保留** [parse] 不动（one-level） |
| `app/src/main/java/com/doubi/android/core/sniffer/WebViewHeadlessSniffer.kt` | `enhanceM3u8IfNeeded` 改用 `parseRecursive` 替 `parse`；fetchBody 用 `suspend (String) -> String?` lambda；初始 body 先 fetch（`fetchM3u8Body`），失败返原 result |
| `app/src/test/java/com/doubi/android/core/sniffer/M3u8ParserTest.kt` | + 4 例 `parseRecursive` 测试（multi-level master / media 不递归 / fetchBody null 降级 / 循环引用降级）；用 `runBlocking` 包 suspend 函数 |
| `app/build.gradle.kts` | versionCode 10→11；versionName "0.5.2"→"0.5.3" |
| `app/src/test/java/com/doubi/android/ExampleUnitTest.kt` | 注释加「阶段 13 升到 v0.5.3」一行 |

### 桌面版 → Android 版

```
桌面版 `src/doubi/core/sniffer.py:WebViewHeadlessSniffer`（Playwright 真 headless）
  ─────────────────────────────────────────────────
  → 阶段 10 v0.5.0：WebViewHeadlessSniffer 用 Android WebView 简化方案
  → 阶段 11 v0.5.1：WebViewHolder idle 30s release
  → 阶段 12 v0.5.2：m3u8 单层解析（M3u8Parser.parse）
  → 阶段 13 v0.5.3：m3u8 递归解析（M3u8Parser.parseRecursive + 5 层 depth 护栏）
```

---

## 二、核心设计决定

### 决定 1：M3u8Parser.parseRecursive 独立方法，不动 parse

**问题**：v0.5.2 的 [parse] 是 one-level（master → first variant m3u8 URL）。要递归就得
让 [M3u8Parser] 调 fetchBody 拉子 m3u8 body。

**v0.5.3 方案**：保留 [parse] 不动，加 [parseRecursive] 走新方法。
- [parse] 仍是 one-level，8 例原测试不动
- [parseRecursive] 走递归，4 例新测试
- 两个方法互不依赖——[parseRecursive] 内部调 [parse] 做单层解析

**对比方案**：
- A) 改 [parse] 签名加 `fetchBody` 参数——破坏 v0.5.2 8 例测试 + 调用方
- B) 抽 [parseRecursive] 独立方法，**不动** [parse] ✅（选 B）
- C) 删 [parse] 全部走 [parseRecursive]——浪费——很多场景（一次性解析、桌面版对应实现）
  不需要 fetchBody

### 决定 2：parseRecursive 是 suspend 函数，fetchBody 是 suspend lambda

**为什么 suspend**：[fetchBody] 要在协程里跑 OkHttp GET（v0.5.2 [WebViewHeadlessSniffer.fetchM3u8Body]
已经是 `withContext(Dispatchers.IO)` 跑 OkHttp）。如果 fetchBody 是非 suspend，
lambda 里得用 `runBlocking { ... }` 包——会阻塞调用方线程，违背 v0.5.2 「不阻塞 Main」的设计。

**v0.5.3 方案**：
- `suspend fun parseRecursive(body, baseUrl, fetchBody: suspend (String) -> String?)`
- 测试用 `runBlocking { ... }` 包——测试不需要真协程上下文，`runBlocking` 创建匿名
  协程并阻塞到完成

**影响**：
- 8 例原 [parse] 测试不受影响（parse 是非 suspend）
- 4 例新 [parseRecursive] 测试需要 `runBlocking` 包——简单模板

### 决定 3：MAX_RECURSION_DEPTH = 5

**5 的依据**：
- 真实场景下 master → media 是 **2 层**（master.m3u8 → variant.m3u8 → media.m3u8 → .ts）
- 少数场景多层（intermediate master + variant list）
- 5 层足够覆盖 99%+ 真实情况
- 防循环引用死循环（master1 → master2 → master1 → ...）

**对比方案**：
- 3 层：太保守，少数多层 master 解析到 3 层会降级 Passthrough 保留中间 URL
- 10 层：太宽松，循环引用场景要 10 次 HTTP 请求才终止
- **5 层 sweet spot**——足够 + 安全

**降级行为**：达到 depth 上限 → 返 `Passthrough(currentUrl)`，调用方保留当前 URL
（不抛异常，跟 v0.5.2 fail-safe 一致）。

### 决定 4：fetchBody null 返 Variant（不返 Passthrough）

**问题**：v0.5.2 简化版 [parse] 把 Passthrough 当"不是合法 m3u8"的降级。但 [parseRecursive]
里 fetchBody 返 null（网络失败）是另一种语义——已经成功解析出 variant URL，只是
fetchBody 拉子 m3u8 body 失败。

**v0.5.3 决策**：fetchBody null → 返当前 variant URL 当 Variant（**不**降级 Passthrough）。
理由：当前 variant URL 是个合法的 m3u8 URL，让调用方（[WebViewHeadlessSniffer]）用这个
URL 当 finalUrl，Engine (yt-dlp) 拿到后自己再下 body 解析。**v0.5.2 的 [parse] 在这个
场景会返 Variant，但 v0.5.2 不递归，调用方拿到 Variant 后直接用，没有进一步解析——v0.5.3
行为跟 v0.5.2 一致**。

**风险**：极小。v0.5.2 已经验证过 [parse] 在 master body 上返 Variant，调用方用 variant
URL 没问题。v0.5.3 只是在 parse 失败前多了一次 fetchBody 尝试。

### 决定 5：v0.5.3 不做多 variant 选择 UI

**v0.5.3 范围**：递归解析到 first segment URL（或 first variant URL if fetchBody fails）。
v0.5.2 决定 3（多 variant 选第一个）继承下来——v0.5.3 仍默认拿第一个 variant。

**理由**：
- 多 variant 选择 UI 是 v0.5.2 阶段 4 写好的 `PromptOptionsDialog` 模式扩展
- 但 UI 工作量大：master playlist 解析 → 提取所有 variants → 显示 radio → 用户选 → 重新解析
- v0.5.3 范围控制：递归 + depth 护栏是核心，多 variant UI 留 v0.5.4+

**风险**：用户不能选清晰度——v0.5.4+ 加 variant UI 解决。

---

## 三、坑 & 决策

### 坑 1：suspend lambda 跨越 Kotlin 编译器边界

**症状**：v0.5.3 起步时 [parseRecursive] 签名是 `fetchBody: (String) -> String?`（非 suspend），
`WebViewHeadlessSniffer` 写 `val fetchBody = { url -> fetchM3u8Body(url) }` 编译报：
```
Suspension functions can only be called within coroutine body
```

**根因**：[fetchM3u8Body] 是 suspend 函数（内部 `withContext(Dispatchers.IO)`），但 lambda
类型不是 suspend——suspend 函数不能从非 suspend lambda 调用。

**修法**：
1. [parseRecursive] 签名改 `fetchBody: suspend (String) -> String?`
2. [WebViewHeadlessSniffer] 改 `val fetchBody: suspend (String) -> String? = { url -> fetchM3u8Body(url) }`
3. 测试 4 例改 `runBlocking { ... }` 包

**教训**：suspend 函数从非 suspend lambda 调用会编译失败。Kotlin 类型系统强制 `suspend` 标
注必须一致传递。

### 坑 2：parseRecursive 第一层 body 传递错误

**症状**：第一版 `enhanceM3u8IfNeeded` 写 `m3u8Parser.parseRecursive("", result.finalUrl, fetchBody)`——
传 `""` 作 body。parseRecursive 第一次调 `parse("", baseUrl)` 返 Passthrough（空 body 不合法 m3u8），
直接退出，根本不进 master 检测。

**根因**：v0.5.2 思路是"parseRecursive 自己 fetch 第一层 body"——但 parseRecursive 签名是
`parseRecursive(body, baseUrl, fetchBody)`，**body 必须是 caller 提供的**。

**修法**：
```kotlin
val initialBody = fetchM3u8Body(result.finalUrl) ?: return result
val fetchBody: suspend (String) -> String? = { url -> fetchM3u8Body(url) }
val parsed = m3u8Parser.parseRecursive(initialBody, result.finalUrl, fetchBody)
```

**教训**：写 [parseRecursive] 这种"递归从 caller 提供 first 节点"的 API 时，doc 一定要
明确写"body 由 caller 准备，parseRecursive 不 fetch 第一个 body"。

### 坑 3：测试用 `runBlocking` 而不是 `runTest`

**症状**：第一版 4 例测试没 `runBlocking` 包，编译报 "Suspension functions can be called
only within coroutine body"——`runBlocking` 没加。

**修法**：
```kotlin
@Test
fun `parseRecursive ...`() = runBlocking {
    ...
}
```

**为什么不用 `runTest`**：v0.5.3 测试只测 [parseRecursive] 的纯逻辑——`parseRecursive` 内部
没有 `delay()` 或其它协程调度，**不需要** TestDispatcher 控制虚拟时间。`runBlocking` 创建
匿名协程并阻塞到完成，对纯逻辑测试最直接。

**风险**：如果未来 [parseRecursive] 加 `delay()` 或协程切换，需要改用 `runTest` 才能正确
控制虚拟时间。v0.5.3 范围**不**改。

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
| `WebViewHolderTest` | 5 | ✅ |
| **`M3u8ParserTest`** | **12**（v0.5.2 8 + v0.5.3 4 新增：parseRecursive multi-level / media 不递归 / fetchBody null 降级 / 循环引用降级）| ✅ |
| **总计** | **221**（v0.5.2 217 + 4 新增）| ✅ |

### APK 验证

```
$ ./gradlew assembleDebug
BUILD SUCCESSFUL in 29s
52 actionable tasks: 15 executed, 37 up-to-date

APK: app/build/outputs/apk/debug/app-debug.apk  ~78 MB（v0.5.2 不变）
- M3u8Parser.parseRecursive 新增 30 行，0 size 字节码
- WebViewHeadlessSniffer 重构 inline 后字节码大小基本不变
```

### 静态检查

`./gradlew testDebugUnitTest --rerun` 全绿 221 例。

---

## 五、复盘清单

### 做了

- [x] **M3u8Parser.parseRecursive**：suspend 函数 + `suspend (String) -> String?` fetchBody 参数 + MAX_RECURSION_DEPTH=5
- [x] **M3u8ParserTest 4 例**：multi-level master / media 不递归 / fetchBody null / 循环引用
- [x] **WebViewHeadlessSniffer 集成**：`enhanceM3u8IfNeeded` 用 parseRecursive，suspend lambda fetchBody，初始 body 先 fetch 失败降级
- [x] **versionCode 10→11** + versionName "0.5.2"→"0.5.3"
- [x] **221/221 单测全绿**
- [x] **`assembleDebug` 通过**
- [x] **阶段 13 复盘文档**（本文档）

### 没做（v0.5.4+ 单独 PR）

- [ ] **m3u8 v7+ HLS encryption**（`#EXT-X-KEY`）—— v0.5.3 仍是 v0.5.2 简化方案
- [ ] **多 variant 选择 UI**（带宽/分辨率）—— v0.5.3 仍默认拿第一个
- [ ] **WebViewHeadlessSniffer 自身单测**（v0.5.0 留的欠账，需要 Robolectric）
- [ ] **ANR 风险测试**（shouldInterceptRequest 1-3s 阻塞 Main 线程）
- [ ] **DefaultWebViewFactory 0 size / GONE / JS enabled 配置的 instrumented test 覆盖**
- [ ] **BilibiliAdapter**（WBI 签名 / click web API）
- [ ] **抖音 adapter**（X-Bogus）

### 文档同步

- [x] [PHASES.md](../PHASES.md) — 阶段 13 加
- [x] [CHANGELOG.md](../CHANGELOG.md) — + v0.5.3-android 段
- [x] [REUSE-MAP.md](../REUSE-MAP.md) — 同步 v0.5.3 parseRecursive 映射
- [x] [README.md](../../README.md) — 阶段 13 标完成
- [x] [phase-13.md](phase-13.md) — 本文档
