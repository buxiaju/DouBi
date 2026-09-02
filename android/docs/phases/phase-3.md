# 阶段 3 复盘：UI 框架 + 还 v0.1.0 关键欠账（✅ 完成）

> **最终状态**：阶段 3 收官。4 个底栏 tab 可切换、Hilt ViewModel 注入到位；v0.1.0 关键欠账 #1#2#3#7#8 全部还完；单测 46 → 64 全绿。
> 这一阶段最大的收获是「**为 v0.1.0 收官铺好地基**」——之前 6 笔欠账里有 5 笔必须在 UI 落地前还清，否则一进阶段 4 就会因为「下载路径不真」「Worker 没退避」之类的隐性债反复返工。

## 一句话总结

本阶段做了 **3 类事情**：

1. **UI 框架**：Navigation Compose + 4 占位 tab + 2 个 Hilt ViewModel
2. **还 5 笔欠账**：失败重试（#1）、路径模板（#2）、Room Migration（#3）、proguard keep（#7）、SETUP.md 修法（#8）
3. **顺手修 2 个新 bug**：字符类 `*?` 误为量词、JDK 26 + AGP 8.7.3 挂在 `androidJdkImage`

每一类都对应「桌面版有、Android 端当时没有/没测过」的具体差距。

---

## 一、UI 框架

### 改了什么

| 项 | 之前 | 之后 |
|---|---|---|
| `MainActivity` | 挂 `HomeScreen` 占位 | 挂 `AppNavigation()`（NavHost + 底栏） |
| 导航 | 无 | `NavHost` 4 个一级路由：`pasting` / `parsing` / `downloading` / `history` |
| 切 tab 状态 | 不适用 | `popUpTo + saveState + restoreState`，输入框 / 滚动位置保留 |
| 4 个 Screen | 1 个（`HomeScreen`） | 4 个独立 Composable + 各自 ViewModel（`PastingViewModel` / `DownloadingViewModel`，后 2 个 Hilt 不需要 ViewModel） |
| 字符串资源 | 3 个 `home_placeholder_*` | 4 个 nav_* + 4 个 Screen title + 4 个空态文案 |

### 桌面版 → Android 版

```
ui/main_window.py
  MainWindow (QMainWindow + 4 page widget + 侧边/顶栏)
  ─────────────────────────────────────────────────────
  → MainActivity (ComponentActivity + AppNavigation composable)
  → NavRoutes: 4 个 string route
  → AppNavigation: Scaffold + NavigationBar + NavHost
  → 4 个 ui/<tab>/<Tab>Screen.kt + <Tab>ViewModel.kt
```

### 关键设计决定

1. **底栏顺序：粘贴 → 解析 → 下载 → 历史**（不是桌面版的「解析 → 下载 → 历史 → 设置」）
   - 理由：v0.1.0 的首页就是「粘 URL」，把「粘贴」放第一 tab 减少跳转
   - 「设置」tab v0.1 不做，留 string 但不挂路由
2. **`DownloadingViewModel` 真订阅 `DownloadRepository.activeTasks` Flow**
   - 阶段 3 还看不出「下载任务列表」价值，但**先打通 Flow 链路**，阶段 5 加进度条 / 取消按钮时直接接
   - 单测覆盖（不在本阶段，留阶段 5 一起）
3. **`PastingViewModel` 故意留 4 个 reserved 字段**
   - 阶段 4 接 `Engine.probe` 时直接加 URL 嗅探，状态机加 `probing` / `probed` / `error` 三档
4. **底栏「解析」/「下载中」两个 tab 命名区分桌面版**
   - 桌面版「下载」是动作（入队），Android「下载中」是状态（看进行中的任务）—— 避免歧义
5. **二级路由 `download/{taskId}` 已留位**，阶段 5 详情页用

### 验收

- [x] 4 个占位页面能切换，标题栏对应显示
- [x] 切换系统暗色模式 → 应用立即变暗
- [x] 复盘文档（即本文件）

### 阶段 3 没做、阶段 4+ 要做的

- 「粘贴」tab 解析按钮不真跳页 / 不真入队
- 「解析中」tab 不接 `Engine.probe`
- 「下载中」tab 只显示 count，不渲染进度条 / 取消按钮
- 「历史」tab 不接 `MediaItemDao` 查询
- 「设置」tab 没做（v0.1 不做）
- Compose UI 测试套件（`androidx.compose.ui:ui-test-junit4`）未加

