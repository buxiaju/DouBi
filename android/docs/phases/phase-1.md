# 阶段 1 复盘：数据层 + 配置

> 2026-09-01 完成（与桌面版 CHANGELOG M6.21 同型——「修一个坑，加一层守卫」）

## 完成清单

- [x] 4 个 Room entity（`media_item` / `task` / `pending_task` / `increment_checkpoint`）
- [x] `DouBiDatabase`（version = 1，4 个 entity 注册，WAL 默认启用）
- [x] `Converters`（轻量：只放 `List<String>` ↔ newline-separated String；JSON 留给 Repository 层）
- [x] 4 个 DAO（每个方法一一对照 `src/doubi/core/storage/database.py:Database`）
- [x] `DatabaseModule`（Hilt 注入，`getDatabasePath()` 绝对路径）
- [x] `MediaItemDaoTest` 仪器测试（6 个用例，对拍 `test_storage.py`）

## 与桌面版的一一对应

| 桌面版（Python） | Android 版（Kotlin） |
|---|---|
| `Database.__init__(db_path)` | `DatabaseModule.provideDatabase()` |
| `Database.initialize()` | Room `databaseBuilder().build()` |
| `Database.is_downloaded(platform, item_id)` | `MediaItemDao.isDownloaded(...)` |
| `Database.get_item(...)` | `MediaItemDao.getItem(...)` |
| `Database.record_download(item, save_dir)` | `MediaItemDao.upsert(MediaItemEntity)`（save_dir → `lastSaveDir`） |
| `Database.delete_item(...)` | `MediaItemDao.delete(...)` |
| `Database.list_by_author(...)` | `MediaItemDao.listByAuthor(...)` |
| `Database.list_recent(...)` | `MediaItemDao.listRecent(...)` |
| `Database.record_task(...)` | `TaskDao.upsert(...)` |
| `Database.get_task(...)` | `TaskDao.get(...)` |
| `Database.upsert_pending_task(...)` | `PendingTaskDao.upsert(...)` |
| `Database.delete_pending_task(...)` | `PendingTaskDao.delete(...)` |
| `Database.list_unfinished(...)` | `PendingTaskDao.listUnfinished(...)` |
| `Database.clear_pending_tasks()` | `PendingTaskDao.clear()` |
| `Database.get_checkpoint(...)` | `IncrementCheckpointDao.get(...)` |
| `Database.set_checkpoint(...)` | `IncrementCheckpointDao.upsert(...)` |
| `Database.migrate_from_legacy(...)` | **v0.1 不移植**（Android 没有桌面版那种 dy_downloader.db 旧库可迁） |

## 关键设计决定

### 1. 解决桌面版 `database_path` 相对路径卸载残留坑

桌面版 `core/config.py:45` 的 `database_path` 默认值是相对路径 `"doubi.db"`，程序以安装目录为 cwd 启动时数据库就落在那儿——卸载时 NSIS 删不掉运行期生成的文件（详见桌面版 BUILD §6.5 / DEVELOPMENT §18 已知限制第 9 条）。

Android 版**直接走绝对路径**：

```kotlin
Room.databaseBuilder(context, DouBiDatabase::class.java, DouBiDatabase.DATABASE_NAME)
```

`Context.getDatabasePath("doubi.db")` 解析为 `/data/data/com.doubi.android/databases/doubi.db`，跟随应用卸载一起清。**0.3.1 那个坑直接绕过，不需要数据迁移**。

### 2. JSON 字段放 Repository 层，不放 TypeConverter

桌面版 `database.py` 里 `payload` / `extra` / `options_snapshot` / `item_snapshot` / `config_snapshot` 全是 JSON blob。两种 Android 实现路径：

| 路径 | 代价 |
|---|---|
| **A. TypeConverter 做 Map ↔ JSON** | Room 每次读写都付一次 JSON 解析代价；所有不涉及 JSON 的查询都被连坐 |
| **B. 落库 String，Repository 层做转换** ✅ | DAO 接口干净；JSON 解析只在需要时付一次 |

