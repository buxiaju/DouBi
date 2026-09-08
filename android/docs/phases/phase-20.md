# 阶段 20 复盘：B 站 API 客户端 5min TTL 缓存（✅ 完成 → v0.5.10-android）

> **最终状态**：阶段 20 收官。v0.5.9-wip 阶段 19 留的"mixin_key / X-Bogus 缓存"欠账**部分**落地——B 站 3 个端点（fetchMixinKey / view / playurl）走 5min 内存缓存。**X-Bogus 缓存**延后到 v0.5.9 完整版（真算法完成后再 wire）。339/339 单测全绿（v0.5.9-wip 327 + 12 新增），`assembleDebug` 通过。
> **v0.5.9-wip-android tag 已发**（阶段 19 收官），本阶段成果属 v0.5.10-android tag。
>
> **versionName 跳号** 0.5.8 → 0.5.10：v0.5.9-wip 是 chore-style WIP tag（不 bump），显式跳号避免 0.5.9 完整版时跟 v0.5.9-wip 混淆。

## 一句话总结

本阶段做了 **3 类事情**（按 commit 顺序）：

1. **[TimeBasedCache<K, V>]** —— 通用 TTL 内存缓存（`suspend getOrLoad` 模式 + 线程安全 + 注入 clock），未来 XBogusSigner / 抖音 API 客户端都能用
2. **B 站 3 个端点 wire 缓存**：
   - `fetchMixinKey()` —— 全局 key="global"（mixin_key 是 B 站服务端单值）
   - `view(bvid)` —— 按 bvid 分 key
   - `playurl(bvid, cid, qn)` —— 按 `"$bvid:$cid:$qn"` 3 元组分 key
3. **versionCode 16→17 + versionName 0.5.8→0.5.10**

**没做**（v0.5.11+ 单独 PR）：

- **X-Bogus 缓存**——v0.5.9-wip 仍 stub chaos，X-Bogus 真算法落地后**才**能 wire（X-Bogus 真算法依赖真 API 验证，v0.5.9 完整版 → v0.5.11 之间）
- **-352 风控时强制失效** —— 当前缓存**不**主动失效，-352 风控时需等 5min 过期
- **按 UA 分 key** —— USER_AGENT 当前写死常量，AppConfig.userAgent 落地后再分
- **TTL 配置化** —— v0.5.10 硬编码 5min，AppConfig.apiCacheTtl 落地后再配置
- **抖音 API 客户端缓存** —— DouyinApiClient.awemeItemInfo 暂**不**加缓存（X-Bogus 没通真 API 时缓存是 stub 数据）
- m3u8 v7+ HLS encryption / 多 variant 选择 UI / WebViewHeadlessSniffer 自身单测（Robolectric）/ ANR 风险测试 / DefaultWebViewFactory 配置 instrumented test

---

## 一、改了什么

### 新增文件

| 路径 | 作用 |
|---|---|
| `app/src/main/java/com/doubi/android/core/util/TimeBasedCache.kt` | 通用 TTL 内存缓存 utility（`suspend getOrLoad` + 线程安全） |
| `app/src/test/java/com/doubi/android/core/util/TimeBasedCacheTest.kt` | 6 例单测（cache miss / hit / expire / null 防御 / invalidate / clear） |
| `docs/phases/phase-20.md` | 本文档 |

### 修改文件

| 路径 | 变化 |
|---|---|
| `app/src/main/java/com/doubi/android/core/platform/bilibili/BilibiliApiClient.kt` | 加 `mixinKeyCache` / `viewCache` / `playurlCache` 3 个 [TimeBasedCache] 字段 + 3 个对应 endpoint 改 `getOrLoad` 模式 |
| `app/src/test/java/com/doubi/android/core/platform/bilibili/BilibiliApiClientTest.kt` | 加 6 例 cache 测试（fetchMixinKey × 2 + view × 2 + playurl × 2） |
| `app/build.gradle.kts` | versionCode 16→17；versionName "0.5.8"→"0.5.10"（**跳号**——v0.5.9-wip 不算正式版本） |

### vs 桌面版

```
桌面版 `src/doubi/utils/cache.py:TimeBasedCache`（v0.4.1 阶段 4 落地的磁盘 JSON 缓存）
  ─────────────────────────────────────────────────
  → 阶段 20 v0.5.10：TimeBasedCache utility（core/util/）—— 内存版简化（**不**持久化）
```

