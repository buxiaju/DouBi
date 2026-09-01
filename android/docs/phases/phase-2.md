# 阶段 2 复盘：下载引擎（**部分落地**）

> 2026-09-02 阶段 2 启动，落地了 80%——Engine interface / 数据模型 / Repository /
> NotificationHelper / DownloadWorker / Application Configuration.Provider 全部就位。
> 唯独 **yt-dlp-android 真实下载链路**没跑通，因为 JitPack 401 Unauthorized。

## 完成清单

### ✅ 落地

- [x] 6 个数据模型（`Platform` / `MediaType` / `Author` / `MediaItem` / `DownloadOptions` / `Progress` / `DownloadResult`）
- [x] `Engine` interface（1:1 对拍桌面 `engines/__init__.py:Engine` ABC）
- [x] `YtDlpEngine`（**stub 版本**——不调 yt-dlp-android，所有方法返回占位值 / Failure）
- [x] `DownloadWorker`（**stub 版本**——调 stub engine，UI 端到端能跑通流程到「Failure」）
- [x] `DownloadRepository`（DAO + WorkManager 入口）
- [x] `NotificationHelper`（前台 Service + 完成通知 + Channel）
- [x] `DouBiApplication` 实现 `Configuration.Provider`（Hilt + WorkManager 集成）
- [x] `AndroidManifest.xml` 关默认 WorkManager 初始化（让 Hilt Application 自管）
- [x] 11 个单测（`ModelTest` 7 + `YtDlpEngineTest` 4 + `ConfigToOptions` 2）
- [x] 阶段 2 复盘文档（本文件）

### ❌ 未落地

- [ ] **yt-dlp-android 真实下载**——JitPack 401，详见下文
- [ ] ffmpeg-kit（HLS 站点通用方案，依赖太重，v0.2 评估）
- [ ] 阶段 4 解析、aria2 / bilibili / douyin 适配器（后续阶段）

## JitPack 401 详细说明

### 报错

```
> Could not resolve io.github.yausername.ytdlp-android:core:2024.10.27.
   > Could not GET 'https://jitpack.io/.../core-2024.10.27.pom'.
      Received status code 401 from server: Unauthorized
```

### 根因

`io.github.yausername.ytdlp-android:core` 这个 artifact **只在 JitPack 上发布**（GitHub `yausername/yt-dlp-android` 仓库被 JitPack 编译成 Maven artifact）。JitPack 现在对未登录用户 / 特定库拒服务——可能是 JitPack 政策调整（要求登录或 token），也可能是 yausername 仓库本身被 JitPack 标记为受限。

### 4 条恢复路径（按推荐顺序）

