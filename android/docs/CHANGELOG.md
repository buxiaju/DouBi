# CHANGELOG — DouBi Android

本文件记录 **Android 版**的变更。版本号从 `v0.1.0` 起**独立递增**，与 Python 桌面版（`/docs/CHANGELOG.md`）**不互通**。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

---

## [未发布] v0.1.0

**当前状态**：阶段 3 / 7 完成，`versionName = 0.1.0`，**尚未发布**。
首发范围是「UI 框架 + 4 占位 tab + 还完 5 笔欠账（#1 重试 / #2 路径模板 / #3 Room 迁移 / #4 Progress speed·eta / #6 jacoco）+ #5 产包验证」；阶段 4-7 留给后续版本。
剩余工作见 [PHASES.md](PHASES.md)。

---

## [未发布] v0.2.0

**当前状态**：阶段 4 完成（解析 + 列表），`versionName = 0.2.0`，**尚未发布**。
本版本新增 YouTube URL 分类 + MediaFormat formats 列表 + PromptOptionsDialog 选清晰度 + DownloadRepository.enqueue 一条龙；上一版 4 个未触发按钮变成真能下载。
**Tag**：`v0.2.0-android`（避免跟 Python 桌面版未来可能的 v0.2.x 撞号）。

### 已完成

**阶段 4 — 解析 + 列表**（`未提交`）

- **YouTubeUrl 分类**（`core/platform/youtube/YouTubeUrl.kt`）：11 字符 video ID regex 1:1 对拍桌面版 `classify_youtube_url`，支持 VIDEO / SHORTS / LIVE / EMBED；CHANNEL / PLAYLIST 归 `UNSUPPORTED`。归一化函数 `toWatchUrl()` 把任意合法 YouTube URL 变成 `https://www.youtube.com/watch?v=ID`
- **MediaFormat 数据类**（`core/model/MediaFormat.kt`）：1:1 对拍 desktop `FormatSpec` 精简版——`formatId` / `ext` / `height` / `width` / `vcodec` / `acodec` / `tbr` / `fileSize` / `isAudioOnly`。`label` 人类可读格式化（4K / 1080p / 720p / 480p / 360p / 240p / 144p / audio only），1 PB/s 停在 TB/s 不数组越界
- **YtDlpEngine.probeWithFormats()**：直接走 `YoutubeDL.getInfo()` 拿 `VideoInfo`，含 `formats: ArrayList<VideoFormat>`。`VideoFormat.toMediaFormatOrNull()` 转换器，`fileSize == 0` 时兜底用 `fileSizeApproximate`
- **EngineModule Hilt 装配**（`engine/ytdlp/di/EngineModule.kt`）：`@Named("baseOutputDir")` 拿 `Context.filesDir/downloads`，避免 YtDlpEngine 间接持有 Context。`@Singleton` 提供 YtDlpEngine
- **ParseAndExpandUseCase**（`core/pipeline/ParseAndExpandUseCase.kt`）：sealed `ParseResult`（Youtube / DirectLink / Unsupported）。YouTube 路径走 `toWatchUrlOrNull` 判 → probeWithFormats；youtube 频道 / 播放列表走 Unsupported；直链（m3u8 / mp4）走 DirectLink，format 选 video-first fallback
- **PromptOptionsDialog**（`ui/parse/PromptOptionsDialog.kt`）：Compose Material 3 AlertDialog。format radio（LazyColumn 滚动列表）+ 容器 chip（mp4 / mkv）+ 缩略图 / 字幕 / 续传 checkbox + 标题模板（勾选启用 + 输入框，默认 `{title}`）。`onConfirm(item, format, options, titleTemplate)` 把数据回传给 ViewModel
- **PastingViewModel 5 状态机**：`Idle` / `Parsing` / `AwaitingConfirm(item, formats, seed)` / `Unsupported(reason)` / `Enqueued(taskId, title)` / `Failure(error)`。一次性消息用 `onMessageShown()` 重置回 Idle，让 snackbar 不重复
- **PastingScreen 改造**：监听 state，`AwaitingConfirm` 时弹 Dialog，`Enqueued` / `Unsupported` / `Failure` 时 snackbar 一次性反馈
- **测试 +54**（`YouTubeUrlTest` 25 + `MediaFormatTest` 15 + `ParseAndExpandUseCaseTest` 14），全量单测 **153/153 全绿**（v0.1 99 → v0.2 153）
- **APK 验证**：`assembleDebug` 0 警告通过，77.05 MB（v0.1 76.43 → v0.2 77.05，+0.6 MB），4 ABI JNI 库 + 8 权限齐
- **覆盖率**：LINE 34.7% / METHOD 45.2% / CLASS 31.2%（v0.1 37.5 / 48.5 / 30.8 —— 新代码量大于测试覆盖是预期，阶段 5 加 Compose UI test + instrumented test 拉起来）