**vs 桌面版简化**：
- 桌面版磁盘 JSON 缓存（**不**同进程重启后命中）—— Android 端**不**需要持久化（应用冷启动重新 fetch，~200ms 一次性延迟可接受）
- 桌面版支持更多策略（max size / TTL per key / multi-store）—— Android 端 v0.5.10 范围 single-store + 统一 TTL，v0.5.11+ 按需扩展

---

## 二、核心设计决定

### 决定 1：抽 [TimeBasedCache] 通用 utility（**不**直接做 BilibiliApiClient 内部缓存）

**问题**：缓存代码**只**给 B 站用**不**？还是抽成通用 utility？

**v0.5.10 方案**：

- 抽 `core/util/TimeBasedCache<K, V>` 通用 utility
- 5 个 commit（v0.5.10 Commit 1-4）都用同一个 [TimeBasedCache] 实例化
- v0.5.11+ XBogusSigner / 抖音 API 客户端 / settings cache 都能复用

**理由**：

- **复用**——v0.5.11+ 加 XBogus 缓存时**不**重写 ConcurrentHashMap 包装
- **可测**——[TimeBasedCache] 单独 6 例单测，**不**依赖具体 cache key
- **desktop 1:1 对拍**——桌面版 [src/doubi/utils/cache.py:TimeBasedCache] 也是通用 utility

**vs 嵌进 BilibiliApiClient**：

- BilibiliApiClient 内部直接用 ConcurrentHashMap —— 3 个 endpoint 各自管 cache（重复 3 份代码）
- 抽 utility 集中处理 TTL / 线程安全 / clock 注入（**单一**实现，3 处复用）

### 决定 2：[getOrLoad] 用 `suspend` loader（**不**用 sync `() -> V` + runBlocking）

**问题**：[getOrLoad] 的 loader 调 HTTP（suspending I/O）—— sync loader + runBlocking **会**阻塞调用方协程。

**v0.5.10 方案**：

```kotlin
suspend fun <K, V> getOrLoad(key: K, loader: suspend () -> V): V
```

**理由**：

- suspend loader 让 `withContext(Dispatchers.IO) { ... }` **自然**嵌套——HTTP 跑 IO 线程池，**不**阻塞调用方
- sync `() -> V` + runBlocking **会**阻塞调用方（runBlocking 挂起当前线程直到 loader 完成，**不**调度到 IO）

**v0.5.10 简化**：

- 测试用 `runTest { ... }` 包装所有 [getOrLoad] 调用（Kotlin coroutines test）
- 没引入额外协程上下文——`runTest` 是 StandardTestDispatcher 同步调度

**v0.5.10 Commit 1 经历**：

- 第一版用 sync `() -> V` loader —— [fetchMixinKey] 用 [withContext(IO)] 包 loader，**编译失败**（`withContext` 是 suspend，**不能**在 sync lambda 里调）
- 改用 suspend loader 后 [fetchMixinKey] 编译通过
- 单测**全**改用 `runTest` 包装

### 决定 3：三层缓存 key 分层（global / bvid / `$bvid:$cid:$qn`）

**问题**：B 站 3 个 endpoint 的缓存 key 应该怎么选？

**v0.5.10 方案**：

- `mixinKeyCache` key = `"global"` —— mixin_key 是 B 站服务端**全局单值**（所有 B 站 endpoint 共用同一个 mixin_key）
- `viewCache` key = `bvid` —— view 返视频 metadata，按 bvid 唯一
- `playurlCache` key = `"$bvid:$cid:$qn"` 3 元组 —— playurl 返**特定** (bvid, cid, qn) 的下载直链

**理由**：

- **mixin_key 全局**——B 站 wbi_img 单值，所有 view / playurl 共用，**1 个 key** 足够
- **view 按 bvid**——单 bvid 唯一标识 1 个视频，metadata 短时间（< 5min）**不**变
- **playurl 按 3 元组**——不同 (bvid, cid, qn) 返**不同** URL，qn 必**进** key

**qn 必进 key 的根因**：

- 1080p (qn=80) 的 url 跟 1080p60 (qn=116) 的 url **不**同
- 用户**不**同时下两个清晰度，**但**多次下载**可能**切换清晰度
- key **不**含 qn → 第二次切换清晰度返**旧** URL（错清晰度）→ 死链

