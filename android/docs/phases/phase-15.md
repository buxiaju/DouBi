# 阶段 15 复盘：真 X-Bogus 算法 part 1（✅ 完成 → v0.5.5-android）

> **最终状态**：阶段 15 收官。v0.5.4 阶段 14 留的「XBogusSigner 是 placeholder」欠账部分落地——**抽 [RC4] cipher + [CustomBase64] utility 升级 XBogusSigner 走 RC4 + a_bogus 字母表编码**。269/269 单测全绿（v0.5.4 258 + 11 新增），`assembleDebug` 通过。
> **v0.5.4-android tag 已发**（阶段 14 收官），本阶段成果属 v0.5.5-android tag。
>
> ⚠️ **v0.5.5 是 part 1**——RC4 + 自定义 base64 是公开反编译的 well-defined 算法，已实装；但 `get_chaos(params, ua)`（要执行抖音 webmssdk.js）仍是 stub。v0.5.6+ 实装真 get_chaos 才能 byte-for-byte 真 a_bogus 输出。

## 一句话总结

本阶段做了 **3 类事情**（按 commit 顺序）：

1. **[RC4] cipher utility** —— 公开反编译 RC4 流密码，KSA + PRGA 标准实现 + 5 例单测（含公开 RC4 test vector `Key`+`Plaintext` → `BBF316E8D940AF0AD3`）
2. **[CustomBase64] utility** —— 抖音 a_bogus 字母表 `Dkdpgh2ZmsQB80/MfvV36XI1R45-WUAlEixNLwoqYTOPuzKFjJnry79HbGcaStCe` 编码 + 6 例单测
3. **[XBogusSigner] 升级** —— 从 v0.5.4 的 SHA-256 简化 placeholder 升级到 **RC4 + CustomBase64 路径**——输出从 20 字符变 44 字符（SHA-256 32 字节 → RC4 → 44 字符 base64）

**没做**（v0.5.6+ 单独 PR）：
- **真 get_chaos 实装**——执行抖音 webmssdk.js 拿 ~110 字节大数组（v0.5.6+ JS 引擎集成 或 反编译算法后手写）
- B 站 / 抖音 API 客户端（v0.5.5+ 已有签名算法，可调 API）
- Engine 集成 / UI 集成
- m3u8 v7+ HLS encryption / 多 variant 选择 UI
- WebViewHeadlessSniffer 自身单测（Robolectric）
- ANR 风险测试

---

## 一、改了什么

### 新增文件

| 路径 | 作用 |
|---|---|
| `app/src/main/java/com/doubi/android/core/util/RC4.kt` | RC4 流密码（KSA + PRGA），1:1 对拍桌面版 Python `arc4` |
| `app/src/main/java/com/doubi/android/core/util/CustomBase64.kt` | 自定义 Base64 编码（64 字符字母表参数化） |
| `app/src/test/java/com/doubi/android/core/util/RC4Test.kt` | 5 例单测（含公开 RC4 test vector） |
| `app/src/test/java/com/doubi/android/core/util/CustomBase64Test.kt` | 6 例单测（含 standard base64 `TWFu` 对照） |

### 修改文件

| 路径 | 变化 |
|---|---|
| `app/src/main/java/com/doubi/android/core/platform/douyin/XBogusSigner.kt` | 升级——v0.5.4 SHA-256 简化 placeholder → v0.5.5 RC4 + a_bogus 字母表编码；`SIGNATURE_LENGTH` 20 → 44 |
| `app/src/test/java/com/doubi/android/core/platform/douyin/XBogusSignerTest.kt` | 更新 5 例测试（44 字符 / a_bogus 字母表字符集） |
| `app/build.gradle.kts` | versionCode 12→13；versionName "0.5.4"→"0.5.5" |
| `app/src/test/java/com/doubi/android/ExampleUnitTest.kt` | 注释加「阶段 15 升到 v0.5.5」一行 |
| `docs/phases/phase-15.md` | 本文档 |