### 修复

- **Function type 不允许 named args**（`v0.2.0`）：`onConfirm: (item, format, options, titleTemplate) -> Unit` 是 function type，调用 `onConfirm(item, sel, opts, titleTemplate = xxx)` 编译错 `Named arguments are prohibited for function types`。lambda 类型的参数名是 IDE 提示用，**不是** named arg key。改成位置传参
- **Use case 漏判 YouTube 频道 / 播放列表**（`v0.2.0`）：第一版 `toWatchUrlOrNull` null 就走 DirectLink 调 probeWithFormats，导致 youtube 频道 URL 也调了 yt-dlp。修：youtube 域名但非视频形态 → Unsupported，**不调** engine
- **Regex 命名组 + `groups["id"]` 在缺失组上崩**（`v0.2.0`）：`YouTubeUrl.classify()` 总是 `m.groups["id"]?.value`，但 CHANNEL / PLAYLIST pattern **不带** `(?<id>...)` 命名组，触发 `IllegalArgumentException: No group with name <id>`。修：`runCatching { m.groups["id"]?.value }.getOrNull().orEmpty()` 兜底

### 已知问题（v0.2.0 发布前**剩余**的必须处理）

- **v0.1 阶段 5 / 6 全部未做**（Worker 进度 / 队列并发 3 / 完成通知三档 / 历史 Room 查询 / 设置 tab）
- **Compose UI test for PromptOptionsDialog** —— 阶段 5 加
- **仪器测试 10 个仍没真机跑过**（v0.1 留的债，v0.2 阶段 5 接 Worker 时一起跑）
- **覆盖率门槛** —— 当前 LINE 34.7% / METHOD 45.2%，新代码增量大于测试覆盖；阶段 5 加 Compose UI test + instrumented test 拉起来

**阶段 0 — 项目脚手架**（`fed93ac`）

- Gradle 工程骨架：`settings.gradle.kts` / `build.gradle.kts` / `gradle.properties` / `gradle/libs.versions.toml` 版本目录
- Hilt 入口 `DouBiApplication`（`@HiltAndroidApp`）+ 单 Activity `MainActivity`
- Material 3 主题（`ui/theme/{Color,Type,Theme}.kt`），亮/暗随系统
- 中英文资源目录（`values/` + `values-zh/`）、adaptive icon
- 文档体系：README / SETUP / PHASES / ARCHITECTURE / REUSE-MAP

**阶段 1 — 数据层 + 配置**（`fed93ac`、`865eb35`、`ab0aee9`）

- Room 数据层：4 个 entity（`media_item` / `task` / `pending_task` / `increment_checkpoint`）+ 4 个 DAO，方法逐一对拍桌面版 `core/storage/database.py:Database`
- `DatabaseModule` 用 `getDatabasePath()` 绝对路径注入，索引命名照搬桌面版
- DataStore 配置层：`AppConfig`（30 字段，对拍桌面版 `core/config.py`）+ `ConfigKeys` + `AppConfigDataStore`（read / write / observe / updateField）
- `ConfigValidator`：8 个白名单 + 2 个 clamp，坏值静默回退默认，**不抛异常**
- 测试 30 个：单测 24（`AppConfigTest` 13 + `AppConfigDataStoreTest` 11）+ 仪器 6（`MediaItemDaoTest`）

**阶段 2 — 下载引擎**（`d814f62`、`eef318a`、`3d4e252`）

- `Engine` interface，4 个成员 1:1 对拍桌面版 `engines/__init__.py:Engine` ABC；callback → `suspend`，抛异常 → `sealed class DownloadResult`
- 7 个数据模型：`MediaItem` / `DownloadOptions` / `DownloadResult` / `Progress` / `Platform` / `MediaType` / `Author`
- `YtDlpEngine` 真实现——`YoutubeDL.getInfo()` 嗅探 + `execute(request, processId, callback)` 下载
- `DownloadWorker`（`CoroutineWorker` + 前台 Service）、`NotificationHelper`（进度/完成通知 + 点击回 `MainActivity`）、`DownloadRepository`（DAO + WorkManager 入口）
- `DouBiApplication` 实现 `Configuration.Provider`，Manifest 关掉 WorkManager 默认初始化
- 测试 +21（`ModelTest` 10 + `YtDlpEngineTest` 11），全量单测 **46/46 全过**

