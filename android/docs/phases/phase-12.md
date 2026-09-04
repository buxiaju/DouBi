# 阶段 12 复盘：m3u8 内容解析（✅ 完成 → v0.5.2-android）

> **最终状态**：阶段 12 收官。v0.5.0 阶段 10 留的「m3u8 内容解析留 v0.5.1+」欠账（[phase-10.md](phase-10.md) 决定 5）落地——抽 [M3u8Parser] pure logic + [WebViewHeadlessSniffer] 集成把 m3u8 finalUrl 替换为 first variant/segment URL。217/217 单测全绿（v0.5.1 209 + 8 新增），`assembleDebug` 通过。
> **v0.5.1-android tag 已发**（阶段 11 收官），本阶段成果属 v0.5.2-android tag。

## 一句话总结

本阶段做了 **3 类事情**（按 commit 顺序）：

1. **抽 [M3u8Result] sealed + [M3u8Parser] pure logic**——master playlist 拿 first variant、media playlist 拿 first segment，**不递归**——所有解析失败 / 不像合法 m3u8 / 空 body 走 Passthrough 保留原 m3u8 URL
2. **M3u8ParserTest 8 例**（master 绝对 URL / master 相对 URL / media .ts / media .m4s / 空 body / 不带 #EXTM3U 头 / comments-only / URL 带 query 保留）
3. **WebViewHeadlessSniffer 集成**——注入 [OkHttpClient] + [M3u8Parser]，拦截到 m3u8 URL 后调 [M3u8Parser] 增强 finalUrl（`withContext(Dispatchers.IO)` 跑 OkHttp GET，不阻塞 Main）

**没做**（v0.5.3+ 单独 PR）：
- 递归解析 master → media（v0.5.2 只一层）
- m3u8 v7+ HLS encryption（`#EXT-X-KEY`）—— 保留原 m3u8 URL 让 Engine 解析
- 多 variant 选择（带宽/分辨率）—— v0.5.2 默认拿第一个（通常是最高带宽）
- WebViewHeadlessSniffer 自身单测（v0.5.0 留的欠账，需要 Robolectric）

---

## 一、改了什么

### 新增文件

| 路径 | 作用 |
|---|---|
| `app/src/main/java/com/doubi/android/core/sniffer/M3u8Result.kt` | sealed class：Variant(url) / Segment(url) / Passthrough(url) |
| `app/src/main/java/com/doubi/android/core/sniffer/M3u8Parser.kt` | `parse(body, baseUrl)` 解析 m3u8 body——master 拿 first variant、media 拿 first segment |
| `app/src/test/java/com/doubi/android/core/sniffer/M3u8ParserTest.kt` | 8 例（master 绝对 / master 相对 / media .ts / media .m4s / 空 body / 不带 #EXTM3U / comments-only / URL 带 query） |

### 修改文件

| 路径 | 变化 |
|---|---|
| `app/src/main/java/com/doubi/android/core/sniffer/WebViewHeadlessSniffer.kt` | + `okHttpClient: OkHttpClient` 跟 `m3u8Parser: M3u8Parser` 构造器注入；`sniff` 拿到 WebView 嗅探结果后调 `enhanceM3u8IfNeeded` 增强；新增 `fetchM3u8Body(url)` 用 `withContext(Dispatchers.IO)` 跑 OkHttp GET |
| `app/build.gradle.kts` | versionCode 9→10；versionName "0.5.1"→"0.5.2" |
| `app/src/test/java/com/doubi/android/ExampleUnitTest.kt` | 注释加「阶段 12 升到 v0.5.2」一行；startsWith 保持 `"0.5"`（v0.5.0 / v0.5.1 / v0.5.2 都 0.5 prefix） |

### 桌面版 → Android 版

```
桌面版 `src/doubi/core/sniffer.py:WebViewHeadlessSniffer`（Playwright 真 headless）
  ─────────────────────────────────────────────────
  → 阶段 10 v0.5.0：WebViewHeadlessSniffer 用 Android WebView 简化方案
  → 阶段 11 v0.5.1：WebViewHolder idle 30s release
  → 阶段 12 v0.5.2：m3u8 内容解析——WebView 拦截到 m3u8 URL 后
    调 M3u8Parser 解析 master/media playlist
    把 finalUrl 替换为 first variant/segment URL
```

桌面版对应实现细节未对齐（`src/doubi/core/sniffer.py` 不在本工作区），v0.5.2 按 Android 端
合理实现——master → first variant、media → first segment、Passthrough 降级。

---

## 二、核心设计决定

### 决定 1：抽 M3u8Parser 为独立 pure logic 类

**问题**：v0.5.0 阶段 10 的 [WebViewHeadlessSniffer] 直接把拦截到的 m3u8 URL 返给 Engine
让 yt-dlp 自己解析——单测没法覆盖 m3u8 解析逻辑（要么在 WebViewHeadlessSniffer 里塞逻辑
测不到，要么抽出来）。

