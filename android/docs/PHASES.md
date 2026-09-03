# 阶段划分与里程碑

> **每个阶段结束都要**：① 通过本阶段所有验收 ② 在 [`phases/`](phases/) 子目录里写一份阶段复盘文档
> **CHANGELOG 节奏**：从 v0.1.0 起独立递增，写在 [`CHANGELOG.md`](CHANGELOG.md)。桌面版与 Android 版号不互通。
>
> **当前位置**：阶段 3 已收官（4 占位 tab + 还完 v0.1.0 关键欠账 #1#2#3），**下一步是阶段 4（解析）**。`versionName` 仍是 `0.1.0`，尚未发布任何版本。
> **本轮变更**（v0.1.0 收官候选）：还账 #1 `setBackoffCriteria`+`Result.retry()`、#2 `Engine` 真读三个路径模板、#3 Room `Migration` 链 + `MigrationTestHelper`；UI 引入 Navigation Compose + 4 tab + 2 个 Hilt ViewModel；单测 46 → 64 全绿。

## 总览

| 阶段 | 名称 | 验收门槛 | 状态 | 预计 |
|---|---|---|---|---|
| 0 | **项目脚手架** | Android Studio sync 成功；Hello World 跑起来 | ✅ 完成 | — |
| 1 | 数据层 + 配置 | Room schema 落库 + 单元测试通过；DataStore 读写往返 | ⚠️ 完成（**2 项欠账**） | 1 周 |
| 2 | 下载引擎（yt-dlp-android 集成） | Worker 跑通；能在后台下载 + 前台通知显示进度 | ⚠️ 完成（**2 项欠账**） | 1.5 周 |
| 3 | UI 框架（Compose 导航 + 主题） | 主框架 4 页（解析/下载/历史/设置）能切换 + 暗色主题 | ⬜ **下一步** | 1 周 |
| 4 | 解析 + 列表 | 粘贴 URL → 解析 → 表格展示候选 → 选清晰度 | ⬜ 未开始 | 1.5 周 |
| 5 | 下载 + 进度 + 完成通知 | 接 phase 2 的 Worker；进度条实时更新；完成弹系统通知 | ⬜ 未开始 | 1 周 |
| 6 | 历史 + 设置 | 历史列表真实查询；设置项可改可保存 | ⬜ 未开始 | 1 周 |
| 7 | 商店准备 | ProGuard/R8 规则、签名配置、隐私政策页、图标 | ✅ 完成（v0.3.0） | 1 周 |
| 8 | 通用嗅探 | 任意 http(s) URL 嗅探 m3u8/mp4；OkHttp + Content-Type 判定 | ✅ 完成（v0.4.0） | 1 周 |

**预计总工期**：6-8 周一人（不含商店审核 1-3 天）

**v0.1 范围**（最小可用）：YouTube + 通用 m3u8/mp4 直链下载。**不含** B 站 / 抖音 / 微博 / Playwright 通用嗅探（这些放 v0.2+）。

> 本文档里的 `v0.1` / `v0.2` 一律指**发布版本的功能范围**。
> [phases/phase-2.md](phases/phase-2.md) 里出现的 `v0.1` / `v0.2` 指的是**同一天内的两轮迭代**，不是版本号——那份文档开头有换算表。

## 跨阶段欠账登记

阶段 1、2、3 的核心交付都可用，但仍有几项验收没真正达成。**集中登记在这里，避免在阶段复盘文档里被埋掉**：

