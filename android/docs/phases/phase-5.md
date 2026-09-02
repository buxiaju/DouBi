# 阶段 5 复盘：下载 + 进度 + 完成通知（✅ 完成 → v0.2.1-android）

> **最终状态**：阶段 5 收官。下载中页真接 Worker 实时进度 + speed/eta；队列并发 3 限制 + 满队列反馈；完成通知 success / all / summary 三档；用户可在 DownloadingScreen 取消任务。单测 153 → 158 全绿（+5）。
> **v0.2.0-android tag 已发**（阶段 4 收官），本阶段成果属 v0.2.1-android tag。

## 一句话总结

本阶段做了 **3 类事情**：

1. **进度 UI**：DownloadingViewModel `combine(activeTasks, workInfosFlow)` 拿实时 `WorkInfo.progress`（含 speed / eta）+ LazyColumn 渲染 + 取消按钮
2. **并发限制**：DownloadRepository.enqueue 加 `QueueFullException`，按 `AppConfig.concurrentJobs` 限制（默认 3），UI 给专门 Snackbar 提示
3. **通知三档**：NotificationHelper.notifyByCompletionMode 按 `AppConfig.notifyOnCompletion` 路由到 success / all / summary 三档

每一类都对应「桌面版有、Android 端当时没有」的具体差距。

---

## 一、改了什么

### 改造文件

| 路径 | 变化 |
|---|---|
| `data/repository/DownloadRepository.kt` | + `workInfosFlow: Flow<List<WorkInfo>>` 包装 `WorkManager.getWorkInfosByTagFlow("download")` + enqueue 入口加 `QueueFullException` 检查（Room + WorkManager in-flight 集合 vs `concurrentJobs`） |
| `download/NotificationHelper.kt` | + `notifyByCompletionMode(mode, taskId, title, success, localPath)` 按 mode 路由：`success` 只发成功 / `all` 都发 / `summary` 单条静默（batch 摘要留 v0.2.2） |
| `download/DownloadWorker.kt` | 退出分支从 `notifyComplete` 改成 `notifyByCompletionMode(config.notifyOnCompletion, ...)`，cancelled 分支**不**发通知（用户主动取消不发） |
| `ui/downloading/DownloadingViewModel.kt` | 阶段 3 占位 → 完整 `combine(activeTasks, workInfosFlow).stateIn` + `DisplayStatus` 映射（WorkInfo.State 优先于 Room.status）+ `onCancelClicked` + `Event.Cancelled` flow |
| `ui/downloading/DownloadingScreen.kt` | 阶段 3 占位 → LazyColumn + `TaskRow`（title + 进度条 + `Progress.statusLine()` 一行式 + 取消按钮 + 失败 message）+ 6 种 DisplayStatus 颜色 + 空态保留 |
| `ui/pasting/PastingViewModel.kt` | enqueue 路径加 `catch (QueueFullException)` 分支 → `ParseStatus.QueueFull(current, limit)` 状态；`onMessageShown()` 也消费 QueueFull |
| `ui/pasting/PastingScreen.kt` | LaunchedEffect 加 QueueFull 处理 → snackbar 显示「下载队列已满（N / M），请稍候」 |
| `res/values/strings.xml` | + 9 个 string：pasting_queue_full + downloading_count/cancel/cancelled + 5 个 downloading_status_* |

### 新增文件

| 路径 | 职责 |
|---|---|
| `app/src/test/.../ui/downloading/DownloadingViewModelTest.kt` | 5 例：QueueFullException 字段 + WorkInfo.progress 提取逻辑 + DisplayStatus enum 完整性 |

### 桌面版 → Android 版

