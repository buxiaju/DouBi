# 阶段 4 复盘：解析 + 列表（✅ 完成 → v0.2.0-android）

> **最终状态**：阶段 4 收官。YouTube 普通 / Shorts / Live / embed + 通用 m3u8 / mp4 直链全部接 Engine 嗅探；PromptOptionsDialog 选 format + 容器 + 缩略图 + 字幕 + 续传 + 标题模板；选完入队 DownloadRepository。单测 99 → 153 全绿（+54）。
> **v0.1.0-android tag 已发**（阶段 3 收官候选），本阶段成果属 v0.2.0-android tag。

## 一句话总结

本阶段做了 **3 类事情**：

1. **解析 use case**：YouTubeUrl 分类（11 字符 ID 提取 + 4 种形态归一化到 `watch?v=ID`）+ MediaFormat 数据类（formatId / ext / vcodec / acodec / height / fileSize）+ YtDlpEngine.probeWithFormats()（`extract_info` 拿 title + formats）+ ParseAndExpandUseCase（sealed result 分 Youtube / DirectLink / Unsupported）
2. **UI 改造**：Compose Dialog `PromptOptionsDialog`（format radio + 容器 / 缩略图 / 字幕 / 续传 checkbox + 标题模板可选）+ PastingViewModel 加 5 状态机（Idle / Parsing / AwaitingConfirm / Unsupported / Enqueued / Failure）+ PastingScreen 串 dialog + snackbar
3. **Hilt 装配**：EngineModule 单独装 YtDlpEngine + `baseOutputDir`（用 `@Named` 避免 Engine 间接持有 Context）

每一类都对应「桌面版有、Android 端当时没有」的具体差距。

---

## 一、改了什么

### 新增文件

| 路径 | 行数 | 职责 |
|---|---|---|
| `core/platform/youtube/YouTubeUrl.kt` | 95 | URL 分类（VIDEO / SHORTS / EMBED / LIVE / UNSUPPORTED）+ 归一化到 `watch?v=ID` |
| `core/model/MediaFormat.kt` | 92 | formats 数据类 + `label` 人类可读格式化（4K / 1080p / 720p / 480p / 360p / 240p / 144p / audio only） |
| `core/pipeline/ParseAndExpandUseCase.kt` | 117 | 解析 use case + `ParseResult` sealed class（Youtube / DirectLink / Unsupported） |
| `engine/ytdlp/di/EngineModule.kt` | 49 | Hilt 装 YtDlpEngine + `@Named("baseOutputDir")` File provider |
| `ui/parse/PromptOptionsDialog.kt` | 281 | Compose Dialog（format radio + 容器 chip + 缩略图 / 字幕 / 续传 / 标题模板 checkbox） |
| `app/src/test/.../YouTubeUrlTest.kt` | 195 | 25 例（VIDEO / SHORTS / LIVE / EMBED / 5 种 UNSUPPORTED 边界） |
| `app/src/test/.../MediaFormatTest.kt` | 165 | 15 例（label 全单位 + 边界 + 1 PB 不数组越界） |
| `app/src/test/.../ParseAndExpandUseCaseTest.kt` | 248 | 14 例（mock YtDlpEngine + 各分支） |

### 改造文件

| 路径 | 变化 |
|---|---|
| `engine/ytdlp/YtDlpEngine.kt` | + `probeWithFormats()` 方法 + `ProbeResult` data class + `VideoFormat.toMediaFormatOrNull()` 转换 |
| `ui/pasting/PastingViewModel.kt` | 阶段 3 占位 → 完整状态机（5 sealed class）+ 注入 ParseAndExpandUseCase + DownloadRepository + AppConfigDataStore |
| `ui/pasting/PastingScreen.kt` | 阶段 3 占位 UI → 监听 state + 弹 PromptOptionsDialog + Snackbar 一次性反馈 |
| `res/values/strings.xml` | + 13 个 prompt / pasting_* 字符串 |

