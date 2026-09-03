# 阶段 8 复盘：通用嗅探（✅ 完成 → v0.4.0-android）

> **最终状态**：阶段 8 收官。Sniffer interface + HttpContentTypeSniffer + SniffResult sealed 落地；SnifferModule Hilt 装配（OkHttp 10s connect / 10s read + followRedirects=true）；ParseAndExpandUseCase 集成 Sniffer 路径（YouTube ❌ → youtube 域名非视频 ❌ → Sniffer 嗅探 → Media / NotMedia / Error 降级 yt-dlp）；PastingScreen Sniffing 状态提示；183 单测全绿（v0.3.0 167 + 16 新增）。
> **v0.3.0-android tag 已发**（阶段 7 收官），本阶段成果属 v0.4.0-android tag。

## 一句话总结

本阶段做了 **4 类事情**：

1. **Sniffer 抽象层**：interface `Sniffer` + sealed `SniffResult`（Media / NotMedia / Error 三分支）+ OkHttp 实现 `HttpContentTypeSniffer`
2. **Hilt 装配**：`SnifferModule` 提供专用 `OkHttpClient`（10s connect / 10s read + followRedirects），`@Binds` 把 interface 绑到实现
3. **ParseAndExpandUseCase 集成**：URL 不在 YouTube 走 Sniffer；Sniffer Media → DirectLink；NotMedia → Unsupported；Error → 降级 yt-dlp
4. **PastingScreen Sniffing 状态**：新 `ParseStatus.Sniffing` object；UI 用 `isLoading` 合并 Parsing + Sniffing，但 loadingText 区分（"解析中…" vs "嗅探中…"）

**没做**（v0.5.0 单独 PR）：
- headless browser 嗅探（WebView load URL + 拦截 m3u8 请求）—— 覆盖 B 站 / 抖音主页 / Twitter 视频页等"页面 JS 异步加载"
- B 站 / 抖音 / Twitter 等具体平台 adapter

---

## 一、改了什么

### 新增文件

| 路径 | 作用 |
|---|---|
| `app/src/main/java/com/doubi/android/core/sniffer/Sniffer.kt` | Sniffer interface（1:1 对拍桌面版 `src/doubi/core/sniffer.py:Sniffer`） |
| `app/src/main/java/com/doubi/android/core/sniffer/SniffResult.kt` | sealed SniffResult（Media / NotMedia / Error 三分支） |
| `app/src/main/java/com/doubi/android/core/sniffer/HttpContentTypeSniffer.kt` | OkHttp HEAD + isMediaContentType 实现 |
| `app/src/main/java/com/doubi/android/core/sniffer/di/SnifferModule.kt` | Hilt 装配（provide OkHttpClient + @Binds Sniffer ↔ HttpContentTypeSniffer） |
| `app/src/test/java/com/doubi/android/core/sniffer/HttpContentTypeSnifferTest.kt` | 13 例单测（mp4 / m3u8 / webm / octet-stream / audio / 大小写 / HTML / 404 / 500 / SocketTimeout / UnknownHost / 重定向 / x-mpegurl） |

### 修改文件