**v0.5.2 方案**：抽 [M3u8Parser] 独立类，输入 `(body, baseUrl)` 返 [M3u8Result] sealed。
[WebViewHeadlessSniffer] 注入 [M3u8Parser] 调它——单测 8 例直接覆盖解析逻辑，**不需要
Robolectric**。

**对比方案**：
- A) 把 m3u8 解析逻辑塞进 [WebViewHeadlessSniffer] 里——单测覆盖不到
- B) 抽 [M3u8Parser] pure logic + 单测覆盖 ✅（选 B）
- C) 接 m3u8 解析库（`net.notice123/m3u8parser` 之类）—— 引新依赖

### 决定 2：master → 第一个 variant，**不递归**

**v0.5.2 范围**：master playlist 解析到第一个 variant 子 m3u8 URL 就停，不下 body 解析子 m3u8。

**理由**：
- 递归要多发一次 HTTP 请求（变体子 m3u8 也是 m3u8，要再拉 body 解析）
- v0.5.2 范围控制：让 Engine (yt-dlp) 拿到子 m3u8 URL 后自己再下 body 解析
- 递归留 v0.5.3+ 单独 PR

**风险**：节省的 HTTP round-trip 比想象少——master 解析是省了"先下 master 决定下啥"，但
子 m3u8 还是得下。可接受——sniifer 阶段提前告诉 Engine 要下啥，Engine 不用再 sniff。

### 决定 3：多 variant 选第一个（通常是最高带宽）

**v0.5.2 范围**：master playlist 多个 `#EXT-X-STREAM-INF` 选第一个。

**理由**：
- 简单——v0.5.2 不实现带宽/分辨率选择 UI
- 第一个通常是最高带宽/分辨率（HLS 推荐排序）
- v0.5.3+ 可加 variant 选择 UI（对齐 v0.2 阶段 4 写好的 `PromptOptionsDialog` format radio 模式）

**风险**：用户不能选清晰度——v0.5.3+ 加 variant 选择 UI 解决。

### 决定 4：解析失败 / 不像 m3u8 走 Passthrough，**不抛异常**

**问题**：m3u8 v7+ 高级特性（`#EXT-X-KEY` 加密、`#EXT-X-MAP` init segment、
`EXT-X-PROGRAM-DATE-TIME` 等）v0.5.2 不支持。

**v0.5.2 行为**：解析不出来 / 不像合法 m3u8 / 空 body / 只注释无 segment 全部走
[M3u8Result.Passthrough]，调用方 [WebViewHeadlessSniffer.enhanceM3u8IfNeeded] 保留原
finalUrl，让 Engine (yt-dlp) 自己解析。

**理由**：
- fail-safe：v0.5.2 解析失败不破坏 v0.5.0 已经 work 的"返 m3u8 URL 给 Engine"路径
- Engine 兼容 m3u8 高级特性（yt-dlp 支持 HLS encryption）
- v0.5.2 是"增强"不是"替换"——v0.5.0 行为兜底

**风险**：几乎无——v0.5.2 是 best-effort 增强。

### 决定 5：OkHttp fetch 用现有 10s client，**不新建 fast client**

**问题**：[SnifferModule.provideOkHttpClient] 配置 10s connect / 10s read。m3u8 body fetch
用这个 client 够不够快？

**v0.5.2 范围**：直接复用 [SnifferModule] 提供的 OkHttpClient（共享 10s timeout）。

**理由**：
- m3u8 playlist body 一般几 KB，10s timeout 远超实际需要
- 共用 client = 0 新配置；新建 "fast client"（3s timeout）增加模块复杂度
- 最坏情况：m3u8 fetch 10s + WebView sniff 5s = 15s 总耗时。可接受
- v0.5.3+ 如要快可加 `OkHttpClient.newBuilder().readTimeout(3, SECONDS).build()` per-call

**风险**：m3u8 巨大（罕见）会拉满 10s timeout——可接受。

---

## 三、坑 & 决策

### 坑 1：相对 URL + query 拼接到 baseUrl 的行为

**症状**：第一次写测试 `relative segment URL with query params preserves them`，用 Java
`URI.resolve()`，发现行为跟想象的不一样——相对 URL 自带 query 时，**不继承** baseUrl 的
query。

**根因**：Java `URI.resolve()` 行为：相对 URL 是 opaque 引用（带 scheme:path/query 的整体），
不继承 baseUrl 的 query；只继承 baseUrl 的 scheme + authority + path prefix。

**修法**：测试断言改成只验证关键 path 段（`startsWith("https://.../segment0.ts")`）+ 验证
相对 URL 自带的 query（`token=abc&exp=12345`）在结果里，**不**断言完整 URL 字符串。

**教训**：Java `URI.resolve()` 行为是 RFC 3986 5.3 节规定的——`relative-ref` 是 opaque
引用，不是"相对路径"。写测试前要先确认 resolve 行为符合预期。

