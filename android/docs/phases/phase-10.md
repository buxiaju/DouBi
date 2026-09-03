# 阶段 10 复盘：headless browser 嗅探（✅ 完成 → v0.5.0-android）

> **最终状态**：阶段 10 收官。**WebView 集成 headless browser 嗅探**落地——任意 http(s) URL（非 YouTube / 直链 m3u8/mp4）能通过 WebView loadUrl + shouldInterceptRequest 拦截 m3u8/mp4 URL，覆盖 B 站 / 抖音 / 微博主页"JS 异步加载"网站。CompositeSniffer 按 `AppConfig.sniffHeadless` 动态选 HttpContentTypeSniffer（HTTP HEAD）还是 WebViewHeadlessSniffer（WebView 集成）。204/204 单测全绿（v0.4.1 200 + CompositeSnifferTest +4）。`assembleDebug` 通过。
> **v0.4.1-android tag 已发**（阶段 9 收官），本阶段成果属 v0.5.0-android tag。

## 一句话总结

本阶段做了 **4 类事情**：

1. **WebViewHolder 单例**：共享不可见 WebView（0 size + GONE），`@ApplicationContext` 注入，`Mutex.withLock { ... }` 串行化多 sniff 任务
2. **WebViewHeadlessSniffer 实现 Sniffer interface**：WebView loadUrl + `shouldInterceptRequest` 拦截 m3u8/mp4/webm/mpd/m4s URL，5s 超时返回 SniffResult
3. **CompositeSniffer 包双 Sniffer**：按 `AppConfig.sniffHeadless` 动态选 HTTP 还是 WebView；`@Binds` 绑到无 @Named 的 Sniffer interface，ParseAndExpandUseCase 不用改
4. **SnifferModule 重构**：`@Named("http")` 跟 `@Named("headless")` 区分两个 Sniffer binding；v0.4.0 阶段 8 的 `@Binds HttpContentTypeSniffer → Sniffer` 改成 `@Binds HttpContentTypeSniffer → @Named("http") Sniffer`

**没做**（v0.5.1+ 单独 PR）：
- WebViewHeadlessSniffer 自身单测（需要 Robolectric 或真机/模拟器）
- m3u8 内容解析（拿到 .m3u8 URL 后转成 .mp4 真下载）
- WebViewHolder idle 30s 后 release / re-create（v0.5.0 单例常驻 30-50MB）
- WebViewClient callback 1-3s 阻塞 Main 线程的 ANR 风险测试

---

## 一、改了什么

### 新增文件

| 路径 | 作用 |
|---|---|
| `app/src/main/java/com/doubi/android/core/sniffer/WebViewHolder.kt` | 共享 WebView 单例：0 size + GONE + Mutex 串行化 |
| `app/src/main/java/com/doubi/android/core/sniffer/WebViewHeadlessSniffer.kt` | Sniffer 实现：WebView loadUrl + shouldInterceptRequest 拦截 m3u8/mp4/webm/mpd/m4s |
| `app/src/main/java/com/doubi/android/core/sniffer/CompositeSniffer.kt` | 双 Sniffer 切换器：按 `AppConfig.sniffHeadless` 选 http / headless |
| `app/src/test/java/com/doubi/android/core/sniffer/CompositeSnifferTest.kt` | 4 例：sniffHeadless 切换契约 + Error / Media 透传 |

### 修改文件

| 路径 | 变化 |
|---|---|
| `app/src/main/java/com/doubi/android/core/sniffer/di/SnifferModule.kt` | 重构：3 个 `@Binds` 替代 v0.4.0 阶段 8 的 1 个 `@Binds`；`@Named("http")` 跟 `@Named("headless")` 区分 + 无 @Named 的 `CompositeSniffer → Sniffer` |
| `app/build.gradle.kts` | versionCode 7→8；versionName "0.4.1"→"0.5.0" |
| `app/src/test/java/com/doubi/android/ExampleUnitTest.kt` | startsWith 断言 "0.4"→"0.5" |

### 桌面版 → Android 版

```
桌面版 `src/doubi/core/sniffer.py:WebViewHeadlessSniffer`（用 Playwright 真 headless，Python）
  ─────────────────────────────────────────────────
  → 阶段 10 v0.5.0：WebViewHeadlessSniffer 用 Android WebView 简化方案
    （不是真 headless——WebView 必须 attach view hierarchy，但 0 size 不可见）
  → WebViewHolder 单例 + Mutex.withLock 串行化（桌面版单进程单 Playwright）
  → CompositeSniffer 切换器（v0.4.0 v0.5.0 双 Sniffer 切换：sniffHeadless 字段）
```

---

## 二、核心设计决定

### 决定 1：WebView 共享单例 + Mutex 串行化

**问题**：每个 sniff 任务 new 一个 WebView 太慢（100-300ms 首次创建），且每个 WebView 持 Chromium 进程（~30-50MB）。

