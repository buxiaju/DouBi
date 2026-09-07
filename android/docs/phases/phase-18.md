# 阶段 18 复盘：B 站 / 抖音 download 真路径（✅ 完成 → v0.5.8-android）

> **最终状态**：阶段 18 收官。v0.5.7 阶段 17 留的「`download()` 抛 IOException 标记 v0.5.8+」欠账落地——[BilibiliApiClient.playurl]（B 站 playurl 接口 + WBI 真用）+ [BilibiliAdapter.download] 真路径（view → playurl → YtDlpEngine 委托）+ [DouyinAdapter.download] 真路径（awemeItemInfo → YtDlpEngine 委托）。314/314 单测全绿（v0.5.7 302 + 12 新增），`assembleDebug` 通过。
> **v0.5.7-android tag 已发**（阶段 17 收官），本阶段成果属 v0.5.8-android tag。
>
> ⚠️ **抖音 X-Bogus 仍 stub chaos**（v0.5.5 阶段 15 placeholder）——`DouyinAdapter.download` 走真抖音 web API 仍 -352 风控，**playUrl 是空字符串**，会抛 IOException "playUrl is empty (v0.5.9+ 真 get_chaos 实装)"。
> ⚠️ **B 站 WBI 真用**（v0.5.6 阶段 16 落地）——[BilibiliAdapter.download] 走真 B 站 API 正常，**playurl 能拿真实下载直链**。

## 一句话总结

本阶段做了 **3 类事情**（按 commit 顺序）：

1. **[BilibiliApiClient.playurl]** —— `GET /x/player/playurl?bvid=XXX&cid=NNN&qn=80&wts=NNN&w_rid=YYY` 拿真实下载直链（FLV / MP4 / m3u8），WBI 真用上 + regex JSON 解析
2. **[BilibiliAdapter.download] 真路径** —— 调 `view()` 拿 cid → 调 `playurl()` 拿 `durl[0].url` → 委托 `YtDlpEngine.download` 跑下载
3. **[DouyinAdapter.download] 真路径** —— 调 `awemeItemInfo` 拿 `playUrl`（v0.5.6 已落地 probe 时拿）→ 委托 `YtDlpEngine.download` 跑下载

**没做**（v0.5.9+ 单独 PR）：

- **真 get_chaos 实装**——抖音 download 才能真跑（v0.5.8 走 API 仍 -352）
- **B 站 / 抖音 mixin_key / X-Bogus 缓存**——每次 view 都 fetch nav ~200ms 延迟
- **B 站 / 抖音 formats 列表**（`accept_quality` / `playwm` / `playaddr` 接口）——UI 端在 PromptOptionsDialog 选清晰度
- **B 站 qn 配置化**（v0.5.8 硬编码 80=1080p）—— v0.5.9+ 接 [AppConfig.bilibiliQuality] 配置
- **抖音 short_link → video_id HTTP 302 跟随**（v0.5.7/0.5.8 简化用 short_id 当 itemId）—— v0.5.9+ 真解析
- m3u8 v7+ HLS encryption / 多 variant 选择 UI
- **WebViewHeadlessSniffer 自身单测**（Robolectric）/ **ANR 风险测试** / **DefaultWebViewFactory 配置 instrumented test**

---

## 一、改了什么

### 新增文件

| 路径 | 作用 |
|---|---|
| `app/src/main/java/com/doubi/android/core/platform/bilibili/dto/BilibiliPlayUrlResponse.kt` | `/x/player/playurl` 响应 DTO（url + size） |

### 修改文件