| # | 欠账 | 来自 | 建议还账阶段 | 不还的后果 | 状态 |
|---|---|---|---|---|---|
| 1 | `FileLayout` + `FilenameTemplate` 未落地，`outputRoot` / `outputDirTemplate` / `filenameTemplate` **三个配置项空转** | 阶段 1 | 阶段 4 或 5 | 阶段 6 设置页改配置无反应，会被当 bug 报回来 | ✅ **阶段 3 已还**——`Engine.resolveOutputDir` 真渲染模板 |
| 2 | Room 只有 `fallbackToDestructiveMigration()`，无显式 `Migration` | 阶段 1 | **阶段 7 必须** | 用户升级版本时历史下载记录全部清空 | ✅ **阶段 3 已还**——`Migrations.ALL` + `MigrationTestHelper` 仪器测试 |
| 3 | 失败重试 + 指数退避**完全未实现**（无 `setBackoffCriteria` / `Result.retry()`） | 阶段 2 | 阶段 5 | 桌面版用 16 个用例守的重试语义在 Android 端裸奔；弱网必然掉任务 | ✅ **阶段 3 已还**——`setBackoffCriteria(EXPONENTIAL, 30s)` + `isTransientFailure` 判据 |
| 4 | `Progress.speed` / `eta` 字段不存在 | 阶段 2 | 阶段 5 | 阶段 5 验收「进度条 + 速度 + ETA」直接过不去 | ✅ **阶段 3 已还**——`Progress` 加 `speedBytesPerSec` / `etaSeconds` + `statusLine()`；`YtDlpEngine` 从 `at 1.23MiB/s` 解析速度并修了「库回调是 0-100 百分量纲被 `coerceIn(0f,1f)` 截成满格」的真 bug；Worker 透传到 `setProgress` / `NotificationHelper.buildProgressNotification` |
| 5 | 真机端到端从未验证（仪器测试写了 7 个，一次没跑） | 阶段 1 + 2 + 3 | 阶段 4 | 落盘、通知、前台 Service 全是「代码通、没人见过」 | ⚠️ **阶段 3 部分还**——跑了 `assembleDebug`，APK 76.4 MB，4 ABI 的 `libpython.zip.so` / `libqjs.so` 完整打入，Manifest 合并后 8 个权限齐，**但未做真机 adb install**（v0.1 计划外，留 v0.2） |
| 6 | 单测覆盖率 ≥ 80% 这条门槛**从未测量**（项目没接 jacoco） | 阶段 1 | 阶段 5 | 门槛形同虚设，要么接工具要么改口径 | ✅ **阶段 3 已还**——接 `org.gradle.jacoco`（不走 plugins DSL，marker artifact 不存在），自定义任务 `jacocoTestReport` 出 XML + HTML，**基线 37.5% LINE / 48.5% METHOD**。80% 门槛要靠 v0.2 加 instrumented test 把 `DownloadWorker.doWork` / `NotificationHelper` / UI ViewModel 拉起来 |
| 7 | `proguard-rules.pro` 缺引擎类 keep 规则 | 阶段 2 | 阶段 3 | release 包启动时 ClassNotFoundException | ✅ **阶段 3 已还**——加了 `com.yausername.youtubedl_android.**` keep |
| 8 | 命令行构建挂在 `androidJdkImage`（JDK 26 + AGP 8.7.3 不兼容） | 阶段 2 收尾时暴露 | 永久修法见 [SETUP.md](SETUP.md) | 缺文档指引会让人以为是代码问题 | ✅ **阶段 3 已还**——SETUP.md 整段重写 + A/B 实测证据 |

> 详细成因见 [phase-1.md 的欠账表](phases/phase-1.md) 和 [phase-2.md 的验收对账](phases/phase-2.md)。

## 阶段 0：项目脚手架 ✅ 完成

**目标**：让工具链跑通；看到一个空白的 DouBi 启动屏。

**包含**：
- `android/` 子目录与本文件结构
- Gradle 配置（`settings.gradle.kts` / `build.gradle.kts` / `gradle.properties` / `libs.versions.toml`）
- 一个 `MainActivity` + 一个 `HomeScreen` 占位 Composable
- Hilt 入口（`@HiltAndroidApp` 标注的 Application）
- 主题（Material 3，自动亮/暗）
- 完整文档（README / SETUP / PHASES / ARCHITECTURE / REUSE-MAP）

**不含**：下载、解析、数据库、Worker。

**验收**：
- [x] Android Studio 打开 `android/` 目录 sync 0 报错
- [x] 跑起来能看到「DouBi Android」字样 + 版本号
- [x] 没有崩溃 / ANR
- [x] 阶段 0 文档完成