**v0.5.10 简化**：

- **不**按 UA 分 key（USER_AGENT 写死常量）
- **不**按 IP 分 key（v0.5.10 scope **不**涉及多 IP 场景）
- **不**做 -352 风控时强制失效（v0.5.11+）

### 决定 4：cache 失败**不**污染（loader 抛错 → 下次重新拉）

**问题**：[getOrLoad] 的 loader 抛 IOException（HTTP 401 / 业务 -352）—— 缓存**是否**写？

**v0.5.10 方案**：

```kotlin
suspend fun <K, V> getOrLoad(key: K, loader: suspend () -> V): V {
    val entry = map[key]
    if (entry != null && entry.expiresAt > now) return entry.value
    val value = loader()  // 抛错 → 整个 getOrLoad 抛 → 缓存**不**写
    checkNotNull(value) { ... }
    map[key] = Entry(value, now + ttlMillis)
    return value
}
```

**理由**：

- loader 抛 IOException → `getOrLoad` 整体抛 → `map[key] = ...` **不**执行 → 缓存**不**写
- 下次 `getOrLoad(key)` 走 cache miss → 重新调 loader
- **避免**缓存"失败状态"——失败是瞬态的，下次重试可能成功

**v0.5.10 测试**：

- `fetchMixinKey does not cache on failure (next call retries HTTP)` — 显式验证连续 2 次失败 → 2 次 HTTP 调用

### 决定 5：versionName 跳号 0.5.8 → 0.5.10（**不**走 0.5.9）

**问题**：v0.5.10 是 v0.5.9-wip 之后的下一个版本，versionName 该是 0.5.9 还是 0.5.10？

**v0.5.10 方案**：

- versionName = "0.5.10"（**跳** 0.5.9）
- versionCode = 16 + 1 = 17（**顺序**整数）
- v0.5.9-wip tag **仍**存在（标记 WIP 状态），但 versionName / versionCode **不**对应 0.5.9

**理由**：

- v0.5.9-wip 是 chore-style WIP（**不**算正式 release），XBogusSigner 真算法**未**完成
- v0.5.10 是**新**正式 release（B 站缓存）—— 自然**跳**过 0.5.9 给真算法完整版留位置
- **避免** v0.5.9-android 跟 v0.5.9-wip-android 混淆（用户看到 0.5.9 是**哪**个？）

**vs v0.5.7 → v0.5.8（**没**跳号）**：

- v0.5.7 完整 release → v0.5.8 完整 release：+1
- v0.5.8 完整 release → v0.5.9-wip WIP：+0（**没** bump versionCode / versionName）
- v0.5.9-wip WIP → v0.5.10 完整 release：跳号（wip tag **不**算**正式** versionName 占用）

### 决定 6：[TimeBasedCache] 简化为单 ConcurrentHashMap（**不**做主动清理 / LRU / 多 store）

**问题**：[TimeBasedCache] 是 5min TTL，但 ConcurrentHashMap **不**自动清理过期 entry——内存会**持续**增长**不**？

**v0.5.10 方案**：

- Lazy expiry on read：`getOrLoad` 时检查 `expiresAt > now`，过期**当** cache miss
- **不**主动清理（**不**起协程扫过期 entry）
- **不**做 LRU 淘汰
- **不**做 size 上限

**理由**：

- 实际 key 数极少（3-5 个：mixin_key / view-by-bvid / playurl-by-bvid-cid-qn / 抖音 XBogus v0.5.11+）
- 5min 后用户**大**概率换了 B 站 URL，**旧** key **自然**被新 key 覆盖（ConcurrentHashMap put **不**删除旧 key，**但** size 仍**只**有 5-10 个）
- **不**起清理协程——避免 lifecycle / 资源泄露

**vs Caffeine / Guava Cache**：

- Caffeine 支持 `@Expire + @MaximumSize + async refresh + access pattern` 等——**功能**多但**依赖**重
- Guava Cache 类似——`com.google.guava:guava` 几 MB
- 手写 30 行 Kotlin + 6 例单测——**功能**够用，0 依赖

**v0.5.10 边界**：

