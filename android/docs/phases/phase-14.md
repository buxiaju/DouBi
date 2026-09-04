# 阶段 14 复盘：BilibiliAdapter / 抖音 adapter foundation（✅ 完成 → v0.5.4-android）

> **最终状态**：阶段 14 收官。v0.5.0 阶段 10 留的「BilibiliAdapter / 抖音 adapter」欠账（[phase-10.md](phase-10.md) 已知问题段）落地——抽 [BilibiliUrl] / [DouyinUrl] / [WbiSigner] / [XBogusSigner] / [PlatformRegistry] 5 个 foundation 类 + Hilt 装配。258/258 单测全绿（v0.5.3 221 + 37 新增），`assembleDebug` 通过。
> **v0.5.3-android tag 已发**（阶段 13 收官），本阶段成果属 v0.5.4-android tag。
>
> ⚠️ **v0.5.4 是 foundation 范围**——XBogusSigner 是 placeholder，**不**是抖音真算法。v0.5.5+ 实装真 X-Bogus 算法 + API 客户端 + Engine 集成 + UI 集成才能真正下 B 站 / 抖音视频。

## 一句话总结

本阶段做了 **5 类事情**（按 commit 顺序）：

1. **B 站 URL 分类** — `BilibiliUrl`（VIDEO / SHORTS / BANGUMI / AUDIO / LIVE / UNSUPPORTED 6 种）+ 10 例单测
2. **B 站 WBI 签名** — `WbiSigner`（公开反编译算法实现，32 字符 mixin_key + MD5 签名）+ 6 例单测
3. **抖音 URL 分类** — `DouyinUrl`（VIDEO / SHORT_LINK / UNSUPPORTED 3 种）+ 9 例单测
4. **抖音 X-Bogus placeholder** — `XBogusSigner`（**结构对齐但算法简化**——SHA-256(UA + URL + timestamp) → base64 前 20 字符，**不是**抖音真 X-Bogus 输出）+ 5 例单测
5. **PlatformRegistry + Hilt** — `PlatformRegistry.classify(url) → Platform`（BILIBILI / DOUYIN / YOUTUBE / GENERIC 4 种分发）+ 7 例单测 + `PlatformModule` Hilt 装配

**没做**（v0.5.5+ 单独 PR）：
- **真 X-Bogus 算法实装**（公开反编译的完整版本需要 RC4 加密 + MD5 + 复杂字节操作 + 编码，**没有真抖音 web 响应作为 test vector** 没法 byte-for-byte 验证）
- **B 站 / 抖音 API 客户端**（OkHttp + Retrofit 调 web API，需要 WBI / X-Bogus 签名支持）
- **Engine 集成**（`PlatformAdapter` 实现 `Engine` interface，调度 B 站 / 抖音 adapter）
- **UI 集成**（`PromptOptionsDialog` 加 B 站清晰度选择 + 抖音合集）
- **m3u8 v7+ HLS encryption** + **多 variant 选择 UI**（v0.5.3 留的欠账）

---

## 一、改了什么

### 新增文件

| 路径 | 作用 |
|---|---|
| `app/src/main/java/com/doubi/android/core/platform/bilibili/BilibiliUrl.kt` | B 站 URL 分类（6 种类型）+ `toCanonicalUrl` 归一化 |
| `app/src/main/java/com/doubi/android/core/platform/bilibili/WbiSigner.kt` | B 站 WBI 签名算法（mixin_key 提取 + w_rid 签名） |
| `app/src/main/java/com/doubi/android/core/platform/douyin/DouyinUrl.kt` | 抖音 URL 分类（3 种类型）+ `toCanonicalUrl` 归一化 |
| `app/src/main/java/com/doubi/android/core/platform/douyin/XBogusSigner.kt` | 抖音 X-Bogus 签名 **placeholder**（v0.5.4 简化版） |
| `app/src/main/java/com/doubi/android/core/platform/PlatformRegistry.kt` | URL → Platform 分发器（BILIBILI / DOUYIN / YOUTUBE / GENERIC） |
| `app/src/main/java/com/doubi/android/core/platform/di/PlatformModule.kt` | Hilt 装配（PlatformRegistry + BilibiliUrl + DouyinUrl；WbiSigner / XBogusSigner 自动 @Inject） |
| `app/src/test/java/com/doubi/android/core/platform/bilibili/BilibiliUrlTest.kt` | 10 例 URL 分类单测 |
| `app/src/test/java/com/doubi/android/core/platform/bilibili/WbiSignerTest.kt` | 6 例 WBI 签名单测 |
| `app/src/test/java/com/doubi/android/core/platform/douyin/DouyinUrlTest.kt` | 9 例 URL 分类单测 |
| `app/src/test/java/com/doubi/android/core/platform/douyin/XBogusSignerTest.kt` | 5 例 X-Bogus 签名单测（验证结构，不验证 byte-for-byte） |
| `app/src/test/java/com/doubi/android/core/platform/PlatformRegistryTest.kt` | 7 例 Platform 分发单测 |
| `docs/phases/phase-14.md` | 本文档 |

