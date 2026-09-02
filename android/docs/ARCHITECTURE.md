# 架构总览

> **本文档同时是目标架构和当前进度**。目录树里的标记：
> ✅ 已落地 ｜ 🟡 占位/部分 ｜ ❌ 尚未创建（**目录本身不存在**）
> 状态截至 2026-09-02（阶段 2 收官），按实际代码核对。

## 模块划分

```
android/
├── app/                          # 主 module（应用入口）
│   ├── src/main/java/com/doubi/android/
│   │   ├── DouBiApplication.kt   ✅ @HiltAndroidApp + WorkManager Configuration.Provider
│   │   │                            + Timber + YoutubeDL.init
│   │   ├── MainActivity.kt       🟡 单 Activity，NavHost 未接（阶段 3）
│   │   ├── core/                 # 业务核心
│   │   │   ├── model/            ✅ MediaItem / DownloadOptions / DownloadResult / Progress
│   │   │   │                        / Platform / MediaType / Author
│   │   │   ├── config/           ✅ AppConfig（30 字段）/ ConfigValidator / ConfigToOptions
│   │   │   ├── pipeline/         ❌ 用例层（ParseAndExpandUseCase / DownloadUseCase）——阶段 4
│   │   │   ├── naming/           ❌ 文件名模板渲染——欠账 #1
│   │   │   └── storage/          ❌ FileLayout 路径模板——欠账 #1
│   │   ├── data/                 # 数据层
│   │   │   ├── db/               ✅ Room：4 entity + 4 DAO + Converters + di/DatabaseModule
│   │   │   ├── config/           ✅ DataStore：AppConfigDataStore / ConfigKeys / di/DataStoreModule
│   │   │   └── repository/       ✅ DownloadRepository（UI 不直接调 DAO）
│   │   ├── engine/               # 下载引擎适配
│   │   │   ├── Engine.kt         ✅ 引擎接口（对齐桌面版 ABC）
│   │   │   ├── ytdlp/            ✅ YtDlpEngine（真实现，junkfood02 fork）
│   │   │   └── ffmpeg/           ❌ FFmpeg-Kit 依赖未启用 → 目前无 HLS 兜底
│   │   ├── platforms/            ❌ **整个目录不存在**
│   │   │   ├── youtube/          ❌ 阶段 4（当前只有 YtDlpEngine.supports 里的域名判断）
│   │   │   ├── generic/          ❌ 阶段 4
│   │   │   ├── bilibili/         ❌ v0.2+
│   │   │   └── douyin/           ❌ v0.2+
│   │   ├── download/             # WorkManager Workers
│   │   │   ├── DownloadWorker.kt ✅ CoroutineWorker + 前台 Service（**未在设备验证**）
│   │   │   └── NotificationHelper.kt ✅ 进度/完成通知 + PendingIntent 回 MainActivity
│   │   └── ui/                   # Compose UI
│   │       ├── theme/            ✅ Color / Type / Theme（首版 2 套）
│   │       ├── home/             🟡 HomeScreen 占位
│   │       ├── parse/            ❌ 阶段 4
│   │       ├── download/         ❌ 阶段 5
│   │       ├── history/          ❌ 阶段 6
│   │       └── settings/         ❌ 阶段 6
│   ├── src/main/res/
│   │   ├── values/               ✅ strings / colors / themes / ic_launcher_background
│   │   ├── values-zh/            ✅ strings.xml（中文 zh_CN）
│   │   ├── values-night/         ✅ themes.xml（暗色）
│   │   ├── drawable/             🟡 只有 ic_launcher_foreground，业务图标未导入
│   │   ├── mipmap-anydpi[-v26]/  ✅ adaptive icon
│   │   └── xml/                  ✅ backup_rules / data_extraction_rules
│   ├── src/test/                 ✅ 46 个单元测试（JUnit 4 + Truth，全绿）
│   ├── src/androidTest/          🟡 7 个仪器测试（**写了但从未执行**）
│   └── proguard-rules.pro        🟡 已 keep Hilt/Room/序列化/Compose，缺引擎类 keep（阶段 7）
│
├── build.gradle.kts              ✅ 根 project 配置（plugin 版本）
├── settings.gradle.kts           ✅ 包含 :app 子 module + repository
├── gradle.properties             ✅ JVM / AndroidX / Compose 标志（注意 ksp.useKSP2=false）
├── gradle/libs.versions.toml     ✅ 版本目录（统一依赖版本管理）
└── docs/                         # 文档（与仓库根 docs/ 分离）
    ├── SETUP.md                  # 环境与构建
    ├── PHASES.md                 # 阶段划分 + 跨阶段欠账登记
    ├── ARCHITECTURE.md           # 本文件
    ├── REUSE-MAP.md              # 桌面版 → Android 映射 + 落地状态
    ├── CHANGELOG.md              # Android 版独立 CHANGELOG（v0.1.0 起）
    └── phases/                   # 阶段复盘（phase-1.md / phase-2.md）
```