| 路径 | 变化 |
|---|---|
| `app/src/main/java/com/doubi/android/core/pipeline/ParseAndExpandUseCase.kt` | 注入 `Sniffer`；YouTube ❌ → youtube 域名非视频 ❌ → **Sniffer 嗅探** → Media(DirectLink) / NotMedia(Unsupported) / Error(降级 yt-dlp) |
| `app/src/main/java/com/doubi/android/ui/pasting/PastingViewModel.kt` | 新 `ParseStatus.Sniffing` object；`onParseClicked()` 调 use case 前按 URL 预判（YouTube → Parsing，其他 → Sniffing） |
| `app/src/main/java/com/doubi/android/ui/pasting/PastingScreen.kt` | `isLoading` 合并 Parsing + Sniffing；`loadingText` 区分（"解析中…" / "嗅探中…"）；输入框 / 按钮 enabled 跟 isLoading 联动 |
| `app/src/main/res/values/strings.xml` | + `pasting_sniffing` 字符串（"嗅探中…"） |
| `app/src/test/java/com/doubi/android/core/pipeline/ParseAndExpandUseCaseTest.kt` | 适配 `Sniffer` 注入：5 个 DirectLink 测试 + stub `sniffer.sniff(url)` 返回 Media；+3 个 v0.4.0 Sniffer 行为测试（NotMedia Unsupported / Error 降级 / 404 提示） |
| `app/build.gradle.kts` | `versionCode 5 → 6`；`versionName "0.3.0" → "0.4.0"`（跟 v0.4.0-android tag 同步） |
| `docs/CHANGELOG.md` | +「未发布 v0.4.0」段 |
| `docs/PHASES.md` | 阶段 7 标 ✅；新增阶段 8 段 |
| `docs/REUSE-MAP.md` | 同步 v0.4.0 通用嗅探映射 |
| `README.md` | 阶段 8 标完成 |

### 桌面版 → Android 版

```
src/doubi/core/sniffer.py:Sniffer (HTTP Content-Type 嗅探)
src/doubi/core/pipeline.py:DownloadPipeline.parse_and_expand (3 分支: Youtube / DirectLink / Unsupported)
  ─────────────────────────────────────────────────────────────────
  → core/sniffer/Sniffer.kt + SniffResult.kt + HttpContentTypeSniffer.kt
  → core/sniffer/di/SnifferModule.kt (Hilt 装配)
  → core/pipeline/ParseAndExpandUseCase.kt 集成 Sniffer 路径
  → ui/pasting/PastingViewModel.kt + PastingScreen.kt (Sniffing 状态)
```

---

## 二、核心设计决定

### 决定 1：拆 v0.4.0 通用嗅探 + v0.5.0 B 站/抖音 两版

**v0.4.0 范围**：HTTP Content-Type 嗅探（OkHttp HEAD），覆盖直链 m3u8 / mp4 / webm / 任意"浏览器访问会被 inline 播放"的视频。
**v0.5.0 范围（不做）**：headless browser 嗅探（WebView load URL + 拦截 m3u8 请求）+ B 站 / 抖音 / Twitter adapter。

**为什么拆**：
- v0.4.0 只用 OkHttp HEAD（HTTP 层），10s connect / 10s read，**单版本可控**
- v0.5.0 要做 headless browser（WebView 集成 + 跨进程 JS 桥接 + 风险评估）——单版本太大
- B 站 / 抖音 / Twitter 等具体平台 adapter（平台 WBI 签名 / click web API / 抖音 X-Bogus）也放 v0.5.0
- v0.4.0 完成 → 用户可以拿任意 m3u8 / mp4 直链玩，v0.5.0 再扩 B 站 / 抖音

**风险**：v0.4.0 不覆盖"页面 JS 异步加载"——B 站 / 抖音主页 / Twitter 视频页嗅探不到。但这跟 v0.1 阶段 4 写的"直链嗅探"行为一致（v0.1 阶段 4 只能嗅探 `.m3u8` / `.mp4` 扩展名结尾的 URL，v0.4.0 升级为 HTTP Content-Type 但仍然不覆盖 JS 异步加载），**功能演进不破坏现有契约**。

### 决定 2：Sniffer 跟 Engine 分层

**Sniffer** 在 use case 内部调（不在 YtDlpEngine 内部）：

```
用户 URL
  ↓
ParseAndExpandUseCase
  ├── 1) YouTube? → ytDlpEngine.probeWithFormats(watchUrl)
  ├── 2) youtube 域名但非视频? → Unsupported
  └── 3) Sniffer.sniff(url)
        ├── Media → ytDlpEngine.probeWithFormats(finalUrl) → DirectLink
        ├── NotMedia → Unsupported
        └── Error → runYtDlpFallback(url) → DirectLink
```

