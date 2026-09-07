# 阶段 17 复盘：平台 Engine 集成（✅ 完成 → v0.5.7-android）

> **最终状态**：阶段 17 收官。v0.5.6 阶段 16 留的「Engine 集成」欠账落地——[PlatformEngineRegistry]（URL → Engine 路由表）+ [BilibiliAdapter]（B 站 Engine 实现）+ [DouyinAdapter]（抖音 Engine 实现）+ [ParseAndExpandUseCase] 加 B 站/抖音 dispatch 路径 + [ParseResult.Platform] sealed variant + [PastingViewModel] 处理 Platform 分支。302/302 单测全绿（v0.5.6 279 + 23 新增），`assembleDebug` 通过。
> **v0.5.6-android tag 已发**（阶段 16 收官），本阶段成果属 v0.5.7-android tag。
>
> ⚠️ **抖音 X-Bogus 仍 stub chaos**（v0.5.5 placeholder）——probe 走真抖音 web API 仍 -352 风控。**B 站 probe 正常**（WBI 真签名 + 真 nav + view 接口）。**download 全部 v0.5.8+**：B 站 `playurl` / 抖音 `playwm` 接口拿真实下载 URL 留 v0.5.8+。

## 一句话总结

本阶段做了 **4 类事情**（按 commit 顺序）：

1. **[BilibiliAdapter]** —— `Engine` interface 实现，包装 [BilibiliApiClient]（v0.5.6）拿 metadata 填 [MediaItem]，`download()` 抛 IOException 标记 v0.5.8+
2. **[DouyinAdapter]** —— 同模式，包装 [DouyinApiClient]（v0.5.6）
3. **[PlatformEngineRegistry]** —— URL → Engine 路由表，调度 B 站/抖音 adapter
4. **[ParseAndExpandUseCase] 改造** —— 加 `PlatformEngineRegistry` 构造参数 + B 站/抖音 dispatch 路径（在 YouTube 后、Sniffer 前）+ [ParseResult.Platform] sealed variant + [PastingViewModel] 加 `is Platform` 分支

**没做**（v0.5.8+ 单独 PR）：

- **B 站 / 抖音 download 路径**（`playurl` / `playwm` 接口拿真实下载 URL + `YtDlpEngine` 跑下载）—— v0.5.7 `download()` 抛 IOException 明确标记 v0.5.8+
- **真 get_chaos 实装** —— 走抖音 web API 必做
- **B 站 / 抖音 mixin_key / X-Bogus 缓存** —— 每次请求 ~200ms 延迟
- **B 站 / 抖音 UI 集成** —— `PromptOptionsDialog` B 站清晰度选择 / 抖音合集展开
- **m3u8 v7+ HLS encryption** / **多 variant 选择 UI**
- **WebViewHeadlessSniffer 自身单测**（Robolectric）/ **ANR 风险测试** / **DefaultWebViewFactory 配置 instrumented test**

---

## 一、改了什么

### 新增文件

| 路径 | 作用 |
|---|---|
| `app/src/main/java/com/doubi/android/core/platform/PlatformEngineRegistry.kt` | URL → Engine 路由表（BILIBILI → BilibiliAdapter / DOUYIN → DouyinAdapter / YOUTUBE / GENERIC → null） |
| `app/src/main/java/com/doubi/android/core/platform/bilibili/BilibiliAdapter.kt` | B 站 Engine 实现（继承 v0.1 阶段 2 的 `Engine` interface，包装 BilibiliApiClient） |
| `app/src/main/java/com/doubi/android/core/platform/douyin/DouyinAdapter.kt` | 抖音 Engine 实现（同模式） |
| `app/src/test/java/com/doubi/android/core/platform/bilibili/BilibiliAdapterTest.kt` | 10 例单测（mockk BilibiliApiClient） |
| `app/src/test/java/com/doubi/android/core/platform/douyin/DouyinAdapterTest.kt` | 8 例单测（mockk DouyinApiClient） |