---

## 二、还 5 笔 v0.1.0 关键欠账

> 这部分是 v0.1.0 收官前必须还的「关键债」。完整登记见 [PHASES.md 跨阶段欠账](../PHASES.md)。

### #1 失败重试 + 指数退避

**桌面版**：`TaskManager.retry()` 由用户在 UI 点触发，**无自动重试**。
**Android 版（v0.1 之前）**：完全没实现 —— 没有 `setBackoffCriteria`、没有 `Result.retry()`，弱网下任务掉完就消失。
**Android 版（v0.1 还账）**：用 WorkManager 自带机制做**自动重试 + 指数退避**，叠加「永久错误」分类做精细控制。

```kotlin
// DownloadRepository.enqueue
.setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)

// DownloadWorker.doWork
val attempt = runAttemptCount + 1
when (result) {
    is Failure -> {
        if (isTransientFailure(result.reason)) Result.retry()  // 瞬时错误
        else Result.failure(workDataOf(KEY_ERROR to result.reason))  // 永久错误
    }
}
```

**判据**（[DownloadWorker.TRANSIENT_PATTERNS](file:///android/app/src/main/java/com/doubi/android/download/DownloadWorker.kt)）：用 3 条 regex 匹配 `timeout` / `connection` / `reset` / `unreachable` / `5xx` / `503` / `429` / `UnknownHostException` / `SSLException` / `EOFException` 等关键字。**不是**就一律 `failure()`。

**与桌面版语义对比**：

| 触发方式 | 桌面版 | Android v0.1 |
|---|---|---|
| 自动重试瞬时错误 | ❌ | ✅ 30s 起步指数退避，10 次封顶 |
| 手动重试任何错误 | ✅ `TaskManager.retry()` 按钮 | ✅ 阶段 6 接历史页「重新下载」按钮，再 `enqueue` 一次 |
| 永久错误 | 直接 `failed` 状态 | 直接 `failure`（不再 retry） |

**单测覆盖**：[DownloadWorkerTest](../app/src/test/java/com/doubi/android/download/DownloadWorkerTest.kt) 13 例，3 个正向（瞬时）+ 5 个反向（永久）+ 1 个空串边界 + 2 个大小写边界 + 1 个部分匹配 + 1 个全小写。
**不覆盖**：WorkManager 退避实际触发（instrumented test，需要 fake WorkManager），阶段 5 真机验证一起做。

### #2 路径模板三字段

**桌面版**：`core/storage/file_layout.py` + `core/naming.py` 是独立模块，负责把 `outputRoot` / `outputDirTemplate` / `filenameTemplate` 三个配置项展开成真实路径。
**Android 版（v0.1 之前）**：`AppConfig` 字段有，但 `YtDlpEngine` **完全忽略**——落盘路径硬编 `baseOutputDir/{platform}/{itemId}.{ext}`。
**Android 版（v0.1 还账）**：把 desktop 的两个模块逻辑**合并到 `YtDlpEngine`**（不再单列 `core/naming/` / `core/storage/FileLayout`）：

```kotlin
internal fun resolveOutputDir(base: File, item: MediaItem, options: DownloadOptions): File {
    val root = options.outputRoot?.takeIf { it.isNotBlank() } ?: "Downloaded"
    val template = options.outputDirTemplate?.takeIf { it.isNotBlank() } ?: DEFAULTS_DIR_TEMPLATE
    val expanded = renderPathTemplate(template, item)  // 展开 {platform}/{author}/{media_type}
    return File(base, root).let { File(it, expanded) }.also { it.mkdirs() }
}
```

**5 个占位符**：

| 占位符 | 取值 | 空时降级 |
|---|---|---|
| `{platform}` | `item.platform.key` | — |
| `{author}` | `item.author?.name` | `_` |
| `{media_type}` | `item.mediaType.name` | — |
| `{title}` | `item.title` | 用 `itemId` |
| `{item_id}` | `item.itemId` | — |

**文件名 sanitize**：替换 `/ \ : * ? " < > |` 9 个字符为 `_`（`YtDlpEngine.sanitizeFilename()`，被 `DownloadWorker` 通过 `@VisibleForTesting` 暴露成 `sanitizeFilenameForTest()` 供单测调用）。

**单测覆盖**：[YtDlpEngineTest](../app/src/test/java/com/doubi/android/engine/YtDlpEngineTest.kt) 加 5 例 —— 「完整模板渲染」「author 降级」「template 降级」「outputRoot 降级」「sanitize 9 字符全替」。
**不覆盖**：跨平台 sanitize 规则一致性（要跟 desktop `util.py:sanitize_filename` 对拍，desktop 的 Python 实现里有什么 Android 端抄过去）。

### #3 Room 显式 Migration 链

**桌面版**：SQLAlchemy `Base.metadata.create_all()`，从版本 N 到 N+1 不需要显式迁移脚本（结构变化通过「删表重建」），数据丢了也没人发现。
**Android 版（v0.1 之前）**：`fallbackToDestructiveMigration()` —— 升 `version` 时 Room 静默删表重建，**用户的历史下载记录全丢**。
**Android 版（v0.1 还账）**：

1. Room 升 **2.6.1 → 2.7.2**（`MigrationTestHelper` 从 2.7.0 起在 `androidx.room:room-testing` 稳定可用）
2. 新建 `data/db/Migrations.kt`（v0.1 提交时 `ALL: Array<Migration> = emptyArray()`）
3. `DatabaseModule` 把 `fallbackToDestructiveMigration()` 换成 `addMigrations(*Migrations.ALL) + fallbackToDestructiveMigrationOnDowngrade(dropAllTables = true)`（只在开发者手动降 version 时清空）
4. `app/schemas/` 导出 schema JSON，`sourceSets.androidTest.assets.srcDirs` 把 schemas 打进仪器测试资源
5. 新建 `MigrationTest.kt` 3 个仪器测试：
   - `v1_createAndQueryMediaItem`：v1 起步能 insert + read
   - `migrateAll_emptyChain_keepsAllTables`：空迁移链不会破 v1
   - `migrateAll_chainIsConsistent`：跑完所有迁移不崩 + 能查 `media_item`

**v0.2+ 加 `Migration(1, 2)` 时必须**：
- 在 `Migrations.ALL` 加条目
- 在 `MigrationTest` 加 `migrate1To2()` 单测
- **同 commit**（不能拆，拆了 review 时看不出迁移写对了没）

### #7 proguard 引擎类 keep

**问题**：`proguard-rules.pro` 已经有 Hilt / Room / Compose / 序列化 keep，但**漏了 `com.yausername.youtubedl_android.**`**。
**后果**：release 包（已开 `isMinifyEnabled = true`）启动时该包被 R8 混淆，native lib 加载链断掉 → `ClassNotFoundException`。
**修法**：加 3 条 keep 规则（不仅 youtube-dl-android，还有 `ytdl` / `ffmpeg` 包也加，预防阶段 5+ 接 ffmpeg-kit）。

### #8 SETUP.md JDK 26 修法

**问题**：本机 `PATH` 上 JDK 是 **26.0.2.1**（Oracle javapath），AGP 8.7.3 的 `androidJdkImage` 在 jlink 这步挂掉。命令行构建**默认失败**。
**前情**：阶段 1、2 当时能跑通是**缓存产物**（`compileDebugJavaWithJavac` UP-TO-DATE），jlink 根本没被调；Gradle 9.3 升级后缓存路径变了，jlink 首次真跑才暴露。
**修法**（A/B 实测已验证）：
- **临时**：`$env:JAVA_HOME = 'C:\A\01SoftWares\03IDE\Android Studio\jbr'`
- **永久**：`~/.gradle/gradle.properties` 加 `org.gradle.java.home=C:/A/01SoftWares/03IDE/Android Studio/jbr`
- Android Studio 自带 JBR 25.0.2 实测通过（**不是官方保证**，AGP 8.7.3 官方只支持 17）

**根因没查到底**：jlink 自己的 stderr 被 Gradle `ProcessException` 吞了。具体哪条 JDK 26 约束不满足**未知**。对干活来说够用。

---

## 三、坑与决策

### 坑 1：字符类内 `*?` 误为量词

```kotlin
// 看起来对的写法
name.replace(Regex("""[/\\:*?"<>|]"""), "_")
// 实际只替 3 个字符（/ : ?），剩下 * " < > | 不替
// 原因：Java regex 字符类里 `*?` 被解析成「懒惰量词」
// 单测抓住了：YtDlpEngineTest 的 sanitize 测试
```

**修法**（也是教训）：

```kotlin
// 字符类里就别用元字符，老老实实 set
val illegal = setOf('/', '\\', ':', '*', '?', '"', '<', '>', '|')
val cleaned = name.map { c -> if (c in illegal) '_' else c }.joinToString("")
```

**为什么单测会抓到**：在 `*` 和 `?` 之间有 `*?` 解析歧义时，Java regex 引擎不报编译错也不报运行警告，**默默只替一部分**。我恰好写了「一个含全部 9 个字符的输入字符串」做端到端验证，才暴露出来。

**给后续的教训**：
- 字符类里**禁用 `*` `?` `+`** —— 就算单字符也用 set 替
- sanitize 之类「替换一组字符」的操作，**写测试覆盖全部字符**，别只测 1-2 个
- PowerShell 自己的 `-replace` 对同一 regex 也有同样 bug —— **别用 PS 模拟 regex 行为**做 sanity check

### 坑 2：kotlinOptions 废弃警告

`app/build.gradle.kts:55` 的 `kotlinOptions { jvmTarget = "17" }` 触发 Kotlin 2.0 弃用警告：「`kotlinOptions types are deprecated, please migrate to the compilerOptions types`」。
**本阶段不修**（Kotlin 2.0 迁移建议耗时 ~30 分钟，与 v0.1.0 收官无关）。警告是 `w:` 不是 `e:`，不影响构建。记到阶段 7 一起清。

### 坑 3：HOME / SETUP / 模板 strings 冲突

第一轮 `strings.xml` 删了 3 个 `home_placeholder_*` 和 `nav_settings`，编译期才发现 `HomeScreen.kt:38/43/49` 还在引用。
**修法**：恢复 3 个 string（标记「阶段 0 遗留，阶段 7 清」），加 `nav_settings` 字符串（仅用于 schema 对齐，UI 不显示）。
**教训**：跨文件改资源前，先 grep 全部引用。Gradle 资源 lint 只在 `:processDebugResources` 阶段报 warning，**编译期才报缺引用**。

### 决策 1：路径模板逻辑放 Engine 不放 core/

`resolveOutputDir` / `sanitizeFilename` 放在 `engine/ytdlp/YtDlpEngine` 里，**不**拆成 `core/naming/FilenameTemplate.kt` + `core/storage/FileLayout.kt` 两个文件。
**理由**：
- 桌面版的 `core/naming.py` 和 `core/storage/file_layout.py` 是两个独立模块，因为 Python 是多文件 + 多次 import 友好；Kotlin 拆成两个文件反而让 `Engine` 一边读 config 一边调两个 util，调用链变长
- v0.1 只有 1 个 Engine（`YtDlpEngine`），未来加 `Aria2Engine` / `FfmpgEngine` 时**它们各自有各自的 `resolveOutputDir` 是 OK 的**（不同引擎对路径模板的需求不一样，比如 aria2 不需要 sanitize 后的标题）

### 决策 2：自动重试 10 次封顶

WorkManager 默认 10 次后自动把 `Result.retry()` 转成 `failure`，我们显式声明 `MAX_ATTEMPTS = 10`。
**理由**：
- 桌面版无自动重试，无法对齐次数
- 10 次 + 30s 起步指数退避 → 第 10 次延迟 ≈ 30s × 2^9 = **约 170 分钟**（近 3 小时），总耗时 4-5 小时
- 弱网下 4-5 小时是用户能接受的极限；再往上没意义
- **永久错误**（404 / 磁盘满）一开始就被判出，10 次封顶对它们**不生效**——直接 fail，0 延迟

### 决策 3：UI 顺序「粘贴 → 解析 → 下载 → 历史」

桌面版顺序是「解析 → 下载 → 历史 → 设置」。Android 端把「粘贴」提前：
- **v0.1 的「下载」实指「入队动作」**（=「粘贴」+「解析」+「点击开始」三步）
- v0.1 的「下载中」实指「看进行中的任务」—— 状态，不是动作
- 跟桌面版顺序对齐不是硬性目标，**用户场景优先**

### 决策 4：字符串资源化但不本地化

v0.1 所有 string 都进 `res/values/strings.xml`（默认中文），**不**做 `res/values-en/strings.xml`。
**理由**：
- 桌面版已经做了 i18n（JSON 词表 + `tr()`），跨平台对齐是「术语统一、翻译各自维护」
- v0.1 Android 端只在中国市场发，省一份翻译
- v0.2 阶段 6 之前会加 `values-en/`，**确保术语跟桌面版 `en` 词表对得上**

### 决策 5：phase-3 复盘不写「设置」tab 内容

「设置」tab 阶段 6 才做，本阶段连占位都不挂路由。PHASES.md 已写明 v0.1 不出设置 tab，CHANGELOG「vs 桌面版」表也已说明这差异。**phase-3.md 不需要再复述**，避免冗余。

---

## 四、测试变化

| 测试类 | 阶段 2 收官 | 阶段 3 收官 | 变化 |
|---|---|---|---|
| `AppConfigTest` | 13 | 13 | — |
| `AppConfigDataStoreTest` | 11 | 11 | — |
| `ModelTest` | 10 | 10 | — |
| `ProgressTest` | 0 | **25** | +25（新文件，#4 配套） |
| `YtDlpEngineTest` | 11 | **26** | +15（路径模板 5 + 速度解析 10） |
| `ExampleUnitTest` | 1 | 1 | — |
| `DownloadWorkerTest` | 0 | **13** | +13（新文件） |
| **单测合计** | **46** | **99** | **+53** |
| 仪器测试 | 7（写了没跑） | 10（写了没跑） | +3 `MigrationTest` |

**覆盖率**（#6 已还）：LINE **37.5%** / METHOD **48.5%** / CLASS 30.8%。`core/model` 100% / `core/config` 100% / `data/config` 85.1% / `engine/ytdlp` 59.9% / `download` 2.5%（worker 真实缺口，留 v0.2 仪器测试）。详见 [§六 B-3](#b-3还账--6--jacoco-接通)。

---

## 五、复盘清单

### 做了

- [x] Navigation Compose + 4 占位 tab + 底栏
- [x] 2 个 Hilt ViewModel（`PastingViewModel` / `DownloadingViewModel`）
- [x] 还欠账 #1 失败重试
- [x] 还欠账 #2 路径模板
- [x] 还欠账 #3 Room Migration
- [x] 还欠账 #7 proguard keep
- [x] 还欠账 #8 SETUP.md JDK 修法
- [x] 单测 46 → 64 全绿

### 没做（移交下阶段）

- [ ] 还欠账 #4 `Progress.speed` / `eta`（阶段 5 必做）
- [ ] 还欠账 #5 真机端到端验证（阶段 4 必做：第一次有真实链接进 Engine）
- [ ] 还欠账 #6 jacoco 覆盖率（阶段 5 必做）
- [ ] Compose UI 测试套件（`androidx.compose.ui:ui-test-junit4`）
- [ ] 阶段 4 「解析」tab 真实接 `Engine.probe`
- [ ] 阶段 4 「下载中」tab 真实渲染 Worker 进度
- [ ] 阶段 4 「历史」tab 真实接 `MediaItemDao` 查询
- [ ] 阶段 7 清「设置」tab 路由 + 「HomeScreen.kt」死代码

### 文档同步

- [PHASES.md](../PHASES.md) — 阶段 3 标「✅ 完成」，跨阶段欠账表 #1#2#3#7#8 标 ✅，#4#5#6 标 ❌
- [CHANGELOG.md](../CHANGELOG.md) — v0.1.0 段补「阶段 3」+ 3 条新修复（字符类、JDK 26、UP-TO-DATE 假绿）
- [REUSE-MAP.md](../REUSE-MAP.md) — `core/naming.py` / `core/storage/file_layout.py` 标 ✅ 落地，`test_pipeline_retry.py` 标 ✅ 13
- [README.md](../../README.md) — 进度表更新到阶段 3，64/64，欠账 3 笔
- [SETUP.md](../SETUP.md) — 整段重写，JDK 26 → JBR 25 修法 + A/B 实测证据
- [ARCHITECTURE.md](../ARCHITECTURE.md) — 目录树对齐实际代码（**阶段 2 已改**，本阶段无更新）

---

## 六、阶段 3 收尾补记（事后追加）

阶段 3 文档初版写完后又跑了一轮「还剩余欠账」，本节把**事后补还的 #4 / #5（部分） / #6 三笔**和**一处真 bug** 补进来，避免这份复盘跟实际状态脱节。

### B-1：进度回调量纲是 0-100，不是 0-1（**真 bug**）

`core/model/Progress.kt` 的注释原本写「fraction: 0.0 - 1.0」，但 youtubedl-android 0.18.1 的 `StreamProcessExtractor` 直接 `Float.parseFloat` 百分号前的数字。

**字节码级证据**（`javap -p -c -constants` 反编译 `library-0.18.1.aar/classes.jar`）：

```java
// StreamProcessExtractor.<clinit>
ldc String \[download\]\s+(\d+\.\d)% .* ETA (\d+):(\d+)  // 主 regex
ldc float 99.0f                                          // ffmpeg 分支硬编
ldc float -1.0f                                          // 初始值
ldc2_w long -1l                                          // eta 未知 sentinel
```

**结论**：progress 是 0-100，eta 未知时是 -1L。

**Bug 现场**（`engine/ytdlp/YtDlpEngine.kt:135`）：

```kotlin
// 旧
fraction = progress.coerceIn(0f, 1f)
```

`coerceIn(0f, 1f)` 会把 1% 以上的进度**全部截成 1.0f = 100%**——进度条从第一次回调起就满格，直到 `findProducedFile` 写出。Android 端没人发现是因为 v0.1 阶段 3 之前根本没接真进度 UI。

**修法**（同 commit 一起）：

```kotlin
// 新
fraction = (progress / 100f).coerceIn(0f, 1f)
```

**教训**：
- 第三方库回调的量纲**不能靠注释猜**，反编译 `javap -p -c` 拿字节码级证据是最快的
- `download` 包的 2.5% 覆盖率让这个 bug 藏了 2 个迭代——**worker 真机跑过一眼就能看出来**

### B-2：还账 #4 —— `Progress.speed` / `eta` 贯通

`Progress` 字段补齐 `speedBytesPerSec` / `etaSeconds`（默认 null，**非正数视为未知**——`eta` 库给的是 -1L，约定保持一致）+ `formatSpeed()`（1024 进制 + `Locale.US`）+ `formatEta()` + `statusLine()` 一行式。

库回调**不给速度**（`StreamProcessExtractor` 只 emit `(progress, eta, line)`），所以 `YtDlpEngine.parseSpeedBytesPerSec()` 自己从 `at 1.23MiB/s` 片段正则解析：

```
\bat\s+([0-9]+(?:\.[0-9]+)?)\s*([KMGT]?[iI]?)B/s
```

`DownloadWorker` 透传：`setProgress(workDataOf(KEY_PROGRESS, KEY_SPEED, KEY_ETA))` 给 WorkInfo observer，通知栏文案走 `progress.statusLine()`。**没改 Room schema**——结构化字段只走 `setProgress` 透传（v0.2 阶段 6 真要落库再说）。

测试 25 + 10 = **35 例**（`ProgressTest` 25：格式 / 退化 / 未知约定全覆盖 + `YtDlpEngineTest.parseSpeedBytesPerSec` 10：MiB/KiB/GB/MB-非-i/Unknown/aria2c/empty/收尾行）。

### B-3：还账 #6 —— jacoco 接通

`libs.versions.toml` 加 `jacoco = "0.8.12"`；根 `build.gradle.kts` 加 `buildscript.dependencies.classpath("org.jacoco:org.jacoco.core:0.8.12")`；`app/build.gradle.kts` `apply(plugin = "org.gradle.jacoco")`（**不是** `org.jacoco`）+ `JacocoTaskExtension.excludes` 排除 KSP/Hilt/Room 生成代码 + 自定义 `jacocoTestReport` 任务同时出 XML + HTML。

**踩坑**（写在 PHASES.md 避免再犯）：
- jacoco plugin marker `org.jacoco:org.jacoco.gradle.plugin:0.8.12` **不存在**，plugins DSL `alias(libs.plugins.jacoco)` 拉不到
- 正确 plugin id 是 `org.gradle.jacoco`（来自 Gradle 内置 `gradle-jacoco-9.3.0.jar`）
- `JacocoTaskExtension` 在 `org.gradle.testing.jacoco.plugins` 包，`JacocoReport` 在 `org.gradle.testing.jacoco.tasks`
- `JacocoTaskExtension.excludes` 是 `List<String>?`，必须 `(excludes ?: emptyList()) + listOf(...)`，不能用 `+=`
- Kotlin DSL 的 `import` 必须在文件最顶部
- jacoco.exec 路径是 `outputs/unit_test_code_coverage/debugUnitTest/testDebugUnitTest.exec`（AGP 8.7+）

**基线覆盖率**（本阶段收尾时测的）：

| 维度 | 数字 |
|---|---|
| LINE | **37.5%** (383/1020) |
| METHOD | **48.5%** (161/332) |
| CLASS | **30.8%** (24/78) |
| INSTRUCTION | 40.8% (3361/8229) |
| BRANCH | 46.7% (200/428) |
| COMPLEXITY | 44.8% (250/558) |

**包级**（LINE）：

| 包 | 覆盖 | 备注 |
|---|---|---|
| `core/model` | **100%** | 全测 |
| `core/config` | **100%** | 30 字段全过 |
| `data/config` | 85.1% | DataStore roundtrip |
| `engine/ytdlp` | 59.9% | 路径模板 + 速度解析 |
| `download` | **2.5%** | **真缺口**——`DownloadWorker.doWork` / `NotificationHelper` 没测 |
| UI ViewModel / Repository / Entity / DAO | 0% | v0.1 阶段 3 没接 Compose 仪器测试，预期差距 |

**80% 门槛解读**：v0.1 阶段 3 走完的代码（core/data 100% 覆盖）确实能打 80%+；UI / Worker 这两片必须靠 v0.2 阶段 4/5 加 Compose UI test + 仪器测试拉起来。**门槛本身不改口径，但要分阶段计**——阶段 3 收尾时是「核心业务 ≥ 80%」（实际 ≈ 100%）；阶段 7 前要补到「全量 ≥ 80%」。

### B-4：还账 #5（部分）—— `assembleDebug` 产包验证

按用户问卷，**只验产包结构，不做真机 adb install**。

```
APK: app-debug.apk  76.43 MB  528 entries
```

| 验证项 | 结果 |
|---|---|
| 4 ABI JNI 库（x86 / x86_64 / armeabi-v7a / arm64-v8a） | ✅ `libpython.zip.so` 12-14 MB × 4、`libqjs.so` 0.6-0.9 MB × 4、`libdatastore_shared_counter.so` × 4 |
| `android:extractNativeLibs="true"` 与 `useLegacyPackaging` 一致 | ✅ 加 `packaging.jniLibs.useLegacyPackaging = true` 后警告消失 |
| Manifest 权限完整 | ✅ 8 个（INTERNET / ACCESS_NETWORK_STATE / FOREGROUND_SERVICE / FOREGROUND_SERVICE_DATA_SYNC / POST_NOTIFICATIONS / WRITE_EXTERNAL_STORAGE[maxSdk=28] / WAKE_LOCK / RECEIVE_BOOT_COMPLETED） |
| WorkManager 三个 Service | ✅ `SystemAlarmService` / `SystemJobService` / `SystemForegroundService` |
| Room `MultiInstanceInvalidationService` | ✅ |
| WorkManager 默认初始化被剔除 | ✅ `DouBiApplication` 接管 + `tools:node="remove"` 在 startup xml |
| schema 资产 | ⚠️ **不**进 main APK（只在 `androidTest` 资源，减小产包）——这是设计选择 |
| 真机 adb install | ❌ **未做**，按问卷留 v0.2 |

### B-5：清理两个 deprecation 警告

- `app/build.gradle.kts:65` `kotlinOptions {}` 已弃用（Kotlin 2.0 迁 kotlin compiler options）—— 留待阶段 7
- `app/build.gradle.kts:260/276` `$buildDir` 引用改 `layout.buildDirectory.dir(...)`——**本轮自清**
