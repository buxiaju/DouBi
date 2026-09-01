# DouBi Android（原 Python 项目 `src/` 的姊妹项目）

**DouBi 的 Android 原生客户端。** 与本仓库的 Python 桌面版（`src/` + `scripts/` + `tools/`）**完全独立**——同一份业务逻辑用 Kotlin 重写，**不**通过 Chaquopy 等桥接内嵌 Python。

桌面版发版节奏、CHANGELOG、BUILD 文档在这里**均不适用**——Android 版有自己的里程碑、文档与发版流程，全部在 `docs/` 子目录里。

## 入口

- **第一次打开这个目录**：[`docs/SETUP.md`](docs/SETUP.md) —— Android Studio 怎么 sync、JDK / SDK 要求
- **这个项目要做到什么程度**：[`docs/PHASES.md`](docs/PHASES.md) —— 阶段划分与里程碑
- **架构总览**：[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) —— 模块划分、技术栈
- **从 Python 桌面版移植了什么**：[`docs/REUSE-MAP.md`](docs/REUSE-MAP.md) —— 一对一映射

## 与桌面版的对应关系

| 桌面版（Python） | Android 版（Kotlin） |
|---|---|
| `src/doubi/core/pipeline.py` | `app/src/main/java/com/doubi/android/core/pipeline/` |
| `src/doubi/engines/yt_dlp.py` | `app/src/main/java/com/doubi/android/engine/ytdlp/`（基于 [yausername/yt-dlp-android](https://github.com/yausername/yt-dlp-android)） |
| `src/doubi/engines/nm3u8dl.py` | v0.1 不移植（见 PHASES） |
| `src/doubi/platforms/{douyin,bilibili,youtube}/` | v0.1 只移植 `youtube/`；`bilibili` / `douyin` 在 v0.2 用 Kotlin 重写 |
| `src/doubi/ui/main_window.py` | `app/src/main/java/com/doubi/android/ui/`（Jetpack Compose 重写） |
| `src/doubi/core/storage/` | `app/src/main/java/com/doubi/android/data/`（Room 替代 SQLite） |
| `src/doubi/core/config.py` | `app/src/main/java/com/doubi/android/data/config/`（DataStore 替代 YAML） |
| `src/doubi/__init__.py:__version__` | `app/build.gradle.kts:versionName` |

## 工作约定

- **绝对不动** `android/` 之外的文件。Python 桌面版的代码、文档、CHANGELOG 全部冻结
- **每个阶段收尾**（PHASES.md 里划的）写一份阶段文档到 `docs/phases/` 子目录
- **测试**：单元测试随模块走（`src/test/java/...`），仪器测试放 `src/androidTest/java/...`
- **CHANGELOG**：Android 版从 v0.1.0 起独立递增，不沿用桌面版号
