# 架构总览

> **本文档同时是目标架构和当前进度**。目录树里的标记：
> ✅ 已落地 ｜ 🟡 占位/部分 ｜ ❌ 尚未创建（**目录本身不存在**）
> 状态截至 2026-09-08（v0.5.10 阶段 20 收官），按实际代码核对。
>
> **当前 release 状态**：**v0.5.10-android**（阶段 20 收官候选）—— B 站 3 端点 wire 5min TTL 缓存 + TimeBasedCache 通用 utility。`versionName = 0.5.10` + `versionCode=17`，**尚未发布**任何正式版本。X-Bogus 真算法 WIP 收尾（v0.5.9-wip-android tag），完整版需真 API 验证环境。

## 模块划分

```
android/
├── app/                          # 主 module（应用入口）
│   ├── src/main/java/com/doubi/android/
│   │   ├── DouBiApplication.kt   ✅ @HiltAndroidApp + WorkManager Configuration.Provider
│   │   │                            + Timber + YoutubeDL.init
│   │   ├── MainActivity.kt       ✅ 单 Activity + NavHost 4-5 tab 切换
│   │   ├── core/                 # 业务核心
│   │   │   ├── model/            ✅ MediaItem / DownloadOptions / DownloadResult / Progress
│   │   │   │                        / Platform / MediaType / Author
│   │   │   ├── config/           ✅ AppConfig（30+ 字段）/ ConfigValidator / ConfigToOptions
│   │   │   ├── pipeline/         ✅ ParseAndExpandUseCase（含 Platform dispatch + B 站/抖音 Adapter 路由）
│   │   │   ├── util/              ✅ TimeBasedCache<K, V>（v0.5.10 阶段 20 落地，5min TTL 通用缓存）
│   │   │   └── naming/           ✅ renderPathTemplate（路径模板渲染，跨 use case 复用）
│   │   ├── data/                 # 数据层
│   │   │   ├── db/               ✅ Room：4 entity + 4 DAO + Converters + di/DatabaseModule
│   │   │   │                        + Migrations.ALL 显式迁移链
│   │   │   ├── config/           ✅ DataStore：AppConfigDataStore / ConfigKeys / di/DataStoreModule
│   │   │   └── repository/       ✅ DownloadRepository（UI 不直接调 DAO）
│   │   ├── engine/               # 下载引擎适配
│   │   │   ├── Engine.kt         ✅ 引擎接口（对齐桌面版 ABC）
│   │   │   ├── ytdlp/            ✅ YtDlpEngine（真实现，junkfood02 fork，~300 行）
│   │   │   └── ffmpeg/           ❌ FFmpeg-Kit 依赖未启用 → 目前无 HLS 兜底
│   │   ├── platforms/            # 平台 adapter（v0.5.x 阶段 14+ 落地）
│   │   │   ├── bilibili/         ✅ BilibiliUrl + WbiSigner + BilibiliApiClient
│   │   │   │                       + BilibiliAdapter + dto/BilibiliPlayUrlResponse
│   │   │   │                       + 5min TTL 缓存（fetchMixinKey / view / playurl 3 端点）
│   │   │   ├── douyin/           🟡 DouyinUrl + XBogusSigner + DouyinApiClient + DouyinAdapter
│   │   │   │                       X-Bogus 真算法 WIP（v0.5.9-wip 阶段 19 收尾，2/5 commit）
│   │   │   ├── youtube/          ✅ YouTubeUrl（URL 分类 + 归一化，走 YtDlpEngine 通用路径）
│   │   │   ├── PlatformEngineRegistry.kt ✅ URL → Engine 路由表（v0.5.7 阶段 17）
│   │   │   ├── PlatformRegistry.kt   ✅ URL → Platform 分类（v0.5.4 阶段 14）
│   │   │   └── di/PlatformModule.kt  ✅ Hilt 装配
│   │   ├── download/             # WorkManager Workers
│   │   │   ├── DownloadWorker.kt ✅ CoroutineWorker + 前台 Service + 指数退避重试
│   │   │   └── NotificationHelper.kt ✅ 进度/完成通知 + PendingIntent 回 MainActivity
│   │   ├── sniffer/              # 嗅探（v0.4.0+ 落地）
│   │   │   ├── Sniffer.kt        ✅ 接口
│   │   │   ├── HttpContentTypeSniffer.kt ✅ OkHttp HEAD 嗅探（m3u8/mp4/webm）
│   │   │   ├── WebViewHeadlessSniffer.kt ✅ WebView 拦截 m3u8/mp4（覆盖 B 站/抖音/微博 JS 异步）
│   │   │   ├── M3u8Parser.kt     ✅ m3u8 内容解析（parseRecursive + MAX_RECURSION_DEPTH=5）
│   │   │   ├── WebViewFactory.kt + DefaultWebViewFactory.kt + WebViewHolder.kt
│   │   │   │                       ✅ WebView 生命周期管理（idle 30s release）
│   │   │   └── CompositeSniffer.kt   ✅ 按 AppConfig.sniffHeadless 动态选 http/headless
│   │   ├── ui/                   # Compose UI（5 tab）
│   │   │   ├── theme/            ✅ Color / Type / Theme（亮/暗双套）
│   │   │   ├── pasting/          ✅ PastingScreen（粘贴 URL → 解析）
│   │   │   ├── parsing/          ✅ ParsingScreen（parse flow 中间态）
│   │   │   ├── downloading/      ✅ DownloadingScreen（实时进度 + 速度 + ETA + 取消）
│   │   │   ├── history/          ✅ HistoryScreen（Room 记录 + 文件状态 + 重下）
│   │   │   └── settings/         ✅ SettingsScreen（13+ 字段配置）
│   │   ├── build.gradle.kts      # versionCode 17 / versionName 0.5.10
│   ├── src/main/res/
│   │   ├── values/               ✅ strings / colors / themes / ic_launcher_background
│   │   ├── values-zh/            ✅ strings.xml（中文 zh_CN）
│   │   ├── values-night/         ✅ themes.xml（暗色）
│   │   ├── drawable/             🟡 业务图标部分导入（v0.1 阶段已加 ic_launcher_foreground）
│   │   ├── mipmap-anydpi[-v26]/  ✅ adaptive icon
│   │   └── xml/                  ✅ backup_rules / data_extraction_rules
│   ├── src/test/                 ✅ **339 个单元测试**（JUnit 4 + Truth + MockK，全绿）
│   ├── src/androidTest/          🟡 10 个仪器测试（**写了但从未执行**——真机 adb install 未做）
│   └── proguard-rules.pro        🟡 已 keep Hilt/Room/序列化/Compose，引擎类 keep 待加
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
    └── phases/                   # 阶段复盘（phase-1.md → phase-20.md 共 20 份）
```