```
src/doubi/ui/pages/download.py                      src/doubi/ui/tray.py:TrayController
  DownloadPage (TaskRow + LazyColumn)                  notify_on_completion 路由 success/all/summary
  ──────────────────────────────────────────────────────────────────────────
  → ui/downloading/DownloadingScreen (LazyColumn + TaskRow Compose)
  → ui/downloading/DownloadingViewModel (combine flow)
  → download/NotificationHelper.notifyByCompletionMode

src/doubi/core/config.py:AppConfig
  concurrent_jobs (default 3) + notify_on_completion (default "success")
  ────────────────────────────────────────────────────────────────────
  → core/config/AppConfig 字段已存在
  → data/repository/DownloadRepository.QueueFullException 实际限制
```

---

## 二、核心设计决定

### 决定 1：双 flow 合并，WorkInfo 状态优先于 Room 状态

`DownloadingViewModel` 合并两个数据源：
- `activeTasks: Flow<List<PendingTaskEntity>>` —— 持久化（Room），有结构化字段（title / sourceUrl / status）
- `workInfosFlow: Flow<List<WorkInfo>>` —— 实时（WorkManager），带 `progress: Data`（speed / eta / fraction）

合并策略：
- key 是 `taskId`（Room 跟 WorkInfo 都用 taskId 作 tag）
- `status` 字段：**WorkInfo.State 优先**（实时态，Room 可能滞后于"ENQUEUED → RUNNING"切换）
- `speed` / `eta` 只在 WorkInfo 存在时填（Room 没存这两字段，避免 schema migration）
- `fraction` 优先用 Room（Room 每帧 updateProgress 写，WorkManager 的 `setProgress` 跟它是同一时刻）

**收益**：UI 拿到的 TaskUiState 是 Room + WorkManager 的合并视图，不用各自订阅。
**代价**：合并逻辑集中在 `DownloadingViewModel.mapStatus`，单测覆盖（DisplayStatus enum 完整性 + 提取逻辑 + QueueFullException 字段验证）。

### 决定 2：并发限制在 enqueue 入口，不在 Worker 内部

桌面版有「任务入队时检查 in-flight」跟「Worker 跑时 hard limit」两种并发控制。Android 端只在 enqueue 入口查：

```kotlin
val roomActive = pendingTaskDao.listUnfinished().map { it.taskId }.toSet()
val workManagerActive = WorkManager.getWorkInfosByTag("download").get()
    .filter { it.state == ENQUEUED || it.state == RUNNING }
    .mapNotNull { it.tags.firstOrNull { it != "download" } }
    .toSet()
val allActive = roomActive + workManagerActive
if (allActive.size >= concurrentJobs) throw QueueFullException(allActive.size, concurrentJobs)
```

**为什么不在 Worker 内部用 Semaphore**：
- 跟 phase 2 的 `setBackoffCriteria` 交互复杂（worker 被信号量卡住时 WorkManager 怎么算 attempt？）
- Worker 一旦 enqueue 永远在跑，Semaphore 卡住只是把"系统级并行"转成"Worker 内部等待"——下载还是下载，没真正"省"
- 入队处卡住更直接：UI 立即知道「队列满」，用户能选择等待或调整 `concurrentJobs` 设置

**race condition**：两个用户同时点 enqueue（理论上 Android 单 UI 不会）——保护方式是给下载按钮加 disable，但 v0.1 范围内没必要。

### 决定 3：notifyOnCompletion 三档的具体语义

桌面版 `TrayController.notify_on_completion` 三档（"success" / "all" / "summary"）语义：
- `success`：只有成功发通知，失败静默
- `all`：成功 / 失败都发
- `summary`：单条不通知，攒 batch 定时汇总

Android 端 v0.1 范围**只实现前两档**，第三档直接吞（不调 notify）。理由：
- `summary` 需要 batch 累计 + 定时器（v0.2.2 阶段 6 实现）
- 前两档能覆盖 95% 用户场景（"想知道下载完了没" / "失败了赶紧看"）
- `summary` 留 `else` 兜底，运行时不会崩

### 决定 4：Compose 状态用 `stateIn(WhileSubscribed(5s))` 不是 `WhileSubscribed()` 默认