**理由**：
- Sniffer 是"判定直链能不能下"的辅助，Engine 是"真下"的执行者——**分层清晰**
- Sniffer 跟 Engine 解耦：v0.5.0 加 headless browser Sniffer 不会影响 Engine
- Sniffer 错误时不直接拒，降级让 yt-dlp 兜底——**保留 v0.1 阶段 4 兜底路径**

### 决定 3：Sniffer 内不再 `newBuilder()` 二次配置 OkHttp client

**v0.4.0 起步版本**：Sniffer 构造器内 `httpClient.newBuilder().connectTimeout(10s).readTimeout(10s).followRedirects(true)...build()` 二次配置。
**v0.4.0 收尾版本**：去掉，所有超时 / 重定向统一由 `SnifferModule.provideOkHttpClient()` 配。

**理由**：
- mock 注入的 OkHttpClient `newBuilder()` 是 final method，mockk relaxed=true 才能模拟，**测试要写更复杂的 stub**
- 生产环境 OkHttp client 跟 Sniffer 用的 OkHttp client **应该共享配置**（超时 / 重定向 / 拦截器）—— 一次配置更清晰
- SnifferModule 已经 provide `OkHttpClient` 10s connect / 10s read / followRedirects=true / followSslRedirects=true，**配置完整**

**风险**：如果未来要分"sniffer 专用 client"（比如允许更长的嗅探超时），需要在 SnifferModule 加 `@Named("sniffer")` qualifier——v0.5.0 再做。

### 决定 4：Sniffer Error 降级让 yt-dlp 兜底，不直接拒

```kotlin
is SniffResult.Error -> {
    // Sniffer 出错（网络 / DNS / SSL）：降级让 yt-dlp 自己嗅探，不直接拒
    // ——v0.1 阶段 4 的兜底路径给机会
    runYtDlpFallback(trimmed)
}
```

**理由**：
- Sniffer 失败 ≠ URL 真的不能下——可能只是 sniff 那一瞬间网络抖动
- yt-dlp 是 v0.1 阶段 2 接入的成熟嗅探器，让它再试一次是**稳健的兜底**
- 直接拒会**降低用户体验**（用户贴了个 URL，App 说"不行"但其实 yt-dlp 能下）

**风险**：Sniffer 失败的 URL 走 yt-dlp 兜底时，用户体验是"嗅探失败后等 15s+ 才出结果"。v0.5.0 优化时**先报 Sniffer 错误给用户**（"嗅探失败，尝试 yt-dlp 兜底..."）再让 yt-dlp 跑。

### 决定 5：PastingScreen `isLoading` 合并 + `loadingText` 区分

```kotlin
val isLoading = state.parseStatus is PastingViewModel.ParseStatus.Parsing ||
    state.parseStatus is PastingViewModel.ParseStatus.Sniffing
val loadingText = if (state.parseStatus is PastingViewModel.ParseStatus.Sniffing) {
    sniffingMsg
} else {
    parsingMsg
}
```

**理由**：
- Parsing 跟 Sniffing 都是"等 use case 返回"中——共享一个 CircularProgressIndicator
- loadingText 区分让用户知道"为啥这条 URL 卡了一会"——YouTube 走 yt-dlp 慢一点合理，非 YouTube 走 HEAD 10s 上限
- v0.4.0 起步纠结过要不要加 `Sniffing` 子类（vs 复用 `Parsing` 状态）——加了让状态机更显式，**未来 v0.5.0 加"正在下载字幕"等状态也好扩展**

---

## 三、坑 & 决策

### 坑 1：Kotlin 注释 `video/*` 跟 `audio/*` 嵌套触发（第 3 次踩）

**症状**：HttpContentTypeSniffer.kt L82-89 的注释里 `video/*` 跟 `audio/*` 触发了 Kotlin 注释的**嵌套**语义（Kotlin 跟 Java 不同——Java `/* /* */ */` 不允许嵌套，Kotlin 允许 `/* 外层 /* 内层 */ 外层继续 */`）。第一个 `*/` 关闭内层注释，外层没人关，整个文件都被当作注释块。KSP 报 "L80 Missing '}'" 跟 "L103 Unclosed comment"。

