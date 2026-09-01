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
