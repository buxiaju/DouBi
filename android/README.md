# DouBi Android（原 Python 项目 `src/` 的姊妹项目）

**DouBi 的 Android 原生客户端。** 与本仓库的 Python 桌面版（`src/` + `scripts/` + `tools/`）**完全独立**——同一份业务逻辑用 Kotlin 重写，**不**通过 Chaquopy 等桥接内嵌 Python。

桌面版发版节奏、CHANGELOG、BUILD 文档在这里**均不适用**——Android 版有自己的里程碑、文档与发版流程，全部在 `docs/` 子目录里。

## 当前进度

**阶段 19 WIP 收尾**（v0.5.9-wip-android 收官候选），`versionName` 仍 `0.5.8`（**未** bump），**尚未发布任何版本**。下一步是 v0.5.9 完整版（在真抖音 API 验证环境下继续 Commit 3+4+5）。

| | 状态 |
|---|---|
| 已完成 | 阶段 0 脚手架 ✅ ｜ 阶段 1 数据层 + 配置 ✅ ｜ 阶段 2 下载引擎 ✅ ｜ 阶段 3 UI 框架 ✅ ｜ 阶段 4 解析 + 列表 ✅ ｜ 阶段 5 下载 + 进度 + 完成通知 ✅ ｜ 阶段 6 历史 + 设置 ✅ ｜ 阶段 7 商店准备 ✅ ｜ 阶段 8 通用嗅探 ✅ ｜ 阶段 9 自用 UX 收官 ✅ ｜ 阶段 10 headless browser 嗅探 ✅ ｜ 阶段 11 WebViewHolder idle 30s release ✅ ｜ 阶段 12 m3u8 内容解析 ✅ ｜ 阶段 13 m3u8 递归解析 ✅｜ 阶段 14 B 站 / 抖音 platform foundation ✅｜ 阶段 15 X-Bogus 真算法 part 1 ✅｜ 阶段 16 B 站 / 抖音 API 客户端 ✅｜ 阶段 17 平台 Engine 集成 ✅｜ 阶段 18 B 站/抖音 download 真路径 ✅｜ **阶段 19 XBogusSigner 真算法 port WIP 收尾** ✅（XBogusEncoding utility + XBogusMd5 utility + 修 alphabet bug + 13 例单测）|
| 待完成 | v0.5.9 完整版（在真 API 验证环境下继续）：XBogusEncodingConversion（Commit 3）+ XBogusSigner.sign() 走真算法（Commit 4，**缺真 API 验证**）+ versionCode 16→17 + versionName 0.5.8→0.5.9（**WIP 不 bump**）+ phase-19 完整版文档替换 WIP 文档。v0.6.0+：B站/抖音 UI 集成 + mixin_key/X-Bogus 缓存 + formats 列表 + B站 qn 配置化 + 抖音 short_link 解析 + m3u8 v7+ HLS encryption + WebViewHeadlessSniffer 自身单测（需 Robolectric）+ ANR 风险测试 + DefaultWebViewFactory 配置 instrumented test |
| 测试 | 单测 **327/327 全绿**（2026-09-07 实跑验证：46 → 64 → 99 → 153 → 158 → 167 → 183 → 200 → 204 → 209 → 217 → 221 → 258 → 269 → 279 → 302 → 314 → 327，+281 例；v0.4.1 +16；v0.5.0 +4；v0.5.1 +5；v0.5.2 +8；v0.5.3 +4；v0.5.4 +37；v0.5.5 +11；v0.5.6 +10；v0.5.7 +23；v0.5.8 +12；v0.5.9-wip +13：XBogusEncodingTest 7 + XBogusMd5Test 6）；仪器测试 10 个**写了但从未在真机执行** |
| 能跑什么 | Run 起来 5 个 tab 底栏可点；粘贴 tab 输入 URL → **任意 http(s) URL**（含 B 站 / 抖音 / 微博主页"JS 异步加载"网站，v0.5.0 WebView 集成）→ 弹「下载选项」选 format + 容器 / 缩略图 / 字幕 / 续传 / 标题模板 → 入队 Worker；下载中 tab 看实时进度 + 速度 + ETA + 取消；历史 tab 看 Room 记录 + 文件状态 + 重新下载；设置 tab **13+ 字段改完即生效**（含主题切换、重复下载策略、引擎 aria2、通用嗅探 5 字段、附加 NFO/JSON/弹幕）；v0.5.7 粘贴 tab 输入 B 站/抖音 URL → 自动 dispatch 到对应 Adapter 拿 metadata 填 MediaItem；v0.5.8 B 站/抖音点入队后走真 web API 拿 playUrl → YtDlpEngine 跑真实下载（B 站 1080p 完整可用，抖音走真 API 仍 -352 需 v0.5.9+ get_chaos 实装）；v0.5.9-wip 加 XBogusEncoding + XBogusMd5 utility（独立可测，**未**串到 XBogusSigner.sign()）；`assembleDebug` 成功出 ~80.8 MB APK；`bundleRelease` 成功出 **64.7 MB .aab**（自用 keystore 签名） |
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
- **阶段复盘**：[`docs/phases/`](docs/phases/) —— [phase-1](docs/phases/phase-1.md)（含 5 个 Kotlin 编译坑）、[phase-2](docs/phases/phase-2.md)（含 4 个依赖集成坑）、[phase-3](docs/phases/phase-3.md)（含 5 笔欠账逐笔详解 + 6 个设计决定 + progress 0-100 量纲字节码证据）、[phase-4](docs/phases/phase-4.md)（含 5 个新文件 + 4 个坑 + 5 个设计决定）、[phase-17](docs/phases/phase-17.md)（含 6 个设计决定 + 4 个 mockk 坑 + 5 份 v0.5.4-0.5.5 遗留 untracked 测试文件登记）、[phase-18](docs/phases/phase-18.md)（含 6 个设计决定 + 4 个坑 + 抖音 X-Bogus 仍 stub chaos 已知限制）、[phase-19](docs/phases/phase-19.md)（**WIP 收尾** — 2/5 commit + 4 个设计决定 + 4 个坑 + 缺真 API 验证的风险登记）

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
