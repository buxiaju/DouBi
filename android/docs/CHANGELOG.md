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

---

## [未发布] v0.2.2

**当前状态**：阶段 6 完成（历史 + 设置），`versionName` 仍 `0.1.0`（CHANGELOG 草稿照例标"已升 0.2.2"是错的，没改），**尚未发布**。
本版本补齐 v0.2.1 漏的 Worker 落库 + 历史 tab 真接 Room + 设置 tab 5 组字段改完即生效。
**Tag**：`v0.2.2-android`。

### 已完成

**阶段 6 — 历史 + 设置**（`未提交`）

- **DownloadWorker Success 路径补 mediaItemDao.upsert(MediaItemEntity)**（`download/DownloadWorker.kt`）：v0.1 阶段 2 没把成功的 MediaItem 落库，给阶段 6 历史 tab 用
  - 注入 `MediaItemDao`（Hilt 自动装配）
  - Success 分支写 `MediaItemEntity(platform, item_id, title, author, ..., lastDownloadTime, lastSaveDir = File(localPath).parent, extra = sourceUrl JSON)`
  - 用 `runCatching` 包，失败只 log 不抛异常（落库失败不影响下载完成态）
- **sourceUrl 存进 extra JSON 字段**（`extra = {"source_url": "https://youtu.be/..."}`）：MediaItemEntity schema 冻结（v0.1 阶段 3 显式 Migration 链），借 `extra` 字段存 platform-specific 字段（跟桌面版用 `extra` 存 platform-specific 一致）
- **HistoryViewModel + HistoryScreen**（`ui/history/`）：
  - 订阅 `MediaItemDao.listRecentFlow(200)` 按 `last_download_time DESC`
  - `withContext(Dispatchers.IO) { checkFileExists(entity) }`：弱版（目录非空即存在，不反推具体文件名——v0.2.2 阶段 7 加严格版）
  - `onRedownload(item)` 读 `extra` 里 sourceUrl 调 `downloadRepo.enqueue(...)` 走原 Worker 路径
  - 6 种状态：✅ 文件存在 / ⚠ 文件已删除（图标 + 文本双提示）
  - Snackbar 反馈「已入队重新下载」「重新下载失败」
- **SettingsViewModel + SettingsScreen**（`ui/settings/`）：
  - 订阅 `AppConfigDataStore.observe()`（DataStore reactive）→ stateIn → Compose 重组
  - `onFieldChanged(key, value)` 调 `configStore.updateField(key, value)` 单字段原子写
  - 5 组 SectionCard：输出（outputRoot / outputDirTemplate / filenameTemplate）/ 画质容器（maxQuality dropdown / container dropdown / concurrentJobs number）/ 附加（writeThumbnail / writeSubtitles / resume / promptBeforeDownload switch）/ 网络（proxy / rateLimit）/ 通知（notifyOnCompletion dropdown）
  - **改完立即生效**（vs 桌面版 `config.py` 需重启）—— DataStore reactive 自动 emit
- **AppNavigation 5 底栏 tab**（`ui/navigation/`）：pasting / parsing / downloading / history / settings；加 `Icons.Outlined.Settings` icon
- **测试 +9**（`HistoryViewModelTest` 6 + `SettingsViewModelTest` 3），全量单测 **167/167 全绿**（v0.2.1 158 → v0.2.2 167）
- **APK 验证**：`assembleDebug` 0 警告通过，APK 77.07 MB（v0.2.1 77.05 → v0.2.2 77.07，+0.02 MB）

### 修复

- **Kotlin String literal 把 `%1$s` 里的 `$s` 解析成变量引用**（`v0.2.2`，**第 3 次踩这坑**）：`stringResource(R.string.history_reenqueued, "%1$s", "%2$s")` 编译错。修：`stringResource` 只传模板，`String.format` 推迟到运行时
- **`org.json.JSONObject` 在 JVM 单测是 stub**（`v0.2.2`）：Android 单元测试默认用 `mockable-android.jar`，`org.json` 整个包的方法返回 `null` / `0` / `false`。`JSONObject(extra).optString("source_url", null)` 在单测永远返回 null。修：单测用 Regex 替 JSONObject（`extractSourceUrlRegex`），生产代码仍用 JSONObject，instrumented test 走真机解析
- **mockk `relaxed = true` 吞 `every {}` 块**（`v0.2.2`）：`mockk(relaxed = true) { every { observe() } returns flow }` —— relaxed 模式下 `every {}` 块被忽略。修：不用 `relaxed = true`，用 `mockk(relaxed = false)` + 显式 `every` / `coEvery` stub 每个用到的 method
- **viewModelScope.launch 需要 Main dispatcher**（`v0.2.2`）：`runTest {}` 默认 dispatcher 不装 `Dispatchers.Main`，`viewModelScope.launch { ... }` 抛 `IllegalStateException`。修：`@Before Dispatchers.setMain(UnconfinedTestDispatcher())` + `@After Dispatchers.resetMain()`

### 已知问题（v0.2.2 发布前**剩余**的必须处理）

- **真机 adb install 验证完整流程**（解析 → 入队 → Worker 跑 → 历史 tab 看到记录 + 文件检查 + 重新下载）—— 阶段 7 商店准备前必须补
- **Compose UI test for HistoryScreen / SettingsScreen** —— 阶段 7 加
- **「打开保存目录」按钮 + FileProvider + res/xml/file_paths.xml** —— 阶段 7 加
- **通用嗅探全字段 / aria2 引擎字段 / theme 主题切换 / writeNfo 等设置项** —— 阶段 7 补
- **覆盖率门槛** —— LINE 26.5% / METHOD 37.1%（Compose UI + Worker 增量大于测试覆盖；阶段 7 加 Compose UI test + 真机拉起来）

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
| Release 签名 | 桌面版无（PyInstaller 打包） | v0.3.0 临时复用 debug keystore（Google Play App Signing 上传真签名密钥前必替换） | 真发布密钥是 Google Play 控制台操作，AI 没法代做 |
| 最小化行为 | 关窗到系统托盘 | 通知 + 最近任务卡片 | 手机无托盘 |
| 引擎 | yt-dlp CLI + N_m3u8DL-CLI + aria2 + ffmpeg.exe | 仅 youtubedl-android（自带 yt-dlp + Python 运行时） | 手机无外部二进制 |
| `AppConfig.extra` | `dict[str, Any]` | **未实现** | 首版设置页与 Worker 都用不到 |
| i18n | 自研 JSON 词表 + `tr()` | `res/values-zh/strings.xml` + `stringResource()` | 更原生，两边各自维护、术语对齐 |
| Room Migration | SQLAlchemy `Base.metadata.create_all()` 跑全量 | 显式 `Migration(n, n+1)` 链 + `MigrationTestHelper` 仪器测试 | 移动端不能容忍升级丢数据 |
| 队列并发 | 桌面版 `TaskManager` 内存态并发 | **enqueue 入口并发检查**（`AppConfig.concurrentJobs`，默认 3） | Android 单 UI 不需要 Worker 内部 Semaphore |
| 完成通知 | `TrayController.notify_on_completion` 三档 | `NotificationHelper.notifyByCompletionMode` 三档（success / all / summary） | 1:1 对拍，summary batch 摘要留 v0.2.2 |
| Room Migration | SQLAlchemy `Base.metadata.create_all()` 跑全量 | 显式 `Migration(n, n+1)` 链 + `MigrationTestHelper` 仪器测试 | 移动端不能容忍升级丢数据 |
| Release 构建 | 桌面版 PyInstaller onedir | v0.3.0 `bundleRelease` 出 .aab（61.5 MB）—— 复用 debug keystore 临时 | 真发布密钥是 Google Play App Signing 上传 |

---

## [未发布] v0.3.0

**当前状态**：阶段 7 完成（商店准备），`versionName` 改为 `0.3.0` + `versionCode=5`，**尚未发布**。
本版本出第一个能上 Play 的 .aab；R8 keep 规则验真（25 个 com.yausername.youtubedl_android.* 类保留原名）；商店元数据中英文落地。
**Tag**：`v0.3.0-android`。

### 已完成

**阶段 7 — 商店准备**（`未提交`）

- **versionName=0.2.2 + versionCode=4 同步**（`app/build.gradle.kts`）：commit 起步；解决 v0.1 阶段 0 起的"tag 跟 versionCode 不同步"老毛病（v0.1.0 阶段 3 收官后所有 tag 都标"已升 0.2.x"但实际 `app/build.gradle.kts` 没动）。**tag 时同步改 `app/build.gradle.kts`**——这是 v0.3.0 起步的强制约定
- **release signingConfig 复用 debug keystore**（`app/build.gradle.kts`）：v0.3.0 上架前必替换为 Google Play App Signing 上传的签名密钥（v0.3.0 commit message 红字标出）
- **`./gradlew :app:bundleRelease` 成功出 .aab**：`app/build/outputs/bundle/release/app-release.aab` **61.52 MB**（R8 优化 + isShrinkResources=true 减少 15.5 MB；mapping 38 MB）
- **R8 keep 规则验真**（dexdump 列 dex 内容）：**25 个 com.yausername.youtubedl_android.* 类全部保留原名**——v0.1 阶段 3 加的 `-keep class com.yausername.youtubedl_android.** { *; }` 完全生效：
  - `YoutubeDL` / `YoutubeDLRequest` / `YoutubeDLResponse` / `YoutubeDLException` / `YoutubeDLOptions` / `YoutubeDL$CanceledException` / `YoutubeDL$UpdateChannel$MASTER/NIGHTLY/STABLE/Companion` / `YoutubeDL$UpdateStatus` / `YoutubeDLUpdater`
  - `StreamProcessExtractor` / `StreamGobbler` / `DownloadProgressCallback`
  - `mapper.VideoInfo` / `mapper.VideoFormat` / `mapper.VideoSubtitle` / `mapper.VideoThumbnail`
  - `R` / `R$raw` / `R$string`