### 桌面版 → Android 版

```
src/doubi/core/pipeline.py                       src/doubi/platforms/youtube/{url,adapter}.py
  DownloadPipeline.parse_and_expand()                YouTubeAdapter.parse() / url.classify()
  ──────────────────────────────────────────────────────────────────────────────────
  → core/pipeline/ParseAndExpandUseCase            → core/platform/youtube/YouTubeUrl
  → engine/ytdlp/YtDlpEngine.probeWithFormats()  → engine/ytdlp/YtDlpEngine 内部
  → core/model/MediaFormat                        → (新增) youtubedl-android VideoFormat 适配

src/doubi/ui/pages/parse.py
  PromptOptionsDialog (PySide6 + qfluentwidgets) + collect_prompt_overrides (pure func)
  ──────────────────────────────────────────────────────────────────────────────────
  → ui/parse/PromptOptionsDialog (Compose Dialog)
  → PastingViewModel.onDialogConfirm 直接 inline 收集 (Compose state 已经在 Dialog 内)
```

---

## 二、核心设计决定

### 决定 1：`probeWithFormats` 不进 `Engine` interface

桌面版 Engine ABC 不含 formats——formats 是 yt-dlp 特有的概念，aria2 / ffmpeg 没这层抽象。Android 端把 `probeWithFormats()` 放在 `YtDlpEngine` 具体类上，**不污染** `Engine` interface。

**收益**：未来加 aria2 / ffmpeg 时 `Engine` interface 仍干净。`ParseAndExpandUseCase` 注入 `YtDlpEngine` 具体类（v0.1 只有一个实现，单接口抽象是 over-engineering）。
**代价**：耦合到具体类——如果 v0.2 引入第二个 engine，这个 use case 要重写（但 v0.1 范围够用）。

### 决定 2：YouTube 频道 / 播放列表直接拒

桌面版 YouTubeAdapter.parse() 对 CHANNEL / PLAYLIST 返回 None 让 pipeline 兜底。Android 端走 sealed result：在 `ParseAndExpandUseCase` 里**先**用 `YouTubeUrl.toWatchUrlOrNull()` 判，`null` 后**再**用 `url.contains("youtube.com")` 二次判，是 youtube 域名但非视频形态 → `Unsupported("YouTube 频道 / 播放列表暂不支持")`。

为什么不走 `DirectLink`（像通用 m3u8 一样）？因为 DirectLink 会**真调 yt-dlp**，把频道 URL 喂给它会拉一堆列表，v0.1 不想支持这条路径。

### 决定 3：formatId 直接给 yt-dlp `-f`

桌面版用 "best" / "1080p" / "720p" 这种 quality 标签，translate 到 yt-dlp `-f "bestvideo[height<=1080]+bestaudio/best"`。Android 端直接用 `MediaFormat.formatId`（yt-dlp 原生字段）—— `137+140` / `22` / `best` 直接给 `-f` 选。

**收益**：少一层 mapping，UI 列表展示的 format 跟 yt-dlp 实际下的 format 一致。
**代价**：formatId 字符串对用户不友好（`137+140` vs `1080p`）—— 用 `MediaFormat.label` 在 UI 层做人类可读展示（`"1080p mp4 (avc1 + mp4a) · 2.3 MB"`）。

### 决定 4：标题模板走 inline，不复制 desktop 端 `apply_title_template`

桌面版 `apply_title_template(items, template)` 接收 MediaItem 列表 + 模板，遍历 mutate title。Android 端 PastingViewModel.onDialogConfirm 收到单个 item + template，inline 做 `item.copy(title = template.replace("{title}", item.title))`。

**收益**：少 30 行 use case，逻辑只有 1 条。批量场景（v0.2 多 URL）才需要 desktop 那种 helper。
**代价**：批量路径留 v0.2 阶段 5 补。

### 决定 5：Hilt 用 `@Named("baseOutputDir")` 而非 `@ApplicationContext`