### 修改文件

| 路径 | 变化 |
|---|---|
| `app/build.gradle.kts` | versionCode 11→12；versionName "0.5.3"→"0.5.4" |
| `app/src/test/java/com/doubi/android/ExampleUnitTest.kt` | 注释加「阶段 14 升到 v0.5.4」一行 |

### 桌面版 → Android 版

```
桌面版 `src/doubi/platforms/bilibili/`（含 `api` / `auth` / `strategies` / `url` / `wbi` / `qr_login`）~1500
  ─────────────────────────────────────────────────
  → 阶段 14 v0.5.4：B 站 foundation
    ├─ platforms/bilibili/BilibiliUrl.kt —— URL 分类（video / shorts / bangumi / live / audio）
    ├─ platforms/bilibili/WbiSigner.kt —— WBI 签名算法（公开反编译 + 真 nav API 输入）
    └─ platforms/PlatformRegistry.kt —— 平台分发

桌面版 `src/doubi/platforms/douyin/`（含 `api` / `auth` / `strategies` / `url` / `live`）~1200
  ─────────────────────────────────────────────────
  → 阶段 14 v0.5.4：抖音 foundation
    ├─ platforms/douyin/DouyinUrl.kt —— URL 分类（main site / short link）
    ├─ platforms/douyin/XBogusSigner.kt —— **v0.5.4 placeholder**（v0.5.5+ 实装真算法）
    └─ platforms/PlatformRegistry.kt —— 平台分发
```

桌面版 1:1 对拍 + 同算法实现。XBogusSigner **算法本体**留 v0.5.5+ 实装（需要真抖音 web 响应作为 test vector）。

---

## 二、核心设计决定

### 决定 1：v0.5.4 只做 foundation，不做 API + Engine + UI

**问题**：双 adapter 一起做 scope 太大——B 站 1:1 对拍桌面版 ~1500 行（api / auth / strategies / url / wbi / qr_login），抖音 ~1200 行（api / auth / strategies / url / live）。

**v0.5.4 方案对比**：
- A) 完整 B 站 + 完整抖音一起做（API + Engine + UI）—— 2-3 周，代码量超 3 个 v0.5.x PR 总和
- B) **只做 foundation 层**（URL 分类 + 签名算法 + 平台分发）—— 1 周内能合
- C) 拆 2 个版本（B 站一个 / 抖音一个）—— 但用户选了"一起做"

**选 B**：foundation 是不依赖网络 / Engine / UI 的纯逻辑层，能 100% 单测覆盖。v0.5.5+ 单独
PR 加 API 客户端 / Engine 集成 / UI 集成。

**为什么这有合理性**：
- 桌面版 `platforms/` 目录本身就有 7+ 子目录（api / auth / strategies / url / wbi / qr_login），
  Android 端 v0.5.4 对应桌面版的 `url.py` + `wbi.py`（B 站）/ `xbogus.py`（抖音）3 个文件
- v0.5.5+ 对应桌面版的 `api.py` + `auth.py` + `strategies.py` 等剩余文件
- 拆 foundation + 集成的边界**清晰**

