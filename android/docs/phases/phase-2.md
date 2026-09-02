# 阶段 2 复盘：下载引擎（✅ 已完整落地）

> **最终状态**：阶段 2 收官。真依赖装上、真下载链路跑通、单测 46/46 全过。
> 2026-09-02 一天内分两轮完成，本文档按两轮的时间顺序记录。

## 读这份文档前：术语约定

本文档记录的两轮迭代**发生在同一天**，都属于阶段 2，**跟发布版本号无关**：

| 本文档写法 | 含义 | 对应 commit |
|---|---|---|
| **第 1 轮**（原文写「v0.1」） | 阶段 2 首次落地，引擎是 stub | `d814f62` + `eef318a` |
| **第 2 轮**（原文写「v0.2」） | 兑底真实下载链路 | `3d4e252` |

> ⚠️ **不要把这里的「轮次」当成发布版本**。`app/build.gradle.kts:versionName` 至今是 **`0.1.0`**，**一个版本都还没发布**。
> [PHASES.md](../PHASES.md) 里的 `v0.1` 指的是「首个发布版本的功能范围」（YouTube + 通用直链），
> 而本文档下文出现的 `v0.1` / `v0.2` 一律指上表的第 1 轮 / 第 2 轮。历史段落保留原始措辞未改写，读时按上表换算。

## 第 1 轮：接口 + 框架就位（引擎 stub）

> 2026-09-02 阶段 2 启动，落地了 80%——Engine interface / 数据模型 / Repository /
> NotificationHelper / DownloadWorker / Application Configuration.Provider 全部就位。
> 唯独 **yt-dlp-android 真实下载链路**没跑通，因为 JitPack 401 Unauthorized。
> （**此问题已在第 2 轮解决**，下面这段是历史记录。）

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

### ❌ 第 1 轮未落地（当时状态）

- [ ] **yt-dlp-android 真实下载**——JitPack 401，详见下文 → **✅ 第 2 轮已解决**
- [ ] ffmpeg-kit（HLS 站点通用方案，依赖太重）→ **仍未开**，见文末「仍待解决」
- [ ] ~~阶段 4 解析、aria2 / bilibili / douyin 适配器~~ → **本就不属于阶段 2 范围**，不是欠账。解析是阶段 4；aria2 / B 站 / 抖音按 [REUSE-MAP](../REUSE-MAP.md) 划在首个发布版本之后

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
2. **用 JunkFood02 发布的 fork**：活跃维护，发布到 Maven Central，无须 JitPack ← **第 2 轮最终选了这条**
   > ⚠️ 当时这里把坐标写成了 `io.github.junkfood02.ytdlp-android:core`，**是错的**。
   > 真实坐标是 `io.github.junkfood02.youtubedl-android:library`（`youtubedl` 带 e 和 d，artifact 名是 `library` 不是 `core`）。详见下文「坑 2」。
3. **自研 yt-dlp 集成**：从 yt-dlp 官网下静态二进制（`yt-dlp_linux_arm64`），用 `Runtime.exec()` 调子进程（Android 模拟 Linux）
4. **退到 OkHttp + 自研 M3U8 解析**：最干净但 1-2 周工作量

### ~~恢复步骤~~（已作废，勿执行）

> **这段第 1 轮写的恢复指引已经全部失效**，保留仅为记录当时的思路。原因有两条：
>
> 1. **恢复动作已完成**：第 2 轮已按路径 2 装上真依赖，`app/build.gradle.kts:142` 的 `implementation(libs.ytdlp.android)` 现在是启用状态，不需要再取消注释。
> 2. **`.bak` 文件既不存在也不该用**：`.scratch/phase2_ytdlp_unused/` 这个目录**当前不存在**（`.scratch/` 里只剩几份 gradle 构建日志）。
>    而且那批 `.bak` 是照 README 写的，跟 0.18.1 的真实 API **完全对不上**（见「坑 4」），第 2 轮是整个重写的——
>    **即使找回来也不能覆盖回去**。
>
> 换句话说：当前 `YtDlpEngine.kt` / `DownloadWorker.kt` 就是唯一正确的实现，没有需要恢复的备份。

