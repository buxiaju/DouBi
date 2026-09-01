# 架构总览

## 模块划分

```
android/
├── app/                          # 主 module（应用入口）
│   ├── src/main/java/com/doubi/android/
│   │   ├── DouBiApplication.kt   # @HiltAndroidApp 入口
│   │   ├── MainActivity.kt       # 单 Activity + Compose NavHost
│   │   ├── core/                 # 业务核心（pipeline / model / 配置 / 异常）
│   │   │   ├── model/            # 纯数据类（MediaItem / DownloadTask / DownloadOptions / AppConfig）
│   │   │   ├── pipeline/         # 用例层（ParseAndExpandUseCase / DownloadUseCase / ...）
│   │   │   ├── naming/           # 文件名模板渲染（_sanitize + renderFilename）
│   │   │   └── config/           # AppConfig 单例 + DataStore 读写
│   │   ├── data/                 # 数据层
│   │   │   ├── db/               # Room：MediaItemDao / TaskDao + entity
│   │   │   ├── datastore/        # DataStore Preferences
│   │   │   └── repository/       # Repository 模式（UI 不直接调 DAO）
│   │   ├── engine/               # 下载引擎适配
│   │   │   ├── ytdlp/            # 基于 yausername/yt-dlp-android
│   │   │   ├── ffmpeg/           # FFmpeg-Kit 通用下载（v0.1 占位）
│   │   │   └── Engine.kt         # 引擎接口 ABC（与桌面版对齐）
│   │   ├── platforms/            # 平台适配器
│   │   │   ├── youtube/          # YouTube 策略（v0.1）
│   │   │   ├── generic/          # 通用 m3u8 / mp4 策略（v0.1）
│   │   │   ├── bilibili/         # v0.2+ 才做
│   │   │   └── douyin/           # v0.2+ 才做
│   │   ├── download/             # WorkManager Workers
│   │   │   ├── DownloadWorker.kt
│   │   │   └── NotificationHelper.kt
│   │   └── ui/                   # Compose UI
│   │       ├── theme/            # Color / Type / Theme
│   │       ├── home/             # 主框架 + 4 页导航
│   │       ├── parse/            # 解析页（粘贴 URL + 表格）
│   │       ├── download/         # 下载中 / 已完成
│   │       ├── history/          # 历史
│   │       └── settings/         # 设置
│   ├── src/main/res/
│   │   ├── values/               # strings.xml / colors.xml / themes.xml
│   │   ├── values-zh/            # 中文（zh_CN）
│   │   ├── values-night/         # 暗色主题
│   │   └── drawable/             # 图标资源
│   └── src/test/                 # 单元测试（JUnit + MockK + Turbine）
│
├── build.gradle.kts              # 根 project 配置（plugin 版本）
├── settings.gradle.kts           # 包含 :app 子 module + repository
├── gradle.properties             # JVM / AndroidX / Compose 标志
├── gradle/libs.versions.toml     # 版本目录（统一依赖版本管理）
└── docs/                         # 文档（与仓库根 docs/ 分离）
    ├── SETUP.md
    ├── PHASES.md
    ├── ARCHITECTURE.md           # 本文件
    └── REUSE-MAP.md
```

## 技术栈