### 修改文件

| 路径 | 变化 |
|---|---|
| `app/src/main/java/com/doubi/android/core/pipeline/ParseAndExpandUseCase.kt` | 加 3rd 构造参数 [PlatformEngineRegistry]；加 B 站/抖音 dispatch 路径（YouTube → 拒绝 YouTube 频道 → **B 站/抖音 adapter** → 通用嗅探）；加 [ParseResult.Platform] sealed variant |
| `app/src/main/java/com/doubi/android/ui/pasting/PastingViewModel.kt` | `when` 加 `is ParseResult.Platform` 分支 → 走 `AwaitingConfirm(item, formats=空, seedOptions)` |
| `app/src/test/java/com/doubi/android/core/pipeline/ParseAndExpandUseCaseTest.kt` | 17 例现有测试加 `engineRegistry: PlatformEngineRegistry` mock（显式 stub `getEngine → null`）；加 5 例新测试（B 站 VIDEO / B 站 UNSUPPORTED / 抖音 VIDEO / 抖音 SHORT_LINK / 抖音 UNSUPPORTED）走真实 dispatch |
| `app/build.gradle.kts` | versionCode 14→15；versionName "0.5.6"→"0.5.7" |
| `docs/phases/phase-17.md` | 本文档 |

### 桌面版 → Android 版

```
桌面版 `src/doubi/platforms/bilibili/strategies.py:BilibiliStrategy`（B 站 Engine 策略）
  ─────────────────────────────────────────────────
  → 阶段 14 v0.5.4：BilibiliUrl + WbiSigner（platform foundation）
  → 阶段 15 v0.5.5：WbiSigner 完整 WBI 算法
  → 阶段 16 v0.5.6：BilibiliApiClient（WBI 真用）
  → 阶段 17 v0.5.7：BilibiliAdapter（**Engine interface 集成**）← 本阶段

桌面版 `src/doubi/platforms/douyin/strategies.py:DouyinStrategy`（抖音 Engine 策略）
  ─────────────────────────────────────────────────
  → 阶段 14 v0.5.4：DouyinUrl + XBogusSigner placeholder
  → 阶段 15 v0.5.5：XBogusSigner RC4 + a_bogus（get_chaos 仍 stub）
  → 阶段 16 v0.5.6：DouyinApiClient（X-Bogus 真调——**stub chaos 走 API 仍 -352**）
  → 阶段 17 v0.5.7：DouyinAdapter（**Engine interface 集成**）← 本阶段

桌面版 `src/doubi/platforms/__init__.py:PlatformRegistry`（平台 Engine 路由表）
  ─────────────────────────────────────────────────
  → 阶段 14 v0.5.4：PlatformRegistry（仅 URL→Platform 分类，无依赖）
  → 阶段 17 v0.5.7：PlatformEngineRegistry（**URL→Engine 路由**，依赖具体 adapter）← 本阶段
```

---

## 二、核心设计决定

### 决定 1：拆 PlatformRegistry 和 PlatformEngineRegistry（**不**合并）

**问题**：[PlatformRegistry]（v0.5.4 阶段 14 落地）只做 URL→Platform 分类（无依赖），但 v0.5.7 需要"URL→具体 Engine 实现"的路由——后者依赖 [BilibiliAdapter] / [DouyinAdapter]。

**v0.5.7 方案对比**：

- A) **拆成两个类**：[PlatformRegistry]（无依赖，URL→Platform）+ [PlatformEngineRegistry]（依赖 adapter，URL→Engine）—— ✅
- B) 合并成 [PlatformRegistry] 一个类，依赖全部 adapter —— 单一类持有 3 个 adapter 依赖
- C) 用 Hilt reflective discovery（`@Inject lateinit var engines: Set<@JvmSuppressWildcards Engine>`）—— 自动发现所有 Engine 实现

**选 A 的理由**：