### 桌面版 → Android 版

```
桌面版 `src/doubi/platforms/douyin/xbogus.py`（a_bogus / X-Bogus 算法实现）
  ─────────────────────────────────────────────────
  → 阶段 14 v0.5.4：XBogusSigner 落地（**SHA-256 placeholder**）
  → 阶段 15 v0.5.5：
    ├─ core/util/RC4.kt —— RC4 cipher 完整实装
    ├─ core/util/CustomBase64.kt —— 自定义 base64 完整实装
    └─ XBogusSigner 重构 —— 用 RC4 + CustomBase64 走真算法路径（**get_chaos 仍 stub**）
```

公开反编译（参考 https://blog.csdn.net/weixin_48673014 / https://blog.csdn.net/weixin_46084750 ）：
- 抖音 a_bogus = `RC4(get_chaos, key=[131]) + CustomBase64(s1 + s2, a_bogus_alphabet)`
- v0.5.5 实装 `RC4` + `CustomBase64` 两部分
- v0.5.6+ 实装 `get_chaos(params, ua)`（需要执行抖音 webmssdk.js 拿 ~110 字节大数组）

---

## 二、核心设计决定

### 决定 1：v0.5.5 只实装 RC4 + CustomBase64 两部分，get_chaos 仍 stub

**问题**：抖音 a_bogus 算法 3 个核心步骤：
1. `get_chaos(params, ua)` —— 调用抖音 webmssdk.js 拿两个 byte 字符串（**s1, s2**）
2. `make_str_chaos(s2)` —— RC4 with key=[131] 加密 s2
3. `chaos2result(s1 + s2)` —— 自定义 base64 编码

**v0.5.5 方案对比**：
- A) 3 步都实装——需要 Android 端 JS 引擎（Rhino / Nashorn）+ 加载 webmssdk.js —— scope 大
- B) **只实装 RC4 + CustomBase64**（well-defined 算法，公开反编译有 byte-for-byte 验证）—— ✅
- C) v0.5.4 placeholder 直接升级——已经有了，再升没意义

**选 B 的理由**：
- RC4 + CustomBase64 是 **well-defined 算法**——公开反编译 + 公开 RC4 test vector 能 byte-for-byte 验证
- `get_chaos` 需要执行抖音 webmssdk.js（~3MB 混淆 JS）——需要 Android 端 JS 引擎集成或反编译算法后手写
- 渐进式：v0.5.5 升级到完整算法路径（RC4 + base64），v0.5.6+ 实装 get_chaos 即可
- v0.5.5 输出**结构对齐**真 a_bogus（44 字符 vs 真 a_bogus 168-172 字符，因为 stub chaos 是 SHA-256 32 字节 vs 真 chaos ~110 字节）

**风险**：
- v0.5.5 stub chaos 走抖音 web API 仍会被 -352 风控
- v0.5.5 输出长度 44 字符 ≠ 真 a_bogus 168-172 字符——真 get_chaos 实装后输出会变

### 决定 2：抽 RC4 + CustomBase64 为独立 utility 类（**不**塞进 XBogusSigner）

**对比方案**：
- A) 把 RC4 逻辑塞进 XBogusSigner 私有方法——单测覆盖难（XBogusSigner 还要 stub chaos）
- B) **抽独立 utility** + 公开 testable 函数 ✅

**选 B 的理由**：
- RC4 是通用算法（不只是 a_bogus 用），未来其它地方也可能用——v0.5.5+ 抽独立 utility 复用
- CustomBase64 是通用工具（任何用 a_bogus 字母表的场景都能用）
- 单测用公开 test vector 验证（RC4 `Key`+`Plaintext` → `BBF316E8D940AF0AD3`；standard base64 `Man` → `TWFu` 对照）
- v0.5.6+ 替换 `get_chaos` 时不影响 RC4 + CustomBase64