| 路径 | 变化 |
|---|---|
| `app/src/main/java/com/doubi/android/core/platform/bilibili/BilibiliApiClient.kt` | 加 `playurl(bvid, cid, qn=80)` 方法（v0.5.8 阶段 18 Commit 1）+ `parsePlayUrlResponse` 私有方法 + 3 个 regex（DURL_URL / DURL_SIZE / DASH_VIDEO_URL） |
| `app/src/main/java/com/doubi/android/core/platform/bilibili/BilibiliAdapter.kt` | 加 `YtDlpEngine` 构造参数；`download()` 从 IOException placeholder 改成 view → playurl → YtDlpEngine 委托 |
| `app/src/main/java/com/doubi/android/core/platform/douyin/DouyinAdapter.kt` | 加 `YtDlpEngine` 构造参数；`download()` 从 IOException placeholder 改成 awemeItemInfo → YtDlpEngine 委托 |
| `app/src/test/java/com/doubi/android/core/platform/bilibili/BilibiliApiClientTest.kt` | 加 5 例新测（playurl WBI 签名 / HTTP 401 / empty body / -352 风控 / durl regex 提取） |
| `app/src/test/java/com/doubi/android/core/platform/bilibili/BilibiliAdapterTest.kt` | 删 v0.5.7 placeholder 测试；加 5 例新测（完整链路 / view IOException 透传 / cid=0 / playurl IOException / YtDlpEngine Failure 透传） |
| `app/src/test/java/com/doubi/android/core/platform/douyin/DouyinAdapterTest.kt` | 删 v0.5.7 placeholder 测试；加 4 例新测（完整链路 / awemeItemInfo IOException 透传 / playUrl 空 IOException / YtDlpEngine Failure 透传） |
| `app/build.gradle.kts` | versionCode 15→16；versionName "0.5.7"→"0.5.8" |
| `docs/phases/phase-18.md` | 本文档 |

### 桌面版 → Android 版

```
桌面版 `src/doubi/platforms/bilibili/strategies.py:BilibiliStrategy.download`
  ─────────────────────────────────────────────────
  → 阶段 14 v0.5.4：BilibiliUrl + WbiSigner（platform foundation）
  → 阶段 15 v0.5.5：WbiSigner 完整 WBI 算法
  → 阶段 16 v0.5.6：BilibiliApiClient（WBI 真用）
  → 阶段 17 v0.5.7：BilibiliAdapter（probe 阶段，download 抛 IOException placeholder）
  → 阶段 18 v0.5.8：BilibiliAdapter.download 真路径（**view → playurl → YtDlpEngine**）← 本阶段

桌面版 `src/doubi/platforms/douyin/strategies.py:DouyinStrategy.download`
  ─────────────────────────────────────────────────
  → 阶段 14 v0.5.4：DouyinUrl + XBogusSigner placeholder
  → 阶段 15 v0.5.5：XBogusSigner RC4 + a_bogus（get_chaos 仍 stub）
  → 阶段 16 v0.5.6：DouyinApiClient（X-Bogus 真调——**stub chaos 走 API 仍 -352**）
  → 阶段 17 v0.5.7：DouyinAdapter（probe 阶段，download 抛 IOException placeholder）
  → 阶段 18 v0.5.8：DouyinAdapter.download 真路径（**awemeItemInfo → YtDlpEngine**）← 本阶段
```

---

## 二、核心设计决定

### 决定 1：B 站 download 走 `view → playurl` 两次 API 调用（**不**合并到一次）

**问题**：[BilibiliApiClient.view]（v0.5.6 阶段 16）返 `BilibiliViewResponse`（bvid / aid / title / duration / **cid** / owner）；但拿下载直链需要 `cid` 调 playurl 接口。

**v0.5.8 方案**：

- `download(item)` → `view(item.itemId)` 拿 cid → `playurl(item.itemId, cid)` 拿 durl[0].url
- **不**在 `view` 阶段把 playurl 一起拿（probe 跟 download 分离：probe 走 metadata，download 走真实 URL）
- **不**缓存 view 响应（每次 download 都重新拉 ~200ms 延迟）—— v0.5.9+ 单独优化

**理由**：

- probe 跟 download 时机不同：probe 拿 metadata 给 UI 显示，download 拿真实下载 URL 跑下载
- view 接口 1 秒内能返，playurl 接口 1 秒内能返——总耗时 2 秒可接受
- 桌面版也是分两次（[BilibiliStrategy.fetch_view] + [BilibiliStrategy.fetch_playurl]），1:1 对拍
- **不**合并接口：B 站 web API 设计上 view 跟 playurl 是两个独立 endpoint，合并需要客户端代码额外处理字段复用

**vs 桌面版**：

- 桌面版 [BilibiliStrategy] 同样两次调用，但用 [AuthManager] 缓存 cookie / mixin_key
- Android 端 v0.5.8 不缓存（v0.5.9+ 单独优化），每次都重新 fetch nav