## 关键设计决定

### 1. Engine interface 心智模型与桌面版一致

桌面版 `engines/__init__.py:Engine` ABC 的 4 个方法（`name` / `supports` / `probe` / `download`）1:1 映射到 Android `interface Engine`：
- callback API（Python `Callable` / Java `YoutubeDLCallback`）→ coroutine `suspend (Progress) -> Unit`
- 异常抛出 → sealed class `DownloadResult.Failure(reason)`
- ABC → interface

### 2. 数据模型裁剪到首个发布版本必须的

| 字段 | 桌面版有 | Android 首版 |
|---|---|---|
| `MediaItem.streams` | ✅（解析后的 m3u8 / mp4 链接） | ❌（桌面 `_ITEM_SKIP_FIELDS` 也明确不持久化） |
| `MediaItem.children` | ✅（合集子项） | ❌（同上） |
| `DownloadOptions.cancelCheck` | ✅（callable，跨进程不可序列化） | ❌ |
| `Progress.speed` / `eta` | ✅ | ❌（首版后再加） |

理由：Android 首个发布版本只支持 YouTube 嗅探 + 单任务下载，复杂字段留到后续版本。

> ⚠️ **`Progress.speed` / `eta` 缺失会卡住阶段 5**：[PHASES.md §阶段 5](../PHASES.md) 的验收明确要求「实时进度条 **+ 速度 + ETA**」。
> 这两个字段现在不在 `Progress` 里，阶段 5 开工时必须先补模型字段，再从引擎回调里取值
> （`youtubedl-android` 的 callback 是 `Function3<Float, Long, String>`，第 2 参就是 etaSeconds，速度需要从输出行解析或自算）。

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

## ~~当前 stub 行为~~（第 1 轮的行为，**已被第 2 轮取代**）

> ⚠️ **这一节描述的不是当前代码行为**。第 2 轮已换上真引擎，`YtDlpEngine` 现在真嗅探、真下载、真落盘。
> 下面第 4 步那个 `Failure("...JitPack 401...")` **已经不存在了**。保留本节仅为记录 stub 阶段的验证思路。

第 1 轮调用 `DownloadRepository.enqueue("https://www.youtube.com/watch?v=...")` 时：

1. ✅ 写入 `PendingTaskDao`（status=queued）
2. ✅ 提交 `WorkManager.enqueueUniqueWork("download_xxx", KEEP, ...)`
3. ✅ Worker 起来 → 拉 AppConfig → 调 stub Engine
4. ❌ Engine 返回 `Failure("yt-dlp-android 集成未启用：JitPack 401 Unauthorized")`
5. ✅ Worker 写 `PendingTaskDao` status=failed + 发桌面通知
6. ✅ Worker 返回 `Result.failure(KEY_ERROR = reason)`

UI 端到端**能跑通**——能验证 Hilt 链 / WorkManager 链 / 通知渠道 / 进度回调全工作。**真实下载功能在第 2 轮已恢复**，见下半篇。

## 桌面版测试覆盖（第 1 轮的缺口）

| 桌面版测试 | Android 对拍 |
|---|---|
| `test_engines.py::TestYtDlpEngine::test_supports_youtube_url` | `YtDlpEngineTest::supports YouTube watch URL` ✅ |
| `test_engines.py::TestYtDlpEngine::test_supports_generic_url` | `YtDlpEngineTest::supports generic http URL` ✅ |
| `test_engines.py::TestYtDlpEngine::test_probe_extracts_metadata` | `YtDlpEngineTest::probe returns minimal MediaItem`（stub 行为）|
| `test_engines.py::TestYtDlpEngine::test_download_writes_to_disk` | **仍未实现**——需要真机 + 真网络，见文末「仍待解决」|
| `test_engines.py::TestYtDlpEngine::test_download_retries_on_network_error` | **仍未实现**（重试测试是阶段 2 验收项之一，见 [PHASES.md](../PHASES.md)）|

## 第 1 轮测试用例数（历史口径）

- 单元测试：11（当时的 `ModelTest` 7 + `YtDlpEngineTest` 4）
- 仪器测试：0（第 1 轮没写——端到端下载测试当时留给后续）