`EngineModule` 显式 `@Provides @Named("baseOutputDir") fun provideBaseOutputDir(@ApplicationContext ctx: Context): File`。

**理由**：避免 `provideYtDlpEngine` 间接拿 `@ApplicationContext`（即使只是包成 File 也保留路径让 GC 释放）。`@Named` 让单测时能 mock 一个不同路径（v0.1 不写，但留口子）。

---

## 三、坑 & 决策

### 坑 1：Kotlin function type 不允许 named arguments

`PromptOptionsDialog.onConfirm: (item, format, options, titleTemplate) -> Unit` 是 function type，调用 `onConfirm(item, sel, opts, titleTemplate = xxx)` 报 `Named arguments are prohibited for function types`。

**修法**：去掉 named arg，按位置传。
**教训**：lambda 类型签名里写参数名是**为调用方 IDE 提示**，**不是**为 named arg。

### 坑 2：MockK 找不到 stub 触发了 unsupported URL

`ParseAndExpandUseCase` 第一版只判 `toWatchUrlOrNull(trimmed)` 是不是 null：null 就走 DirectLink 路径调 `probeWithFormats(trimmed)`。但 youtube 频道 / 播放列表 `toWatchUrlOrNull` 也是 null，导致**所有 youtube 域名但非视频形态的 URL 都调 probeWithFormats**。

**修法**：加二次判——`url.contains("youtube.com")` → `Unsupported("YouTube 频道 / 播放列表暂不支持")`，不再调 engine。
**教训**：use case 的分支判据要**显式穷举**，不要用"剩下都是 X"做兜底。`channel` / `playlist` 既不是 video 也不是 direct link，是第三类。

### 坑 3：regex 命名组 + `groups["id"]` 在缺失组上崩

`YouTubeUrl.classify()` 总是 `m.groups["id"]?.value`，但 CHANNEL / PLAYLIST pattern **不带** `(?<id>...)` 命名组，调用 `groups["id"]` 抛 `IllegalArgumentException: No group with name <id>`。

**修法**：`runCatching { m.groups["id"]?.value }.getOrNull().orEmpty()` 兜底。
**教训**：用 `m.groups[name]` 拿命名组前要确认 pattern 有这个组；或者用 `runCatching` 兜底。

### 坑 4：桌面版 `_QUALITY_CHOICES = ("best", "8k", "4k", "1080p", "720p", "480p")` 在 Android 端不适用

桌面版用 quality preset（"1080p"），Android 端用 `MediaFormat.formatId`（"137+140"）。我**没**用桌面版的 quality preset 因为：
1. 走 formatId 才能精确控制选哪个流（v0.1 YouTube formats 列表里 1080p 可能有好几个：`137` 视频 + `140` 音频、`22` 单流 720p MP4 等）
2. 8k / 4k preset 在手机屏幕上没意义（v0.1 目标是 720p / 1080p 主流）
3. 直链场景（m3u8 / mp4）根本没有 preset 选择

**结果**：PromptOptionsDialog 的"最高画质"下拉换成 formats 列表 radio，每个 format 自带人类可读 label（4K / 1080p / 720p / ...）。

---

## 四、测试变化

| 测试类 | 阶段 3 收官 | 阶段 4 收官 | 变化 |
|---|---|---|---|
| `AppConfigTest` | 13 | 13 | — |
| `AppConfigDataStoreTest` | 11 | 11 | — |
| `ModelTest` | 10 | 10 | — |
| `ProgressTest` | 25 | 25 | — |
| `MediaFormatTest` | 0 | **15** | +15（新文件） |
| `YouTubeUrlTest` | 0 | **25** | +25（新文件） |
| `ParseAndExpandUseCaseTest` | 0 | **14** | +14（新文件） |
| `YtDlpEngineTest` | 26 | 26 | — |
| `DownloadWorkerTest` | 13 | 13 | — |
| `ExampleUnitTest` | 1 | 1 | — |
| **单测合计** | **99** | **153** | **+54** |
| 仪器测试 | 10（写了没跑） | 10（写了没跑） | — |