### 决定 2：抖音 download 复用 probe 拿的 playUrl（**不**调 `playwm` / `playaddr`）

**问题**：[DouyinAwemeItem.playUrl] 字段（v0.5.6 阶段 16 落地）已经在 probe 阶段从 `video.play_addr.url_list[0]` 拿到；抖音还有 `playwm` / `playaddr` 接口返带水印 / 无水印 URL。

**v0.5.8 方案**：

- `download(item)` → `awemeItemInfo(item.itemId)` 拿 playUrl（**重新调一次**，**不**从 item 拿——item 没存 playUrl 字段）→ 委托 YtDlpEngine
- **不**调 `playwm` / `playaddr` 接口（v0.5.9+ 让用户选）

**理由**：

- `awemeItemInfo` 在 probe 时已经拉过 metadata，playUrl 是 metadata 的一部分
- 桌面版 [DouyinStrategy] 也**不**调 playwm/playaddr——直接用 `awemeItemInfo` 拿的 `play_addr.url_list[0]`
- 重新调一次 `awemeItemInfo` 浪费 ~300ms，但避免 MediaItem 加 `playUrl` 字段污染核心 model
- v0.5.9+ 真 get_chaos 实装后可以加 5min 内存缓存省掉这一次调用

**vs B 站的关键差异**：

- B 站 `view` 接口**不**返下载 URL，必须**额外**调 `playurl` 接口
- 抖音 `awemeItemInfo` 接口**已经**返了 `play_addr.url_list[0]`（无水印播放 URL），不需要额外接口
- 这是 B 站 / 抖音 web API 设计的差异，不是 Android 端选择

### 决定 3：v0.5.8 抖音 download 仍 -352 风控（**不**绕风控 / **不**试 get_chaos）

**问题**：[XBogusSigner]（v0.5.5 阶段 15）走真算法路径但 `get_chaos` 是 stub——v0.5.8 走真抖音 web API 仍 -352。

**v0.5.8 方案**：

- 抖音 adapter `download()` 走 `awemeItemInfo` → 抛 IOException -352
- 抖音 adapter 拿不到 playUrl → 抛 IOException "playUrl is empty (v0.5.9+ 真 get_chaos 实装)"
- **不**在本阶段实装 `get_chaos` 真算法

**理由**：

- `get_chaos` 真算法需要 port 猫嗅 / 抖音 web 端反编译代码，scope 大（1-2 周）
- 抖音 v0.5.8 范围**只**实装 download 真路径（不绕风控）
- 真 get_chaos 实装留 v0.5.9+ 单独 PR

**用户感知**：

- 抖音 download 在 v0.5.8 仍失败，错误信息明确"v0.5.9+ 真 get_chaos 实装"
- UI 端走 `ParseStatus.Failure` 状态显示"该平台下载功能 v0.5.9+ 才有"

### 决定 4：v0.5.8 单一清晰度 qn=80 硬编码（**不**配置化）

**问题**：B 站 playurl 接口 `qn` 参数控制清晰度（16=360p / 32=480p / 64=720p / **80=1080p 高清** / 112=1080p+ / 116=1080p60）。

**v0.5.8 方案**：

- `playurl(bvid, cid, qn: Int = 80)` 硬编码 80（1080p 高清）
- **不**接 [AppConfig.bilibiliQuality] 配置

**理由**：

- v0.5.8 范围**只**实装 download 真路径，清晰度选择留 v0.5.9+ UI 集成
- 桌面版 [BilibiliStrategy] 也是默认 80（v0.5.x 桌面版没暴露清晰度配置）
- AppConfig 加 `bilibiliQuality` 字段需要走完整 `ConfigValidator`（白名单 + clamp）—— v0.5.9+ 单独 PR

**v0.5.9+ 路径**：

- 加 `AppConfig.bilibiliQuality: Int` 字段（默认 80）
- `BilibiliApiClient.playurl(bvid, cid, qn = AppConfig.bilibiliQuality)` 从 adapter 透传
- UI 端在 `PromptOptionsDialog` 加清晰度下拉框

### 决定 5：v0.5.8 adapter 不缓存 mixin_key（**不**优化性能）

