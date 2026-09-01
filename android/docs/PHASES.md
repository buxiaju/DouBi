# 阶段划分与里程碑

> **每个阶段结束都要**：① 通过本阶段所有验收 ② 在 [`phases/`](phases/) 子目录里写一份阶段复盘文档
> **CHANGELOG 节奏**：从 v0.1.0 起独立递增。桌面版与 Android 版号不互通。

## 总览

| 阶段 | 名称 | 验收门槛 | 预计 |
|---|---|---|---|
| 0 | **项目脚手架**（本文档） | Android Studio sync 成功；Hello World 跑起来 | ✅ 已完成 |
| 1 | 数据层 + 配置 | Room schema 落库 + 单元测试通过；DataStore 读写往返 | 1 周 |
| 2 | 下载引擎（yt-dlp-android 集成） | Worker 跑通；能在后台下载 + 前台通知显示进度 | 1.5 周 |
| 3 | UI 框架（Compose 导航 + 主题） | 主框架 4 页（解析/下载/历史/设置）能切换 + 暗色主题 | 1 周 |
| 4 | 解析 + 列表 | 粘贴 URL → 解析 → 表格展示候选 → 选清晰度 | 1.5 周 |
| 5 | 下载 + 进度 + 完成通知 | 接 phase 2 的 Worker；进度条实时更新；完成弹系统通知 | 1 周 |
| 6 | 历史 + 设置 | 历史列表真实查询；设置项可改可保存 | 1 周 |
| 7 | 商店准备 | ProGuard/R8 规则、签名配置、隐私政策页、图标 | 1 周 |

**预计总工期**：6-8 周一人（不含商店审核 1-3 天）

**v0.1 范围**（最小可用）：YouTube + 通用 m3u8/mp4 直链下载。**不含** B 站 / 抖音 / 微博 / Playwright 通用嗅探（这些放 v0.2+）。

## 阶段 0：项目脚手架（当前）

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

## 阶段 1：数据层 + 配置

**目标**：把桌面版的 `core/storage/` + `core/config.py` 移植到 Room + DataStore。

**桌面版 → Android 版对应**：
- `core/storage/database.py`（SQLite + WAL） → Room `MediaItemDao` / `TaskDao` / `IncrementCheckpointDao`
- `core/storage/file_layout.py`（路径模板） → `core/storage/FileLayout` 纯 Kotlin 类
- `core/storage/manifest.py`（jsonl） → 暂用 Room `Download` 表 + WorkManager 进度合并；v0.2 再考虑是否要 jsonl 旁路
- `core/config.py`（YAML + env） → DataStore Preferences（KV）+ Hilt 提供单例

**关键边界**：
- `database_path` 那个老坑（`core/config.py:45` 相对路径，详见桌面版 CHANGELOG G9）—— **Android 版直接用绝对路径**（app-private `getDatabasePath()`），不再背这个坑
- `~/.doubi/config.yml` → `Context.dataStore`（每个 app 自己的私有目录）

**验收**：
- [ ] Room schema 编译通过 + 迁移测试覆盖 1 → 2 schema 变化
- [ ] DataStore 读写往返 + 非法值回退（与 `test_config_theme.py` 对齐）
- [ ] 单测覆盖率 ≥ 80%
- [ ] 阶段 1 复盘文档

## 阶段 2：下载引擎

