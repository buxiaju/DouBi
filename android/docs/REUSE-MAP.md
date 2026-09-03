# 桌面版 → Android 版 一对一映射

> **活文档**，随阶段推进更新。**状态列口径**（2026-09-02 按实际代码核对）：
> ✅ 已落地 ｜ 🟡 部分落地 ｜ ❌ 未落地 ｜ ⏸️ 明确不做

## 规则

- **业务算法照搬**（URL 分类、JSON 解析、文件名渲染、正则）—— Kotlin 重写但**保留字段名**（snake_case 改 camelCase，但**业务意义不变**）
- **配置 schema 字段名照搬**（`database` / `manifest_path` / `filename_template` 等）—— 便于跨平台对照文档
- **i18n 字符串**重写为 `strings.xml`，**翻译**人工对齐（开 PR 时附对照表）
- **测试用例的断言**逐条翻译为 Kotlin（JUnit 4 + Truth + MockK），不增减
- **落点路径以本表为准**：本表写的落点如果和实际代码不一致，说明其中一边错了——**改到一致再往下做**，别留着两个名字

> ⚠️ **单测框架订正**：早期文档写「JUnit 5 + MockK」，实际项目用的是 **JUnit 4 + Truth**
> （Jupiter 与 AS 的 JUnit 模板冲突，会报 "No junit.jar"，见 [phase-1.md](phases/phase-1.md) 坑记录）。
> [ARCHITECTURE.md](ARCHITECTURE.md) 的技术栈表也已同步订正。

## 完整映射表

### `core/`

| 桌面版文件 | 行数 | Android 版落点 | 计划阶段 | 状态 |
|---|---|---|---|---|
| `core/models.py` | ~200 | `core/model/MediaItem.kt` / `DownloadOptions.kt` / `DownloadResult.kt` / `Progress.kt` / `Platform.kt` / `MediaType.kt` / `Author.kt` | 1 | ✅ 阶段 3 补齐（欠账 #4 已还）—— `Progress` 加 `speedBytesPerSec` / `etaSeconds` 字段 + `statusLine()` / `formatSpeed()` / `formatEta()`，并修了「progress 回调是 0-100 百分比」的量纲 bug（之前会被 `coerceIn(0f, 1f)` 截成满格）。**还顺带发现并修了一个旧 bug**：原 YtDlpEngine 把 `progress / 100` 漏写 |
| `core/pipeline.py` | ~600 | `core/pipeline/ParseAndExpandUseCase.kt` / `DownloadUseCase.kt` / `DownloadPipeline.kt` | 1, 2, 4 | ⚠️ **阶段 4 部分还 + 阶段 8 升级**——`ParseAndExpandUseCase` 落地（解析 + 选 format + 弹 PromptOptionsDialog 入队）；v0.4.0 集成 Sniffer 路径（YouTube ❌ → youtube 域名非视频 ❌ → Sniffer → Media / NotMedia / Error 降级 yt-dlp）。`DownloadUseCase` / `DownloadPipeline` / `PipelineRegistry` 留 v0.2+ 阶段 5/6 |
| `core/sniffer.py` | ~250 | `core/sniffer/Sniffer.kt` + `SniffResult.kt` + `HttpContentTypeSniffer.kt` + `core/sniffer/di/SnifferModule.kt` | 8 | ✅ **阶段 8 落地**——`HttpContentTypeSniffer` OkHttp HEAD 实现（10s connect / 10s read + followRedirects）；`isMediaContentType` 覆盖 `video/_` / `audio/_` / `application/vnd.apple.mpegurl` / `application/x-mpegurl` / `application/octet-stream` / `binary/octet-stream`。**v0.4.0 不做 headless browser**（v0.5.0 单独 PR） |
| `core/naming.py` | ~150 | `engine/ytdlp/YtDlpEngine.sanitizeFilename()` + `renderTemplate()` + `renderPathTemplate()` | 1 | ✅ 阶段 3 落地（合并到 Engine，不再单列 `core/naming/`）—— `{title}` / `{item_id}` / `{platform}` / `{author}` / `{media_type}` 全支持，author 为空降级 `_`，9 个非法字符全替 `_` |
| `core/registry.py` | ~50 | `core/pipeline/PipelineRegistry.kt` | 1 | ❌ 未落地，阶段 4 策略分发前必须补 |
| `platforms/youtube/url.py` | ~80 | `core/platform/youtube/YouTubeUrl.kt` | 4 | ✅ 阶段 4 落地——`classify_youtube_url` 1:1 对拍 VIDEO / SHORTS / LIVE / EMBED / UNSUPPORTED；`to_watch_url` 归一化到 `https://www.youtube.com/watch?v=ID` |
| `platforms/youtube/adapter.py` | ~180 | `engine/ytdlp/YtDlpEngine.probeWithFormats()` + 内部 `VideoFormat.toMediaFormatOrNull()` | 4 | ✅ 阶段 4 落地——`extract_info` 拿 title / duration / uploader，YouTubeUrl 分类后的 watch URL 喂给 yt-dlp-android，formats 列表转成 `MediaFormat` 列表 |
| `core/config.py` | ~300 | `core/config/AppConfig.kt` + `core/config/ConfigValidator.kt` + `data/config/AppConfigDataStore.kt` + `data/config/ConfigKeys.kt` | 1 | ✅ 30 字段全落地，校验比桌面版更严 |
| `core/logger.py` | ~50 | Timber（直接用第三方） | 1 | ✅ `DouBiApplication` 里初始化 |
| `core/storage/database.py` | ~400 | `data/db/DouBiDatabase.kt` + `data/db/entity/*.kt` + `data/db/dao/*.kt` | 1 | ✅ 4 entity + 4 DAO 全落地 |
| `core/storage/file_layout.py` | ~100 | `engine/ytdlp/YtDlpEngine.resolveOutputDir()`（合并到 Engine） | 1 | ✅ 阶段 3 落地（欠账 #1 已还）—— `baseOutputDir/outputRoot/<dirTemplate>` 三层结构 |
| `core/storage/manifest.py` | ~150 | v0.1 用 Room 替代；v0.2 再考虑 jsonl 旁路 | 1 | ⏸️ 按计划用 Room 替代 |
| `core/storage/migrate.py` | ~200 | v0.1 不做（旧库迁移用不上） | 延后 | ⏸️ 不做 |

