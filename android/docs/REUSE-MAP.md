# 桌面版 → Android 版 一对一映射

> 阶段 0 完成时**仅做参考**，**不实际同步代码**。后续每个阶段会从这里选一个子集落地。

## 规则

- **业务算法照搬**（URL 分类、JSON 解析、文件名渲染、正则）—— Kotlin 重写但**保留字段名**（snake_case 改 camelCase，但**业务意义不变**）
- **配置 schema 字段名照搬**（`database` / `manifest_path` / `filename_template` 等）—— 便于跨平台对照文档
- **i18n 字符串**重写为 `strings.xml`，**翻译**人工对齐（开 PR 时附对照表）
- **测试用例的断言**逐条翻译为 Kotlin（JUnit 5 + MockK），不增减

## 完整映射表

### `core/`

| 桌面版文件 | 行数 | Android 版落点 | 阶段 |
|---|---|---|---|
| `core/models.py` | ~200 | `core/model/MediaItem.kt` / `DownloadOptions.kt` / `DownloadResult.kt` / `Progress.kt` | 1 |
| `core/pipeline.py` | ~600 | `core/pipeline/ParseAndExpandUseCase.kt` / `DownloadUseCase.kt` / `DownloadPipeline.kt` | 1, 2, 4 |
| `core/naming.py` | ~150 | `core/naming/FilenameTemplate.kt` + `_sanitize` 扩展 | 1 |
| `core/registry.py` | ~50 | `core/pipeline/PipelineRegistry.kt` | 1 |
| `core/config.py` | ~300 | `core/config/AppConfig.kt` + `data/datastore/AppConfigSerializer.kt` | 1 |
| `core/logger.py` | ~50 | Timber（直接用第三方） | 1 |
| `core/storage/database.py` | ~400 | `data/db/DouBiDatabase.kt` + `data/db/entity/*.kt` + DAO | 1 |
| `core/storage/file_layout.py` | ~100 | `core/storage/FileLayout.kt`（纯 Kotlin 类） | 1 |
| `core/storage/manifest.py` | ~150 | v0.1 用 Room 替代；v0.2 再考虑 jsonl 旁路 | 1 |
| `core/storage/migrate.py` | ~200 | v0.1 不做（旧库迁移用不上） | 延后 |

### `engines/`

| 桌面版文件 | 行数 | Android 版落点 | 阶段 |
|---|---|---|---|
| `engines/__init__.py:Engine` ABC | ~30 | `engine/Engine.kt` interface | 1 |
| `engines/yt_dlp.py` | ~250 | `engine/ytdlp/YtDlpEngine.kt`（基于 yausername/yt-dlp-android） | 2 |
| `engines/nm3u8dl.py` | ~350 | **v0.1 不移植**；HLS 走 FFmpeg-Kit 通用方案 | 3+ |
| `engines/aria2.py` | ~200 | **v0.1 不移植** | 延后 |
| `engines/m3u8dl_fallback.py` | ~100 | 合并到 FFmpeg-Kit 通用方案 | 3+ |

### `platforms/`

| 桌面版文件 | 行数 | Android 版落点 | 阶段 |
|---|---|---|---|
| `platforms/youtube/`（含 `api` / `url` / `strategies`） | ~500 | `platforms/youtube/YouTubeStrategy.kt` + `YouTubeUrlClassifier.kt` | 4 |
| `platforms/bilibili/`（含 `api` / `auth` / `strategies` / `url` / `wbi` / `qr_login`） | ~1500 | v0.2+ | v0.2 |
| `platforms/douyin/`（含 `api` / `auth` / `strategies` / `url` / `live`） | ~1200 | v0.2+ | v0.2 |
| `platforms/generic/`（Playwright 嗅探） | ~800 | v0.4+ 评估 playwright-android；v0.1 用直链嗅探 | 延后 |

### `ui/`