| 关注点 | 选型 | 桌面版对照 |
|---|---|---|
| 语言 | Kotlin 2.0.21 + K2 编译器 | Python 3.13 |
| UI 框架 | Jetpack Compose + Material 3 | PySide6 + qfluentwidgets |
| 架构模式 | MVVM + Repository | 单文件 page widget |
| 异步 | Coroutines + Flow | asyncio + aiohttp |
| 依赖注入 | Hilt | 无（手动 wiring） |
| 本地存储 | Room（SQLite）+ DataStore | SQLite + YAML |
| 后台任务 | WorkManager + 前台 Service | asyncio 任务 + 系统托盘 |
| 网络 | Retrofit + OkHttp + kotlinx.serialization | aiohttp + orjson |
| 视频下载 | [yausername/yt-dlp-android](https://github.com/yausername/yt-dlp-android) | yt-dlp (CLI/Python) |
| HLS / ffmpeg | FFmpeg-Kit | N_m3u8DL-CLI + ffmpeg.exe |
| 单元测试 | JUnit 5 + MockK + Turbine | pytest + pytest-asyncio |
| 仪器测试 | Espresso + Compose UI Test | 无（PySide6 难自动化） |
| i18n | `res/values-zh/strings.xml` + `stringResource()` | JSON 词表 + `tr()` |

## 关键架构决定

### 1. 引擎抽象对齐桌面版

桌面版 `engines/__init__.py:Engine` ABC 的三个方法在 Android 版保持一致：

```kotlin
interface Engine {
    val name: String                  // "yt-dlp" / "ffmpeg" / "aria2"
    fun supports(url: String, options: DownloadOptions): Boolean
    suspend fun probe(url: String, options: DownloadOptions): MediaItem
    suspend fun download(item: MediaItem, options: DownloadOptions, onProgress: suspend (Progress) -> Unit): DownloadResult
}
```

这样 `DownloadPipeline` 在两个平台是**心智模型一致**的——同样支持「嗅探 → 解析 → 策略分发 → 引擎下载」四步。

### 2. 配置 `AppConfig` 数据类

桌面版 `core/config.py:AppConfig` 是 dataclass；Android 版用 Kotlin data class + Hilt 注入。字段一一对应，详见 [REUSE-MAP.md](REUSE-MAP.md)。

### 3. i18n 不复用桌面版 JSON 词表

桌面版用自研 JSON 词表（`ui/locales/zh_CN.json`），Android 版用 `res/values-zh/strings.xml` 更原生。两边各自维护，**术语保持一致**（中英文翻译用一个对照表，避免漂移）。

### 4. WorkManager 替代 asyncio 任务

桌面版一个长下载就是一个 asyncio 任务；Android 版用 `CoroutineWorker`。WorkManager 的好处是：
- 进程被杀后能恢复（对齐桌面版 M6.10 跨进程恢复）
- 系统重启 / OTA 后能继续
- 低内存自动降级（不像桌面版那么紧迫）

### 5. 通知替代托盘

桌面版「关窗最小化到托盘」是 Windows 特有交互。手机端对应物是「通知 + 最近任务卡片」：
- 进度通知（前台 Service 必需）
- 完成通知（success / all / summary 三档对齐桌面版）
- 点击通知 → 回到应用对应任务

## 数据流（下载一条 YouTube 视频）

```
[用户]
  │  粘贴 URL 到「解析」页
  ▼
[ui/parse/ParseScreen] ──── 点「解析」────► [ViewModel.parse(url)]
  │                                              │
  │                                              ▼
  │                                  [core/pipeline/ParseAndExpandUseCase]
  │                                              │
  │                                              ├─► [platforms/youtube/YouTubeStrategy.detect(url)]
  │                                              │       │
  │                                              │       ▼
  │                                              │   [engine/ytdlp/YtDlpEngine.probe(url)]
  │                                              │       │
  │                                              │       ▼
  │                                              │   yausername/yt-dlp-android
  │                                              │       │ extractInfo()
  │                                              │       │
  │                                              │       ▼
  │                                              │   List<MediaItem>
  │                                              │
  │                                              ▼
  │                                  [List<MediaItem> 流回 UI]
  │
  │  [用户勾选若干条，点「下载」]
  │
  ▼
[ui/parse/ParseScreen] ──── 入队────► [data/repository/TaskRepository.enqueue(items)]
  │                                          │
  │                                          ▼
  │                              [WorkManager.enqueue(DownloadWorker, ...)]
  │                                          │
  │                                          ▼
  │                              [download/DownloadWorker.doWork()]
  │                                          │
  │                                          ├─► [core/pipeline/DownloadUseCase]
  │                                          │       │
  │                                          │       ▼
  │                                          │   [engine/ytdlp/YtDlpEngine.download(...)]
  │                                          │       │
  │                                          │       ▼
  │                                          │   yausername/yt-dlp-android
  │                                          │       │ download() + 进度回调
  │                                          │       │
  │                                          │       ▼
  │                                          │   文件落盘到 app 私有目录
  │                                          │
  │                                          ├─► [data/db/TaskDao.update(progress)]
  │                                          │       │
  │                                          │       ▼
  │                                          │   Room 数据库
  │                                          │
  │                                          └─► [download/NotificationHelper.notify(progress)]
  │                                                  │
  │                                                  ▼
  │                                          系统通知栏（前台 Service 持续显示）
  │
  ▼
[ui/download/DownloadScreen] 通过 Flow 观察 Room 进度 → 实时刷新
```

## 后续演进

- v0.2：B 站适配器（Web API + WBI 签名重写为 Kotlin）
- v0.3：抖音适配器（Web API + 签名）
- v0.4：通用嗅探（v0.1 不带 Chromium，手机版先用直链嗅探，v0.4 评估是否集成 [microsoft/playwright-android](https://github.com/microsoft/playwright/)）
- v1.0：i18n 完善 + 平板适配 + Google Play 上架