> **落点路径订正**：原表把配置的 DataStore 落点写成 `data/datastore/AppConfigSerializer.kt`，
> 实际代码是 `data/config/AppConfigDataStore.kt`（外加 `data/config/ConfigKeys.kt` 和 `data/config/di/DataStoreModule.kt`）。
> 项目里**没有** `data/datastore/` 目录，也没有 `AppConfigSerializer` 这个类——上表已改成实际路径。

### `engines/`

| 桌面版文件 | 行数 | Android 版落点 | 计划阶段 | 状态 |
|---|---|---|---|---|
| `engines/__init__.py:Engine` ABC | ~30 | `engine/Engine.kt` interface | 1 | ✅ 阶段 2 落地，4 个成员 1:1 对齐 |
| `engines/yt_dlp.py` | ~250 | `engine/ytdlp/YtDlpEngine.kt` | 2 | ✅ 真实现（`io.github.junkfood02.youtubedl-android:library:0.18.1`）。落盘路径硬编，未用模板 |
| `engines/nm3u8dl.py` | ~350 | **v0.1 不移植**；HLS 原计划走 FFmpeg-Kit | 3+ | ❌ **ffmpeg 依赖也没开**（`build.gradle.kts:143` 注释状态）→ 目前无任何 HLS 兜底 |
| `engines/aria2.py` | ~200 | **v0.1 不移植** | 延后 | ⏸️ 不做（但 `ConfigValidator` 的 engine 白名单里留了 `aria2`） |
| `engines/m3u8dl_fallback.py` | ~100 | 合并到 FFmpeg-Kit 通用方案 | 3+ | ❌ 同 nm3u8dl |

### `platforms/`

| 桌面版文件 | 行数 | Android 版落点 | 计划阶段 | 状态 |
|---|---|---|---|---|
| `platforms/youtube/`（含 `api` / `url` / `strategies`） | ~500 | `platforms/youtube/YouTubeStrategy.kt` + `YouTubeUrlClassifier.kt` | 4 | ❌ **`platforms/` 目录整个不存在**。当前 YouTube 识别只有 `YtDlpEngine.supports()` 里的 URL 判断 |
| `platforms/bilibili/`（含 `api` / `auth` / `strategies` / `url` / `wbi` / `qr_login`） | ~1500 | v0.2+ | v0.2 | ⏸️ 首版不做 |
| `platforms/douyin/`（含 `api` / `auth` / `strategies` / `url` / `live`） | ~1200 | v0.2+ | v0.2 | ⏸️ 首版不做 |
| `platforms/generic/`（Playwright 嗅探） | ~800 | v0.4+ 评估 playwright-android；v0.1 用直链嗅探 | 延后 | ⏸️ 首版不做 |

### `ui/`