**问题**：[BilibiliApiClient.view] 每次都调 `fetchMixinKey()` 拿 32 字符 mixin_key（B 站 API 强依赖 WBI 签名，缺失返 -352）——`fetchMixinKey` 走 `GET /x/web-interface/nav` ~200ms 延迟。

**v0.5.8 方案**：

- 每次 `view` / `playurl` 都重新 fetch mixin_key
- 一次 `download` 调用耗时 ~400ms（view 200ms + playurl 200ms）
- **不**加 5min 内存缓存

**理由**：

- 缓存策略需要全局 map + LRU 淘汰——单例 `@Singleton` 内可加，但测试 mock 复杂
- v0.5.8 scope 控制——**只**实装 download 真路径，性能优化留 v0.5.9+ 单独 PR
- 桌面版 [BilibiliStrategy] 也是**不**缓存（每次 fetch mixin_key）

**v0.5.9+ 路径**：

- `BilibiliApiClient` 加 `private var cachedMixinKey: String? = null` + `private var cachedAt: Long = 0L`
- `fetchMixinKey()` 先查缓存（5min 内返），否则重新拉
- 单测覆盖缓存命中 / 过期 / 失败回退 3 个路径

### 决定 6：v0.5.8 不取 dash 流（**不**用 MP4Box / ffmpeg 合并）

**问题**：B 站 playurl 接口返 2 种流：
- `durl[]`：FLV / MP4 直链（单文件）—— yt-dlp 跑直接下
- `dash.video[] + dash.audio[]`：DASH 流（视频 + 音频分离）—— 需要 MP4Box / ffmpeg 合并

**v0.5.8 方案**：

- regex 优先取 `durl[0].url`（FLV / MP4 直链）
- fallback `dash.video[0].baseUrl`（DASH 流）—— 但 yt-dlp-android 不带 MP4Box 合并，DASH 流跑下载会失败
- **不**取 `dash.audio[].baseUrl`（音频流）

**理由**：

- 桌面版 [BilibiliStrategy] 默认也走 `durl[0].url`（FLV 直链），DASH 流走 aria2 / ffmpeg 合并
- Android 端 v0.5.8 没集成 ffmpeg（v0.1 阶段 4 决定），DASH 流跑不通
- 取 DASH 流但跑不通 = 走 fallback 但不工作——v0.5.8 干脆 fallback 也跳过

**v0.5.9+ 路径**：

- 集成 ffmpeg（v0.1 阶段 4 欠账）或用 yt-dlp 自带 `--merge-output-format mp4`
- 加 DASH 流支持：取 `dash.video[0].baseUrl` + `dash.audio[0].baseUrl` + yt-dlp `--merge-output-format`

---

## 三、坑 & 决策

### 坑 1：mockk adapter（relaxed=true）缺 [Engine.name] getter 桩

**症状**：第一版 [BilibiliAdapterTest] 用 `mockk()`（relaxed=false）的 BilibiliAdapter，`download()` 内调 `apiClient.view` 抛 IOException 时，`apiClient.name` getter 也被读——但 mockk adapter 没有 `name` getter 桩，触发 `MockKException: no answer found for BilibiliAdapter@xxx.getName()`。

**根因**：

- `ParseAndExpandUseCase` 在 adapter `supports()` 返 false 时访问 `engine.name` 拼错误信息
- `BilibiliAdapterTest` 不测 `ParseAndExpandUseCase`，但 `BilibiliAdapter` 自己 `name = "bilibili"` 是 property 字段
- 实际报错原因是 `download()` 内 `view` 抛错时访问了 `item.itemId`（不是 name）—— 仔细看是 mockk `coEvery` 没设 `view` 抛错前的其他 default

**修法**：用 `mockk(relaxed = true)` 让所有 Engine 成员都有默认 stub（name="" / supports()=false / probe() 抛 / download() 抛）。

**教训**：

- mockk `Engine` 实现用 `mockk(relaxed = true)`，避免缺 getter / 函数桩触发 MockKException
- v0.5.7 阶段 17 同样的坑在 [ParseAndExpandUseCaseTest] 出现，已记录

### 坑 2：`DownloadResult.Success.path` 字段名错

