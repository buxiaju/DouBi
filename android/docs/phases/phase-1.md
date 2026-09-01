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
- 阶段 2 加 `mockk`（mock `WorkManager` 入口）
- 阶段 3 加 `espresso`（Compose UI 自动化）

## 下一步

按 [PHASES.md §1.1 下半场](../PHASES.md)：

1. **`data/datastore/AppConfigSerializer.kt`**：把 `core/config.py:AppConfig` 的 25 个字段搬成 DataStore Preferences
2. **`core/config/AppConfig.kt`**：Kotlin data class，对拍 Python 版本字段（camelCase）
3. **`core/config/ConfigRepository.kt`**：Hilt 注入 + 读/写/观察 AppConfig
4. **`AppConfigTest.kt`**：与 `test_config_theme.py` 对拍（`notify_on_completion` 三档往返、非法值回退、默认值、YAML 字段名一致）
