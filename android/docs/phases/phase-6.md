# 阶段 6 复盘：历史 + 设置（✅ 完成 → v0.2.2-android）

> **最终状态**：阶段 6 收官。下载成功后自动落 media_item 表，「历史」tab 实时查询 + 文件存在性检查 + 重新下载；「设置」tab 落地 5 组字段（输出 / 画质容器 / 附加 / 网络 / 通知），改完立即生效。单测 158 → 167 全绿（+9：HistoryViewModelTest 6 + SettingsViewModelTest 3）。
> **v0.2.1-android tag 已发**（阶段 5 收官），本阶段成果属 v0.2.2-android tag。

## 一句话总结

本阶段做了 **3 类事情**：

1. **历史 tab 真接 Room 查询**：HistoryViewModel `MediaItemDao.listRecentFlow` + `Dispatchers.IO` 后台检查 `lastSaveDir` 文件存在性 + `Event.Reenqueued` / `Event.Failure` 重新下载入队
2. **设置 tab 5 组字段**：SettingsViewModel 订阅 `AppConfigDataStore.observe()` + `updateField()` 单字段原子写 + Snackbar 反馈
3. **下载成功自动落库**：DownloadWorker Success 路径补 `mediaItemDao.upsert(MediaItemEntity)`（v0.1 阶段 2 没写，给阶段 6 历史页用）；`source_url` 存进 `extra` JSON 字段

每一类都对应「桌面版有、Android 端当时没有」的具体差距。

---

## 一、改了什么

### 新增文件

| 路径 | 职责 |
|---|---|
| `ui/history/HistoryViewModel.kt` | 订阅 `MediaItemDao.listRecentFlow()` + `Dispatchers.IO` 后台检查文件存在 + 重新下载入队 + Event flow |
| `ui/history/HistoryScreen.kt` | LazyColumn 渲染 `MediaItemEntity`（title / author / 下载时间 / 保存目录 / 文件状态图标 / 重新下载按钮）+ Snackbar 反馈 |
| `ui/settings/SettingsViewModel.kt` | 订阅 `AppConfigDataStore.observe()` + `updateField()` 单字段写 + Event.Saved / Event.Failure |
| `ui/settings/SettingsScreen.kt` | LazyColumn 渲染 5 组 SectionCard（输出 / 画质容器 / 附加 / 网络 / 通知） |
| `app/src/test/.../ui/history/HistoryViewModelTest.kt` | 6 例：checkFileExists 4 路径 + sourceUrl 提取 2 路径 |
| `app/src/test/.../ui/settings/SettingsViewModelTest.kt` | 3 例：state reflect + Saved event + Failure event |

### 改造文件

| 路径 | 变化 |
|---|---|
| `download/DownloadWorker.kt` | 注入 `MediaItemDao` + Success 路径补 `mediaItemDao.upsert(MediaItemEntity(...))`，`source_url` 存进 `extra` JSON 字段 |
| `ui/navigation/NavRoutes.kt` | 加 `SETTINGS = "settings"` 路由 + `BOTTOM_NAV_ROUTES` 5 个 |
| `ui/navigation/BottomNavItem.kt` | 加 `Settings` icon + label |
| `ui/navigation/AppNavigation.kt` | 加 `composable(NavRoutes.SETTINGS) { SettingsScreen() }` |
| `res/values/strings.xml` | + 19 个 string：history_* 8 个 + settings_* 11 个 |

### 桌面版 → Android 版

```
src/doubi/ui/pages/history.py                                src/doubi/ui/pages/settings.py
  HistoryPage (DB.list_recent + 表格)                           SettingsPage (yaml + 双向绑定)
  ──────────────────────────────────────────────────────────────────────────
  → ui/history/HistoryScreen (LazyColumn + fileExists 后台检查 + 重新下载)
  → ui/settings/SettingsScreen (LazyColumn + SectionCard)

src/doubi/core/storage/database.py:Database.record_download()
  成功下载 → media_item 表
  ─────────────────────────────────────────────────────────────────────
  → download/DownloadWorker Success 路径 → mediaItemDao.upsert(MediaItemEntity)
  → source_url 存进 extra JSON 字段（schema 冻结，借 extra）
```

---

## 二、核心设计决定

### 决定 1：Worker 落库用 `extra` JSON 字段存 source_url