> **当前真实数据流**（v0.5.10 阶段 20）：
> ```
> URL → ParseAndExpandUseCase
>   → PlatformEngineRegistry 路由（B 站 / 抖音 / 其它）
>   → Engine.probe（Adapter 走真 web API 拿 metadata）
>   → Engine.download（Adapter 走 playurl API 拿直链 → YtDlpEngine 跑下载）
>   → DownloadWorker（WorkManager 调度 + 前台 Service + 进度回调）
> ```
> 缓存层（v0.5.10 落地）：B 站 3 端点 5min TTL 内存缓存（fetchMixinKey / view / playurl）。

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
| 网络 | OkHttp + WBI 签名（B 站）+ X-Bogus 签名（抖音，WIP） | aiohttp + orjson |
| 视频下载 | [junkfood02 发布的 youtubedl-android](https://github.com/yausername/youtubedl-android) fork | yt-dlp (CLI/Python) |
| 平台 adapter | 自研 [BilibiliAdapter](app/src/main/java/com/doubi/android/core/platform/bilibili/BilibiliAdapter.kt) + [DouyinAdapter](app/src/main/java/com/doubi/android/core/platform/douyin/DouyinAdapter.kt) | 桌面版 `platforms/bilibili/strategies.py` + `platforms/douyin/strategies.py` |
| HLS / ffmpeg | FFmpeg-Kit（**依赖未启用**） | N_m3u8DL-CLI + ffmpeg.exe |
| 缓存 | 自研 [TimeBasedCache<K, V>](app/src/main/java/com/doubi/android/core/util/TimeBasedCache.kt)（5min TTL，suspend getOrLoad，ConcurrentHashMap） | 桌面版 `utils/cache.py:TimeBasedCache`（磁盘 JSON 缓存） |
| 单元测试 | **JUnit 4 + Truth + MockK**（**MockK + Turbine 已在生产代码广泛使用**） | pytest + pytest-asyncio |
| 仪器测试 | Espresso + Compose UI Test（**尚未执行过**） | 无（PySide6 难自动化） |
| i18n | `res/values-zh/strings.xml` + `stringResource()` | JSON 词表 + `tr()` |

> ⚠️ **测试框架订正**：早期文档写「JUnit 5 + MockK」，实际用的是 **JUnit 4 + Truth**。
> 原因是 JUnit 5（Jupiter）与 Android Studio 的 JUnit 模板冲突，会报 "No junit.jar"，
> 阶段 1 已把 Jupiter 移除（commit `82f0399`）。MockK 已**广泛使用**于 v0.5.x 阶段 17+ 的
> Adapter / ParseAndExpandUseCase 单测。
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

v0.5.7 阶段 17 新增 4 个 Engine 实现：
- [YtDlpEngine](app/src/main/java/com/doubi/android/engine/ytdlp/YtDlpEngine.kt) — 通用 fallback
- [BilibiliAdapter](app/src/main/java/com/doubi/android/core/platform/bilibili/BilibiliAdapter.kt) — B 站（`name = "bilibili"`）
- [DouyinAdapter](app/src/main/java/com/doubi/android/core/platform/douyin/DouyinAdapter.kt) — 抖音（`name = "douyin"`，X-Bogus WIP）
- [PlatformEngineRegistry](app/src/main/java/com/doubi/android/core/platform/PlatformEngineRegistry.kt) — URL → Engine 路由表

`ParseAndExpandUseCase` 在 v0.5.7 阶段 17 加 Platform 分支（YouTube → 通用 / B 站 / 抖音 → 平台 Adapter）—— 心智模型跟桌面版 `DownloadPipeline` 一致。

### 2. 配置 `AppConfig` 数据类

桌面版 `core/config.py:AppConfig` 是 dataclass；Android 版用 Kotlin data class + Hilt 注入。字段一一对应，详见 [REUSE-MAP.md](REUSE-MAP.md)。v0.5.10 范围 30+ 字段（含 13+ 用户配置 + ConfigValidator 白名单/clamp）。

### 3. i18n 不复用桌面版 JSON 词表

桌面版用自研 JSON 词表（`ui/locales/zh_CN.json`），Android 版用 `res/values-zh/strings.xml` 更原生。两边各自维护，**术语保持一致**（中英文翻译用一个对照表，避免漂移）。

### 4. WorkManager 替代 asyncio 任务

桌面版一个长下载就是一个 asyncio 任务；Android 版用 `CoroutineWorker`。WorkManager 的好处是：
- 进程被杀后能恢复（对齐桌面版 M6.10 跨进程恢复）
- 系统重启 / OTA 后能继续
- 低内存自动降级（不像桌面版那么紧迫）
- v0.5.0 阶段 10 修了 `#1 失败重试`（`setBackoffCriteria` EXPONENTIAL + `Result.retry()`，10 次封顶）

### 5. 平台 Adapter 自己拿 metadata（**不**走 yt-dlp 嗅探）

桌面版 `BilibiliStrategy.get_metadata` 走 B 站 web API（`/x/web-interface/view`），不调 yt-dlp。Android 端 v0.5.7 阶段 17 + v0.5.8 阶段 18 + v0.5.10 阶段 20 一致 1:1 对拍：
- `BilibiliAdapter.probe` 调 `BilibiliApiClient.view` 拿 `cid` + metadata
- `BilibiliAdapter.download` 调 `BilibiliApiClient.playurl` 拿真实下载直链 → `YtDlpEngine.download`
- `DouyinAdapter` 同模式（X-Bogus 仍 stub chaos 走真 API 返 -352，**不**能真下载抖音视频——v0.5.9-wip 落地的 XBogusEncoding + XBogusMd5 utility 是基础设施，真算法完整版留 v0.5.9 完整版 → v0.5.11+）

**vs 桌面版**：
- 桌面版 [BilibiliStrategy] 同样两次调用（fetch_view + fetch_playurl），用 [AuthManager] 缓存 cookie / mixin_key
- Android 端 v0.5.10 阶段 20 加 [TimeBasedCache] 缓存 mixin_key（**不**做 cookie 缓存——v0.5.x 阶段**不**登录 B 站）

### 6. WBI / X-Bogus 签名（**不**走 YouTube 通用路径）

B 站/抖音 web API 强依赖签名（缺失返 -352 风控），Android 端 v0.5.4-v0.5.6 自研签名：
- **WBI**（B 站）—— [WbiSigner](app/src/main/java/com/doubi/android/core/platform/bilibili/WbiSigner.kt) 反编译抖音 webmssdk.js 算法，v0.5.5 阶段 15 完整实装
- **X-Bogus**（抖音）—— [XBogusSigner](app/src/main/java/com/doubi/android/core/platform/douyin/XBogusSigner.kt) 真 RC4 + 真 a_bogus 字母表编码（v0.5.5 阶段 15）+ 真 get_chaos 算法 port（WIP v0.5.9-wip 阶段 19）

**vs 桌面版**：
- 桌面版 [src/doubi/platforms/bilibili/wbi.py] / [src/doubi/platforms/douyin/xbogus.py] 1:1 对拍
- v0.5.9-wip 修了 v0.5.5 阶段 15 写错的 A_BOGUS_ALPHABET（64 字符）—— 1:1 对拍抖音 webmssdk.js 反编译

### 7. 缓存层（v0.5.10 阶段 20）

[TimeBasedCache<K, V>](app/src/main/java/com/doubi/android/core/util/TimeBasedCache.kt) 通用 TTL 内存缓存，**3 个端点 wire**：
- `mixinKeyCache` key=`"global"` —— B 站 mixin_key 全局单值
- `viewCache` key=`bvid` —— 视频 metadata
- `playurlCache` key=`"$bvid:$cid:$qn"` —— 真实下载直链

**suspend getOrLoad** 模式 + `ConcurrentHashMap` 线程安全 + 注入 `clock` 函数。**不**做主动清理 / LRU / size 上限（5-10 个 key 内存**远低于**阈值）。**不**做持久化（**仅**进程生命周期内有效——应用重启清空，~200ms 一次性延迟可接受）。

## 数据流

### URL 解析（v0.5.7 阶段 17 + v0.5.10 阶段 20 缓存层）

```
PastingScreen.onParseClicked(url)
  → ParseAndExpandUseCase(url)
    → PlatformRegistry.classify(url)        # URL → Platform
    → if (B 站 / 抖音) PlatformEngineRegistry.getEngine(url)  # Platform → Engine
      → BilibiliAdapter.probe(url) / DouyinAdapter.probe(url)
        → BilibiliApiClient.view(bvid)        # viewCache 缓存（5min）
          → fetchMixinKey()                    # mixinKeyCache 缓存（5min）
        → MediaItem（title / duration / author / cover / platform / itemId / sourceUrl）
    → if (其它) YtDlpEngine.probeWithFormats(url)  # YouTube / generic
    → ParseResult.Youtube / Platform / DirectLink / Unsupported
  → PastingViewModel 转 ParseStatus（AwaitingConfirm / Unsupported / Failure）
  → PromptOptionsDialog 显示清晰度下拉 + 容器 / 缩略图 / 字幕 / 续传 / 标题模板
```

### 下载（v0.5.8 阶段 18 + v0.5.10 阶段 20 缓存层）

```
PromptOptionsDialog.onConfirm(item, format, options)
  → PastingViewModel.onDialogConfirm
    → DownloadRepository.enqueue(sourceUrl, platform, itemId, title)
      → WorkManager.enqueue(DownloadWorker)
        → DownloadWorker.doWork()
          → EngineFactory.create(item.platform)
            → BilibiliAdapter / DouyinAdapter / YtDlpEngine
          → engine.download(item, options, onProgress)
            → BilibiliAdapter.download: view() → playurl() → YtDlpEngine.download
              → BilibiliApiClient.view(bvid)     # viewCache 缓存命中（5min）
              → BilibiliApiClient.playurl(bvid, cid, qn)  # playurlCache 缓存命中（5min）
              → YtDlpEngine.download(sourceUrl=playurl, ...)
            → onProgress callback 透传
          → DownloadResult.Success(filePath) / Failure(reason) / Cancelled
          → WorkManager.Result.success() / failure() / retry()
        → NotificationHelper.buildProgressNotification / buildCompleteNotification
```

## 关键架构演进（v0.1 → v0.5.10 摘要）

| 阶段 | 关键架构变化 |
|---|---|
| 0-7（v0.1 基础期） | Gradle / Hilt / Room / WorkManager / Compose 4 tab / proguard keep |
| 8-9（v0.4 通用嗅探期） | OkHttp HEAD / WebView 拦截 m3u8-mp4 / CompositeSniffer |
| 10-13（v0.5.0-3 WebView + m3u8 期） | WebViewHolder idle release / M3u8Parser parseRecursive |
| 14-16（v0.5.4-6 平台 foundation 期） | BilibiliUrl + WbiSigner / XBogusSigner / BilibiliApiClient / DouyinApiClient / Hilt PlatformModule |
| 17-18（v0.5.7-8 Engine 集成 + download 真路径） | PlatformEngineRegistry / BilibiliAdapter / DouyinAdapter / playurl / ParseResult.Platform |
| 19-20（v0.5.9-wip-10 算法 + 性能期） | XBogusEncoding / XBogusMd5 (WIP) / TimeBasedCache / B 站 3 端点 wire cache |

> 详细阶段复盘见 [`docs/phases/`](phases/)（共 20 份 phase-1.md → phase-20.md）。