**风险**：XBogusSigner 是 placeholder，**不**是抖音真算法。v0.5.5+ 必须实装真算法
+ API 客户端 + Engine 集成才能真正下抖音视频。

### 决定 2：XBogusSigner v0.5.4 是 placeholder，**不**做 byte-for-byte 真算法

**问题**：公开反编译的抖音 X-Bogus 算法涉及 RC4 加密 + MD5 + 复杂字节操作 + 编码，
代码量 200+ 行，**没有真抖音 web 响应作为 test vector** 没法 byte-for-byte 验证。

**v0.5.4 方案**：实现 placeholder——SHA-256(UA + URL + timestamp) 拼一起，取前 20
字符 base64。**结构对齐**（输入参数 + 输出格式 + 长度 + 字符集），但**算法值不
等于**抖音真 X-Bogus。

**对比方案**：
- A) 完全跳过 XBogusSigner，v0.5.4 不实装 — v0.5.4 验收缺 X-Bogus 入口
- B) **placeholder 落地** + 文档清楚标记 v0.5.5+ 必须实装真算法 ✅（选 B）
- C) 直接 port 公开反编译算法，赌 byte-for-byte 正确——不测可能 ship broken code

**选 B 的理由**：
- 诚实——placeholder 输出**不能**直接拿去打抖音 web API（会被 -352）
- 单测验证**结构**（参数敏感性 / 确定性 / 输出长度）——v0.5.5+ 替换为真算法时这些测试
  仍然有效
- v0.5.5+ API 集成时**新加**byte-for-byte 测试（用真抖音 web 响应作为 test vector）

**代码注释清晰标记**——`XBogusSigner` 类头注释 + `sign` 方法注释都说明
"v0.5.4 placeholder, v0.5.5+ 实装真算法"。

### 决定 3：WbiSigner v0.5.4 是真算法实装

**问题**：WBI 签名的公开反编译算法比 X-Bogus 简单很多（mixin_key 表替换 + MD5 签名），
代码量 ~50 行，**结构**清晰，公开文档详细。

**v0.5.4 方案**：实装完整算法。`extractMixinKey(imgUrl, subUrl): String` + `sign(query,
mixinKey, wts): String`。

**为什么这次能实装**：
- 算法简单（无 RC4 / 无复杂字节操作）
- 公开文档详细（mixin_key 表 32 个下标写得很清楚）
- MD5 是 Java 标准库（`MessageDigest.getInstance("MD5")`）
- 1:1 对拍桌面版 `src/doubi/platforms/bilibili/wbi.py`（Python 实现）

**测试限制**：
- 没有真 B 站 nav 响应作为 test vector——**不**验证 byte-for-byte 输出
- 单测验证**结构**（字符数、表替换正确性、MD5 长度、确定性、参数敏感性）
- v0.5.5+ API 集成时用真 B 站 nav 响应验证 byte-for-byte + 新加 test cases

**风险**：
- 公开反编译的算法如果 B 站前端 JS 改了，签名会失败——v0.5.5+ live validation
- 跟 XBogusSigner 的 placeholder 同样的潜在风险——但代码可读性更强，修正更简单

### 决定 4：PlatformRegistry 不做 unsupported 二次过滤

**v0.5.4 行为**：`classify(url)` 看到 `bilibili.com` 域名就返 [Platform.BILIBILI]，
**不**管 URL 内容是 video / bangumi / live / 专栏 / 列表。

**对比方案**：
- A) 二次过滤——看到 `bilibili.com/read/...` 返 GENERIC（拒绝）——v0.5.5+ Engine 集成
  时再做
- B) **只做域名分发**——内容分类留 Engine 层 ✅（选 B）

**选 B 的理由**：
- v0.5.4 只做 foundation——Engine 集成是 v0.5.5+ 的事
- 二次过滤需要 Engine 知识（"哪些 URL 能下、哪些不能"）——v0.5.4 不该有
- 单一职责：PlatformRegistry 只管"是什么平台"，不管"能不能下"

**未来**：
- v0.5.5+ 写 `BilibiliAdapter : Engine` 时，Engine 内部调 [BilibiliUrl.classify] 看 type
  是否支持，UNSUPPORTED 返 `Engine.supports` false