- **分层清晰**：[PlatformRegistry] 关注"URL 是什么平台"（无副作用、纯函数）；[PlatformEngineRegistry] 关注"这个平台用哪个 Engine"（依赖注入）
- **测试解耦**：[PlatformRegistryTest] 不用 mockk 任何 adapter；[PlatformEngineRegistryTest] 单独 mock adapter 测路由表
- **未来扩展**：v0.5.8+ 加新平台（如 Twitter / Weibo），只动 [PlatformEngineRegistry]，**不**动 [PlatformRegistry]
- desktop 端两者合并成一个（classify + select）；Android 端按"分类 vs 路由"切开更符合 dependency injection 最佳实践

**风险**：

- 两类职责看似重复——reader 可能疑惑"为啥不合并"。**注释里写清楚**职责切分
- v0.5.7 仅 2 个 adapter；v0.5.8+ 数量增长（Twitter / Weibo / 等），`when` 分支会变长——届时可考虑 `Set<Engine>` 自动发现（**保留** C 方案作为未来重构路径）

### 决定 2：[ParseAndExpandUseCase] 构造加第 3 参数 [PlatformEngineRegistry]（**不**用默认参数 / @Inject lateinit var）

**问题**：[ParseAndExpandUseCase]（v0.1 阶段 4 落地）当前 2 参构造（`YtDlpEngine` + `Sniffer`），v0.5.7 集成 adapter 后变 3 参。

**v0.5.7 方案对比**：

- A) **直接改构造 + 更新 17 例现有测试** —— ✅
- B) Kotlin 默认参数：`PlatformEngineRegistry = EmptyPlatformEngineRegistry` —— 现有测试**不**破坏，但 Hilt 注入可能有歧义（默认参数 vs @Provides）
- C) `@Inject lateinit var` 字段注入 —— 字段注入是 anti-pattern，构造时无法保证 null safety

**选 A 的理由**：

- 17 例现有测试改动量**极小**：加 1 行 `private val engineRegistry: PlatformEngineRegistry = mockk()` + 1 行 `init { every { engineRegistry.getEngine(any()) } returns null }` + 1 行 useCase 构造调用更新
- dependency injection 最佳实践：**显式依赖**优于隐式默认
- Hilt 自动装配 [PlatformEngineRegistry]（`@Inject constructor` + `@Singleton`），不需要 PlatformModule 补 @Provides

**B 方案的坑**：

- Kotlin 默认参数 + Hilt 装配：Hilt 不知道用哪个（默认 vs @Provides）
- 需要 `@JvmOverloads` 给 Java 调用方生成多 constructor，对 Java 友好但 Kotlin-only 项目无意义
- "隐式依赖"违反 Android Architecture Guide

**C 方案的坑**：

- 字段注入不能 `final` 修饰，类不是 immutable
- 构造时 adapter 引用是 `null`，**首次**访问才赋值——空指针风险在 `ParseAndExpandUseCase.invoke()` 内（不是构造时）
- 单元测试需要 `@Before` 重新赋值 mock adapter

### 决定 3：dispatch 在 YouTube 后、Sniffer 前（B 站/抖音 URL **不**走 Sniffer）

**问题**：B 站/抖音 URL 走 [Sniffer] 会 HEAD 请求 + 看 Content-Type——但 B 站 `bilibili.com/video/BV1xxx` 返 HTML，B 站 `playurl` 接口才返 JSON，Content-Type 是 HTML 不会命中 m3u8/mp4。

**v0.5.7 调度顺序**：

```
1. YouTube watch URL → ParseResult.Youtube
2. YouTube 频道/播放列表 → ParseResult.Unsupported
3. B 站/抖音 adapter 路径（NEW v0.5.7）：
   - platformEngineRegistry.getEngine(trimmed) 返 Engine?
   - 是 → engine.supports() 判定；是支持类型 → engine.probe() → ParseResult.Platform
   - 否 → ParseResult.Unsupported("该 ${engine.name} URL 类型暂不支持")
4. 通用嗅探（v0.4.0 阶段 8）→ DirectLink 或 Unsupported
5. 兜底 yt-dlp 嗅探 → DirectLink
```