| 桌面版文件 | 行数 | Android 版落点 | 计划阶段 | 状态 |
|---|---|---|---|---|
| `ui/app.py` | ~50 | `DouBiApplication.kt` | 0 | ✅ 含 Hilt + WorkManager `Configuration.Provider` + Timber + `YoutubeDL.init` |
| `ui/main_window.py` | ~300 | `MainActivity.kt` + `ui/home/HomeScreen.kt`（Compose NavHost） | 3 | 🟡 两个文件都存在但**是占位**，NavHost / 底部导航未做 |
| `ui/workers.py` | ~200 | `data/repository/DownloadRepository.kt` + WorkManager | 1, 2 | ✅ 阶段 2 落地 |
| `ui/pages/parse.py` | ~1000 | `ui/parse/ParseScreen.kt` + `ParseViewModel.kt` | 4 | ✅ 阶段 4 落地（`PastingScreen` + `PromptOptionsDialog` + `ParseAndExpandUseCase`，名字差异：Android 用 Pasting 不用 Parse） |
| `ui/pages/download.py` | ~600 | `ui/downloading/DownloadingScreen.kt` + `DownloadingViewModel.kt` | 5 | ✅ 阶段 5 落地——`LazyColumn` 渲染 `TaskRow`（title / 进度条 / `Progress.statusLine()` / 取消按钮 / 6 种 `DisplayStatus` 颜色） |
| `ui/pages/history.py` | ~300 | `ui/history/HistoryScreen.kt` + `HistoryViewModel.kt` | 6 | ✅ 阶段 6 落地——`LazyColumn` 渲染 `MediaItemEntity`（按 `last_download_time DESC`）+ 文件存在性检查（弱版：目录非空即存在）+ 重新下载 |
| `ui/pages/settings.py` | ~400 | `ui/settings/SettingsScreen.kt` + `SettingsViewModel.kt` | 6 | ✅ 阶段 6 落地——`LazyColumn` 5 组 `SectionCard`（输出 / 画质容器 / 附加 / 网络 / 通知），DataStore reactive 改完立即生效（vs 桌面版需重启） |
| `ui/task_manager.py` | ~400 | `data/repository/DownloadRepository.kt`（融合 Download + TaskManager） | 1, 5 | 🟡 入队 / 状态写库 / 取消 / 队列并发 3 已有，**任务管理**（暂停 / 恢复 / 重下）未做 |
| `ui/tray.py:TrayController.notify_on_completion` | ~50 | `download/NotificationHelper.notifyByCompletionMode` | 5 | ✅ 阶段 5 落地——三档路由（success / all / summary），cancelled 不发通知 |
| `core/storage/database.py:Database.record_download` | ~30 | `download/DownloadWorker` Success 路径调 `mediaItemDao.upsert(MediaItemEntity)` | 6 | ✅ 阶段 6 落地——sourceUrl 存进 `extra` JSON 字段（schema 冻结，借 extra 字段） |
| 桌面版 `[project]` 段（name / version / authors） | `pyproject.toml` ~50 | `app/build.gradle.kts` `defaultConfig.versionCode/versionName` | 7 | ✅ 阶段 7 落地——v0.3.0 同步 `versionCode=5 + versionName="0.3.0"`，commit 起步强制约定（v0.1 阶段 0 起的"tag 跟 versionCode 不同步"老毛病修了） |
| 桌面版无（PyInstaller 打包） | — | `app/build.gradle.kts` `buildTypes.release.signingConfig = signingConfigs.getByName("debug")`（v0.3.0 临时） | 7 | 🟡 阶段 7 部分——复用 debug keystore 让 `bundleRelease` 跑通，**v0.3.0 上架前必替换**为 Google Play App Signing 上传的签名密钥 |
| 桌面版 PyInstaller spec | — | `./gradlew :app:bundleRelease` 出 .aab（61.5 MB）+ R8 keep 规则（25 个 com.yausername.* 类保留原名） | 7 | ✅ 阶段 7 落地——`app-release.aab` 准备上 Play |
| `ui/auth_actions.py` | ~300 | v0.2+（账号登录放 v0.2 起） | v0.2 | ⏸️ 首版不做 |
| `ui/dialogs/login_dialog.py` | ~200 | v0.2+ | v0.2 | ⏸️ 首版不做 |
| `ui/dialogs/prompt_options_dialog.py` | ~250 | `ui/parse/PromptOptionsDialog.kt` | 4 | ❌ 未落地 |
| `ui/theme.py` | ~500 | `ui/theme/{Color,Type,Theme}.kt` | 3 | 🟡 三个文件已建（阶段 0），首版按 2 套主题；亮/暗切换待阶段 3 验证 |
| `ui/resources/icons/*.svg` | ~30 个 | `res/drawable/` | 0, 3 | 🟡 目前只有 `ic_launcher_foreground.xml`，业务图标未导入 |
| `ui/locales/zh_CN.json` | ~200 条 | `res/values-zh/strings.xml` | 3, 6 | 🟡 文件已建，词条随页面增补 |
| `ui/locales/en.json` | ~200 条 | `res/values/strings.xml` | 3, 6 | 🟡 同上 |