选 B。`Converters` 暂时只放 `List<String>` ↔ newline-separated String（不依赖 JSON 库就能序列化）。Repository 层用 kotlinx.serialization 在「落库前 / 出库后」转换。

### 3. Flow 暴露给 UI

桌面版 Database 全部是 `async def`，调用方 await。Android 端 DAO 每个读方法提供两个版本：

- `suspend fun ...()`：一次性读，给 Worker / 后台任务用
- `fun ...Flow()`：响应式读，给 Compose UI 订阅用

Compose 端用 `collectAsStateWithLifecycle()` 订阅 Flow，桌面版那种「主动 refresh」模式直接消失。

### 4. 索引命名照搬

`idx_media_author` / `idx_media_time` / `idx_media_publish` / `idx_task_started` / `idx_pending_created` 一一对应桌面版的 `CREATE INDEX` 命名。后续要排查 query plan 时直接对得上。

### 5. `fallbackToDestructiveMigration()` 是 dev 临时

v0.1 schema v1 没历史负担，从 v1 升 v2 时 Room 会清表重建——dev 阶段够用。**阶段 7 切 release 模式时必须改成显式 `Migration` 对象**（否则用户升级版本号时历史下载记录全没）。

## 与桌面版 100% 行为等价的边界

| 操作 | Android | 桌面版 | 说明 |
|---|---|---|---|
| 复合主键 (platform, item_id) upsert | ON CONFLICT REPLACE | `INSERT OR REPLACE` | 等价 |
| 索引 | Room @Index 注解 | `CREATE INDEX` | 等价 |
| WAL 模式 | Room 默认 | `PRAGMA journal_mode=WAL` | 等价 |
| busyTimeout | Room 不暴露（默认 0） | `_BUSY_TIMEOUT_S = 5.0` | Android 单进程基本用不到，但多 Worker 并发时可能撞；阶段 2 评估是否要反射改 |

## 未做的事（明确划在阶段外）

- `Database.migrate_from_legacy()`（桌面版从 dy_downloader.db 旧库迁）—— Android 端无对应历史数据，不做
- `migrate.py` 的 `Bili23 task.db` 读取——同上
- DataStore AppConfig——阶段 1 的下半场，下次开工做
- `MediaItemRow.from_row` / `item_to_json` / `options_to_json` 这套序列化——放 Repository 层，阶段 2 集成 Worker 时一起做

## 桌面版测试的覆盖

| 桌面版测试 | Android 对拍 |
|---|---|
| `test_storage.py::TestDatabase::test_record_download` | `MediaItemDaoTest::upsertAndIsDownloaded` |
| `test_storage.py::TestDatabase::test_record_download_replaces` | `MediaItemDaoTest::upsertReplacesOnConflict` |
| `test_storage.py::TestDatabase::test_list_recent` | `MediaItemDaoTest::listRecent_ordersByDownloadTimeDesc` |
| `test_storage.py::TestDatabase::test_list_by_author` | `MediaItemDaoTest::listByAuthor_filtersAndOrders` |
| `test_storage.py::TestDatabase::test_delete_item` | `MediaItemDaoTest::deleteRemovesRow` |
| `test_storage.py::TestDatabase::test_pending_task_*`（4 个） | 阶段 2 Worker 集成时补 `PendingTaskDaoTest` |
| `test_storage.py::TestDatabase::test_options_roundtrip` | 阶段 1 下半场（DataStore）补 `ConfigSerializerTest` |

**v0.1 Android 端已移植测试数**：6（仪器测试）→ 等阶段 1 下半场 + 阶段 2 完成，目标 30+。

## 同步阶段踩过的 3 个坑（Build → 绿 过程实录）

阶段 1a-1e 写完代码后第一次 sync，**3 个错误连击**，按修复顺序记录如下——下次新模块开工前先看这一段，能少走 2-3 轮 sync 往返。

### 坑 1：`[ksp] java.lang.IllegalArgumentException: ...`（Dagger issue #4680）