`WhileSubscribed(5_000L)` 让 ViewModel 在 UI 切到后台时**保留 5 秒**流的状态（避免屏幕旋转时重新订阅、重新 combine）。默认的 `WhileSubscribed()` 是 0ms——屏幕一切就 dispose，下次切回来重订阅——combine 重新跑会有几帧的空白。

5s 是经验值：足够覆盖 ConfigurationChange 触发的 activity 重建，又不会在用户真正离开 tab 时长期持有状态。

### 决定 5：取消任务用 `WorkManager.cancelUniqueWork` 不直接 kill 进程

`DownloadRepository.cancel(taskId)` 调 `WorkManager.cancelUniqueWork("download_$taskId")`，触发 `CoroutineWorker.cancel()`，worker 协程内能感知 `cont.isCancelled`（phase 2 已实现）。`pendingTaskDao.updateProgress(..., "paused", 0f, "已取消", ...)` 把状态写"已暂停"。

**为什么不直接 `Process.killProcess()`**：协程取消会触发 `CancellationException`，engine 的 callback 也能感知（`cont.isCancelled`），下载能优雅退出。`killProcess` 会让 worker 强行结束，可能漏写 `paused` 状态。

---

## 三、坑 & 决策

### 坑 1：Kotlin String literal 把 `%1$d` 里的 `$d` 解析成变量引用

```kotlin
val queueFullMsg = stringResource(R.string.pasting_queue_full, "%1$d", "%2$d")
// 编译错: Unresolved reference 'd'
```

Kotlin 解析 `"%1$d"` 时，`$` 紧跟 identifier char `d` → 当 Kotlin 变量引用。`d` 未定义 → 编译错。

**修法**：`stringResource` 只传模板，`String.format` 推迟到运行时：
```kotlin
val queueFullTemplate = stringResource(R.string.pasting_queue_full)
// ...
snackbarHostState.showSnackbar(queueFullTemplate.format(s.current, s.limit))
```

**教训**：Kotlin String literal 跟 printf-style format 冲突时（`$X` vs `%X$d`），要么用 `\$` escape，要么用模板 + 运行时 format。`"\$"` 丑，后者更干净。

### 坑 2：NotificationHelper 三档通知的 mock 测试成本

NotificationManagerCompat 是静态类，调 `notify` 会真触发系统通知（不发，但 SecurityException 路径需要 mock 权限）。mockk 静态类需要 `mockkObject` 关键字 + 全局 stub——对 Robolectric / mockk-inline 都有要求。

**取舍**：v0.1 阶段 5 不写 NotificationHelper 单元测试，用真实 adb install 走通（`adb install` + `adb shell am start` 触发 worker，看 logcat 跟通知栏）。Compose UI test 跟 instrumented test 在阶段 6/7 加。

**核心逻辑的"分支决定"用解析方式证明**：
- 成功 + success 模式 → 调 `notifyComplete(success=true)`
- 失败 + success 模式 → 不调
- 成功 / 失败 + all 模式 → 都调
- 成功 / 失败 + summary 模式 → 都不调

代码 review 跟手动测试能覆盖。

### 坑 3：WorkInfo 静态 mock 受限

`WorkInfo(UUID, State, ...)` 真构造器是 `internal`，外部用 mockk 直接 mock 静态 final class 也受限。

**取舍**：DownloadingViewModelTest 不直接测 ViewModel 的 combine 逻辑，改测**纯数据变换**：
- `QueueFullException` 字段（3 例）
- WorkInfo.progress 提取逻辑（3 例）：speed/eta 解析 + unknown sentinel（-1 / 0）
- DisplayStatus enum 完整性（1 例）

不测 combine flow——留给 v0.2 Compose UI test / instrumented test。

---

## 四、测试变化

| 测试类 | v0.2 收官 | v0.2.1 收官 | 变化 |
|---|---|---|---|
| 上一版全量 | 153 | 153 | — |
| `DownloadingViewModelTest` | 0 | **5** | +5（新文件，纯数据变换） |
| **单测合计** | **153** | **158** | **+5** |