- 单进程 5-10 个 key × 几 KB = 50KB 内存——**远低于** 1MB 阈值
- v0.5.11+ 加抖音 / 微博等**多**平台 → 单进程 50-100 个 key——仍**远低于**阈值
- 假设**有** 10000+ key（不现实）→ 再考虑 LRU

---

## 三、坑 & 决策

### 坑 1：v0.5.10 Commit 1 第一版 `getOrLoad` 用 sync `() -> V` loader → fetchMixinKey 编译失败

**症状**：

```kotlin
// 第一版
fun <K, V> getOrLoad(key: K, loader: () -> V): V

// fetchMixinKey
suspend fun fetchMixinKey(): String = mixinKeyCache.getOrLoad("global") {
    withContext(Dispatchers.IO) { ... }  // ← 编译失败：withContext 是 suspend
}
```

**根因**：

- `withContext(Dispatchers.IO) { ... }` 是 suspend 函数
- sync lambda `() -> V` **不**能调 suspend 函数
- 编译错：`Suspension functions can be called only within coroutine body`

**修法**：

- `getOrLoad` 改 `suspend fun <K, V> getOrLoad(key: K, loader: suspend () -> V): V`
- 单测**全**改用 `runTest { ... }` 包装

**教训**：

- Android 端缓存 utility 跟 desktop 端**不**同——desktop 端**没**协程概念，sync lambda 是默认
- Android 端 I/O 几乎**全** suspend（`withContext(IO)` 跑阻塞 HTTP）—— 缓存 utility 必 suspend
- v0.5.10 Commit 1 第一版**没**意识到这点 → 编译失败 → 改 suspend 后通过

### 坑 2：v0.5.10 Commit 3 `view uses different cache keys for different bvids` 测试 mock 错位

**症状**：

- mock `call.execute()` 4 次响应（navJson × 2 + viewJson1 + viewJson2）
- 实际 HTTP 调用只有 3 次（1 mixin_key + 2 view）
- 3rd view 实际**没**走 HTTP（cache hit），但 mock 假定它走 HTTP → 3rd HTTP 返回 `navJson`（**错**位）
- 测试 `r2.title` 期望 "t2" 实际是 ""（parseViewResponse 解析 navJson **没**有 "title" 字段）

**根因**：

- `returnsMany` list 长度**不**匹配实际 HTTP 调用次数
- 第 2 次 `view(BV1xx)` cache hit → **不**走 HTTP → 实际**只** 2 次 view HTTP
- 列表第 3 个 `navJson` **没**被用，但 mockk **不**报错（**只**对**已**调用的调用检查顺序）

**修法**：

- 改成 3 元素 list（1 navJson + 1 viewJson1 + 1 viewJson2）
- 实际 HTTP：1 mixin_key + 2 view = 3 次

**教训**：

- mockk `returnsMany` list 长度必**匹配**实际 HTTP 调用次数
- **不**要冗余 mock——多余的元素**不会**被用，**会**让 mock 错位**不**被察觉
- 写 mock 前**先**trace 实际 HTTP 调用顺序（哪些 cache hit、哪些 cache miss）

### 坑 3：`checkNotNull` 抛 `IllegalStateException`（**不**是 `NullPointerException`）

**症状**：

- `TimeBasedCacheTest` 写 `assertThat(ex).isInstanceOf(NullPointerException::class.java)`
- 实际抛 `IllegalStateException: TimeBasedCache loader returned null for key=key`
- 测试失败

**根因**：

- Kotlin `checkNotNull(value) { ... }` 用 `IllegalStateException`（**不**是 Java 的 NPE）
- 跟 Java 8+ `Objects.requireNonNull` 行为**不**同（Java 抛 NPE）

**修法**：

- 改用 `assertThat(ex).isInstanceOf(IllegalStateException::class.java)`

**教训**：

- Kotlin `checkNotNull` / `requireNotNull` 行为跟 Java `Objects.requireNonNull` **不**同
- **不**要凭 Java 经验写 Kotlin exception type 断言

### 坑 4：TimeBasedCache `<K, V>` type inference 失败 → BilibiliApiClient 编译错

**症状**：

```kotlin
// v0.5.10 Commit 2
private val mixinKeyCache = TimeBasedCache<String>(
    ttlMillis = 5 * 60 * 1000L,
)
//            ↑ 编译错：Cannot infer type for this parameter
```