> **落点路径订正**：原表把 `ui/workers.py` 和 `ui/task_manager.py` 的落点都写成 `data/repository/TaskRepository.kt`，
> 实际类名是 **`DownloadRepository.kt`**，项目里没有 `TaskRepository`。上表已改成实际类名。

### `tests/`

| 桌面版文件 | 用例数 | Android 版落点 | 实际进度 |
|---|---|---|---|
| `tests/test_pipeline_smoke.py` | 28 | 阶段 1、4 落地 | ❌ 0（`core/pipeline/` 还不存在） |
| `tests/test_pipeline_retry.py` | 16 | 阶段 2 + 3 落地 | ✅ 13（`DownloadWorkerTest` 13 例 `isTransientFailure` 判据）—— 欠账 #3 阶段 3 已还 |
| `tests/test_bilibili_adapter.py` | 56 | v0.2+ | ⏸️ 首版不做 |
| `tests/test_douyin_adapter.py` | 43 | v0.2+ | ⏸️ 首版不做 |
| `tests/test_youtube_adapter.py` | 31 | 阶段 4 落地 | 🟡 6（`YtDlpEngineTest` 里的 URL 识别部分） |
| `tests/test_storage.py` | 55 | 阶段 1 落地 | 🟡 6（`MediaItemDaoTest`，**从未在设备上跑过**）。`PendingTaskDao` / `TaskDao` / `IncrementCheckpointDao` 三个 DAO 零测试 |
| `tests/test_task_manager.py` | 31 | 阶段 1 + 5 落地 | ❌ 0 |
| `tests/test_ui_polish.py` | 45 | 阶段 3 落地（Compose UI 测试套件未接） | ❌ 0 — UI 4 占位 tab 代码有了，Compose UI 测试框架（`androidx.compose.ui:ui-test-junit4`）未加 |
| `tests/test_config_theme.py` | 26 | 阶段 1 + 3 落地 | ✅ 24（`AppConfigTest` 13 + `AppConfigDataStoreTest` 11），另含桌面版没有的 clamp 测试 |
| `tests/test_cli_config_layering.py` | 17 | 阶段 1 落地 | ⏸️ **需重新评估**——Android 端没有 CLI，配置只有 DataStore 一层，这 17 例多半不适用 |
| `tests/test_server.py` | 19 | 不移植（Android 不需要 server 模块） | ⏸️ 不做 |
| `tests/test_server_security.py` | 81 | 不移植 | ⏸️ 不做 |
| `tests/test_mcp.py` | 15 | 不移植 | ⏸️ 不做 |
| `tests/test_ui_*.py` | 多 | 阶段 3-6 落地（部分） | ❌ 0 |
| `tests/test_prompt_options.py` | 11 | 阶段 4 落地 | ❌ 0 |
| `tests/test_tray.py` | 18 | 不移植（无托盘） | ⏸️ 不做 |

**v0.1 落地用例数估算**：约 280 个（已剔除 server / mcp / bilibili / douyin / tray / 部分 ui_polish）。

**当前实际**（2026-09-02 按 `@Test` 实数清点）：

| 口径 | 数量 |
|---|---|
| 单元测试（`src/test/`，JVM，全绿） | **46**（业务 45 + AS 模板 1） |
| 仪器测试（`src/androidTest/`，**从未执行**） | **7**（业务 6 + AS 模板 1） |
| 相对 ~280 估算的进度 | 约 **18%** |

其中 `ModelTest` 10 例是 Android 端自加的（桌面版没有对应的 `test_models.py`），不计入上面的移植映射。

## CHANGELOG 同步策略

- **桌面版 CHANGELOG**（`/docs/CHANGELOG.md`）继续按里程碑写
- **Android 版 CHANGELOG**（[`/android/docs/CHANGELOG.md`](CHANGELOG.md)）从 v0.1.0 起独立写
- **跨平台行为差异**（如有）在 Android 版 CHANGELOG 里单独列「vs 桌面版」对比段
- 桌面版的 BUG 修复如果同步需要 port 到 Android，CHANGELOG 两边都记一笔

## 复用方法

落地某个阶段时：

1. 打开桌面版对应文件（这份表的「桌面版文件」列）
2. 在 Android 版对应位置（这份表的「Android 版落点」列）**重写**
3. 字段名 snake → camel（业务意义不变）
4. 把桌面版的单测翻译过来，**断言一字不改**
5. **回本表更新状态列**（✅ / 🟡 / ❌ / ⏸️）。落点路径与实际代码不一致时，**当场改到一致**——阶段 1、2 就是因为没做这一步，攒下了 `data/datastore` / `TaskRepository` 两个不存在的路径和一批漏记的欠账
6. 写阶段复盘文档到 `docs/phases/`，并把未达成的验收登记到 [PHASES.md 的跨阶段欠账](PHASES.md)

这份表是**长期活文档**——阶段推进时回头更新它。