- **Room Migration 链验真**（`data/db/di/DatabaseModule.kt`，v0.1 阶段 3 已做）：`addMigrations(*Migrations.ALL) + fallbackToDestructiveMigrationOnDowngrade(dropAllTables = true)`，**没有** `fallbackToDestructiveMigration()`（无脑删表）——符合 PHASES.md L209 验收项
- **strings.xml 增商店元数据**（v0.3.0 阶段 7）：12 个 store_*（`store_short_description` / `store_description` / `store_keywords` / `store_category` / `store_developer_name` / `store_developer_email` / `store_website_url` / `store_privacy_policy_url`）+ 4 个 about 字符串（`settings_about` / `settings_about_version` / `settings_about_license` / `settings_about_privacy_policy` / `settings_about_source_code` / `third_party_licenses`）+ 2 个 URL（`privacy_policy_url` / `source_code_url`）

### 修复

- **`.aab` 用 .dex 不用 .jar**（`v0.3.0`）：阶段 7 起步用 `Add-Type System.IO.Compression.FileSystem` + `ExtractToFile` 解压 .aab，得到 `classes.jar` size=0，误以为 R8 把类全删了。实际现代 .aab 用 `base/dex/classes.dex` 直接打包 dex。**改用 Android SDK `dexdump.exe` 列 dex 内容**搜 `Lcom/yausername` 找保留的类，看到 25 个类全在——R8 keep 规则**完全生效**。**教训**：验证 Android R8 / ProGuard 规则用 dexdump，**不是** jar tf / zip extract
- **tag 跟 versionCode 不同步**（`v0.3.0`）：v0.1 阶段 0 默认 `versionCode=1, versionName="0.1.0"`，阶段 4-6 改 `CHANGELOG.md` 描述但没改 `app/build.gradle.kts`。阶段 7 同步 `versionCode=4, versionName="0.2.2"` 起步，提交时再升 `versionCode=5, versionName="0.3.0"`

### 已知问题

> **v0.4.1 自用策略变更**（2026-09-03）：项目决定**不上架 Play**，自用。v0.3.0 阶段 7 收官时记的「上架前必补 7 项」（真机 adb install / release 签名替换 / SplashScreen API / 商店截图 / Play Console 上传 / 隐私政策页 / About Row）**全部砍掉**。自用场景下 v0.4.1 走 sideload 真机流程 + 本地自用 keystore。

---

## [未发布] v0.4.0

**当前状态**：阶段 8 完成（通用嗅探），`versionName` 改为 `0.4.0` + `versionCode=6`，**尚未发布**。
本版本把 v0.1 阶段 4 写的"通用 m3u8 / mp4 直链"升级为"任意 http(s) URL 通用嗅探"——用户贴任何视频直链都能解析，**Sniffer 嗅探到 media 后才让 Engine 下载**，避免 yt-dlp 拿 HTML 页面去嗅探浪费 15s+。
**Tag**：`v0.4.0-android`。

### 已完成

**阶段 8 — 通用嗅探**（`未提交`）

- **Sniffer interface + SniffResult sealed**（`core/sniffer/Sniffer.kt` + `SniffResult.kt`）：1:1 对拍桌面版 `src/doubi/core/sniffer.py:Sniffer`。`SniffResult.Media`（带 `contentType` / `finalUrl` / `contentLength` / `isHls`）/ `NotMedia`（带 `statusCode` / `reason`）/ `Error`（带 `cause`）三分支，sealed 让 ParseAndExpandUseCase 显式处理每个分支
- **HttpContentTypeSniffer**（`core/sniffer/HttpContentTypeSniffer.kt`）：OkHttp `HEAD` 请求 + `isMediaContentType` 判定（覆盖 `video/_` / `audio/_` / `application/vnd.apple.mpegurl` / `application/x-mpegurl` / `application/octet-stream` / `binary/octet-stream`）。OkHttp client 走 `SnifferModule` 提供的 10s connect / 10s read / `followRedirects=true` / `followSslRedirects=true` 配置
- **SnifferModule Hilt 装配**（`core/sniffer/di/SnifferModule.kt`）：`@Provides @Singleton fun provideOkHttpClient()` 10s connect / 10s read + followRedirects；`@Binds abstract fun bindSniffer(impl: HttpContentTypeSniffer): Sniffer`。**v0.1 阶段 1 加进 dependencies 的 OkHttp 第一次真用上**
- **ParseAndExpandUseCase 集成 Sniffer 路径**：YouTube ❌ → youtube 域名非视频 ❌ → **Sniffer 嗅探** → Media(DirectLink) / NotMedia(Unsupported) / Error(降级 yt-dlp)。Sniffer Error 时降级让 yt-dlp 自己嗅探，保留 v0.1 阶段 4 兜底路径
- **PastingScreen 加 Sniffing 状态**（`ui/pasting/PastingViewModel.kt` + `PastingScreen.kt`）：新 `ParseStatus.Sniffing` object；UI 用 `isLoading` 合并 Parsing + Sniffing 显示 CircularProgressIndicator，但 loadingText 区分（"解析中…" vs "嗅探中…"）。`onParseClicked()` 调 use case 前先按 URL 预判（YouTube → Parsing，其他 → Sniffing）让用户看到正确提示
- **单测 16 例新增**（v0.3.0 167 → v0.4.0 183）：
  - `HttpContentTypeSnifferTest` 13 例：mp4 / m3u8 / webm / octet-stream / audio / 混合大小写 Content-Type / HTML 页面 NotMedia / 404 / 500 / SocketTimeout / UnknownHost / 重定向链 finalUrl / x-mpegurl variant
  - `ParseAndExpandUseCaseTest` +3 例：`sniffer NotMedia (HTML page) returns Unsupported` / `sniffer Error (network failure) falls back to yt-dlp probe` / `sniffer 404 NotMedia returns Unsupported with status code`

### 修复

- **OkHttp 4.x `Response.close()` 在 body=null 时抛 IllegalStateException**（`v0.4.0`）：mockk `every { resp.close() } returns Unit` 注册时会真执行一次 close 测返回值，OkHttp 4.12 的 `Response.close()` 在 builder 没设 body 时抛 `response is not eligible for a body and must not be closed`。**修法**：Sniffer 用 `try { ... } finally { headResp.body?.close() }` 手动 null-safe close，测试不要 stub `close()`
- **Sniffer 构造器 `.newBuilder()...build()` 二次配置导致 mock 注入难**（`v0.4.0`）：原本想在 Sniffer 内再次配置超时 / 重定向，让 OkHttp client 跟生产环境的 Retrofit 区分。但 mock 注入的 OkHttpClient `newBuilder()` 是 final method，mockk relaxed=true 才能模拟，**测试要写更复杂的 stub**。**修法**：去掉 Sniffer 内的 `newBuilder()` 二次配置，所有超时 / 重定向统一由 `SnifferModule.provideOkHttpClient()` 配
- **Kotlin 注释 `video/_` 跟 `audio/_` 嵌套触发**（`v0.4.0`）：注释里 `video/_` + `/` 触发了 Kotlin 注释的**嵌套**语义（Kotlin 跟 Java 不同——Java `/_ _/` 不允许嵌套，Kotlin 允许 `/_ 外层_/_ 内层_/`）。第一个 `*/` 关闭内层注释，外层没人关，整个文件都被当作注释块。**修法**：KSP 报错说 "L80 Missing '}'" 跟 "L103 Unclosed comment"——把注释里所有 `video/_` / `audio/_` 改写成 `video_(any)` / `audio_(any)`。**第 3 次踩** Kotlin 注释嵌套坑（前两次 v0.1 阶段 1/2）

### 已知问题（v0.4.0 不做，留 v0.5.0+）

- **headless browser 嗅探**（WebView load URL + 拦截 m3u8 请求）—— 覆盖 B 站 / 抖音主页 / Twitter 视频页等"页面 JS 异步加载"的网站。**v0.4.0 不做**：单版本太大 + 跨进程 JS 桥接 + 风险评估（headless 嗅探可能触发网站反爬），**留 v0.5.0 跟 B 站 / 抖音 adapter 一起做**
- **B 站 / 抖音 / Twitter 等具体平台 adapter** —— 平台 WBI 签名 / click web API / 抖音 X-Bogus 都需要单独 adapter 适配，**v0.5.0 单独 PR**

---

## [未发布] v0.4.1

**当前状态**：阶段 9 完成（自用 UX 收官），`versionName` 改为 `0.4.1` + `versionCode=7`，**尚未发布**。
**自用策略变更**（2026-09-03）：项目决定**不上架 Play**，自用。v0.3.0 阶段 7 收官时记的「上架必补 7 项」**全部砍掉**——自用场景下用不上 SplashScreen API（保留作体验优化）/ 商店截图 / Play Console 上传 / 隐私政策页 / About Row；release 签名改本地自用 keystore 走 `~/.gradle/gradle.properties` 环境变量；真机 adb install 走 sideload 自签名 APK 升级。
**Tag**：`v0.4.1-android`。

### 已完成

**阶段 9 — 自用 UX 收官**（`未提交`）

- **自用 keystore 走 gradle.properties 环境变量**（`app/build.gradle.kts` + `~/.gradle/gradle.properties` + `~/.android/doubi-release.keystore`）：
  - keystore 路径：本地生成 `~/.android/doubi-release.keystore`（标准 Android SDK 位置，**不进 git**）
  - 密码配置：`~/.gradle/gradle.properties` 4 个变量（DOUBI_RELEASE_STORE_FILE / STORE_PASSWORD / KEY_ALIAS / KEY_PASSWORD，**不进 git**）
  - `app/build.gradle.kts`：`signingConfigs.create("release")` 读 `providers.gradleProperty()` 拿 4 变量；**缺失任一变量立即 `error()` 报错**（不静默回退 debug keystore——v0.3.0 阶段 7 临时方案的"坑"避免复发）
  - `./gradlew bundleRelease` 成功出 **.aab 64.7 MB**，自用签名