**根因**：

- `<String>` 只有 1 个 type parameter，Kotlin **不**能 infer V
- 必须显式给 `<String, String>`

**修法**：

```kotlin
private val mixinKeyCache = TimeBasedCache<String, String>(
    ttlMillis = 5 * 60 * 1000L,
)
```

**教训**：

- Kotlin generic 推断**不**能跨函数边界——构造函数调用时 type arg 必显式
- 写 utility 时 KDoc 显式标注 `<K, V>`，调用方**必须** `<String, String>` 显式给

---

## 四、验证

### 单测

| 测试类 | 例数 | 状态 |
|---|---|---|
| ...（v0.5.9-wip 之前所有测试）| 327 | ✅ |
| **`TimeBasedCacheTest`** | **6**（v0.5.10 Commit 1 新增：cache miss / hit / expire / null 防御 / invalidate / clear）| ✅ |
| **`BilibiliApiClientTest` 新增** | **+6**（v0.5.10 Commit 2-4 新增：fetchMixinKey × 2 + view × 2 + playurl × 2）| ✅ |
| **总计** | **339**（v0.5.9-wip 327 + 12 新增）| ✅ |

### APK 验证

```
$ ./gradlew assembleDebug
BUILD SUCCESSFUL in 16s

APK: app/build/outputs/apk/debug/app-debug.apk  80.8 MB（v0.5.8 同大小）
- 3 个 [TimeBasedCache] 字段（mixinKeyCache / viewCache / playurlCache）—— 进程内 5-10 个 key × 几 KB
- 0 新依赖（Kotlin ConcurrentHashMap + coroutines 已 classpath）
- BilibiliApiClient 字节码增量 ~500 行
```

### 静态检查

`./gradlew testDebugUnitTest --rerun` 全绿 339 例（v0.5.9-wip 327 + 12 新增）。

---

## 五、复盘清单

### 做了

- [x] **[TimeBasedCache<K, V>]**（v0.5.10 Commit 1）—— 通用 TTL 内存缓存 + 6 例单测
- [x] **[BilibiliApiClient.fetchMixinKey] 5min 缓存**（v0.5.10 Commit 2）—— 2 例单测
- [x] **[BilibiliApiClient.view] 按 bvid 5min 缓存**（v0.5.10 Commit 3）—— 2 例单测
- [x] **[BilibiliApiClient.playurl] 按 `"$bvid:$cid:$qn"` 5min 缓存**（v0.5.10 Commit 4）—— 2 例单测
- [x] **versionCode 16→17** + versionName "0.5.8"→"0.5.10"（v0.5.10 Commit 4）
- [x] **339/339 单测全绿**
- [x] **`assembleDebug` 通过**
- [x] **阶段 20 复盘文档**（本文档）

### 没做（v0.5.11+ 单独 PR）

- [ ] **X-Bogus 缓存**——XBogusSigner 真算法落地后 wire（v0.5.9-wip 仍 stub chaos）
- [ ] **抖音 API 客户端缓存**——DouyinApiClient.awemeItemInfo 暂**不**加（X-Bogus 没通真 API 时缓存是 stub 数据）
- [ ] **-352 风控时强制失效**——当前缓存**不**主动失效，-352 风控时需等 5min 过期
- [ ] **按 UA 分 key** —— USER_AGENT 写死常量，AppConfig.userAgent 落地后再分
- [ ] **TTL 配置化** —— v0.5.10 硬编码 5min，AppConfig.apiCacheTtl 落地后再配置
- [ ] **m3u8 v7+ HLS encryption** / **多 variant 选择 UI** / **WebViewHeadlessSniffer 自身单测**（Robolectric）/ **ANR 风险测试** / **DefaultWebViewFactory 配置 instrumented test**
- [ ] 仪器测试 10 个真机 adb install（跨阶段欠账 #5）

### 文档同步

- [x] [PHASES.md](../PHASES.md) — 阶段 20 行加
- [x] [CHANGELOG.md](../CHANGELOG.md) — + v0.5.10 段
- [x] [REUSE-MAP.md](../REUSE-MAP.md) — 同步 v0.5.10 缓存映射
- [x] [README.md](../../README.md) — 阶段 20 标完成
- [x] [phase-20.md](phase-20.md) — 本文档