**根因**：Kotlin 注释**支持嵌套**——这是 Kotlin 跟 Java 的注释语义差异（v0.1 阶段 1 跟 阶段 2 各踩过一次类似坑，这次是第 3 次）。

**修法**：把注释里所有 `video/*` / `audio/*` 改写成 `video_(any)` / `audio_(any)`：

```diff
- * 主 mime type 是 video/* / audio/* /
+ * 主 mime type 是 video_(any) / audio_(any) /
```

**教训**：
- 写 Kotlin 注释时**不要**让 `/*` 出现——避免嵌套触发
- 遇到 "Missing '}'" + "Unclosed comment" 两个错同时报，**几乎肯定是注释嵌套问题**

### 坑 2：mockk `every { resp.close() } returns Unit` 注册时真执行 close 抛错

**症状**：测试里 stub `every { resp.close() } returns Unit`——mockk 注册 every 时会**真执行一次** `resp.close()` 测返回值，OkHttp 4.12 的 `Response.close()` 在 builder 没设 body 时抛 `IllegalStateException: response is not eligible for a body and must not be closed`。11 个测试 fail，trace 全指向 `HttpContentTypeSnifferTest.kt:262` 的 `every { resp.close() } returns Unit`。

**根因**：mockk 的 `every { }` 块在初始化时**实际执行**一次目标调用来记录 stub 行为，OkHttp Response.close() 的 invariant 检查在 builder 阶段 body=null 时抛错。

**修法**：
1. Sniffer 改用 `try { ... } finally { headResp.body?.close() }` 手动 null-safe close
2. 测试**不要** stub `resp.close()`——body null 时 OkHttp `body?.close()` 走 null 分支 no-op 即可

```diff
- headResp.use { resp -> ... }
+ try { ... } finally { headResp.body?.close() }
```

**教训**：
- 测 OkHttp Response 时**不要** stub `close()`——让 OkHttp 的 invariant 检查自己抛错（或者用 `headResp.body?.close()` 绕过）
- mockk 的 `every { }` 块会**真执行**目标调用来记录 stub——如果目标调用有副作用 / invariant 检查，要小心

### 坑 3：Sniffer 构造器 `newBuilder()` 让 mock 注入复杂化

**症状**：v0.4.0 起步版本 Sniffer 构造器 `httpClient.newBuilder().connectTimeout(10s).readTimeout(10s).followRedirects(true)...build()` 二次配置 OkHttp client。但 mock 注入的 OkHttpClient `newBuilder()` 是 final method，mockk 默认不模拟 final method，**测试 fail with "no answer found for newBuilder()"**。

**根因**：mockk 默认只模拟 open method（Kotlin class 默认 final），要 `mockk(relaxed = true)` 才能模拟 `newBuilder()` 等 final method。

**修法**：
1. Sniffer 去掉 `newBuilder()` 二次配置——所有超时 / 重定向统一由 `SnifferModule.provideOkHttpClient()` 配
2. Sniffer 直接 `private val client: OkHttpClient` 持有注入的 client

**教训**：
- Sniffer / Engine 这类"工具类"**不应该**二次配置 OkHttp client——让 Hilt module 统一配
- 如果真要分"sniffer 专用 client"，用 `@Named("sniffer")` qualifier 而不是 `.newBuilder()` 复制

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
| `ParseAndExpandUseCaseTest` | **17**（v0.3.0 14 + 3 Sniffer 行为）| ✅ |
| `YtDlpEngineTest` | 26 | ✅ |
| `DownloadWorkerTest` | 13 | ✅ |
| `ExampleUnitTest` | 1 | ✅ |
| `DownloadingViewModelTest` | 5 | ✅ |
| `HistoryViewModelTest` | 6 | ✅ |
| `SettingsViewModelTest` | 3 | ✅ |
| **`HttpContentTypeSnifferTest`** | **13**（v0.4.0 新增）| ✅ |
| **总计** | **183**（v0.3.0 167 + 16 新增）| ✅ |