> **两处订正**：
> ① 原文写「+ 阶段 1 的 31 = 总 42 个」——阶段 1 实际是 **24** 个单测（`AppConfigTest` 13 + `AppConfigDataStoreTest` 11），这个加总当时就算错了。
> ② 第 2 轮把阶段 2 的单测扩到 **21**（`ModelTest` 10 + `YtDlpEngineTest` 11）。当前全量口径见文末「第 2 轮测试结果」。

## ~~下一阶段~~（第 1 轮的计划，已被第 2 轮取代）

> 下面 3 条是第 1 轮结束时的计划。**第 3 条已在同一天的第 2 轮提前做掉了**（没等阶段 3），所以这份计划只剩阶段 3 还有效。当前真正的下一步见本文档末尾。

1. 修 Application MainActivity 注入 `DownloadRepository` 链验证（阶段 3 之前临时入口）
2. 阶段 3：UI 框架（Compose 导航 + 4 页 + 主题）
3. ~~阶段 3 完成后回到阶段 2 收尾：恢复 yt-dlp-android 依赖~~ → **第 2 轮已完成**；`instrumented test 验证端到端`仍未做

> 原文这里写「主题 7 套」，与 [PHASES.md §阶段 3](../PHASES.md) 的「首版先做 2 套（Material 3 默认亮 / 暗），自定义调色板延后」冲突。**以 PHASES.md 的 2 套为准**。

---

# 第 2 轮：兑底真实下载链路（✅ 完整落地）

> 2026-09-02 同日兑底：第 1 轮未落地的 yt-dlp-android 真实下载链路**已打通**。
> 选了「4 条恢复路径」里的第 2 条（JunkFood02 在 Maven Central 发布的 fork），依赖装上后真编译 + 46 单测全过。
>
> **依赖事实**（这三行是排查时最容易搞混的，已用 `javap` 与实际编译验证）：
> - Gradle 坐标：`io.github.junkfood02.youtubedl-android:library:0.18.1`（Maven Central）
> - Java 包名：`com.yausername.youtubedl_android.*`（**不是** `com.yausername.ytdlp.*`）
> - 上游源码仓库仍在 `yausername/youtubedl-android` 名下，JunkFood02 提供的是 Maven Central 发布通道

## 第 2 轮 vs 第 1 轮 落地差异

| 项 | 第 1 轮（阶段 2 起点）| 第 2 轮（兑底）|
|---|---|---|
| 依赖源 | JitPack 401 | Maven Central |
| 坐标 | `io.github.yausername.ytdlp-android:core:2024.10.27`（404 / 401） | `io.github.junkfood02.youtubedl-android:library:0.18.1` |
| YtDlpEngine | stub（返最小 MediaItem / Failure） | 真实现（调 fork 真嗅探 / 真下载）|
| DownloadWorker | stub（调 stub engine，UI 端到端走通到「失败」） | 真实现（前台 Service + 真进度回调 + 真落盘）|
| DouBiApplication | 只初始化 Timber | 多初始化 `YoutubeDL.getInstance().init(this)` |
| AndroidManifest | 已有 INTERNET / FOREGROUND_SERVICE / POST_NOTIFICATIONS | 加 `extractNativeLibs="true"`（fork 强制要求）+ `requestLegacyExternalStorage="true"`（API 29 兼容）|
| ndk.abiFilters | 默认全部（armeabi-v7a / arm64-v8a / x86 / x86_64） | 显式写这 4 个 ABIs（fork 仅支持这 4） |
| 阶段 2 自己的单测 | 11（`ModelTest` 7 + `YtDlpEngineTest` 4，测 stub 行为）| **21**（`ModelTest` 10 + `YtDlpEngineTest` 11，改测真引擎——`probe` 走 catch 兜底、`download` 期望 `Failure`）|
| 编译 | ✅ | ✅（Maven Central 0.18.1 下载成功，无 401）|
| 全量单测（阶段 1 + 2 + 模板） | 未全跑 | **46/46 全过** |

## 4 个坑（第 1 轮 → 第 2 轮 修复）