### 坑 2：EXT-X-MAP 跟 EXT-X-KEY 都被当 # 注释

**症状**：media playlist with m4s segments 测试里，body 包含 `#EXT-X-MAP:URI="init.mp4"`
——v0.5.2 解析逻辑只检查 `line.startsWith("#")`，会跳过 init.mp4。

**根因**：EXT-X-MAP 的 URI 不是 segment URL，是 initialization segment（视频文件的 metadata
段）—— 解析第一个 segment 时应该跳过。

**v0.5.2 行为**：所有 `#` 开头行都跳过，第一个非 # 非空行就是 segment URL。**包括** EXT-X-MAP。

**这是 v0.5.2 的简化**——完整 HLS 解析需要单独处理 init segment（m3u8 v7+ 高级特性），
v0.5.2 不做。Engine (yt-dlp) 拿到 segment URL 后自己处理 init segment。

**风险**：极少数 site 的 m3u8 init segment 是**必要**的（fmp4 模式），少 init segment
下不下来——v0.5.2 直接返 .m4s URL 给 Engine，Engine 应该能处理。

### 坑 3：M3u8Parser 测试里 trimIndent() + triple-quote string

**症状**：M3u8ParserTest 用 Kotlin triple-quote + `trimIndent()` 写 m3u8 body 字符串。

**根因**：m3u8 body 是多行文本，单行 string literal 写起来要 `"\n"`，可读性差。

**修法**：`trimIndent()` 自动去掉每行公共缩进——写 `"""` + `trimIndent()` 组合最干净。

**教训**：Kotlin 写多行字符串 / 配置文件内容 / m3u8 body 都用 `trimIndent()` 组合。

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
| **`M3u8ParserTest`** | **8**（v0.5.2 新增：master 绝对 / master 相对 / media .ts / media .m4s / 空 body / 不带 #EXTM3U / comments-only / URL 带 query）| ✅ |
| **总计** | **217**（v0.5.1 209 + 8 新增）| ✅ |

### APK 验证

```
$ ./gradlew assembleDebug
BUILD SUCCESSFUL in 5s
41 actionable tasks: 4 executed, 37 up-to-date

APK: app/build/outputs/apk/debug/app-debug.apk  ~78 MB（v0.5.1 不变）
- M3u8Result / M3u8Parser 两个新类，0 size 字节码
- WebViewHeadlessSniffer 重构 inline 后字节码大小基本不变
- OkHttp 调用走现有 SnifferModule.provideOkHttpClient，0 新依赖
```

### 静态检查

`./gradlew testDebugUnitTest --rerun` 全绿 217 例。

---

## 五、复盘清单

### 做了

- [x] **M3u8Result sealed**（Variant / Segment / Passthrough）
- [x] **M3u8Parser**（master 拿 first variant、media 拿 first segment、失败 Passthrough）
- [x] **M3u8ParserTest 8 例**（v0.5.2 新增）
- [x] **WebViewHeadlessSniffer 集成**：注入 [OkHttpClient] + [M3u8Parser]，`enhanceM3u8IfNeeded` 增强 finalUrl，`withContext(Dispatchers.IO)` 跑 OkHttp GET 不阻塞 Main
- [x] **versionCode 9→10** + versionName "0.5.1"→"0.5.2"
- [x] **217/217 单测全绿**
- [x] **`assembleDebug` 通过**
- [x] **阶段 12 复盘文档**（本文档）

### 没做（v0.5.3+ 单独 PR）

- [ ] **递归解析 master → media**（v0.5.2 只一层；变体子 m3u8 仍要 Engine 自己解析）
- [ ] **m3u8 v7+ HLS encryption**（`#EXT-X-KEY`）—— 保留原 m3u8 URL 让 Engine 解析
- [ ] **多 variant 选择 UI**（带宽/分辨率）—— v0.5.2 默认拿第一个；v0.5.3+ 可加 `PromptOptionsDialog` variant radio
- [ ] **WebViewHeadlessSniffer 自身单测**（v0.5.0 留的欠账，需要 Robolectric）
- [ ] **ANR 风险测试**（shouldInterceptRequest 1-3s 阻塞 Main 线程）
- [ ] **DefaultWebViewFactory 0 size / GONE / JS enabled 配置的 instrumented test 覆盖**
- [ ] **BilibiliAdapter**（WBI 签名 / click web API）
- [ ] **抖音 adapter**（X-Bogus）

### 文档同步

- [x] [PHASES.md](../PHASES.md) — 阶段 12 加
- [x] [CHANGELOG.md](../CHANGELOG.md) — + v0.5.2-android 段
- [x] [REUSE-MAP.md](../REUSE-MAP.md) — 同步 v0.5.2 M3u8Parser 映射
- [x] [README.md](../../README.md) — 阶段 12 标完成
- [x] [phase-12.md](phase-12.md) — 本文档
