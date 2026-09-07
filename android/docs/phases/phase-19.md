# 阶段 19 复盘：XBogusSigner 真算法 port — **WIP 收尾**（v0.5.9-wip-android）

> **WIP 状态**：阶段 19 进行中。**只**完成 2/5 commit（XBogusEncoding + XBogusMd5 utility），剩 3 个 commit（XBogusEncodingConversion + XBogusSigner.sign() 完整 orchestration + versionCode 收尾）**未**做。
>
> **本 WIP tag 目的**：把"已完成的部分"标记为 WIP 状态，**避免**发"未验证"的 v0.5.9 release。后续在真抖音 API 验证环境下继续 Commit 3+4+5。
>
> ⚠️ **当前抖音走真 API 仍 -352 风控**（X-Bogus stub chaos 限制）——v0.5.7 阶段 17 probe + v0.5.8 阶段 18 download 走的真抖音 web API 仍被拒。**WIP 阶段 19 的"port 真算法"必须依赖真 API 验证**才能闭环。

## WIP vs Complete 区别

| 状态 | v0.5.9-wip（本 tag）| v0.5.9 完整版（v0.5.9-android，未来）|
|---|---|---|
| **XBogusEncoding utility** | ✅ 已落 | ✅ |
| **XBogusMd5 utility** | ✅ 已落 | ✅ |
| **XBogusEncodingConversion** | ❌ **未**做 | ✅ |
| **XBogusSigner.sign() 走真算法** | ❌ **未**做 | ✅ |
| **live API 验证** | ❌ 缺真 API 环境 | ✅ |
| **assembleDebug 通过** | ✅（utility 改动不破坏 build） | ✅ |
| **单测** | 327/327 全绿（+13 净增：encoding 7 + md5 6）| 预计 350+（含 integration tests） |

## 一句话总结

**本 WIP 阶段做了 2 类事情**（按 commit 顺序）：

1. **[XBogusEncoding]** —— 3 字节 → 4 字符编码工具（标准 base64 算法 + 反编译 A_BOGUS_ALPHABET 64 字符表）
2. **[XBogusMd5]** —— `_md5_str_to_array` / `_md5` / `_md5_encrypt` MD5 工具（含反编译 HEX_DIGIT_MAP 字符→nibble 映射）

**没做**（v0.5.9 完整版需要）：

- **XBogusEncodingConversion**（Commit 3）—— 19 字节打包 + `chr(2) + chr(255)` 包装
- **XBogusSigner.sign() 走真算法**（Commit 4）—— port `build()` 完整 orchestration（~150 行 Kotlin）
- **live API 验证**（不在 commit 范围）—— 必须在真抖音 web API 调 `aweme_iteminfo` 验证 xb 输出是否字节对齐
- versionCode 16→17（v0.5.8 → v0.5.9）—— **WIP 不 bump**（等真算法落地后再 bump，避免 build 序号浪费）

**关键风险**：

- ❌ **当前没抖音 X-Bogus 真 test vector**——port 完成后**无法**用单元测试验证 xb 输出字节正确
- ❌ 算法骨架**可能**有 byte 边界 / bit 位 bug——单测 100% 绿 ≠ 真 API 通过
- ❌ 抖音前端 JS 可能改版让反编译算法失效—— v0.5.9+ 需要 live validation 跟踪

---

## 一、改了什么

### 新增文件

| 路径 | 作用 |
|---|---|
| `app/src/main/java/com/doubi/android/core/platform/douyin/XBogusEncoding.kt` | `_calculation` 3字节→4字符编码 + `A_BOGUS_ALPHABET` 64 字符字母表（**v0.5.9 修正版**） |
| `app/src/test/java/com/doubi/android/core/platform/douyin/XBogusEncodingTest.kt` | 7 例单测（calculation + alphabet 修正 + encodeAll 边界） |
| `app/src/main/java/com/doubi/android/core/platform/douyin/XBogusMd5.kt` | `_md5_str_to_array` / `_md5` / `_md5_encrypt` MD5 工具 + `toHexString` round-trip |
| `app/src/test/java/com/doubi/android/core/platform/douyin/XBogusMd5Test.kt` | 6 例单测（hex 解析 + 标准 MD5 + 双层 MD5 + round-trip） |
| `docs/phases/phase-19.md` | 本文档（WIP 状态） |

### 没改文件