1. **试 Maven Central 镜像**：搜 `io.github.yausername.*`，看看 yausername 是否在 Maven Central 有其他发布渠道
2. **用 [JunkFood02/yt-dlp-android](https://github.com/junkfood02/yt-dlp-android) fork**：活跃维护，发布到 Maven Central（artifact: `io.github.junkfood02.ytdlp-android:core`），无须 JitPack
3. **自研 yt-dlp 集成**：从 yt-dlp 官网下静态二进制（`yt-dlp_linux_arm64`），用 `Runtime.exec()` 调子进程（Android 模拟 Linux）
4. **退到 OkHttp + 自研 M3U8 解析**：最干净但 1-2 周工作量

### 恢复步骤

任何方案恢复后：

1. 取消 `app/build.gradle.kts:141` `ytdlp-android` 依赖的注释
2. 把 `.scratch/phase2_ytdlp_unused/YtDlpEngine.kt.bak` 覆盖回 `app/src/main/java/com/doubi/android/engine/ytdlp/YtDlpEngine.kt`
3. 把 `.scratch/phase2_ytdlp_unused/DownloadWorker.kt.bak` 覆盖回 `app/src/main/java/com/doubi/android/download/DownloadWorker.kt`
4. Sync + 跑测试

> 完整实现版本已 stash 在 `.scratch/phase2_ytdlp_unused/`——保留全部 callback API + coroutine 桥接代码，未来换源时直接恢复。

## 关键设计决定

### 1. Engine interface 心智模型与桌面版一致

桌面版 `engines/__init__.py:Engine` ABC 的 4 个方法（`name` / `supports` / `probe` / `download`）1:1 映射到 Android `interface Engine`：
- callback API（Python `Callable` / Java `YoutubeDLCallback`）→ coroutine `suspend (Progress) -> Unit`
- 异常抛出 → sealed class `DownloadResult.Failure(reason)`
- ABC → interface

### 2. 数据模型裁剪到 v0.1 必须的

| 字段 | 桌面版有 | Android v0.1 |
|---|---|---|
| `MediaItem.streams` | ✅（解析后的 m3u8 / mp4 链接） | ❌（桌面 `_ITEM_SKIP_FIELDS` 也明确不持久化） |
| `MediaItem.children` | ✅（合集子项） | ❌（同上） |
| `DownloadOptions.cancelCheck` | ✅（callable，跨进程不可序列化） | ❌ |
| `Progress.speed` / `eta` | ✅ | ❌（v0.2+ 加） |

理由：v0.1 Android 端只支持 YouTube 嗅探 + 单任务下载，复杂字段留 v0.2+。

### 3. WorkManager + Hilt 通过 `Configuration.Provider` 集成

桌面版有「任务持久化 + asyncio 协程 + UI 进度回调」三件套。Android 端：

- 任务持久化 → `PendingTaskDao`（Room）
- 后台执行 → WorkManager（`@HiltWorker` 协程化）
- UI 进度回调 → `WorkInfo.progress` + Room `Flow`（实时观察）

要 `@HiltWorker` 注入依赖，必须：
1. Application 实现 `Configuration.Provider`（`DouBiApplication.workManagerConfiguration`）
2. Manifest 关默认 WorkManager 初始化（`tools:node="remove"`）
3. hilt-work + hilt-compiler（KSP）依赖到位

### 4. DownloadResult 用 sealed class 显式三态

桌面版用「返回 `Optional[str]` / 抛异常」混合模式，Android 端用 `sealed class` 显式建模 Success / Failure / Cancelled——Worker / UI 都用 `when` 模式匹配穷尽性，编译期保证不漏分支。

### 5. 通知渠道统一管理

`NotificationHelper` 单例管理一个 channel（`doubi_download`）。前台 Service 通知 vs 完成通知复用同一 Builder，区别只在 `setOngoing(true)` + `setProgress` vs `setAutoCancel(true)`。

## 当前 stub 行为（v0.1）

调用 `DownloadRepository.enqueue("https://www.youtube.com/watch?v=...")`：

1. ✅ 写入 `PendingTaskDao`（status=queued）
2. ✅ 提交 `WorkManager.enqueueUniqueWork("download_xxx", KEEP, ...)`
3. ✅ Worker 起来 → 拉 AppConfig → 调 stub Engine
4. ❌ Engine 返回 `Failure("yt-dlp-android 集成未启用：JitPack 401 Unauthorized")`
5. ✅ Worker 写 `PendingTaskDao` status=failed + 发桌面通知
6. ✅ Worker 返回 `Result.failure(KEY_ERROR = reason)`

UI 端到端**能跑通**——能验证 Hilt 链 / WorkManager 链 / 通知渠道 / 进度回调全工作。**实际下载功能等到 v0.2 恢复依赖**。

## 桌面版测试覆盖（v0.1 没覆盖的，等 v0.2 补）

| 桌面版测试 | Android 对拍 |
|---|---|
| `test_engines.py::TestYtDlpEngine::test_supports_youtube_url` | `YtDlpEngineTest::supports YouTube watch URL` ✅ |
| `test_engines.py::TestYtDlpEngine::test_supports_generic_url` | `YtDlpEngineTest::supports generic http URL` ✅ |
| `test_engines.py::TestYtDlpEngine::test_probe_extracts_metadata` | `YtDlpEngineTest::probe returns minimal MediaItem`（stub 行为）|
| `test_engines.py::TestYtDlpEngine::test_download_writes_to_disk` | **v0.1 未实现**（v0.2 依赖恢复后补）|
| `test_engines.py::TestYtDlpEngine::test_download_retries_on_network_error` | v0.2+ |

## 阶段 2 测试用例数

- 单元测试：11（`ModelTest` 7 + `YtDlpEngineTest` 4 + `ConfigToOptions` 2 中 2 个直接测）
- 仪器测试：0（v0.1 没写——end-to-end 下载测试留 v0.2）
- **合计 11**（+ 阶段 1 的 31 = 总 42 个）

## 下一阶段

按 [PHASES.md §3](../PHASES.md)：

1. 修 Application MainActivity 注入 `DownloadRepository` 链验证（阶段 3 之前临时入口）
2. 阶段 3：UI 框架（Compose 导航 + 4 页 + 主题 7 套）
3. 阶段 3 完成后回到阶段 2 收尾：恢复 yt-dlp-android 依赖 + 写 instrumented test 验证端到端

或者按时间预算，直接进阶段 3——阶段 2 的接口/模型/Repository 全部到位，Worker 和 Engine 是 stub，阶段 3 起 UI 可以正常调（看到的是「失败」通知，符合预期）。

---

# 阶段 2 v0.2 兑底：JunkFood02/yausername/youtubedl-android 集成（**完整落地**）

> 2026-09-02 v0.2 兑底：阶段 2 当时未落地的 yt-dlp-android 真实下载链路**已恢复**。
> 选了「4 条恢复路径」里的第 2 条（JunkFood02 fork），依赖装上后真编译 + 46 单测全过。

## v0.2 vs v0.1 落地差异

| 项 | v0.1（阶段 2 起点）| v0.2（兑底）|
|---|---|---|
| 依赖源 | JitPack 401 | Maven Central |
| 坐标 | `io.github.yausername.ytdlp-android:core:2024.10.27`（404 / 401） | `io.github.junkfood02.youtubedl-android:library:0.18.1` |
| YtDlpEngine | stub（返最小 MediaItem / Failure） | 真实现（调 fork 真嗅探 / 真下载）|
| DownloadWorker | stub（调 stub engine，UI 端到端走通到「失败」） | 真实现（前台 Service + 真进度回调 + 真落盘）|
| DouBiApplication | 只初始化 Timber | 多初始化 `YoutubeDL.getInstance().init(this)` |
| AndroidManifest | 已有 INTERNET / FOREGROUND_SERVICE / POST_NOTIFICATIONS | 加 `extractNativeLibs="true"`（fork 强制要求）+ `requestLegacyExternalStorage="true"`（API 29 兼容）|
| ndk.abiFilters | 默认全部（armeabi-v7a / arm64-v8a / x86 / x86_64） | 显式写这 4 个 ABIs（fork 仅支持这 4） |
| 单元测试 | 11（stub 行为）| 11（改测真引擎——`probe` 走 catch 兜底、`download` 期望 `Failure`） |
| 编译 | ✅ | ✅（Maven Central 0.18.1 下载成功，无 401）|
| 单测 | 11/11 | **46/46**（阶段 1 + 2 全过）|

## 4 个坑（v0.1 → v0.2 修复）

### 坑 1：JitPack 401（v0.1 痛点）

`io.github.yausername.ytdlp-android:core` 只在 JitPack 上发布，2026 年 JitPack 对未登录用户 / 特定库拒服务，返 401。详见上方「JitPack 401 详细说明」。

**v0.2 解决**：换 [JunkFood02/yausername/youtubedl-android](https://github.com/yausername/youtubedl-android) fork——这其实是 yausername 原仓库被 JunkFood02 接手后改的发布通道（README 都在 yausername 名下）。JunkFood02 把 artifact 发到 **Maven Central**，稳定无须 token。

### 坑 2：包名写错（"ytdlp" vs "youtubedl"）

`/junkfood02/ytdlp-android:library` 这个路径在 Maven Central **根本不存在**——真正的 artifact 是 `/junkfood02/youtubedl-android:library`（带 e 和 d）。我第一版写错成 `ytdlp`，导致 Gradle 还是去 JitPack 找 401。

**踩坑过程**：
- 第一版：`io.github.junkfood02.ytdlp-android:library:0.16` → 401（JitPack 找不到）
- 修正：`io.github.junkfood02.youtubedl-android:library:0.18.1` → 200 OK

**教训**：搜 package 坐标时用 Maven Central 搜索（`central.sonatype.com`）确认 artifact 真实存在，别凭印象写。

### 坑 3：包路径不是 README 写的那个

README 里的 import 是 `com.yausername.ytdlp.YoutubeDL`——但 fork 0.18.1 实际 AAR 里的包是 `com.yausername.youtubedl_android.YoutubeDL`（多了 `_android` 后缀）。

**踩坑过程**：
- 第一版 import 用 `com.yausername.ytdlp.*` → 编译报 `Unresolved reference 'ytdlp'`
- 靠 `javap -p` 直接看 AAR 里的 `classes.jar` 实际类路径定 → 改成 `com.yausername.youtubedl_android.*`

**教训**：compile 报 Unresolved reference 别瞎猜包名，用 `javap -p classes.jar` 反推真实路径。

### 坑 4：API 表面跟 README 描述对不上

README 说 callback 是 `YoutubeDLCallback { onYoutubeDLProgress(...) }`——但 0.18.1 实际 API 是：
- callback 改成 Kotlin `Function3<Float, Long, String, Unit>`（progress, etaSeconds, line）
- `getInfo()` 不带 callback（不是 callback API）
- `execute(request, processId, callback)` 才带 callback
- `execute()` 返 `YoutubeDLResponse`（有 `exitCode` / `out` / `err`），不是 void
- `VideoInfo.duration: Int`（秒，0 = 未知）——不是 `Double?`
- `addOption(key, value)` 是分两个参数的——不是 args 列表

**修复**：完整重写 `YtDlpEngine.kt` 和 `DownloadWorker.kt`，按 AAR 实际 API 调。第一版 (`.scratch/phase2_ytdlp_unused/*.kt.bak`) 是基于 README 写的，跟真实 API 全对不上，整个重写。

## 实际写到的 6 个文件 + 1 个测试改

| 文件 | 改动 |
|---|---|
| `gradle/libs.versions.toml` | 换坐标 `io.github.junkfood02.youtubedl-android:library:0.18.1` |
| `app/build.gradle.kts` | 取消 `implementation(libs.ytdlp.android)` 注释 + 加 `ndk.abiFilters` |
| `app/src/main/AndroidManifest.xml` | `extractNativeLibs="true"` + `requestLegacyExternalStorage="true"` |
| `DouBiApplication.kt` | `YoutubeDL.getInstance().init(this)` in onCreate |
| `engine/ytdlp/YtDlpEngine.kt` | 完整重写——`addOption` 分 key/value、Function3 callback、VideoInfo 字段映射 |
| `download/DownloadWorker.kt` | 完整重写——`setForeground(ForegroundInfo(...))` 包装、进度回调每条都刷前台通知、try/catch 显式三态返回 |
| `app/src/test/.../YtDlpEngineTest.kt` | 改测试语义——从「测 stub 行为」改成「测真引擎 catch 兜底行为」 |

## v0.2 测试结果

- **单元测试：46/46 全过**（编译 0 error，单测 0 fail）
  - `ModelTest` 10
  - `AppConfigTest` 13
  - `AppConfigDataStoreTest` 11
  - `YtDlpEngineTest` 11（v0.1 时 4 个 stub 测试 + ConfigToOptions 2 + 新增 5 个真引擎测试）
  - `ExampleUnitTest` 1
- 仪器测试：0（端到端下载需要真手机 + 真网络，v0.3 评估）

## 仍待解决（v0.2 没做、留 v0.3+）

- [ ] **APK 体积**：JunkFood02 fork 自带 ~30MB native libs（yt-dlp 二进制 + Python 3.8 运行时）。完整 `library` 装上后 APK 预计 30~50MB。要做 abi split 按架构分发才能压到 ~10MB / 架构。fmr Android 8 + ARM64 主流机型，可控。
- [ ] **ffmpeg-kit 暂未开**：`io.github.junkfood02.youtubedl-android:ffmpeg:0.18.1` 另开 artifact（+10MB），用于 HLS / 音视频合并 / 抽音频。v0.1 阶段不需要，等 v0.3 真有 B 站/抖音 HLS 需求时再开。
- [ ] **真机端到端测试**：v0.2 单测全过但没在真机/模拟器上跑过——`adb shell am start` 触发 enqueue → WorkManager → 真下载 YouTube 视频 → 通知点击跳到文件管理器。这条路径是阶段 5 的核心验证项。
- [ ] **取消语义**：新 `execute(request, processId, callback)` 第二参是 processId，理论上能用 `YoutubeDL.getInstance().destroyProcessById(processId)` 取消。但目前 `DownloadWorker.cancel()` 走的是 WorkManager 取消，引擎层没有联动——v0.3+ 补。
- [ ] **proguard 规则**：`release` 构建需要保留 `com.yausername.youtubedl_android.*` 类——v0.3+ 商店准备阶段一起处理。

## 阶段 2 v0.2 测试覆盖

| 测试 | 状态 |
|---|---|
| `YtDlpEngineTest::supports YouTube watch URL` | ✅ |
| `YtDlpEngineTest::supports YouTube short URL` | ✅ |
| `YtDlpEngineTest::supports YouTube URL case insensitive` | ✅ |
| `YtDlpEngineTest::supports generic http URL` | ✅ |
| `YtDlpEngineTest::rejects non-URL input` | ✅ |
| `YtDlpEngineTest::engine name is yt-dlp` | ✅ |
| `YtDlpEngineTest::probe returns minimal MediaItem with URL as title when yt-dlp unavailable` | ✅（v0.1 时是 stub 行为，v0.2 时是真引擎 catch 块兜底）|
| `YtDlpEngineTest::probe of non-YouTube URL uses generic platform` | ✅ |
| `YtDlpEngineTest::download returns Failure when yt-dlp not initialized in unit test` | ✅（v0.1 时测 stub 返 Failure 的 reason 文本，v0.2 时只验 Failure 类型）|
| `YtDlpEngineTest::ConfigToOptions maps all relevant fields` | ✅ |
| `YtDlpEngineTest::ConfigToOptions defaults from AppConfig DEFAULTS` | ✅ |

## 下一阶段

阶段 2 完整收官（v0.2 兑底完）。下一步按 [PHASES.md §3](../PHASES.md)：

- **阶段 3：UI 框架**（Compose 导航 + 4 页 + 主题 7 套）——可在 AS 里点 Run 实机/模拟器看了
- 阶段 3 完成后回到阶段 5：进度通知三档 + 通知点击跳文件管理器