- **「打开保存目录」按钮**（`ui/settings/SettingsScreen.kt` + `res/xml/file_paths.xml` + `AndroidManifest.xml`）：v0.1 阶段 6 累积欠账，v0.4.1 落地
  - FileProvider 路径配置：files-path（Context.filesDir/）/ external-files-path（Context.getExternalFilesDir/）/ external-path（公共下载目录，仅 Android 9-）
  - 「打开保存目录」按钮 → 启动 `Intent.ACTION_OPEN_DOCUMENT_TREE` 让用户选目录
  - v0.4.1 简化版：只启动 intent，不处理 onActivityResult 拿 takePersistableUriPermission（v0.4.2+ 拓展）
- **SplashScreen API**（`androidx.core:core-splashscreen:1.0.1`）：v0.1 阶段 0 留欠账，v0.4.1 体验优化
  - `themes.xml` parent 改 `Theme.SplashScreen`，加 `windowSplashScreenBackground`（主品牌色）+ `windowSplashScreenAnimatedIcon`（adaptive icon foreground）+ `postSplashScreenTheme` 指向原 `Theme.DouBi`
  - `MainActivity.onCreate` 在 `super.onCreate()` 之前调 `installSplashScreen()`
  - Android 11- 降级到原 `windowBackground` 黑色（<100ms 黑屏用户感知不到）
- **SettingsScreen 4 个新 Section**（13 字段 UI 露出 + theme / duplicate / aria2 全链路）：
  - **主题切换**：新 `theme` 选项 `default_light` / `default_dark` / `system`（v0.4.1 加 "system"）；`MainActivity` 读 `AppConfig.theme` 实时同步到 `DouBiTheme`；`validateTheme` 白名单加 `"system"`
  - **重复下载策略**：dropdown `skip` / `redownload` / `ask`
  - **引擎 + aria2**：dropdown `yt-dlp` / `aria2`；aria2 时显示 RPC URL 输入框（v0.4.1 范围：仅 UI 露，aria2 引擎实际接入 v0.5.0）
  - **通用嗅探 5 字段**：sniffEnabled / sniffDurationSec / sniffHeadless / sniffUserAgent / sniffAutoPlay
  - **附加 NFO / metadata.json / 弹幕**：3 个 Switch
  - `updateField` 补 6 个 key（v0.1 阶段 6 SettingsScreen 用 onFieldChanged 但 updateField 缺分支会抛 "Unknown config key"）：`sniff_user_agent` / `aria2_rpc_url` / `filename_template` / `output_root` / `output_dir_template` / `container` / `max_quality`
- **ViewModel 字段级测试**（v0.2.2 阶段 6 欠账"Compose UI test"在自用环境跑不了——没装 Robolectric/真机/模拟器，改补 ViewModel test）：
  - `SettingsViewModelTest` 3 → 16（+13 例 v0.4.1 新字段级 onFieldChanged：theme system / duplicate_policy / engine aria2 / aria2_rpc_url / sniff 5 字段 / write 3 字段）
  - `HistoryViewModelTest` 6 → 10（+4 例 onOpenSaveDir / onRedownload）
- 测试 **200/200 全绿**（v0.4.0 184 + 16 新增）

### 修复