**风险**：
- 多 1-2 个文件——可接受（utility 类的可读性 > 单文件聚合）
- `core/util/` 目录新建——之前没用过，但 utility 类归属 `core/` 合理

### 决定 3：a_bogus 字母表 + RC4 key 写成 `companion object` 常量（**不** hardcode 散落各处）

**v0.5.5 做法**：
```kotlin
companion object {
    private val RC4_KEY: ByteArray = byteArrayOf(131.toByte())
    const val A_BOGUS_ALPHABET = "Dkdpgh2ZmsQB80/MfvV36XI1R45-WUAlEixNLwoqYTOPuzKFjJnry79HbGcaStCe"
    const val SIGNATURE_LENGTH = 44
}
```

**对比方案**：
- A) 字母表跟 key 写在函数体内 / hardcode——散落难维护
- B) **`companion object` 集中** + 公开 const（`A_BOGUS_ALPHABET` / `SIGNATURE_LENGTH`）——✅

**选 B 的理由**：
- 字母表 + key 是公开反编译固定值——写一起方便单测对照 + 未来改字母表只改一处
- 字母表 public 暴露（`const val`）——CustomBase64 单测可以直接 import 用
- SIGNATURE_LENGTH public 暴露——单测断言输出长度可读

**风险**：
- 公开 const 是 bytecode 常量，改了要重 build——可接受

### 决定 4：v0.5.5 stub chaos 用 SHA-256（**不**用固定字符串 / 随机数）

**v0.5.4 placeholder**：SHA-256(UA + URL + timestamp) → 20 字符 base64
**v0.5.5 stub chaos**：SHA-256(UA + URL + timestamp) → 32 字节 → RC4 → 44 字符 a_bogus base64

**为什么还是 SHA-256**：
- 输出**确定性**（同输入 → 同输出）——单测能写断言
- 32 字节长度——是 SHA-256 天然输出，不需要 padding
- 跟 v0.5.4 placeholder 一样的输入**参数**——单测迁移成本 0
- v0.5.6+ 实装真 get_chaos 时只替换 `generateStubChaos` 函数实现，**不**改其它部分

**风险**：
- v0.5.5 stub chaos ≠ 真 chaos——真 a_bogus 算法 168-172 字符输出 vs v0.5.5 44 字符输出
- v0.5.5 stub 走抖音 web API 仍会被 -352——只**不能**用，但**结构验证**有效

### 决定 5：v0.5.5 不做"标准 base64 `Man` → `TWFu` test" 同款字节对照（用 a_bogus 字母表）

**对比方案**：
- A) 用 standard base64 字母表验 `Man` → `TWFu`（公开标准 test vector）—— 验证 CustomBase64 实现正确
- B) 用 a_bogus 字母表验 `[0x41,0x42,0x43]` → `"f6sp"`（手算）—— 验证 a_bogus 路径正确

**v0.5.5 选 A + B 都有**：
- `three bytes produces 4 chars` 用 **a_bogus 字母表**验"f6sp"——验 a_bogus 路径
- `a_bogus alphabet encodes standard test vector` 额外用 **standard 字母表**验 `Man` → `TWFu`——验 CustomBase64 实现正确（标准 base64 字母表 A-Z a-z 0-9 +/ 跟 a_bogus 顺序不同）

**理由**：
- CustomBase64 字母表是参数化的——验 standard 字母表 + 验 a_bogus 字母表 = 验证实现 + 验证应用

---

## 三、坑 & 决策

### 坑 1：`byteArrayOf(131)` 不合法（Int vs Byte）

**症状**：第一版 RC4Test 写 `byteArrayOf(131)` 编译报 "Argument type mismatch: actual type is 'kotlin.Int', but 'kotlin.Byte' was expected."

**根因**：Kotlin 的 `byteArrayOf` 只接受 `Byte` 参数。131 是 Int，**不**能直接转 Byte（Kotlin 没有 implicit conversion）。

**修法**：`byteArrayOf(131.toByte())` 显式转 Byte。