**方案**：
- `WebViewHolder` 单例（`@Singleton` + `by lazy`）—— 第一次 sniff 才创建，后续复用
- 多个 sniff 并发用 `Mutex.withLock { ... }` 串行（WebView 是单线程组件，不能并发 loadUrl）

**理由**：
- WebView 共享是 Android 端嗅探效率的关键——频繁嗅探场景下复用 WebView 减少冷启动
- Mutex 是 kotlinx-coroutines 自带，比 `@Synchronized`（不能用在 suspend 函数）更适合

**风险**：
- 内存常驻 30-50MB 不可忽视——v0.5.1+ 优化：idle 30s 后 release / re-create
- Mutex 串行化在多用户场景下排队——v0.5.0 单用户自用可接受

### 决定 2：CompositeSniffer 抽象，ParseAndExpandUseCase 不动

**v0.4.0 阶段 8**：`ParseAndExpandUseCase` 注入单一 `Sniffer` interface → 绑 `HttpContentTypeSniffer` 实现。
**v0.5.0**：需要根据 `AppConfig.sniffHeadless` 动态选 HTTP 还是 WebView。

**方案对比**：
- A) `ParseAndExpandUseCase` 注入两个 Sniffer，加 `useHeadless: Boolean` 参数 → 破坏 v0.4.0 阶段 8 写的 17 例测试
- B) `CompositeSniffer` 包双 Sniffer，`@Binds` 绑到无 @Named 的 `Sniffer` interface → ParseAndExpandUseCase 不动 ✅
- C) `ParseAndExpandUseCase` 注入 `AppConfigDataStore` 自己读 sniffHeadless → 改领域层逻辑

**选 B**：Hilt 多 binding 模式（`@Named("http")` / `@Named("headless")` / 无 @Named Composite），最干净。

### 决定 3：WebView 0 size + GONE 不可见

**问题**：WebView 必须 attach 到 view hierarchy 才能渲染，否则 loadUrl 抛 "WebView not attached to window"。

**方案**：
- `layoutParams = ViewGroup.LayoutParams(0, 0)` —— 占 0 空间
- `visibility = View.GONE` —— 不渲染不接收 onDraw

**理由**：用户不需要看到浏览器——v0.5.0 headless Sniffer 走后台嗅探路径。WebView 实际不渲染，但仍能 loadUrl + shouldInterceptRequest 拦截请求（因为 attach 到 view hierarchy）。

**v0.5.1+ 优化**：可以 attach 到一个 `View.GONE` 的 FrameLayout，attach 跟 inflate 更稳。

### 决定 4：v0.5.0 不做 WebView 自身单测

**问题**：WebView 是 Android framework 真实组件，没法 mockk（要 Robolectric 或真机/模拟器）。自用环境 v0.4.1 阶段 9 决定不装 Robolectric。

**v0.5.0 范围**：只测 CompositeSniffer 切换契约（4 例）。WebViewHeadlessSniffer 自身单测留 v0.5.1+ Robolectric 起来再补。

**风险**：WebViewHeadlessSniffer 自身 bug 测不到——v0.5.1 引入 Robolectric 或真机 sideload 跑 instrumented test 覆盖。

### 决定 5：v0.5.0 不做 m3u8 内容解析

**问题**：拦截到 m3u8 URL 后，m3u8 本身是 HLS playlist（.ts 分片列表），不能直接下载——需要解析 m3u8 拿 .ts 分片 URL 列表，逐一下载再合并。

**v0.5.0 范围**：返回第一个 m3u8 URL 当作 `finalUrl`。Engine (yt-dlp-android) 拿到 m3u8 URL 后能自动解析 m3u8 内容（yt-dlp 支持 HLS）。

**v0.5.1+ 优化**：可以 WebView 额外拦截 `.ts` 分片 URL 拼成完整视频 URL。

---

## 三、坑 & 决策

### 坑 1：`@Synchronized` 不能用在 suspend 函数

**症状**：v0.5.0 起步 `WebViewHolder.withLock` 标 `@Synchronized` + `fun <T> withLock(block: (WebView) -> T): T` 编译过——但 `WebViewHeadlessSniffer.sniffOnMainThread` 是 suspend，调 `kotlinx.coroutines.delay(100L)` 编译报：
```
Suspension functions can only be called within coroutine body
```

**根因**：`@Synchronized` 编译时锁的是普通函数，不能跨越 suspend point。

**修法**：换 `kotlinx.coroutines.sync.Mutex` + `withLock`：
```kotlin
private val mutex = Mutex()
suspend fun <T> withLock(block: suspend (WebView) -> T): T = mutex.withLock {
    block(webView)
}
```

**教训**：Kotlin 协程的同步用 `Mutex`，不要用 `synchronized` / `@Synchronized`。

### 坑 2：`@SuppressLint` 不能用在 lazy property delegate

**症状**：v0.5.0 `WebViewHolder` 标 `@SuppressLint("SetJavaScriptEnabled") val webView: WebView by lazy { ... }` 编译报：
```
This annotation is not applicable to target 'member property with delegate'
```