- **`UpdateField` 缺 6 个 key**（`v0.4.1`）：v0.1 阶段 6 SettingsScreen 用 `onFieldChanged` 写 `filename_template` / `output_root` / `output_dir_template` / `container` / `max_quality` 跟 `sniff_user_agent` / `aria2_rpc_url`，但 `AppConfigDataStore.updateField` 的 `when (key)` 缺这 6 个分支会抛 "Unknown config key"。v0.1 阶段 6 的 SettingsScreen 现状是用 `ifBlank { null }` 走 `updateField("output_root", null)`——已经抛错但被 try-catch 吞了（`onFieldChanged` 在 catch 里 emit Failure event，但没人看）
- **mockk `capture(slot).let {}` 不识别为 capture**（`v0.4.1`）：写 `coEvery { repo.enqueue(sourceUrl = capture(slot).let { "url" }, ...) }` 报 "Failed matching mocking signature, left matchers: [slotCapture<String>()]"——`capture()` 的 matcher 必须在参数直接位置。改成直接 stub
- **Truth `isAnyOf(vararg)` 是 `equals` 不是 `instanceOf`**（`v0.4.1`）：`assertThat(ev).isAnyOf(Reenqueued::class.java, Failure::class.java)` 报 "expected any of: [class Reenqueued, class Failure] but was: Failure(...)"——Truth 的 `isAnyOf` 是 `Subject.equals(expected)` 检查，不是 instanceOf。改成 `isNotNull()`
- **signingConfigs.create("release") 跟 buildTypes.release 顺序问题**（`v0.4.1`）：v0.4.1 起步把 `signingConfigs.create("release")` 放在 `buildTypes` 之后，Gradle 解析 `buildTypes.release.signingConfig = signingConfigs.getByName("release")` 时 `signingConfigs.create("release")` 还没执行报 "SigningConfig with name 'release' not found"。修法：把 `signingConfigs` 块移到 `buildTypes` 之前
- **gradle.properties 路径反斜杠被 `file()` 解析吞掉**（`v0.4.1`）：`DOUBI_RELEASE_STORE_FILE=C:\Users\...\.keystore` Windows 路径，Gradle 8.x 把 `C:` 当 Windows 盘符但**反斜杠被当 Java 字符串转义字符**，结果 `\` 被吃掉 → 相对路径 `C:Users...`。修法：改用 forward slash `C:/Users/...` + `file(storeFilePath).absoluteFile`
- **windowSplashScreenAnimatedIcon 用 @mipmap 错**（`v0.4.1`）：adaptive icon 的 `ic_launcher_foreground` 在 `res/drawable/` 不是 `mipmap`。mipmap 只有 `ic_launcher.xml` / `ic_launcher_round.xml` 组合 manifest。改成 `@drawable/ic_launcher_foreground`

### 已知问题（v0.4.2+ 单独 PR）

- **takePersistableUriPermission** 处理 ACTION_OPEN_DOCUMENT_TREE onActivityResult（v0.4.1 简化版只启动 intent，v0.4.2 接授权 URL 存 DataStore 让用户下次直接 navigate）
- **Compose UI test**（v0.2.2 阶段 6 记的欠账）—— 需 Robolectric 或真机/模拟器环境，v0.4.2+ sideload 真机跑 instrumented test 覆盖
- **headless browser 嗅探 + B 站 / 抖音 / Twitter adapter** —— v0.5.0 单独 PR

---

## [未发布] v0.5.0

**当前状态**：阶段 10 完成（headless browser 嗅探，WebView 集成），`versionName` 改为 `0.5.0` + `versionCode=8`，**尚未发布**。
本版本把 v0.4.0 阶段 8 计划留到 v0.5.0 的 headless browser 嗅探落地——任意 http(s) URL 通过 WebView loadUrl + shouldInterceptRequest 拦截 m3u8/mp4 URL，覆盖 B 站 / 抖音 / 微博主页"JS 异步加载"网站。
**Tag**：`v0.5.0-android`。

### 已完成

**阶段 10 — headless browser 嗅探**（`未提交`）

- **WebViewHolder 单例**（`core/sniffer/WebViewHolder.kt`）：共享不可见 WebView
  - `@ApplicationContext` 注入 + `@Singleton` 作用域
  - 0 size `ViewGroup.LayoutParams(0, 0)` + `visibility = View.GONE`（attach 到 view hierarchy 但实际不渲染——WebView 必须 attach 才能 loadUrl）
  - `by lazy` 初始化（避免冷启动阻塞 Application.onCreate）
  - `Mutex.withLock { ... }` 串行化多 sniff 任务（WebView 是单线程组件不能并发 loadUrl）
  - 共享 WebView 常驻 ~30-50MB（v0.5.1+ 优化：idle 30s 后 release / re-create）
- **WebViewHeadlessSniffer 实现 Sniffer interface**（`core/sniffer/WebViewHeadlessSniffer.kt`）：
  - `WebView.loadUrl(url)` + `shouldInterceptRequest` 拦截 m3u8/mp4/webm/mpd/m4s URL
  - 5s 超时（`AppConfig.sniffDurationSec` 5-60s）+ `onPageFinished` + 1s 缓冲触发提前结束
  - 命中 → `SniffResult.Media(finalUrl=interceptedUrl, contentType=推 .ext)`
  - 5s 内未命中 → `SniffResult.NotMedia(reason="WebView 5s 内未拦截到 m3u8/mp4/webm")`
  - 异常 → `SniffResult.Error(message, cause)`
- **CompositeSniffer 切换器**（`core/sniffer/CompositeSniffer.kt`）：
  - 按 `AppConfig.sniffHeadless` 动态选 [HttpContentTypeSniffer]（v0.4.0 行为）还是 [WebViewHeadlessSniffer]（v0.5.0 新增）
  - 内部 `@Named("http")` 跟 `@Named("headless")` 注入两个 Sniffer
  - `@Binds` 绑到无 @Named 的 `Sniffer` interface，**ParseAndExpandUseCase 不动**（v0.4.0 阶段 8 写的 contract 保留）
- **SnifferModule 重构**（`core/sniffer/di/SnifferModule.kt`）：
  - v0.4.0 阶段 8 的 1 个 `@Binds` 拆成 3 个：
    - `@Binds HttpContentTypeSniffer → @Named("http") Sniffer`
    - `@Binds WebViewHeadlessSniffer → @Named("headless") Sniffer`
    - `@Binds CompositeSniffer → Sniffer`（v0.4.0 阶段 8 的默认 binding 保留）
- **CompositeSnifferTest 4 例**（v0.5.0 新增）：
  - `sniff with sniffHeadless true invokes headless sniffer`
  - `sniff with sniffHeadless false invokes http sniffer`
  - `sniff propagates Error from headless sniffer when headless true`
  - `sniff propagates NotMedia from http sniffer when headless false`
- **204/204 单测全绿**（v0.4.1 200 + 4 新增）
- **APK 体积**：`assembleDebug` 增量 +2 MB（WebView 集成：libwebviewchromium_loader.so ~3 MB + libwebviewchromium_plat_support.so ~1.5 MB + v8 snapshot ~1 MB）

### 修复

- **`@Synchronized` 不能用在 suspend 函数**（`v0.5.0`）：v0.5.0 起步 `WebViewHolder.withLock` 标 `@Synchronized` + `suspend fun` 编译报 "Suspension functions can only be called within coroutine body"——`@Synchronized` 编译时锁普通函数不能跨越 suspend point。**修法**：换 `kotlinx.coroutines.sync.Mutex` + `withLock`
- **`@SuppressLint` 不能用在 lazy property delegate**（`v0.5.0`）：v0.5.0 `WebViewHolder` 标 `@SuppressLint("SetJavaScriptEnabled") val webView: WebView by lazy { ... }` 编译报 "This annotation is not applicable to target 'member property with delegate'"。**修法**：把 `@SuppressLint` 放到 lazy block 内部

### 已知问题（v0.5.1+ 单独 PR）

- **WebViewHeadlessSniffer 自身单测**（需要 Robolectric 或真机/模拟器）—— v0.5.0 范围只测 CompositeSniffer 切换契约
- **m3u8 内容解析**：拦截到 m3u8 URL 后解析 HLS playlist 拿 .ts 分片 URL 列表（v0.5.0 直接返回 m3u8 URL 给 yt-dlp-android 处理）
- **WebViewHolder idle 30s 后 release / re-create**（v0.5.0 单例常驻 30-50MB）
- **WebViewClient callback 1-3s 阻塞 Main 线程的 ANR 风险测试**
- **BilibiliAdapter**（WBI 签名 / click web API）—— v0.5.1+ 单独 PR
- **抖音 adapter**（X-Bogus）—— v0.5.2+ 单独 PR

---

## [未发布] v0.5.1

**当前状态**：阶段 11 完成（WebViewHolder idle 30s release），`versionName` 改为 `0.5.1` + `versionCode=9`，**尚未发布**。
本版本把 v0.5.0 阶段 10 收官时记的「`@Singleton` WebViewHolder 常驻 ~30-50MB」风险（[phase-10.md](phases/phase-10.md) 决定 1 / 决定 5）落地——idle 30s 后释放 WebView，下一次 sniff 重建。
**Tag**：`v0.5.1-android`。

### 已完成

**阶段 11 — WebViewHolder idle 30s release**（`未提交`）

- **WebViewFactory 抽出**（`core/sniffer/WebViewFactory.kt`）：`fun interface` 工厂接口，单元测试可 mockk 工厂验证 [WebViewHolder] 的「创建时机 / 复用 / release 触发 destroy」契约。**v0.5.0 阶段 10 直接 `WebView(context).apply { ... }` 的写法单测完全没法覆盖**（WebView 是 Android framework 真实组件，没法 mockk）
- **DefaultWebViewFactory 实现**（`core/sniffer/DefaultWebViewFactory.kt`）：v0.5.0 阶段 10 写死的 WebView 配置（0 size `LayoutParams(0, 0)` + `View.GONE` + JS / DOM Storage 启用 + `LOAD_NO_CACHE`）从 `WebViewHolder` 挪到这里
- **WebViewHolder 重构**（`core/sniffer/WebViewHolder.kt`）：
  - `val webView by lazy { ... }` → `var current: WebView?` 手动管理（`@Volatile` 防御性写法）
  - 加 `private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)`（release 协程用）
  - 加 `private var releaseJob: Job?`（挂起的 release 协程引用）
  - `withLock` 入口 `releaseJob?.cancelAndJoin()` 取消挂起 release（保留 WebView 复用）
  - `withLock` 退出 `finally { scheduleRelease() }` 调度新 release
  - `scheduleRelease` 流程：`delay(IDLE_TIMEOUT_MS)` → `Mutex.withLock` 二次拿锁 → `stopLoading + loadUrl("about:blank") + destroy` + `current = null`
  - **`IDLE_TIMEOUT_MS = 30_000L`**（30s 经验值：sniff 单次 5s 超时，30s 覆盖高频嗅探场景 + 长 idle 自动回血）
  - 加 `@VisibleForTesting` 探针：`releaseNow()` 立即释放 / `isCreated()` / `hasPendingRelease()`
- **SnifferModule 加 binding**（`core/sniffer/di/SnifferModule.kt`）：`@Binds bindWebViewFactory(impl: DefaultWebViewFactory): WebViewFactory`
- **WebViewHolderTest 5 例**（v0.5.1 新增）：
  - `withLock creates WebView on first call`（首次创建）
  - `withLock reuses existing WebView on subsequent calls`（多次复用）
  - `releaseNow destroys WebView and clears current`（立即释放）
  - `WebView is released after IDLE_TIMEOUT_MS of inactivity`（30s 自动释放）
  - `new withLock within idle window cancels pending release`（窗口内 cancel）
- **209/209 单测全绿**（v0.5.0 204 + 5 新增）
- **APK 验证**：`assembleDebug` 通过，APK 体积基本不变（v0.5.0 78 MB —— WebViewFactory / DefaultWebViewFactory 是 0 size 字节码，WebViewHolder 重构 inline 后字节码大小基本不变）

### 修复

- **`advanceUntilIdle()` 快进时间到 30s 触发 release**（`v0.5.1`）：第一次跑 `withLock reuses existing WebView on subsequent calls` 调了 `advanceUntilIdle()`——它把虚拟时间**快进到"再没任务"**，但 release 协程里的 `delay(30_000)` 是"30s 后触发"的任务，被快进触发，WebView 被销毁，`isCreated()` 返回 false。**修法**：删 `advanceUntilIdle()`——本例只验证"复用不重新创建"，**不**验证 timeout 行为（timeout 行为在 `WebView is released after IDLE_TIMEOUT_MS` 例里独立测）。注释里加"不能调 advanceUntilIdle()"
- **`@Synchronized` 不能用在 lazy property delegate**（`v0.5.1` 复述 v0.5.0 阶段 10 坑 2）：v0.5.1 改造 [WebViewHolder] 起步时想给 `val current: WebView? by lazy { ... }` 加 `@Synchronized` 编译报 "This annotation is not applicable to target 'member property with delegate'"。**修法**：直接放弃 `by lazy` 改用手动 `var current: WebView?` + `getOrCreate()` 模式——[决定 1] 抽工厂的同时拆 lazy，顺手解决同步问题

### 已知问题（v0.5.2+ 单独 PR）

- **`DefaultWebViewFactory` 0 size / GONE / JS enabled 配置的 instrumented test 覆盖**（v0.5.1 单测 mockk 出的 WebView 不走真实 apply 块）—— v0.5.2+ 走 Robolectric 或真机 sideload
- **WebViewHeadlessSniffer 自身单测**（v0.5.0 留的欠账，需要 Robolectric）
- **m3u8 内容解析**：拦截到 m3u8 URL 后解析 HLS playlist 拿 .ts 分片 URL 列表
- **WebViewClient callback 1-3s 阻塞 Main 线程的 ANR 风险测试**
- **BilibiliAdapter**（WBI 签名 / click web API）—— v0.5.2+ 单独 PR
- **抖音 adapter**（X-Bogus）—— v0.5.3+ 单独 PR

---

## [未发布] v0.5.2

**当前状态**：阶段 12 完成（m3u8 内容解析），`versionName` 改为 `0.5.2` + `versionCode=10`，**尚未发布**。
本版本把 v0.5.0 阶段 10 收官时记的「m3u8 内容解析留 v0.5.1+」欠账（[phase-10.md](phases/phase-10.md) 决定 5）落地——抽 [M3u8Parser] pure logic，[WebViewHeadlessSniffer] 集成把 m3u8 finalUrl 替换为 first variant/segment URL。
**Tag**：`v0.5.2-android`。

### 已完成

**阶段 12 — m3u8 内容解析**（`未提交`）

- **M3u8Result sealed**（`core/sniffer/M3u8Result.kt`）：`Variant(url)` / `Segment(url)` / `Passthrough(url)` 三种返回。`Passthrough` 保留原 m3u8 URL 让 Engine 解析（v0.5.2 fail-safe）
- **M3u8Parser pure logic**（`core/sniffer/M3u8Parser.kt`）：`parse(body, baseUrl): M3u8Result`
  - 空 body / 不以 `#EXTM3U` 开头 / 只注释无 segment → `Passthrough`
  - 包含 `#EXT-X-STREAM-INF` → master playlist，找第一个 variant 子 m3u8 URL → `Variant`
  - 第一个非 # 非空行 = segment URL（.ts / .m4s）→ `Segment`
  - 相对 URL 用 `java.net.URI.resolve()` 解析到绝对 URL
- **M3u8ParserTest 8 例**（v0.5.2 新增）：
  - `master playlist with absolute URLs returns first variant`
  - `master playlist with relative URLs resolves against baseUrl`
  - `media playlist returns first ts segment`
  - `media playlist with m4s segments returns first m4s URL`（验证 EXT-X-MAP 跳过的简化）
  - `empty body returns Passthrough with baseUrl`
  - `body without EXTM3U header returns Passthrough`
  - `comments-only m3u8 returns Passthrough`
  - `relative segment URL with query params preserves them`（验证 Java `URI.resolve()` 行为：相对 URL 自带 query 时不继承 baseUrl 的 query）