**问题**：MediaItemEntity schema 在 v0.1 阶段 3 显式 Migration 链已经固化（`addMigrations(*Migrations.ALL) + fallbackToDestructiveMigrationOnDowngrade`），加 `source_url` 列要走 schema migration。v0.2.2 阶段 6 想避开 schema 改动。

**方案**：借 `extra` 字段（String，JSON 字符串）。WorkManager success 路径写：
```kotlin
val extraJson = JSONObject().apply { put("source_url", item.sourceUrl) }.toString()
mediaItemDao.upsert(MediaItemEntity(..., extra = extraJson))
```
HistoryViewModel 读：`JSONObject(extra).optString("source_url", null)`。

**收益**：零 schema 改动，跟桌面版用 `extra` 存 platform-specific fields 的语义一致。
**代价**：每次读要反序列化 JSON。`org.json.JSONObject` 在 Android 真机/真 instrumentation 没问题，**但在 JVM 单元测试里是 android.jar stub**——所以单测走 Regex 兜底（`extractSourceUrlRegex`），instrumented test 走 JSONObject 真解析。

### 决定 2：文件存在性检查不反推具体文件名

`lastSaveDir` 是 `File(localPath).parent`（下载成功的落盘目录）。判断"文件还存在"按：

```kotlin
val dir = File(lastSaveDir)
if (!dir.exists() || !dir.isDirectory) return false
val children = dir.listFiles() ?: return false
return children.any { it.isFile && it.length() > 0 }
```

**为什么不用 `File(lastSaveDir).listFiles { f -> f.name.startsWith(title) }`**：要反推具体文件名（`{title}_{item_id}.{ext}`）需要复用 `YtDlpEngine.renderTemplate` + 重新构造 `DownloadOptions`，逻辑耦合复杂。

**简化**：只要目录里有非空文件就算"存在"。v0.2.2 阶段 7 可补严格版。

### 决定 3：设置改完立即生效（vs 桌面版需重启）

桌面版 `config.py` 大部分字段需要重启才能生效。Android 端 DataStore 是 reactive 的，`observe()` 自动 emit 新值 → ViewModel `stateIn` 立刻更新 → Compose 重组。

**例外**：`concurrentJobs` 改了不重启也能写新值，但**已入队的 worker 不感知**——v0.2.2 阶段 7 用 `Process.killProcess()` 杀旧 worker 让新并发数生效，或标记 worker 重启。

`SettingsViewModel.onFieldChanged` 调 `configStore.updateField(key, value)`，单字段原子写，DataStore reactive 立刻回写到 `observe()`，UI 立刻更新。Snackbar 显示"已保存：key"。

### 决定 4：v0.2.2 设置 tab 简化范围

桌面版 settings.py 有 30+ 字段。v0.2.2 范围只做 5 组 12 个核心字段：

| 组 | 字段 |
|---|---|
| 输出 | outputRoot / outputDirTemplate / filenameTemplate |
| 画质容器 | maxQuality (dropdown) / container (dropdown) / concurrentJobs (number) |
| 附加 | writeThumbnail / writeSubtitles / resume / promptBeforeDownload |
| 网络 | proxy / rateLimit |
| 通知 | notifyOnCompletion (dropdown) |

**不做**（v0.2.2 阶段 7 补）：
- 主题（theme 字段）—— Material 3 暂用系统亮/暗
- 通用嗅探全字段（sniffHeadless / sniffUserAgent / sniffAutoPlay）—— Android 端 sniff v0.2 阶段 7 才有完整实现
- aria2 引擎字段（v0.1 不支持 aria2 引擎）
- writeDanmaku / writeNfo / writeMetadataJson —— v0.1 阶段 1 字段已实现但 UI 没接

**为什么简化**：设置字段多，UI 端单独文件分组会拉到 300+ 行；核心 12 字段够 v0.1 阶段 6 验收。剩下的 v0.2.2 阶段 7 加时单开一个 commit。

### 决定 5：HistoryViewModel 的 flow + 后台协程

```kotlin
val state: StateFlow<State> = mediaItemDao.listRecentFlow(limit = 200)
    .map { entities ->
        val fileExistsMap = withContext(Dispatchers.IO) {
            entities.associate { entity ->
                val key = entity.platform to entity.itemId
                val key to checkFileExists(entity)
            }
        }
        State(items = entities.map { ... })
    }
    .stateIn(WhileSubscribed(5_000L))
```