**HttpContentTypeSnifferTest 13 例覆盖**：
- mp4 / m3u8 / webm / octet-stream / audio 5 例 Media 分支
- x-mpegurl variant 1 例（m3u8 另一种 Content-Type）
- 混合大小写 Content-Type 1 例（"Video/MP4; charset=utf-8"）
- HTML 页面 / 404 / 500 3 例 NotMedia 分支
- SocketTimeoutException / UnknownHostException 2 例 Error 分支
- 重定向链 finalUrl 1 例（resp.request.url 是 OkHttp followRedirects 后的最终 URL）

**ParseAndExpandUseCaseTest +3 例覆盖**：
- `sniffer NotMedia (HTML page) returns Unsupported without yt-dlp fallback`（Sniffer 明确说不是 media → 直接 Unsupported，不调 yt-dlp）
- `sniffer Error (network failure) falls back to yt-dlp probe`（Sniffer 网络错误 → 降级让 yt-dlp 自己嗅探）
- `sniffer 404 NotMedia returns Unsupported with status code in reason`（Sniffer 404 → Unsupported reason 含 "404"）

### APK 验证

```bash
$ ./gradlew.bat assembleDebug
BUILD SUCCESSFUL in 13s
41 actionable tasks: 14 executed, 27 up-to-date
```

APK 编译通过，Hilt module 装配 OK（Sniffer 注入到 ParseAndExpandUseCase，HttpContentTypeSniffer 注入 OkHttpClient）。

### 静态检查

`./gradlew.bat testDebugUnitTest --rerun` 全绿 183 例。

---

## 五、APK 验证

```
APK: app/build/outputs/apk/debug/app-debug.apk  (v0.3.0 维持 ~77 MB)

Hilt 注入链：
  SnifferModule.provideOkHttpClient() (10s connect / 10s read + followRedirects)
    ↓ @Singleton
  HttpContentTypeSniffer (Sniffer 实现)
    ↓ @Inject
  ParseAndExpandUseCase (URL 不在 YouTube 走 Sniffer)
    ↓ @Inject
  PastingViewModel (按 URL 预判 Parsing / Sniffing 状态)
```

---

## 六、复盘清单

### 做了

- [x] Sniffer interface + SniffResult sealed 落地
- [x] HttpContentTypeSniffer OkHttp HEAD 实现（10s 超时 + follow redirects）
- [x] SnifferModule Hilt 装配
- [x] ParseAndExpandUseCase 集成 Sniffer 路径（YouTube ❌ → youtube 域名非视频 ❌ → Sniffer → Media / NotMedia / Error 降级）
- [x] PastingScreen Sniffing 状态提示（"嗅探中…" 区别 Parsing "解析中…"）
- [x] 单测 HttpContentTypeSniffer 13 例 + ParseAndExpandUseCase +3 例
- [x] versionName="0.4.0" + versionCode=6 同步
- [x] 阶段 8 复盘文档

### 没做（v0.5.0 单独 PR）

- [ ] **headless browser 嗅探**（WebView load URL + 拦截 m3u8 请求）—— 覆盖 B 站 / 抖音主页 / Twitter 视频页等"页面 JS 异步加载"
- [ ] **B 站 / 抖音 / Twitter 等具体平台 adapter**（平台 WBI 签名 / click web API / 抖音 X-Bogus）
- [ ] **容器展开**（YouTube playlist / 抖音合集 / B 站收藏夹）—— v0.5.0+ 用 desktop 同样的 `expand` 接口扩展

### 文档同步

- [PHASES.md](../PHASES.md) — 阶段 7 标 ✅；新增阶段 8 段
- [CHANGELOG.md](../CHANGELOG.md) — 加 v0.4.0-android 段
- [REUSE-MAP.md](../REUSE-MAP.md) — 同步 v0.4.0 通用嗅探映射
- [README.md](../../README.md) — 阶段 8 标完成
- [phase-8.md](phase-8.md) — 本文档