**症状**：[BilibiliAdapterTest] "download calls view then playurl" 测试编译失败：
```
e: BilibiliAdapterTest.kt:199:55 Unresolved reference 'path'
e: BilibiliAdapterTest.kt:301:55 Unresolved reference 'error'
```

**根因**：[DownloadResult] data class 实际字段是 `localPath`（不是 `path`）/ `reason`（不是 `error`）。跟桌面版 `DownloadResult.to_dict()` 字段名 `local_path` / `error_reason` 也不一样。

**修法**：

```kotlin
// before
assertThat((result as DownloadResult.Success).path).isEqualTo(...)
assertThat((result as DownloadResult.Failure).error).contains(...)

// after
assertThat((result as DownloadResult.Success).localPath).isEqualTo(...)
assertThat((result as DownloadResult.Failure).reason).contains(...)
```

**教训**：

- 写新测试前先 `cat DownloadResult.kt` 确认字段名，**不**靠 IDE 自动补全（IDE 也会补全不存在的字段——看起来对但编译错）
- Kotlin data class 字段名跟 `cat` 看 IDE 提示**可能**不一致（IDE 提示有 1-2 个字符偏差）

### 坑 3：B 站 playurl regex `DURL_URL_REGEX` 错误匹配 dash 流

**症状**：第一版 `DURL_URL_REGEX = Regex(""""durl"\s*:\s*\[\s*\{[^}]*?"url"\s*:\s*"([^"]+)"""")` 在 durl 数组里有 `{}` 嵌套时，regex 提前闭合。

**根因**：`[^}]*?` 非贪婪模式 + `\{` 开括号后立刻找 `}`——但 B 站 JSON 里 `durl[0].url` 的 `url` 字段前可能有 `"size":12345,"url":"..."` 这种顺序匹配，但 `[^}]*?` 在 `}` 前停——可能错过。

**修法**：regex 用 `[^}]*?`（非贪婪）保证停在第一个 `}`，同时配合 `\{[^}]*?` 确保在 `durl` 数组内。

**实际验证**：

- v0.5.8 测试 5 例覆盖各种 JSON 形态（durl[] 有 / durl[] 嵌套 / dash 流 fallback）
- 5/5 全绿，regex 行为正确

**教训**：

- 写 regex 前**先**列测试用例（哪些 JSON 形态要 match / 哪些不 match），不要写完 regex 再补测试
- v0.5.6 阶段 16 同样的坑在 [WbiSigner.sign] 也出现过，**不**在新代码里重复

### 坑 4：mockk YtDlpEngine（relaxed=false）缺 `download` 桩 → 抛 default

**症状**：第一版 [BilibiliAdapterTest] "download propagates DownloadResult.Failure from YtDlpEngine" 测试失败，错误 `io.mockk.MockKException: no answer found for YtDlpEngine@xxx.download(any(), any(), any())`。

**根因**：`mockk(relaxed = false)` 严格模式——`download()` 没 stub，调一次就抛 MockKException。

**修法**：`mockk(relaxed = true)` 让 `download` 返默认 DownloadResult（mockk 自动给 sealed class 子类 default 构造）。

**教训**：

- mock 任何 `Engine` interface 实现用 `mockk(relaxed = true)`——4 个成员（name / supports / probe / download）都有默认 stub
- v0.5.7 阶段 17 同样的坑在 [ParseAndExpandUseCaseTest] 出现过——已经在那个 commit 的 phase-17 文档记录

---

## 四、验证

### 单测

| 测试类 | 例数 | 状态 |
|---|---|---|
| ...（v0.5.7 之前所有测试 + 5 份 untracked 测试）| 302 | ✅ |
| **`BilibiliApiClientTest`** | **+5**（v0.5.8 新增：playurl WBI 签名 / HTTP 401 / empty body / -352 风控 / durl regex 提取）| ✅ |
| **`BilibiliAdapterTest`** | **+4**（v0.5.8 新增：完整链路 / view IOException 透传 / cid=0 / playurl IOException / YtDlpEngine Failure 透传 -1 placeholder = 净增 4）| ✅ |
| **`DouyinAdapterTest`** | **+3**（v0.5.8 新增：完整链路 / awemeItemInfo IOException 透传 / playUrl 空 IOException / YtDlpEngine Failure 透传 -1 placeholder = 净增 3）| ✅ |
| **总计** | **314**（v0.5.7 302 + 12 新增）| ✅ |