**理由**：

- B 站/抖音 URL **不**会被 YouTube 路径匹配（域名不同，step 1 返 null）
- B 站/抖音 URL **不**走 YouTube 拒绝路径（step 2 不会 fire）
- B 站/抖音 URL 直接走 step 3 adapter 路径，**跳过** Sniffer
- 拒绝 `youtube.com` 但非视频 URL 在 step 2 守门

**风险**：

- [Engine.supports] 调一次（v0.5.7 B 站/BilibiliUrl.classify + 抖音/DouyinUrl.classify 都是 pure function，开销可忽略）
- 如果 [Engine.supports] 返 false → 直接 Unsupported（不浪费 HTTP 请求调 probe）

### 决定 4：v0.5.7 adapter 的 `download()` 抛 IOException（**不**返回 placeholder DownloadResult）

**问题**：[Engine] interface 的 `download()` 必须返回 [DownloadResult]（v0.1 阶段 2 落地）——v0.5.7 拿不到真实下载 URL（B 站 `playurl` / 抖音 `playwm` 接口 v0.5.8+）。

**v0.5.7 方案对比**：

- A) **抛 IOException "v0.5.8+ 才有"** —— ✅
- B) 返回 `DownloadResult.Failure(error = "v0.5.8+ 才有")` —— 占位但容易掩盖实现缺陷
- C) 阻塞返回 `DownloadResult.Success(file = null, ...)` —— 假装成功更危险

**选 A 的理由**：

- **明确信号**：UI 走 `ParseStatus.Failure` 状态显示"该平台下载功能 v0.5.8+ 才有"
- 跟"未实现"语义一致——Java/Kotlin 习惯用异常表达"方法暂不可用"
- v0.5.8+ 真下时改成正常路径，UI 状态自动切换

**B 方案的坑**：

- `Failure` 跟"网络错误 / 解析失败"混在一起——`ParseStatus.Failure` UI 不知道是"未实现"还是"真错误"
- 给 v0.5.8+ 留 regression 风险：实现者要小心区分"未实现 Failure"和"真 Failure"

### 决定 5：v0.5.7 [ParseResult.Platform] formats 走空列表（**不**返回 fake formats）

**问题**：[ParseResult.Youtube] 一定带 formats（yt-dlp 几乎一定有内容）；[ParseResult.Platform]（v0.5.7 新增）拿不到 formats（adapter 没调 `playurl` / `playwm`）。

**v0.5.7 方案**：

- `data class Platform(item, formats: List<MediaFormat> = emptyList())` —— formats 走空

**理由**：

- 跟 [Youtube] 同形，调用方可以**统一**走"format 列表非空就显示下拉框，否则走'无 format 选项'"路径
- 不**伪造** formats（B 站 360p / 720p / 1080p fake 列表）—— 容易给用户错误预期
- v0.5.8+ adapter 真下时再补 formats（[BilibiliAdapter] / [DouyinAdapter] 增加 `formats: List<MediaFormat>` 返回）

**调用方处理**（[PastingViewModel]）：

```kotlin
is ParseResult.Platform -> ParseStatus.AwaitingConfirm(
    item = result.item,
    formats = result.formats,  // v0.5.7 = 空
    seedOptions = currentSeed,
)
```

UI 走「无 format 选项」路径——直接入队，让 `DownloadRepository` 拿 item.platform.key 派发到对应 Engine（v0.5.8+ Engine 真下时）。

### 决定 6：B 站 / 抖音 Adapter 的 `probe` 走 `BilibiliApiClient.view` / `DouyinApiClient.awemeItemInfo`（**不**调 yt-dlp）

**问题**：B 站/抖音 probe 可以走两条路——adapter 内部调 [BilibiliApiClient] / [DouyinApiClient]（v0.5.6 落地）拿 metadata，或者调 `YtDlpEngine.probeWithFormats(url)` 走 yt-dlp。

