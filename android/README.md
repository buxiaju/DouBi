# DouBi Android（原 Python 项目 `src/` 的姊妹项目）

**DouBi 的 Android 原生客户端。** 与本仓库的 Python 桌面版（`src/` + `scripts/` + `tools/`）**完全独立**——同一份业务逻辑用 Kotlin 重写，**不**通过 Chaquopy 等桥接内嵌 Python。

桌面版发版节奏、CHANGELOG、BUILD 文档在这里**均不适用**——Android 版有自己的里程碑、文档与发版流程，全部在 `docs/` 子目录里。

## 当前进度

**阶段 14 完成**（v0.5.4-android 收官候选），`versionName = 0.5.4`，**尚未发布任何版本**。下一步是 v0.5.5+（真 X-Bogus 实装 / B 站抖音 API 客户端 / Engine 集成 / UI 集成）。

| | 状态 |
|---|---|
| 已完成 | 阶段 0 脚手架 ✅ ｜ 阶段 1 数据层 + 配置 ✅ ｜ 阶段 2 下载引擎 ✅ ｜ 阶段 3 UI 框架 ✅ ｜ 阶段 4 解析 + 列表 ✅ ｜ 阶段 5 下载 + 进度 + 完成通知 ✅ ｜ 阶段 6 历史 + 设置 ✅ ｜ 阶段 7 商店准备 ✅ ｜ 阶段 8 通用嗅探 ✅ ｜ 阶段 9 自用 UX 收官 ✅ ｜ 阶段 10 headless browser 嗅探 ✅ ｜ 阶段 11 WebViewHolder idle 30s release ✅ ｜ 阶段 12 m3u8 内容解析 ✅ ｜ 阶段 13 m3u8 递归解析 ✅｜ **阶段 14 B 站 / 抖音 platform foundation** ✅（BilibiliUrl 6 类型 + WbiSigner 完整 WBI 算法 + DouyinUrl 3 类型 + XBogusSigner placeholder + PlatformRegistry URL→Platform 分发 + PlatformModule Hilt + 37 例单测）|
| 待完成 | v0.5.5+ 单独 PR：真 X-Bogus 算法实装（v0.5.4 placeholder 不能直接打抖音 API）+ B 站 / 抖音 API 客户端（OkHttp + Retrofit + WBI/X-Bogus 签名）+ Engine 集成（`PlatformAdapter : Engine`）+ UI 集成（`PromptOptionsDialog` 清晰度选择 + 合集）。v0.5.6+：m3u8 v7+ HLS encryption / 多 variant 选择 UI / WebViewHeadlessSniffer 自身单测（需 Robolectric）/ ANR 风险测试 / DefaultWebViewFactory 配置 instrumented test |
| 测试 | 单测 **258/258 全绿**（2026-09-04 实跑验证：46 → 64 → 99 → 153 → 158 → 167 → 183 → 200 → 204 → 209 → 217 → 221 → 258，+212 例；v0.4.1 +16 例：SettingsViewModelTest +13 + HistoryViewModelTest +4；v0.5.0 +4：CompositeSnifferTest；v0.5.1 +5：WebViewHolderTest；v0.5.2 +8：M3u8ParserTest one-level；v0.5.3 +4：M3u8ParserTest parseRecursive；v0.5.4 +37：BilibiliUrlTest 10 + WbiSignerTest 6 + DouyinUrlTest 9 + XBogusSignerTest 5 + PlatformRegistryTest 7）；仪器测试 10 个**写了但从未在真机执行** |
| 能跑什么 | Run 起来 5 个 tab 底栏可点；粘贴 tab 输入 URL → **任意 http(s) URL**（含 B 站 / 抖音 / 微博主页"JS 异步加载"网站，v0.5.0 WebView 集成）→ 弹「下载选项」选 format + 容器 / 缩略图 / 字幕 / 续传 / 标题模板 → 入队 Worker；下载中 tab 看实时进度 + 速度 + ETA + 取消；历史 tab 看 Room 记录 + 文件状态 + 重新下载；设置 tab **13+ 字段改完即生效**（含主题切换、重复下载策略、引擎 aria2、通用嗅探 5 字段、附加 NFO/JSON/弹幕）；`assembleDebug` 成功出 ~78 MB APK（v0.5.0 WebView 集成 Chromium native lib 增量 +2 MB）；`bundleRelease` 成功出 **64.7 MB .aab**（自用 keystore 签名） |
| 构建环境 | ⚠️ 命令行必须用 AS 自带 JBR 25，系统 JDK 26 会挂在 `androidJdkImage`（[SETUP.md](docs/SETUP.md)）⚠️ release 签名走 `~/.gradle/gradle.properties` 环境变量，**keystore 不进 git**——换电脑需重新生成 |