**教训**：Kotlin `byteArrayOf` 是 typed function，不是 generic。任何 `Int` 进 `byteArrayOf` 都要先 `.toByte()`。

### 坑 2：`(Int xor Int) → Int`，赋给 `output[i]: Byte` 类型错

**症状**：第一版 RC4.encrypt 写 `output[i] = (data[i].toInt() and 0xFF) xor keystreamByte` 编译报 "Argument type mismatch: actual type is 'kotlin.Int', but 'kotlin.Byte' was expected."

**根因**：`Int xor Int` 结果是 `Int`，不是 `Byte`。

**修法**：`.toByte()` 显式转：`output[i] = ((data[i].toInt() and 0xFF) xor keystreamByte).toByte()`。

**教训**：bitwise operation（`xor` / `and` / `or`）结果总是 `Int`。赋给 `Byte` 字段要 `.toByte()`。

### 坑 3：手算 bit segment 算错（"p2dk" 应该是 "f6sp"）

**症状**：第一版 CustomBase64Test "three bytes produces 4 chars" 期望 `"p2dk"`，但实际输出 `"f6sp"`。

**根因**：手算 `[0x41, 0x42, 0x43]` → 4 个 6-bit 段：
- 错算成 010000(16), 000101(5), 000010(2), 000011(3)
- 对 a_bogusAlphabet 索引 → "Qhdk" (16='Q', 5='h', 2='d', 3='k')
- 实际应该是 010000(16), 010100(20), 001001(9), 000011(3)
- 对 a_bogusAlphabet 索引 → "f6sp" (16='f', 20='6', 9='s', 3='p')

错在哪：手算时把 `0x42 = 01000010` 拆成 `01 000010` 算第二段，错位了——应该是 `010100`，因为 `<< 8` 移位后第二段从 bit 14 开始：
- byte 0 (0x41) → bits 16-23 = `01000001` → 段 0 (bits 18-23) = `010000` (16) ✓ 段 1 (bits 12-17) = `000101` (5) ← **错**
- 实际 0x41 << 16 = 0x410000，bits 12-17 = `000101`... wait

让我重算：
0x414243 = 0100 0001 0100 0010 0100 0011

bits 18-23: `01 0000` = 010000 = 16
bits 12-17: `01 0100` = 010100 = 20
bits 6-11:  `00 1001` = 001001 = 9
bits 0-5:   `00 0011` = 000011 = 3

对 a_bogusAlphabet = "Dkdpgh2ZmsQB80/MfvV36XI1R45-WUAlEixNLwoqYTOPuzKFjJnry79HbGcaStCe":
- 16 = 'f'
- 20 = '6'
- 9 = 's'
- 3 = 'p'
→ "f6sp" ✓

**修法**：重新算 bit segment 找对索引。

**教训**：手算 bit segment 时**用计算器验一遍**（16 进制 → 2 进制 → 6-bit group）——错 1 bit 整个索引错。

### 坑 4：test 函数名带括号 `()` 编译错

**症状**：第一版 `fun `single byte produces 4 chars (no padding)`()` 编译报 "Expecting '('"。

**根因**：Kotlin function name 用 backtick `\`...\`` 包时，里面的 `(` 是 function 参数列表的左括号——`name()` 实际上 `name` 是函数名（空参数）——跟测试断言的 "(no padding)" 文本混淆。

**修法**：`fun `single byte produces 4 chars no padding`() {`（去掉 `(no padding)` 括号）。

**教训**：test 函数名用 backtick 包时**不要**带括号——跟 Kotlin function call syntax 冲突。

### 坑 5：Truth `isIn(String)` 不存在

**症状**：第一版 `assertThat(c.toString()).isIn(aBogusAlphabet)` 编译报 "None of the following candidates is applicable"。

**根因**：Truth `Subject.isIn(...)` 只接受 `Iterable<T>`（如 `List<T>` / array），不接受 `String`（虽然 `Char` 是 `Iterable<Char>`，但 `String` 不是 `Iterable<Char>`）。