**v0.5.7 方案**：

- B 站 adapter → [BilibiliApiClient.view] 拿 title / duration / cid / owner
- 抖音 adapter → [DouyinApiClient.awemeItemInfo] 拿 desc / duration / author / playUrl / coverUrl

**理由**：

- **桌面版 1:1 对拍**：[BilibiliStrategy.get_metadata] 走 B 站 web API（`/x/web-interface/view`），不调 yt-dlp
- **更快**：单次 HTTP 请求 < 1s；yt-dlp 启动 5-15s
- **更准**：web API 返 metadata 完整（title / author / duration / cover），yt-dlp 嗅探经常拿不到 cover
- **避免 B 站 WBI 签名绕过**：yt-dlp 不带 WBI 签名，B 站返 -352 错误

**抖音限制**：

- X-Bogus stub chaos 走真 web API 仍 -352——adapter probe 走不通
- v0.5.7 adapter 调 `awemeItemInfo` 会抛 IOException("抖音 -352 风控")
- v0.5.8+ 真 get_chaos 实装后正常

**B 站 / 抖音 download 路径**：

- v0.5.7 adapter `download()` 抛 IOException "v0.5.8+ 才有"
- v0.5.8+ 调 [BilibiliApiClient] 拿 `playurl` / 抖音 `playwm` 接口拿真实下载 URL，再走 `YtDlpEngine` 跑下载

---

## 三、坑 & 决策

### 坑 1：`mockk(relaxed = true)` 让 `PlatformEngineRegistry.getEngine()` 返 mock Engine

**症状**：第一版 [ParseAndExpandUseCaseTest] 用 `engineRegistry: PlatformEngineRegistry = mockk(relaxed = true)`，跑测试 10 例失败：

```
expected instance of: ParseResult$DirectLink
but was instance of : ParseResult$Unsupported
with value: Unsupported(reason=该  URL 类型暂不支持：https://example.com/video.mp4)
```

**根因**：`mockk(relaxed = true)` 对**非空返回类型**会返一个 relaxed mock 实例——`getEngine(): Engine?` 是 nullable，mockk **不**返 null，返一个默认 mock Engine（`name=""` / `supports()=false`）。existing 测试的 generic URL（`example.com/stream.m3u8`）被错误派发到 mock Engine → `supports()=false` → `该  URL 类型暂不支持`（注意 `${engine.name}` 是空字符串，"该  URL"之间有双空格）。

**修法**：

```kotlin
private val engineRegistry: PlatformEngineRegistry = mockk()  // 不用 relaxed
private val useCase = ParseAndExpandUseCase(engine, sniffer, engineRegistry)

init {
    io.mockk.every { engineRegistry.getEngine(any()) } returns null
}
```

**教训**：

- `mockk(relaxed = true)` 对 nullable 返回类型**不**返 null，返 relaxed mock 实例
- 显式 stub `returns null` 是更安全的语义
- mockk 文档说 relaxed 默认值是 "default primitive / null for nullable"——**实测**对 nullable 返 mock 实例不是 null

### 坑 2：mockk adapter（relaxed=false）缺 [Engine.name] getter 桩 → MockKException

**症状**：第一版 B 站 UNSUPPORTED 测试失败：

```
io.mockk.MockKException: no answer found for BilibiliAdapter@xxx.getName()
  among the configured answers: (BilibiliAdapter@xxx.supports(eq(...), any()))
```

**根因**：`mockk()`（relaxed=false）的 [BilibiliAdapter] 没有 stub `name` getter——[ParseAndExpandUseCase] 在 adapter `supports()` 返 false 时访问 `engine.name` 拼错误信息，触发 MockKException。

**修法**：adapter 改 `mockk(relaxed = true)`——`name` / `supports` / `probe` 三个 Engine 成员都有默认 stub（`name=""` / `supports()=false` / `probe()` 抛异常）：