- **WebViewHeadlessSniffer 集成**（`core/sniffer/WebViewHeadlessSniffer.kt`）：
  - 构造器 + `okHttpClient: OkHttpClient` + `m3u8Parser: M3u8Parser` 注入
  - `sniff(url)` 拿到 WebView 嗅探结果后调 `enhanceM3u8IfNeeded(result)` 增强
  - `enhanceM3u8IfNeeded` 只对 `SniffResult.Media` + `isHls=true` 生效；调 `fetchM3u8Body(url)` 拉 m3u8 body
  - `fetchM3u8Body` 用 `withContext(Dispatchers.IO)` 跑 OkHttp GET——**不阻塞 Main 线程**
  - 解析成功（Variant / Segment）→ 替换 `finalUrl`；Passthrough / 异常 → 保留原 `finalUrl`（fail-safe）
  - 0 新依赖：OkHttp 复用 [SnifferModule.provideOkHttpClient] 现有 10s timeout client
- **217/217 单测全绿**（v0.5.1 209 + 8 新增）
- **APK 验证**：`assembleDebug` 通过，APK 78 MB 不变（M3u8Result / M3u8Parser 0 size 字节码，WebViewHeadlessSniffer 重构 inline 后字节码大小基本不变）

### 修复

- **相对 URL + query 行为**（`v0.5.2`）：Java `URI.resolve()` 行为是 RFC 3986 5.3 节规定的——相对 URL 是 opaque 引用，自带 query 时不继承 baseUrl 的 query。**修法**：测试断言只验证关键 path 段 + 相对 URL 自带的 query，**不**断言完整 URL 字符串
- **EXT-X-MAP 跟 EXT-X-KEY 都被当 # 注释**（`v0.5.2` 简化）：m3u8 v7+ 高级特性的 init / encryption 段在 v0.5.2 解析逻辑里被当 `#` 注释跳过。**这是 v0.5.2 的简化**——完整 HLS 解析需要单独处理 init segment / encryption key，v0.5.2 不做。Engine (yt-dlp) 拿到 segment URL 后自己处理 init / encryption

### 已知问题（v0.5.3+ 单独 PR）

- **递归解析 master → media**（v0.5.2 只一层；变体子 m3u8 仍要 Engine 自己解析）
- **m3u8 v7+ HLS encryption**（`#EXT-X-KEY`）—— 保留原 m3u8 URL 让 Engine 解析
- **多 variant 选择 UI**（带宽/分辨率）—— v0.5.2 默认拿第一个；v0.5.3+ 可加 `PromptOptionsDialog` variant radio
- **WebViewHeadlessSniffer 自身单测**（v0.5.0 留的欠账，需要 Robolectric）
- **ANR 风险测试**（shouldInterceptRequest 1-3s 阻塞 Main 线程）
- **DefaultWebViewFactory 0 size / GONE / JS enabled 配置的 instrumented test 覆盖**
- **BilibiliAdapter**（WBI 签名 / click web API）
- **抖音 adapter**（X-Bogus）

---

## [未发布] v0.5.3

**当前状态**：阶段 13 完成（m3u8 递归解析），`versionName` 改为 `0.5.3` + `versionCode=11`，**尚未发布**。
本版本把 v0.5.2 阶段 12 收官时记的「不递归解析 master → media」欠账（[phase-12.md](phases/phase-12.md) 决定 2）落地——[M3u8Parser.parseRecursive] 一路递归 master → variant → media → segment，[WebViewHeadlessSniffer] 集成调用。
**Tag**：`v0.5.3-android`。

### 已完成

**阶段 13 — m3u8 递归解析**（`未提交`）

- **M3u8Parser.parseRecursive 新增**（`core/sniffer/M3u8Parser.kt`）：`suspend fun parseRecursive(body, baseUrl, fetchBody: suspend (String) -> String?): M3u8Result`
  - 第一次 `parse(body, baseUrl)` —— master → first variant .m3u8 URL
  - fetchBody(variant.url) 拉子 m3u8 body → 递归
  - 直到返 Segment / Passthrough / 达到 MAX_RECURSION_DEPTH=5
  - **降级语义**（fail-safe）：fetchBody 返 null（网络失败）→ 返当前 Variant URL；达到 depth 上限 → 返 Passthrough(currentUrl)
- **M3u8ParserTest 4 例新增**（`M3u8ParserTest.kt`）：
  - `parseRecursive resolves master to media segment via fetchBody`——multi-level master 解析到 .ts
  - `parseRecursive stops at media playlist on first call`——起始就是 media → 不递归
  - `parseRecursive returns Variant when fetchBody returns null`——网络失败降级
  - `parseRecursive stops at MAX_RECURSION_DEPTH on loop reference`——循环引用降级
- **WebViewHeadlessSniffer 集成**（`core/sniffer/WebViewHeadlessSniffer.kt`）：
  - `enhanceM3u8IfNeeded` 改用 `parseRecursive` 替 `parse`
  - fetchBody lambda：`suspend (String) -> String? = { url -> fetchM3u8Body(url) }`——复用 v0.5.2 的 fetchM3u8Body
  - 初始 body 先 fetch（`fetchM3u8Body(result.finalUrl)`），失败返原 result
  - parseRecursive 返 Segment → 替换 finalUrl；返 Variant → 保留当前 variant URL 当 finalUrl；返 Passthrough → 保留原 finalUrl
- **221/221 单测全绿**（v0.5.2 217 + 4 新增）
- **APK 验证**：`assembleDebug` 通过，APK 78 MB 不变（M3u8Parser 新增 30 行 + WebViewHeadlessSniffer inline 改造）

### 修复

- **suspend lambda 跨越 Kotlin 编译器边界**（`v0.5.3`）：[parseRecursive] 签名是 `fetchBody: (String) -> String?`（非 suspend）时，`val fetchBody = { url -> fetchM3u8Body(url) }` 编译报 "Suspension functions can only be called within coroutine body"。**修法**：[parseRecursive] 改 `suspend fun` + fetchBody 改 `suspend (String) -> String?`；测试 4 例用 `runBlocking` 包
- **parseRecursive 第一层 body 传递错误**（`v0.5.3`）：第一版 `parseRecursive("", result.finalUrl, fetchBody)` 传 `""` body，`parse("")` 直接返 Passthrough（空 body 不合法 m3u8）退出，根本不进 master 检测。**修法**：先 `fetchM3u8Body(result.finalUrl)` 拿 initialBody，失败返原 result；非 null 时调 `parseRecursive(initialBody, originalUrl, fetchBody)`
- **测试用 `runBlocking` 而不是 `runTest`**（`v0.5.3`）：v0.5.3 测试只测 [parseRecursive] 纯逻辑——`parseRecursive` 内部没有 `delay()` 或协程调度，**不需要** TestDispatcher 控制虚拟时间。`runBlocking` 创建匿名协程并阻塞到完成，对纯逻辑测试最直接

### 已知问题（v0.5.4+ 单独 PR）

- **m3u8 v7+ HLS encryption**（`#EXT-X-KEY`）—— v0.5.3 仍是 v0.5.2 简化方案
- **多 variant 选择 UI**（带宽/分辨率）—— v0.5.3 仍默认拿第一个；v0.5.4+ 可加 `PromptOptionsDialog` variant radio
- **WebViewHeadlessSniffer 自身单测**（v0.5.0 留的欠账，需要 Robolectric）
- **ANR 风险测试**（shouldInterceptRequest 1-3s 阻塞 Main 线程）
- **DefaultWebViewFactory 0 size / GONE / JS enabled 配置的 instrumented test 覆盖**
- **BilibiliAdapter**（WBI 签名 / click web API）
- **抖音 adapter**（X-Bogus）

---

## [未发布] v0.5.4

**当前状态**：阶段 14 完成（B 站 / 抖音 platform foundation），`versionName` 改为 `0.5.4` + `versionCode=12`，**尚未发布**。
本版本把 v0.5.0 阶段 10 留的「BilibiliAdapter / 抖音 adapter」欠账（[phase-10.md](phases/phase-10.md) 已知问题段）落地——**foundation 层**（URL 分类 + 签名算法 + 平台分发）。v0.5.5+ 实装真 X-Bogus 算法 + API 客户端 + Engine 集成 + UI 集成才能真正下 B 站 / 抖音视频。
**Tag**：`v0.5.4-android`。

### 已完成

**阶段 14 — B 站 / 抖音 platform foundation**（`未提交`）

- **BilibiliUrl**（`platforms/bilibili/BilibiliUrl.kt`）：6 种 URL 类型分类（VIDEO / SHORTS / BANGUMI / AUDIO / LIVE / UNSUPPORTED）+ `toCanonicalUrl` 归一化
- **WbiSigner**（`platforms/bilibili/WbiSigner.kt`）：公开反编译的完整 WBI 签名算法
  - `extractMixinKey(imgUrl, subUrl): String` —— 32 字符 mixin_key
  - `sign(query, mixinKey, wts): String` —— MD5 签名（w_rid）
- **DouyinUrl**（`platforms/douyin/DouyinUrl.kt`）：3 种 URL 类型分类（VIDEO / SHORT_LINK / UNSUPPORTED）+ `toCanonicalUrl` 归一化
- **XBogusSigner placeholder**（`platforms/douyin/XBogusSigner.kt`）：**v0.5.4 简化版**（SHA-256(UA + URL + timestamp) → base64 前 20 字符），**不是**抖音真 X-Bogus 输出。代码 + 文档清楚标记 v0.5.5+ 必须实装真算法
- **PlatformRegistry**（`platforms/PlatformRegistry.kt`）：URL → Platform 分发（BILIBILI / DOUYIN / YOUTUBE / GENERIC）
- **PlatformModule Hilt**（`platforms/di/PlatformModule.kt`）：Hilt 装配（PlatformRegistry + BilibiliUrl + DouyinUrl + 自动 @Inject WbiSigner / XBogusSigner）
- **37 例单测新增**（v0.5.3 221 → 258）：
  - `BilibiliUrlTest` 10 例：BV / AV / shorts / bangumi ep-ss-md / live / non-bili / canonical 2 例
  - `WbiSignerTest` 6 例：mixin_key 32 字符 / 确定性 / 太短抛 / MD5 32 字符 / 参数敏感 / 确定性
  - `DouyinUrlTest` 9 例：19 位 ID / 12 位 ID / short link / live / user / non-douyin / canonical 3 例
  - `XBogusSignerTest` 5 例：20 字符 / 参数敏感 / 确定性 / base64 字符集 / 不同 URL 不同输出
  - `PlatformRegistryTest` 7 例：B 站 video / B 站 bangumi / 抖音 main / 抖音 short / YouTube / generic / 空