| 桌面版文件 | 行数 | Android 版落点 | 阶段 |
|---|---|---|---|
| `ui/app.py` | ~50 | `DouBiApplication.kt` | 0 |
| `ui/main_window.py` | ~300 | `MainActivity.kt` + `ui/home/HomeScreen.kt`（Compose NavHost） | 3 |
| `ui/workers.py` | ~200 | `data/repository/TaskRepository.kt` + WorkManager | 1, 2 |
| `ui/pages/parse.py` | ~1000 | `ui/parse/ParseScreen.kt` + `ParseViewModel.kt` | 4 |
| `ui/pages/download.py` | ~600 | `ui/download/DownloadScreen.kt` + `DownloadViewModel.kt` | 5 |
| `ui/pages/history.py` | ~300 | `ui/history/HistoryScreen.kt` | 6 |
| `ui/pages/settings.py` | ~400 | `ui/settings/SettingsScreen.kt` | 6 |
| `ui/task_manager.py` | ~400 | `data/repository/TaskRepository.kt`（融合 Download + TaskManager） | 1, 5 |
| `ui/tray.py` | ~200 | v0.1 不做（手机无托盘） | 不做 |
| `ui/auth_actions.py` | ~300 | v0.2+（账号登录放 v0.2 起） | v0.2 |
| `ui/dialogs/login_dialog.py` | ~200 | v0.2+ | v0.2 |
| `ui/dialogs/prompt_options_dialog.py` | ~250 | `ui/parse/PromptOptionsDialog.kt` | 4 |
| `ui/theme.py` | ~500 | `ui/theme/{Color,Type,Theme}.kt`（v0.1 先做 2 套默认） | 3 |
| `ui/resources/icons/*.svg` | ~30 个 | `res/drawable/`（用 AS Vector Asset Studio 导入） | 0, 3 |
| `ui/locales/zh_CN.json` | ~200 条 | `res/values-zh/strings.xml` | 3, 6 |
| `ui/locales/en.json` | ~200 条 | `res/values/strings.xml` | 3, 6 |

### `tests/`

| 桌面版文件 | 用例数 | Android 版落点 |
|---|---|---|
| `tests/test_pipeline_smoke.py` | 28 | 阶段 1、4 落地 |
| `tests/test_pipeline_retry.py` | 16 | 阶段 2 落地（含 8 个变异杀测试的关键） |
| `tests/test_bilibili_adapter.py` | 56 | v0.2+ |
| `tests/test_douyin_adapter.py` | 43 | v0.2+ |
| `tests/test_youtube_adapter.py` | 31 | 阶段 4 落地 |
| `tests/test_storage.py` | 55 | 阶段 1 落地 |
| `tests/test_task_manager.py` | 31 | 阶段 1 + 5 落地 |
| `tests/test_ui_polish.py` | 45 | 阶段 3 落地（部分） |
| `tests/test_config_theme.py` | 26 | 阶段 1 + 3 落地 |
| `tests/test_cli_config_layering.py` | 17 | 阶段 1 落地 |
| `tests/test_server.py` | 19 | 不移植（Android 不需要 server 模块） |
| `tests/test_server_security.py` | 81 | 不移植 |
| `tests/test_mcp.py` | 15 | 不移植 |
| `tests/test_ui_*.py` | 多 | 阶段 3-6 落地（部分） |
| `tests/test_prompt_options.py` | 11 | 阶段 4 落地 |
| `tests/test_tray.py` | 18 | 不移植（无托盘） |

**v0.1 落地用例数估算**：约 280 个（已剔除 server / mcp / bilibili / douyin / tray / 部分 ui_polish）。

## CHANGELOG 同步策略

- **桌面版 CHANGELOG**（`/docs/CHANGELOG.md`）继续按里程碑写
- **Android 版 CHANGELOG**（`/android/docs/CHANGELOG.md`）从 v0.1.0 起独立写
- **跨平台行为差异**（如有）在 Android 版 CHANGELOG 里单独列「vs 桌面版」对比段
- 桌面版的 BUG 修复如果同步需要 port 到 Android，CHANGELOG 两边都记一笔

## 复用方法

落地某个阶段时：

1. 打开桌面版对应文件（这份表的「桌面版文件」列）
2. 在 Android 版对应位置（这份表的「Android 版落点」列）**重写**
3. 字段名 snake → camel（业务意义不变）
4. 把桌面版的单测翻译过来，**断言一字不改**
5. 在本表对应行加 ✅ 表示已落地
6. 写阶段复盘文档到 `docs/phases/`

这份表是**长期活文档**——阶段推进时回头更新它。