**v0.1.0 收官前已还 7 笔欠账**：
- #1 失败重试（`setBackoffCriteria` EXPONENTIAL + `Result.retry()`，10 次封顶）
- #2 路径模板（Engine 真消费 `outputRoot` / `outputDirTemplate` / `filenameTemplate`）
- #3 Room 显式 `Migration` 链 + `MigrationTestHelper` 仪器测试
- #4 `Progress.speed` / `eta` 字段 + **修了 progress 0-100 量纲被截成满格的真 bug**（字节码级证据）
- #6 jacoco 覆盖率（基线 LINE 37.5% / METHOD 48.5%）
- #5（部分）`assembleDebug` 0 警告 + 4 ABI JNI 库完整
- #7 proguard 引擎类 keep + #8 SETUP.md JDK 26 → JBR 25 修法

**仍欠**：`#5 真机 adb install`（10 个仪器测试一次没跑）。完整登记见 [PHASES.md 的跨阶段欠账](docs/PHASES.md)。

## 入口

- **第一次打开这个目录**：[`docs/SETUP.md`](docs/SETUP.md) —— 实测环境、命令行构建与测试命令、排错表
- **这个项目要做到什么程度**：[`docs/PHASES.md`](docs/PHASES.md) —— 阶段划分、验收对账、跨阶段欠账
- **架构总览**：[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) —— 模块划分（标注已落地/未落地）、技术栈
- **从 Python 桌面版移植了什么**：[`docs/REUSE-MAP.md`](docs/REUSE-MAP.md) —— 一对一映射 + 落地状态
- **变更记录**：[`docs/CHANGELOG.md`](docs/CHANGELOG.md) —— Android 版独立 CHANGELOG，含「vs 桌面版」行为差异表
- **阶段复盘**：[`docs/phases/`](docs/phases/) —— [phase-1](docs/phases/phase-1.md)（含 5 个 Kotlin 编译坑）、[phase-2](docs/phases/phase-2.md)（含 4 个依赖集成坑）、[phase-3](docs/phases/phase-3.md)（含 5 笔欠账逐笔详解 + 6 个设计决定 + progress 0-100 量纲字节码证据）、[phase-4](docs/phases/phase-4.md)（含 5 个新文件 + 4 个坑 + 5 个设计决定）

## 与桌面版的对应关系

| 桌面版（Python） | Android 版（Kotlin） | 状态 |
|---|---|---|
| `src/doubi/core/pipeline.py` | `core/pipeline/` | ❌ 目录还不存在（阶段 4） |
| `src/doubi/engines/yt_dlp.py` | `engine/ytdlp/`（基于 Maven Central 的 `io.github.junkfood02.youtubedl-android:library`，Java 包名 `com.yausername.youtubedl_android.*`） | ✅ |
| `src/doubi/engines/nm3u8dl.py` | v0.1 不移植（见 PHASES）；ffmpeg 依赖也未启用 → **目前无 HLS 兜底** | ⏸️ |
| `src/doubi/platforms/{douyin,bilibili,youtube}/` | v0.1 只移植 `youtube/`；`bilibili` / `douyin` 在 v0.2 用 Kotlin 重写 | ❌ `platforms/` 整个目录不存在（阶段 4） |
| `src/doubi/ui/main_window.py` | `ui/`（Jetpack Compose 重写） | 🟡 只有占位 `home/` 和 `theme/` |
| `src/doubi/core/storage/` | `data/db/`（Room 替代 SQLite） | ✅ 4 entity + 4 DAO |
| `src/doubi/core/config.py` | `core/config/` + `data/config/`（DataStore 替代 YAML） | ✅ 30 字段 |
| `src/doubi/__init__.py:__version__` | `app/build.gradle.kts:versionName` | ✅ |

> Android 版包路径统一省略前缀 `app/src/main/java/com/doubi/android/`。

## 工作约定

- **绝对不动** `android/` 之外的文件。Python 桌面版的代码、文档、CHANGELOG 全部冻结
- **每个阶段收尾**（PHASES.md 里划的）写一份阶段文档到 `docs/phases/`，并把**未达成的验收登记到 PHASES.md 的欠账表**——阶段 1、2 就是因为漏了这步，攒下 6 笔隐性欠账
- **测试**：单元测试随模块走（`src/test/java/...`），仪器测试放 `src/androidTest/java/...`。用 **JUnit 4 + Truth**（不是 JUnit 5——Jupiter 与 AS 模板冲突）
- **CHANGELOG**：Android 版从 v0.1.0 起独立递增，写在 [`docs/CHANGELOG.md`](docs/CHANGELOG.md)，不沿用桌面版号
- **落地某个模块后**：回 [REUSE-MAP.md](docs/REUSE-MAP.md) 更新状态列，落点路径与实际代码不一致时当场改到一致
- **命令行构建**（PowerShell，不用 `&&`）：**先设 `$env:JAVA_HOME = 'C:\A\01SoftWares\03IDE\Android Studio\jbr'`**，
  再 `.\gradlew.bat testDebugUnitTest --rerun`。不设的话会用系统 JDK 26，构建必失败（jlink 挂在
  `androidJdkImage`）；不加 `--rerun` 可能 UP-TO-DATE 假绿。详见 [SETUP.md](docs/SETUP.md)