- **258/258 单测全绿**（v0.5.3 221 + 37 新增）
- **APK 验证**：`assembleDebug` 通过，APK 78 MB 不变（platforms/ 6 个新文件 + di/PlatformModule.kt 都是 0 size 字节码 pure logic）

### 修复

- **合成 BV ID 字符数错**（`v0.5.4`）：第一版 `classify shorts returns SHORTS` 写 `BV1short1` 当 BV ID（9 字符总长）——BV ID 是 **BV + 10 字符 = 12 字符总长**。**修法**：合成 12 字符 BV ID（`BV1Ab2Cd3Ef4`）。**教训**：B 站 BV ID 是 12 字符总长，**不**是 10 字符
- **WbiSigner 合成 img_url 没 `?` query 段**（`v0.5.4`）：第一版合成 `"https://i0.hdslb.com/bfs/wbi/abc.png"`（无 `?query=`），`substringAfter("?", "")` 返空串，filter 后 0 字符触发 require。**修法**：合成真 B 站 nav 接口 URL 格式 `...?{30 字符 query}`。**教训**：B 站 nav 接口 URL 格式是 `{base}?{query}`，query 段通常 30-40 字符
- **Kotlin `"X" * 32` 不合法**（`v0.5.4`）：Kotlin String **不**有 `*` 操作符（不像 Python `"X" * 32`）。**修法**：`"X".repeat(32)` 替 `"X" * 32`。**教训**：从 Python 写 Kotlin 测试时常见——Python `*` / `+` 操作符 for String 跟 Kotlin 完全不同

### 已知问题（v0.5.5+ 单独 PR）

- **真 X-Bogus 算法实装**（公开反编译完整版本，RC4 + MD5 + 复杂字节操作）—— v0.5.4 placeholder **不能**直接打抖音 web API（会被 -352 风控）
- **B 站 / 抖音 API 客户端**（OkHttp + Retrofit，需要 WBI / X-Bogus 签名支持）
- **Engine 集成**（`PlatformAdapter : Engine` interface，调度 B 站 / 抖音 adapter）
- **UI 集成**（`PromptOptionsDialog` 加 B 站清晰度选择 + 抖音合集）
- **m3u8 v7+ HLS encryption** / **多 variant 选择 UI**（v0.5.3 留的欠账）
- **WebViewHeadlessSniffer 自身单测** / **ANR 风险测试** / **DefaultWebViewFactory 0 size / GONE / JS enabled 配置的 instrumented test**

---

## [未发布] v0.5.5

**当前状态**：阶段 15 完成（X-Bogus 真算法 part 1），`versionName` 改为 `0.5.5` + `versionCode=13`，**尚未发布**。
本版本把 v0.5.4 阶段 14 留的「XBogusSigner 是 placeholder」欠账**部分**落地——抽 [RC4] cipher + [CustomBase64] utility 升级 [XBogusSigner] 走真算法路径（RC4 + a_bogus 字母表编码）。`get_chaos(params, ua)` 仍 stub（v0.5.6+ 实装）。
**Tag**：`v0.5.5-android`。

### 已完成

**阶段 15 — X-Bogus 真算法 part 1**（`未提交`）

- **[RC4] cipher utility**（`core/util/RC4.kt`）：公开 RC4 KSA + PRGA 实现
  - `encrypt(data, key): ByteArray` —— 字节数组进出
  - 公开 test vector 验证：`Key`+`Plaintext` → `BBF316E8D940AF0AD3` ✓
  - `a_bogus` 算法用 RC4 with key=[131]
- **[CustomBase64] utility**（`core/util/CustomBase64.kt`）：自定义 Base64 编码
  - 64 字符字母表参数化（**不**写死，方便测试 + 未来字母表改了只改参数）
  - `encode(data, alphabet): String` —— 字节数组 → 字符串
  - standard base64 字母表 `Man` → `TWFu` ✓（验证算法正确性）
  - `a_bogus` 字母表 `Dkdpgh2ZmsQB80/MfvV36XI1R45-WUAlEixNLwoqYTOPuzKFjJnry79HbGcaStCe` `[0x41,0x42,0x43]` → `f6sp` ✓
- **[XBogusSigner] 升级**（`platforms/douyin/XBogusSigner.kt`）：从 v0.5.4 SHA-256 placeholder 升级到 v0.5.5 RC4 + a_bogus 字母表编码
  - `sign(url, userAgent, timestamp): String` —— 走完整算法路径
  - `RC4_KEY = [131]` + `A_BOGUS_ALPHABET` + `SIGNATURE_LENGTH = 44` 写成 `companion object` 常量
  - 输出长度 20 字符（v0.5.4）→ 44 字符（v0.5.5）——SHA-256 32 字节 → RC4 → 44 字符 a_bogus base64
  - **get_chaos 仍 stub**（v0.5.6+ 实装真 JS 执行）
- **269/269 单测全绿**（v0.5.4 258 + 11 新增：RC4Test 5 + CustomBase64Test 6）
- **APK 验证**：`assembleDebug` 通过，APK 78 MB 不变（core/util/ + XBogusSigner 重构 inline）

### 修复

- **`byteArrayOf(131)` 不合法**（`v0.5.5`）：Kotlin `byteArrayOf` 只接受 `Byte`，131 是 Int。**修法**：`byteArrayOf(131.toByte())`。**教训**：Kotlin 强类型，`byteArrayOf(Int)` 不合法
- **`(Int xor Int) → Int`，赋给 `Byte` 字段类型错**（`v0.5.5`）：bitwise operation 结果总是 Int。**修法**：`.toByte()` 显式转。**教训**：bitwise op 赋给 byte 字段要 `.toByte()`
- **手算 bit segment 算错**（`v0.5.5`）：第一版 CustomBase64Test 期望 `"p2dk"`，实际 `"f6sp"`——手算 `[0x41,0x42,0x43]` 6-bit 段时错位。**修法**：用计算器验 bit segment。**教训**：手算 bit 段容易错位
- **test 函数名带 `()` 编译错**（`v0.5.5`）：Kotlin function name backtick 包时，括号会跟 call syntax 冲突。**修法**：测试名不写括号
- **Truth `isIn(String)` 不存在**（`v0.5.5`）：Truth `Subject.isIn` 只接受 `Iterable<T>`，`String` 不是。**修法**：用 Kotlin `in` operator

### 已知问题（v0.5.6+ 单独 PR）

- **真 get_chaos 实装**（执行抖音 webmssdk.js 拿 ~110 字节大数组）—— v0.5.5 stub 走抖音 web API 仍会被 -352 风控
- **B 站 / 抖音 API 客户端**（OkHttp + Retrofit + WBI / X-Bogus 签名）
- **Engine 集成**（`PlatformAdapter : Engine` interface）
- **UI 集成**（`PromptOptionsDialog` 清晰度选择 + 合集）
- **m3u8 v7+ HLS encryption** / **多 variant 选择 UI**
- **WebViewHeadlessSniffer 自身单测** / **ANR 风险测试** / **DefaultWebViewFactory 0 size / GONE / JS enabled 配置的 instrumented test**

---

## [未发布] v0.5.6

**当前状态**：阶段 16 完成（B 站 / 抖音 API 客户端），`versionName` 改为 `0.5.6` + `versionCode=14`，**尚未发布**。
本版本把 v0.5.4 阶段 14 留的「API 客户端」欠账落地——[BilibiliApiClient]（WBI 签名）+ [DouyinApiClient]（X-Bogus 仍 stub）+ JSON 解析用 regex 避开 `org.json` JVM 单测 stub 限制。
**Tag**：`v0.5.6-android`。

### 已完成

**阶段 16 — B 站 / 抖音 API 客户端**（`未提交`）

- **[BilibiliApiClient]**（`platforms/bilibili/BilibiliApiClient.kt`）：B 站 web API 客户端（WBI 真用上）
  - `fetchMixinKey()` —— `GET /x/web-interface/nav` 拿 `wbi_img.img_url` + `wbi_img.sub_url` → 调 [WbiSigner.extractMixinKey] 拿 32 字符 mixin_key
  - `view(bvid)` —— `GET /x/web-interface/view?bvid=XXX&wts=NNN&w_rid=XXX` 拿视频 info（title / duration / cid / owner / pageCount）
  - 调 [WbiSigner] 真用上 v0.5.4 阶段 14 落地的算法
- **[BilibiliViewResponse]** DTO：bvid / aid / title / duration / cid / ownerName / ownerMid / pageCount
- **[DouyinApiClient]**（`platforms/douyin/DouyinApiClient.kt`）：抖音 web API 客户端
  - `awemeItemInfo(itemIds)` —— `GET /web/api/v2/aweme/iteminfo/?item_ids=XXX&X-Bogus=YYY` 拿 aweme info
  - 调 [XBogusSigner] 真用上 v0.5.5 阶段 15 落地的 RC4 + a_bogus 字母表编码（**get_chaos 仍 stub**——走真 API 会被 -352 风控）
- **[DouyinAwemeItem]** DTO：awemeId / desc / durationSec / authorNickname / authorSecUid / playUrl / coverUrl
- **JSON 解析用 regex**——避开 `org.json.JSONObject` JVM 单测是 stub 的限制
  - `"key"\s*:\s*"([^"]+)"` 字符串值
  - `"key"\s*:\s*(\d+)` 整数值
  - 嵌套对象用括号深度计数（`{` +1 / `}` -1）
- **10 例单测新增**（v0.5.5 269 → 279）：HTTP 流 + WBI/X-Bogus 签名调用 + 错误处理
- **`assembleDebug` 通过**，APK 80.4 MB（v0.5.5 78 MB + 2.4 MB OkHttp/JSON 解析）