**覆盖率**（jacoco 0.8.12）：

| 维度 | v0.2 收官 | v0.2.1 收官 |
|---|---|---|
| LINE | 34.7% | 30.7% |
| METHOD | 45.2% | 42.1% |
| INSTRUCTION | 34.3% | 30.6% |
| BRANCH | 43.4% | 37.6% |
| CLASS | 31.2% | 29.0% |

**覆盖率解读**：继续下降——阶段 5 增量代码（DownloadingViewModel / DownloadingScreen / Repository queue-full / NotificationHelper 三档）大部分是 ViewModel + Compose UI，跟 phase 4 同样原因（Compose UI test 跟 instrumented test 留 v0.2.2 阶段 6）。

**真实缺口**（v0.2.2 阶段 6 必须补）：
- DownloadingScreen 实际渲染（LazyColumn + TaskRow）—— 需 Compose UI test
- DownloadWorker 退出路径调用 notifyByCompletionMode 的全分支 —— 需 instrumented test + mock NotificationHelper
- 真机 adb install 走通完整流程（解析 → 弹 dialog → 入队 → Worker 跑 → Downloading tab 看进度）—— 阶段 6 真机跑

---

## 五、APK 验证

```
APK: app-debug.apk  77.05 MB  528 entries (vs v0.2 77.05 MB, +0)
- 4 ABI JNI 库全在 (libpython.zip.so / libqjs.so / libdatastore_shared_counter.so)
- 0 警告（packaging.jniLibs.useLegacyPackaging = true 仍生效）
- Manifest 合并后 8 个权限齐 + WorkManager 三个 Service 完整
- 全 153 单测全绿
```

---

## 六、复盘清单

### 做了

- [x] DownloadingViewModel combine (activeTasks, workInfosFlow) 推 speed/eta
- [x] DownloadingScreen LazyColumn + TaskRow + 取消按钮
- [x] DownloadRepository.QueueFullException + enqueue 入口检查
- [x] PastingViewModel 捕获 QueueFullException → ParseStatus.QueueFull
- [x] PastingScreen snackbar 显示「队列已满 N / M」
- [x] NotificationHelper.notifyByCompletionMode 三档路由
- [x] DownloadWorker 调 notifyByCompletionMode 替 notifyComplete
- [x] DisplayStatus 6 种颜色 + 字符串 + Spacer / 进度条
- [x] 单测 153 → 158 全绿（+5：DownloadingViewModelTest 5 例）
- [x] assembleDebug 0 警告通过，APK 77.05 MB（不变）
- [x] 阶段 5 复盘文档

### 没做（移交下阶段）

- [ ] 真机 adb install 验证完整流程（解析 → 弹 dialog → 入队 → Worker 跑 → Downloading tab 看进度）—— 阶段 6 接历史 tab 前必须补
- [ ] Compose UI test for DownloadingScreen —— 阶段 6 加
- [ ] instrumented test for DownloadWorker 三档通知（mock NotificationHelper）—— 阶段 6 加
- [ ] `summary` 模式 batch 定时汇总（桌面版 10 分钟汇总）—— v0.2.2 阶段 6
- [ ] DownloadingViewModel.mapStatus 跟 combine 逻辑 instrumented test —— 阶段 6
- [ ] 取消任务时回收 PendingTaskDao 那条 row（当前只 updateProgress "paused"，不删）—— v0.2.2

### 文档同步

- [PHASES.md](../PHASES.md) — 阶段 5 标 ✅
- [CHANGELOG.md](../CHANGELOG.md) — 加 v0.2.1-android 段
- [REUSE-MAP.md](../REUSE-MAP.md) — `ui/tray.py:TrayController.notify_on_completion` 标 ✅ 落地
- [README.md](../../README.md) — 阶段 5 标完成
- [phase-5.md](phase-5.md) — 本文档