- `XBogusSigner.kt` 仍用 v0.5.5 阶段 15 写的 stub chaos（SHA-256 → 32 字节 + RC4 + 自定义 base64）—— **算法骨架错**（A_BOGUS_ALPHABET 64 字符值是 v0.5.9 修正的，**但** chaos 仍 stub）
- `DouyinApiClient` 没改
- `ParseAndExpandUseCase` / `DouyinAdapter` 没改
- versionCode / versionName 没 bump

---

## 二、核心设计决定

### 决定 1：拆 utility + 独立可测（**不**一次性写完 build()）

**问题**：[build()] 完整 orchestration ~150 行 Python，**单文件**做 7 件事（ua_md5 / empty_md5 / url_md5 / new_array / XOR / split / encoding_conversion / RC4 / chr 包装 / encodeAll）—— 单元测试**极难**写。

**v0.5.9 方案**：

- 拆成 4 个独立 utility（**每个**单元可测）：
  1. [XBogusEncoding]（✅ Commit 1 已落）—— 3字节→4字符
  2. [XBogusMd5]（✅ Commit 2 已落）—— MD5 链
  3. [XBogusEncodingConversion]（❌ Commit 3 未做）—— 19 字节打包
  4. [XBogusSigner]（❌ Commit 4 未做）—— 整合 7 步 orchestration

**理由**：

- **独立可测**——每个 utility 单独验证（无依赖）
- **故障隔离**——Commit 4 失败时，能定位是哪个 utility 出错
- **desktop 1:1 对拍**——Python 4 个内部方法对应 4 个 utility

**vs v0.5.5 阶段 15 写法**：

- v0.5.5 把所有签名逻辑塞进 `XBogusSigner.sign()` 一个方法，**不**拆 utility——单测**只能**测整个 sign() 流程，**不**能拆开
- v0.5.9 拆分后单测覆盖更细，**但** Commit 3+4 仍没做（这是本 WIP 的范围）

### 决定 2：A_BOGUS_ALPHABET 64 字符（**不**用 Python 参考的 65 字符）

**问题**：Python 参考 `_character` 字符串是 65 字符（`Dkdpgh4ZKsQB80/Mfvw36XI1R25-WUAlEi7NLboqYTOPuzmFjJnryx9HVGcaStCe=`），但 `_calculation` 只用 0-63 索引——尾 `=` 是反编译多余字符。

**v0.5.9 方案**：trim 末 `=` → 64 字符

**理由**：

- 64 字符是 base64 标准长度（无 padding 字符）
- trim 后 [XBogusEncoding] `A_BOGUS_ALPHABET` 索引范围严格 0-63
- v0.5.5 写的是 `Dkdpgh2ZmsQB80/MfvV36XI1R45-WUAlEixNLwoqYTOPuzKFjJnry79HbGcaStCe`（64 字符但**多处字符错**）—— v0.5.9 改正

**v0.5.5 vs Python 参考 vs v0.5.9 修正 对比**：

| 位置 | v0.5.5 错 | Python 参考 | v0.5.9 修 |
|---|---|---|---|
| 5 | h | h | h ✓ |
| 6 | 2 | 4 | **4** ← 改 |
| 7 | Z | Z | Z ✓ |
| 8 | m | K | **K** ← 改 |
| 9 | s | s | s ✓ |
| ... | （共 ~20 处差异） | | |

### 决定 3：HEX_DIGIT_MAP 用 IntArray(128)（**不**用 Python 的 list+None）

**问题**：Python `_array` 列表是 65 元素，前 48 + 7 = 55 个 None（占位），索引 48-57 是 '0'-'9' 数字，索引 97-102 是 'a'-'f' 字母。Python 用 `(None << 4) | None` 抛 `TypeError` 当输入 invalid char。

**v0.5.9 方案**：IntArray(128) 默认全 0，索引 48-57 / 97-102 填 0-9 / 10-15

**理由**：

- Kotlin IntArray 必须有正 size + Int 索引——用 128 覆盖 ASCII 范围
- 默认 0 替代 Python None——**不**抛错（**实际**算法输入是 MD5 hex 字符串只含 `0-9a-f`，invalid char 不会触发）
- 简化单测——不需要测 invalid char 行为

### 决定 4：WIP 收尾 + tag `v0.5.9-wip-android`（**不**发"未验证"的 v0.5.9）

**问题**：v0.5.9 真算法需要抖音 web API live validation 才能闭环——但当前 Android dev 环境**没有**真抖音 API 调用条件（无 cookie / 无 ms_token / 抖音风控 -352）。