**阶段 3 — UI 框架 + 还 v0.1.0 关键欠账**（`待提交`）

- 接入 Navigation Compose 2.8.4（已在 `libs.versions.toml` 留位）+ Hilt Navigation Compose 1.2.0
- `AppNavigation` 壳：Scaffold + 4 tab 底栏 + NavHost，`saveState`/`restoreState` 让切 tab 不重置输入框
- 4 个 Screen 占位（`pasting` / `parsing` / `downloading` / `history`）+ 各自 Hilt `ViewModel`（`PastingViewModel` / `DownloadingViewModel`）；`DownloadingViewModel` 订阅 `DownloadRepository.activeTasks` 实时显示活跃任务数
- 字符串资源化（`nav_paste` / `nav_parse` / `nav_download` / `nav_history` + 4 个 Screen 标题）
- **还账 #1**：`DownloadRepository.enqueue` 加 `setBackoffCriteria(EXPONENTIAL, 30s)`；`DownloadWorker.doWork` 加 `runAttemptCount` 打点 + `isTransientFailure()` 判据；瞬时错误 `Result.retry()`、永久错误 `Result.failure()`。最多 10 次自动重试
- **还账 #2**：`DownloadOptions` 加 `outputRoot` / `outputDirTemplate` 字段；`YtDlpEngine.resolveOutputDir()` 真消费三个模板，`{title}` / `{item_id}` / `{platform}` / `{author}` / `{media_type}` 全展开，author 为空时降级 `_`；`sanitizeFilename` 把 `/ \ : * ? " < > |` 全替 `_`；`findProducedFile` 兜底扫描子目录
- **还账 #3 part 1**：`Migrations` 对象（`ALL: Array<Migration>`）+ `app/schemas/` 导出 + `androidTest.assets.srcDirs` 把 schemas 打进仪器测试资源；`DatabaseModule` 把 `fallbackToDestructiveMigration()` 换成 `addMigrations(*Migrations.ALL) + fallbackToDestructiveMigrationOnDowngrade(true)`；Room 升 **2.7.2**（`MigrationTestHelper` 从 2.7 起稳定）；新增 `MigrationTest`（3 个仪器测试）
- **还账 #3 part 2**：`proguard-rules.pro` 加 `-keep class com.yausername.youtubedl_android.** { *; }` 与 `-dontwarn`
- **还账 #4**：`Progress` 加 `speedBytesPerSec` / `etaSeconds` 字段（默认 null，`non-positive` 视为未知）+ `statusLine()` / `formatSpeed()` / `formatEta()`（1024 进制 + `Locale.US`）；`YtDlpEngine` 从 `at 1.23MiB/s` 片段正则解析；`DownloadWorker` 用 `setProgress(KEY_SPEED/ETA)` 透传，`NotificationHelper.buildProgressNotification` 走 `statusLine()` 一行式
- **还账 #6**：接 `org.gradle.jacoco`（走 `buildscript classpath`，**不**走 plugins DSL —— plugin marker artifact `org.jacoco:org.jacoco.gradle.plugin:0.8.12` 不存在）；自定义 `jacocoTestReport` 任务出 XML + HTML，KSP/Hilt/Room 生成的 stub 排除。**基线覆盖率 LINE 37.5% / METHOD 48.5% / CLASS 30.8%**（`core/model` 100% / `core/config` 100% / `engine/ytdlp` 59.9% / `download` 2.5%——`doWork` 跟 `NotificationHelper` 是 v0.2 仪器测试要补的真实缺口）
- **还账 #5（部分）**：`assembleDebug` 0 警告通过，APK **76.4 MB** 含 4 ABI（x86 / x86_64 / armeabi-v7a / arm64-v8a）的 `libpython.zip.so`（每个 12-14 MB）+ `libqjs.so` + `libdatastore_shared_counter.so`；合并后 Manifest 8 个权限齐（`INTERNET` / `ACCESS_NETWORK_STATE` / `FOREGROUND_SERVICE` / `FOREGROUND_SERVICE_DATA_SYNC` / `POST_NOTIFICATIONS` / `WRITE_EXTERNAL_STORAGE(maxSdkVersion=28)` / `WAKE_LOCK` / `RECEIVE_BOOT_COMPLETED`）+ WorkManager 三个 Service 完整；schema 资产**故意不**进 main APK（只在 androidTest 用，减小产包）。**真机 adb install 未做**（v0.1 计划外）
- **顺手加固**：`packaging.jniLibs.useLegacyPackaging = true`（消除「`extractNativeLibs=true` 跟 AGP 默认冲突」警告）；`buildDir` 改用 `layout.buildDirectory`（去两个 deprecation 警告）
- 测试 +35（`ProgressTest` 25 测格式 / 退化 / 未知约定 + `YtDlpEngineTest` 加 10 测 `parseSpeedBytesPerSec`），全量单测 **99/99 全过**