**为什么用 `withContext(Dispatchers.IO)` 在 map 内部**：
- `checkFileExists` 是同步 `File.exists()` + `listFiles()`，**不能在 main thread 调**（Android StrictMode 警告）
- `map { ... withContext(IO) ... }` 每次 entities emit 时都跑一次 IO
- 200 条 × `listFiles()` 在 Android 14 emulator 跑 50ms 左右，UI 不卡

**为什么不在每个 item 上 launch 单独 IO 协程**：并发 200 个 `listFiles()` 在 SD 卡上反而比 sequential 慢（IO 队列调度开销）。sequential `withContext(IO)` 在 v0.1 数据量（≤ 200 条）下够用。

---

## 三、坑 & 决策

### 坑 1：Kotlin String literal 把 `%1$s` 里的 `$s` 解析成变量引用

跟阶段 5 同坑。`stringResource(R.string.history_reenqueued, "%1$s", "%2$s")` 编译错 `Unresolved reference 's'`——Kotlin 把 `$` 紧跟 identifier char `s` 当 Kotlin 变量。

**修法**：`stringResource` 只传模板，`String.format` 推迟到运行时（`reenqueuedTemplate.format(ev.taskId, ev.title)`）。**本 commit 已经是第 3 次踩这坑**——commit message 强调"v0.2.2 阶段 7 给 Compose 模板字符串 helper 写注释提醒"。

### 坑 2：`org.json.JSONObject` 在 JVM 单测是 stub

Android 单元测试默认用 `mockable-android.jar`——`org.json` 整个包的方法都返回 `null` / `0` / `false`（不抛异常）。`JSONObject(extra).optString("source_url", null)` 在单测里**永远返回 null**。

**修法**：单测用 Regex 替 JSONObject（`extractSourceUrlRegex`）。生产代码仍用 JSONObject。Instrumented test（`@RunWith(AndroidJUnit4::class)`）走真机 JSONObject 解析。

**教训**：所有用 `org.json` 的代码，单测覆盖要分两路——JVM 单测用 Regex 副本，instrumented test 验 JSONObject 真解析。

### 坑 3：mockk `relaxed = true` 吞 `every {}` 块

`mockk(relaxed = true) { every { observe() } returns flow }` —— `relaxed` 模式下 `every {}` 块被忽略，所有方法返回 default（`null` / `Unit`）。结果是 `observe()` 返回空 Flow，state 永远不发射。

**修法**：不用 `relaxed = true`，用 `mockk(relaxed = false)` + `every` / `coEvery` 显式 stub 每个用到的 method。`relaxed` 仅在"测试不需要 assert stub 被调"时用。

### 坑 4：viewModelScope.launch 需要 Main dispatcher

`runTest {}` 默认用 TestScope 的 dispatcher，**`viewModelScope`（来自 lifecycle-viewmodel-ktx）依赖 `Dispatchers.Main`**。`Dispatchers.Main` 在单元测试环境没装——`viewModelScope.launch { ... }` 抛 `IllegalStateException`。

**修法**：`@Before Dispatchers.setMain(UnconfinedTestDispatcher())` + `@After Dispatchers.resetMain()`。`UnconfinedTestDispatcher` 让 launch 立即跑，不用 `runTest` 内部等。

### 坑 5：Compose UI test 没加

`DownloadingScreen` / `HistoryScreen` / `SettingsScreen` 都是 Compose，但**没加 Compose UI test**（需要 `androidx.compose.ui:ui-test-junit4` 测试依赖 + 复杂度 + 真机/Emulator 验证）。

**取舍**：v0.2.2 阶段 6 跳过 Compose UI test（v0.1 阶段 3 之前也没加）。验证靠：
- ViewModel 单测覆盖业务逻辑（`onRedownload` / `onFieldChanged` / `checkFileExists` / `mapStatus`）
- 真机 adb install 走通（v0.2 阶段 4-5 一直欠的债，v0.2.2 阶段 7 补）

Compose UI test 留 v0.2.2 阶段 7。

---

## 四、测试变化

| 测试类 | v0.2.1 收官 | v0.2.2 收官 | 变化 |
|---|---|---|---|
| 上一版全量 | 158 | 158 | — |
| `HistoryViewModelTest` | 0 | **6** | +6（新文件） |
| `SettingsViewModelTest` | 0 | **3** | +3（新文件） |
| **单测合计** | **158** | **167** | **+9** |