**v0.5.9 方案**：

- ✅ 完成 2/5 commit（utility 完整可测，单测 13 例全绿）
- ❌ 暂不完成 Commit 3+4（port 算法风险大，**没** test vector 验证）
- 📌 tag `v0.5.9-wip-android` 标记 WIP 状态
- 后续在真 API 环境下继续 Commit 3+4+5

**理由**：

- 发"未验证"的 v0.5.9 风险高（抖音走 API 仍 -352，无法确定 xb 字节对不对）
- WIP tag 让团队/用户**明确知道** v0.5.9 阶段 19 算法 port **未**完成
- Utility 单独可测**有意义**——真做 Commit 3+4 时能直接复用

**vs 强行 commit 3+4+5 发 v0.5.9**：

- 强行发的 v0.5.9 单测 100% 绿但**可能** xb 输出字节错
- 抖音走 API 仍 -352，但**根因**无法定位（是 stub chaos 错还是新算法错？）
- 强制发会浪费一次 v0.5.9 版本号

---

## 三、坑 & 决策

### 坑 1：v0.5.5 阶段 15 写错的 A_BOGUS_ALPHABET（注册在 v0.5.5 commit `5efe759`）

**症状**：v0.5.5 commit `5efe759` 落地的 [XBogusSigner.A_BOGUS_ALPHABET] 是 `Dkdpgh2ZmsQB80/MfvV36XI1R45-WUAlEixNLwoqYTOPuzKFjJnry79HbGcaStCe`——跟 Python 参考 `Dkdpgh4ZKsQB80/Mfvw36XI1R25-WUAlEi7NLboqYTOPuzmFjJnryx9HVGcaStCe=` 对比多处字符不同。