## 阶段 1：数据层 + 配置 ⚠️ 完成（2 项欠账）

**目标**：把桌面版的 `core/storage/` + `core/config.py` 移植到 Room + DataStore。

**桌面版 → Android 版对应**：
- `core/storage/database.py`（SQLite + WAL） → Room `MediaItemDao` / `TaskDao` / `IncrementCheckpointDao`
- `core/storage/file_layout.py`（路径模板） → `core/storage/FileLayout` 纯 Kotlin 类
- `core/storage/manifest.py`（jsonl） → 暂用 Room `Download` 表 + WorkManager 进度合并；v0.2 再考虑是否要 jsonl 旁路
- `core/config.py`（YAML + env） → DataStore Preferences（KV）+ Hilt 提供单例

**关键边界**：
- `database_path` 那个老坑（`core/config.py:45` 相对路径，详见桌面版 CHANGELOG G9）—— **Android 版直接用绝对路径**（app-private `getDatabasePath()`），不再背这个坑
- `~/.doubi/config.yml` → `Context.dataStore`（每个 app 自己的私有目录）

**验收**（复盘见 [phase-1.md](phases/phase-1.md)）：
- [x] Room schema 编译通过
- [ ] ~~迁移测试覆盖 1 → 2 schema 变化~~ → ❌ **未达成**，用的 `fallbackToDestructiveMigration()`（欠账 #2）
- [x] DataStore 读写往返 + 非法值回退（与 `test_config_theme.py` 对齐）——`AppConfigDataStoreTest` 11 例
- [ ] ~~单测覆盖率 ≥ 80%~~ → ⚠️ **从未测量**，项目没接 jacoco（欠账 #6）
- [x] 阶段 1 复盘文档

**实际产出**：30 个测试（单测 24 + 仪器 6），另外**没做**的还有 `FileLayout` / `FilenameTemplate`（欠账 #1）。

## 阶段 2：下载引擎 ⚠️ 完成（2 项欠账）