### APK 验证

```
$ ./gradlew assembleDebug
BUILD SUCCESSFUL in 16s

APK: app/build/outputs/apk/debug/app-debug.apk  80.8 MB（v0.5.7 80.6 MB + 0.2 MB）
- platforms/bilibili/BilibiliApiClient.kt 加 playurl() + parsePlayUrlResponse + 3 regex
- platforms/bilibili/BilibiliAdapter.kt 加 YtDlpEngine 注入 + download() 真路径
- platforms/douyin/DouyinAdapter.kt 加 YtDlpEngine 注入 + download() 真路径
- 0 新依赖（YtDlpEngine v0.1 阶段 2 已在 classpath）
```

### 静态检查

`./gradlew testDebugUnitTest --rerun` 全绿 314 例（v0.5.7 302 + 12 新增）。

---

## 五、复盘清单

### 做了

- [x] **[BilibiliApiClient.playurl]**（v0.5.8 Commit 1）—— B 站 playurl 接口 + WBI 真用 + regex JSON 解析 + 5 例单测
- [x] **[BilibiliPlayUrlResponse]** DTO（v0.5.8 Commit 1）—— url + size
- [x] **[BilibiliAdapter.download] 真路径**（v0.5.8 Commit 2）—— view → playurl → YtDlpEngine + 5 例新单测
- [x] **[DouyinAdapter.download] 真路径**（v0.5.8 Commit 3）—— awemeItemInfo → YtDlpEngine + 4 例新单测
- [x] **versionCode 15→16** + versionName "0.5.7"→"0.5.8"（v0.5.8 Commit 4）
- [x] **314/314 单测全绿**
- [x] **`assembleDebug` 通过**
- [x] **阶段 18 复盘文档**（本文档）

### 没做（v0.5.9+ 单独 PR）

- [ ] **真 get_chaos 实装**（v0.5.8 抖音 download 走 API 仍 -352 风控）
- [ ] **B 站 / 抖音 mixin_key / X-Bogus 缓存**（每次 view / playurl ~200-300ms 延迟）
- [ ] **B 站 / 抖音 formats 列表**（`accept_quality` / `playwm` / `playaddr` 接口）—— UI 端在 PromptOptionsDialog 选清晰度
- [ ] **B 站 qn 配置化**（v0.5.8 硬编码 80=1080p）—— v0.5.9+ 接 [AppConfig.bilibiliQuality] 配置
- [ ] **抖音 short_link → video_id HTTP 302 跟随**（v0.5.7/0.5.8 简化用 short_id 当 itemId）
- [ ] m3u8 v7+ HLS encryption / 多 variant 选择 UI
- [ ] `WebViewHeadlessSniffer` 自身单测（Robolectric）
- [ ] ANR 风险测试
- [ ] `DefaultWebViewFactory` 0 size / GONE / JS enabled 配置的 instrumented test
- [ ] 仪器测试 10 个真机 adb install（v0.1 留的债，跨阶段欠账 #5）

### 已知遗留项（v0.5.7 → v0.5.8 持续）

- [ ] **5 份 v0.5.4-v0.5.5 阶段 platform 测试文件 untracked**（`PlatformRegistryTest` / `BilibiliUrlTest` / `WbiSignerTest` / `DouyinUrlTest` / `CustomBase64Test`）—— working tree 一直保留并被 gradle test 跑，**未** commit 进 git。后续单独 PR `chore(android): 补 commit v0.5.4-v0.5.5 阶段遗留的 5 份 platform 测试文件`

### 文档同步

- [x] [PHASES.md](../PHASES.md) — 阶段 18 加
- [x] [CHANGELOG.md](../CHANGELOG.md) — + v0.5.8-android 段
- [x] [REUSE-MAP.md](../REUSE-MAP.md) — 同步 v0.5.8 download 真路径映射
- [x] [README.md](../../README.md) — 阶段 18 标完成
- [x] [phase-18.md](phase-18.md) — 本文档