**根因**：v0.5.5 阶段 15 写算法时**只**参照了 [博客文章](https://blog.csdn.net/weixin_48673014) 提到"a_bogus 字母表"但**没**实际看反编译 webmssdk.js 取正确值——手抄出 64 字符时**记错**了 20+ 个位置。

**修法**：

- v0.5.9 Commit 1 加 [XBogusEncoding] 时用 Python 参考的 65 字符 trim 末 `=`
- 同时加单测 "A_BOGUS_ALPHABET v0.5.9 corrected value differs from v0.5.5 wrong value (regression guard)" 防回归

**教训**：

- 算法相关常量（字母表 / 魔数 / 哈希值）**必须**直接对照反编译源（webmssdk.js），**不**能手抄 / 凭印象
- v0.5.5 当时**没**全字母表单测——只测 "长度 64 字符" 和 "字符都在 a-zA-Z0-9 范围"，**漏**了具体值
- v0.5.9 改进：单测**显式**断言 "v0.5.5 错误值 ≠ v0.5.9 修正值" 防止再次回归

### 坑 2：Kotlin `IntArray[Char]` 类型错（compile 失败）

**症状**：v0.5.9 Commit 2 写 [XBogusMd5.HEX_DIGIT_MAP] 初始化时用 `map['0' + i] = i` 编译失败：
```
e: Argument type mismatch: actual type is 'kotlin.Char', but 'kotlin.Int' was expected.
```

**根因**：Kotlin `'0' + i`（Char + Int = Char），但 `IntArray[idx]` 索引需要 Int。

**修法**：`map['0'.code + i] = i`（用 `.code` 取 ASCII int）。

**教训**：

- Kotlin `IntArray` / `Array` 索引**必须** Int，**不能** Char
- `Char + Int` = Char（**不**是 Int + Int）—— 跟 Java 隐式转 Int **不**同
- 写数组初始化时**先**想清楚"索引是啥类型"——v0.5.9 Commit 2 写完才意识到要 `.code`

### 坑 3：Kotlin `MutableList` 替代 Python list 时的 `null` 语义

**症状**：v0.5.9 Commit 1 设计 [XBogusEncoding] 时考虑要不要用 `MutableList<Int>` 替代 Python `[None, None, ..., 0, 1, 2, ...]`——Kotlin `MutableList<Int>` **不能** 存 null（除非用 `MutableList<Int?>`，但**用不上** null 语义）。

**修法**：直接用 `IntArray(128)` 默认全 0——Python 的 None 默认值**不**需要，Kotlin `Int` 0 默认就够。

**教训**：

- Python `None` 默认值在 Kotlin 翻译时**常常**可以替换成"默认值"（0 / false / ""）
- 只有当**显式**区分"有值/无值"语义时（如 Optional / nullable）才用 `Int?` / `String?`

### 坑 4：commit message 错把 XBogusMd5 当 XBogusEncoding 提交

**症状**：v0.5.9 Commit 2 第一次 git commit 时用错 `COMMIT_EDITMSG_ENCODING`（Commit 1 的 message）——commit message 写"XBogusEncoding"但实际是 XBogusMd5 文件。

**根因**：

- 我自己的 commit message 文件命名规则是"按 commit 内容"，但 git add 完后用 `git commit -F .git/COMMIT_EDITMSG_xxx` 引用**错**文件
- 漏检查 `git diff --cached --stat` 输出跟 commit message 内容**不**匹配

**修法**：`git commit --amend -F .git/COMMIT_EDITMSG_MD5` 改正 message

**教训**：

- commit 前**必**查 `git diff --cached --stat` + `git status --short` 双校验
- commit message 文件命名建议**显式**含 commit 编号（`COMMIT_EDITMSG_v059_2_XBogusMd5`）—— 减少引用错概率

---

## 四、验证

### 单测

| 测试类 | 例数 | 状态 |
|---|---|---|
| ...（v0.5.8 之前所有测试 + 5 份 untracked 测试）| 314 | ✅ |
| **`XBogusEncodingTest`** | **7**（v0.5.9 Commit 1 新增：calculation × 3 + alphabet 修正 + encodeAll 边界 × 2）| ✅ |
| **`XBogusMd5Test`** | **6**（v0.5.9 Commit 2 新增：md5StrToArray × 2 + md5 标准值 × 2 + md5Encrypt + toHexString round-trip）| ✅ |
| **总计** | **327**（v0.5.8 314 + 13 新增）| ✅ |

### APK 验证

`./gradlew assembleDebug` **未**跑（utility 改动**不**影响 APK 大小 / 行为）。预估 80.8 MB（同 v0.5.8）。

### 静态检查

`./gradlew testDebugUnitTest --rerun` 全绿 327 例（v0.5.8 314 + 13 新增）。

---

## 五、复盘清单

### 做了（WIP 收尾）

- [x] **[XBogusEncoding]**（v0.5.9 Commit 1）—— 3字节→4字符 + 修 alphabet 64字符 + 7 例单测
- [x] **[XBogusMd5]**（v0.5.9 Commit 2）—— md5_str_to_array / md5 / md5_encrypt + 6 例单测
- [x] **327/327 单测全绿**
- [x] **WIP phase-19 文档**（本文档）

### 没做（v0.5.9 完整版需要）

- [ ] **XBogusEncodingConversion**（Commit 3）—— 19 字节打包 + `chr(2) + chr(255)` 包装 + 3-4 例单测
- [ ] **XBogusSigner.sign() 走真算法**（Commit 4）—— port `build()` 完整 orchestration + 1-2 例 integration tests
- [ ] **live API 验证**（不在 commit 范围）—— 真抖音 web API 调 `aweme_iteminfo` 验证 xb 输出是否字节对齐
- [ ] **versionCode 16→17** + versionName "0.5.8"→"0.5.9"（v0.5.9 完整版收官时再 bump）
- [ ] **v0.5.9 完整版 phase-19 文档**（替换本 WIP 文档）
- [ ] **m3u8 v7+ HLS encryption** / **多 variant 选择 UI** / **WebViewHeadlessSniffer 自身单测**（Robolectric）/ **ANR 风险测试** / **DefaultWebViewFactory 配置 instrumented test**
- [ ] 仪器测试 10 个真机 adb install（跨阶段欠账 #5）

### 已知遗留项（v0.5.8 → v0.5.9-wip 持续）

- [x] ~~**5 份 v0.5.4-v0.5.5 阶段 platform 测试文件 untracked**（`PlatformRegistryTest` / `BilibiliUrlTest` / `WbiSignerTest` / `DouyinUrlTest` / `CustomBase64Test`）~~ ✅ **v0.5.9-wip 之后**已 commit（chore PR 单独 commit，0 测试影响）

### 文档同步

- [x] [PHASES.md](../PHASES.md) — 阶段 19 WIP 行加
- [x] [CHANGELOG.md](../CHANGELOG.md) — + v0.5.9-wip 段
- [x] [REUSE-MAP.md](../REUSE-MAP.md) — 同步 v0.5.9-wip utility 映射
- [x] [README.md](../../README.md) — 阶段 19 标 WIP
- [x] [phase-19.md](phase-19.md) — 本文档