- 这跟 v0.1 阶段 4 写 YouTube 时的模式一致（YouTubeUrl.classify + YtDlpEngine.supports）

### 决定 5：XBogusSigner / WbiSigner 接受 userAgent 作为参数

**v0.5.4 行为**：`XBogusSigner.sign(url, userAgent, timestamp)` / `WbiSigner.sign(query,
mixinKey, wts)` 都把 userAgent / mixinKey 作为显式参数。

**对比方案**：
- A) 把 userAgent / mixinKey 写死在 Signer 内部——单测不用传，但配置不灵活
- B) **显式参数**——调用方决定传什么，单测可以传 mock 值 ✅（选 B）

**选 B 的理由**：
- v0.5.5+ 集成 AppConfig.userAgent 时，Engine 内部 `XBogusSigner.sign(url,
  appConfig.userAgent, ts)` 直接拼
- 单测 `sign("https://...", "TestAgent", 1700000000L)` 显式传 mock UA，不需要 mock
  Config
- userAgent 不同会产不同签名（X-Bogus / WBI 都把 UA 算进 hash）——这正是 v0.5.5+
  测试要验证的

**风险**：v0.5.5+ 集成时如果 AppConfig 改 userAgent 字段名，Engine 调用方要跟着改——
但**单测层面不受影响**（仍显式传 mock UA）。

---

## 三、坑 & 决策

### 坑 1：合成 BV ID 字符数错（第一版）

**症状**：第一版 `classify shorts returns SHORTS` 写 `BV1short1` 当 BV ID，测试失败：
```
expected: SHORTS
but was: UNSUPPORTED
```

**根因**：`BV1short1` 是 BV + 8 字符 = 9 字符总长，B 站 BV ID 是 **BV + 10 字符** = 12 字符。
Regex `BV[A-Za-z0-9]{10}` 不匹配 8 字符的 `BV1short1`。

**修法**：合成 12 字符 BV ID（`BV1Ab2Cd3Ef4` = BV + 10 字符 = 12 字符总长）。

**教训**：B 站 BV ID 是 12 字符总长，**不**是 10 字符。BV 后面是 10 字符 base58 字符。

### 坑 2：WbiSigner 合成 img_url 没 `?` query 段

**症状**：第一版 `extractMixinKey` 测试抛 `IllegalArgumentException: filtered raw too
short: 0 chars (need ≥ 59)`。

**根因**：合成 img_url 写的是 `"https://i0.hdslb.com/bfs/wbi/abc.png"`（无 `?query=`），
`substringAfter("?", "")` 返空串，filter 后 0 字符，触发 require 检查。

**修法**：合成真 B 站 nav 接口 URL 格式 `"https://i0.hdslb.com/bfs/wbi/abc.png?0123..."`（30
字符 query）。两个 URL 拼一起 60 字符，过滤后 60 字符 ≥ 59 chars。

**教训**：B 站 nav 接口返回的 `img_url` / `sub_url` 格式是 `{base}?{query}`，query 段通常
30-40 字符。合成 test data 时**必须**保留 `?query=` 段。

### 坑 3：Kotlin `"X" * 32` 不合法

**症状**：WbiSignerTest 写 `signer.sign(query, "X" * 32, baseWts)` 编译报 "Unresolved
reference 'times' for operator '*'"。

**根因**：Kotlin String **不**有 `*` 操作符（不像 Python `"X" * 32`）。Kotlin 用
`"X".repeat(32)`。

**修法**：用 `"X".repeat(32)` 替 `"X" * 32`。