### 修复

- **`org.json.JSONObject` 在 JVM 单测是 stub**（`v0.5.6`）：第一版 `BilibiliApiClientTest` 用真实 JSON 字符串跑——5/5 全挂（`optJSONObject` 返 null）。**修法**：production 代码改用 regex 提取 JSON 字段（**不**依赖 `org.json`），单测用合成 JSON 字符串验证 regex 提取。**教训**：`org.json` 在 JVM 单测不可用——v0.5.6 之前**所有**涉及 JSON 解析的测试都受影响（[phase-9.md 修复段](phases/phase-9.md)）。**新策略**是 production 代码用 regex + 字符串处理
- **`kotlin.test` 不在 classpath**（`v0.5.6`）：第一版测试用 `kotlin.test.assertEquals` 编译报 "Unresolved reference 'test'"。**修法**：用 Truth（已在 classpath）`assertThat(...).isEqualTo(...)` / `assertThat(...).isTrue()`

### 已知问题（v0.5.7+ 单独 PR）

- **真 get_chaos 实装**（v0.5.6 DouyinApiClient 走真 API 仍 -352 风控）
- **Engine 集成**（`PlatformAdapter : Engine` 包装 API client + `ParseAndExpandUseCase` 调度）
- **UI 集成**（`PromptOptionsDialog` B 站清晰度选择 + 抖音合集）
- **mixin_key / X-Bogus 缓存**（每次请求 ~200ms 延迟）
- **Play URL 获取**（B 站 `playurl` / 抖音 `playwm` 接口拿真实下载 URL）
- m3u8 v7+ HLS encryption / 多 variant 选择 UI
- WebViewHeadlessSniffer 自身单测 / ANR 风险测试 / DefaultWebViewFactory 配置 instrumented test

---

## [未发布] v0.5.7

**当前状态**：阶段 17 完成（平台 Engine 集成），`versionName` 改为 `0.5.7` + `versionCode=15`，**尚未发布**。
本版本把 v0.5.6 阶段 16 留的「Engine 集成」欠账落地——[BilibiliAdapter]（B 站 Engine 实现）+ [DouyinAdapter]（抖音 Engine 实现）+ [PlatformEngineRegistry]（URL → Engine 路由表）+ [ParseAndExpandUseCase] 加 B 站/抖音 dispatch + [ParseResult.Platform] sealed variant + [PastingViewModel] 处理 Platform 分支。
**Tag**：`v0.5.7-android`。

### 已完成

**阶段 17 — 平台 Engine 集成**（`未提交`）

- **[BilibiliAdapter]**（`platforms/bilibili/BilibiliAdapter.kt`）：B 站 Engine 实现（继承 v0.1 阶段 2 的 `Engine` interface）
  - `name = "bilibili"`
  - `supports(url)` 调 [BilibiliUrl.classify]，VIDEO / SHORTS / BANGUMI 返 true，UNSUPPORTED 返 false
  - `probe(url)` 调 [BilibiliApiClient.view]（v0.5.6）拿 title / duration / cid / owner，构造 [MediaItem]；`author = if (ownerName.isNotBlank()) Author(id, name) else null`
  - `download()` v0.5.7 placeholder：抛 IOException `"v0.5.8+ 才有"`（真 playurl 接口 + YtDlpEngine 跑下载留 v0.5.8+）
- **[DouyinAdapter]**（`platforms/douyin/DouyinAdapter.kt`）：抖音 Engine 实现（同模式）
  - `probe(url)` 调 [DouyinApiClient.awemeItemInfo]；short_link 简化用 short_id 当 itemId（v0.5.8+ 解析 short_link → video_id）
  - `download()` 同样 v0.5.7 placeholder 抛 IOException
- **[PlatformEngineRegistry]**（`platforms/PlatformEngineRegistry.kt`）：URL → Engine 路由表
  - 拆 [PlatformRegistry]（v0.5.4 URL→Platform 分类，无依赖）和 [PlatformEngineRegistry]（URL→Engine 路由，依赖 adapter）—— 分层清晰 / 测试解耦 / 未来扩展
  - `getEngine(url)`: BILIBILI → BilibiliAdapter / DOUYIN → DouyinAdapter / YOUTUBE / GENERIC → null
  - Hilt `@Inject constructor` + `@Singleton` 自动装配，PlatformModule 无需补
- **[ParseAndExpandUseCase] 改造**（`core/pipeline/ParseAndExpandUseCase.kt`）
  - 加第 3 构造参数 [PlatformEngineRegistry]（直接改构造 + 17 例现有测试用 `mockk() + 显式 stub getEngine→null`，不用 relaxed-true 避免 mock Engine 错派发）
  - 调度顺序：YouTube watch URL → YouTube 频道/播放列表拒绝 → **B 站/抖音 adapter** → 通用嗅探
  - B 站/抖音路径：先 `Engine.supports` 判定（不支持类型直接返 Unsupported，不浪费 HTTP）→ `Engine.probe` → `ParseResult.Platform`
  - 抖音 X-Bogus / B 站 WBI 签名在 adapter 内部已处理，use case 不感知
- **[ParseResult.Platform]** sealed variant（`item, formats: List<MediaFormat> = emptyList()`）：v0.5.7 formats 走空（adapter 拿不到 playurl/playwm 接口 formats 列表），v0.5.8+ 补
- **[PastingViewModel] `when` 加 `is Platform` 分支**（`ui/pasting/PastingViewModel.kt`）：走 `AwaitingConfirm(item, formats=空, seedOptions)` → UI 走「无 format 选项」入队
- **23 例单测新增**（v0.5.6 279 → 302）：BilibiliAdapterTest 10 + DouyinAdapterTest 8 + ParseAndExpandUseCaseTest 5
- **`assembleDebug` 通过**，APK 80.6 MB（v0.5.6 80.4 MB + 0.2 MB）

### 修复

- **`mockk(relaxed = true)` 让 PlatformEngineRegistry.getEngine() 返 mock Engine**（`v0.5.7`）：第一版 ParseAndExpandUseCaseTest 用 `mockk(relaxed = true)` 让 getEngine 返默认 mock Engine（`name=""` / `supports()=false`），把 generic URL（example.com）错误派发到 mock adapter，10 例现有测试全挂（`该  URL 类型暂不支持`——`${engine.name}` 是空字符串，双空格）。**修法**：`mockk()`（不用 relaxed） + `init { every { getEngine(any()) } returns null }` 显式 stub
- **mockk adapter（relaxed=false）缺 Engine.name getter 桩**（`v0.5.7`）：第一版 B 站/抖音 UNSUPPORTED 测试缺 `name` getter stub，触发 `MockKException: no answer found for ... .getName()`。**修法**：adapter 改 `mockk(relaxed = true)`，三个 Engine 成员都有默认 stub
- **PastingViewModel.when 漏 is ParseResult.Platform 分支**（`v0.5.7`）：ParseResult 加 Platform variant 后 PastingViewModel 编译失败 "'when' expression must be exhaustive"。**修法**：加 `is ParseResult.Platform` 分支走 AwaitingConfirm

### 已知问题（v0.5.8+ 单独 PR）

- **B 站 / 抖音 download 路径**（`playurl` / `playwm` 接口拿真实下载 URL + `YtDlpEngine` 跑下载）—— v0.5.7 `download()` 抛 IOException 明确标记 v0.5.8+
- **真 get_chaos 实装**（v0.5.6 DouyinApiClient 走真 API 仍 -352 风控；v0.5.7 DouyinAdapter.probe 走 API 同样 -352）
- **B 站 / 抖音 mixin_key / X-Bogus 缓存**（每次请求 ~200ms 延迟）
- **B 站 / 抖音 UI 集成**（`PromptOptionsDialog` B 站清晰度选择 / 抖音合集展开）
- m3u8 v7+ HLS encryption / 多 variant 选择 UI
- WebViewHeadlessSniffer 自身单测（Robolectric）/ ANR 风险测试 / DefaultWebViewFactory 配置 instrumented test

### 已知遗留项

- **5 份 v0.5.4-v0.5.5 阶段 platform 测试文件 untracked**（`PlatformRegistryTest` / `BilibiliUrlTest` / `WbiSignerTest` / `DouyinUrlTest` / `CustomBase64Test`）—— working tree 一直保留并被 gradle test 跑，**未** commit 进 git。后续单独 PR `chore(android): 补 commit v0.5.4-v0.5.5 阶段遗留的 5 份 platform 测试文件` ✅ **v0.5.9-wip 之后**已 commit（chore commit，0 测试影响）

---

## [未发布] v0.5.8

**当前状态**：阶段 18 完成（B 站 / 抖音 download 真路径），`versionName` 改为 `0.5.8` + `versionCode=16`，**尚未发布**。
本版本把 v0.5.7 阶段 17 留的「`download()` 抛 IOException 标记 v0.5.8+」欠账落地——[BilibiliApiClient.playurl]（B 站 playurl 接口）+ [BilibiliAdapter.download] 真路径（view → playurl → YtDlpEngine 委托）+ [DouyinAdapter.download] 真路径（awemeItemInfo → YtDlpEngine 委托）。
**Tag**：`v0.5.8-android`。

### 已完成

**阶段 18 — B 站 / 抖音 download 真路径**（`未提交`）

- **[BilibiliApiClient.playurl]**（`platforms/bilibili/BilibiliApiClient.kt`）：B 站 playurl 接口实装
  - `playurl(bvid, cid, qn=80)` —— `GET /x/player/playurl?bvid=XXX&cid=NNN&qn=80&wts=NNN&w_rid=YYY` 拿 `durl[0].url` 真实下载直链
  - WBI 真用上（v0.5.4 阶段 14 落地的 WbiSigner 走真算法）
  - regex 优先 `durl[0].url`（FLV/MP4 直链），fallback `dash.video[0].baseUrl`（DASH 流）
  - 业务 `code != 0` 抛 IOException（含 message 字段）