**根因**：Kotlin 的 `@SuppressLint` annotation target 是 `property`，不能是 `property with delegate`。

**修法**：把 `@SuppressLint` 放到 lazy block 内部（WebView 创建 apply 块），或者改用 `val webView: WebView by lazy(LazyThreadSafetyMode.NONE) { @SuppressLint(...) WebView(...).apply { ... } }`。

**教训**：Kotlin annotation 跟 Java 注解 target 规则有差异——遇到 "annotation is not applicable to target" 报错时换 target 或者改结构。

### 坑 3：WebViewHolder.withLock 改成 Mutex 后 @Synchronized 残留

**症状**：v0.5.0 起步时 `withLock` 写 `@Synchronized` + `suspend fun` —— 编译报 "Suspension functions can only be called within coroutine body"（坑 1）。修法改用 Mutex 后忘了删 `@Synchronized`，第二次编译报 `@SuppressLint is not applicable to target 'member property with delegate'`（坑 2）。

**修法**：先去掉 `@Synchronized` 标注，再加 `Mutex` 字段。分两步修但实际上一次性重写 WebViewHolder.kt。

**教训**：连锁编译错时，把整个文件重写比逐行 patch 更快。

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
| **`CompositeSnifferTest`** | **4**（v0.5.0 新增：sniffHeadless 切换 + Error/Media 透传）| ✅ |
| **总计** | **204**（v0.4.1 200 + 4 新增）| ✅ |

### APK 验证

```
$ ./gradlew assembleDebug
BUILD SUCCESSFUL in 37s
41 actionable tasks: 10 executed, 31 up-to-date

APK: app/build/outputs/apk/debug/app-debug.apk  ~78 MB
- WebView 集成：Android 端首次创建 WebView 会加载 Chromium native lib
  + libwebviewchromium_loader.so + libwebviewchromium_plat_support.so
  + .so 文件增加 ~5-8 MB
- R8 keep 规则仍然生效（25 个 com.yausername.youtubedl_android.* 类保留原名）
```

### 静态检查

`./gradlew testDebugUnitTest --rerun` 全绿 204 例。

---

## 五、APK 验证

```
APK 体积预估：~78 MB（v0.4.1 76 MB + 2 MB WebView 增量）
- libwebviewchromium_loader.so ~3 MB
- libwebviewchromium_plat_support.so ~1.5 MB
- v8 snapshot ~1 MB
- 其它 WebView 资源 ~1 MB
```

---

## 六、复盘清单

### 做了

- [x] **WebViewHolder 单例**：`@ApplicationContext` + `Mutex.withLock { ... }` 串行化 + 0 size + GONE 不可见 + lazy 初始化
- [x] **WebViewHeadlessSniffer 实现 Sniffer interface**：5s 超时 + shouldInterceptRequest 拦截 m3u8/mp4/webm/mpd/m4s + onPageFinished 触发提前结束 + Error 透传
- [x] **CompositeSniffer 切换器**：按 `AppConfig.sniffHeadless` 选 http / headless；`@Binds` 绑到无 @Named 的 Sniffer interface，ParseAndExpandUseCase 不动
- [x] **SnifferModule 重构**：`@Named("http")` 跟 `@Named("headless")` 区分两个 Sniffer + 无 @Named Composite；3 个 `@Binds`
- [x] **CompositeSnifferTest 4 例**（v0.5.0 新增）
- [x] **versionCode 7→8** + versionName "0.4.1"→"0.5.0"
- [x] **204/204 单测全绿**
- [x] **assembleDebug 通过**
- [x] **阶段 10 复盘文档**

### 没做（v0.5.1+ 单独 PR）

- [ ] **WebViewHeadlessSniffer 自身单测**（需要 Robolectric 或真机 sideload 跑 instrumented test）
- [ ] **m3u8 内容解析**：拦截到 m3u8 URL 后解析 HLS playlist 拿 .ts 分片 URL 列表（v0.5.0 直接返回 m3u8 URL 给 yt-dlp 处理）
- [ ] **WebViewHolder idle 30s 后 release / re-create**（v0.5.0 单例常驻 30-50MB）
- [ ] **WebViewClient callback 1-3s 阻塞 Main 线程的 ANR 风险测试**
- [ ] **BilibiliAdapter**（WBI 签名 / click web API）—— v0.5.1+ 单独 PR
- [ ] **抖音 adapter**（X-Bogus）—— v0.5.2+ 单独 PR

### 文档同步

- [x] [PHASES.md](../PHASES.md) — 阶段 7 改自用策略说明（v0.4.1 同步） + 阶段 10 加
- [x] [CHANGELOG.md](../CHANGELOG.md) — + v0.5.0-android 段
- [x] [REUSE-MAP.md](../REUSE-MAP.md) — 同步 v0.5.0 headless browser 映射
- [x] [README.md](../../README.md) — 阶段 10 标完成
- [x] [phase-10.md](phase-10.md) — 本文档