**教训**：从 Python 写 Kotlin 测试时常见——Python `*` / `+` 操作符 for String 跟 Kotlin
完全不同（Kotlin String 不可变，**没**有 `*` 跟 `+` 操作符 for String）。

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
| `M3u8ParserTest` | 12 | ✅ |
| **`BilibiliUrlTest`** | **10**（v0.5.4 新增：BV / AV / shorts / bangumi ep-ss-md / live / non-bili / canonical 2 例）| ✅ |
| **`WbiSignerTest`** | **6**（v0.5.4 新增：mixin_key 32 字符 / 确定性 / 太短抛 / MD5 32 字符 / 参数敏感 / 确定性）| ✅ |
| **`DouyinUrlTest`** | **9**（v0.5.4 新增：19 位 ID / 12 位 ID / short link / live / user / non-douyin / canonical 3 例）| ✅ |
| **`XBogusSignerTest`** | **5**（v0.5.4 新增：20 字符 / 参数敏感 / 确定性 / base64 字符集 / 不同 URL 不同输出）| ✅ |
| **`PlatformRegistryTest`** | **7**（v0.5.4 新增：B 站 video / B 站 bangumi / 抖音 main / 抖音 short / YouTube / generic / 空）| ✅ |
| **总计** | **258**（v0.5.3 221 + 37 新增）| ✅ |

### APK 验证

```
$ ./gradlew assembleDebug
BUILD SUCCESSFUL in 21s
52 actionable tasks: 19 executed, 33 up-to-date

APK: app/build/outputs/apk/debug/app-debug.apk  ~78 MB（v0.5.3 不变）
- platforms/ 目录 6 个新文件 + di/PlatformModule.kt
- 0 size 字节码（pure logic 类） + Hilt @Provides 字节码
```

### 静态检查

`./gradlew testDebugUnitTest --rerun` 全绿 258 例。

---

## 五、复盘清单

### 做了

- [x] **BilibiliUrl** —— B 站 URL 分类（6 种类型）+ `toCanonicalUrl` 归一化
- [x] **WbiSigner** —— 公开反编译的 WBI 签名算法（extractMixinKey + sign）
- [x] **DouyinUrl** —— 抖音 URL 分类（3 种类型）+ `toCanonicalUrl` 归一化
- [x] **XBogusSigner placeholder** —— 结构对齐（参数 / 输出格式 / 长度），算法 v0.5.5+ 实装
- [x] **PlatformRegistry** —— URL → Platform 分发（BILIBILI / DOUYIN / YOUTUBE / GENERIC）
- [x] **PlatformModule** —— Hilt 装配（PlatformRegistry + BilibiliUrl + DouyinUrl + 自动 @Inject 签名算法）
- [x] **37 例单测全绿**（10 + 6 + 9 + 5 + 7）
- [x] **versionCode 11→12** + versionName "0.5.3"→"0.5.4"
- [x] **258/258 单测全绿**（v0.5.3 221 + 37）
- [x] **`assembleDebug` 通过**
- [x] **阶段 14 复盘文档**（本文档）

### 没做（v0.5.5+ 单独 PR）

- [ ] **真 X-Bogus 算法实装**（公开反编译的完整版本，RC4 + MD5 + 复杂字节操作 + 编码）—— v0.5.5+ 实装 + 真抖音 web 响应作为 test vector
- [ ] **B 站 / 抖音 API 客户端**（OkHttp + Retrofit 调 web API，需要 WBI / X-Bogus 签名支持）
- [ ] **Engine 集成**（`PlatformAdapter : Engine` interface，调度 B 站 / 抖音 adapter）
- [ ] **UI 集成**（`PromptOptionsDialog` 加 B 站清晰度选择 + 抖音合集）
- [ ] **m3u8 v7+ HLS encryption** + **多 variant 选择 UI**（v0.5.3 留的欠账）
- [ ] **`WebViewHeadlessSniffer` 自身单测**（v0.5.0 留的欠账，需要 Robolectric）
- [ ] **ANR 风险测试**（shouldInterceptRequest 1-3s 阻塞 Main 线程）
- [ ] **`DefaultWebViewFactory` 0 size / GONE / JS enabled 配置的 instrumented test**

### 文档同步

- [x] [PHASES.md](../PHASES.md) — 阶段 14 加
- [x] [CHANGELOG.md](../CHANGELOG.md) — + v0.5.4-android 段
- [x] [REUSE-MAP.md](../REUSE-MAP.md) — 同步 v0.5.4 platforms/ 映射
- [x] [README.md](../../README.md) — 阶段 14 标完成
- [x] [phase-14.md](phase-14.md) — 本文档