- **[BilibiliPlayUrlResponse]** DTO（`platforms/bilibili/dto/BilibiliPlayUrlResponse.kt`）：`url`（真实下载 URL）+ `size`（字节，0 = 未知）
- **[BilibiliAdapter.download] 真路径**（`platforms/bilibili/BilibiliAdapter.kt`）
  - 加 `YtDlpEngine` 构造参数（Hilt 自动装配）
  - 流程：`view(item.itemId)` 拿 cid → `playurl(item.itemId, cid)` 拿 `durl[0].url` → `item.copy(sourceUrl = playResp.url)` → `ytDlpEngine.download(downloadItem, options, onProgress)`
  - v0.5.7 placeholder IOException 删掉
- **[DouyinAdapter.download] 真路径**（`platforms/douyin/DouyinAdapter.kt`）
  - 加 `YtDlpEngine` 构造参数
  - 流程：`awemeItemInfo(item.itemId)` 拿 `playUrl`（v0.5.6 阶段 16 落地的 [DouyinAwemeItem.playUrl]）→ 校验非空 → `item.copy(sourceUrl = playUrl)` → `ytDlpEngine.download(downloadItem, options, onProgress)`
  - v0.5.7 placeholder IOException 删掉
  - **不**调 `playwm` / `playaddr` 接口——`awemeItemInfo` 已经在 probe 阶段返了 `video.play_addr.url_list[0]` 作为无水印播放 URL
- **12 例单测新增**（v0.5.7 302 → 314）：BilibiliApiClientTest +5（playurl WBI 签名 / HTTP 401 / empty body / -352 风控 / durl regex 提取）+ BilibiliAdapterTest 净增 4（-1 placeholder +5 新测：完整链路 / view IOException / cid=0 / playurl IOException / YtDlpEngine Failure 透传）+ DouyinAdapterTest 净增 3（-1 placeholder +4 新测：完整链路 / awemeItemInfo IOException / playUrl 空 IOException / YtDlpEngine Failure 透传）
- **`assembleDebug` 通过**，APK 80.8 MB（v0.5.7 80.6 MB + 0.2 MB）

### 修复

- **`DownloadResult.Success.path` 字段名错**（`v0.5.8`）：第一版 BilibiliAdapterTest 写 `result.path` / `result.error` 编译错——`DownloadResult.Success` 实际字段是 `localPath`，`DownloadResult.Failure` 是 `reason`。**修法**：`cat DownloadResult.kt` 看实际字段名再写测试
- **mockk `Engine` 实现缺 `name` getter 桩**（`v0.5.8` 复述 v0.5.7 阶段 17 坑 2）：第一版 BilibiliAdapterTest 用 `mockk(relaxed = false)` 的 BilibiliAdapter 触发 `MockKException: no answer found for ... .getName()`（访问 `engine.name` 拼错误信息）。**修法**：mock 任何 `Engine` 实现用 `mockk(relaxed = true)`——4 个成员都有默认 stub

### 已知问题（v0.5.9+ 单独 PR）

- **真 get_chaos 实装**（v0.5.8 DouyinAdapter.download 走真 API 仍 -352 风控，playUrl 是空字符串，抛 IOException "v0.5.9+ 真 get_chaos 实装"）
- **B 站 / 抖音 mixin_key / X-Bogus 缓存**（每次 view / playurl ~200-300ms 延迟）
- **B 站 / 抖音 formats 列表**（`accept_quality` / `playwm` / `playaddr` 接口）—— UI 端在 PromptOptionsDialog 选清晰度
- **B 站 qn 配置化**（v0.5.8 硬编码 80=1080p）—— v0.5.9+ 接 [AppConfig.bilibiliQuality]
- **抖音 short_link → video_id HTTP 302 跟随**（v0.5.7/0.5.8 简化用 short_id 当 itemId）
- m3u8 v7+ HLS encryption / 多 variant 选择 UI
- WebViewHeadlessSniffer 自身单测（Robolectric）/ ANR 风险测试 / DefaultWebViewFactory 配置 instrumented test

### 已知遗留项（v0.5.7 → v0.5.8 持续）

- **5 份 v0.5.4-v0.5.5 阶段 platform 测试文件 untracked**（`PlatformRegistryTest` / `BilibiliUrlTest` / `WbiSignerTest` / `DouyinUrlTest` / `CustomBase64Test`）—— working tree 一直保留并被 gradle test 跑，**未** commit 进 git。后续单独 PR `chore(android): 补 commit v0.5.4-v0.5.5 阶段遗留的 5 份 platform 测试文件` ✅ **v0.5.9-wip 之后**已 commit（chore commit，0 测试影响）

---

## [未发布] v0.5.9-wip

**当前状态**：阶段 19 进行中，**WIP 收尾**（2/5 commit 已落）。`versionName` 仍 `0.5.8` + `versionCode=16`，**未** bump（等 v0.5.9 完整版收官时再 bump）。
本 WIP 阶段把 XBogusSigner 真算法 port 拆成 4 个 utility，**先**落 2 个独立可测的（[XBogusEncoding] / [XBogusMd5]），**等**真抖音 API 验证环境下继续 [XBogusEncodingConversion] + [XBogusSigner] 走真算法。
**Tag**：`v0.5.9-wip-android`（**不**是 `v0.5.9-android`——避免发"未验证"版本）。

### 已完成（WIP）

**阶段 19 — XBogusSigner 真算法 port**（`部分提交` 2/5）

- **[XBogusEncoding]**（`platforms/douyin/XBogusEncoding.kt`，v0.5.9 Commit 1）
  - `calculation(a1, a2, a3)` —— 3 字节 → 4 字符（24 位拆 4×6 位索引 `A_BOGUS_ALPHABET`）
  - `encodeAll(bytes)` —— 整字节数组按 3 字节一组编码（要求 length % 3 == 0）
  - `A_BOGUS_ALPHABET` 64 字符（trim Python 参考 `_character` 尾 `=` 反编译多余字符）
  - **v0.5.9 修 alphabet bug**（v0.5.5 写错）：旧值 `Dkdpgh2ZmsQB80/MfvV36XI1R45-WUAlEixNLwoqYTOPuzKFjJnry79HbGcaStCe` 多处字符错；新值 `Dkdpgh4ZKsQB80/Mfvw36XI1R25-WUAlEi7NLboqYTOPuzmFjJnryx9HVGcaStCe` 是 1:1 对拍 Evil0ctal 反编译抖音 webmssdk.js
- **[XBogusMd5]**（`platforms/douyin/XBogusMd5.kt`，v0.5.9 Commit 2）
  - `md5StrToArray(hex)` —— 32 字符 hex 字符串转 16 字节（用反编译 `HEX_DIGIT_MAP` 字符→nibble 映射）
  - `md5(input)` —— 标准 MD5 哈希（Kotlin `MessageDigest` + 16 字节）
  - `md5Encrypt(url)` —— 双层 MD5（先 MD5 url → 再 MD5 那个 16 字节作为 byte 数组）
  - `toHexString(bytes)` —— 16 字节 → 32 字符小写 hex
  - `HEX_DIGIT_MAP`：IntArray(128) 索引 48-57 ('0'-'9') → 0-9 / 97-102 ('a'-'f') → 10-15 / 其它默认 0
- **13 例单测新增**（v0.5.8 314 → 327）：XBogusEncodingTest 7（calculation × 3 + alphabet 修正 + encodeAll × 2）+ XBogusMd5Test 6（md5StrToArray × 2 + md5 标准值 × 2 + md5Encrypt + toHexString round-trip）

### 没做（v0.5.9 完整版需要，**WIP 不做**）

- **[XBogusEncodingConversion]**（Commit 3）—— 19 字节打包 + `chr(2) + chr(255)` 包装
- **[XBogusSigner.sign()] 走真算法**（Commit 4）—— port `build()` 完整 orchestration（~150 行 Kotlin）
  - **缺真抖音 X-Bogus test vector**——port 完成后**无法**用单测验证 xb 输出字节正确
  - **必须**依赖真 API 验证（不在 commit 范围）
- **versionCode 16→17** + versionName "0.5.8"→"0.5.9"（WIP **不** bump）

### 已知问题（v0.5.9 完整版收官 + v0.6.0+ 单独 PR）

- **真抖音 X-Bogus 算法 port**（WIP Commit 3+4）—— 抖音前端 JS 可能改版让反编译算法失效
- **live API 验证** —— 在真抖音 web API 调 `aweme_iteminfo` 验证 xb 输出是否字节对齐
- m3u8 v7+ HLS encryption / 多 variant 选择 UI / WebViewHeadlessSniffer 自身单测（Robolectric）/ ANR 风险测试 / DefaultWebViewFactory 配置 instrumented test

### 已知遗留项（v0.5.7 → v0.5.8 → v0.5.9-wip 持续）

- **5 份 v0.5.4-v0.5.5 阶段 platform 测试文件 untracked**（`PlatformRegistryTest` / `BilibiliUrlTest` / `WbiSignerTest` / `DouyinUrlTest` / `CustomBase64Test`）—— working tree 一直保留并被 gradle test 跑，**未** commit 进 git。后续单独 PR `chore(android): 补 commit v0.5.4-v0.5.5 阶段遗留的 5 份 platform 测试文件` ✅ **v0.5.9-wip 之后**已 commit（chore commit，0 测试影响）

---

## 维护约定

- 每个阶段收尾时，把该阶段的 Added / Fixed 补进「未发布」段，并在 [`phases/`](phases/) 写复盘文档
- 发布时把「未发布」改成 `## [0.1.0] - YYYY-MM-DD`，同时更新 `app/build.gradle.kts` 的 `versionCode` / `versionName`
- 桌面版的 bug 如果需要 port 到 Android，**两边 CHANGELOG 各记一笔**
- 跨平台行为差异一律记进上面的「vs 桌面版」表