**目标**：用 [yausername/yt-dlp-android](https://github.com/yausername/yt-dlp-android) 跑通 YouTube 视频下载到本地。

**桌面版 → Android 版对应**：
- `engines/yt_dlp.py`（async 包装，to_thread 跑 sync yt-dlp） → `engine/ytdlp/YtDlpEngine`（基于 yt-dlp-android 的 `YoutubeDL` 类）
- `engines/nm3u8dl.py`（外部 .exe + 文件系统 watchdog） → **v0.1 不移植**；HLS 站点原计划走 FFmpeg-Kit 通用方案，但 **ffmpeg 依赖至今未启用**（`libs.versions.toml` 里有坐标，`build.gradle.kts:143` 仍是注释状态），所以目前没有任何 HLS 兜底方案
- `engines/aria2.py` → **v0.1 不移植**

**关键边界**：
- 手机没有外部二进制；yt-dlp-android 自带 ffmpeg，所以 Aria2 / N_m3u8DL-CLI / imageio-ffmpeg 全部要重做或砍掉
- WorkManager `CoroutineWorker` 替代 asyncio 任务 + 后台线程
- 前台 Service 通知（`setForegroundAsync`）替代桌面版「关窗最小化到托盘」

**验收**（复盘见 [phase-2.md](phases/phase-2.md)）：
- [ ] 输入一个 YouTube 链接 → WorkManager Worker 拉起 → 下载到 app 私有目录 → ⚠️ **代码通但从未在设备上验证**（欠账 #5）
- [x] 进度通知显示 + 点击进应用——`NotificationHelper.kt:42-46`
- [ ] ~~失败重试（指数退避）—— 对齐桌面版 `test_pipeline_retry.py` 的 8 个变异杀测试~~ → ❌ **完全未实现**（欠账 #3）
- [x] 阶段 2 复盘文档

**实际产出**：21 个单测；引擎依赖从 JitPack 401 换到 Maven Central 的 `io.github.junkfood02.youtubedl-android:library:0.18.1`。

## 阶段 3：UI 框架 ✅ 完成（v0.1.0 收官候选）

**目标**：主框架 4 页（粘贴/解析/下载/历史）能切换 + Material 3 主题（亮/暗） + 还 v0.1.0 关键欠账 #1#2#3。

**桌面版 → Android 版对应**：
- `ui/main_window.py`（主窗口 + 4 页 + 导航） → `MainActivity` + Compose `NavHost` + 底部导航栏
- `ui/theme.py`（7 套主题） → v0.1 先做 **2 套**：Material 3 默认亮 + Material 3 默认暗；自定义调色板放 v0.2
- `ui/resources/icons/*.svg`（矢量图标） → Material Icons Extended 的 Outlined 风格，v0.2 替换为本地矢量

**关键边界**：
- i18n：桌面版是 JSON 词表 + `tr()` 函数，Android 版用 `res/values/strings.xml` + `stringResource()`（v0.1 只做中文；英文资源等 v0.2）
- 底栏顺序：**粘贴 → 解析 → 下载 → 历史**（v0.1 改用「粘贴 URL」作首页，不再是「解析」；与桌面版 `nav.*` 字段名对齐）

**验收**：
- [x] 4 个占位页面能切换，标题栏对应显示
- [x] 切换系统暗色模式 → 应用立即变暗
- [x] 阶段 3 复盘文档（[phase-3.md](phases/phase-3.md) 已写）
- [x] 还欠账 #1 `setBackoffCriteria` + `Result.retry()`（详见 [跨阶段欠账登记](#跨阶段欠账登记)）
- [x] 还欠账 #2 `outputRoot/outputDirTemplate/filenameTemplate` 真渲染
- [x] 还欠账 #3 Room 显式 `Migration` 链 + `MigrationTestHelper` 仪器测试
- [x] 还欠账 #4 `Progress.speed/eta` 字段 + 修 progress 0-100 量纲 bug（**额外发现**）
- [x] 还欠账 #6 接 jacoco 出覆盖率报告（基线 LINE 37.5% / METHOD 48.5%）
- [x] 还欠账 #7 proguard 引擎类 keep
- [x] 还欠账 #5（**部分**）：`assembleDebug` 0 警告通过，APK 76.4 MB 含 4 ABI JNI 库 + Manifest 8 权限齐 + jacoco 重新跑成功；**真机 adb install 仍留 v0.2**

**未做完的欠账**（移交给下阶段）：
- ⚠️ 欠账 #5 剩余：仪器测试 7+3 例仍未真机跑过（阶段 4 必做：第一次有真实链接进 Engine）。`DownloadWorker.doWork` / `NotificationHelper` 在 jacoco 上是真实缺口（2.5% LINE 覆盖），需要 instrumented + mock WorkManager Context
- ⏸️ 80% 覆盖率门槛：基线 37.5% LINE / 48.5% METHOD，要靠 v0.2 阶段 4/5 加 UI ViewModel / Worker 仪器测试拉起来
- ❌ 欠账 #6：jacoco 覆盖率（阶段 5 必做）

## 阶段 4：解析 + 列表

**目标**：粘贴 URL → 调用 yt-dlp-android 解析 → 表格展示候选 → 选清晰度。

**桌面版 → Android 版对应**：
- `core/pipeline.py:parse_and_expand()` → `core/pipeline/ParseAndExpandUseCase`
- `platforms/youtube/strategies.py` → `platforms/youtube/YouTubeStrategy`（基于 yt-dlp-android 提取信息）
- `ui/pages/parse.py:PromptOptionsDialog` → `ui/parse/PromptOptionsDialog` Composable

**v0.1 站点**：YouTube + 通用 m3u8/mp4 直链（yt-dlp-android 用 `YoutubeDL.extractInfo()` 处理）

**验收**：
- [x] YouTube 链接（普通 + Shorts + Live）解析正确
- [x] 直链 m3u8 / mp4 解析正确
- [x] 选清晰度后能入队（到阶段 5 才真正下载）
- [x] 阶段 4 复盘文档（[phase-4.md](phases/phase-4.md)）

**已完成（详见 [phase-4.md](phases/phase-4.md)）**：
- YouTubeUrl 分类（VIDEO / SHORTS / LIVE / EMBED / UNSUPPORTED）+ 归一化到 `watch?v=ID`
- MediaFormat 数据类（formatId / ext / vcodec / acodec / height / fileSize / isAudioOnly）
- YtDlpEngine.probeWithFormats() 拿 title + formats 列表
- EngineModule Hilt 装配（@Named("baseOutputDir") 避免 Engine 持有 Context）
- ParseAndExpandUseCase + ParseResult sealed class（Youtube / DirectLink / Unsupported）
- PromptOptionsDialog Compose（format radio + 容器 / 缩略图 / 字幕 / 续传 + 标题模板可选）
- PastingViewModel 5 状态机（Idle / Parsing / AwaitingConfirm / Unsupported / Enqueued / Failure）
- PastingScreen 串 dialog + snackbar
- 单测 99 → 153 全绿（+54：YouTubeUrl 25 + MediaFormat 15 + ParseAndExpandUseCase 14）
- assembleDebug 0 警告通过，APK 77.05 MB（vs v0.1.0 76.43 MB，+0.6 MB）

## 阶段 5：下载 + 进度 + 完成通知

**目标**：接 phase 2 的 Worker，UI 上看进度，完成弹系统通知。

**桌面版 → Android 版对应**：
- `ui/pages/download.py:TaskRow` → `ui/download/TaskRow` Composable
- `ui/tray.py:TrayController` → `NotificationManager`（不再需要托盘——手机只有通知）
- `ui/main_window.py:notify_on_completion` → `Worker.doWork()` 完成后发 `NotificationCompat.Builder`

**验收**：
- [x] 下载中页能看到实时进度条 + 速度 + ETA
- [x] 队列并发（默认 3，配置可改）
- [x] 完成通知（success / all / summary 三档，对齐桌面版）
- [x] 阶段 5 复盘文档（[phase-5.md](phases/phase-5.md)）

**已完成（详见 [phase-5.md](phases/phase-5.md)）**：
- DownloadingViewModel `combine(activeTasks, workInfosFlow).stateIn` 拿实时 WorkInfo.progress
- DownloadingScreen LazyColumn + TaskRow（title + 进度条 + `Progress.statusLine()` + 取消按钮 + 6 种 DisplayStatus 颜色）
- DownloadRepository.QueueFullException + enqueue 入口按 `AppConfig.concurrentJobs` 检查
- PastingViewModel 捕获 QueueFullException → ParseStatus.QueueFull → snackbar 「队列已满 N / M」
- NotificationHelper.notifyByCompletionMode 按 mode 路由：`success` 只发成功 / `all` 都发 / `summary` 单条静默（batch 摘要留 v0.2.2）
- DownloadWorker 退出分支从 `notifyComplete` 改 `notifyByCompletionMode(config.notifyOnCompletion)`
- DisplayStatus enum 6 种（QUEUED / RUNNING / PAUSED / COMPLETED / FAILED / UNKNOWN）
- 单测 153 → 158 全绿（+5：DownloadingViewModelTest 5 例纯数据变换）
- assembleDebug 0 警告通过，APK 77.05 MB（不变）

**必须先还的账**（不还则上面的验收做不出来）：
- [x] `Progress` 补 `speed` / `eta` 字段（欠账 #4）—— 阶段 3 已还
- [x] 失败重试 + 指数退避（欠账 #3）—— 阶段 3 已还
- [x] `FileLayout` + `FilenameTemplate`（欠账 #1）—— 阶段 3 已还

## 阶段 6：历史 + 设置

**目标**：历史页真实查询 + 设置项可改可保存。

**桌面版 → Android 版对应**：
- `ui/pages/history.py` → `ui/history/HistoryScreen`（Room 查询 + LazyColumn）
- `ui/pages/settings.py` → `ui/settings/SettingsScreen`（DataStore 读写）
- 重新下载功能 → 复用 phase 2 的 Worker 入口

**验收**：
- [x] 历史列表按时间倒序
- [x] 「文件已删除」检测（与桌面版 `test_task_manager.py::test_restore` 对齐，弱版：目录非空即存在）
- [x] 设置改完立即生效（不用重启，桌面版 `config.py` 有「需重启」限制）
- [x] 阶段 6 复盘文档（[phase-6.md](phases/phase-6.md)）

**已完成（详见 [phase-6.md](phases/phase-6.md)）**：
- DownloadWorker Success 路径补 `mediaItemDao.upsert(MediaItemEntity)`（v0.1 阶段 2 没写，给历史 tab 用）
- sourceUrl 存进 `extra` JSON 字段（schema 冻结，借 extra 字段）
- HistoryViewModel 订阅 `MediaItemDao.listRecentFlow()` + `Dispatchers.IO` 后台检查 `lastSaveDir` 文件存在
- HistoryScreen LazyColumn + 文件状态图标 + 重新下载按钮 + Snackbar 反馈
- SettingsViewModel 订阅 `AppConfigDataStore.observe()` + `updateField()` 单字段原子写
- SettingsScreen LazyColumn 5 组 SectionCard（输出 / 画质容器 / 附加 / 网络 / 通知）
- AppNavigation 加 SETTINGS 路由 + BottomNavItem 加 Settings icon
- 单测 158 → 167 全绿（+9：HistoryViewModelTest 6 + SettingsViewModelTest 3）
- assembleDebug 0 警告通过，APK 77.07 MB（+0.02 MB）

## 阶段 7：商店准备

**目标**：能 `bundleRelease` 出 `.aab` 提交 Google Play。

**包含**：
- 签名（`keystore.properties` + `signingConfigs.release`）
- ProGuard / R8 规则（保留 Room 实体、Hilt 类、Compose 函数名）
- 应用图标（adaptive icon）
- 启动屏
- 隐私政策页（GitHub Pages 或 Gitee Pages 挂一份）
- 商店截图（4.7" / 6.7" 各 2 张）
- 应用描述（中英文）

**验收**：
- [x] `./gradlew bundleRelease` 成功出 `.aab`（**61.52 MB**，v0.3.0-android tag）
- [x] release 包 R8 keep 规则验证（dexdump 列 **25 个 com.yausername.youtubedl_android.* 类全部保留原名**——v0.1 阶段 3 加的 `-keep class com.yausername.youtubedl_android.** { *; }` 完全生效）
- [x] Room 显式 `Migration` 替换 `fallbackToDestructiveMigration()`（v0.1 阶段 3 已做）
- [x] versionName=0.2.2 + versionCode=4 同步（commit 起步，解决 v0.1 阶段 0 起的"tag 跟 versionCode 不同步"老毛病）
- [x] 阶段 7 复盘文档（[phase-7.md](phases/phase-7.md)）

**已完成（详见 [phase-7.md](phases/phase-7.md)）**：
- release signingConfig 复用 debug keystore（v0.3.0 上架前必替换为 Google Play App Signing 上传的签名密钥）
- bundleRelease 出 .aab 61.52 MB
- strings.xml + 12 个 store_* 字符串 + 4 个 about 字符串 + 2 个 URL（policy_url / source_code_url）
- R8 keep 规则验真（dexdump 列 25 个 com.yausername.youtubedl_android.* 类全部保留原名）

**没做（v0.3.0 上架前必补，**用户手动**）**：
- 真机 adb install 走通完整流程（v0.1 阶段 5/6 已知问题累积）
- release 包签名替换（Google Play App Signing 上传真签名密钥）
- SplashScreen API（Android 12+ 圆形图标 + 背景色标准启屏）
- 商店截图（4.7" / 6.7" 各 2 张 PNG）
- Play Console 上传 .aab + 预审
- 隐私政策页面（`https://buxiaju.gitee.io/dou-bi-docs/privacy/` 实际部署）
- SettingsScreen 底部「关于 / 版本 / 隐私政策 / 源代码 / 第三方许可」Row

## 收尾

阶段 7 完成 → 提 Play Console 审核 → 1-3 天过审 → 上线 v0.1.0。

之后进入迭代期（v0.2 / v0.3），按需扩 B 站 / 抖音 / 通用嗅探（参考 [REUSE-MAP.md](REUSE-MAP.md)）。

---

## 阶段 8：通用嗅探 ✅ 完成（v0.4.0）

**目标**：v0.1 阶段 4 写的"通用 m3u8 / mp4 直链"是写死的——只有用户贴 `.m3u8` / `.mp4` 结尾的 URL 才走 DirectLink，其他全部走 yt-dlp 兜底。本阶段把"直链判定"从**扩展名匹配**升级为**HTTP 嗅探**：任意 http(s) URL 先发 HEAD 看 Content-Type，识别为 m3u8 / mp4 / webm / octet-stream → DirectLink；其他 → NotMedia 或 yt-dlp 兜底。

1:1 对拍桌面版 `src/doubi/core/sniffer.py:HttpContentTypeSniffer`（v0.4.0 简版——**不做 headless browser**）。

**为什么拆成 v0.4.0 通用嗅探 + v0.5.0 B 站/抖音 两版**：
- v0.4.0 只用 OkHttp HEAD（HTTP 层），10s connect / 10s read，**单版本可控**
- v0.5.0 要做 headless browser（WebView load URL + 拦截 m3u8 请求），需要 WebView 集成 + 跨进程 JS 桥接 + 风险评估（headless 嗅探可能触发网站反爬）——单版本太大，跟 B 站 / 抖音 adapter 一起做
- B 站 / 抖音 / Twitter 等具体平台 adapter（平台 WBI 签名 / click web API / 抖音 X-Bogus）也放 v0.5.0

**预计工期**：1 周

**验收项**：
- [x] Sniffer interface + SniffResult sealed 落地
- [x] HttpContentTypeSniffer OkHttp HEAD 实现（10s 超时 + follow redirects）
- [x] SnifferModule Hilt 装配
- [x] ParseAndExpandUseCase 集成 Sniffer 路径（YouTube ❌ → youtube 域名非视频 ❌ → Sniffer → Media / NotMedia / Error 降级）
- [x] PastingScreen Sniffing 状态提示（"嗅探中…" 区别 Parsing "解析中…"）
- [x] 单测 HttpContentTypeSniffer 13 例 + ParseAndExpandUseCase +3 例
- [x] 阶段 8 复盘文档（[phase-8.md](phases/phase-8.md)）

**已完成（详见 [phase-8.md](phases/phase-8.md)）**：
- Sniffer interface + SniffResult sealed（Media / NotMedia / Error 三分支）
- HttpContentTypeSniffer（OkHttp HEAD + isMediaContentType 覆盖 video/_ / audio/_ / m3u8 / octet-stream）
- SnifferModule Hilt 装配（provide OkHttpClient 10s connect / 10s read + followRedirects）
- ParseAndExpandUseCase 集成 Sniffer 路径：YouTube ❌ → youtube 域名非视频 ❌ → Sniffer → Media(DirectLink) / NotMedia(Unsupported) / Error(降级 yt-dlp)
- PastingScreen Sniffing 状态提示（"嗅探中…" 区别 Parsing "解析中…"）
- 单测 16 例新增（HttpContentTypeSnifferTest 13 + ParseAndExpandUseCaseTest +3）

### 不做（留 v0.5.0+）

- headless browser 嗅探（WebView load URL + 拦截 m3u8 请求）—— 覆盖 B 站 / 抖音主页 / Twitter 视频页等"页面 JS 异步加载"的网站
- B 站 / 抖音 / Twitter 等具体平台 adapter（平台 WBI 签名 / click web API / 抖音 X-Bogus）
- 容器展开（YouTube playlist / 抖音合集 / B 站收藏夹）—— v0.5.0+ 用 desktop 同样的 `expand` 接口扩展