**覆盖率**（jacoco 0.8.12）：

| 维度 | 阶段 3 收官 | 阶段 4 收官 |
|---|---|---|
| LINE | 37.5% | 34.7% |
| METHOD | 48.5% | 45.2% |
| INSTRUCTION | 40.8% | 34.3% |
| BRANCH | 46.7% | 43.4% |
| CLASS | 30.8% | 31.2% |

**覆盖率解读**：下降是因为新代码量（YouTubeUrl + MediaFormat + ParseAndExpandUseCase + PromptOptionsDialog + EngineModule + PastingViewModel 改造）增量比单测覆盖的更多。新文件只有 `YouTubeUrlTest` / `MediaFormatTest` / `ParseAndExpandUseCaseTest` 三层覆盖；`PromptOptionsDialog` 是 Compose UI 暂时没 Compose UI test；`PastingViewModel` 涉及 Hilt + WorkManager 走 instrumented test。

v0.2 阶段 5 接 Worker 进度订阅时一起加 Compose UI test + instrumented test，目标是把 `PromptOptionsDialog` / `PastingViewModel` / `DownloadingViewModel` 拉到 ≥60%。

---

## 五、APK 验证

```
APK: app-debug.apk  77.05 MB  528 entries (vs v0.1.0 76.43 MB, +0.6 MB)
- 4 ABI JNI 库全在 (libpython.zip.so / libqjs.so / libdatastore_shared_counter.so)
- 0 警告（packaging.jniLibs.useLegacyPackaging = true 仍生效）
- Manifest 合并后 8 个权限齐 + WorkManager 三个 Service 完整
```

---

## 六、复盘清单

### 做了

- [x] YouTubeUrl 分类（VIDEO / SHORTS / LIVE / EMBED / UNSUPPORTED）+ 归一化
- [x] MediaFormat 数据类 + label 人类可读
- [x] YtDlpEngine.probeWithFormats() + VideoFormat 转换
- [x] EngineModule Hilt 装配
- [x] ParseAndExpandUseCase + ParseResult sealed class
- [x] PromptOptionsDialog (Compose)
- [x] PastingViewModel 5 状态机
- [x] PastingScreen 弹 Dialog + Snackbar 反馈
- [x] 单测 99 → 153 全绿（+54）
- [x] assembleDebug 0 警告通过
- [x] jacoco 报告出新（基线 34.7% LINE / 45.2% METHOD）
- [x] 阶段 4 复盘文档

### 没做（移交下阶段）

- [ ] 多 URL 解析（v0.1 阶段 4 单 URL 流程够用，桌面版的"每行一个 URL + 表格"留 v0.2+）
- [ ] 容器展开（YouTube playlist / 抖音合集 / B 站收藏夹）—— v0.2+ 走 desktop 同样的 `expand` 接口
- [ ] 通用嗅探（headless browser 跑 15s 嗅探 m3u8）—— v0.2 单独 PR
- [ ] B 站 / 抖音 adapter —— v0.2+ 阶段 5/6 接
- [ ] Compose UI test for PromptOptionsDialog —— 阶段 5 加
- [ ] 标题模板批量应用（desktop `apply_title_template`）—— 阶段 5 多 URL 流程
- [ ] 选 format 后的"立即开始下载"按钮（v0.1 必须先入队，dialog 确认即入队）

### 文档同步

- [PHASES.md](../PHASES.md) — 阶段 4 标 ✅
- [CHANGELOG.md](../CHANGELOG.md) — 加 v0.2.0-android 段（待写）
- [REUSE-MAP.md](../REUSE-MAP.md) — `core/pipeline.py:parse_and_expand` 标 ✅ 落地
- [README.md](../../README.md) — 阶段 4 标完成
- [phase-4.md](phase-4.md) — 本文档
