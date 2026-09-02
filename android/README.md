# DouBi Android（原 Python 项目 `src/` 的姊妹项目）

**DouBi 的 Android 原生客户端。** 与本仓库的 Python 桌面版（`src/` + `scripts/` + `tools/`）**完全独立**——同一份业务逻辑用 Kotlin 重写，**不**通过 Chaquopy 等桥接内嵌 Python。

桌面版发版节奏、CHANGELOG、BUILD 文档在这里**均不适用**——Android 版有自己的里程碑、文档与发版流程，全部在 `docs/` 子目录里。

## 当前进度

**阶段 3 / 7 完成**（v0.1.0 收官候选），`versionName = 0.1.0`，**尚未发布任何版本**。下一步是阶段 4（解析）。

| | 状态 |
|---|---|
| 已完成 | 阶段 0 脚手架 ✅ ｜ 阶段 1 数据层 + 配置 ✅（Room Migration 链已显式化）｜ 阶段 2 下载引擎 ✅（重试退避已加）｜ 阶段 3 UI 框架 ✅（4 占位 tab + Hilt ViewModel）|
| 待完成 | 阶段 4 解析 ｜ 5 下载进度 ｜ 6 历史设置 ｜ 7 商店准备 |
| 测试 | 单测 **99/99 全绿**（2026-09-02 实跑验证：46 → 64 → 99，+53 例）；仪器测试 10 个**写了但从未在真机执行**；jacoco 报告 LINE 37.5% / METHOD 48.5%（`core/model` 100% / `core/config` 100% / `engine/ytdlp` 59.9% / `download` 2.5% 是真缺口） |
| 能跑什么 | Run 起来 4 个 tab 底栏可点；粘贴 tab 可输入 URL；下载链路代码通但**无 UI 入口触发、未在真机验证**；`assembleDebug` 0 警告通过，APK 76.4 MB 含 4 ABI JNI 库 |
| 构建环境 | ⚠️ 命令行必须用 AS 自带 JBR 25，系统 JDK 26 会挂在 `androidJdkImage`（[SETUP.md](docs/SETUP.md)） |

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
- **阶段复盘**：[`docs/phases/`](docs/phases/) —— [phase-1](docs/phases/phase-1.md)（含 5 个 Kotlin 编译坑）、[phase-2](docs/phases/phase-2.md)（含 4 个依赖集成坑）、[phase-3](docs/phases/phase-3.md)（含 5 笔欠账逐笔详解 + 6 个设计决定 + progress 0-100 量纲字节码证据）

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