> **下文的「数据流」和「关键架构决定」描述的是目标架构**，其中 `platforms/` 与 `core/pipeline/` 尚未落地。
> 当前真实链路是「URL → `DownloadRepository.enqueue` → `DownloadWorker` → `YtDlpEngine`」，**没有经过策略层**。

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
| 视频下载 | [junkfood02 发布的 youtubedl-android](https://github.com/yausername/youtubedl-android) fork | yt-dlp (CLI/Python) |
| HLS / ffmpeg | FFmpeg-Kit（**依赖未启用**） | N_m3u8DL-CLI + ffmpeg.exe |
| 单元测试 | **JUnit 4 + Truth**（+ MockK / Turbine 已引入待用） | pytest + pytest-asyncio |
| 仪器测试 | Espresso + Compose UI Test（**尚未执行过**） | 无（PySide6 难自动化） |
| i18n | `res/values-zh/strings.xml` + `stringResource()` | JSON 词表 + `tr()` |

> ⚠️ **测试框架订正**：早期文档写「JUnit 5 + MockK」，实际用的是 **JUnit 4 + Truth**。
> 原因是 JUnit 5（Jupiter）与 Android Studio 的 JUnit 模板冲突，会报 "No junit.jar"，
> 阶段 1 已把 Jupiter 移除（commit `82f0399`）。MockK 和 Turbine 依赖在 `build.gradle.kts` 里已声明，但目前还没有测试用到。
>
> **依赖坐标 vs 包名**（最容易踩的一处）：Gradle 坐标是 `io.github.junkfood02.youtubedl-android:library:0.18.1`，
> 但 Java 包名是 `com.yausername.youtubedl_android.*`。详见 [phase-2.md](phases/phase-2.md) 的坑 2 / 坑 3。

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

## 数据流（下载一条 YouTube 视频）—— 🎯 目标架构

> ⚠️ **这张图画的是阶段 4/5 完成后的形态**，不是当前代码。图中 `ParseScreen` / `ParseViewModel` /
> `YouTubeStrategy` / `ParseAndExpandUseCase` / `DownloadUseCase` / `DownloadScreen` **都还不存在**。
>
> **当前真实链路**（阶段 2 终态，无 UI 无策略层）：
>
> ```
> URL ─► DownloadRepository.enqueue(url)
>          ├─► PendingTaskDao.upsert(status=queued)      # Room
>          └─► WorkManager.enqueueUniqueWork(DownloadWorker)
>                └─► DownloadWorker.doWork()
>                      ├─► AppConfigDataStore.get() ─► toDownloadOptions()
>                      ├─► YtDlpEngine.probe(url)          # YoutubeDL.getInfo()
>                      ├─► YtDlpEngine.download(...)       # YoutubeDL.execute()
>                      │     └─► filesDir/downloads/{platform}/{itemId}.{ext}
>                      ├─► PendingTaskDao 更新 status/progress
>                      └─► NotificationHelper 前台通知 + 完成通知
> ```

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
  │                                              │   YoutubeDL（youtubedl-android）
  │                                              │       │ getInfo(url)
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
[ui/parse/ParseScreen] ──── 入队────► [data/repository/DownloadRepository.enqueue(items)]
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
  │                                          │   YoutubeDL（youtubedl-android）
  │                                          │       │ execute(request, processId, callback)
  │                                          │       │
  │                                          │       ▼
  │                                          │   文件落盘到 app 私有目录
  │                                          │
  │                                          ├─► [data/db/PendingTaskDao.updateProgress(...)]
  │                                          │       │
  │                                          │       ▼
  │                                          │   Room 数据库
  │                                          │
  │                                          └─► [download/NotificationHelper.buildProgressNotification(...)]
  │                                                  │
  │                                                  ▼
  │                                          系统通知栏（前台 Service 持续显示）
  │
  ▼
[ui/download/DownloadScreen] 通过 Flow 观察 Room 进度 → 实时刷新
```

## 后续演进

**先把 v0.1 做完**（当前在阶段 3，见 [PHASES.md](PHASES.md)），之后：

- v0.2：B 站适配器（Web API + WBI 签名重写为 Kotlin）
- v0.3：抖音适配器（Web API + 签名）
- v0.4：通用嗅探（v0.1 不带 Chromium，手机版先用直链嗅探，v0.4 评估是否集成 [microsoft/playwright-android](https://github.com/microsoft/playwright/)）
- v1.0：i18n 完善 + 平板适配 + Google Play 上架

> 这几条都在**首个发布版本之后**。当前优先级是 [PHASES.md 的跨阶段欠账](PHASES.md)——
> 重试退避、路径模板、Room 迁移这三笔不还，v0.1 本身就不完整。