**修法**：`assertThat(c in aBogusAlphabet).isTrue()`（用 Kotlin `in` operator 代替）。

**教训**：Truth 跟 Kotlin collection API 不完全对齐——`String.contains(Char)` 跟 `Subject.isIn` 不通用。

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
| `BilibiliUrlTest` | 10 | ✅ |
| `WbiSignerTest` | 6 | ✅ |
| `DouyinUrlTest` | 9 | ✅ |
| `XBogusSignerTest` | 5 | ✅（v0.5.5 更新签名长度 20→44） |
| `PlatformRegistryTest` | 7 | ✅ |
| **`RC4Test`** | **5**（v0.5.5 新增：空 / 单字节 / RFC test vector / a_bogus key / roundtrip）| ✅ |
| **`CustomBase64Test`** | **6**（v0.5.5 新增：空 / 1 byte / 3 bytes "f6sp" / a_bogus alphabet / standard `TWFu` / 确定性 / 64 字符检查）| ✅ |
| **总计** | **269**（v0.5.4 258 + 11 新增）| ✅ |

### APK 验证

```
$ ./gradlew assembleDebug
BUILD SUCCESSFUL in 18s
52 actionable tasks: 7 executed, 45 up-to-date

APK: app/build/outputs/apk/debug/app-debug.apk  ~78 MB（v0.5.4 不变）
- core/util/RC4.kt + core/util/CustomBase64.kt 两个新文件
- XBogusSigner 重构 inline，字节码大小基本不变
- 0 新依赖
```

### 静态检查

`./gradlew testDebugUnitTest --rerun` 全绿 269 例。

---

## 五、复盘清单

### 做了

- [x] **RC4 cipher utility** —— 公开 RC4 KSA + PRGA 算法 + 5 例单测（含公开 test vector）
- [x] **CustomBase64 utility** —— 抖音 a_bogus 字母表编码 + 6 例单测（含 standard base64 对照）
- [x] **XBogusSigner 升级** —— v0.5.4 SHA-256 placeholder → v0.5.5 RC4 + a_bogus 字母表编码
- [x] **XBogusSignerTest 更新** —— 5 例测试从 20 字符适配到 44 字符 + a_bogus 字母表字符集
- [x] **versionCode 12→13** + versionName "0.5.4"→"0.5.5"
- [x] **269/269 单测全绿**
- [x] **`assembleDebug` 通过**
- [x] **阶段 15 复盘文档**（本文档）

### 没做（v0.5.6+ 单独 PR）

- [ ] **真 get_chaos 实装**（执行抖音 webmssdk.js 拿 ~110 字节大数组）—— Android 端 JS 引擎集成（Rhino / Nashorn）或反编译算法后手写
- [ ] **B 站 / 抖音 API 客户端**（OkHttp + Retrofit + WBI / X-Bogus 签名支持）—— v0.5.5+ 签名算法已就绪
- [ ] **Engine 集成**（`PlatformAdapter : Engine` interface）
- [ ] **UI 集成**（`PromptOptionsDialog` 清晰度选择 + 合集）
- [ ] m3u8 v7+ HLS encryption / 多 variant 选择 UI（v0.5.3 留的欠账）
- [ ] `WebViewHeadlessSniffer` 自身单测（Robolectric）
- [ ] ANR 风险测试
- [ ] `DefaultWebViewFactory` 0 size / GONE / JS enabled 配置的 instrumented test

### 文档同步

- [x] [PHASES.md](../PHASES.md) — 阶段 15 加
- [x] [CHANGELOG.md](../CHANGELOG.md) — + v0.5.5-android 段
- [x] [REUSE-MAP.md](../REUSE-MAP.md) — 同步 v0.5.5 RC4 + CustomBase64 utility
- [x] [README.md](../../README.md) — 阶段 15 标完成
- [x] [phase-15.md](phase-15.md) — 本文档