```kotlin
private val bilibiliAdapter: BilibiliAdapter = mockk(relaxed = true)
private val douyinAdapter: DouyinAdapter = mockk(relaxed = true)
```

**教训**：

- 模拟 [Engine] interface 实现用 `mockk(relaxed = true)`——三个成员都有默认 stub，避免 `no answer found`
- 不要 `mockk()`（relaxed=false）模拟 interface——缺一个成员 getter 桩就崩

### 坑 3：[PastingViewModel] 的 `when` 表达式 `is ParseResult` 不 exhaustive

**症状**：第一次跑测试编译失败：

```
e: file:///.../PastingViewModel.kt:78:39 'when' expression must be exhaustive.
  Add the 'is Platform' branch or an 'else' branch.
```

**根因**：[ParseAndExpandUseCase] 加 [ParseResult.Platform] sealed variant 后，调用方 [PastingViewModel] 的 `when (result)` 必须加 `is ParseResult.Platform` 分支——Kotlin sealed class exhaustive 检查强制要求。

**修法**：加分支：

```kotlin
is ParseResult.Platform -> ParseStatus.AwaitingConfirm(
    item = result.item,
    formats = result.formats,
    seedOptions = currentSeed,
)
```

**教训**：

- Kotlin sealed class 改 sealed variants 是**编译期强制 exhaustive 检查**——漏掉一处 `when` 编译失败，立刻能发现
- 加新 variant 必查所有 `when` over sealed class 位置（grep `is ParseResult\.<Variant>` 找出全部调用方）

### 坑 4：v0.5.4-v0.5.5 阶段遗留 5 份 platform 测试文件**未**提交（pre-existing untracked）

**症状**：`git status` 显示 5 份 platform 测试文件 untracked（LastWriteTime 9/2-9/4 是 v0.5.4-v0.5.5 阶段创建）：

- `PlatformRegistryTest.kt`（v0.5.4 阶段 14 创建）
- `BilibiliUrlTest.kt`（v0.5.4 阶段 14 创建）
- `WbiSignerTest.kt`（v0.5.4 阶段 14 创建）
- `DouyinUrlTest.kt`（v0.5.4 阶段 14 创建）
- `CustomBase64Test.kt`（v0.5.5 阶段 15 创建）

**根因**：v0.5.4 / v0.5.5 commit 收官时**漏**了 commit 这些 test 文件——production 代码 commit 进去了，test 文件**未** commit。但 working tree 一直保留这些文件，gradle test 一直跑它们。

**v0.5.7 决定**：

- **不**在 v0.5.7 commit 里附带这 5 份（避免 conflate v0.5.4-v0.5.5 欠账和 v0.5.7 平台 Engine 集成）
- **已知遗留项**在 phase-17 复盘文档里登记
- 后续单独 PR（`chore(android): 补 commit v0.5.4-v0.5.5 阶段遗留的 5 份 platform 测试文件`）

**风险**：

- working tree 删这些文件 → 后续测试会少 5+N 例（需要从 git history 找回）
- working tree 保留这些文件 → 持续 untracked 状态（`git status` 看着乱）

**教训**：

- 每个阶段 commit 收官前**检查** `git status` 看有没有 untracked 文件
- 阶段 14 收官没检查 → 留债到阶段 17 才暴露

---

## 四、验证

### 单测

| 测试类 | 例数 | 状态 |
|---|---|---|
| ...（v0.5.6 之前所有测试 + 5 份 untracked 测试）| 279 | ✅ |
| **`BilibiliAdapterTest`** | **10**（v0.5.7 新增：name / supports × 4 / probe × 3 / download placeholder）| ✅ |
| **`DouyinAdapterTest`** | **8**（v0.5.7 新增：name / supports × 3 / probe × 3 / download placeholder）| ✅ |
| **`ParseAndExpandUseCaseTest` 新增** | **5**（B 站 VIDEO / B 站 UNSUPPORTED / 抖音 VIDEO / 抖音 SHORT_LINK / 抖音 UNSUPPORTED）| ✅ |
| **总计** | **302**（v0.5.6 279 + 23 新增）| ✅ |