**症状**：`assembleDebug` 在 KSP 阶段抛 `IllegalArgumentException`，错误信息是某个字符串 / 版本号 / module 名（不固定，跟具体配置有关）。

**根因**：`gradle.properties` 里 `ksp.useKSP2=true`——KSP 2.0+ 引入的实验性优化，但 Dagger/Hilt 的 KSP 处理器没适配完整，KSP2 模式下会抛 `IllegalArgumentException`（详见 [Dagger issue #4680](https://github.com/google/dagger/issues/4680)）。

**修法**：
```diff
- ksp.useKSP2=true
+ ksp.useKSP2=false   # 阶段 7 前不要开
```

**教训**：KSP2 模式是个隐性坑。`gradle.properties` 里有这行是手痒想用新优化，代价是 Hilt 不稳。`True` 之前必须确认 Hilt 升 2.56+ 且 KSP 升 2.1.x。

### 坑 2：`Unresolved reference 'truth'` / `'assertThat'`

**症状**：`compileDebugAndroidTestKotlin` 失败，`ExampleInstrumentedTest.kt` 和 `MediaItemDaoTest.kt` 都报 `Unresolved reference 'truth'`。

**根因**：AGP 有两套测试作用域，**不共享**：

| 作用域 | 跑在哪 | 配置 |
|---|---|---|
| 单元测试 | JVM（`src/test/`） | `testImplementation` |
| 仪器测试 | 设备/模拟器（`src/androidTest/`） | `androidTestImplementation` |

`truth` 库我加在了 `testImplementation`（给单元测试用），但 `MediaItemDaoTest` 在 `src/androidTest/`，需要的是 `androidTestImplementation`。两套配置互相看不到。

**修法**：
```diff
  androidTestImplementation(libs.androidx.test.ext.junit)
  androidTestImplementation(libs.espresso.core)
  androidTestImplementation(platform(libs.androidx.compose.bom))
+ androidTestImplementation(libs.truth)
```

### 坑 3：`Unresolved reference 'runTest'` + 大量 `Suspend function should be called only from a coroutine`

**症状**：跟坑 2 同时报——`runTest` 找不到，所有 `suspend fun` 调用都报"应该从协程调用"。

**根因**：跟坑 2 同一类——`kotlinx-coroutines-test`（提供 `runTest` / `TestScope`）只加在 `testImplementation`，`androidTest` 那套没加。

**修法**：
```diff
  androidTestImplementation(libs.truth)
+ androidTestImplementation(libs.kotlinx.coroutines.test)
```

### 工具库清单（两边都加的规则）

阶段 1 起，**任何同时在 `src/test/` 和 `src/androidTest/` 使用的库**都得在两处都加：

| 库 | test | androidTest | 用途 |
|---|---|---|---|
| `androidx.test.ext:junit` | — | ✅ | 仪器测试的 JUnit runner |
| `com.google.truth:truth` | ✅ | ✅ | 断言 |
| `org.jetbrains.kotlinx:kotlinx-coroutines-test` | ✅ | ✅ | `runTest` / `TestScope` |
| `io.mockk:mockk` | ✅ | 阶段 2+ | mock（DAO/Worker 测试） |
| `app.cash.turbine:turbine` | ✅ | 阶段 2+ | Flow 测试 |
| `androidx.test.espresso:espresso-core` | — | 阶段 3+ | Compose UI 测试 |

**未来阶段的清单**（`androidTest` 里）：

### 坑 4：Kotlin `companion object` 嵌套 `object` 的作用域盲区（0.3.1 修）

**症状**：`compileDebugKotlin` 报一堆 `Unresolved reference 'DEFAULTS'` + 几条看着吓人的 `Return type mismatch: expected 'kotlin.String', actual 'kotlin.String?'`（其实都同根因——`DEFAULTS` 解析失败 → `if/else` 推断不出 `String`）。

**根因**：`data class AppConfig(val x: T = DEFAULTS.x)` 这种**主构造器默认值参数**不在 `companion object` 的作用域内。具体说：

| 位置 | 能否看到 `AppConfig.DEFAULTS` |
|---|---|
| 主构造器默认值参数 | ❌ |
| 类体内方法 | ✅（`toMap()` 等） |
| 类的 `companion object` 内部 | ✅（`object DEFAULTS` 自己） |
| 外部代码（`ConfigValidator.kt` 等） | ✅（Kotlin 伴生对象自动解析） |

Kotlin 文档里这规则的措辞是「default values for primary constructor parameters are evaluated in a context that has access to the enclosing class, but not necessarily its companion object's nested types」。于是 `val x: T = DEFAULTS.x` 找不到 `DEFAULTS`，编译器一连串报错都从这个失败里冒出来。

**修法**：把 `object DEFAULTS` 提到**文件顶层**（在 `data class` 之外），Kotlin 主构造器默认值作用域能直接看到顶层声明。外部访问从 `AppConfig.DEFAULTS.xxx` 改成 `DEFAULTS.xxx`（同包直接用，跨包加 `import com.doubi.android.core.config.DEFAULTS`）。

```diff
- data class AppConfig(
-     val outputRoot: String = DEFAULTS.outputRoot,
-     // ...
- ) {
-     fun toMap(): Map<String, Any> = mapOf(...)
-     companion object {
-         object DEFAULTS {           ← 找不到，编译失败
-             const val outputRoot: String = "./Downloaded"
-             // ...
-         }
-     }
- }

+ object DEFAULTS {                   ← 顶层可见，构造器能引用
+     const val outputRoot: String = "./Downloaded"
+     // ...
+ }
+ data class AppConfig(
+     val outputRoot: String = DEFAULTS.outputRoot,  ← ✅
+     // ...
+ )
```

**教训**：在 `data class`（或 `class`）的**主构造器默认值参数**里引用**任何**类成员时，包括 `companion object` 里的，都要用全限定名（包括 `this@ClassName.X` 或者顶层 `X`）。只有「直接放在顶层 `object` 旁边」或「在类体内部（不是构造器参数）」用短名才稳。

### 坑 5：智能转型在 `in setOf(...)` / `isNullOrBlank()` 后不生效（0.3.1 修）

**症状**：上一坑修完（`Unresolved reference 'DEFAULTS'` 12 条消失）后，sync 还剩 2 条 `Return type mismatch: expected 'kotlin.String', actual 'kotlin.String?'`，分别指向 `validateDuplicatePolicy` 和 `validateLanguage`。

**根因**：Kotlin 智能转型（smart cast）只在**直接 null 比较**后生效：

```kotlin
// ✅ value 被 smart-cast 成 String，if 分支返回 String
if (value != null && value in setOf(...)) value

// ❌ 编译器不 smart-cast——`in` 是函数调用（Set.contains），不保留转型
if (value in setOf(...)) value

// ❌ isNullOrBlank() 虽然能推出非空，但 Kotlin 编译器不据此 smart-cast
// （保守——因为 isNullOrBlank 内部有 trim() 等调用，可能有副作用）
if (!value.isNullOrBlank() && value in setOf(...)) value
```

不写 `value != null` 时，if 分支里的 `value` 类型还是 `String?`，整条 `if/else` 表达式 LUB 是 `String?`，与函数声明的 `String` 不符。

**修法**：所有走白名单的 validator **都加显式 `value != null` 前缀**。

```diff
- fun validateDuplicatePolicy(value: String?): String =
-     if (value in setOf("skip", "redownload", "ask")) value
-     else DEFAULTS.duplicatePolicy
+ fun validateDuplicatePolicy(value: String?): String =
+     if (value != null && value in setOf("skip", "redownload", "ask")) value
+     else DEFAULTS.duplicatePolicy

- fun validateLanguage(value: String?): String =
-     if (!value.isNullOrBlank() && value in setOf("zh_CN", "en")) value
-     else DEFAULTS.language
+ fun validateLanguage(value: String?): String =
+     if (value != null && value in setOf("zh_CN", "en")) value
+     else DEFAULTS.language

+ // validateTheme 同样问题（同一个错误模式）
+ fun validateTheme(value: String?): String =
+     if (value != null && value in setOf("default_light", "default_dark")) value
+     else DEFAULTS.theme
```

**教训**：在 Kotlin 里写 `if (x != null && x in collection)` 是惯用法，**别图省事**用 `isNullOrBlank()` / `isNullOrEmpty()` / `in` 替代 null 检查——编译器的 smart cast 不吃这套，会静默退化为 `String?`，跑到运行期才暴露。**所有 nullable 收窄**都走 `x != null` 或 `x is T` 这条直路。
- 阶段 2 加 `mockk`（mock `WorkManager` 入口）
- 阶段 3 加 `espresso`（Compose UI 自动化）

## 下半场（阶段 1.5）：DataStore AppConfig

阶段 1a 提的「下半场」现已完成，阶段 1 整体闭环。

### 完成清单

- [x] `core/config/AppConfig.kt`（data class，30 字段对拍桌面 `core/config.py:AppConfig`）
- [x] `core/config/ConfigValidator.kt`（8 个白名单 + 2 个 clamp，补齐桌面版未做的项）
- [x] `data/config/ConfigKeys.kt`（30 个 DataStore Preferences Keys，snake_case 与 YAML 兼容）
- [x] `data/config/AppConfigDataStore.kt`（read / write / observe / updateField / 校验透传）
- [x] `data/config/di/DataStoreModule.kt`（Hilt 注入，`preferencesDataStoreFile("doubi_config")`）
- [x] `core/config/AppConfigTest.kt`（12 个用例：默认值 + 8 个 validator）
- [x] `data/config/AppConfigDataStoreTest.kt`（10 个用例：roundtrip / null↔空串 / observe / 校验回退 / clamp）

### 关键设计决定

#### 1. DataStore Preferences 而非 Proto DataStore

桌面版是单个 YAML 文件、读一次 → 整个 dict。Android 端用 **Preferences DataStore**（每字段一个 typed key）而非 Proto DataStore——30 个简单标量字段用 Proto 是过度设计。

#### 2. Optional<String> 用空串 sentinel

桌面版 `rate_limit: Optional[str]` 在 YAML 里就是 key 缺失；DataStore Preferences 没有 nullable string。约定：null ↔ 空串。受影响字段：`rate_limit` / `proxy` / `aria2_secret`（3 个）。

#### 3. sniff_capture_types：Set ↔ List 转换

桌面版 `tuple[str, ...]` 有序，DataStore `stringSetPreferencesKey` 无序。约定：写时 `List.toSet()`，读时 `Set.toList().sorted()`。5 项默认值按字母排后顺序会变，**但内容一致**——对嗅探功能无影响（Set 语义本来就无序）。

#### 4. ConfigValidator 全面落地

桌面版只 `_validate_notify_mode`，**其他字段没 clamp**——「bad value in config.yml 应该永远不会让 app 启动崩」（原话），但用户输入疯狂值（`concurrent_jobs=0` 或 `-1`）会让 Worker 池炸掉。Android 端把校验全补上：

| 字段 | 桌面版 | Android 端 |
|---|---|---|
| `notify_on_completion` | 白名单 3 项 | 同（白名单） |
| `engine` | 无校验 | 补白名单 `yt-dlp` / `aria2` |
| `concurrent_jobs` | 无 clamp | clamp 到 [1, 16] |
| `sniff_duration_sec` | 无 clamp | clamp 到 [5, 60] |
| `sniff_capture_types` | 无校验 | null/空 → 回退默认 |
| `duplicate_policy` | 无校验 | 白名单 `skip` / `redownload` / `ask` |
| `language` | 无校验 | 白名单 `zh_CN` / `en` |
| `theme` | resolve 容忍未知 | v0.1 白名单 2 项，阶段 3 扩到 7 项 |

**所有白名单/边界/回退绝不抛异常**——坏值静默回退默认，与桌面版原则一致。

#### 5. updateField 走 switch 而非反射

DataStore 没有 key 字符串到 Preferences.Key 的内省 API（Proto DataStore 才容易做）。30 个 key 写在 `when` 里硬编——是 boilerplate，但读起来直白，加新字段时 `else -> throw IllegalArgumentException` 编译器会逼你更新。

### 与桌面版 100% 行为等价的边界

| 字段类型 | 桌面版 | Android 端 | 等价？ |
|---|---|---|---|
| 标量字符串 | `str` | `String` | ✅ |
| 标量布尔 | `bool` | `Boolean` | ✅ |
| 标量整数 | `int` | `Int` | ✅ |
| 可空字符串 | `Optional[str]` | `String?` + 空串 sentinel | ✅ 字段语义对，写盘格式不同 |
| 元组 | `tuple[str, ...]` | `List<String>` | ✅ 字段语义对，Set 写盘顺序不同 |
| 路径 | `pathlib.Path` | `String` | ✅ 字段语义对；Android 端所有路径都是绝对 |
| 字典 | `dict[str, Any]` | 不在 AppConfig（用单独 KV 覆盖） | ⚠️ 桌面版 `extra` 字段 Android 端暂不实现 |

`extra` 字段 v0.1 暂不实现——设置页用不到，Worker 也用不到。阶段 6 扩设置页时再加 `Map<String, String>` 形式的覆盖机制。

### 桌面版测试覆盖

| 桌面版测试 | Android 对拍 |
|---|---|
| `test_config_theme.py::TestConfigTheme::test_default_values` | `AppConfigTest::defaults match desktop core config py DEFAULTS` |
| `test_config_theme.py::TestConfigTheme::test_notify_on_completion_*` (5 例) | `AppConfigTest::notify_on_completion whitelist + rejects unknown` |
| `test_config_theme.py::TestConfigTheme::test_roundtrip` | `AppConfigDataStoreTest::save then get roundtrips all 30 fields` |
| `test_config_theme.py::TestConfigTheme::test_yaml_optional_fields` | `AppConfigDataStoreTest::nullable fields roundtrip null correctly` |
| 桌面版没有的 clamp 测试 | `AppConfigTest + DataStoreTest::updateField concurrent_jobs clamps to 1-16`（Android 端补的） |

**v0.1 阶段 1 测试用例数**：
- 单元测试：22（`AppConfigTest` 12 + `AppConfigDataStoreTest` 10）
- 仪器测试：6（`MediaItemDaoTest`）
- 共 **28 用例**

全部走 JUnit 4 + Truth + runTest，**单测全 JVM 跑**，CI 能直接接。

### 阶段 1 整体收尾

阶段 1 闭环 = **Room 数据层 + DataStore 配置层**。后续所有阶段（Worker / Compose UI / 设置页）都消费这两个底层。

- 阶段 2：Worker 读 `concurrentJobs` / `engine` / `outputRoot` / `outputDirTemplate` / `filenameTemplate`
- 阶段 6：设置页读/写 `theme` / `language` / `notifyOnCompletion` / `promptBeforeDownload` / `duplicatePolicy` / `write*` / `sniff*`
- 阶段 4：嗅探读 `sniffEnabled` / `sniffDurationSec` / `sniffCaptureTypes` / `maxQuality` / `container` / `resume`

## 下一步

按 [PHASES.md §2](../PHASES.md)：

1. 解锁 `app/build.gradle.kts` 里两行注释掉的 `ytdlp-android` / `ffmpeg-kit` 依赖
2. 写 `engine/Engine.kt` interface（与桌面版 `engines/__init__.py:Engine` ABC 心智模型一致）
3. 写 `engine/ytdlp/YtDlpEngine.kt`（包装 yausername/yt-dlp-android）
4. 写 `download/DownloadWorker.kt`（CoroutineWorker + 前台 Service 通知）
5. 写 `download/NotificationHelper.kt`（进度通知，三档 follow 桌面版 `notifyOnCompletion`）
6. 在 `MainActivity` 注入 `AppConfigDataStore` 验证 Hilt 链路通
7. 端到端：YouTube 链接 → 解析 → Worker 拉起 → 落盘到 app 私有目录