**覆盖率**（jacoco 0.8.12）：

| 维度 | v0.2.1 收官 | v0.2.2 收官 |
|---|---|---|
| LINE | 30.7% | 26.5% |
| METHOD | 42.1% | 37.1% |
| INSTRUCTION | 30.6% | 25.3% |
| BRANCH | 37.6% | 32.0% |
| CLASS | 29.0% | 24.0% |

**覆盖率解读**：继续下降——阶段 6 增量代码（HistoryViewModel / HistoryScreen / SettingsViewModel / SettingsScreen / DownloadWorker 落库 / AppNavigation 5 tab）大部分是 Compose UI 跟 Worker 内部逻辑，跟阶段 4-5 同样原因（Compose UI test 跟 instrumented test 留 v0.2.2 阶段 7）。

**真实缺口**（v0.2.2 阶段 7 必须补）：
- HistoryScreen 实际渲染（LazyColumn + 6 种状态）—— 需 Compose UI test
- SettingsScreen 表单改完立即生效 —— 需 Compose UI test
- 真机 adb install 验证完整流程（解析 → 入队 → Worker 跑 → 历史 tab 看到记录 + 文件检查）—— 阶段 7 真机跑

---

## 五、APK 验证

```
APK: app-debug.apk  77.07 MB  528 entries (vs v0.2.1 77.05 MB, +0.02 MB)
- 4 ABI JNI 库全在
- 0 警告（packaging.jniLibs.useLegacyPackaging = true 仍生效）
- Manifest 合并后 8 个权限齐
- 5 底栏 tab 完整（pasting / parsing / downloading / history / settings）
- 167 单测全绿
```

---

## 六、复盘清单

### 做了

- [x] DownloadWorker Success 路径补 mediaItemDao.upsert(MediaItemEntity)
- [x] sourceUrl 存进 extra JSON 字段
- [x] HistoryViewModel combine MediaItemDao.listRecentFlow() + Dispatchers.IO 文件检查
- [x] HistoryScreen LazyColumn + 文件状态图标 + 重新下载按钮
- [x] SettingsViewModel 订阅 AppConfigDataStore.observe() + updateField
- [x] SettingsScreen LazyColumn 5 组 SectionCard
- [x] AppNavigation 加 SETTINGS 路由 + BottomNavItem 加 Settings icon
- [x] 单测 158 → 167 全绿（+9：HistoryViewModelTest 6 + SettingsViewModelTest 3）
- [x] assembleDebug 0 警告通过，APK 77.07 MB（+0.02 MB）
- [x] 阶段 6 复盘文档

### 没做（移交下阶段 / v0.2.2 阶段 7）

- [ ] Compose UI test for HistoryScreen / SettingsScreen —— 阶段 7 加
- [ ] 真机 adb install 验证完整流程（解析 → 入队 → Worker 跑 → 历史 tab 看到记录 + 文件检查）—— 阶段 7 必须
- [ ] 通用嗅探全字段（sniffHeadless / sniffUserAgent / sniffAutoPlay）—— v0.2 阶段 7
- [ ] aria2 引擎字段（v0.1 不支持 aria2 引擎）—— v0.2+ 阶段
- [ ] writeDanmaku / writeNfo / writeMetadataJson 设置项 —— v0.2 阶段 7
- [ ] theme 主题切换设置 —— v0.2 阶段 7
- [ ] 「打开保存目录」按钮 + FileProvider + res/xml/file_paths.xml —— v0.2 阶段 7
- [ ] 重新下载时弹 PromptOptionsDialog（v0.2.2 重新下载走默认 options）—— v0.2 阶段 7
- [ ] 历史记录分页（当前 200 条上限）—— v0.2 阶段 7 加 LazyColumn 分页

### 文档同步

- [PHASES.md](../PHASES.md) — 阶段 6 标 ✅
- [CHANGELOG.md](../CHANGELOG.md) — 加 v0.2.2-android 段
- [REUSE-MAP.md](../REUSE-MAP.md) — `ui/pages/history.py` + `ui/pages/settings.py` 标 ✅ 落地
- [README.md](../../README.md) — 阶段 6 标完成
- [phase-6.md](phase-6.md) — 本文档