### APK 验证

```
$ ./gradlew assembleDebug
BUILD SUCCESSFUL in 16s

APK: app/build/outputs/apk/debug/app-debug.apk  80.6 MB（v0.5.6 80.4 MB + 0.2 MB）
- platforms/PlatformEngineRegistry.kt（新增 ~60 行）
- platforms/bilibili/BilibiliAdapter.kt（新增 ~100 行）
- platforms/douyin/DouyinAdapter.kt（新增 ~95 行）
- 0 新依赖（Hilt + MockK 已在 classpath）
```

### 静态检查

`./gradlew testDebugUnitTest --rerun` 全绿 302 例（v0.5.6 279 + 23 新增）。

---

## 五、复盘清单

### 做了

- [x] **[BilibiliAdapter]**（v0.5.7 Commit 1）—— `Engine` interface 实现 + 10 例单测
- [x] **[DouyinAdapter]**（v0.5.7 Commit 2）—— `Engine` interface 实现 + 8 例单测
- [x] **[PlatformEngineRegistry]**（v0.5.7 Commit 3）—— URL → Engine 路由表
- [x] **[ParseAndExpandUseCase] 改造**（v0.5.7 Commit 3）—— 加 3rd 构造参数 + B 站/抖音 dispatch + [ParseResult.Platform] sealed variant + 5 例新单测
- [x] **[PastingViewModel] 加 `is Platform` 分支**（v0.5.7 Commit 3）
- [x] **versionCode 14→15** + versionName "0.5.6"→"0.5.7"（v0.5.7 Commit 4）
- [x] **302/302 单测全绿**
- [x] **`assembleDebug` 通过**
- [x] **阶段 17 复盘文档**（本文档）

### 没做（v0.5.8+ 单独 PR）

- [ ] **B 站 / 抖音 download 路径**（`playurl` / `playwm` 接口拿真实下载 URL + `YtDlpEngine` 跑下载）—— v0.5.7 `download()` 抛 IOException 明确标记 v0.5.8+
- [ ] **真 get_chaos 实装**（v0.5.6 抖音 API 仍 -352 风控）
- [ ] **B 站 / 抖音 mixin_key / X-Bogus 缓存**（每次请求 ~200ms 延迟）
- [ ] **B 站 / 抖音 UI 集成**（`PromptOptionsDialog` B 站清晰度选择 / 抖音合集展开）
- [ ] m3u8 v7+ HLS encryption / 多 variant 选择 UI
- [ ] `WebViewHeadlessSniffer` 自身单测（Robolectric）
- [ ] ANR 风险测试
- [ ] `DefaultWebViewFactory` 0 size / GONE / JS enabled 配置的 instrumented test
- [ ] 仪器测试 10 个真机 adb install（v0.1 留的债，跨阶段欠账 #5）

### 已知遗留项

- [ ] **5 份 v0.5.4-v0.5.5 阶段 platform 测试文件 untracked**（`PlatformRegistryTest` / `BilibiliUrlTest` / `WbiSignerTest` / `DouyinUrlTest` / `CustomBase64Test`）—— working tree 一直保留并被 gradle test 跑，**未** commit 进 git。后续单独 PR `chore(android): 补 commit v0.5.4-v0.5.5 阶段遗留的 5 份 platform 测试文件`

### 文档同步

- [x] [PHASES.md](../PHASES.md) — 阶段 17 加
- [x] [CHANGELOG.md](../CHANGELOG.md) — + v0.5.7-android 段
- [x] [REUSE-MAP.md](../REUSE-MAP.md) — 同步 v0.5.7 Engine 集成映射
- [x] [README.md](../../README.md) — 阶段 17 标完成
- [x] [phase-17.md](phase-17.md) — 本文档