**目标**：用 [yausername/yt-dlp-android](https://github.com/yausername/yt-dlp-android) 跑通 YouTube 视频下载到本地。

**桌面版 → Android 版对应**：
- `engines/yt_dlp.py`（async 包装，to_thread 跑 sync yt-dlp） → `engine/ytdlp/YtDlpEngine`（基于 yt-dlp-android 的 `YoutubeDL` 类）
- `engines/nm3u8dl.py`（外部 .exe + 文件系统 watchdog） → **v0.1 不移植**；HLS 站点暂用 FFmpeg-Kit 通用方案
- `engines/aria2.py` → **v0.1 不移植**

**关键边界**：
- 手机没有外部二进制；yt-dlp-android 自带 ffmpeg，所以 Aria2 / N_m3u8DL-CLI / imageio-ffmpeg 全部要重做或砍掉
- WorkManager `CoroutineWorker` 替代 asyncio 任务 + 后台线程
- 前台 Service 通知（`setForegroundAsync`）替代桌面版「关窗最小化到托盘」

**验收**：
- [ ] 输入一个 YouTube 链接 → WorkManager Worker 拉起 → 下载到 app 私有目录
- [ ] 进度通知显示 + 点击进应用
- [ ] 失败重试（指数退避）—— 对齐桌面版 `test_pipeline_retry.py` 的 8 个变异杀测试
- [ ] 阶段 2 复盘文档

## 阶段 3：UI 框架

**目标**：主框架 4 页（解析/下载/历史/设置）能切换 + Material 3 主题（亮/暗）。

**桌面版 → Android 版对应**：
- `ui/main_window.py`（主窗口 + 4 页 + 导航） → `MainActivity` + Compose `NavHost` + 底部导航栏
- `ui/theme.py`（7 套主题） → v0.1 先做 **2 套**：Material 3 默认亮 + Material 3 默认暗；自定义调色板放 v0.2
- `ui/resources/icons/*.svg`（矢量图标） → `android/app/src/main/res/drawable/`（用 Android Studio 的 Vector Asset Studio 导入 SVG）

**关键边界**：
- i18n：桌面版是 JSON 词表 + `tr()` 函数，Android 版用 `res/values-zh/strings.xml` + `res/values-en/strings.xml` + `stringResource()`，更原生
- 底部导航 4 项 vs 桌面版左侧导航 4 项，**项的顺序和命名要对齐**（解析/下载/历史/设置）

**验收**：
- [ ] 4 个空页面能切换，标题栏对应显示
- [ ] 切换系统暗色模式 → 应用立即变暗
- [ ] 阶段 3 复盘文档

## 阶段 4：解析 + 列表

**目标**：粘贴 URL → 调用 yt-dlp-android 解析 → 表格展示候选 → 选清晰度。

**桌面版 → Android 版对应**：
- `core/pipeline.py:parse_and_expand()` → `core/pipeline/ParseAndExpandUseCase`
- `platforms/youtube/strategies.py` → `platforms/youtube/YouTubeStrategy`（基于 yt-dlp-android 提取信息）
- `ui/pages/parse.py:PromptOptionsDialog` → `ui/parse/PromptOptionsDialog` Composable

**v0.1 站点**：YouTube + 通用 m3u8/mp4 直链（yt-dlp-android 用 `YoutubeDL.extractInfo()` 处理）

**验收**：
- [ ] YouTube 链接（普通 + Shorts + Live）解析正确
- [ ] 直链 m3u8 / mp4 解析正确
- [ ] 选清晰度后能入队（到阶段 5 才真正下载）
- [ ] 阶段 4 复盘文档

## 阶段 5：下载 + 进度 + 完成通知

**目标**：接 phase 2 的 Worker，UI 上看进度，完成弹系统通知。

**桌面版 → Android 版对应**：
- `ui/pages/download.py:TaskRow` → `ui/download/TaskRow` Composable
- `ui/tray.py:TrayController` → `NotificationManager`（不再需要托盘——手机只有通知）
- `ui/main_window.py:notify_on_completion` → `Worker.doWork()` 完成后发 `NotificationCompat.Builder`

**验收**：
- [ ] 下载中页能看到实时进度条 + 速度 + ETA
- [ ] 队列并发（默认 3，配置可改）
- [ ] 完成通知（success / all / summary 三档，对齐桌面版）
- [ ] 阶段 5 复盘文档

## 阶段 6：历史 + 设置

**目标**：历史页真实查询 + 设置项可改可保存。

**桌面版 → Android 版对应**：
- `ui/pages/history.py` → `ui/history/HistoryScreen`（Room 查询 + LazyColumn）
- `ui/pages/settings.py` → `ui/settings/SettingsScreen`（DataStore 读写）
- 重新下载功能 → 复用 phase 2 的 Worker 入口

**验收**：
- [ ] 历史列表按时间倒序
- [ ] 「文件已删除」检测（与桌面版 `test_task_manager.py::test_restore` 对齐）
- [ ] 设置改完立即生效（不用重启，桌面版 `config.py` 有「需重启」限制）
- [ ] 阶段 6 复盘文档

## 阶段 7：商店准备

**目标**：能 `assembleRelease` 出 `.aab` 提交 Google Play。

**包含**：
- 签名（`keystore.properties` + `signingConfigs.release`）
- ProGuard / R8 规则（保留 Room 实体、Hilt 类、Compose 函数名）
- 应用图标（adaptive icon）
- 启动屏
- 隐私政策页（GitHub Pages 或 Gitee Pages 挂一份）
- 商店截图（4.7" / 6.7" 各 2 张）
- 应用描述（中英文）

**验收**：
- [ ] `./gradlew assembleRelease` 成功出 `.aab`
- [ ] Play Console 上传预审通过（自己账号）
- [ ] 阶段 7 复盘文档

## 收尾

阶段 7 完成 → 提 Play Console 审核 → 1-3 天过审 → 上线 v0.1.0。

之后进入迭代期（v0.2 / v0.3），按需扩 B 站 / 抖音 / 通用嗅探（参考 [REUSE-MAP.md](REUSE-MAP.md)）。