### 修复

- **KSP2 与 Hilt 不兼容**（`fed93ac`）：`ksp.useKSP2=true` 导致 KSP 阶段抛 `IllegalArgumentException`（[Dagger #4680](https://github.com/google/dagger/issues/4680)）。改为 `false`，阶段 7 前不要开
- **测试库作用域**（`fed93ac`）：`truth` / `kotlinx-coroutines-test` 只加在 `testImplementation`，`androidTest` 编译失败。两个作用域都要加
- **`DEFAULTS` 作用域盲区**（`d4f730f`）：`data class` 主构造器默认值看不到 `companion object` 里的嵌套 `object`，12 条 `Unresolved reference`。把 `object DEFAULTS` 提到文件顶层
- **Kotlin smart-cast 失效**（`2f84d55`）：`if (value in setOf(...))` 和 `isNullOrBlank()` 都不触发 smart cast，返回类型退化成 `String?`。所有 validator 显式加 `value != null`
- **`updateField` 可空入参**（`b795380`）
- **JUnit Jupiter 冲突**（`82f0399`）：Jupiter 与 AS 的 JUnit 模板冲突报 "No junit.jar"，移除 Jupiter，统一用 **JUnit 4 + Truth**
- **`sniff_capture_types` roundtrip 顺序**（`ab0aee9`）：DataStore `stringSetPreferencesKey` 无序，约定写时 `toSet()`、读时 `toList().sorted()`
- **JitPack 401 → Maven Central**（`3d4e252`）：`io.github.yausername.ytdlp-android:core` 只在 JitPack 发布且返 401。换成 Maven Central 的 `io.github.junkfood02.youtubedl-android:library:0.18.1`
- **引擎包名与 API 表面**（`3d4e252`）：实际包名是 `com.yausername.youtubedl_android.*`（不是 `com.yausername.ytdlp.*`），callback 是 `Function3<Float, Long, String, Unit>`、`addOption(key, value)` 分两参、`execute()` 返 `YoutubeDLResponse`。按 AAR 实际 API 重写 `YtDlpEngine` 与 `DownloadWorker`
- **字符类内 `*?` 误为量词**（`阶段 3`）：`Regex("""[/\\:*?"<>|]""")` 里 `*?` 被 Java regex 解析成懒惰量词，导致 5 个非法字符里 2 个不被替。改成 `setOf(...)` + `map` 遍历，9 个字符 100% 命中
- **命令行构建挂在 `androidJdkImage`**（`阶段 3`）：本机 PATH 上是 JDK 26，AGP 8.7.3 在 jlink 这步挂掉。**修法**：把 `JAVA_HOME` 指向 Android Studio 自带的 JBR 25（`C:\A\01SoftWares\03IDE\Android Studio\jbr`），或写 `~/.gradle/gradle.properties` 的 `org.gradle.java.home`。详见 [SETUP.md](SETUP.md)
- **`UP-TO-DATE` 假绿**（`阶段 3`）：`testDebugUnitTest` 在没源文件变动时直接返回 `BUILD SUCCESSFUL` 而一个测试都没跑。要强制重跑必须加 `--rerun`，或看 `app/build/test-results/testDebugUnitTest/` 报告时间戳
- **progress 回调量纲是 0-100 而非 0-1**（`阶段 3`）：youtubedl-android 0.18.1 的 `StreamProcessExtractor.getProgress` 直接 `Float.parseFloat` 百分号前的数字（**字节码级证据**：`\[download\]\s+(\d+\.\d)% .* ETA (\d+):(\d+)`），ffmpeg 分支硬编 `99.0f`，初始值 `-1.0f`。原 `YtDlpEngine.download` 写 `progress.coerceIn(0f, 1f)` 会把 1% 以上的进度**全部截成 100%**——进度条从第一次回调起就满格。修法：`(progress / 100f).coerceIn(0f, 1f)`
- **Kotlin String literal 把 `%1$d` 里的 `$d` 解析成变量引用**（`阶段 5`）：`stringResource(R.string.pasting_queue_full, "%1$d", "%2$d")` 编译错 `Unresolved reference 'd'`——Kotlin 把 `$` 紧跟 identifier char `d` 当 Kotlin 变量。修法：`stringResource` 只传模板，`String.format` 推迟到运行时

### 已知问题（v0.2.1 发布前**剩余**的必须处理）

完整登记见 [PHASES.md 的跨阶段欠账](PHASES.md)。阶段 5 已还 5 笔 v0.2.0 阶段欠账（#1 阶段 3 已还的也累计算），**仍欠**：

- **真机 adb install 验证完整流程**（解析 → 弹 dialog → 入队 → Worker 跑 → Downloading tab 看进度）—— 阶段 6 接历史 tab 前必须补
- **Compose UI test for DownloadingScreen** —— 阶段 6 加
- **instrumented test for DownloadWorker 三档通知**（mock NotificationHelper）—— 阶段 6 加
- **summary 模式 batch 定时汇总**（桌面版 10 分钟汇总）—— v0.2.2
- **取消任务时回收 PendingTaskDao 那条 row**（当前只 updateProgress "paused"，不删）—— v0.2.2
- **覆盖率门槛** —— LINE 30.7% / METHOD 42.1%（新 UI 增量大于测试覆盖；阶段 6 加 Compose UI test + instrumented 拉起来）

### vs 桌面版的行为差异

| 项 | 桌面版（Python） | Android 版 | 原因 |
|---|---|---|---|
| 数据库路径 | `database_path` 默认相对路径 `"doubi.db"`，卸载有残留（桌面版 0.3.1 的坑） | `getDatabasePath()` 绝对路径，随卸载清除 | 平台机制不同，**主动绕开该坑** |
| 配置存储 | `~/.doubi/config.yml`（YAML） | DataStore Preferences（app 私有目录） | 更原生 |
| 配置校验 | 只校验 `notify_on_completion` | 8 个白名单 + 2 个 clamp 全覆盖 | **Android 端比桌面版更严**——手机上 Worker 池被坏值炸掉代价更高 |
| 可空字符串 | YAML 里 key 缺失 | 空串 sentinel（`rateLimit` / `proxy` / `aria2Secret`） | Preferences 无 nullable string |
| `sniff_capture_types` | `tuple[str, ...]` 有序 | `Set` 落盘、读出排序 | Set 语义本就无序，对功能无影响 |
| 后台任务 | asyncio 任务 | WorkManager `CoroutineWorker` | 进程被杀 / 重启后可恢复 |
| 失败重试 | **手动**——`TaskManager.retry()` 由用户在 UI 点 | **自动 + 手动**——WorkManager 指数退避 10 次封顶，永久错误返 failure 让用户手动 retry | 移动端 OS 杀进程更频繁 |
| 最小化行为 | 关窗到系统托盘 | 通知 + 最近任务卡片 | 手机无托盘 |
| 引擎 | yt-dlp CLI + N_m3u8DL-CLI + aria2 + ffmpeg.exe | 仅 youtubedl-android（自带 yt-dlp + Python 运行时） | 手机无外部二进制 |
| `AppConfig.extra` | `dict[str, Any]` | **未实现** | 首版设置页与 Worker 都用不到 |
| i18n | 自研 JSON 词表 + `tr()` | `res/values-zh/strings.xml` + `stringResource()` | 更原生，两边各自维护、术语对齐 |
| Room Migration | SQLAlchemy `Base.metadata.create_all()` 跑全量 | 显式 `Migration(n, n+1)` 链 + `MigrationTestHelper` 仪器测试 | 移动端不能容忍升级丢数据 |
| 队列并发 | 桌面版 `TaskManager` 内存态并发 | **enqueue 入口并发检查**（`AppConfig.concurrentJobs`，默认 3） | Android 单 UI 不需要 Worker 内部 Semaphore |
| 完成通知 | `TrayController.notify_on_completion` 三档 | `NotificationHelper.notifyByCompletionMode` 三档（success / all / summary） | 1:1 对拍，summary batch 摘要留 v0.2.2 |

---

## 维护约定

- 每个阶段收尾时，把该阶段的 Added / Fixed 补进「未发布」段，并在 [`phases/`](phases/) 写复盘文档
- 发布时把「未发布」改成 `## [0.1.0] - YYYY-MM-DD`，同时更新 `app/build.gradle.kts` 的 `versionCode` / `versionName`
- 桌面版的 bug 如果需要 port 到 Android，**两边 CHANGELOG 各记一笔**
- 跨平台行为差异一律记进上面的「vs 桌面版」表