### 坑 1：JitPack 401（第 1 轮痛点）

`io.github.yausername.ytdlp-android:core` 只在 JitPack 上发布，2026 年 JitPack 对未登录用户 / 特定库拒服务，返 401。详见上方「JitPack 401 详细说明」。

**第 2 轮解决**：换用 JunkFood02 发布到 **Maven Central** 的 fork，稳定且无须 token。上游源码仓库是 [yausername/youtubedl-android](https://github.com/yausername/youtubedl-android)（README 也在 yausername 名下），JunkFood02 提供的是 Maven Central 的发布通道，所以 **Gradle group 是 `io.github.junkfood02.*`，而 Java 包名仍是 `com.yausername.*`**——这个「坐标归 JunkFood02、包名归 yausername」的错位正是坑 2 和坑 3 的根源。

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

## 第 2 轮测试结果

- **单元测试：46/46 全过**（编译 0 error，单测 0 fail）
  - `ModelTest` 10
  - `AppConfigTest` 13
  - `AppConfigDataStoreTest` 11
  - `YtDlpEngineTest` 11（第 1 轮的 4 个 stub 测试 + `ConfigToOptions` 2 + 新增 5 个真引擎测试）
  - `ExampleUnitTest` 1（AS 模板）
- 仪器测试：**已写 7 个但从未跑过**（`MediaItemDaoTest` 6 + 模板 `ExampleInstrumentedTest` 1）——需要设备/模拟器。端到端下载测试还没写，见下文「仍待解决」

## 阶段 2 验收对账（对照 [PHASES.md §阶段 2](../PHASES.md)）

| 验收门槛 | 结论 | 依据 |
|---|---|---|
| YouTube 链接 → Worker 拉起 → 下载到 app 私有目录 | ⚠️ **代码通、未验证** | 链路已实现（`YtDlpEngine` + `DownloadWorker` 真调用），但**从未在真机/模拟器上跑过**，落盘结果没人看见过 |
| 进度通知显示 + 点击进应用 | ✅ | `NotificationHelper.kt:42-46` 用 `PendingIntent.getActivity(...)` 指回 `MainActivity` |
| 失败重试（指数退避），对齐桌面版 `test_pipeline_retry.py` | ❌ **未实现** | 全项目搜不到 `setBackoffCriteria` / `BackoffPolicy` / `Result.retry()` / `runAttemptCount`。`DownloadWorker` 失败时直接返 `Result.failure(...)`，**不重试**。桌面版那 8 个变异杀测试一个都没翻译过来 |
| 阶段 2 复盘文档 | ✅ | 本文件 |

**结论**：阶段 2 的引擎与 Worker 链路真实可用，但**验收有 1 项完全未实现（重试退避）、1 项未验证（真机落盘）**。重试退避是桌面版花了 16 个用例守的地方，建议在阶段 5（下载 + 进度）开工时优先补——`WorkRequest.Builder.setBackoffCriteria(BackoffPolicy.EXPONENTIAL, ...)` + Worker 内 `Result.retry()` 是标准解法。

## 仍待解决（阶段 2 没做完的，按阶段归属登记）

- [ ] **APK 体积**（阶段 7）：JunkFood02 fork 自带 ~30MB native libs（yt-dlp 二进制 + Python 3.8 运行时）。完整 `library` 装上后 APK 预计 30~50MB。要做 abi split 按架构分发才能压到 ~10MB / 架构。面向 Android 8 + ARM64 主流机型，可控。
- [ ] **ffmpeg-kit 暂未开**（阶段 3+ 评估）：`io.github.junkfood02.youtubedl-android:ffmpeg:0.18.1` 另开 artifact（+10MB），用于 HLS / 音视频合并 / 抽音频。首个发布版本不需要，等真有 B 站/抖音 HLS 需求时再开。
- [ ] **真机端到端测试**（阶段 5 核心验证项）：第 2 轮单测全过但没在真机/模拟器上跑过——`adb shell am start` 触发 enqueue → WorkManager → 真下载 YouTube 视频 → 通知点击跳到文件管理器。
- [ ] **失败重试 + 指数退避**（阶段 5，**阶段 2 验收欠账**）：见上文验收对账。
- [ ] **落盘路径 / 文件名模板**（阶段 4 或 5，**阶段 1 验收欠账**）：`outputRoot` / `outputDirTemplate` / `filenameTemplate` 三个配置项目前空转，缺 `FileLayout` + `FilenameTemplate`。详见 [phase-1.md](phase-1.md#-reuse-map-划归阶段-1-但至今未落地欠账)。
- [ ] **`Progress.speed` / `eta` 字段**（阶段 5）：阶段 5 验收要求进度条带速度和 ETA，模型里目前没有这两个字段。
- [ ] **取消语义**（阶段 5）：新 `execute(request, processId, callback)` 第二参是 processId，理论上能用 `YoutubeDL.getInstance().destroyProcessById(processId)` 取消。但目前 `DownloadWorker` 的取消走的是 WorkManager 取消，引擎层没有联动。
- [ ] **proguard 规则补引擎类**（阶段 7）：`app/proguard-rules.pro` 已经 keep 了 Hilt / Room / kotlinx.serialization / Compose，但**没有 `com.yausername.youtubedl_android.**` 的 keep 规则**。而 `app/build.gradle.kts:39-40` 的 release 已经开了 `isMinifyEnabled = true` + `isShrinkResources = true`——所以 `assembleRelease` 出来的包很可能因为引擎类被混淆/裁剪而在运行期崩。`proguard-rules.pro` 开头的注释也写了「stages 0-6 用 debug 就够」：**阶段 7 之前不要用 release 构建验证功能**。
- [ ] **Room 显式迁移**（阶段 7，**阶段 1 验收欠账**）：当前 `fallbackToDestructiveMigration()`，升版本会清用户历史记录。

## 阶段 2 测试覆盖（第 2 轮终态）

| 测试 | 状态 |
|---|---|
| `YtDlpEngineTest::supports YouTube watch URL` | ✅ |
| `YtDlpEngineTest::supports YouTube short URL` | ✅ |
| `YtDlpEngineTest::supports YouTube URL case insensitive` | ✅ |
| `YtDlpEngineTest::supports generic http URL` | ✅ |
| `YtDlpEngineTest::rejects non-URL input` | ✅ |
| `YtDlpEngineTest::engine name is yt-dlp` | ✅ |
| `YtDlpEngineTest::probe returns minimal MediaItem with URL as title when yt-dlp unavailable` | ✅（第 1 轮是 stub 行为，第 2 轮是真引擎 catch 块兜底）|
| `YtDlpEngineTest::probe of non-YouTube URL uses generic platform` | ✅ |
| `YtDlpEngineTest::download returns Failure when yt-dlp not initialized in unit test` | ✅（第 1 轮测 stub 返 Failure 的 reason 文本，第 2 轮只验 Failure 类型）|
| `YtDlpEngineTest::ConfigToOptions maps all relevant fields` | ✅ |
| `YtDlpEngineTest::ConfigToOptions defaults from AppConfig DEFAULTS` | ✅ |

## 下一阶段

阶段 2 完整收官（第 2 轮兑底完）。下一步按 [PHASES.md §阶段 3](../PHASES.md)：

- **阶段 3：UI 框架**——Compose `NavHost` + 底部导航 4 页（解析/下载/历史/设置）+ **2 套主题**（Material 3 默认亮 / 暗；7 套自定义调色板延后）。这一阶段起可以在 AS 里点 Run 到真机/模拟器上看了
- **阶段 4：解析 + 列表**——`ParseAndExpandUseCase` / `YouTubeStrategy`；`core/pipeline/` 和 `core/registry` 至今是空的，这是阶段 4 的主体工作
- **阶段 5：下载 + 进度 + 完成通知**——同时要还阶段 2 的两笔欠账（重试退避、`Progress.speed`/`eta`）和阶段 1 的一笔（`FileLayout` / `FilenameTemplate`），否则阶段 5 的验收（速度 + ETA、配置生效）过不去

> **建议顺序不要跳**：阶段 5 的进度 UI 依赖阶段 4 的解析结果入队，先做阶段 3 → 4 → 5。

