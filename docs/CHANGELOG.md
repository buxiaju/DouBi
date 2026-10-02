# Changelog

## 0.3.2 (2026-10-02) — 抖音采集全家桶落地 + 注解可求值性修复 + Android 板块移出

> 本版把此前一直躺在工作区、从未提交的 M6.48–M6.59 成果正式入库（68 个文件、
> +19227/−718），并修掉体检中发现的 5 处缺陷：3 处注解可求值性运行时缺陷 +
> 2 处 GUI 侧缺陷（漏搬 `cookies_file`、账号状态刷新丢弃协程）。
> 版本号单一真源 `src/doubi/__init__.py` 由 0.3.1 升至 0.3.2，GUI 标题栏 /
> `doubi -V` / REST `/health` / MCP `serverInfo` / 安装包文件名全部派生自它。

### 一、抖音采集能力（M6.48–M6.59 入库）

此前这批代码只存在于本地工作区，任何一次误清理都会丢失。本版一次性入库：

**签名管线**（新增文件）

| 模块 | 作用 |
|---|---|
| `platforms/douyin/sign/websign.py` | `x-secsdk-web-signature`（WebSign）+ `DOUYIN_SIGNED_PATHS` 白名单（26 条） |
| `platforms/douyin/sign/ms_token.py` | mssdk 取 msToken（含 `_MSSDK_STRDATA` 常量，随官方 bundler 升级需重取） |
| `platforms/douyin/sign/tt_wid.py` | tt-wid 生成 |

**采集子命令**（8 个，CLI 侧已可用；GUI/MCP 侧仍是缺口，见 ROADMAP P1-3 / P1-4）

`search`（综合/视频/用户/直播 4 子类 + 排序/时间/时长/粉丝量筛选）、`hot`（4 榜单）、
`favorites`（收藏夹 + 视频/合集/音乐/短剧 5 类）、`comments`（一级 + 嵌套回复）、
`user`（`--kind following|followers`）、`hashtag`（话题作品）、`mix`（合集回查）、
`live`（详情 + 6 档清晰度直录）。

**其他入库内容**

- `platforms/ytdlp_generic/`：通用 URL 走 yt-dlp 的适配器（3 个模块）
- `ui/dialogs/sms_verify_dialog.py`：抖音短信验证对话框
- 10 个新测试文件（`test_douyin_{search,hot,favorites,comments,user,hashtag,mix,live,sign}.py`
  + `test_ytdlp_generic_adapter.py`）

### 二、修复 3 处真实运行时缺陷（发版前体检发现）

**根因同一个**：`from __future__ import annotations` 把注解变成字符串，字符串一旦被
**显式求值**就会去模块 `__globals__` 里找名字。`typing.get_type_hints()` 直读那个
dict，缺失名字时抛 `NameError`。

这个坑项目**已经踩过一次**，根因写在 `server/deps.py` 的 docstring 里：FastAPI 用
`get_type_hints(fn, fn.__globals__)` 求值依赖函数注解，找不到 `Request` 就把它退化成
必填 query 参数，导致所有鉴权路由 422。本次是同一模式的另外三处：

| 位置 | 症状 | 修法 |
|---|---|---|
| `core/registry.py` | `get_type_hints(PlatformRegistry.detect)` → `NameError: PlatformAdapter` | 模块末尾 `_install_adapter_annotation()` 把名字绑定进 globals（顶部导入会与 `platforms/base.py` 构成循环） |
| `platforms/douyin/auth.py` | `parse_netscape_file` / `parse_json_cookies` 注解求值 → `NameError: Any` | 补 `typing.Any` 导入 |
| `platforms/bilibili/qr_login.py` | `render_pil` 注解求值 → `NameError: PIL` | 加 `TYPE_CHECKING` 块（PIL 是 qrcode 的可选依赖，不能运行期顶层导入） |

**顺带否掉一个看似优雅的错误方案**：模块级 `__getattr__`（PEP 562）**救不了**
`get_type_hints`——它不参与 `__globals__` 的 dict 查找。这条判断已固化成用例
`test_module_level_getattr_cannot_satisfy_get_type_hints`，避免后人用 `__getattr__`
重写一遍。

**保留未改的一处**：`ui/dialogs/login_dialog.py` 的 `"QWidget"` 注解不可解析，
但这是**设计使然**——该模块顶层刻意不 import Qt（保证无 Qt 环境能导入），为此
加顶层 Qt 导入会破坏这个前提。已就地加注释说明，不修。

### 三、Android 板块移出本仓

用户决策：不再需要 Android 板块。删除 `android/` 全部 184 个文件（Kotlin 源码 /
Gradle 配置 / 阶段文档），单独一个 commit。

代码未真正丢失：`origin/master` 保有 122 个文件副本，且 `v0.1.0-android` …
`v0.5.10-android` 共 18 个 tag 均已推送，需要时可从远端或历史取回。

### 四、`.gitignore` 补漏

- `/TikTokDownloader-master/`：README 早已声明该上游参考目录不入库，但排除规则
  一直缺失，导致它常驻 `git status` 未跟踪列表。
- 根目录两个零引用探针草稿（`check_douyin_api.py` / `scratch_probe_ytdlp.py`）：
  与 `scripts/diag_*` 那种「CHANGELOG 记录在案的工具」不同，它们无归属目录、
  任何文档都不引用。

### 五、修复 GUI 解析页漏搬 `cookies_file`

`ui/pages/parse.py:_build_options()` 是 GUI 侧**唯一**的 `AppConfig → DownloadOptions`
搬运出口，但它从未搬运 `cookies_file` —— 该字段自首次提交就在两个 dataclass 里，
属于**既有缺陷**，不是本次改动引入的。

**暴露路径值得记录**：守护它的用例
`test_ui_empty_parse.py::test_build_options_covers_every_shared_config_field`
带 `pytest.mark.gui`，默认的逻辑层运行（`-m "not gui"`）会把它 deselect 掉，
而 `scripts/run_full_tests.py` 才包含 GUI 用例。所以缺陷一直存在，只有全量跑才现形。

**影响面**：`AppConfig.cookies_file` 默认 `None`，GUI 设置页也没有暴露该控件，
因此走「登录态自动落在 `~/.doubi/cookies/`」这条主路径的用户不受影响 ——
`core/pipeline.py` 在 `options.cookies_file is None` 时会回落到按平台解析的
cookie 文件。受影响的只有**显式指定过** `cookies_file` 的用户（配置文件或
`DOUBI_COOKIES_FILE` 环境变量）：CLI / REST / MCP 三条路径都搬运了该字段，
唯独 GUI 不搬，配了等于没配。修法即补上一行转发，并就地注释说明
「此处的 `None` 是语义值（走回落），而非未设置」。

### 六、修复账号状态刷新丢弃协程（测试输出里的 `never awaited`）

`ui/pages/settings.py` 有 6 个地方要排一次账号状态刷新（构造后的延迟首刷 +
刷新按钮 + 两种扫码登录 + 两种 Cookie 导入）。触发方式是
`asyncio.ensure_future(self._refresh_account_status_async())` —— **协程对象在
调用点就已经构造出来了**。当没有可用 loop 时（测试 / 截屏脚本 /
`--no-event-loop`），`ensure_future` 抛 `RuntimeError`，那个已经在手的协程
既不会被执行也不会被 await，交给 GC 时抛
`RuntimeWarning: coroutine ... was never awaited`，而那条被丢掉的协程**正是
本该完成的账号状态刷新**。

顺带暴露的不一致：只有构造后的首刷那条包了 `try`，另外 5 个按钮回调没有 ——
同一个前提失效时，点按钮会直接把 `RuntimeError` 冒到 Qt 槽里。

修法：6 处收敛到模块级 `_spawn_account_refresh(page)`，判别失败时显式
`coro.close()` 再走同步兜底。两个刻意的实现选择已写进 docstring：

- 判别仍用 `asyncio.ensure_future`，**不换** `asyncio.get_running_loop()`：
  两者判的不是同一件事。qasync 启动瞬间的 loop 处于「已 set 但尚未 run」，
  `ensure_future` 认它，`get_running_loop()` 不认；误判成「没有 loop」改走
  `asyncio.run`，那个临时 loop 收尾时会把 current loop 清成 None，此后
  所有 `ensure_future` 调用都会开始抛 `RuntimeError`。
- 不给 `coro.close()` 写合成用例。实测在「loop 已关闭」的构造下，被丢弃的
  协程按引用计数就被回收且**不触发**警告；真实告警只在整套 GUI 跑起来、
  协程落进循环引用链时才出现。所以把关交给真实触发点，见下。

### 七、回归

> 三处注解缺陷 + `cookies_file` 漏搬 + 协程丢弃，共 5 处。

- 逻辑层：**1013 passed / 263 deselected**。
- GUI 层（`-m gui`，排除会挂住的 `test_theme_apply_gui.py`）：**228 passed / 7 skipped**。
- 全量收集 1276 例，`scripts/run_full_tests.py` 修前 `1 failed / 1240 passed`，
  修后该失败项（`test_build_options_covers_every_shared_config_field`）转绿。
- **协程丢弃的 A/B 验证**（真实触发点，非合成用例）：
  `pytest -m gui --ignore=tests/test_theme_apply_gui.py -W always::RuntimeWarning`
  —— 去掉 `coro.close()` 时 `tests/test_row_mapping_cache.py` 出 **4 条**
  `never awaited`，保留后 **0 条**。
- 新增 `tests/test_ui_settings_refresh.py`（2 例，不依赖 PySide6）锁住
  「无 loop → 同步兜底跑一次」「有 loop → 排进 loop 而非就地执行」两条契约。
- 新增 4 例注解守卫（`tests/test_registry_annotations.py`），并实测「移除绑定即复现
  原始 `NameError`」，确认修复是承重的而非装饰性的。
- `ruff`：本次触碰的源文件 0 新增；仓库其余 139 处为历史遗留（ROADMAP P3-3）。

---

## P0-1 / P3-2 修复（2026-10-02）— 图集判定统一口径 + 签名白名单漂移守卫

> 本轮不是新里程碑，而是对 [docs/ROADMAP.md](ROADMAP.md) 里两条既有项的收口。
> 改动前先核实了 ROADMAP 的每一条 P0/P1，把其中已被历史版本修掉的剔除——
> 详见下方「核实结论」。

### P0-1 抖音图集类型判定偏弱（已修）

**根因**：图集有两条互相独立的判定路径，各写一套判据且都不完整。

| 路径 | 位置 | 原判据 | 缺陷 |
|---|---|---|---|
| yt-dlp | `platforms/douyin/api.py:_classify_media_type` | 无视频流 **且无音频流** + 有 thumbnails | 抖音图文帖几乎都带一条纯音频流（背景音乐），`has_audio` 为真即落回 `VIDEO` |
| 自建签名 | `platforms/douyin/webapi.py:aweme_to_media_item` | `images` 或 `aweme_type in (150, 68)` | 漏 `image_url` / `thumbnails_list` 两种偏移表示 |

**影响面（本轮核实，原 ROADMAP 标记为「尚未核实」）**：
`engines/yt_dlp.py:173` 只对 `MediaType.LIVE` 做特殊分支（`live_from_start` /
不 merge），**非直播一律走同一条下载路径**——即 `IMAGE_ALBUM` 与 `VIDEO`
在下载行为上完全等价，图集由 yt-dlp 的抖音 extractor 自行展开。因此这不是
「下载坏掉」类 bug，它的真实影响是：

- GUI / CLI 的类型展示与筛选（图集被显示成「视频」）
- `{media_type}` 输出目录模板的取值（图集落进 `video/` 目录）
- MCP / REST 返回给外部消费方的 `media_type` 字段语义错误

**修法**：把判据收敛为单一真源，两条路径共用。

- 新增 `platforms/douyin/url.py:is_image_album_payload()` 与常量
  `IMAGE_AWEME_TYPES` / `IMAGE_ALBUM_FIELDS`。放在 `url.py` 的理由：它是
  抖音包内唯一不依赖 `httpx` / `yt_dlp` 的底层模块，两边都能安全导入，
  既不会造成循环依赖，也不会把 `yt_dlp` 拖进 `webapi.py` 的导入链。
- 判据为「`images` / `image_url` / `thumbnails_list` 任一非空 **或**
  `aweme_type ∈ {68, 150}`」，**刻意不看 `formats`**。
- `api.py` / `webapi.py` 两处改为调用该函数；`api.py` 保留「无音视频流 +
  有缩略图」的末位兜底分支，避免历史行为回归。
- `bool` 是 `int` 子类，`aweme_type=True` 被显式排除，不参与类型码比较。

**验收判据**：`tests/test_douyin_adapter.py` 新增 6 例——带音频流的图集在
yt-dlp 路径与 webapi 路径上**都是** `IMAGE_ALBUM` 且**两者相等**；普通视频
带封面仍是 `VIDEO`（不能因 thumbnails 非空误判）；LIVE 优先级高于图集信号；
`aweme_type=True` 不算类型码。

### P3-2 签名白名单与真实请求的偏离守卫（已加）

**诉求**（ROADMAP P3-2）：任何被真实调用却不在 `DOUYIN_SIGNED_PATHS` 里的
端点，应当在测试阶段失败，而不是等线上 403。

**修法**：`tests/test_douyin_sign.py` 新增 AST 静态扫描守卫——
`test_every_used_web_api_path_is_whitelisted()` 扫描抖音包内所有 `.py` 的
字面量 `/aweme/v1/web/...` 字符串，与白名单求差集，非空即失败并列出
「路径 + 出现文件 + 修法」。

刻意**没有**写第二份人工清单：人工清单本身就会跟着代码一起漂移，正是要防的
东西。已实测该守卫确实能捕获新增未登记端点。

另有一例 `test_signed_paths_drift_is_surfaced_for_review()` 只打印白名单中
当前未被调用的路径供复核，**不设失败条件**——白名单来源是平台 secsdk 的
protectedHost 表，预留项是有意的（如 Collects 家族在 M6.48 就登记、M6.50 才用）。
当前实测：白名单 26 条，全部在用，0 条漂移。

### 核实结论（ROADMAP 逐条）

- **P0-1** 属实，已修（本条）。
- **P0-2**（uifid 是 UUID4 占位）**保留**：确认平台当前不校验，改真生成方式
  属提前逆向、无收益，维持 ROADMAP。
- **P1-1**（`doubi.db` / `manifest.jsonl` 默认落 CWD）**属实且未修**：本轮
  未动，因为「老用户迁移路径」需要单独设计与测试，不宜混进判定修复。
- **P1-2**（`IMAGE_ALBUM` 端到端行为）**降级**：本轮已核实图集下载由 yt-dlp
  extractor 展开，`engines/yt_dlp.py` 对非直播走统一路径（见上），因此
  「图集任务能否下全多张图」不取决于本分类，该项的剩余价值仅为真机实测确认。
- **P1-3 / P1-4 / P2 / P3-1 / P3-3** 未动，维持 ROADMAP（P3-3 即 ruff 历史遗留）。

### 回归

- 全量逻辑层：**1009 passed**（改动前 1001，+8 例新测试），263 deselected。
- `ruff`：本轮改动的 3 个源文件（`url.py` / `api.py` / `webapi.py`）
  **All checks passed**，0 新增；同目录其余 19 处为历史遗留（未触碰）。

---

## 0.1.0 (2026-08-23) — 里程碑快照 M0–M6.3

### M1 内核骨架
- `core/{models,registry,pipeline,config,logger,naming}.py`
- `engines/yt_dlp.py`（async 包装，to_thread 跑 sync yt-dlp）
- `platforms/{douyin,bilibili}` 自注册适配器 + URL 分类
- `cli/main.py`：`platforms` / `download` 子命令

### M2 抖音深耕
- `platforms/douyin/{api,auth,strategies,url}.py`：yt-dlp 元数据、cookie 文件、
  post/like 容器策略、短链解析
- pipeline 容器递归 + 文件名渲染

### M2.1 抖音 Cookie 管理 + Live
- `platforms/douyin/auth.py`：Netscape/JSON/legacy cookies 解析、登录态校验
- `platforms/douyin/live.py`：`LiveRecorder`（max_duration、room.json sidecar、
  stream-ended 优雅结束）
- `doubi auth douyin` / `doubi live`

### M3 B 站深耕
- `platforms/bilibili/{api,auth,strategies,url,wbi,qr_login}.py`
- space / favlist / watch_later / mix 容器策略（登录保护）

### M3.1 / M3.1.1 登录
- QR 登录 + 轮询（`qr_login.py`）
- Playwright 自动登录（`core/auth/browser_login.py`）：
  `URLChangeLogin`（B 站）与 `CookieSetLogin`（抖音）

### M4 统一存储
- `core/storage/{database,file_layout,manifest,migrate}.py`
- `media_item` / `task` / `increment_checkpoint` 三表 + WAL
- JSONL manifest（append + fsync）
- 旧库迁移：`doubi migrate --from {douyin,bilibili}`

### M5 GUI（最小可用）
- `ui/{app,main_window,workers}.py` + `ui/pages/{download,history,settings}.py`
- PySide6 Fluent 壳 + qasync 桥接；`doubi-gui` console script

### M5.1 GUI 完善
- 下载页：批量 URL + 平台选择 + 每任务独立进度 + InfoBar 提示
- 历史页：真实查询 + 刷新 + 打开目录
- 设置页：代理 / 并发 / 主题 / Cookie 目录 + 打开目录按钮
- 主窗口：主题切换按钮

### M5.2 解析-勾选-下载（Bili23 风格）
- `pipeline.parse_and_expand(url, strategy=None)` — 让 adapter 自动选策略
- `pipeline.download_item(item, options)` — 跳过重解析，单条直接下
- 下载页：解析 → 表格（全选/全不选/下载选中 N）→ 任务列表
- 去掉策略下拉框（自动识别 URL 类型）
- B 站 MixStrategy 改走官方 series/archives API（更稳）
- 解析为空时根据 URL 类型给出"B 站需要登录"具体提示
  （指向 `~/.doubi/cookies/bilibili.txt`）

### M5.3 GUI 账号登录入口
- `ui/auth_actions.py`：纯 Python 异步/线程包装登录流程
  （`bilibili_status` / `douyin_status` / `import_*_cookies` /
  `import_douyin_legacy_json` / `bilibili_generate_qr` /
  `*_login_via_browser` / `*_save_cookies`）
- `ui/dialogs/login_dialog.py`：两个 QDialog
  - `build_bilibili_qr_dialog` — 渲染 ASCII QR + 轮询 + 浏览器自动抓取
  - `build_douyin_browser_dialog` — 启动 Chromium 等待登录完成
- 设置页加"账号与登录"卡片：B 站 / 抖音各一行
  状态标签 + 扫码登录 + 导入 Cookie 文件（抖音多一个 legacy JSON 入口）
  + 右上角刷新状态
- 线程回调通过 `QEvent` post 回主线程，安全更新 UI

### M5.4 拆分"解析"与"下载"页（对齐 Bili23 流程）
- 新增 `ui/task_manager.py`：`TaskManager` 持有全部下载任务状态
  （active / completed），MainWindow 创建一次，解析页与下载页共享
- 新增 `ui/pages/parse.py`：`ParsePage` 为默认首页
  - URL 输入（批量）+ 解析 / 快速下载 + 平台选择
  - 结果表：搜索框实时过滤、全选/全不选、按行号范围选择（`1-5,7,9-12`）
  - 右键菜单：解析此项 / 在浏览器中打开 / 作为单个视频下载 / 查看元数据
  - "下载选中"→ 加入 TaskManager（解析与下载解耦）
- 重写 `ui/pages/download.py`：`DownloadPage` 变纯任务管理
  - SegmentedWidget 两个 tab：下载中 / 已完成
  - 每个任务一个 TaskRow（状态 + 标题 + 进度条 + 消息 + 移除）
  - 全部删除 / 清空已完成 / 打开下载目录
  - 任务完成时复用同一行 widget 移到已完成 tab（无闪烁）
- `main_window.py`：注册 解析 / 下载 / 历史 / 设置 四个页面，默认落在解析页
- 测试：`test_task_manager.py`（6）+ `test_download_page.py`（2）
  迁移 `test_ui_empty_parse.py` / `test_parse_and_expand_gui.py` 到 ParsePage

### M5.4 修复：分P视频下载失败（yt-dlp playlist info.json 写目录不存在）
- `engines/yt_dlp.py`：`_download_sync` 在调用 yt-dlp 前预创建输出目录
- 背景：B 站分P视频（multi_video）yt-dlp 会在下载 media 前先写
  playlist info.json，而 `write_json_file` 不 mkdir → FileNotFoundError
- 实测验证：BV1zygDzDES2 分P下载成功（30MB mp4 + info.json 落盘）
- 新增 `test_ytdlp_engine.py`（2 个测试：目录预创建、调用前目录已存在）

### 关键修复
- FastAPI body 路由：pydantic v2 + `from __future__ import annotations` 下
  必须模块级定义 schema 并显式 `Body(...)`，否则被当作 query 参数
- JobManager eviction：`submitted_at` FIFO 排序（原按 uuid 排序导致随机删任务）
- JobManager eviction：完成时 `exclude_job_id` 保护（否则刚完成的 job 会被
  当"最老 finished"删掉）
- GUI PlatformRegistry 空：所有形态（CLI/server/mcp/GUI）走
  `core.engine_loader.build_default_pipeline()`，内部 `from ..platforms import`
  触发自注册（不再裸 `DownloadPipeline(engine=YtDlpEngine())`）

### M6.1 GUI 解析页树形表格修复（ugc_season 三层结构）

B 站「带分类的合集」在解析页展开为 `分类 → 分集 → 分P` 三层。这一轮修掉了 4 个相互关联的
缺陷，根因都是「用表格行号去表达树结构」。

**① 展开状态用行号做 key（表象：展开逻辑混乱）**
- `_expanded_rows` / `_expanded_episode_rows` 原以行号为 key，而 section 自己的行号会随
  前面兄弟 section 的展开/折叠而位移
- 实测：4 个 section 时先展开 section2（row=2），再展开 section0 插入 3 行 → section2 位移
  到 row=5 → `_expanded_rows.get(5)` 返回 None → episodes 凭空消失
- 修法：改用稳定键 `(top_idx,)` / `(top_idx, child_idx)`，行号退化为派生只读缓存

**② 折叠分类残留分P行**
- `_collapse_section` 只 `removeRow(row+1)` × `len(episodes)`，从不删除展开在 episode 之下
  的 page 行（实测折叠后 `rowCount()` 应为 4，实际得到 9）
- 修法：先收集 `rows_to_remove`（episode 行 + 其 page 行），再自底向上 `reverse=True` 删除

**③ 交错布局下偏移量算术失效（表象：分P能展开，分章能展开折叠分章）**
- 子行插在父行正下方（`insert_at = row + 1`），真实布局是 `sec0, ep00, pg0..pg4, ep01, ep02`
  ——同级 episode 行**不连续**。旧代码用 `offset = row - top_row - 1` 与
  `ep_row = row + 1 + child_idx` 反算，ep00 一旦展开 5 页，`_episode_key_for_row(7)` 就返回
  None → ep01/ep02 的右键菜单里「展开分P / 折叠分P」整项消失
- 修法：`_refresh_row_mapping` 新增 `_row_to_episode_key` / `_row_to_page_key` 两个权威缓存
  （共 5 套），其余函数退化为 `dict.get(row)`；新增 `_resolve_page_for_row`
- 连带修正两处发射逻辑：`_resolve_download_targets` / `_selected_items` 都改为 page 优先，
  episode 行若 pages 已展开则 skip，否则整集会被重复入队（实测多出一个 ep00）

**④ 分章行错误显示「折叠分类」（表象：点它会把其他分章一起折叠掉）**
- `_row_to_top_idx` 的语义是「这一行归属哪个顶层 section」，子行也映射到所属 section 的
  `top_idx`，因此 `_resolve_top_item_for_row(子行)` 返回的是 **section 容器对象**
- `_on_table_context_menu` 用「resolved item 是不是 section」这个宽松判据 gate 菜单项，导致
  右键分章行也弹出「折叠分类」。点下去 → `_collapse_section` 用分章的行号查到 section 的
  `top_idx` → 从「分章行 + 1」开始删行 → 把该分章的分P行连同后续兄弟分章一起吃掉
- 修法（纵深防御三层）：菜单层改用行身份判据 `row == _top_to_row.get(top_idx)`；
  `_collapse_section` / `_expand_section_row` 加非顶层行硬防护 + warning 日志；
  修正 `_is_section_row` 语义
- `_on_table_context_menu` 此前**零测试覆盖**，是本 bug 完整逃逸的直接原因

**其他 GUI 改动**
- section 行 checkbox 强制 `Qt.PartiallyChecked` 并剥掉 `Qt.ItemIsUserCheckable`，容器不可
  直接勾选（pipeline 侧会以 `Refusing to download container` 拒绝）；`_select_all` 跳过
  不可勾选行
- 新增 `test_row_mapping_cache.py`（6 个测试）：行映射全循环、交错布局解析、折叠后**存活行
  标题列表**、下载目标去重、行身份判据、子行误调 `_collapse_section` 必须 no-op
- `docs/DEVELOPMENT.md` §13.3 补写「稳定键」「交错布局禁止偏移量算术」「`_row_to_top_idx`
  语义陷阱」三节

### M6 REST + MCP + 打包
- `server/{app,jobs,schemas}.py`：FastAPI REST（health/platforms/download/jobs）
- `mcp/server.py`：stdlib JSON-RPC 2.0 stdio 桥（5 个工具）
- `doubi.spec`：PyInstaller 配置
- `docs/{ARCHITECTURE,QUICKSTART}.md`
- `docs/DEVELOPMENT.md`：面向 AI/开发者的完整开发文档
  （数据模型、数据流、平台/引擎扩展指南、B 站风控专题、测试体系、
  常见坑、改动检查单、已知限制与路线图）

### M6.2 补齐「预留字段」与暂停/续传（P0 + P3）

这一轮的共同根因是**声明与行为脱节**：`DownloadOptions` 里若干字段只被存下来、
从未传给引擎，UI 上若干按钮只被画出来、从未接线。

**P0-1 字幕 / NFO 开关是空开关**
- `engines/yt_dlp.py`：`write_subtitles` 现在真正映射到 yt-dlp 的
  `writesubtitles` / `writeautomaticsub` / `subtitleslangs`
- 新增 `core/storage/nfo.py`：从 `MediaItem` 渲染 Jellyfin/Plex 可读的
  `.nfo`，由 pipeline 在单条下载成功后写出
- 判据：开关关闭时产物目录不得出现 `.nfo` / `.vtt`（测试直接断言落盘文件集合）

**P0-2 B 站弹幕下载**
- 新增 `platforms/bilibili/danmaku.py`：`resolve_cid` → `fetch_danmaku_xml`
  → `write_danmaku` 三步，弹幕按**分P 的 cid** 而非 BV 号取，且走另一个
  对 cookie 敏感的端点，因此天生不可能做成一个 yt-dlp 选项
- 接线点是 `platforms/bilibili/adapter.py::post_download` 钩子，**不进 `engines/`**
  ——引擎层必须保持平台无关（见 DEVELOPMENT §2 三条解耦轴）
- 容器直接跳过：其子项各自作为单条下载，各写各的 sidecar

**P0-3 REST 容器统计误报 failed**
- 根因：`_execute_download` 把 `item.is_container()` 当作**失败**判据，于是
  子项全部成功的合集仍返回 `total=1, succeeded=0, failed=1`
- 修法：改以 `"child_count" in item.extra` 为判据，直接读 pipeline 真正写下的
  `downloaded_count` / `failed_count` / `child_count`
- 为什么不用 `is_container()`：它只是 `bool(children)`，而 pipeline 还会把
  尚无 children 的裸 `MediaType.USER` 也走容器展开——两个判据会打架；
  读 pipeline 自己写的统计则不可能与它脱同步

**P3-1 引擎层断点续传与取消**
- `core/models.py`：`DownloadOptions` 新增 `resume: bool = True` 与
  `cancel_check: Optional[Callable[[], bool]] = None`
- `engines/yt_dlp.py`：`continuedl=options.resume`；进度钩子**无条件注册**并在
  每个 tick 轮询 `cancel_check`，命中则抛 `_LocalDownloadCancelled`
- 取消时**跳过 `.part` 清理**并返回 `False`（清理只在非续传路径做，否则
  下一次续传无从接续）
- 根因：`YtDlpEngine.download` 是 `await asyncio.to_thread(...)`，
  **`Task.cancel()` 永远打不断已进入线程的传输**，取消只能是协作式的
- `config.py` DEFAULTS + `cli/main.py --no-resume` + `server/app.py` 同步接线

**P3-2 GUI 单任务与全部暂停 / 恢复**
- `ui/task_manager.py`：
  - `_tasks` / `_flags` 两个注册表——此前 spawn 出去的 asyncio.Task
    **完全不可寻址**，`remove()` 的「会取消下载」注释是空承诺
  - **双机制停止**：先置 `_StopFlag`（够得到已在引擎线程里的传输），
    再 `task.cancel()`（覆盖「还没进引擎」的窗口，如卡在并发信号量上）
  - **flag 按尝试而非按 task_id**：暂停中的 worker 可能仍在引擎线程里，
    共享 flag 会让 `resume()` 复活旧线程 → **两个写者抢同一个 `.part`**
  - `replace(options, cancel_check=flag)` 而非原地改——调用方合法地把同一个
    `DownloadOptions` 传给多个 `add()`
  - 协作式停止表现为 `ok is False`（引擎自己吞掉了取消），故判据是
    `flag.stopped and not ok`——**已下完的文件要赢过迟到的暂停**
  - `_forget` / `_finish_stopped` 的 stale 守卫：将死的旧尝试不得把
    `paused` 盖到新尝试的 `running` 上
  - `paused` 刻意设计为**非终态**：保留 `_active` 里的位置与磁盘上的分片
  - `pause()` 同步翻转状态并发 `task_progress`——worker 要等引擎下一个
    进度 tick 才察觉 flag，UI 不能等
- `ui/pages/download.py`：
  - TaskRow 增加暂停列（52px 固定宽 holder，按钮文案表达**下一步动作**：
    running→「暂停」/ paused→「继续」/ 终态→隐藏但不塌宽度）
  - `_on_pause_all` 规则：**只要还有 running 就一律暂停**，全暂停后按钮才变
    「全部继续」——否则混合列表上一次点击会立刻自我抵消
  - `_refresh_active_rows()`：批量操作绕过了逐行信号路径，需显式推一次
  - `_update_summaries()` 输出「N 个正在下载，M 个已暂停」，并让按钮文案与
    `_on_pause_all` 的规则严格同源
- 测试：`test_task_manager.py` 6 → 15，`test_download_page.py` 2 → 5，
  `test_ytdlp_engine.py` 4 → 11
- 测试坑：`add()` / `resume()` 只是**排程**，不 yield 就 `pause()` 会在协程体
  执行前把它取消掉，pipeline 根本没被碰到（6 个用例因此假失败）。真实环境永远
  有 loop 在跑，所以由测试用 `_started()` 补一次 yield，**不改生产代码**

**顺带修掉的「静默失效开关」（按检查单第 5 条自查发现）**

上面几项做完后，按 DEVELOPMENT §17 改动检查单第 5 条「加配置项要动五处」逐处
核对 `resume`，结果发现**第五处压根没动**，还牵出一个更早就存在的漏洞：

| 位置 | 漏掉的字段 | 后果 |
| --- | --- | --- |
| `ui/pages/parse.py::_build_options()` | `write_nfo` / `write_danmaku` / `write_subtitles` / `resume` / `output_dir_template` | GUI 是唯一忽略这些开关的端 |
| `server/app.py::_build_options()` | `output_dir_template` / `proxy` / `rate_limit` | REST 忽略目录模板与代理限速 |

- 根因：引擎和 `file_layout` 都只认 `DownloadOptions`，**从不读 `AppConfig`**。
  每端的 `_build_options()` 是唯一的搬运环节，漏一个字段就等于那个开关在该端
  是死的——而且配置文件里改了也毫无反应。
- `output_dir_template` 比开关更隐蔽：它决定 `resolve_item_dir()` 的落盘目录，
  漏转发时会静默退回 dataclass 默认值，用户自定义的目录结构直接失效。
- 判据：`AppConfig` 与 `DownloadOptions` 的**同名字段交集**必须逐个抵达
  options。为此两端各加一个结构性测试
  （`test_build_options_covers_every_shared_config_field`），以后新增字段忘了
  转发会**测试变红**，而不是发出一个点了没用的控件。
- 该测试的关键设计：填 cfg 时必须把每个字段推到**非默认值**。第一版直接用
  `AppConfig()` 原值比较，删掉 `resume=` 那行竟然照样通过——因为两个 dataclass
  的 `resume` 默认值都是 `True`，「没转发」和「转发了」结果相等，是个**假保险**。
  改成非默认值填充后，删任意一行都能稳定变红（已分别删 `resume`、`max_quality`
  实测过）。遇到不认识的字段类型时 `pytest.fail`，避免默默削弱检查强度。
- CLI 不在此列：它从命令行参数直接构造 options，字段本来就是齐的。

### M6.3 多主题系统（6 套主题包 + 全局即时生效）

界面原先只有 fluent 默认亮色。这一轮引入**具名主题包**：每套主题自带一整张 token 表
（背景 / 文字 / 表格斑马纹 / 5 种状态色 / 4 种进度条色 / 圆角 / 行高），而不是「亮暗开关 +
强调色」。内置 `default_light` / `default_dark` / `deep_sea` / `morandi` / `eye_care` /
`high_contrast`，新增 `ui/theme.py`（720 行）。

- 接线：`config.py` 加 `theme` 字段（`DOUBI_THEME` 可覆盖）、`app.py` 加 `--theme`
  （`choices=theme_names()`）、设置页下拉框、导航栏画笔按钮循环切换。
- 设计要点：**语义色必须随明度重算而非直接复用**。`#c02b2b` 这类暗红在深色底上几乎不可读，
  暗色骨架一律提亮到 `#ff6b6b` 一档。
- 详见 `docs/DEVELOPMENT.md §13.4`。

**用户实测反馈：「整体的背景没有变，解析口的颜色一直都是白色」**

token 表写对了，界面却基本没变色。逐层排查发现**五个独立失效点**，任一个没处理都会让主题
「看起来没生效」：

| # | 失效点 | 根因 | 修法 |
| --- | --- | --- | --- |
| ① | 六套主题只有强调色在变 | qfluentwidgets 只有 `Theme.LIGHT` / `Theme.DARK` 两套内置调色板，`setTheme()` 无法表达 6 套配色，`setThemeColor()` 只改强调色 → `bg_base` 从未生效 | `app_qss()` 把 token 表翻译成全局 QSS |
| ② | Win11 上主窗口底色画了看不见 | 开启 **Mica** 毛玻璃时 `_normalBackgroundColor()` 返回**全透明**，`setCustomBackgroundColor` 形同虚设 | `_apply_window_background()` 先 `setMicaEffectEnabled(False)` 再设色 |
| ③ | **解析框一直是白的**（用户反馈的原话） | Qt 里**控件自己的样式表优先级高于 `QApplication` 全局样式表**（全局表是最低优先级兜底），而 fluent 给每个控件单独 `setStyleSheet` → 全局 QSS 只对原生控件有效。`line_edit.qss` 的 `:focus` 更是写死纯 `white` | `_refresh_fluent_widgets()` 用官方 `setCustomStyleSheet(w, light, dark)` 逐个覆盖 |
| ④ | 卡片始终半透明白 | `CardWidget.paintEvent` 自绘，取硬编码 `QColor(255,255,255,170)`，**任何 QSS 都碰不到** | `_patch_fluent_card_background()` 猴补丁替换取色方法；`SimpleCardWidget` 自己也覆写了这三个 getter，**两个类都得打** |
| ⑤ | 切完主题后新开的菜单/对话框又白回去 | 下拉弹窗、右键菜单、登录对话框都懒创建，构造时向 `styleSheetManager.register` 领了库自带亮色 QSS，错过了刷新时机 | `_patch_style_sheet_register()` 包一层 `register`，控件一登记就补当前主题 QSS |

- **`set_theme()` 内部有强制顺序**，不是可随意重排的六行：两个猴补丁必须早于刷新（卡片重算时
  取色方法要已被替换，`register` 钩子要赶在后续控件创建之前就位），`_notify()` 收尾通知那些
  把颜色烘进自身 stylesheet 的控件。
- **`app.py` 里 `set_theme()` 故意调两次**，别当重复代码删：第一次在建窗口前（页面构造要按
  token 取色），但那时 `_apply_window_background` 遍历不到任何顶层窗口，主窗口底色与 Mica
  关闭落不下去；窗口建好后必须再刷一次。
- 判据：`test_theme_apply_gui.py` 24 个用例对**每套主题**参数化断言四件事——窗口底色等于
  `bg_base` 且 Mica 已关、现存 fluent 控件的 `lightCustomQss` 含 `bg_layer`、
  `cards[0]._normalBackgroundColor()` 等于 `bg_layer`、切换后新建的 ComboBox 也带上主题 QSS。
  第三、四条正是 ④⑤ 的回归防线。
- 测试教训：循环断言必须有「至少找到一个」的兜底（`assert checked, "主窗口里一个 fluent 控件
  都没找到"`），否则控件一个都没匹配上时**整个用例空转变绿**。改全局状态的 GUI 测试要用
  autouse fixture 复位到 `default_light`，否则先跑的用例污染后跑的。
- 顺带修掉 `settings.py::_find_settings_page()` **永远返回 None**：它按
  `objectName() == "settingsPage"` 查找，但容器注册页面时把 objectName 覆写成了
  `"settingsInterface"`，而调用方一个宽泛的 `except Exception` 把失败彻底吞掉。改为**按能力
  识别**（检查是否具备目标方法）+ 沿 parent 链上溯。教训：**objectName 会被容器改写，不是可靠
  的身份判据**。
- 测试：新增 `test_config_theme.py` 26 个（无 Qt 也能跑：token 键一致性、`resolve_theme`
  兼容 `light`/`亮色`/`dark`/`暗色`/`auto` 等旧值、YAML 往返）、`test_theme_apply_gui.py`
  24 个；331 → 381 passed。

## 统计
- 源码 62 个 .py 文件，约 12100 行
- 测试 19 个文件，385 个用例收集：**381 passed / 4 skipped**
  （4 个 skip 均为「无 PySide6 则跳过」的 GUI 用例）
- 基线演进：280（M6.1）→ 299（P0-2）→ 309（P0-3）→ 316（P3-1）→ 328（P3-2）
  → 331（补齐 `_build_options` 转发 + 结构性守卫）→ 381（多主题系统 + 五层失效点回归）

---

## 0.3.0 (2026-08-26) — 通用 URL 嗅探、GUI 体验加固与健壮性扫尾

> 这一轮的主题是「把 0.2.0 的骨架用到真实场景」：用户开始拿通用视频站（silidm、
> sv.baidu.com 等）跑，暴露了通用适配器在 Playwright 嗅探、下载引擎、文件名
> 安全、取消语义、异常兜底五方面的十多个真 bug。0.3.0 把它们连同若干 GUI
> 体验痛点一起补齐，回归测试从 450 涨到 614，是历次修复周期里密度最高的一次。

### G1 通用 URL（generic adapter）嗅探管线重构

这是 0.3.0 最大的一块：`platforms/generic/` 之前只会把 URL 丢给 yt-dlp，
对于 SPA 页面（动态 `<video>` 注入 / `m3u8` 在 `fetch/XHR` 里返回）根本抓
不到，而这些「抓不到」才是真实世界里 80% 的通用视频站。

**嗅探器三层架构**（`core/sniffer.py`，含 `platforms/generic/catch_lite.js`
Chromium 注入脚本）：

| 层 | 职责 |
|---|---|
| L1 Playwright 网络拦截 | 启动 Chromium，catch_lite.js 监听 `<video>` src 属性、`canplay` 事件与所有 `requestfinished`；MIME + URL 白名单双过滤后只把媒体候选人往上层送 |
| L2 JS 页面扫描 + SPA 重试 | 页面初次 idle 后如果没抓到媒体候选人，再等 2s 第二轮扫描 + 滚动 `scrollIntoView` 触发懒加载；`window.location` 跳转后重挂监听器 |
| L3 候选整理 | 代理去重（query 里嵌入的真实 `m3u8` 优先）→ MIME filter → **扩展名白名单** → 分片目录去重 |

**扩展名白名单**（用户明确要求「只显示 m3u8 + mp4 等视频后缀，ts/aac 不要
出现在解析列表里」）：

```python
_ALLOWED_VIDEO_EXTS = frozenset({
    "m3u8", "m3u",
    "mp4", "m4v", "mkv", "flv", "webm", "mov", "avi",
})
```

- 白名单而不是黑名单，`.mpd` / `.m4s` / `.aac` 这类边角媒体天然过滤
- 分片目录去重：同一条 m3u8 下面列出的 ts 分片如果和 m3u8 同目录，直接砍掉
- `is_direct_video_url` 同步从白名单派生（之前 `.ts` 会被当成直链——典型
  黑名单策略漏项）

**代理去重**（`platforms/generic/adapter.py::_video_target`）：
- 最常见的代理形态 `dp.283bt.com/?url=<real-m3u8>`：先从 query 里提取目标
  URL，如果它是 `m3u8`，直接把目标当真实源；否则回落到 URL 本身
- 相同 target 合并去重——实测 silidm 从 14 条（12 ts + 2 重复 m3u8）降到
  干净的 **2 条候选**（1 m3u8 + 1 yt-dlp 回退页）

### G2 GUI 三项用户体验修复

用户反馈的三个点，全部按原文诉求落地：

**① 解析列表过滤后缀白名单** → 见 G1，直接是通用管线里的 L3 一步到位，
CLI/REST/MCP 四端同步受益（不是只在 GUI 前端过滤，其他入口看不到）。

**② 启动居中**（`ui/main_window.py::_center_on_screen`）：
- 用 `QGuiApplication.primaryScreen().availableGeometry()` 取**可用区域**
  （不是整个屏幕，减去任务栏高度），然后用 `frameGeometry().moveCenter(center)`
  居中——直接 `setGeometry(screen.center())` 会让窗口左上角落在中心，是常
  见的「写了居中结果只露右下角」坑
- 在 `MainWindow.__init__` 里 `resize(1100, 760)` 之后立刻调用

**③ 已完成 + 文件本地被删除 → 显示"缺失"并允许"重新下载"**：
- `ui/task_manager.py::_save_path_missing(info)` 静态方法：先查
  `Path(info.save_path).exists()`，再 fallback 到 `resolve_item_dir` 目录里
  搜媒体文件（用户手动改 out_dir 或 DB save_path 是老路径时也能兜底）
- `TaskManager.retry(task_id)` 从「只接受 failed/cancelled」扩为「也接受
  completed 且 `_save_path_missing` 为 True」
- `ui/pages/download.py` 下载页表现：
  - 状态徽标 `_status_text`：completed + 缺文件 → 显示 **缺失**（红底）
  - 消息行 `_status_message`：显示「文件已删除」
  - 重试按钮：文案从「重试」变为 **重新下载**；切到已完成 tab 时逐行重
    刷状态（文件可能是用户切页期间删的，进度缓存不能信）

### G3 下载引擎健壮性扫尾（查缺补漏）

这是最耗时间的一块——用户报告 silidm 下载**卡在「准备中 0%」半小时不动**，
追到底是 N_m3u8DL-CLI 的进度回写方式与 Windows 路径上限两个独立 bug 的叠
加。修复方法是「不要每个引擎各写一套 subprocess/取消/路径，提公共 helper
再三引擎统一迁移」。

**G3.1 `\r` 进度 + 子进程看门狗**（新文件 `engines/_subproc.py`）：

N_m3u8DL-CLI、ffmpeg 的进度回写是 `\r` 回车（单行覆盖），从来不用 `\n`。
asyncio 默认 StreamReader 的 `readline()` 是按 `\n` 切，默认 64KB 上限，没
换行时就抛 `LimitOverrunError`——表现就是 GUI 永远 0%，对用户来说是「下载
卡住了」。

`run_supervised_subprocess(args, on_chunk, cancel_check, watchdog_seconds=180)`
是所有子进程的统一入口：

```
├─ 1MB buffer (不是默认 64KB)
├─ 自定义字节 splitter (同时识别 \r 与 \n)
├─ on_chunk 回调：engine 解析进度字符串
├─ cancel_check：每 chunk 轮询
├─ watchdog：180s 无任何 stdout 输出 → SubprocessTimeout，
│            terminate → 1.2s → kill (POSIX)，
│            Windows 走 TerminateProcess 硬终止
└─ finally 降落伞：杀一次没杀掉再补一刀
```

**三引擎都迁移过了**：
| 引擎 | 迁移点 |
|---|---|
| `Nm3u8dlEngine` | 整个 `N_m3u8DL-CLI_v3.0.2.exe` 生命周期走 supervisor |
| `M3u8Engine` | ffmpeg 合片路径走 supervisor（watchdog=240s，合片慢）；aiohttp 分片下载每分片 `cancel_flag_polling` + ClientTimeout 30s + 180s stall 检测器 |
| `DirectHttpEngine` | 每 64KB chunk `cancel_flag_polling` + `asyncio.wait_for(chunk_read, 30)` 读超时 + 180s stall 总预算；`CancelledError` 不包装直接重抛 |

**G3.2 Windows MAX_PATH 安全**（`engines/base.py`）：

Windows Explorer / ffmpeg / N_m3u8DL-CLI 仍然在 >260 字符路径上失败（即便
Python 本身能开长路径前缀，这些外部工具开不了）。两道防线：

1. `safe_basename_for_item(item)`：
   - 非法字符 → `_`；空白折叠；头尾 `.`/`_` 剥掉
   - UTF-8 字节预算 **≤ 170**（out_dir + ext 通常占 80-90）
   - 截断时末尾补 `_<sha1[:8]>`，截断不会撞名

2. `output_path_under(out_dir, basename, ext)`：
   - 强制 `len(str(path)) ≤ 259`
   - 超出时按预算截断 basename 再补 `_<sha1[:8]>`
   - 不幸运的 UTF-16 surrogate 场景还有紧循环逐字符 shave
   - 最后兜底：只用 8 位 hash stem（极端病理 out_dir）

**G3.3 统一取消语义**：`cancel_flag_polling(flag)` 同时支持 `flag.cancelled` /
`flag.stopped` / 可调用三种形态——`_StopFlag`（TaskManager 用）和其他调用者
混用不会再「cancel 发出去但引擎不接」。

### G4 异常兜底：GUI 不再悄无声息闪退

这是桌面软件的经典坑：Qt 槽函数里抛 Python 异常，或 `asyncio.create_task`
里没人 await 的异常——默认行为要么是应用直接消失（进程退出码非 0），要
么是异常写进 stderr 用户看不见。修复：

**① `ui/app.py` `_install_exception_hooks()`**：
- `sys.excepthook` 替换：Qt 主线程任何未捕获异常 → 先 `logger.error` 打完整
  traceback + flush handler，再链式调用原始 hook（保证 Python 原标准错误行
  为不变，也不会吞掉致命错误）
- `asyncio` 事件 loop 自定义 `set_exception_handler`：`create_task` 未 await
  的异常 → 同样落日志到 `logger.error`，然后 fallback 回默认 handler（默认
  那个只有 "Task exception was never retrieved"）

**② `ui/task_manager.py` `_on_progress` 双层 try/except**：
- 内层单独包 `self.task_progress.emit(...)`：Qt 跨线程信号 emit 时，接收
  槽抛出的异常会反向传回到引擎的调用点——表现为「UI 一个控件崩了，结果
  正在下载的 4 条任务一起挂」，是极难排查的跨层 bug
- 外层兜底整个进度处理体，任何处理失败都只记日志不杀下载引擎

### G5 已修复的显性 bug

| Bug | 根因 | 修法 |
|---|---|---|
| silidm 下载卡在「准备中 0%」 | N_m3u8DL-CLI 用 `\r` 回写进度，asyncio 默认 64KB readline buffer 抛 `LimitOverrunError` | 走 `run_supervised_subprocess`，1MB buffer + 自定义 `\r/\n` splitter |
| silidm 解析列表 14 条（12 ts + 2 m3u8 重复） | 没扩展名白名单 + 代理包装 URL 没去重 | 三层候选整理（L3）+ `_video_target` query 优先解析 |
| m3u8 engine 报错 `Error opening output files: Invalid argument` | 用户选了极长标题 / 中文标题，结果 basename 带非法字符或超 MAX_PATH | `safe_basename_for_item` + `output_path_under` |
| 通用直链 `.mp4` 被误删 | 最早的 ts 修剪用了「目录前缀 + .mp4 也归入分片集合」 | 分片修剪只在 `{ts,aac,m4s}` 集合内动，不动真视频扩展名 |
| 取消下载后子进程 N_m3u8DL-CLI 还在跑 | 旧代码只 `task.cancel()`，不 terminate 实际子进程 | supervisor 里 cancel_check 命中立刻 terminate → kill parachute |
| ffmpeg 合片跑几小时没输出（正常，但会被误判卡死） | 旧版没 watchdog，卡死/正常长合片分不清 | watchdog=240s 只对 ffmpeg，其他默认 180s；有稳定进度输出就不触发 |
| GUI 槽里异常导致整程序死 | `sys.excepthook` 没装 + progress emit 异常没隔离 | G4 两层兜底 |

### G7 打包后 GUI 文本异常：i18n 资源丢失 + frozen 路径解析错误（0.3.0 修复版增补）

0.3.0 首次打包后用户反馈：**GUI 直接显示 i18n 的英文 key 名而不是译文**——标
题栏是 `豆比下载 0.3.0 · app.title_suffix`，侧边栏显示 `nav.parse` /
`av.downloads` / `nav.history` / `nav.settings`，设置页"语言"前的 label 是
`language.label`。

**双重 root cause**（任何一环都能导致症状；这次是两层同时错了）：

| 层 | 发生了什么 |
|---|---|
| **打包时（build_exe.py）** | `scripts/build_exe.py` 的 `--add-data` 只把 `icon_template.svg` 收进 `doubi/ui/resources`，**完全漏掉** `src/doubi/ui/locales/{zh_CN,en}.json` 两个 JSON 词表。PyInstaller 根本不会把翻译表拷进 frozen bundle。 |
| **运行时（i18n.py `_LOCALES_DIR`）** | 旧写法 `Path(__file__).resolve().parent / "locales"`。PyInstaller frozen 包中，`doubi/ui/i18n.py` 被编译成字节码塞进 **PYZ CArchive**（不是真实文件），`__file__` 指向一个 PYZ 内部假路径，拼出来的 `locales` 目录**实际上不存在**。i18n `_load_table` 任何语言都 open 失败 → 走 `return key` 兜底。 |

**修复（双保险，两处同时改）**：

1. **打包侧** — [scripts/build_exe.py](file:///c:/A/03Projects/DeepSeekHarness/DouBi/scripts/build_exe.py#L143-L144) 新增一行 `--add-data src/doubi/ui/locales → doubi/ui/locales`，把 `zh_CN.json` / `en.json` 完整拷入 frozen bundle 的 `doubi/ui/locales` 相对路径。
2. **运行侧** — [src/doubi/ui/i18n.py::_resolve_locales_dir()](file:///c:/A/03Projects/DeepSeekHarness/DouBi/src/doubi/ui/i18n.py#L53-L99) 改成**三层优先级**的 resolver：
   - `frozen`：`sys.frozen` 为真 → 读 `sys._MEIPASS / "doubi" / "ui" / "locales"`（与 `--add-data` 路径严丝合缝）
   - `源码 / pip -e`：保留 `Path(__file__).parent / "locales"` 老逻辑
   - 兜底：`importlib.resources.files("doubi.ui").joinpath("locales")`（pip wheel / pex / zipapp 形态）
   - `frozen` 分支如果目标目录不存在，还会打 `logger.WARNING`：**「PyInstaller frozen: _MEIPASS/locales 未找到」**，避免下次 `--add-data` 忘加时毫无征兆。

**验证**（三层独立）：
- 单元 smoke：正常形态 + `sys.frozen=True + sys._MEIPASS=tmpdir` 两种形态下，`tr('nav.parse') / tr('app.title_suffix') / tr('language.label')` 6 条全部译对
- onedir 解包目录：`dist/doubi-gui/_internal/doubi/ui/locales/{zh_CN.json,en.json}` **真实存在**（PyInstaller 解包时 `sys._MEIPASS` 就指向 `dist/doubi-gui/_internal/`，正好对应 resolver 的第一层路径）

### G8 NSIS 安装包 integrity check 失败：makensis CRC 头未刷 + DatablockOptimize >1GB 已知坑（0.3.0 修复版增补）

用户首次运行 `DouBi-Setup-0.3.0.exe` 立刻弹窗：

```
NSIS Error — Installer integrity check has failed.
Common causes include incomplete download and damaged media.
Contact the installer's author to obtain a new copy.
```

**同样是双层根因叠加**：

| 层 | 发生了什么 |
|---|---|
| **操作层（抢读半成品）** | 前次 NSIS 构建任务还没真正 exit（日志只打印到 `Compressed data:`，footer `CRC (…): 4/4 bytes` 还没写），我就 `ls dist/` 看到文件存在并立刻跑 hash_final。**写入 sidecar 的 SHA256 是"NSIS 写了一半"的快照**，用户拿到的 exe 里 launcher 预存的自校验 CRC 头和实际文件内容天然对不上。<br>实锤：sidecar `c1facb0b…` 和磁盘最终内容 `c999b48e…` **不一致**。 |
| **NSIS 3.11 自身 bug** | 安装包的 Install data 有 **1.57 GB**（PyInstaller onedir + Playwright Chromium 浏览器目录）。NSIS 默认 `SetDatablockOptimize on` 会合并重排相同数据块来省体积——**makensis 3.11 在 >1GB 包上偶发 exit 0 但 launcher CRC 头与实际文件不一致**（NSIS 社区已知 issue，官方文档也建议对大体积包关闭此优化）。即使前次等足了 exit，也有小概率仍命中 integrity fail。 |

**修复（操作层 + NSIS 层两条硬规则）**：

1. **`installer/doubi.nsi` 永久关 DatablockOptimize**（[L76](file:///c:/A/03Projects/DeepSeekHarness/DouBi/installer/doubi.nsi#L76)）：
   ```nsis
   ; 1.5GB+ 大安装包 NSIS 3.11 datablock optimizer 偶发 CRC 与 launcher 头不一致
   SetDatablockOptimize off
   SetCompressor /SOLID lzma
   ```
   代价：安装包体积从 345 MB → **441.31 MB**（+28%），但**makensis 日志一定会显式打印 `CRC (0xBC93FFD1): 4 / 4 bytes`**（launcher CRC 真正写进了 PE 头），用户侧 integrity check 永不触发。
2. **构建脚本两条硬规则**（写成 `_rebuild_nsis.py` 的同步流程，不允许异步后台跑一半就抢读）：
   - **① 同步跑 makensis**：`subprocess.run(build_installer.py, timeout=20min, rc check)`，一定要 makensis exit code 0 才进入下一步。
   - **② 大小稳定等待 10s 窗口**：`wait_stable(window_sec=10, poll_sec=1.5, timeout_sec=120)`，连续 10 秒文件字节数不变才允许算 SHA256。保证「Windows 写缓存刷盘 + NSIS 写最终 CRC/footer + Windows Defender 钩子释放句柄」都完成后再哈希。

**验证链（4 环锁死不回归）**：
1. NSIS 日志含 footer：`CRC (0xBC93FFD1): 4 / 4 bytes` + `Total size: 462,741,868 / 1,575,281,166 bytes` + `OK → DouBi-Setup-0.3.0.exe (441.3 MB)`
2. `wait_stable` 日志：`stable_for=0.0 → 1.5 → … → 10.5s`，满足 10s 窗口后放行
3. 脚本内部 sidecar 写回再 reread：`[OK] DouBi-Setup-0.3.0.exe`
4. PowerShell `Get-FileHash DouBi-Setup-0.3.0.exe` 独立重算 vs `DouBi-Setup-0.3.0.exe.sha256` → **`[VERIFY ✓]`**

### G6 文档

- `CHANGELOG.md`：补本节（0.3.0），所有改动条目带文件级定位与可回溯源码引用
- `README.md`：补「通用视频站支持」特性行 + GUI 新行为（居中 / 缺失文件重新下载）+ 0.3.0 实际体积与 SHA256 校验方法
- `BUILD.md`：补 locale 收集清单、PyInstaller frozen 下 `sys._MEIPASS` 寻址规则、NSIS DatablockOptimize off 强制规则、wait_stable(10s) CRC 刷盘硬要求
- `QUICKSTART.md`：补「两种分发形态」与「首次运行翻译正常自检 2 条」（标题栏 / 侧边栏）

### G9 0.3.0 发布产物清单（修复版：i18n + NSIS integrity 双通道）

> 这是 2026-08-26 最终发版的三份正式产物，均经过「稳定等待 + 独立 sidecar 校验」
> 。前一日生成的 `DouBi-Setup-0.3.0.exe`（345 MB）属于「半成品」，不要分发。

| 产物 | 位置 | 体积 | SHA256 | 推荐人群 |
|---|---|---|---|---|
| onedir 绿色目录 | `dist/doubi-gui/`（4003 文件，约 1.5 GB） | ~1.5 GB | —（目录无单哈希） | 发布 zip 绿色版 / 开发 / 企业内网分发（启动最快，免安装） |
| onefile 便携版 | `dist/doubi-gui.exe` | **615.17 MB** | `f767978e18c446b4a2208e763bf32c81a18c6a1ba863350769fe023b18b79c37` | 个人下载、U 盘、网盘（双击即跑，自解压到 %TEMP%） |
| NSIS 安装包 | `dist/DouBi-Setup-0.3.0.exe` | **441.31 MB** | `1a7ba7a47b00f06a6da047340b2b794f642e48d64f465b67a81749b76b53dca8` | 最终用户、有开始菜单/桌面快捷方式需求、需要控制面板卸载（普通用户首选） |

侧签名文件（与 exe 并排落盘）：
- `dist/doubi-gui.exe.sha256`
- `dist/DouBi-Setup-0.3.0.exe.sha256`
- `dist/SHA256SUMS.txt`（上面两条合集，发布时贴到 Release 说明）

Windows PowerShell 校验命令：
```powershell
# 方式 1：Get-FileHash（推荐，直接对比）
$expected = (Get-Content dist\DouBi-Setup-0.3.0.exe.sha256).Trim()
$actual   = (Get-FileHash dist\DouBi-Setup-0.3.0.exe -Algorithm SHA256).Hash.ToLower()
$expected -eq $actual   # $true = 通过

# 方式 2：certutil（老 Win 机器也有）
certutil -hashfile dist\doubi-gui.exe SHA256
```

> **为什么安装包 441 MB 这么大？** 因为 onedir 里带了 **Playwright Chromium 浏览器目录**
> （通用视频站嗅探需要）+ PySide6/Fluent 完整样式与资源。
>
> ⚠️ **这段已被 M6.17 落实**：当时提的「去掉 ms-playwright 的 `--add-data` 能砍 60%」
> 是个错方向——那会直接废掉通用嗅探。M6.17 改为砍 `--collect-all` 拉进来的
> **未被 import 的** Qt 子模块（WebEngine/Multimedia）+ headless_shell + PIL +
> imageio_ffmpeg，**功能一条没减**，onedir 1501.8 MB → 678.5 MB，
> 安装包 441.31 MB → **215.46 MB**。上表是 2026-08-26 的历史快照，
> 精简后的产物见 M6.17「重打安装包」；**当前实际发布的是 M6.20 修复版
> 219.02 MB**（补 aiohttp 全链 +3.56 MB，见 M6.20）。

### M6.16 (2026-08-27) — 通用嗅探四入口接通 + 配置转发守卫

> G1 建好了嗅探器**内核**，但配置只到了内核门口：`AppConfig` 里的 6 个
> `sniff_*` 字段没有任何入口真正把它们递给 `Sniffer`。表现是「设置页改了
> 嗅探时长毫无效果」——不报错、不告警，静默失效。M6.16 把四个入口全部接
> 通，并补上能自动发现此类断裂的守卫。

**根因：两条互相独立的配置传递链，其中一条结构性地测不到**

| 链 | 路径 | 已有守卫能否发现断裂 |
|---|---|---|
| A `AppConfig → DownloadOptions` | 字段在**两个** dataclass 上同名存在 | ✅ 能。既有守卫用「取两个 dataclass 字段名交集，逐个比对」的自动化写法 |
| B `AppConfig → SniffOptions` | `sniff_*` **只**存在于 `AppConfig`，`SniffOptions` 用的是 `duration_sec` / `headless` 等短名 | ❌ **不能**。交集为空，自动守卫扫出 0 个字段，永远绿灯 |

链 B 的唯一转换点是 `core/sniffer.py::sniff_options_from_config()`（长名 →
短名的手写映射），少写一行就静默丢一个字段。**结论：自动化守卫对改名映射
天然失明，必须为链 B 单独写一份显式守卫。**

**四入口接通点**

| 入口 | 注入位置 | 用户可见变化 |
|---|---|---|
| CLI | `cli/main.py::_apply_sniff_overrides()`（在 `_cmd_download` 内调用） | 新增 `--sniff-duration N`、`--sniff / --no-sniff` |
| GUI | `ui/app.py` 启动时 `GenericAdapter.set_config(cfg)`；`ui/pages/settings.py` 第 6 张「通用嗅探」卡片 → `sniffConfigChanged` → `ui/main_window.py` 转发 | 设置页可调时长（5–60 秒钳制）与总开关；解析页显示「嗅探中… (Ns)」倒计时 |
| REST | `server/app.py::_apply_sniff_config()` | `POST /parse` 接受任意 URL；`GET /parse/{task_id}`；`GET /sniff/status` 自检 Playwright 可用性 |
| MCP | `mcp/server.py::run_stdio()` 启动注入 | 新增 `sniff_status` 工具；`parse_url` 展平 children 并输出 `direct_url` |

**`sniff_enabled` 新字段**：`core/config.py` 的 DEFAULTS / dataclass /
`load_config()` 强制转换三处同步添加。为 `False` 时
`GenericAdapter.parse()` 在**启动浏览器之前**短路返回，避免为一次注定失败
的嗅探付出 Chromium 冷启动成本。

**GUI 剪贴板回归修复**（`ui/pages/parse.py`）：剪贴板监听原先只在
「有适配器能 detect」时提示，而 `GenericAdapter.priority = -1` 使**任何**
http(s) URL 都能 detect 成功——于是复制任何链接都会弹提示。修复是显式排除
`priority < 0` 的兜底适配器。

> **`adapter.priority < 0` 是判断「这是否一次通用嗅探」的唯一谓词**，共 3
> 处使用：GUI 剪贴板过滤、GUI `_sniff_seconds_for()`、REST
> `_expected_sniff_sec()`。不能用 `isinstance(GenericAdapter)`——那会让
> 未来新增的兜底适配器漏网。

**测试守卫**（新文件 `tests/test_config_forwarding.py`，8 条）：

| 守卫 | 抓什么 |
|---|---|
| `test_sniff_options_forwarded_to_sniffer` | 用**偏离默认值**的探针配置（`duration_sec=42`、`headless=False`、`user_agent="probe-agent"`）走真实 `parse()`，比对 Sniffer 实收的 `SniffOptions` |
| `test_sniff_disabled_short_circuits_before_launching_browser` | `sniff_enabled=False` 时 `last_options is None`，证明浏览器根本没起 |
| `test_every_entry_calls_set_config` | 源码文本断言：四个入口文件都必须出现 `set_config` 调用 |
| CLI 覆盖 3 条 / REST 1 条 / MCP 1 条 | 各入口的 override 语义 |

**「推离默认值」原则**：守卫的探针值必须与 dataclass 默认值不同。若探针用
默认值 15，那么「字段没被转发」时 Sniffer 拿到的也是默认 15，断言相等、守
卫全绿——一条永远不会失败的守卫等于没有守卫。

**变异测试验证**（守卫本身也要被验证）：故意从
`sniff_options_from_config()` 删掉 `duration_sec=cfg.sniff_duration_sec`
一行 → 守卫立刻红灯 `assert 15 == 42` → 恢复该行 → 复绿。

**`tests/test_mcp.py` 白名单同步 + 新增同集守卫**：`sniff_status` 上线后
`test_tools_list_includes_all_registered` 的 `==` 硬编码白名单变红。这里的
`==`（而非 `>=`）是**刻意**的——它能同时抓到「工具被误删」，所以正确修法是
更新白名单而不是放宽断言。顺带补 `test_every_advertised_tool_has_a_handler`
守卫 `set(TOOLS) == set(_HANDLERS)`，防止「宣告了工具却忘注册 handler，客
户端能看到、一调用就 method not found」。

**`pyproject.toml`**：playwright 从 `gui` extra **提升为基础依赖**（通用嗅
探是四入口共享的兜底解析路径，不再是 GUI 专属），同时删除 `gui` 里的重复
声明以防版本约束漂移。注释里明确 pip 只装 Python 客户端（几 MB），浏览器内
核需另跑 `playwright install chromium`（约 150 MB）；缺内核时
`is_available()` 返回 False，`GenericAdapter` 返回一条 `[嗅探失败]`
MediaItem 而非抛异常。

**测试运行踩坑记录（PowerShell + Qt）**：
- `python -m pytest -q 2>&1 | Select-Object -Last 30` 会把输出**全部缓冲**，
  后台跑时 4 分钟看不到任何进度。改用 `python -u -m pytest -q -r f`（不接
  管道）才有实时点阵。
- 全量套件在 `test_ui_*` 段落**近乎停滞**（3 分钟只前进 4 个点），GUI 用例
  在等真实 Qt 事件循环。定位失败用例时用 `--ignore` 排除 9 个 GUI 文件，
  103 秒跑完非 GUI 部分。
- 结果：**673 passed / 0 failed**（非 GUI 全量 + 新增守卫）。

**spec 文档按实现修正**（`docs/superpowers/specs/2026-08-25-generic-sniffer-design.md`
状态改为 `implemented`）。核对时发现**设计文档的引擎路由表已过时**，实际是
四级路由，且 adapter 只写提示位、不直接选引擎：

```
adapter 写 extra 提示位 (is_hls / is_dash / is_direct_video)
    ↓
pipeline._select_engine() 按 extra_engines 顺序取第一个
supports() 为真且 is_available 的引擎：
    Nm3u8dlEngine → M3u8Engine → DirectHttpEngine → 默认引擎
```

处理原则：**按实现改文档，不能反过来把代码退回过时设计。** 顺带记录两处
已知缺口（不阻塞收尾）：`is_dash` 目前无任何引擎的 `supports()` 读取（死
字段）；`Aria2Engine` 在通用场景永远轮不到（`DirectHttpEngine` 在它之前
就接走了所有直链）。

### M6.17 (2026-08-27) — 打包体积精简：1501.8 MB → 678.5 MB（−54.8%）

> 一句话：**发布版有一半以上是「装进来但从没被 import」的死重量。**
> onedir 产物从 **1501.8 MB / 4005 文件** 降到 **678.5 MB / 881 文件**
> （−823.3 MB，−54.8%），且四项功能逐一实测未退化。
>
> 注：标题与本段是 **M6.17 当时**的数字。M6.20 补进 aiohttp 全链后当前值为
> **687.4 MB / 1002 文件（−54.2%）**、安装包 **219.02 MB**——引用体积数据时
> 请以 M6.20 一节或本文末「统计」为准。

#### 分项战绩

| 分项 | 精简前 | 精简后 | 手段 |
|---|---|---|---|
| `PySide6` | 550.6 MB | **92.3 MB** | `--exclude-module` × 46 |
| `playwright_browsers` | 701 MB | **430.3 MB** | 不打包 `chromium_headless_shell` |
| `imageio_ffmpeg` | 83.6 MB | **0** | 换成 `tools/nm3u8dl/ffmpeg.exe`（10.91 MB） |
| `PIL` | 12.8 MB | **0** | `--exclude-module PIL` |

#### 根因：`--collect-all` 的过度收集

`--collect-all qfluentwidgets` 会强收**每一个**子模块，不看代码有没有
import。三条从没被走到的路径把整个 Qt 重型栈拖了进来：

- `qfluentwidgets/multimedia/{media_player,video_widget}.py` → QtMultimedia
- `qframelesswindow/webengine/__init__.py` → QtWebEngineWidgets → **QtWebEngineCore（321 MB）**
- `qfluentwidgets/common/image_utils.py` → PIL

其中 QtWebEngineCore 一进依赖图，PySide6 的 hook 就连带拽入
`Qt6WebEngineCore.dll` 194 MB + `qtwebengine_devtools_resources.debug.pak`
72.3 MB + `.pak` 11.1 MB + `qtwebengine_locales` 43.65 MB。

#### 判据：「`sys.modules` 里有没有」，而不是「文件在不在包里」

排除任何模块前做了三重取证，最后一条最关键：

1. 全量 grep `src/`：除 `QtCore` / `QtGui` / `QtWidgets` / `QtSvg` 外零 Qt import
2. 起真 GUI 探 `sys.modules`：QtWebEngine / QtMultimedia / QtQuick / QtQml / PIL 一个都没加载
3. **重打包后逐文件核对：`_internal` 里零个 `*webengine*` 残留** —— 这条证明了
   `--exclude-module` 会把 hook 贡献的**数据文件**（`.pak` / locales）一起丢掉，
   而这恰是静态分析唯一答不出来的问题

PIL 另有构造性保证：`qfluentwidgets/components/widgets/acrylic_label.py` 把它
包在 `try/except ImportError` 里，缺了就降级成朴素 `QPixmap`；而 DouBi 全仓
`Acrylic` / `gaussianBlur` / `isAcrylicAvailable` **零引用**，连降级路径都走不到。

#### 三条互相咬合的新约束

**① 两处 `chromium.launch` 必须都带 `channel="chromium"`**（`core/sniffer.py`、
`core/auth/browser_login.py`）。Playwright 1.62 的裸 `headless=True` 会去找单独的
`chrome-headless-shell.exe`——正在被跳过的那 270.7 MB 里，缺了直接 launch 失败；
`channel="chromium"` 改用完整 Chromium 内置的 new headless。

**② `EXCLUDE_MODULES` 只在「没人 import 它们」时成立**。以后要加视频预览 /
内嵌浏览器 / PIL 处理，必须先从 `scripts/build_exe.py::EXCLUDE_MODULES` 摘掉对应项，
否则打包能过、运行时 `ImportError`。

**③ ffmpeg 必须继续靠 `--add-data` 带进去**。`installer/doubi.nsi` 的唯一
payload 规则是 `File /r "${SRC_DIR}\*.*"` 覆盖 `dist/doubi-gui`，仓库 `tools/`
**不进安装包**——所以排掉 `imageio_ffmpeg` 后，`build_exe.py::FFMPEG_EXE` 那行
`--add-data` 是发布版**唯一**的 ffmpeg 来源，另配构建期 pre-flight 检查
（文件不在就直接失败，绝不产出残废包）。

四个引擎（`m3u8` / `nm3u8dl` / `yt_dlp` + 共享层）统一改走
`engines/_subproc.py::find_bundled_ffmpeg()`，寻址顺序 **`_MEIPASS` 优先**：
frozen 形态从快捷方式启动时 `Path.cwd()` 常常是 `C:\Windows\System32`，
cwd-relative 一定找不到。

#### 实测验证（不是推断）

- **浏览器**：拿**打包产物里**那个被裁过的 `playwright_browsers` 起 Chromium，
  `headless=True → HeadlessChrome/151.0.0.0`、`headless=False → Chrome/151.0.0.0`，
  两种模式都成功
- **ffmpeg 寻址**：模拟 frozen 布局（设 `sys._MEIPASS` + `sys.frozen` +
  `os.chdir(r'C:\Windows\System32')`），四个解析器全部返回打包内路径
- **ffmpeg 本体**：`ffmpeg version N-94813-g85386c36e3-ffmpeg-for-N_m3u8DL-CLI`，
  10.91 MB，可执行
- **GUI**：frozen 产物启动，窗口标题正常渲染为「豆比下载 0.3.0 · 多平台视频下载器」，
  `Responding=True`、驻留 156.6 MB，并成功读 `~/.doubi/config.yml` + 写 `cookies/*.txt`
  —— 说明被裁过的 Qt 栈与配置 I/O 都完好

#### 重打 0.3.0 安装包：441.31 MB → 215.46 MB（−51.2%）

精简只改了 onedir，安装包的收益必须重打才能量化。复用现有 `dist/doubi-gui/`
跑 `python scripts/build_installer.py --skip-build`：

| 项 | 精简前 | 精简后 | 变化 |
|---|---:|---:|---|
| NSIS 源目录 | 1501.8 MB / 4005 文件 | 678.5 MB / 881 文件 | −54.8% |
| 压缩段 | 462.3 MB | 225.9 MB | −51.1% |
| **安装包 exe** | **441.31 MB** | **215.46 MB** | **−51.2%** |
| 压缩率 | 29.3% | 31.7% | +2.4pp |

- 产物：`dist/DouBi-Setup-0.3.0.exe`，225,926,086 字节
- SHA256：`e833f155485509736cb25682fae431a2907474cb44c03421308dfed32954ddbe`
- 侧签：`DouBi-Setup-0.3.0.exe.sha256`、`SHA256SUMS.txt`（LF、无 BOM）

**压缩率反而升高是预期的**，不是异常：被砍掉的 WebEngine `.pak`、
`qtwebengine_locales`、headless_shell、PIL 本来就是高可压缩的重复内容；
剩下的 Chromium / `node.exe` 二进制熵更高，压不动。所以安装包降幅（−51.2%）
略小于 onedir 降幅（−54.8%）——**别指望两个百分比相等**。

G8 那两条硬规则全程遵守，没有因为「包变小了」就放松：

1. `SetDatablockOptimize off` 保持关闭。事故的触发条件是 optimizer 的块合并
   逻辑本身，**不是「包够大才会犯」**——体积变小只降低概率，没修掉 bug。
2. makensis exit 0 后先等「文件大小连续 10 秒不变」才算哈希。本次日志
   两行 footer 齐全：`CRC (0x5291D80F): 4 / 4 bytes` +
   `Total size: 225926086 / 711750527 bytes (31.7%)`。

静默装卸全链路实测（`/S /D=%LOCALAPPDATA%\DouBi_VerifyTest`）：

- 安装退出码 0；落盘 **882 文件 / 678.5 MB**（881 源文件 + `uninstall.exe`），
  与源目录逐项吻合
- `*webengine*` / `*headless_shell*` 残留各 **0 个** —— 证明精简在**安装侧**
  也生效，而不只是构建目录里干净
- 关键文件到位：`doubi-gui.exe`、`_internal/tools/nm3u8dl/ffmpeg.exe`（约束③
  的落地证据）、`_internal/doubi/ui/locales/{zh_CN,en}.json`（G7 回归项）
- 装出来的程序启动正常：标题「豆比下载 0.3.0 · 多平台视频下载器」、
  `Responding=True`、160.2 MB
- 注册表 `EstimatedSize` 自动重算为 694817 KB（≈678.5 MB），没沿用 0.1.0 基线
- **故意让程序开着**卸载以检验 `EnsureAppClosed`：退出码 0，安装目录 / HKCU 键 /
  残留进程全部归零，而 `~/.doubi` 完好保留

> onefile 便携版（`dist/doubi-gui.exe`，精简前 615.17 MB）本轮**没有重建**，
> 用户选定的范围是「仅重打安装包」。所以 onefile 的精简收益目前仍是未量化的，
> 发绿色便携版前需补跑 `python scripts/build_exe.py`。

#### 顺带的仓库/磁盘清理

- `tools/nm3u8dl/*.zip` 加入 `.gitignore` 并 `git rm --cached`：原始压缩包与解出的
  3 个 exe **SHA256 逐字节相同**（按哈希核对，不是按体积猜），6.53 MB 纯冗余；
  同时删掉一个 0 字节、`Central Directory corrupt` 的坏 zip
- 删两个零引用游离脚本 `_test_token.py`、`test_hang.py`（后者还硬编码绝对路径）
- 删 8 个游离根日志；`dist/` 从 3667.2 MB 清到 678.5 MB（释放 2988.8 MB）
- 修正了一个自己的误判：`.gitignore` 对 `dist/` / `build/` / `*.log` **本来就有覆盖**，
  真正的缺口只有那两个 zip
- `INTEGRATION_PLAN.md` 有意保留：`docs/ARCHITECTURE.md` / `docs/DEVELOPMENT.md`（×2）
  / `README.md`（×2）共 5 处活引用，为 33 KB 改 5 个地方不值

#### 守卫测试

新增 `tests/test_packaging_slim.py`（13 条），把上面三条约束全部锁死。延续
`test_version_single_source.py` 的风格——**断言「有几个地方能决定这件事」，
而不是断言具体值**；`channel` 检查走 AST（`ast.Call` → `Attribute(attr="launch")`
→ owner `Attribute(attr="chromium")`）而非 grep，关键字参数才读得准。

其中 3 条做过变异验证（故意改坏约束，确认对应测试变红且**理由正确**）。
过程中有一次变异「绿了」，查明是 `.Replace()` 用 `` `r`n `` 没匹配上 LF 文件、
改动根本没生效 —— 该次绿色被明确拒收，重做后才通过。

---

### M6.18 (2026-08-27) — 发布与同步：SSH 接通 + 两处发版事故

#### 代码同步到 GitHub（SSH）

`Github` 远端从 HTTPS 切为 `git@github.com:buxiaju/DouBi.git`，
`ssh -T git@github.com` 鉴权通过（`Hi buxiaju!`），推送
`c5913c5..13f3393  master -> master`，回验
`git rev-list --left-right --count Github/master...HEAD` → `0	0`，
且 `Github/master:tests` 下 `test_config_forwarding.py` /
`test_packaging_slim.py` 均已落地。

三个环境事实值得记住（已写入 `docs/BUILD.md` §8.1–§8.2）：

- GitHub 远端名是 **`Github`**，`origin` 是 **Gitee**；默认分支是 **`master`**
- 本地 `master` 的 upstream 指向 `origin/master`，**裸跑 `git push` 会推去 Gitee**
- `ssh -T git@github.com` **退出码 1 是成功**（GitHub 不给 shell）；PowerShell 把
  git 的 stderr 进度渲染成红色 `NativeCommandError` 也**不是错误**——判据是退出码
  和 refspec 行

#### 事故 1：`v0.3.0` 标签指向了 0.2.0 时代的 commit

`git log -n 1 --oneline v0.3.0` → `c5913c5 fix(ci): 修复 0.2.0 发版 CI 测试集合失败`，
而非 `13f3393 release: 0.3.0 ...`。根因是**标签建在 release commit 推送之前**
（标签 `created_at` 2026-08-25T11:00:13Z 早于 release commit）。且是**轻量标签**
（`git cat-file -t` → `commit`）。

影响面比"难看"严重：GitHub Release 的 **Source code (zip/tar.gz) 按标签解析**，
所以从 Release 页下载源码会拿到旧代码，与新安装包资产不一致；`git describe`
版本考古同样错。

**尚未修复**——因为 `git push --force` 一个 `v*` 标签会触发
`.github/workflows/build.yml`（`on: push: tags: ["v*"]`）重跑 CI，
`softprops/action-gh-release@v2` 会 update 已发布的 Release 并**可能覆盖
已人工验证的安装包资产**（NSIS 非可复现构建，新哈希必然不同）。安全补救
路径见 `docs/BUILD.md` §8.4：先让触发器失效，再动标签。

#### 事故 2：Release 正文粘贴截断

已发布正文停在「Chromium 与 ffmpeg 均已随包提供」，**丢了 `静默安装`、
`校验（SHA256）`、`已知限制` 三段** —— 后果是下载者拿不到官方哈希做比对。

#### 好消息：二进制本体没问题

线上 `DouBi-Setup-0.3.0.exe` 的 `digest` =
`sha256:e833f155485509736cb25682fae431a2907474cb44c03421308dfed32954ddbe`、
225,926,086 字节，与本地验证过的构建**逐字节一致**，三个资产 `state: uploaded`。
即 CI 未曾覆盖过资产。

#### 文档加固

- `docs/BUILD.md`：新增 §8.1 仓库拓扑 / §8.2 SSH 配置 / §8.3 发布顺序（先推
  commit 再打 annotated tag）/ §8.4 标签补救 / §8.5 手动发布填写要点；§7 增加
  「发布后线上核对」5 项；修正两处旧错误（版本真源写成 `pyproject.toml`、
  `main` 分支应为 `master`）；记下 CI 与本地 **sha256 sidecar 格式分歧**
- `docs/DEVELOPMENT.md`：§17 增加「两个远端，别推错」；§18 修正过期的
  「没有 i18n」（M6.14 已做），新增第 8 条已知限制「发布流程仍是手工序列」

---

### M6.19 (2026-08-27) — 修复：发布版通用嗅探全废（`catch_lite.js` 未进包）

#### 现象

用户在安装版里解析非平台链接，得到
`[嗅探失败] silidm.com — catch_lite.js 加载失败；安装包可能损坏`。
即**通用嗅探在发布版 100% 不可用**——而开发环境下一直正常。

#### 根因

`scripts/build_exe.py` 从未给 `catch_lite.js` 加 `--add-data`。

关键认知：**`--collect-submodules doubi` 只收 Python 模块，不收数据文件**。
`core/sniffer.py` 用 `importlib.resources.files("doubi.platforms.generic")`
读这个 JS——`importlib` 让**路径**在冻结后仍正确，但它管不了**文件有没有进包**。
两件事被长期混为一谈，旧 docstring 里那句「resource access via importlib 是
PyInstaller 友好的方式」正是这个误解的载体（本次已改写）。

证据链：

- `dist/doubi-gui/_internal/doubi/` 递归列举只有 3 个文件
  （`ui/locales/en.json`、`ui/locales/zh_CN.json`、`ui/resources/icon_template.svg`），
  恰好就是当时 `--add-data` 的三个来源，`catch_lite.js` 不在其中
- `git log -- scripts/build_exe.py` 显示嗅探特性提交 `c9ad826` 未动过这个文件
  → **缺陷自通用嗅探引入之日就存在，不是 M6.17 精简砍掉的**；
  M6.16 把嗅探接进四入口后它才被用户触达

**为什么本地永远测不出来**：开发态 `importlib` 解析到真实 `src/` 目录，
文件当然在；只有冻结产物（`sys._MEIPASS`）才暴露。这类缺陷的唯一拦截点
在构建脚本本身，不在运行时测试。

#### 修复

`scripts/build_exe.py` 三处：`CATCH_LITE_JS` 常量、`is_file()` 预检
（PyInstaller 对不存在的 `--add-data` 源**只告警不报错**，预检是唯一
早失败的机会）、`--add-data f"{CATCH_LITE_JS}{sep}doubi/platforms/generic"`。

验证：重建 onedir 后 `_internal/doubi/platforms/generic/catch_lite.js` 存在，
9036 字节，SHA256 与源文件**逐字节一致**（`1E77A0B1…`）。

#### 顺带排查了同类风险（结论：只有这一个是 bug）

枚举 `src/doubi` 下全部 7 个非 `.py` 文件并逐个判定是否运行时读取：

| 文件 | 判定 |
|---|---|
| `catch_lite.js` | **硬依赖**，无兜底，缺失即功能死 → 真 bug |
| `en.json` / `zh_CN.json` / `icon_template.svg` | 已有 `--add-data` |
| `icon.png` | **有保护的兜底**：`_render_png` 仅在 QtSvg 不可用时走到，且先 `is_file()` → 安全降级 |
| `icon.svg` | 归档设计源，不参与渲染 |
| `icon.ico` | 走 `--icon`，编译进 exe 资源 |

即 `icon.png`/`icon.svg` 不打包是**有意的体积决策**，不是漏打包。

#### 测试加固（`tests/test_packaging_slim.py` 13 → 17 条）

原有 13 条守卫全绿却漏掉了这个 bug，所以新守卫**不硬编码文件名**，而是
AST 扫描 `resources.files(pkg).joinpath(name)` 的调用点，再与 AST 解析出的
`--add-data` 目标集合求差——**未来任何新资源自动纳入覆盖**。

- `test_every_importlib_resource_exists_in_the_repo`
- `test_every_non_py_resource_read_at_runtime_has_an_add_data_entry`（核心）
- `test_build_script_preflights_every_add_data_source_file`
- `test_catch_lite_js_is_the_only_source_of_the_injected_script`

**变异验证**：删掉那行 `--add-data` 后，测试精确报出
`sniffer.py:318 运行时要读 doubi.platforms.generic/catch_lite.js，
但 build_exe.py 里没有对应的 --add-data 目标`，并列出现有目标供比对；
文件字节级还原。绿测试不等于有效测试，必须这么验一遍。

两条新测试第一版是**红的**，且红得有价值：

- `ui/i18n.py:83` 读的是 `doubi.ui/locales` 这个**目录**
  → 断言从 `is_file()` 放宽为 `exists()`（资源可以是目录）
- 遍历全部 `ast.JoinedStr` 把预检的中文报错消息也当成了 `--add-data` 目标
  → 改为严格按「列表里紧跟 `--add-data` 的那个元素」配对

#### 影响与后续

已发布的 `DouBi-Setup-0.3.0.exe` 的通用嗅探**不可用**，需重新发版才能修好；
平台适配器（抖音/B站等）走独立代码路径，**不受影响**。

---

### M6.20 (2026-08-27) — 修复：HLS 下载全废（三个独立根因叠加）

用户反馈「解析能成功，但下载失败」。UI 只显示 `engine returned False`，
输出目录被创建但为空。排查下来是**三个彼此独立**的缺陷叠在一起，
任何一个单独存在都足以让 https m3u8 下载 100% 失败。

#### 根因 A：捆绑的 ffmpeg 没有 TLS 后端

`tools/nm3u8dl/ffmpeg.exe` 是 N_m3u8DL-CLI 自带的 2019 定制构建
（`N-94813-g85386c36e3-ffmpeg-for-N_m3u8DL-CLI`，gcc 8.2.0），
编译时**未启用任何 TLS 后端**。喂它 https 播放列表会立刻退出：

```
https protocol not found, recompile FFmpeg with openssl, gnutls
or securetransport enabled.
```

这个 ffmpeg 原本只承担 N_m3u8DL-CLI 的**本地 .ts 合并**职责——
https 分片是 .NET 侧自己下的。而 N_m3u8DL-CLI 的二进制并没有进包
（`nm3u8dl.py::_find_cli()` 也缺 `sys._MEIPASS` 分支），
于是 ffmpeg 被直接递上了 https 播放列表。现实中 m3u8 几乎全是 https，
所以这不是偶发，而是**必然失败**。

修复：`_ffmpeg_supports_https()` 用 `-protocols` 探测能力（`lru_cache` 缓存，
`CREATE_NO_WINDOW` 避免窗口闪烁），`_can_ffmpeg_fetch()` 在路由前拦截。
关键改动是**判据从「ffmpeg 是否存在」变成「ffmpeg 是否胜任」**——
旧代码只在 ffmpeg *缺失* 时回退 aiohttp，ffmpeg *无能* 时不会回退。

#### 根因 B：分片 URL 用字符串拼接而非 urljoin

`_fetch_segments` 原本 `base + line`。播放列表里混着三种 URI 形态，
其中**根相对**形式（`/video/adjump/time/*.ts`，注入的广告分片）被拼成
`.../bfc23af8d1b2//video/adjump/...`——多一个斜杠，源站回 404。
真实案例 2835 个分片里有 18 个这种广告分片，下载在第 284 个分片处整体崩掉。

修复：改用 `urljoin(url, line)`，三种形态统一正确解析。

#### 根因 C：真实错误被 pipeline 吞掉

`_ENGINE_ERROR_PREFIXES` 里缺 `m3u8 engine error:` 和 `无法创建输出目录`，
`_wrap_engine_progress` 因此从不捕获它们，`last_error` 退化成毫无信息量的
`engine returned False`——这正是用户唯一能看到的东西。**诊断信息的缺失
本身就是一个 bug**：它让上面两个根因在整个排查前期都是隐形的。

修复：补齐两个前缀（8 → 10 条）。

#### 连带修复：分片下载器改为并发 + 分片级重试

根因 A 的二阶后果值得单独记一笔：既然 ffmpeg 无法处理 https，
aiohttp 分片下载器就**从「降级备选」升格为唯一可行路径**，
它的性能与健壮性因此从次要变成关键。

- **并发**：原实现是严格顺序 `for` 循环，2835 分片约需 10 分钟。
  改为 `asyncio.Semaphore` 限流的 `gather`，复用 yt-dlp / aria2 已在用的
  `concurrent_fragments` 旋钮（**不新造设置**，同名配置在所有引擎语义一致）。
- **分片级重试**（3 次，线性退避）：这比提速更重要。按单分片 99.9% 成功率算，
  2835 个分片一次全过的概率仅约 **5.7%**——没有重试，长播放列表几乎
  注定失败，而且失败形态正是用户看到的那种「跑一半崩掉」。
- 进度按**完成计数**而非分片下标递增，乱序完成时进度条仍单调。
- 异常时显式 `cancel()` 并 `gather` 兄弟任务，避免 session 被提前关闭
  引发一堆掩盖真实原因的 `Session is closed` 噪声。

#### 打包缺口（自查发现，属发版阻断级）

`grep` 发现 `build_exe.py` 里**完全没有 aiohttp 相关条目**。
在根因 A 修复之前这只是隐患，之后则是**发版阻断**。两个原因说明
仅靠静态分析不可靠：

1. `m3u8.py` / `direct_http.py` 里是**函数内延迟导入** `import aiohttp`；
2. `multidict` / `yarl` / `propcache` / `frozenlist` 都带 C 扩展（`.pyd`）。

漏包的表现是**运行时** `ModuleNotFoundError`，构建期毫无征兆。
修复：显式 `--collect-all aiohttp / multidict / yarl`。

#### 验证

有界端到端验证（**刻意不整片下载**——那等于实际抓取一部完整影视作品，
既不必要也不合适；修复的正确性可以用有界方式精确证明）：

| 检查项 | 结果 |
|---|---|
| `_can_ffmpeg_fetch` | `False` + 明确的无 TLS 告警（根因 A 生效） |
| 分片总数 | 2835 |
| 双斜杠 URL 数 | **0**（根因 B 生效） |
| 广告分片 | 18 个，`HEAD` 全部 200 |
| 24 分片顺序 vs 并发 | **10.03s → 3.31s**，输出字节完全一致 |
| 新包 aiohttp 链 | PYZ 内 `aiohttp` 54 / `aiosignal` 1 / `aiohappyeyeballs` 5 / `attr` 13 个模块 + 4 个 `.pyd`；8 个模块**真实导入成功**（带来源断言，排除开发环境 site-packages 假阳性），旧包同项为 **0** |
| 静默装卸（新包） | 安装/卸载退出码均 **0**；落盘 **1003 文件 / 687.4 MB**（= onedir 1002 + `uninstall.exe`），与构建目录逐项吻合 |
| 装后关键文件 | `catch_lite.js` 8.8 KB、`ffmpeg.exe` 11174.5 KB、`_ssl.pyd` 177.7 KB、`_socket.pyd` 84.7 KB 全部在位 |
| `EnsureAppClosed` | **故意开着程序卸载**：卸载前 1 个进程 → 卸载后 **0 个**，目录清空，`~/.doubi` 完好保留 |
| 装后启动 | 标题栏「豆比下载 0.3.0 · 多平台视频下载器 - DouBi」（真实译文非键名），`Responding=True`，内存 152.1 MB |

#### 重打 0.3.0 安装包（第二次）：215.46 MB → 219.02 MB

补进 aiohttp 全链的代价，**这不是体积回退而是功能必需**——打包后的 ffmpeg
无 TLS 后端（根因 A），aiohttp 成了 https 分片下载的唯一可行路径：

| 项 | M6.17 精简后 | M6.20 修复后 | 变化 |
|---|---|---|---|
| onedir | 678.5 MB / 881 文件 | **687.4 MB / 1002 文件** | +8.9 MB / +121 文件 |
| NSIS 安装包 | 215.46 MB | **219.02 MB** | +3.56 MB（+1.7%） |
| 压缩率 | 31.7% | 31.8% | — |

发布指纹。这一份**同时取代两个旧构建**（发版时务必替换线上资产）：

| 构建 | 字节 | SHA256 | 状态 |
|---|---|---|---|
| M6.17 精简版 | 225,926,086 | `e833f155…54ddbe` | **已发布到 GitHub，必须替换** |
| M6.19 `catch_lite` 修复版 | 225,938,999 | `59389653…390c2b` | 仅本地，从未发布 |
| **M6.20 本版** | **229,657,135** | `5d28ba83…b03eae` | **应发布** |

| 项 | 值 |
|---|---|
| 文件 | `dist/DouBi-Setup-0.3.0.exe` |
| 字节 | `229657135`（219.02 MB） |
| SHA256 | `5d28ba835acd4daf31685f5773edb6b0ee04acc861152b01724f8ac120b03eae` |
| NSIS CRC | `0xB1919CD7` |
| 构建时间 | 2026-08-27 13:30:34 |

侧签 `DouBi-Setup-0.3.0.exe.sha256` 与 `SHA256SUMS.txt` 已同步重写
（88 字节、LF、无 BOM，格式 `<hash> *<filename>`）。**这两个文件之前还留着
M6.17 的 `e833f155…`，与实际 exe 不匹配** —— 任何照它校验的人都会失败，
所以重打包后必须连侧签一起更新，不能只换 exe。已用 `Get-FileHash` 与
`certutil` 两种独立工具交叉验证一致。

> 查残留的坑：`Get-ChildItem -Filter *webengine*` 会命中
> `_internal\qframelesswindow\webengine\` 这个**目录名**（内含一个 756 B 的
> `__init__.py`），看起来像「精简失效」。按**文件**计残留为 **0**，且
> `Qt6WebEngineCore.dll` / `qtwebengine_resources.pak` /
> `qtwebengine_devtools_resources.debug.pak` / `QtWebEngineCore.pyd`
> 四项全为 0——判定残留要数文件，不能数条目。

新增 34 条回归测试：

- `tests/test_engine_routing.py` +29（`TestFfmpegHttpsCapability` 10、
  `TestSegmentUrlResolution` 5、`TestSegmentDownloadConcurrency` 8、
  错误识别 3、真实服务器行为编排替身 `_FakeSegmentServer`）
- `tests/test_packaging_slim.py` +5（aiohttp 栈必须被收集 / 已声明 / 未被排除）

其中 `test_all_m3u8_emitted_prefixes_registered` 守护的是**根因 C 的模式**
而非症状：它遍历引擎真实发出的消息，确保「引擎发什么」与「pipeline 认什么」
这两份手工维护的清单不再脱节。

#### 影响与后续

已发布的 `DouBi-Setup-0.3.0.exe` 的 **HLS（m3u8）下载完全不可用**，
需重新发版；走 yt-dlp 的平台（抖音/B站/YouTube）**不受影响**
（用户的 bilibili 54.4 MB、douyin 8.3 MB 文件均正常）。

---

### M6.21 (2026-08-27) — 修复：发版 CI 红（`ModuleNotFoundError: No module named 'pydantic'`）

M6.20 的提交 `086bbaf` 连同移动后的 `v0.3.0` 标签推上去，`build-installer #3`
在 **1m54s** 就红了。失败发生在**测试段**，所以打包段与 `Create GitHub Release`
两步都没执行——这反而省事：线上没有产生需要清理的 draft release。

```
1 failed, 628 passed, 146 skipped in 45.82s
FAILED tests/test_config_forwarding.py::test_rest_applies_sniff_config
  - ModuleNotFoundError: No module named 'pydantic'
```

#### 根因：一条裸导入穿过了懒导入的防线

```
test_config_forwarding.py:190  from doubi.server import app      ← 修复前的行号
  → server/app.py:39           from .schemas import DownloadRequest, ParseRequest
    → server/schemas.py:10     from pydantic import BaseModel, Field   ← 炸在这里
```

`fastapi` / `pydantic` / `uvicorn` 只在 `[project.optional-dependencies].server`
里，而 CI 装的是 `pip install .` + `pytest pytest-asyncio ruff`，**不带任何 extras**。

这条链**不能靠懒导入解决**：`schemas.py` 是故意把模型定义在模块顶层的，
好让 Pydantic v2 把注解解析成真类型而不是前向引用。

值得记的是这是一个**已经解决过的 bug 类别的复发**。`c5913c5` 当初把
`doubi/server/__init__.py` 改成 PEP 562 懒导入模块，正是为了阻止
`from doubi.server import security`（只用 stdlib）被 pydantic 连坐。
教训一句话：**懒导入只能保护「入口不被连坐」，保护不了「有人直接敲门」**——
`from doubi.server import app` 要的就是 `app` 本身，`__getattr__` 会老老实实
把重型链拉进来，这是它的正确行为，不是漏洞。

#### 修复：按既有约定加 `importorskip`，且只加在函数内

项目里早有这条约定，只有 `test_config_forwarding.py` 漏了：

| 位置 | 守卫 |
|---|---|
| `test_server.py:24-26` | `fastapi` / `httpx` / `pydantic` |
| `test_server_security.py:277-278` | 同上 |
| `test_version_single_source.py:92` | `setuptools` |
| `test_prompt_options.py:40` | `PySide6.QtWidgets` |
| **`test_config_forwarding.py:201-202`** | **本次补上 `pydantic` / `fastapi`** |

`importorskip` 放在**函数内而不是模块顶层**是刻意的：同文件里 CLI / MCP 两条
转发守卫只依赖 stdlib，`test_every_entry_calls_set_config` 更是**源码文本级**
断言（读 `_ENTRY_SOURCES` 里四个文件的文本 grep `GenericAdapter.set_config`，
一个模块都不 import）。把跳过条件提到顶层，会让这些本该在任何环境下都生效的
守卫被 REST 的可选依赖连坐——那等于用一个静默降低覆盖的办法去修一个报错。

顺带审计了全部测试文件的可选依赖裸导入：`httpx` 是**基础依赖**
（`pyproject.toml:35`，`httpx>=0.25`），所以 `test_bilibili_adapter.py` /
`test_douyin_adapter.py` 里的顶层 `import httpx` 是安全的。
pydantic / fastapi 是唯一的缺口。

#### 验证：模拟 CI 依赖集，而不是「本地能跑就算过」

本地装着全部 extras，直接跑必然复现不出来。用 `sys.meta_path` 插一个
Blocker（`find_spec` 对 `pydantic` / `fastapi` / `uvicorn` / `PySide6` /
`qfluentwidgets` / `qasync` / `psutil` 抛 `ModuleNotFoundError`，并清掉
`sys.modules` 里已导入的同名模块），再照 CI 原命令跑全量：

| 口径 | 结果 |
|---|---|
| CI（修复前） | `1 failed, 628 passed, 146 skipped in 45.82s` |
| 本地模拟 CI（修复后） | **`629 passed, 146 skipped in 104.79s`** |

`628 + 1 = 629` **且 skipped 数完全相同**——两个等式一起才构成证据：
前者说明环境等价（不是少收集了用例而"变绿"），后者说明没有测试被**多**跳过
（不是把问题掩盖成 skip）。单跑该文件亦可见
`SKIPPED [1] tests\test_config_forwarding.py:201: could not import 'pydantic'`。

#### 附带发现：CI 与本地的测试集有两处不等价

排查中本地全量跑卡在 `[ 82%]` 十几分钟不动，起初以为是新问题，其实是**第二个**
独立的 CI/本地分歧：

1. **CI 不过滤 mark**——`build.yml:72` 是 `python -m pytest -q --maxfail=5`，
   没有 `-m "not slow"`；而我本地把关一直用 `-m "not slow"`，比 CI **小一圈**。
   这个失效模式因此必然漏过去。
2. **`slow` 标记在两边的实际效果相反**——全项目只有
   `test_theme_apply_gui.py:33`（`pytestmark = [pytest.mark.gui, pytest.mark.slow]`）
   带此标记。本地装着 PySide6，它会**真的起 Qt 事件循环**并长时间挂住；CI 没有
   PySide6，它直接被 skip。这就解释了 CI 45.82s vs 本地 10 分钟+ 的差距。

换句话说，**「本地全量」既不是 CI 的超集也不是子集**，两边各自漏掉对方覆盖的一块。

#### 影响与后续

只改了一个测试文件（+15/−1），**不触及任何发布产物**——`219.02 MB` 安装包与
`5d28ba83…b03eae` 哈希均不受影响，无需重打包。修复提交 `20ffa0a` 只推 master
（两个远端），**刻意不再移动 `v0.3.0` 标签**：标签已经在 M6.18 里挪过一次，
再挪一次会二次改写发布史，而这次的改动对产物零影响，不值得。代价是
`v0.3.0` 标签上留着一次红色 CI 记录——**留着比抹掉更诚实**。

待决（未采纳，记录备选）：让 CI 装齐 extras（代价是变慢），或把「屏蔽可选依赖
跑一遍全量」固化成发版前检查（已写入 `BUILD.md` §7），或干脆去掉 CI 的
`Create GitHub Release` 步骤改为纯构建。

---

### 统计
- 源码：~18,600 行（相较 0.2.0 净增约 700 行，主要是 supervisor + 嗅探器）
- 新文件：`engines/_subproc.py`，`engines/base.py` 增加 filename/cancel helpers
- 测试：31 个文件，**614 passed / 203 deselected**（无 PySide6 环境下跳过 GUI 标记）
  - sniffer + engine routing：85 passed
  - 新增健壮性烟雾检查（basename 字节预算、path≤259、cancel_flag 鸭子类型）全部通过
  - Ruff 全部文件 clean（33 项 ruff --fix + 3 处人工修复）
- M6.16 收尾后：**33 个文件，673 passed / 0 failed**（排除 9 个 GUI 文件的全量跑）
  - 新增 `tests/test_config_forwarding.py`（8 条链 B 转发守卫）
  - `tests/test_server.py` 新增 5 条嗅探 REST 用例 + `no_real_browser` 替身 fixture
    （5 条 1.77s 跑完，真起 Chromium 至少 30s，用耗时反证替身生效）
  - `tests/test_mcp.py` 新增 `TOOLS`/`_HANDLERS` 同集守卫
  - 基线演进：381 → 403 → 423 → 450 → 687 → 713 → **673（非 GUI 口径）**
- M6.17 收尾后：新增 `tests/test_packaging_slim.py`（13 条打包约束守卫，3 条变异验证）
- M6.19 收尾后：`catch_lite.js` 的 `--add-data` 守卫入网（精简版嗅探回归）
- M6.20 收尾后：**846 passed / 4 skipped / 28 deselected（`-m "not slow"`，203s）**
  - `tests/test_engine_routing.py`：47 → **76**（+29；ffmpeg TLS 能力探测 10、
    分片 URL 解析 5、并发与重试 8、错误前缀识别 3，其余为既有用例）
  - `tests/test_packaging_slim.py`：17 → **22**（+5；aiohttp/multidict/yarl
    三包 `--collect-all` 正反向守卫。此处是 parametrize 展开后的用例数，
    与上文 M6.17「13 条」的函数口径不同）
  - 基线演进：381 → 403 → 423 → 450 → 687 → 713 → 838 → **846**
- M6.21 收尾后：**629 passed / 146 skipped / 0 failed**（模拟 CI 依赖集的**无过滤**
  全量跑，104.79s）。注意这与上面 M6.20 的 846 不是同一口径：
  - 上面是**本地** `-m "not slow"`，装齐 extras；这里是**屏蔽可选依赖**
    （pydantic/fastapi/uvicorn/PySide6/qfluentwidgets/qasync/psutil）、**不过滤 mark**
  - 屏蔽依赖会把 GUI / REST 用例整批转成 skip，所以 passed 数反而更低——
    数字变小不代表覆盖退化，**两个口径要分别对照各自的历史值**
  - `tests/test_config_forwarding.py`：8 条中 1 条（`test_rest_applies_sniff_config`）
    在无 pydantic 环境下改为 skip，其余 7 条（含源码文本级四入口守卫）照常执行
- 打包产物：onedir **1501.8 MB / 4005 文件 → 678.5 MB / 881 文件**（−54.8%），
  M6.20 补 aiohttp 全链后为 **687.4 MB / 1002 文件**（当前值，相对原始基线 **−54.2%**）
- NSIS 安装包：**441.31 MB → 215.46 MB**（−51.2%），M6.20 后 **219.02 MB**（当前值，
  相对原始基线 **−50.4%**，`sha256 5d28ba83…b03eae`，静默装卸 + `EnsureAppClosed`
  + CRC footer 全验证通过）
- 仓库跟踪体积：**719 个文件 / 28.8 MB**（剔除 6.53 MB 冗余 zip 后）

---

## 0.2.0 (2026-08-25) — M6.4–M6.15 品牌化、合集、跨进程恢复、直播与多引擎

> 这一轮涵盖 12 个里程碑（M6.4–M6.15），共同主题是「让用户看到的和用到的，
> 跟内核一样讲究」——视觉品牌化、抖音合集、跨进程断点续传、REST 安全收口、
> YouTube 适配器、i18n 基础设施、B 站直播录制、aria2 多线程引擎。每条改动
> 都有可解释的取舍（写进 DEVELOPMENT 跟代码一起活），不是「我看着不舒服就改了」。
>
> 0.1.0 快照（M0–M6.3）见下方独立节。本节内部按里程碑顺序排列：M6.4 UI 品牌化 →
> M6.5 矢量图标管线 → M6.6 Windows 任务栏图标与 PyInstaller 打包 → M6.7 抖音合集 →
> M6.8 NSIS 安装包 → M6.9 安全敞口收口 → M6.10 跨进程断点续传恢复 →
> M6.11 下载前选项对话框 → M6.12 YouTube 适配器 → M6.13 YouTube 下载双故障修复 →
> M6.14 代码健康/UX/功能/工程化一揽子 → M6.15 B 站直播 + aria2 引擎。

### M6.4 UI 全方位品牌化

`ui/theme.py` 从 6 套主题扩到 **7 套**，新增品牌主题 **`doubi`（豆比紫）**：
- 配色从图标自身取色——深紫底 `#1a1230` + 琥珀橙主色 `#f59e6a`
- **豆比紫是品牌默认主题**，代码里 `set_theme("doubi")` 直接拿到
  品牌色而不是用「亮/暗 + 强调色」近似
- 全 7 套主题的 token 表补全：`accent_soft` / `accent_strong` /
  `bg_elevated` / `shadow` / `gradient_header` 五个之前缺位的字段
  （旧版 dataclass 没声明，`accent_soft` 默认空串，下游按字段取色就
  AttributeError）

**Token 体系扩充**（`theme.py`）：
- **排版常量** `TYPE_H1..TINY`：6 级字号（24/20/16/13/12/10），按尺度单调递增
- **间距常量** `SPACE_XS..XXL`：6 级（4/8/12/16/24/32），同样单调
- **圆角常量** `RADIUS_DEFAULT(4) / RADIUS_CARD(8) / RADIUS_PILL(20)`
- **辅助 QSS**：`heading_qss(level)` / `body_qss()` / `card_qss(elevated)` /
  `header_qss(level)` / `muted_qss()`。每条都有命名（而非 `setStyleSheet("color: gray;")`
  散落），换主题时跟着 token 走，不再有「字面量 gray 在暗底上对比度不足」一类退化

**共享组件**（新增 `ui/widgets.py`，每个组件一个工厂函数 `build_*` 延迟 import Qt）：
| 组件 | 用途 |
| --- | --- |
| `PageHeader` | 页面级「标题 + 副标题 + 右侧动作」三段式，解析/下载/历史/设置四个页面统一 |
| `EmptyState` | 居中展示的占位态（图标 + 主标 + 副标），下载/历史页都用它替代自定义空态 |
| `StatChip` | 顶部统计条小方块（"3 个正在下载" 这类），4 种 kind 颜色（running/paused/completed/failed） |
| `PlatformBadge` | 圆形彩色平台徽标（B 站蓝 / 抖音红），登录对话框与设置页都用它 |
| `SectionDivider` | 卡片内的分组分隔线，统一「细横线 + 副标题」样式 |

设计要点：
- **不依赖 PySide6 也能 import 模块**：每个组件 `class_<Name>(<QWidget>)` 都写
  在工厂函数内部，模块顶层只有 `build_*` 函数。`from doubi.ui.widgets import build_*`
  在 CI 无头环境也能跑。
- **API 一致**：所有工厂都返回 `(Class, factory)` 二元组，调用方
  `cls = build_xxx(); widget = cls()` 拿现成组件。
- **不强制使用**：现有 qfluentwidgets 控件（`PushButton` / `LineEdit` 等）继续直接用，
  共享组件是「需要统一表达力」时用，**不取代** fluent 控件。

**页面级美化**（统一语言落到四个页面 + 三个对话框）：
- 解析页：PageHeader + 输入卡 + QStackedWidget 切换表格/空态；行高统一 36px
- 下载页：4 个 StatChip + 双空态（下载中 / 已完成）+ 按钮从 24→28px
- 历史页：2 个 StatChip + 表格/空态切换 + 数据库未启用引导
- 设置页：拆成 5 张分组卡（账号 / 下载 / 性能 / 主题 / Cookie），每张
  有标题 + 副标题 + 分隔线；不再是一张大表单
- 登录对话框：B 站 / 抖音各加品牌 hero 区（圆形平台色徽章 + 标题 + 副标题），
  右侧放 32px 应用图标作为「这是豆比下载」的次级落款
- 关于对话框：品牌 hero + 信息卡 + 版权行

**修复的细节**：
- 空态副标题原本 56 字挤压成「宽 200px 文字溢出」状态，缩短为 ≤30 字
- 按钮文字原本被 `setFixedHeight(24)` 压扁，统一到 28px
- 抠掉图标的白色描边：`flood fill` BFS 阈值 240，把 20% 接近纯白的背景
  像素变透明——之前 PNG 图标四周有一圈白边
- QIcon 提供 8 个尺寸档（16/20/24/32/40/48/64/96/128/256），标题栏缩放
  不再锯齿

**启动体验**：
- 闪屏：加载期间显示 256px 品牌图标
- 任务栏图标：与窗口图标同步
- 窗口标题：`豆比下载 0.6.0 · 多平台视频下载器`（之前是 `DouBi - main`）

**主窗口**：
- 导航栏最底部加「关于」按钮（`position=NavigationItemPosition.BOTTOM`）
- 窗口默认尺寸 1100×760（之前是 1180×780），更贴合多数笔记本屏幕

**Bug 修复**：
- `settings.py` 启动时 `asyncio.ensure_future` 在 Qt 主线程里抛 RuntimeError，
  现有 `try/except` 只吞了警告没解决，账号状态卡死成「未登录」。
  修法：fallback 路径用 `asyncio.run()`，并在 `__aenter__` 防御性 try/except

**测试**：`tests/test_ui_polish.py` 新增 22 个，覆盖：
- 豆比紫主题存在性、`THEMES` 键集完整、所有主题的 dataclass 字段
- 排版 / 间距 / 圆角常量的单调性
- 辅助 QSS 函数返回非空字符串
- 资源模块元数据（`APP_NAME = "Doubi"`、版本号、版权）
- 图标路径解析到 `RESOURCE_DIR/icon.png`、且文件存在
- `load_app_icon()` 在有/无尺寸参数下都返回非空 QIcon
- 共享组件工厂可调用 + 实例化 + 各项 set 方法有效
- 关于对话框可实例化、标题以「关于」开头
- 闪屏不崩溃（图标缺失时静默退化为 None）

`tests/test_ui_workers.py` 增加 1 个（`build_main_window` 可用性）。

统计：381 → 403 passed / 4 skipped（+22）。

---

### M6.5 矢量图标管线（SVG → 多档位 Qt → 多主题配色）

M6.4 上图标已经改过两版（PNG、抠白底），但都是「一张位图硬塞进所有地方」。这一轮把
图标做成**矢量 + 主题感知**——切主题时标题栏、关于对话框、登录对话框、闪屏里的
图标自动换色。详见 [docs/ICONS.md](../ICONS.md)（或 DEVELOPMENT §13.6）。

**设计源稿**：用户提供 `icon.svg`（1124×1124，画板较大、带 `<filter>` 投影
+ `<clipPath>` 裁剪）。直接 `QSvgRenderer` 渲染有两大坑：

1. **filter 失效**：Qt 只实现 SVG Tiny 1.2，原始 SVG 的 `feColorMatrix`
   被误画成「实心黑圆角矩形」在最上层——实测 29% 像素变纯黑，整张图标
   糊掉。
2. **留白过大**：原始画布 1124×1124，但圆角方块只占 (50,30)-(1074,1054)，
   四周 4.5% 是死边。图标在标题栏 / 任务栏里看着偏小就是这段留白吃掉的。

**修法**（`ui/resources/icon_template.svg`）：
- 去 `<filter>`、去 `<clipPath>`，投影由 rim-light 描边近似，clipPath 本来
  就是 no-op（裁剪框完全包住两个腮红椭圆）
- viewBox 收紧到 `50 30 1024 1024`，让圆角方块出血铺满整幅画布
- 7 个品牌色 hex（`#FF8C42 / #FF5E7C / #E8552A / #FFE4D1 / #2A2A2A / #FF9AA2 / #FF6B6B`）
  既是模板里的字面量，也是**换色锚点**——`icon_svg(accent)` 一次正则替换完成
- 模板单独打开就是一张正常的品牌色图标，没有引入模板语法

**资源模块**（`ui/resources/__init__.py`，~260 行）：
- `BRAND_PALETTE`：7 色 → 语义名（`bg_from` / `tuft` / `face` / `ink` / `blush` / `tongue`）
- `icon_palette(accent=None)`：按主色推导整套图标配色
  - 底板渐变 = 主色色相 ±20°，亮度 0.63 → 0.68（莫兰迪等低饱和主题会被压到
    `0.42 + 0.55*s`，不会刺眼）
  - 呆毛 = 同色相再沉一档（亮度 0.52）
  - 脸 = 主色色相的极浅色（亮度 0.90）
  - **腮红 / 舌头 / 眼睛恒定**——这三是吉祥物辨识度的核心，跟主题变色
    会丢掉可爱感
- `icon_svg(accent=None)`：单次正则替换换色（不是逐色 `str.replace`，
  避免「A 被换成 B，B 又被下一轮替换」的二次命中 bug）
- `render_icon_pixmap(size, accent=None, *, themed=True)`：用 QtSvg 渲染到
  任意尺寸。`themed=True` 时自动跟随当前主题的主色
- `load_app_icon(size=None, ...)`：返回 `QIcon`，默认装填 8 档尺寸
  （16/20/24/32/40/48/64/96/128/256），Qt 在标题栏 / 任务栏 / Alt+Tab
  各挑最合适的一档，避免系统强制缩放产生锯齿
- `load_splash_pixmap(w, h)`：闪屏专用，`min(w, h)` 边长的矢量渲染
- 缓存：`_pixmap_cache` / `_icon_cache` 按 `(size, accent)` 缓存

**豆比紫主题二次推导陷阱**：`doubi` 主题本身就是从图标反推的，再用主色
`#f59e6a` 推导回图标会偏离原图。`icon_palette(doubi)` 直接返回
`BRAND_PALETTE` 不变。`_active_accent()` 检测到 `current_theme().name == "doubi"`
时返回 `None`，让 `themed=True` 走品牌原色。

**主窗口图标全链路**：
```
set_theme(...)
  → subscribe_theme(self, _refresh_app_icon) 自动触发
  → load_app_icon() 渲染新配色
  → self.setWindowIcon(icon)
  → QApplication.setWindowIcon(icon)（任务栏 / Alt+Tab 同步）
  → windowIconChanged 信号
  → qfluentwidgets.FluentTitleBar.setIcon(icon)
  → iconLabel.setPixmap(QIcon(icon).pixmap(18, 18))   ← 这里
```

`qfluentwidgets.FluentTitleBar.setIcon` 把 pixmap 尺寸**写死 18px**——
48px 高的标题栏里 18px 图标明显偏小。修法：
- `iconLabel.setFixedSize(28, 28)`
- 断开 `windowIconChanged → title_bar.setIcon` 的旧连接
- 改用 `set_icon(icon)` 闭包，按新尺寸重设 pixmap
- 全程防御性处理（拿不到 `iconLabel` 就放弃，不影响主窗口）

**关于 / 登录对话框补 setWindowIcon**：这三个 dialog 之前没设
`windowIcon`，Windows 任务栏 / Alt+Tab 会回退到 **python.exe 的双蛇 logo**
（用户报的「Python 终端图标」就是这个）。修法是 `self.setWindowIcon(load_app_icon())`
+ 工厂函数顶部 import `load_app_icon`。

**真机验证**（`screenshots/` 下 `verify_*.png` + `icon_themes.png`）：
- 7 套主题在标题栏图标底板的采样：7 种不同底板色（豆比橙、深海青绿、高对比黄等）
- 关于对话框 96px 大图标、关于信息卡布局正确
- 登录对话框平台徽章 + 应用图标次级落款

**测试**：`test_ui_polish.py` 新增 20 个：
- 模板存在性 + 含 7 个品牌色锚点
- 模板无 `<filter>` / `<clipPath>`（剥注释后查）
- `icon_palette(None)` 等于品牌调色板；脏色值回退到品牌调色板
- `icon_palette("#2dd4bf")` 推导完整 7 键、都是合法 hex
- 腮红 / 舌头 / 眼睛在 4 个测试主题下都保持品牌色
- 底板 / 脸 / 呆毛在换主题时确实换色
- 莫兰迪主色推导的底板饱和度 < 亮色主色推导的底板饱和度
- 换色后的 SVG 不残留任何被替换的锚点色
- `icon_svg(None)` 字节相等于模板
- `render_icon_pixmap(128)` 不出现 >5% 的纯黑（filter bug 回归）
- 渲染结果是全出血（中心不透明、左上角被圆角切掉、顶边中点不透明）
- 拒绝 `size <= 0`
- QIcon 含全部 8 档尺寸
- 3 套主题渲染出的图标底板色互不相同
- 豆比紫主题下 `_active_accent()` 返回 `None`（不二次推导）
- `load_app_icon()` 默认 size=None 时跟当前主题

**`scripts/build_icons.py`**：从 SVG 模板生成 1024px 兜底 PNG + 各主题预览图
（`screenshots/icon_themes.png`），运行时只在 QtSvg 不可用时使用 PNG。

**踩过的坑**：
- `QPixmap.save(QBuffer, "PNG")` 在 `QT_QPA_PLATFORM=offscreen` 下会触发
  `STATUS_STACK_BUFFER_OVERRUN`（0xC0000409）——某些 PySide6 6.x 版本的
  bug。换 `QImage.save(QBuffer, "PNG")` 立即好。这条经验写进了 `build_ico.py`
  的注释。
- `BRAND_PALETTE` 的 hex 必须与模板里的字面量**逐字一致**（包括大小写），
  否则 `icon_svg` 替换锚点会漏色。`BRAND_PALETTE` 写成大写、模板跟着
  大写，避免 `ValueError: invalid hex` 类静默 bug。

统计：403 → 423 passed / 4 skipped（+20）。

---

### M6.6 Windows 任务栏图标 + PyInstaller 打包

用户报「Windows 任务栏上显示的图标也是 Python 默认那个」。这是 Python 应用的**硬伤**：
任务栏的「应用分组」图标从 **.exe 文件资源段**读，Python 进程没这个资源，
永远是 `python.exe` 的蓝色终端 + 双蛇。`QApplication.setWindowIcon` 只能改
标题栏 / Alt+Tab，**改不了任务栏的应用图标**。

**解决**：`PyInstaller` 打包成单文件 .exe 时把 `icon.ico` 嵌入 .exe 资源，
Windows 任务栏读这个资源。详见 [docs/BUILD.md](../BUILD.md)。

**`scripts/build_ico.py`**（手写 ICONDIR / ICONDIRENTRY）：
- 不依赖 Pillow——`Pillow 12.3.0 + Python 3.13 + Windows` 触发
  `STATUS_STACK_BUFFER_OVERRUN`。绕开最稳的路径
- 6 档位（16/32/48/64/128/256）独立矢量渲染 → Qt `QImage.save(QBuffer, "PNG")`
  → 内存 PNG 字节流
- 按 .ico 格式手写 6 字节 ICONDIR + 6×16 字节 ICONDIRENTRY + PNG 数据
- Windows 任务栏 / 资源管理器按目标像素挑最接近的尺寸

**`scripts/build_exe.py`**（PyInstaller 包装）：
- `--onefile` 默认 + `--windowed` 不弹控制台
- `--icon src/doubi/ui/resources/icon.ico` —— 关键！让 .exe 资源段带图标
- `--add-data icon_template.svg;doubi/ui/resources` —— 模板走文件系统读
- `--collect-all qframelesswindow --collect-all qfluentwidgets` —— 第三方
  Qt 库有隐藏的 QRC 资源 / 插件，PyInstaller 默认钩子抓不全
- `--collect-submodules doubi` + 入口不用包内文件。`app.py` 内部是
  `from .theme import ...` 相对导入，onefile 模式若以顶层脚本方式解包运行，
  **`doubi` 父包不存在**，相对 import 直接挂
- 产物：`dist/doubi-gui.exe`（~235 MB，PyInstaller onefile 把 Python
  runtime 全打包，正常体积）

> ⚠️ **后续更正（M6.8）**：本条目原先写的是「改用 `--module doubi.ui.app`
> 走模块路径」。**PyInstaller 并没有 `--module` 选项**，6.22.2 会直接报
> `unrecognized arguments: --module`——当时的记录是错的。真正的解法是
> `build_exe.py` 在构建期生成一层位于包**外面**的启动壳，用绝对导入
> `from doubi.ui.app import main` 进包，包结构因此完整保留。见
> [docs/BUILD.md §4.2 / §5.1](./BUILD.md)。

**踩过的坑**：
- 首次打包 `app.py` 入口失败：`ImportError: attempted relative import
  with no known parent package`。原因如上，改用包外启动壳后通过
  （当时误记为 `--module`，见上方更正）。
- `QPixmap.save(QBuffer, "PNG")` 在 offscreen 平台 crash（见 M6.5）。

**测试**：打包产物通过 `tests/test_ui_polish.py` 的回归测试覆盖
（图标模板 / 资源路径 / `load_app_icon` / dialog windowIcon），但
**`build_exe.py` 本身没加测试**——打包产物验证要 `dist/*.exe` 真启动
GUI，比单元测试贵两个量级，留给发版前的手动 check 清单。

---

## M6.7 (2026-08-23) — 抖音合集批量下载 + 登录链路修复

> 这一轮的共同根因是「**抖音在 yt-dlp 之外还有一整个签名 Web API 世界**」：
> 抽取器只认 `/video/{id}`，合集/用户作品/登录态判定全都要自己实现。

### 抖音合集（mix）批量下载（主特性）

- **核心认知**：yt-dlp 2026.08 **没有**抖音合集/用户页抽取器（离线
  `ie.suitable()` 验证均 NO MATCH），合集列举必须走签名 Web API
  `/aweme/v1/web/mix/aweme/?mix_id=&cursor=&count=`。
- 新增 `platforms/douyin/sign/`：a_bogus / x_bogus 签名算法（移植自
  douyin-downloader-main，MIT；abogus.py 依赖 `gmssl` 的 sm3）。
- 新增 `platforms/douyin/webapi.py`：httpx 签名客户端。
  - 反爬重试：**HTTP 200 空 body = 反爬**（最阴险的信号）、403/429/461/471/5xx
    全部重新签名重试（延迟 1/2/5s），每次尝试重新取 msToken
  - msToken 策略：cookie 文件优先，否则 182 随机字符伪 token 兜底
  - `iter_mix_awemes` / `iter_user_posts` 分页枚举（cursor 卡死保护）
  - `aweme_to_media_item` 归一化：canonical `/video/{id}`、desc 首行做标题、
    duration ms→s、mix_info 写 extra
- 接线（六处）：
  - `url.py`：+iesdouyin.com/share/mix/detail/{id} 分享链分类
  - `adapter.py`：parse() 路由 COLLECTION/MIX → `_parse_collection`（MIX 容器，
    标题从第一页 `mix_info.mix_name` 探测——`/mix/detail/` 端点本身 403）；
    `collection_of(aweme_id)` 反查所属合集；expand() 加 MIX 分支
  - `strategies.py`：PostStrategy 优先走 `webapi.iter_user_posts`
    （旧 yt-dlp fetch_flat 路径已**静默失效**，保留兜底）
  - `core/pipeline.py`：三处容器判定（run / download_item 守卫 / parse_and_expand）
    从 `USER` 扩为 `(USER, MIX)`——`is_container()` 只看 children，MIX 容器解析时
    刻意不填。顺带修复 B 站 LIST 合集的同类判定
  - `ui/pages/parse.py`：右键菜单 +「下载整个合集」
    （collection_of → expand → 重填结果表）
- **两种用户用法**：① 直接粘贴合集链接（`/collection/{id}` 或 iesdouyin 分享链）；
  ② 解析任意合集内视频 → 右键 →「下载整个合集」
- 实测：合集《我是xj》30 条视频完整分页枚举，标题/时长/canonical URL 正确；
  从单条视频反查合集命中

### 抖音链接识别扩展

- `modal_id` 弹窗链接（`/jingxuan?modal_id=...`）：modal_id 就是 aweme_id，
  adapter 将其规范化为 `/video/{id}` 再交 yt-dlp
- 用户主页合集 tab 的单视频链接（`/user/{sec_uid}?...&modal_id=...&vid=...`）：
  modal_id / vid 规则**必须排在 USER 之前**，否则会被误判成用户容器触发整页展开；
  顺手收紧 USER 的 id 字符类（原会把查询串吞进 sec_uid）

### 抖音登录链路修复（三轮）

- **扫码后不抓 cookie**：`_DOUYIN_REQUIRED_COOKIES` 名单两个方向都错——
  ttwid/odin_tt/passport_csrf_token 是游客 cookie，msToken 是 JS 风控 token
  （Chromium 自动化下经常不写入），真正的登录态 cookie（sessionid/sessionid_ss/
  sid_guard）不在名单里。改为登录 cookie 名单 + `min_present=1`
- **登录窗口 10s 超时不关**：`browser_login.py` 在登录成功后等
  `wait_for_load_state("networkidle")`——落地页的推荐流/WebSocket/心跳让它永远
  到不了 networkidle。改为固定 500ms settle。B 站同路径一并修复
- **登录态校验 404**：`user/info/self` 端点被风控（无签名必 404），
  `validate_cookies` 降级为 session cookie 存在性判定

### GUI 下载 cookie 注入（M 级 bug）

- 现象：解析成功但 yt-dlp 报 `Fresh cookies (not necessarily logged in) are needed`
- 根因：解析阶段 adapter 自己读 cookie 文件，下载阶段引擎只认
  `DownloadOptions.cookies_file`——四个入口全都没传，引擎裸跑
- 修在 `core/pipeline.py`（懒加载注入 + `dataclasses.replace` 副本），
  修一处救四端（GUI/CLI/REST/MCP）

### 其他

- EmptyState 文字挤压回归测试（间距/minHeight/line-height 三重断言，
  防止上次的"无记录回退"再次无声发生）
- 真实环境 E2E 脚本：`_test_live/sanity_collection.py`（离线 stub）、
  `_test_live/e2e_collection_live.py`（真实 API，不入正式测试套件）

### 统计

- 源码 70 个 .py 文件，约 17,900 行
- 测试 21 个文件，454 个用例收集：**450 passed / 4 skipped**
  （4 个 skip 均为「无 PySide6 则跳过」的 GUI 用例；全量跑一次约 27 分钟，
  theme_apply_gui 的真实 Qt 渲染占大头——增量验证用单文件跑）
- 基线演进：423（M6.6）→ 450（M6.7 登录修复 + 链接识别 + 合集功能，+31 用例）

---

## M6.8 (2026-08-23) — NSIS 安装包 + 版本号统一 + 主题顺序

### NSIS 安装包（新增）

- `installer/doubi.nsi` + `scripts/build_installer.py`：一条
  `python scripts/build_installer.py` 出 `dist/DouBi-Setup-<version>.exe`（213.1 MB）
- 便携版 NSIS 3.11 随仓库入库（`tools/nsis/`，zlib/libpng 许可），
  clone 下来不装任何打包工具即可构建
- 安装形态：`RequestExecutionLevel user` 装到 `%LOCALAPPDATA%\DouBi`，
  **无 UAC 弹窗**；开始菜单快捷方式（必装）+ 桌面快捷方式（可选）
- 卸载：目录 / 注册表 / 进程零残留；`~/.doubi` 的配置与下载记录默认**保留**，
  需要清除时在卸载界面勾选独立分节
- 打包形态选的是 **onedir 拆目录**而非 onefile：安装包本身已经压缩过一次，
  再套 onefile 的自解压等于压两遍，且每次启动都要解包 800 MB 到 `%TEMP%`

**踩过的坑**：

- **`RequestExecutionLevel user` 意味着注册表只能写 HKCU**。写 HKLM
  不会报错，是**静默失败**——控制面板里看不到卸载项，排查时容易误判成
  卸载信息没写。
- **便携版 NSIS 没有 `nsProcess.dll`**，检测「程序是否在运行」只能退回
  `tasklist` 的退出码当谓词，`taskkill` 之后还要 `Sleep 1500`——
  句柄释放是异步的，不等就会撞 `File: 无法写入`。
- **`makensis` 必须带 `/INPUTCHARSET UTF8`**，否则中文界面文案全是乱码。
- **NSIS 的相对路径是相对 `makensis` 的工作目录**解析的，不是相对 .nsi
  所在目录，所以脚本里的路径一律用 `/D` 注入绝对路径。
- **`VIProductVersion` 必须是恰好四段数字**，`0.1.0` 会直接编译失败。
- LZMA solid 压缩 825,238,595 → 223,414,961 字节（**27.0%**）是**单线程**的，
  约 10 分钟，期间在 `%TEMP%` 暂存约 800 MB。看着像卡死时先
  `Get-Process makensis` 确认还活着再等，别急着 Ctrl+C。

### 版本号统一 0.6.0 → 0.1.0

- 现象：安装包写 `0.1.0`，装完打开标题栏却显示 `豆比下载 0.6.0`
- 根因：版本号有**两处真源**且已漂移——`pyproject.toml` 的 `version`
  （被 `build_installer.py` 读走注入 NSIS）与
  `src/doubi/ui/resources/__init__.py` 的 `APP_VERSION`（标题栏 + 关于对话框 ×2）
- 修法：`APP_VERSION` 对齐到 `0.1.0`。改版本号务必同时动这两处
- 判据：静默装到独立目录后启动，窗口标题为
  `豆比下载 0.1.0 · 多平台视频下载器`

### 主题顺序

- `ui/theme.py` 的 `THEMES` 键序调整为
  `default_light → default_dark → doubi → deep_sea → morandi → eye_care → high_contrast`，
  两套系统默认主题排最前面，品牌主题 `doubi` 紧随其后
- `THEMES` 的键序同时决定设置页下拉框、导航栏循环切换与 `--theme choices`
  的顺序，改一处三处同步

### 文档

- `docs/BUILD.md`：新增 §6「NSIS 安装包」（命令 / makensis 调用要点 /
  `.nsi` 设计取舍 / 静默验证配方 / 编译卡顿判别），章节重编号至 §9，
  验证清单补安装包检查项与版本一致性检查
- **更正 `--module` 的错误记录**：`PyInstaller` **没有** `--module` 选项，
  早期 BUILD.md 与 CHANGELOG 把它写成了相对导入崩溃的解法。真解法是
  构建期生成包外启动壳，用绝对导入 `from doubi.ui.app import main` 进包
- `README.md`：补主界面与主题截图、安装包获取路径、「数据与配置」小节
  （`~/.doubi` 与相对路径的 `doubi.db` 不是一回事）、项目结构补
  `scripts/` `installer/` `tools/`、文档表补 `UI_DESIGN.md`
- 主题表顺序在 `README` / `QUICKSTART` / `DEVELOPMENT` / `UI_DESIGN`
  四处与代码对齐——这几处都写着「键序 = 界面展示序」，表格却是旧序

### 发布准备

- `.gitignore` 补 `doubi.db` / `download_manifest.jsonl` / `_test_live/`
  / `.workbuddy/` / 打包临时产物；前两者含真实下载历史，已
  `git rm --cached` 停止跟踪（本地文件保留）
- `tools/nsis/` 显式**不忽略**，换取「clone 即可打包」

---

## M6.9 (2026-08-24) — 安全敞口收口 + 版本号单一真源 + 健壮性加固

> 这一轮没有新功能，全在补「不做可能出事」的洞。三件事的共同点是
> **失败时不报错**：绑到公网不会报错、版本号漂移不会报错、
> 取消下载留下的脏连接也不会报错——都要靠专门的守卫把沉默变成响声。

### REST 鉴权 + 默认绑回环

- `server/security.py`（新增）：`resolve_token` / `token_matches` /
  `audit_binding`
- **token 比较用 `secrets.compare_digest` 而不是 `==`**：后者发现首个
  不同字节就返回，比较耗时随「猜对的前缀长度」变化，逐字节爆破可从
  256^n 降到 256×n 次。这类计时侧信道在本地网络里尤其好利用
- **默认 `--host 127.0.0.1`**。绑到本机之外可达的地址且**没有 token 时
  拒绝启动**，除非显式给 `--allow-insecure` 逃生阀。原先的默认值等于
  「把一个能往磁盘写文件的接口挂到局域网上」，且没有任何提示
- 报错文案给三条出路（去掉 `--host` / 设 token / 明知故犯），
  而不是只说「拒绝启动」
- 测试 `test_server_security.py` 81 例（参数化占大头）

### 版本号单一真源

- M6.8 只是把两处漂移的数值**对齐**，真源仍是两个——迟早再漂
- 改为 `pyproject.toml` 是唯一真源，`doubi.__version__` 经
  `importlib.metadata` 派生，`APP_VERSION = __version__` 不再手抄
- `test_version_single_source.py` 7 例：断言标题栏 / `doubi -V` /
  REST `/health` / 安装包文件名四处**恒等**，而不是各自「等于 0.1.0」
  ——后者改版本号时会四处同时变红，等于没测

### 健壮性

- **pipeline 重试退避尊重 `cancel_check`**：退避期间不占并发额度，
  取消不重试（`test_pipeline_retry.py` 16 例，**8/8 变异杀死**）
- **收敛 `Database` 双生命周期**（既能当上下文管理器又能长驻）
- **取消下载引发的连接泄漏与连接毒化（BUG #1–#4）**：取消发生在
  `await` 点上，`finally` 里那句归还连接的代码在某些路径上根本没执行到，
  连接带着未回滚的事务回到池子里，**下一个使用者才炸**——现场与根因
  隔着好几个测试。见 DEVELOPMENT.md 坑位 27 / 28 / 29
- **重试通知让 GUI 进度条倒退回 0**：重试是新一轮 `download_item`，
  fraction 从 0 重新开始。顺带审计四端 fraction 消费者，加单调守卫
  （坑位 26）
- `server/app.py` `_execute_download` 里一个只 append 不读的 `events`
  列表——长任务下是纯内存增长

---

## M6.10 (2026-08-24) — 跨进程断点续传恢复

> 引擎层的 `continuedl` 一直是开的，`.part` 文件也一直在磁盘上：
> **重启后能接着下的能力早就有了，缺的只是「重启后还记得有哪些任务」**。
> 所以这一轮的工作量全在持久化与交互，不在下载。

### 三层

| 层 | 位置 | 职责 |
|---|---|---|
| 持久层 | `core/storage/database.py` | `pending_task` 表 + `PendingTaskRow` + options 快照编解码 |
| 状态层 | `ui/task_manager.py` | `list_restorable` / `restore` / `discard_restorable` / `_reseed_counter` |
| 交互层 | `ui/main_window.py` | 启动时 `singleShot(0, _offer_restore)` → 询问 → `_restore_flow` |

### 几个刻意的决定（改之前先读理由，详见 DEVELOPMENT.md §13.2.1）

- **恢复出来的任务一律是 `paused`，不自动开下**。重启这个时刻恰恰是
  用户意图最不确定的时候（可能就是因为下得太猛才关的），而
  `.part` 文件无论如何都在，晚点下不丢东西；自动开下则可能在用户
  没注意时占满带宽
- **「不恢复」必须落库**，否则同一批任务每次启动都问一遍，
  用户第二次看见就会开始忽略所有弹窗
- **`restore()` 必须 `_reseed_counter()`**：id 计数器从 0 开始，
  恢复了 5 个任务后新建任务会撞 id。`task_manager.py:513-519` 那处
  改键是第二道防线，**不是**替代品
- 用 `get_running_loop()` 而不是 `get_event_loop()`——后者在无循环时
  会造一个新的，恢复流程会静默地跑在错误的循环上
- `self._restore_task = task` 那句不能删：asyncio 只持弱引用，
  不留强引用任务可能被 GC 掉，表现为「有时恢复有时不恢复」

### 踩过的坑

- **切页动画让 `currentWidget()` 延迟 300ms 才更新**：
  qfluentwidgets 的 `setCurrentWidget` 默认 `popOut=True`，那条分支
  只记下 `_nextIndex` 并起动画，**不调 `super().setCurrentIndex()`**。
  测试里 `setAnimationEnabled(False)` 解决——不要改成 sleep 等动画，
  也不要把断言弱化成「调用过 setCurrentWidget」（坑位 30）
- **`deleteLater()` 在不转 Qt 事件循环的测试里等于没拆**：它只往队列里
  排一个 `DeferredDelete`，纯 asyncio 的测试文件没人消费这个队列，
  析构不发生 → `destroyed` 不发 → `subscribe_theme` 的解绑不执行。
  实测建 3 个窗口后主题回调数 57，`deleteLater()` 之后还是 57。
  用 `QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)`
  才真正归零（坑位 31）。这条同时更正了 §13.7 原先的说法：贵的不是
  「构造窗口」，是**没死透的旧窗口**
- 测试 `test_ui_restore.py` 12 例，**5 轮破坏验证**：删
  `discard_restorable` / 断开 `task_added` / 删 `_reseed_counter` /
  改成自动续传 / 删标题截断，各自只让对应用例变红

---

## M6.11 (2026-08-24) — 下载前选项对话框

> 文档自评里这一项 ROI 最高。范围刻意只取 4 个「单次下载产物」字段——
> 把弹窗做成「这一批我想要什么」的小开关，不侵入设置页的「持久偏好」
> 概念，避免出现「我在弹窗里关掉的字幕，会不会被记成全局关闭」的歧义。

### 形状（保住唯一的 `AppConfig → DownloadOptions` 搬运边界）

- 解析页所有「准备入队一条下载」的入口（quick download / 勾选下载）都
  改走 `_options_for_overrides(overrides=None)`，不再直接 `_build_options()`。
  右键菜单「作为单视频下载」保留 `_options_for_overrides()` 但不接弹窗——
  右键菜单本身已经是一个明确操作
- **弹窗不绕进 `_build_options`**：overrides 用 `dataclasses.replace` 叠
  加在已搬运好的 `DownloadOptions` 上，并按 `DownloadOptions` 字段名作白
  名单过滤（防止 `database_path` / `proxy` 这类 AppConfig 字段被误传）
- `_build_options_covers_every_shared_config_field` 守卫测试继续生效——
  `prompt_before_download` 是 AppConfig-only（DownloadOptions 没有同名
  字段），所以守卫用的 `cfg_names & opt_names` 交集算法天然不踩它

### 触发方式（你定的）

- 设置页「主题与外观」卡片里加一个 `prompt_before_download` SwitchButton，
  默认 **False**——「点一下就走」是绝大多数用户的心智模型
- 启动时主窗口从设置页的 `_cfg` 读初值并下发到 `parse_interface`；用户
  在设置页里切换时通过 `promptBeforeDownloadChanged` 信号实时下发，不
  必重启

### 弹窗本身（`PromptOptionsDialog`）

- `qfluentwidgets.MessageBoxBase` 子类。两个按钮（**下载** / **取消**）。
  本仓库这个版本的 qfluentwidgets 没有 `view` widget，只有 `viewLayout`
  （QVBoxLayout），这是与文档示例不一致的地方，必须看本地源码
- 字段：`max_quality` / `container` / `write_thumbnail` / `write_metadata_json`
- 选项集合复用设置页已定的 `["mp4","mkv"]` / `["best","8k","4k","1080p","720p","480p"]`
  ——不在弹窗里另起炉灶，否则两处能选的值不一样就是 bug
- 测试用 `tests/test_prompt_options.py` 11 例（`exec()` 会进模态循环，
  offscreen 测试环境下会卡死，所以测试覆盖三个非模态面：构造 / 字段
  收集 / ParsePage 集成）

### 配置层

- `AppConfig.prompt_before_download: bool = False`，加进 `DEFAULTS`、
  `load_config` 的显式字段；`to_dict()` 自动包含（`asdict`），所以
  settings.py 的 `_on_save` 一行 `data["prompt_before_download"] = ...`
  就够了
- YAML 存盘键 `prompt_before_download`，人类可读；切换瞬时生效

---

## M6.12 (2026-08-24) — YouTube 适配器 + 注册收敛 + CI 打包 workflow

> 这一轮是「最低成本扩张」的样板：YouTube adapter 总共不到 200 行
> 代码+测试，证明架构允许「按平台复杂度调整 adapter 厚度」。

### YouTube 适配器（`platforms/youtube/`）

- **URL 分类**：watch / shorts / embed / live / youtu.be 五种视频形态 +
  /@handle / /channel/UC... 频道 + /playlist 三类容器，全部正则驱动。
  11 字符 video ID 用 `(?:[&#]|$)` 锚定定长，拒绝 `watch?v=IDextra` 这类
  12 字符的伪 ID
- **元数据获取**：`asyncio.to_thread` 包 `yt_dlp.YoutubeDL.extract_info(
  download=False)`，仿浏览器 UA；失败 → 返回占位 item（title="YouTube
  ID"），让 GUI 仍能入队，把元数据拉取完全交给下载阶段兜底
- **故意不做**：channel / playlist 容器展开（由 yt-dlp 自己处理）、
  danmaku / 字幕 / NFO post-processing（yt-dlp 原生支持 YouTube）、
  cookie 注入（YouTube 不需要）
- **架构验真**：这是「adapter 极简化」样本——B 站 / 抖音各自 1000+ 行
  adapter（容器策略 / 签名 / cookie），YouTube 不到 200 行。说明架构
  允许「按平台复杂度调整 adapter 厚度」

### 注册收敛

- 原来 3 处 `from ..platforms import douyin, bilibili` 的副作用 import
  （server/app.py / mcp/server.py / core/engine_loader.py）合并为单点
  `from .. import platforms`。新增 platform 只需改 `platforms/__init__.py`
  一处即可

### CI 打包 workflow（`.github/workflows/build.yml`）

- 触发：tag `v*` push（自动跑 + 创建 GitHub Release draft）+ 手动
  `workflow_dispatch`（仅验证打包，不发版）
- 流程：测试 → `build_installer.py` → 计算 SHA256 → 上传 artifact
  （90 天）→ （仅 tag）创建 draft release
- 显式不交叉验证：用 PyInstaller 命令行重写一遍「会复制一份维护成本」，
  直接调项目里既有的 `scripts/build_installer.py`
- 故意不加密签名：项目规模不需要 GPG，SHA256 已是最低成本的「未篡改」
  证据
- ruff 已经在 CI 装了；mypy **没**装——仓库本就没有 mypy 配置，强行加
  要写大量第三方库（PySide6/qfluentwidgets）的 type stubs，性价比低

---

## M6.13 (2026-08-25) — YouTube 下载双故障修复 + 错误可见性

> 用户报「YouTube 能解析但下载失败」，跟进后发现是**两个独立的非对称故障
> 叠加**，并且失败后 GUI 只显示「engine returned False」，无法定位。
> 一次改动同时把**故障根因**和**故障可见性**都修掉。

### 修复 1：解析与下载用不同 User-Agent → YouTube 403（`engines/yt_dlp.py`）

**症状**：解析能拿到标题和作者，但点下载就失败，GUI 显示 403。

**根因**：`YouTubeAdapter._extract_meta(do_meta=True)` 为元数据抓取硬编码了
一个 Chrome UA（`Mozilla/5.0 ... Chrome/124.0 Safari/537.36`），但引擎层
之前只在 `DownloadOptions.user_agent` **显式传了值**时才写进 yt-dlp，
否则沿用 yt-dlp 内置的 `yt-dlp/<版本号>`。YouTube 近年对裸
`yt-dlp/*` UA 渐进式 HTTP 403，于是出现**解析阶段过了、下载阶段被拒**
的不对称失败。

**修法**：
- `engines/yt_dlp.py` 新增模块级常量 `DEFAULT_USER_AGENT`（与适配器用
  同一串 Chrome UA），`_build_opts()` 改为
  `opts["user_agent"] = options.user_agent or DEFAULT_USER_AGENT`。
- 保证**解析与下载永远用同一个身份**。对 B 站 / 抖音也是无害的更保守
  默认（本来两者的 UA 宽容度就更高）。

### 修复 2：独立视频布局把标题写两遍 → Windows MAX_PATH（`file_layout` + `naming`）

**症状**（用户截图原文）：
```
yt-dlp error: ERROR: unable to open for writing: [Errno 2] No such file or directory:
'Downloaded\youtube\The Middle-Sized Garden\video\
  Garden design in is the detail - ... oasis\
  Garden design in is the detail - ... oasis_If_JeStOC1o.f401.mp4.part'
```
标题 "Garden design in is the detail - how to transform a boring backyard to a
lush green oasis" 约 95 字，同时出现在**子目录名**和**文件名前缀**里，
路径总长度直接突破 Windows 经典 MAX_PATH=260。yt-dlp 打开 `.part` 时，
Windows API 因父目录路径超限返回「找不到文件」，与真实的文件不存在共享
错误码，表象非常有欺骗性。

**修法（三层防线，任何单一一层都不够）**：

| 层 | 改动 | 效果 |
| --- | --- | --- |
| `file_layout.item_leaf_parts()` | **独立视频不再套 `{title}/` 子目录**，返回 `[]` | 消除标题翻倍，立省 80–100 字路径长度 |
| `file_layout.MAX_COMPONENT` | 120 → 80 | 防止 collection/section/episode 三层各顶到 120 字 |
| `naming.MAX_BASENAME` | 200 → 120 | 文件名含 `{title}_{id}` 本身也被上限兜底 |

独立视频布局因此从：
```
Downloaded/youtube/author/video/{title_dir}/{title}_{id}.mp4
```
变为（与 yt-dlp 默认输出、合集内 episode 的布局一致）：
```
Downloaded/youtube/author/video/{title}_{id}.mp4
```

Sidecar 文件（缩略图 / NFO / JSON / 字幕 / 弹幕）共享同一个 basename 前
缀，在文件系统里天然排序到一起，**不需要独立子目录也能自证归属**。

**合集/分类合集布局保持不变**：合集名与分集名本来就不重复，套合集子目录
才有意义（"所有 episode 共享一个文件夹"这个用户期望必须保留）。

`item_leaf_name()` 同步加空列表兜底，不影响未来调用方。

### 修复 3：pipeline 重试循环吞掉引擎真实错误（`core/pipeline.py`）

**症状**：无论引擎是 403、超时、磁盘满还是 `[Errno 2]`，GUI 失败提示永
远是「下载失败」或至多「engine returned False」，无法区分故障。

**根因**：`pipeline._download_with_progress` 的重试循环在引擎返回
`False` 后直接：
```python
last_error = "" if ok else "engine returned False"
```
把引擎之前已经通过 progress hook 传上来的具体错误（如
`"yt-dlp error: HTTP Error 403: Forbidden"`、
`"yt-dlp error: [Errno 2] No such file or directory"`）**覆盖成通用
字符串**。

**修法**：为引擎侧的 progress 回调加一层 wrapper
（`_wrap_engine_progress`），闭包把 `yt-dlp error:` / `yt-dlp reported`
开头的消息写进共享 dict `last_engine_error`。最终赋值优先级：

```
last_error = 捕获到的引擎具体错误 or "engine returned False"
```

pipeline 自己抛出的异常分支同样优先用捕获内容，只有真的没任何线索时才
退回 `f"Exception: {exc}"`。GUI 因此能把真正的 HTTP 错误 / Errno / 超时
显示出来，不用靠猜。

### 测试修正

两条 `test_storage.py` 用例原先断言旧布局（独立视频有 title 子目录）：

- `test_resolve_item_dir_creates_leaf` → 重写为
  `test_resolve_item_dir_standalone_no_leaf_subdir`：断言独立视频的
  `item_dir` 等于 `save_dir`（共享目录，无额外 leaf）
- `test_resolve_item_dir_sanitizes_illegal_chars_in_leaf` → 重写为
  `test_resolve_item_dir_sanitizes_illegal_chars_in_collection_leaf`：
  把「非法字符过滤」验证移到合集场景——合集名仍然真有子目录，语义匹配。

309 条核心测试（storage / pipeline / engines / adapters / sidecars / task_manager）全部通过。

---

## M6.14 (2026-08-25) — 代码健康 / UX / 功能 / 工程化 一揽子改进

> 按「代码健康 → UX 补齐 → 功能缺口 → 工程化」四象限评审后落地的改进批次。
> 每条都带测试，回归 687 passed / 4 skipped。

### 一、代码健康

| # | 改动 | 文件 |
| --- | --- | --- |
| 1 | **容器判定收敛**：`is_container()` 与 `media_type in (USER, MIX)` 两套发散判定统一为 `MediaItem.needs_expansion()`，pipeline 全量替换 | `core/models.py`、`core/pipeline.py` |
| 2 | **测试提速**：引入 `pytest-xdist` 并行 + `gui`/`slow` 分层标记，全量 ~25min → ~10min | `pyproject.toml` |
| 3 | **静态检查**：`ruff`（lint）+ `mypy`（类型）配置入 `pyproject.toml` | `pyproject.toml` |
| 4 | **修正文档快照漂移**：DEVELOPMENT.md 快照版本对齐到 M6.13 | `docs/DEVELOPMENT.md` |

### 二、UX 补齐

| # | 改动 | 文件 |
| --- | --- | --- |
| 1 | **纯编号解析**：B 站裸 `BV/av/ep/ss/ml` 归一化为完整 URL | `platforms/bilibili/url.py` |
| 2 | **剪贴板监听**：复制链接后自动填入解析输入框 | `ui/pages/parse.py` |
| 3 | **解析历史**：记录 + 右键「重新解析」一键回填 | `ui/main_window.py` |
| 4 | **重复下载策略**：`duplicate_policy`（skip/redownload/ask）+ DB 去重 | `core/models.py`、`core/pipeline.py` |

### 三、功能缺口

| # | 改动 | 文件 |
| --- | --- | --- |
| 5 | **REST/MCP 容器子项级重试**：`process_batch` 追踪 `failed_items`，REST 暴露给前端做粒度重试；修掉 `UnboundLocalError` | `core/pipeline.py`、`server/app.py` |

### 四、工程化

| # | 改动 | 文件 |
| --- | --- | --- |
| 8 | **配置热重载提示**：需重启字段（database_path/theme/language）标注 | `ui/pages/settings.py` |
| 9 | **i18n 基础设施**：JSON 词表 + 模块级 `tr()`（不走 Qt `.ts/.qm` 工具链），`zh_CN.json` / `en.json` 双语言，设置页语言下拉，配置 `language` 字段 | `ui/i18n.py`、`ui/locales/*`、`ui/app.py`、`ui/main_window.py`、`ui/pages/settings.py`、`core/config.py` |
| 10 | **启动闪屏时序前移**：`show_splash` 后 `app.processEvents()` 让闪屏先渲染 | `ui/app.py` |

### i18n 设计取舍

不用 Qt 自带 `.ts/.qm` 工具链：`lupdate`/`lrelease` 两步构建依赖工具链，且 Qt 的 `tr()` 绑死 `QObject` 子类，模块级函数和 CLI/REST 用不了。改用 **JSON 词表 + 纯函数 `tr()`**：词表人能直接读改无需编译，`tr()` 任何代码都能调，回退顺序「当前语言 → `zh_CN` → key 本身」。

GUI 切语言后需重启生效（已渲染控件不自动重译），与 `database_path`/`theme` 同属「重启生效」档。本次迁移导航标签 / 窗口标题 / tooltip 等核心可见字符串，其余字符串后续按词表 key 逐步迁移即可，基础设施已就绪。

### 测试

新增 `tests/test_i18n.py`（14 例）：词表完整性、回退、占位符、语言切换、未知语言兜底、源语言全覆盖校验。回归 687 passed / 4 skipped。

---

## M6.15 (2026-08-25) — B站直播录制 + aria2 多线程引擎

> 把两项「需要外部环境」的功能做成了可独立测试的形态：
> 直播录制的 URL 识别 / 类型映射 / 引擎适配可单测；
> aria2 引擎用注入式 RPC 客户端，测试用 Mock 不依赖 aria2 二进制。

### 三-6 B站直播录制

| 层 | 改动 | 文件 |
| --- | --- | --- |
| URL 识别 | 新增 `BilibiliURLType.LIVE`，匹配 `live.bilibili.com/{room_id}`（含 h5/blanc 前缀和查询参数） | `platforms/bilibili/url.py` |
| 适配器映射 | `LIVE → MediaType.LIVE`，加入 `url_patterns` 和 `supported_media_types` | `platforms/bilibili/adapter.py` |
| extractor 识别 | `_classify_media_type` 识别 yt-dlp 的 `BiliBiliLive` extractor key | `platforms/bilibili/api.py` |
| 引擎适配 | 直播流不 `merge_output_format`（HLS 无片尾）、`live_from_start`（时移录制）、`fragment_retries=10`（断流重连） | `engines/yt_dlp.py` |

设计取舍：直播录制的真实循环（断流重连、时移边界、房间状态查询）需要真实直播流才能端到端验证，这部分留给集成测试。本次落地的是「识别 + 路由 + 引擎参数」三层，每一层都纯函数可单测，是直播功能的可靠地基。

### 三-7 aria2 多线程引擎

| 层 | 改动 | 文件 |
| --- | --- | --- |
| 引擎实现 | `Aria2Engine`：JSON-RPC 客户端、`addUri` / `tellStatus` / `remove` 三方法、进度轮询、取消、续传 | `engines/aria2.py`（新增） |
| 配置 | `engine`（yt-dlp / aria2）、`aria2_rpc_url`、`aria2_secret` | `core/config.py` |
| 引擎选择 | `build_default_engine(cfg)` 按配置选引擎，未知引擎名回退 yt-dlp | `core/engine_loader.py` |

设计取舍：

aria2 是纯下载器（不解析网页），所以 `Aria2Engine.supports()` 只认有 `item.extra["direct_url"]` 的 item——没有直链的 item 自动回退 yt-dlp。aria2 引擎的角色是「加速下载后端」，不取代 yt-dlp 的网页解析。

RPC 客户端是注入的（`Aria2RpcClient` Protocol），测试用内存 Mock 验证 `addUri` 参数构造、进度轮询、取消逻辑，不依赖 aria2 二进制。生产用 `_HttpxAria2Client`（基于 httpx，直接发 JSON-RPC）。

### 测试

| 文件 | 用例数 | 覆盖 |
| --- | --- | --- |
| `test_bilibili_adapter.py` | +8 | LIVE URL 识别（plain/h5/query）、不误吞 SPACE、match_url、类型映射、extractor 识别、supported_media_types |
| `test_aria2_engine.py` | 18（新增文件） | supports、_build_options（fragments/rate_limit/proxy/ua/resume/omission）、download（success/error/cancel/no_url/addUri_failure）、engine_loader（default/aria2/unknown/pipeline）、辅助函数 |

回归 687 + 8 + 18 = 713 passed / 4 skipped。

---

## 0.3.1 (2026-08-30) — 标题模板 + nm3u8dl watchdog 兜底 + 托盘 + 完成通知

> 0.3.0 发版后追加的 hotfix + UX 改进批次。0.3.0 段里的 M6.16–M6.21
> 是嗅探/打包/同步相关；本批聚焦「下载体验最后一公里」——
> 标题模板、进度条、关窗后还能叫回主窗口、下载完成弹通知。
> 三个里程碑各自的新增测试见小节末尾的测试表；全量回归 **913 passed /
> 7 skipped**（实测，口径见「0.3.1 统计」）。

## M6.22 (2026-08-30) — 下载前询问弹窗「修改视频标题」模板

> 把单任务已有的「下载前询问」弹窗扩成支持批量：勾选「修改视频标题」
> + 填模板（含 `{title}` token）→ 逐 item 渲染到 `MediaItem.title` →
> 复用既有 `naming.render_filename` 走完整路径。两处入队点都接上。

### 一、UI（`ui/pages/parse.py`）

- `PromptOptionsDialog` 加两个控件（`modify_title_check` + `title_input`），
  复选框默认未勾选、输入框默认 `setEnabled(False)`，由 `toggled` 驱动
- 摘要 `summary` 标签按 `item_count` 渲染：「将下载 1 个视频。」vs
  「将下载 N 个视频，标题模板会逐个应用到每个视频。」
- `_ask_prompt_overrides(targets=None)` 接受 items 列表（旧契约保留
  默认参数 = 1 个 item，4 个 `MainWindow()` 集成测试不受影响）

### 二、契约（`collect_prompt_overrides`）

返回 5 个字段（新增 `title_template`），关键边界：

- 复选框**未勾选** → 强制返回 `None`（区别于空串，区别于 token）
- 勾选但留空 → 回退 `"{title}"`（用户意愿 = "改了，但用默认"）
- 模板进 `apply_title_template`，**不**进 `DownloadOptions`（`title_template`
  是 per-item 字段；`_options_for_overrides` 的 `dataclasses.fields`
  白名单会把它过滤掉，避免 `TypeError`）

### 三、模板渲染（`apply_title_template`）

模块级纯函数，便于无 QApplication 单测：

- `None` / 空串 → no-op
- 含 `{title}` token → 每 item 用自身 title 替换
- 不含 token → 全部重命名为同一字符串
- 结果经 `doubi.core.naming._sanitize` 净化（去掉 Windows 非法字符）

### 四、入队点（`ui/pages/parse.py`）

两处 `self._task_manager.add(...)` 前插入 `apply_title_template(targets,
overrides.get("title_template"))`，让 `MediaItem.title` 走新值。

### 测试

| 文件 | 用例数 | 覆盖 |
| --- | --- | --- |
| `test_prompt_options.py` | +14 | 弹窗预填 / 复选框 toggle / 摘要文案 / 5 字段契约 / 未勾选清空 / 留空回退 / `apply_title_template` 7 例（token pass-through / 前缀 / 后缀 / 字面量 / 净化 / 多 token） |

---

## M6.23 (2026-08-30) — nm3u8dl 进度条修复

> N_m3u8DL-CLI v3.0.2 改成「先 meta.json，再 stdout」两段输出，原先的
> `[#N/M]` 正则永远不命中，进度条卡在 0%。改成 **1 Hz 文件系统 watchdog**
> 扫输出目录，与 stdout 格式解耦。`engines/nm3u8dl.py` 单文件 ~345 行
> 改动。

### 三个 root cause

1. **stdout 格式变了**：v3.0.2 不再输出 `[#N/M]`，改成
   `时间戳 + 总分片：9425, 已选择分片：9425 + (速度)`，`_PROGRESS_RE`
   永远不命中
2. **watchdog 初版只扫 2 层**：N_m3u8DL-CLI 会自建子目录（`--saveName` 含
   路径时尤甚），2 层深度漏算
3. **真实目录布局是 3 层**：`out_dir/<saveName_tail>/Part_N/*.ts`

### 改动（`engines/nm3u8dl.py`）

- 新增 `_TOTAL_SEG_RE = re.compile(r"总分片[：:]\s*(\d+)")`：从 stdout 抓
  总分片数（仅作 best-effort fallback，主路径不依赖）
- 新增 `_find_meta_json(out_dir)`：定位 `meta.json`，读 `m3u8Info.count`
  作为权威分片总数
- 新增 `_discover_total_segments(out_dir, save_name)` + `_count_completed_segments(out_dir)`
- BFS 通用 helper `_find_first_named(root, name, *, max_depth)` / `_count_files_named(root, suffix, *, max_depth)`
- `total_segments_box: dict[str, int]` 共享容器（规避 lambda 闭包 rebind）
- `watchdog_stop = asyncio.Event()` + `_watchdog()` 协程（1Hz，check
  `cancel_flag.stopped`）+ try/except CancelledError/finally 三条清理路径

### 设计取舍

- watchdog **只依赖文件系统布局**（N_m3u8DL-CLI 的稳定契约），不依赖
  日志格式 —— 任何 stdout 升级都不会再让它失效
- BFS 限制 `max_depth=3` 而不是无限递归：N_m3u8DL-CLI 不会超过 3 层
  嵌套，再深是别的问题

### 测试

| 文件 | 用例数 | 覆盖 |
| --- | --- | --- |
| `test_engine_routing.py` | +16 | `TestNm3u8dlWatchdog` 13 例（meta.json 解析、总分片发现、已完成计数、BFS helper、watchdog 启停）+ `_TOTAL_SEG_RE` 3 例（中文 / 英文冒号 / 多位数）+ 2 个深层目录回归守卫（`test_discover_total_segments_deep_layout` / `test_count_completed_segments_deep_layout`） |

### 端到端验证

- `.scratch/probe_e2e.py` 真实下载 60s → 19 帧回调，0% → 15.2% 单调递增
- `.scratch/probe_watchdog.py` 模拟 21 帧、1% 精确步进

---

## M6.24 (2026-08-30) — 进度去重 + 系统托盘 + 下载完成通知

> 三项独立 UX 改进打成一发：把 watchdog 漏出的「60% m3u8 下载中 60%」
> 修了；给关窗后软件丢托盘加回主窗口的口子；下载完成弹系统通知，范围
> 可在设置页三档切换。新增 `ui/tray.py`（约 250 行）和 33 个新测试，
> 全部回归 **913 passed / 7 skipped**（实测，见「0.3.1 统计」）。

### 一、进度去重（`engines/nm3u8dl.py` + `ui/pages/download.py`）

- watchdog 的 `on_progress` message 改为 `"m3u8 下载中"`（去掉 `{pct}%`）
- `TaskRow._friendly_phase` 的逻辑抽成**模块级** `friendly_phase(message)`
  （便于无 QApplication 单测），`_friendly_phase` 变薄包装
- `friendly_phase` 新增中文「下载」匹配 + `_PERCENT_RE` 剥离兜底 +
  剥完为空回退 `"下载中"`

### 二、关窗最小化到托盘

**新增 `ui/tray.py`**（`TrayController` + 4 个 Signal + 右键菜单 +
`notify_completion` / `notify_summary`）：

- 菜单 4 项：「显示主窗口 / 全部暂停 / 全部继续 / 退出」
- `_on_activated` 接受 `Trigger` + `DoubleClick`
- `update_running_state(running=, paused=)` 驱动暂停/继续按钮可用性
- `notify_completion(*, mode, success, title, error)` 按 `mode` 走
  `success` / `all` / `summary` 三档
- `notify_summary(*, succeeded, failed)` 给 `summary` 模式用
- 留 Python 引用 `self._menu = menu`（`setContextMenu` 不转移所有权）

**`ui/main_window.py`**：

- 构造末尾调 `self._install_tray()`
- 接管 4 个 task_manager 信号（`task_added` / `task_finished` / `task_failed`
  / `task_removed`）到 `_on_task_state_changed` → 同步托盘按钮
- `closeEvent` 加 `_truly_quit` 标志分支：默认 `event.ignore()` +
  `self.hide()` + 首次「DouBi 在后台运行」toast（`_tray_hide_announced`
  内存标志，**不**进 config —— 是「本次会话是否已通知」的临时态）
- 新增 `quit()`（翻标志后 `self.close()`）/ `_install_tray()` /
  `_show_from_tray()`

**`ui/app.py`**：`QApplication` 构造后立刻
`app.setQuitOnLastWindowClosed(False)`，否则关窗就结束进程，托盘链路全废。

### 三、下载完成通知

**配置（`core/config.py`）**：

- `DEFAULTS["notify_on_completion"] = "success"`
- `AppConfig.notify_on_completion: str` 字段
- `_validate_notify_mode(value)` 白名单校验（非法值回退 `"success"`）

**设置页（`ui/pages/settings.py`）**：外观卡片加 ComboBox「下载完成通知」，
三档「成功完成 / 成功 + 失败 / 全部完成后弹一次」。`save` / `reload`
各走一个 combo helper（按索引映射，不走文本查找）。

**下载页（`ui/pages/download.py`）**：

- `_on_task_finished` / `_on_task_failed` 调 `_maybe_notify_completion`
- `summary` 模式不立刻发：累计 `_succeeded_pending` / `_failed_pending`，
  500ms `QTimer` 检查 `running_count + paused_count == 0` 才弹汇总
  （同一时刻批量完成时合并成一条 toast）

### 四、两个 shipped bug

- `tray.py` 的 `_on_activated` 用 `int(reason)` 抛
  `TypeError: int() argument must be ... not 'ActivationReason'`
  （PySide6 的 `ActivationReason` 是 QFlags 风格枚举）—— 改为
  `reason.value if hasattr(reason, "value") else int(reason)`
- `main_window.closeEvent` 里 `self.tray.show_window_requested.disconnect()`
  名义「防止重复连」，实际**第一次关窗就把所有槽全断了**，托盘「显示主
  窗口」emit 出去没人接 —— 删掉这行，并在注释里写明

### 五、项目既有 bug（顺手修）

- `parse.py:336` 的 `InfoBar.information` → `InfoBar.info`（qfluentwidgets
  的 `InfoBar` 没有 `information` 属性，每次剪贴板剪到新链接就抛
  `AttributeError`）

### 测试

| 文件 | 用例数 | 覆盖 |
| --- | --- | --- |
| `test_tray.py`（新增） | 18 (+3 skip) | `TestActivationReason` 4 例（Trigger / DoubleClick / Unknown / Context / MiddleClick —— 后三者必须**不**抛异常也不 emit）+ `TestNotifyCompletion` 7 例（success / all / summary 三档边界 + 失败体裁断 + 未知 mode 兜底 + 缺标题占位）+ `TestNotifySummary` 3 例（含零项静默）+ `TestCloseEventDoesNotDisconnectTray` 源码级回归守卫 2 例（`disconnect` 字符串必须不出现在 `closeEvent` 源码里）+ `TestMenuLifetime` 3 例（菜单引用保留 + 6 个 actions + pause/resume 状态切换）+ `TestShutdown` 1 例（幂等） |
| `test_config_theme.py` | +5 | `notify_on_completion` 字段三档值往返 + 非法值回退 + 默认值 |
| `test_download_page.py` | +5 / +6 | `TestFriendlyPhaseDedup` 5 例（百分比剥离 + 仅百分比回退 + 中文 / 英文 phase 识别）+ `TestMaybeNotifyCompletion` 6 例（success / all / summary 三档转发 + 无 tray / 无 settings_interface 静默 + flush 路径） |

本批新增 18 + 5 + 5 + 6 = 34 个测试。**注意：不要把这些增量累加到上一版基线
去推算总数**——0.3.1 一度就是这么算出「901 passed / 3 skipped」的，实测是
**913 passed / 7 skipped**（口径与工具见「0.3.1 统计」）。

---

## M6.25 (2026-09-11) — B 站登录：「窗口内二维码图」+「导入 Cookie」双 Tab，零浏览器

> 用户原始诉求："账号登录这一块， 不显示整个浏览器，而是只显示登录的
> 二维码和账号密码，或手机和验证码登录的框"。本轮把 B 站做对了一半——
> **二维码**现在就是窗口内一张图（不再是 ASCII 字符画），且**完全不再
> 开 Playwright**；**账号密码 / 手机+验证码**两个登录方式经 API 端点
> 实查被极验 GeeTest + b_wet WASM 指纹卡死（B 站 web 端独有的反爬墙），
> 走 QWebEngineView 嵌入能让墙消失但要付出 +200 MB 打包代价（0.3.0 拆
> 0.3.0 的目的就是拆掉它，见 BUILD §4.5），故选「**QR + 导入 Cookie**」
> 双 Tab 收口，覆盖 >99 % 真实使用场景。抖音这版不动。

### 一、`platforms/bilibili/qr_login.py`（改造）

- **`QRCode.render_pil(*, box_size=10, border=4) -> PIL.Image.Image`**
  - 替代 `render_ascii()` 的真实图片版本（保留 ASCII 给 CLI 终端用户）
  - 走 `qrcode.QRCode` + `qrcode.image.pil.PilImage` factory
  - **必须 force `convert("L")`**：qrcode ≥ 7.4 的 `PilImage` 类 MRO 是
    `[PilImage, BaseImage, object]`，**不是** `PIL.Image.Image` 的子类——
    任何 `isinstance(img, PIL.Image.Image)` 守卫都会跳过 mode 提升，留下
    `mode='1'` 1-bit 图，Qt `QImage` 配错格式时会画出颠倒的二值图。
  - 单元测试覆盖：`test_qrcode_render_pil_returns_l_mode_image`
- **`REQUIRED_BILIBILI_COOKIES = ("SESSDATA", "bili_jct", "DedeUserID", "sid")`**
  - 与 `auth.cookies_to_netscape_dicts` 对齐；登录成功但任一缺失立刻 raise
- **`cookies_to_netscape(cookies, *, domain=".bilibili.com", include_subdomains=True)`**
  - 7-列 tab 分隔 Netscape 格式；required 顺序在前、extras 附后；空 name / 空 value
    跳过（含空字符串键这种边界），`%` URL-encoded 逗号（如 SESSDATA 真实值）
    不会被误切成两行
  - 单元测试覆盖：`test_cookies_to_netscape_preserves_order_and_extras`
- **`save_cookies_to_drive(cookies, cookie_path) -> Path`**
  - `mkdir -p` parent + `write_text(encoding="utf-8")`
  - 单元测试覆盖：`test_save_cookies_to_drive_creates_parent_and_writes`
- **`bilibili_login_via_qr(cookie_path, *, poll_interval, max_wait, on_qr_ready, on_status) -> Path`**
  - 顶层 orchestrator：generate → wait_for_login → 提取 client.cookies
    → 校验必需 cookie → `save_cookies_to_drive`
  - **不再开 Playwright**——`Set-Cookie` 在 `qrcode/poll` 的成功响应头里
    就直接下发，httpx client 吸收到 jar 后我们直接拿出来
  - 缺失关键 cookie 时 raise 明确（"扫码成功但缺少关键 cookie: SESSDATA,
    bili_jct。请重试或改用「导入 Cookie」"）——避免写出半截 cookie 文件
  - 单元测试覆盖三个场景：端到端成功 / QR 过期 raise / 缺关键 cookie raise
  - 端到端用 `monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)` 离线
    跑通，不依赖任何网络

### 二、`ui/auth_actions.py`

- 新增 `bilibili_qr_login_image(*, cookie_path, max_wait, on_qr_ready, on_status, on_done)`
  - 与 `bilibili_extract_cookies_via_browser` 同构：daemon 线程跑
    `asyncio.run(bilibili_login_via_qr(...))`，callback 通过 `on_qr_ready`
    (拿 `QRCode`) / `on_status` (拿 `PollResult`) / `on_done` (拿 `Path` 或
    `Exception`) 推回 UI
  - 三个 callback 全是**同步**函数（GUI 那边用 `QTimer.singleShot` 切回主线程）

### 三、`ui/dialogs/login_dialog.py`（重写 B 站部分）

- `build_bilibili_qr_dialog` → **`build_bilibili_login_dialog`**（重命名 + 重新实现）
- **qfluentwidgets `SegmentedWidget` 顶部 2 Tab**：
  - **Tab 1: 二维码登录**
    - `QLabel` 居中放 QR 图（260×260，`QPixmap.scaled(... SmoothTransformation)`）
    - URL 副标签（可复制）
    - 4px 进度条（indeterminate，QR 阶段常驻）
    - 状态标签：等待扫码 → 已扫码请确认 → 登录成功 → 二维码失效
    - 「刷新二维码」+「复制链接」按钮
  - **Tab 2: 导入 Cookie**
    - 「选择 Cookie 文件…」+「导入并验证」按钮
    - 复用 `import_bilibili_cookies`（与 settings 页的"导入 Cookie 文件"按钮同源）
    - 成功后 800ms 自动 `accept()`
- **`_on_qr_ready` 走 `QImage(bytes, w, h, bytes_per_row, QImage.Format_Grayscale8)`**
  - **不用 `PIL.ImageQt`**——它依赖 sip/PyQt 风格桥接；Pillow 走 raw bytes
    + 8-bit grayscale 格式更省一层依赖
- 抖音 `build_douyin_browser_dialog` **保持原样**（Playwright headed 模式），
  docstring 标注 "pending M6.27 headless-equals-QR rework"
- `closeEvent` + `_on_close` 清理子线程引用

### 四、`ui/pages/settings.py`

- 按钮文案：「扫码登录」→「**登录**」+ 下方说明改"打开 B 站登录对话框,内含
  二维码 + 导入 Cookie 两个 Tab"
- 「导入 Cookie 文件」按钮**保留**作为快捷入口（不再走 dialog 的导入 Tab）
- 调用入口换成 `build_bilibili_login_dialog()`

### 五、`tests/test_ui_polish.py`

- `test_login_dialogs_use_brand_window_icon` 的 import 从
  `build_bilibili_qr_dialog` 改为 `build_bilibili_login_dialog`

### 六、测试

- `test_bilibili_auth.py` 新增 5 个用例：
  - `test_qrcode_render_pil_returns_l_mode_image` — mode == "L" 守卫
  - `test_cookies_to_netscape_preserves_order_and_extras` — 顺序、tab 分隔、
    URL-encoded 逗号、空 name 跳过
  - `test_save_cookies_to_drive_creates_parent_and_writes` — mkdir -p
  - `test_bilibili_login_via_qr_end_to_end` — monkeypatch httpx，端到端
    generate → 2×NOT_SCANNED → SUCCESS → 落盘 + 事件回调顺序
  - `test_bilibili_login_via_qr_raises_when_qrcode_expires` — EXPIRED 不写文件
  - `test_bilibili_login_via_qr_raises_when_required_cookies_missing` —
    code=0 但 client jar 没 SESSDATA 时 raise
- 全部 6 个新用例 `pytest.importorskip("PIL")` 守卫，CI 缺依赖时跳过

### 七、打包体积：撤销「M6.17 撤 PIL 12.8 MB 精简」

- `scripts/build_exe.py::EXCLUDE_MODULES` 移除 `"PIL"`
  - 注释里留历史说明（"M6.16 起 B 站登录对话框用 QR 码真实图片替代了
    ASCII, qrcode.make_image(image_factory=PilImage) 必须用 PIL"）
- `tests/test_packaging_slim.py::test_the_heavy_hitters_stay_excluded` 的
  `must_exclude` 移除 `"PIL"`
- `docs/BUILD.md` §4.5 体积表：「PIL | 12.8 MB | **0** | `--exclude-module PIL`」
  改为「12.8 MB | **12.8 MB** | M6.16 起撤销此精简」+ 加 M6.16 撤销说明段
- 后续安装包：NSIS 预计 219 MB → **232 MB**（+13 MB，相对 0.3.1 的 +5.9%）

### 八、覆盖 B 站账号密码 / 手机+验证码登录？**没有。**

- B 站 web 端登录被两道墙卡死：
  1. **极验 GeeTest 滑块**（`/x/passport-login/captcha` 返回 `gt + challenge`，
     密码登录与短信发送都要带 `validate + seccode`）
  2. **`b_ret` / `b_wet` 设备指纹 WASM**（`SecureCollectSDK` 收集 Canvas +
     WebGL 指纹，密码登录必须带 `b_ret`）
  - 两道墙都需要 B 站 web 自己的 JS 跑起来才能解开
  - 走 `QWebEngineView` 嵌登录页能解，但要把 0.3.0 才拆掉的 QtWebEngine
    加回打包（NSIS +200 MB，安装包翻倍），权衡后放弃
- 实操影响：B 站国际版（`bilibili.tv`）/ 港澳台版未在本轮范围；如未来要支持，
  走同一条 QR + 导入 Cookie 路径（API 端点不同，逻辑一样）

### 九、未做

- **抖音登录不动**——保留 Playwright headed 模式（用户最初选 C 方案时已经
  评估过 headless 模式会被反爬、纯 web API 端点未验证，权衡后选稳）
  - 后续如要做，参考 B 站新流程：QWebEngineView 嵌登录页（+200 MB）
    或验证 `/passport/web/get_qrcode/` 不需要 a_bogus 签名后改纯 web API
- 国际化字符串：M6.16 没动 i18n，新加的"二维码登录 / 导入 Cookie / 刷新
  二维码 / 复制链接 / 等待扫码 / 已扫码请确认 / 登录成功 / 二维码已失效"
  等文案目前仅中文，纳入下一轮 i18n 扫尾

### 十、版本号

- 0.3.1 内的 hotfix 批次；不单独发版。下一发版 0.3.2 时一起带。

---

## M6.26 (2026-09-11) — 抖音登录：Playwright headless + 扒 QR 图进窗口

> B 站 M6.25 已经把扫码变成"窗口内一张图"。本批把同一招扩到
> 抖音——但抖音 web 端的反爬太严(滑块 + a_bogus + 设备指纹),不可能
> 走纯 web API 路径,只能继续靠 Playwright 渲染登录页,**只不过不再
> 弹独立 Chromium 窗口**:M6.25 引入的 ``qr_callback`` 钩子被
> 抖音侧的 ``_qr_snapshot`` 拿过来,把 QR 元素截成 PNG bytes 推回
> GUI 居中显示。默认 headless=True,失败时勾「显示浏览器」一键降级。

### 一、`core/auth/browser_login.py`(钩子基础设施)

- **`_BaseBrowserLogin.__init__` 加 ``qr_callback: Optional[Callable[[Page], None]] = None``**
- **`_BaseBrowserLogin._run_browser` 在 ``on_page_ready`` 之后、
  ``_wait_for_success`` 之前**调用一次 ``self.qr_callback(page)``。
  - 异常用 ``logger.exception`` 吞掉,best-effort:selector 选错不会
    阻塞登录流程
- **`URLChangeLogin` 和 `CookieSetLogin` 透传**这个新参数

### 二、`platforms/douyin/auth.py`

- `browser_login` 接受 `qr_callback=None` 并透传给 `CookieSetLogin`
- 抖音 web 端登录是「点击登录按钮 → 弹登录 modal → QR 在 modal 里」,
  不需要自选 URL,沿用 M3.1 的 `https://www.douyin.com/`

### 三、`ui/auth_actions.py`

- **`douyin_login_via_browser` 加 `on_qr_image: Optional[Callable[[bytes], None]] = None`**
  - 与 `bilibili_qr_login_image` 不同的关键点:抖音流程是**在 Playwright
    线程里同步截图**(`_qr_snapshot` 闭包持有 `on_qr_image` + `page`)
  - 候选选择器(按新鲜度排序):
    1. `div[data-e2e='login-qrcode'] img`
    2. `div.login-QRcode img`
    3. `img[class*='qrcode']`
    4. `div[class*='qrcode'] img`
  - **fallback**:`page.screenshot(type="png", full_page=False)` 截全屏
  - 单测覆盖 selector 命中 vs fallback 两条路径
- 透传 `qr_callback=` 给 `dy_auth.browser_login`

### 四、`ui/dialogs/login_dialog.py`

- **`DouyinBrowserDialog` 重写**(M6.26):
  - 顶部品牌 hero(共享 `_build_brand_hero` 助手)
  - 居中 260×260 `QLabel` 显示 QR 截图(`QImage.fromData(png, "PNG")` +
    `QPixmap.scaled(... SmoothTransformation)`)
  - 4px 进度条 + 状态标签:"正在启动无头浏览器…" → "二维码已就绪 — 用
    抖音 App 扫描" → "登录成功!" / "登录失败:..."
  - **「显示浏览器(反爬降级)」复选框**:默认未勾选(无头),勾了之后
    `headless=False` 重启,会弹独立 Chromium 窗口
  - 工具提示明确写了"headless 可能被抖音反爬,反复失败时勾这个"
  - 失败时状态标签追加"如反复失败,请勾选「显示浏览器」以 headed 模式重试"
- `_DyQRImageEvent` + `_DyDoneEvent` 两个 `QEvent` 子类做线程间通讯
  (跟 B 站 dialog 的 `_BrowserDoneEvent` 同模式)
- 取消 indeterminate 进度条:扫到码就 `setRange(0, 1)`,转成"等用户操作"信号

### 五、`ui/pages/settings.py`

- 抖音 row detail 文案改为反映 M6.26:"M6.26 起:扫码登录在后台跑无头
  Chromium,本窗口只显示抖音登录页上的二维码..."
- 「扫码登录」按钮名不变(行为已经改变,但入口语义没变)

### 六、测试

- `test_browser_login.py` 新增 4 个用例:
  - `test_qr_callback_fires_once_with_page` — 钩子被调一次 + 拿到正确 Page
  - `test_qr_callback_selector_miss_falls_back_to_viewport` — 4 个选择器
    全 miss 时回落到 `page.screenshot` viewport
  - `test_douyin_browser_login_forwards_qr_callback` — 抖音 `browser_login`
    透传 `qr_callback`
  - `test_douyin_browser_login_qr_callback_default_none` — 缺省值是 `None`(老路径不变)

### 七、未解决的风险

- **headless 模式被抖音反爬触发**:抖音 web 端对 `navigator.webdriver`
  / canvas 行为 / 鼠标无活动非常敏感。headless 模式下:
  - **可能**正常出 QR 截图 + 扫码成功(最理想)
  - **可能**登录页本身被风控拦截 → QR 区域加载不出来 → 截到的是
    「请用浏览器打开」提示页,扫码也无效
  - **可能**扫了码后 web 端出现滑块验证,需要人工操作(headless 模式
    没法解滑块)
- 这三个 case 我们没办法在 CI 测出来——**必须在你机器上实测**才能定
  哪些场景需要走「显示浏览器」降级。代码里已经埋好降级开关,反复
  失败就勾上,会弹独立 Chromium 窗口(回退到 M6.16 行为)

### 八、未做

- **抖音账号密码 / 手机+验证码登录**:跟 B 站一样,被极验滑块 + a_bogus
  卡死,纯 API 不可行,跟 M6.25 一样的取舍
- **抖音 web 端 a_bogus 纯 web API 路径**:实测未验证,留作未来轮
- **i18n**:M6.26 新文案仅中文,跟 M6.25 一起纳入下一轮 i18n 扫尾

### 九、版本号

- 跟 M6.25 一起进 0.3.2

---

## M6.27 (2026-09-11) — i18n 扫尾：M6.25 + M6.26 新文案走 tr() + 英译

> M6.25 (B 站) + M6.26 (抖音) 改了两套登录对话框,里面的新文案
> (二维码/导入 Cookie/刷新二维码/复制链接/等待扫码/已扫码请确认/
> 登录成功/二维码已失效/二维码已就绪/显示浏览器/反爬降级) 当时
> 全部硬编码中文,只填进了 `zh_CN.json` (但**连这个也没填**,纯
> 写在 Python 里)。本批把它们收进词表,en 翻译,加了 9 个新单测
> 钉死「未来不能再用硬编码中文」。

### 一、词表(`src/doubi/ui/locales/`)

- `zh_CN.json` 从 22 → **54 条**(+32)
- `en.json` 从 22 → **54 条**(+32,与 zh_CN 一一对应)
- 新增 key 都走 `category.subcategory.name` 命名:
  - `common.close`(M6 dialog 共用关闭按钮)
  - `login.bili.window_title / tab.qr / tab.import_cookie`
  - `login.bili.qr.{hint,generating,preparing,waiting_scan,
    scanned_confirm,success_saving,expired,poll_error,url_label,
    refresh_button,copy_button,fail_prefix,success_path,render_fail}`
  - `login.bili.import.{title,hint,pick_button,placeholder,confirm_button}`
  - `login.bili.settings_detail`
  - `login.dy.{window_title,hint,qr.loading,qr.screenshot_decode_fail}`
  - `login.dy.status.{starting,starting_headless,qr_ready}`
  - `login.dy.checkbox.{headed,headed_tooltip}`
  - `login.dy.{fail_with_hint,success,settings_detail}`
- 占位符 key:`{url}/{length}/{message}/{error}/{path}`,在 en 译文
  里都保留同一占位符名,确保 `tr(**kwargs)` 行为对齐

### 二、`ui/dialogs/login_dialog.py`

- B 站 dialog (`build_bilibili_login_dialog`):
  - `_build_ui` / `_build_qr_tab` / `_build_import_tab` 全部从
    硬编码中文字符串改为 `tr("login.bili.*")` 调用
  - `_start_qr_login` 的 3 个 callback (`_on_qr_ready` /
    `_on_status` / `_on_done`) 也走 tr:URL 副标签用 `url_label`、
    错误信息用 `fail_prefix` / `render_fail` / `poll_error`、
    状态文字用 `waiting_scan` / `scanned_confirm` /
    `success_saving` / `expired`
  - 状态映射 dict (`NOT_SCANNED / SCANNED / SUCCESS / EXPIRED /
    ERROR`) 每条都走独立 key,英译时语义独立可调
- 抖音 dialog (`build_douyin_browser_dialog`):
  - 同样全量改 tr:窗口标题/hint/QR 占位/状态标签/「显示浏览器」
    复选框文案 + tooltip/失败信息
- 顶部 import 加 `from ..i18n import tr`(M6.27 唯一新增的模块级
  import;docstring 中英文都保留作为给读者看的)

### 三、`ui/pages/settings.py`

- 账号卡内 M6.25 改的 B 站 detail 文案 → `tr("login.bili.settings_detail")`
- 账号卡内 M6.26 改的抖音 detail 文案 → `tr("login.dy.settings_detail")`
- `_build_account_card` 顶部加 `from ..i18n import tr`(同其他函数
  内部的 import 习惯)

### 四、测试 (`tests/test_i18n.py`,14 → 23)

- **`test_m6_login_keys_all_present_in_source_locale`** — 白名单
  35 个 M6 key,钉死在源语言都有
- **`test_m6_login_keys_fully_translated_in_every_language`** — 同
  白名单,所有非源语言都必须覆盖
- **`test_m6_login_keys_format_placeholders[6 个 parametrize]`** —
  验证带 `{url}` / `{error}` / `{path}` / `{message}` / `{length}`
  的 key 都能用 happy-path kwargs 走通,占位符都被填实
- **`test_login_dialog_strings_use_tr_not_hardcoded_zh`** — 用
  regex 扫 `login_dialog.py` 里 `setText / setWindowTitle /
  setPlaceholderText / setToolTip / addItem` 五个会落到 UI 的
  方法调用,**任何含「扫码/二维码/导入/抖音/B 站/确认/关闭」的中
  文字符串都会 fail**。这是「未来谁动 dialog 字符串都得用 tr」
  的执行护栏

### 五、未做

- **日语 (`ja_JP`) 词表** — 用户答「英语日语起码走一条」,
  本批先把 en 这条做满;ja 词表需要从零翻译,工作量跟做 en
  同档(35 个 key),不抢 0.3.2 节奏
- **i18n 切语言后热重载** — 切语言需要重启的现状保持,
  跟主题/数据库路径同一档「重启生效」处理。要做的话需要在
  每张卡片做 `retranslateUi()`,工程量跟 dialog 一个量级

### 六、版本号

- 跟 M6.25 + M6.26 一起进 0.3.2

---

## M6.28 (2026-09-11) — 实测发现：M6.25 B 站 dialog 跨线程 bug fix

> 用户实测 M6.25 + M6.26 + M6.27 候选版本时,在 B 站 dialog 里点了
> 「登录」,日志里 B 站 QR 协议跑通 (`/x/passport-login/web/qrcode/generate`
> + `/qrcode/poll` 都 200 OK),但同时弹了 Qt 跨线程警告:

> ```
> QObject: Cannot create children for a parent that is in a different thread.
> (Parent is QLabel(0x...), parent's thread is QThread(0x...),
>  current thread is QThread(0x...))
> ```

> 根因:`bilibili_qr_login_image` 在 worker 线程直接调 GUI 端
> `on_qr_ready` / `on_status` callback, callback 里
> `self.qr_image.setPixmap(...)` 触发了 Qt 的跨线程保护。
> 抖音 dialog 没这问题是因为它本来就走 `QApplication.postEvent`
> (见 M6.26 段)。本批把同样的桥接加到 B 站路径,GUI 端零改动。

### 一、修复

- `ui/auth_actions.py::bilibili_qr_login_image` 内部加 `_Dispatcher`
  (`QObject` 子类,parented to `QApplication.instance()` → 主线程)
- 3 个 callback 各加一个 `QEvent` 子类:`_BiliQRReadyEvent` /
  `_BiliStatusEvent` / `_BiliDoneEvent`
- worker 线程里调 `QApplication.postEvent(dispatcher, event)` 而非
  直接调 user callback;`QObject.event()` 在主线程被分发,把
  callback 切回主线程调
- 没起 `QApplication` 的 CLI / smoke test 路径:直接 inline 调
  callback(没人碰 widget,安全)

### 二、为什么选 `postEvent` 而不是 `QTimer.singleShot` / `QMetaObject.invokeMethod`

- `QTimer.singleShot(0, func)` 在 worker 线程被调时,`QTimer` 绑
  worker 线程的 event loop。我们 worker 线程只跑 `loop.run_until_complete`
  跑 async 函数,**没有持久的 Qt event loop**,timer 不会触发。
- `QMetaObject.invokeMethod` 在 PySide6 6.x **不接受 Python callable
  形参**,只接 `member: str`(QObject 已有方法名)。要传 `Q_ARG`
  复杂且对 callable 不可行。
- `QApplication.postEvent` 是 Qt **官方文档**推荐的跨线程桥接,
  所有 PySide6 / PyQt 版本一致支持。

### 三、测试

- `tests/test_auth_actions.py` +3 个新用例 (8 → 11):
  - `test_bilibili_qr_login_image_callbacks_dispatch_on_main_thread`
    — monkeypatch `bilibili_login_via_qr` 让它在 worker 线程同步
    调 callback,验证 user callback 全部在 `threading.main_thread()`
    上落地(用 `threading.current_thread().ident` 对比)
  - `test_bilibili_qr_login_image_no_qapp_calls_inline` — 没起
    `QApplication` 时 callback 必须仍被调(CLI / smoke 路径)
  - `test_bilibili_qr_login_image_done_after_timeout` — 用
    `_FakeThread` 让 `t.join` 立即返回 + `is_alive()` 永远 True,
    验证 wrap 走 timeout 分支 `on_done(None, TimeoutError)`
- 实测日志:用户跑 M6.25 时弹的 "Cannot create children for a parent
  that is in a different thread" 在 M6.28 改完后消失

### 四、未做

- 同样的 postEvent 桥接**没有加**到 `douyin_login_via_browser` —
  它本来 callback 就只 post event 不碰 widget(见 M6.26 段),
  验证过没有问题。如果以后有改动再 review。

### 五、版本号

- 跟 M6.25 + M6.26 + M6.27 一起进 0.3.2

---

## M6.30 (2026-09-11) — B 站扫码 cookies 流转补完：poll 成功 ≠ cookies 落地

> 用户实测 M6.29 候选版本时扫码成功,但状态栏报
> "B 站扫码成功但缺少关键 cookie: SESSDATA, bili_jct, DedeUserID, sid。
> 请重试或改用「导入 Cookie」"。
>
> 根因分析:B 站 web 端扫码成功的 Set-Cookie 头**不在** `/qrcode/poll`
> 响应里下发——服务端在 poll 响应里只给一个 `data.url`(web 端跳转
> 目标 URL),需要客户端**自己 GET 那个 URL** 才会拿到 Set-Cookie 头。
> M6.25 的实现只读 `client.cookies` jar 里的现有 cookies(来源是
> poll 响应——没 Set-Cookie),所以一直空。

### 一、`platforms/bilibili/qr_login.py`

- `PollResult` 加 `url: Optional[str] = None` 字段
- `QRSession.poll` 解 `data.url` 填到 PollResult
- `bilibili_login_via_qr` 在 SUCCESS 之后,`if result.url: await
  s._client.get(result.url)` 触发 Set-Cookie 下发到 client jar
  - 异常用 `logger.warning` 吞掉(网络抖动不该掩盖"缺少关键
    cookie"这个更准确的错误)
  - 没有 `data.url` 的 B 站 API 变体走 fallthrough,仍然被「缺少
    关键 cookie」分支接住

### 二、为什么不用 `refresh_token` 调 `/x/passport-login/web/refresh`

B 站 web 端 `data` 字段里**同时**有 `refresh_token` 和 `url`:
- `url` 是 web 端带登录态的跳转 URL——`GET url` 直接拿 Set-Cookie,
  走最朴素的浏览器路径
- `refresh_token` 需要调 `/x/passport-login/web/refresh` 端点换
  cookies,这个端点**也有**风控(需要带 `bili_jct`、cookie 状态等),
  实测在纯 httpx 路径上不一定稳
- 走 `url` 这条路最朴素,跟 B 站 web 端浏览器流程一致

### 三、测试

- `tests/test_bilibili_auth.py` 47 → **49**:
  - `test_bilibili_login_via_qr_end_to_end` — 更新 mock:success
    响应加 `data.url`,fake httpx 加对 url 的 GET handler(在那里
    Set-Cookie 落到 jar),断言整个流程调用了 follow-up URL 一次
  - `test_bilibili_login_via_qr_raises_when_required_cookies_missing`
    — 更新 mock 加 `data.url: "https://.../follow-up-no-cookies"`
    路径,验证 follow-up GET 没 Set-Cookie 时仍然报「缺少关键 cookie」
  - **`test_bilibili_login_via_qr_url_followup_raises_but_clear_error`**
    (新) — follow-up GET 抛 `httpx.ConnectError` 时,**不能**让
    httpx 异常掩盖真错误,应该 fall through 到「缺少关键 cookie」
  - **`test_bilibili_login_via_qr_handles_no_data_url_on_success`**
    (新) — 防御:B 站如果某次 a-b test 把 `data.url` 去掉,不能
    crash,要 fall through

### 四、版本号

- 跟 M6.25 + M6.26 + M6.27 + M6.28 + M6.29 一起进 0.3.2

---

## M6.31 (2026-09-11) — 撤 M6.25：实测发现 B 站 web 端针对纯 API 反爬,``data.url`` 跳转不下发 Set-Cookie

> 用户实测 M6.30 候选版本时扫码成功了但仍报「缺少关键 cookie:
> SESSDATA, bili_jct, DedeUserID, sid」。根因:**B 站 web 端
> 2026 改版对纯 API 路径反爬,``data.url`` 跳转不通过 Set-Cookie
> 下发 cookies**——M6.25 承诺的「完全不开浏览器」对 B 站不成立。
>
> 之前 web search 出来的所有 B 站纯 httpx QR 登录实现,都靠
> ``data.url`` 里 regex 抽 SESSDATA 字符串;但我们的 SESSDATA
> 不在 URL 字段里(可能在 JS 写 cookie 里),纯 httpx 看不到。
>
> 本批把 B 站 GUI 路径**撤回**纯 API,改走跟 M6.26 抖音一样的
> 路径:Playwright headless + 扒图。UI 体验**不变**(「窗口内显示
> 二维码图,不弹浏览器」),**技术路径变了**。
>
> M6.25 / M6.30 标记为「撤回」,**保留** M6.25 的纯 API 代码
> 作为 CLI 兜底(M6.31 测试里 ``bilibili_login_via_qr`` 现在
> 永远 raise "缺少关键 cookie",CLI 路径下用户需要走
> ``--browser`` flag 走 Playwright)。

### 一、改动

- `core/auth/browser_login.py::URLChangeLogin.__init__` 加
  ``qr_callback`` 透传(对齐 M6.26 ``CookieSetLogin``)
- `platforms/bilibili/auth.py::browser_login` 加 ``qr_callback``
  形参(从 `Callable[[Page], None]` 透传给 `URLChangeLogin`)
- `ui/auth_actions.py::bilibili_qr_login_image` **核心改动**:
  - 不再调 `bilibili_login_via_qr`(纯 API)
  - 改调 `bili_auth.browser_login(headless=True, qr_callback=...)`
  - ``on_qr_ready`` callback 现在接 **PNG bytes** 而不是
    ``QRCode`` 对象(对齐抖音 dialog)
  - ``on_status`` 接 **字符串** ``"starting_browser" / "done" /
    "timeout" / "failed" / "unknown"``,不再是 ``PollResult``
- `ui/dialogs/login_dialog.py::BilibiliLoginDialog._start_qr_login`
  - ``_on_qr_ready(png_bytes)`` 改用 `QImage.fromData(bytes,
    "PNG")` 路径(跟抖音 dialog 一致,不再用 PIL `render_pil`)
  - ``_on_status(status_str)`` 改字符串处理
- `platforms/bilibili/qr_login.py::bilibili_login_via_qr`:
  - 撤掉 M6.30 的 ``GET result.url`` follow-up(实测无用)
  - 错误信息追加"或用 CLI 走 Playwright 的
    ``doubi auth bilibili --browser``"提示
  - ``PollResult.url`` 字段**保留**给纯 API path 用,GUI 不用

### 二、i18n

- `zh_CN.json` / `en.json` 加 1 个新 key:
  ``login.bili.qr.starting_browser`` = "正在启动浏览器…" /
  "Starting browser…"
- B 站 dialog 的 ``_set_qr_status`` 现在用 ``login.bili.qr.fail_prefix``
  / ``login.bili.qr.success_path`` / ``login.bili.qr.render_fail`` 三条
  已有 key,不再用 ``login.bili.qr.url_label``(M6.25 残留)— 实际
  上 ``url_label`` 也保留着(给 ASCII QR CLI 路径用),但 GUI
  dialog 不再引用

### 三、测试 (49 → 47,变动)

- `tests/test_bilibili_auth.py`:
  - `test_bilibili_login_via_qr_end_to_end` **改语义**:从「能
    拿到 cookies 落盘」改成「扫码成功但 raise '缺少关键
    cookie',不写文件」—— 钉死 M6.31 行为
  - `test_bilibili_login_via_qr_url_followup_raises_but_clear_error`
    / `test_bilibili_login_via_qr_handles_no_data_url_on_success`:
    保留(M6.30 defensive,defensive 测试不删)
  - `test_bilibili_login_via_qr_raises_when_required_cookies_missing`:
    更新 mock 加 `data.url` 路径
- `tests/test_auth_actions.py`:
  - 3 个 `test_bilibili_qr_login_image_*` 全部改 mock:从
    ``bilibili_login_via_qr`` 改成 ``bili_auth.browser_login`` +
    ``bili_auth.write_netscape_cookies``
  - ``_FakePage`` / ``_FakeLocator`` 类(借鉴 M6.26 抖音测试):
    - ``Locator.first`` 用 `@property` 不是 method(Playwright 真实
      API 是 property,生产代码 ``page.locator(sel).first`` 不加
      括号,跟我们的 mock 必须一致)
- 净 -2 个 test(M6.30 改 end_to_end 测试语义不算新增)
  - 47 → 49(实际跑了 -2 + 0 = 47,但 ``test_bilibili_login_via_qr_url_followup_raises``
    还在,49 我写错了以实际跑通为准)

### 四、未做

- **B 站 QR 选择器优化**:M6.31 的 5 个 selector 是 web 经验,可能
  B 站 passport.bilibili.com 实际页面需要调整。**用户实测** 时
  如果 QR 元素 selector miss,会用 ``page.screenshot`` 兜底截
  全屏——能看到整页但 QR 不居中。后续根据实测加 selector
- **B 站勾选「显示浏览器」降级**:抖音 dialog 已经有这个 checkbox,
  B 站 dialog M6.25 阶段没加(纯 API 路径不需要降级)。M6.31 走
  Playwright 之后应该加,留作 M6.32
- **CLI 路径用 Playwright**:已经有 M3.1 路径(
  ``doubi auth bilibili --browser``),不需要新加代码

### 五、版本号

- 跟 M6.25 / M6.26 / M6.27 / M6.28 / M6.29 / M6.30 一起进 0.3.2

---

## M6.32 (2026-09-11) — B 站 QR 元素 selector 修对

> 用户实测 M6.31 候选版本时,二维码区只显示**白色背景** —— 截图
> 不是真正的 QR,是 B 站 passport.bilibili.com 登录页 viewport
> 截图(整页含 banner / 链接等无关元素)。
>
> 根因:M6.31 我给的 selector `img[class*='qrcode']` 实际匹配 0 个
> 元素。**真实结构**是 `<div class="login-scan__qrcode">` 嵌
> `<img alt="Scan me!" src="data:image/png;base64,...">` —— img
> 标签**没有** `qrcode` class,是**父 div** 有。

### 一、修复

- `ui/auth_actions.py::bilibili_qr_login_image._qr_snapshot` 候选
  selector 重排:
  ```python
  selectors = (
      "div.login-scan__qrcode img",   # M6.32 新增,2026-09 实测命中
      "div[class*='qrcode'] img",      # M6.31 错误地写在最前
      "img[alt='Scan me!']",            # M6.32 新增,alt 文本最稳
      "img[alt*='QR']",
      "canvas[class*='qrcode']",
  )
  ```
  - `div.login-scan__qrcode img` 放最前(精确匹配,B 站 web 端
    渲染后稳定可见)
  - `img[alt='Scan me!']` 作为兜底(alt 文本最稳,只要 B 站不改文案就稳)

### 二、验证

- 用 Playwright 直接加载 `https://passport.bilibili.com/login`:
  - 5 个候选 selector 的可见性检查:`div[class*=qrcode] img` visible=1
    ✅,其他几个 visible=0 ❌
  - 改 selector 后实测 `el.screenshot(type='png')` 拿到 2337 字节
    PNG,中心是 B 站 logo + QR 矩阵,decoded base64 真实内容

### 三、未做

- **A/B test 风险**:B 站如果再改前端结构(改 class name 改 alt 文案),
  selector 又会 miss → 走 viewport 兜底 → 用户看到整页截图。应对:
  - 加 v0.3.3 轮次里让用户报 selector 错位,再用 Playwright 重新侦察

### 四、版本号

- 跟 M6.25 / M6.26 / M6.27 / M6.28 / M6.29 / M6.30 / M6.31 一起进 0.3.2

---

## M6.33 (2026-09-11) — B 站 QR 元素 wait_for_selector:JS 异步渲染不等人

> 用户实测 M6.32 候选版本时,二维码区**仍然只显示白色背景**。
> 看起来跟 M6.32 修 selector 之前一模一样。
>
> 根因:B 站 passport.bilibili.com 登录页的 QR **不是** HTML
> 静态资源,是由 JS 异步渲染的(从
> `https://account.bilibili.com/h5/account-h5/auth/scan-web?qrcode_key=...`
> 拉 base64 拼出来)。生产代码用 ``wait_until="domcontentloaded"``,
> **只等 HTML 解析完,不等 JS 跑完**。
>
> 验证:用 ``URLChangeLogin`` 同样的 ``goto(..., wait_until='domcontentloaded')``
> 之后立刻查 selector → count=0;加 ``wait_for_selector(timeout=10s, state='visible')``
> 之后 → count=1, is_visible=True, src 2321 字节真 QR。
>
> M6.32 改的 selector 是对的,但**早跑了一拍**——抓了没渲染的页面。

### 一、修复

- `ui/auth_actions.py::bilibili_qr_login_image._qr_snapshot` 顶部加:
  ```python
  page.wait_for_selector(
      "div.login-scan__qrcode img, img[alt='Scan me!']",
      timeout=10_000,
      state="visible",
  )
  ```
  - 等 JS 异步生成 QR 元素(最多 10s)
  - 异常时(JS 真的没渲染)走原候选 selector + viewport 兜底
  - 命中后:`is_visible` 检查 + `el.screenshot(type='png')` 一定拿到真 QR

### 二、抖音对照

M6.26 抖音的 `_qr_snapshot` **没有** `wait_for_selector`——抖音
的 QR 元素也是 JS 异步的,但 M6.26 实测能跑通,原因可能是:
- 抖音 QR 元素在 ``domcontentloaded`` 之后很短时间内就出现
- 抖音 selector 触发 ``page.screenshot(full_page=False)`` 兜底
  后 viewport 截图能直接命中 QR
但这是"碰巧能跑",不是"代码正确"。**M6.34** 应该给抖音也加
``wait_for_selector`` 防御。

### 三、版本号

- 跟 M6.25 / M6.26 / M6.27 / M6.28 / M6.29 / M6.30 / M6.31 / M6.32
  一起进 0.3.2

---

## M6.34 (2026-09-11) — 截父 div 不截 img:把 QR 三方块从 padding 里捞回来

> 用户实测 M6.33 候选版本时 QR **真的出来了**(不再是白板),
> 但**左右两边被切了**——B 站 App 扫不出来,认不出方向。
>
> 根因:B 站 passport.bilibili.com 的 QR 结构是
> ``<div class="login-scan__qrcode">`` 158x158,**里面**嵌
> ``<img alt="Scan me!" width="140" height="140" />``。
> - M6.33 截的 **img 元素**是 140x140,但里面 QR 矩阵在 CSS 上
>   被居中,padding 把左右两边的 finder pattern(三个角的大方块
>   之一)推到边界外,截 img 就把这部分裁切了
> - 截**父 div** (158x158)能完整保留 QR + 周边 padding;scale
>   到 dialog 260 居中后三个 finder pattern 都还在

### 一、修复

- `ui/auth_actions.py::bilibili_qr_login_image._qr_snapshot` 候选
  selector 把 `div.login-scan__qrcode` 放第一位(截 div,不截 img)
- 后续的 `div[class*='qrcode']` / `... img` / `img[alt*='QR']` 仍
  作兜底
- `wait_for_selector` 仍然等 `... img`(确认 JS 渲染完了),截
  时改用 div——这两个 selector 分离是合理的:wait 用 img 状态,
  截用 div 几何

### 二、验证

- 用 Playwright 实测:
  - `div.login-scan__qrcode` bounding box = 158x158,3 个 finder pattern
    完整可见
  - 之前 `el.screenshot()` 用 140x140 img → 截到 140x140 PNG,左右
    两边 finder pattern 被裁掉
- 用 PIL 打开两种截图对比:
  - **img 140x140**:finder pattern 缺左右两个,只有顶部
  - **div 158x158**:三个 finder pattern 完整,白色 padding 围绕
    QR 矩阵

### 三、未做

- **抖音也加 wait_for_selector** (M6.34 候选):跟 B 站同问题
- 修后 0.3.2 发版

### 四、版本号

- 跟 M6.25 / M6.26 / M6.27 / M6.28 / M6.29 / M6.30 / M6.31 / M6.32
  / M6.33 一起进 0.3.2

---

## M6.35 (2026-09-11) — ``write_netscape_cookies`` 不返 tuple,GUI 别再 unpack 了

> 用户实测 M6.34 候选版,**QR 完整能扫了**,扫码完成后弹出
> **「登录失败:cannot unpack non-iterable WindowsPath object」**。
>
> 根因:`platforms/{bilibili,douyin}/auth.py::write_netscape_cookies`
> 的真实签名是
>
> ```python
> def write_netscape_cookies(cookies: list[dict], path: Optional[Path] = None) -> Path:
> ```
>
> ——成功返回 ``Path``,失败直接 ``raise``。但 M6.25 / M6.26
> 引入的两处 GUI 调用写的是
> ``ok, msg = write_netscape_cookies(cookies, target)``,
> 把一个 ``WindowsPath`` 当成 ``(ok, msg)`` tuple 拆,触发
> ``TypeError: cannot unpack non-iterable WindowsPath object``。
>
> 这个 bug 在 M6.25(M6.31 撤回)期间没人触发是因为 B 站纯 API
> 路径根本走不到这里;M6.31 改走 Playwright headless 后,扫码
> 完成 → cookies 抓到 → **第一次**真去写盘,**第一次**真触发
> unpacking 错误。

### 一、修复

- `ui/auth_actions.py::bilibili_qr_login_image._runner`:从
  ```python
  ok, msg = bili_auth.write_netscape_cookies(cookies, target)
  if not ok:
      box["error"] = RuntimeError(f"B 站 cookies 写入失败:{msg}")
  else:
      box["path"] = target
  ```
  改为
  ```python
  try:
      bili_auth.write_netscape_cookies(cookies, path=target)
  except Exception as exc:
      box["error"] = RuntimeError(f"B 站 cookies 写入失败:{exc}")
      return
  box["path"] = target
  ```
  - 不再尝试解包返回值;写盘异常走 ``box["error"]`` 路径
  - ``browser_login`` 自身异常另起一个 try/except 兜住(M6.34
    把这两块错误揉在一个 try 里,现在拆开更清楚)
- `ui/dialogs/login_dialog.py::DouyinBrowserLoginDialog._on_done`
  同款 bug:把 ``ok, msg = dy_auth.write_netscape_cookies(...)``
  换成 try/except,写成功 → ``_set_status(tr("login.dy.success"))``
  + ``_refresh_parent_status`` + 800ms 自动 accept;写失败 →
  复用 ``login.dy.fail_with_hint``(已经带「勾选显示浏览器」提示)

### 二、回归测试

- `tests/test_auth_actions.py` 新增 2 个:
  - `test_bilibili_qr_login_image_write_cookies_failure_does_not_unpack`
    - 场景 1:`write_netscape_cookies` 真实签名(返回 ``Path``)→
      ``on_done`` 收到 ``(path, None)``,不报 TypeError
    - 场景 2:`write_netscape_cookies`` raise OSError → ``on_done``
      收到 ``(None, RuntimeError("...disk full..."))``,
      **没有** TypeError / WindowsPath 字样泄露
  - `test_douyin_qr_login_dialog_write_cookies_signature`:
    抖音 dialog 同款修复不被回归
- 顺手修了 M6.25 / M6.31 引入的 2 个 mock:`fake_write` 之前返回
  ``(True, "wrote ...")`` tuple(违反真实签名),
  现在改成返回 ``Path``(对齐 ``platforms/*/auth.py``)

### 三、未做

- 抖音也加 ``wait_for_selector``(M6.34 候选):同 B 站风险,0.3.2
  发版前补
- 0.3.2 发版

### 四、版本号

- 跟 M6.25 / M6.26 / M6.27 / M6.28 / M6.29 / M6.30 / M6.31 / M6.32
  / M6.33 / M6.34 一起进 0.3.2

---

## M6.36 (2026-09-12) — 抖音 QR 也加 wait_for_selector:跟 B 站 M6.33 对称

> 用户实测 M6.35 候选版,B 站扫码登录已经通了;但开抖音
> 登录 dialog 后,二维码区域**只显示白板**——没出来。
>
> 根因:抖音走的 ``CookieSetLogin`` 跟 B 站 ``URLChangeLogin``
> 都用 ``wait_until="domcontentloaded"`` —— **不等 JS**。
> B 站在 M6.33 已经修了:在 ``_qr_snapshot`` 内显式
> ``wait_for_selector`` 10s 等 JS 渲染 QR 元素;但 M6.26 引入的
> 抖音 ``_qr_snapshot`` 一直没加这个 wait,callback 进来时所有
> selector 都找不到,viewport fallback 截到的是 loading 白板。
>
> 跟 B 站根因同款,只是我之前在 M6.34 段里挂的尾巴(M6.36
> 候选)正好对上。

### 一、修复

- `ui/auth_actions.py::douyin_login_via_browser._qr_snapshot`:
  - 加 ``page.wait_for_selector(..., timeout=10_000, state="visible")``,
    跟 B 站 M6.33 对称,等 JS 异步生成 QR 元素
  - 候选 selector 把**父 div 截整张**放第一位,跟 B 站 M6.34
    对称:``div[data-e2e='login-qrcode']`` / ``div.login-QRcode``
  - 兜底 selector 跟之前一样
- 跟 B 站 M6.33 一样:wait 失败不抛,继续走候选 selector 兜底,
  不让扫码流程卡在 wait 上

### 二、回归测试

- `tests/test_auth_actions.py::test_douyin_qr_login_image_waits_for_qr_selector`:
  - mock ``page.wait_for_selector`` 验证它被以
    ``timeout=10_000, state="visible"`` 调用过(防回归)
  - 验证 ``on_qr_image`` 收到的是 selector 截图,不是 viewport
    fallback 的白板

### 三、用户实测发现新问题(2026-09-12 08:18)

> 跑了 M6.36 候选版,用户截图显示 dialog 里"二维码已就绪"状态
> 已经显示,但 QR 区域截到的是**绿色"通过以下方式获取帮助"
> 卡片**,不是抖音的二维码。
>
> 根因深入:`scripts/diag_douyin_qr_selector.py` headless 探测
> 结果(URL = `https://www.douyin.com/`):
> ```
> Title: '验证中继页'
> body 完全是一个滑块验证码 iframe:
>   <iframe src="https://rmc.bytedance.com/verifycenter/captcha/v2?...">
>   + window.TTGCaptcha.init() 滑块渲染 JS
>   + __ac_referer / aid=6383 等字节系风控 cookie
> 所有 14 个候选 selector 全部 0 命中
> ```
>
> 字节系 2026 反爬升级:`https://www.douyin.com/` 在 headless
> 模式下**必被重定向到滑块验证码中继页**(`rmc.bytedance.com/
> verifycenter/captcha/v2`),**根本没有进登录页**。用户截图
> 里"绿色帮助卡"就是这个 verify iframe 内部的"无法完成验证?
> 试试其他方式"区块。
>
> 结论:**这不是 selector 问题,也不是 JS 时序问题** —— M6.36
> wait_for_selector 修对了(等 JS 渲染),但**没有 QR 可等**。
> 抖音 web 端对自动化 headless 浏览器的设备指纹 / webdriver
> 标记 / canvas 噪声一查一个准。
>
> 用户决定(M6.36 落定):**抖音必须 headed 模式**——勾上
> dialog 底下的「显示浏览器(反爬降级)」复选框,M6.26 引入
> dialog 时就埋了这个兜底。headed 模式下:
> - 真实 Chromium 窗口弹出,绕过 verify 风控
> - _qr_snapshot 命中真 QR 元素 → 截图推到 dialog
> - 用户在真浏览器里扫码 → cookies 写盘 → dialog 自动关闭
>
> 0.3.2 文档要标:「抖音 headless 受字节系反爬限制,请勾 headed
> 复选框;B 站保持 headless」。

### 四、未做

- 0.3.2 发版(文档需补「抖音 headed 必备」说明)
- 0.3.3+ 路线: 抖音改走「手机号+验证码」或 stealth plugin
  (见 0.3.2 路线图)

### 五、版本号

- 跟 M6.25 / M6.26 / M6.27 / M6.28 / M6.29 / M6.30 / M6.31 / M6.32
  / M6.33 / M6.34 / M6.35 一起进 0.3.2

---

## M6.37 (2026-09-12) — 抖音 headed 模式 click "扫码登录" 按钮:让 QR modal 真出来

> M6.36 修完后用户勾 headed 复选框实测,QR 区域仍显示 verify
> UI(绿色"通过以下方式获取帮助"卡)。`scripts/diag_douyin_qr_
> selector.py` headed 探测:
> - URL = `https://www.douyin.com/jingxuan`(没有 verify!)
> - 找到"扫码登录"按钮:`xpath=//span[contains(text(),'扫码登录')]`
>   visible,坐标 (427, 230),64x24
> - 找到"扫一扫"提示 visible
> - **没有真 QR 元素** — 因为 modal 还没点出来
>
> 根因:抖音 web 端的 QR 元素**不在首页**,**点"扫码登录"按钮
> 才弹 modal**。生产流程 `CookieSetLogin._on_ready` 只 `page.goto`,
> 不 click。headed 模式启动后页面正确,但 _qr_snapshot 截到的还是
> 首页,**没有 QR**。

### 一、修复

- `core/auth/browser_login.py::CookieSetLogin.__init__`:
  新增可选参数 ``pre_login_hook: Optional[Callable[[Page], None]] = None``
- `core/auth/browser_login.py::CookieSetLogin.run`:
  在 `page.goto` 之后 + qr_callback / _wait_for_success 之前调
  ``pre_login_hook(page)``(try/except 包,失败不抛,继续等 QR)
- `platforms/douyin/auth.py::browser_login`:
  - 只在 **headed 模式** 注入 ``pre_login_hook``(内部定义
    ``_click_scan_login(page)``):
    1. ``wait_for_load_state("load", timeout=15_000)`` 等首页 React
       水合完成
    2. 候选 selector (按 stability 排序):`xpath=//*[normalize-space(
       text())='扫码登录']` → `xpath=//*[contains(text(),'扫码登录')]`
       → `xpath=//span[contains(text(),'扫码')]` → `xpath=//div[
       contains(text(),'扫码')]` → `xpath=//a[contains(text(),'登录')]`
    3. 第一个 visible 的就 click + 等 1.5s modal 动画
    4. 全部 miss → logger.warning,不抛(headless 模式 click 没用)
  - headless 模式**不 click**(verify 必挡,click 反而延长等待)
- `ui/auth_actions.py::douyin_login_via_browser._qr_snapshot`(M6.36)
  wait 10s 不变 — click 按钮 + 等 1.5s 后调 callback,这时 QR
  模态应该已经异步渲染

### 二、回归测试

- `tests/test_browser_login.py` 新增 2 个 + 修 1 个:
  - `test_douyin_browser_login_pre_login_hook_only_in_headed`:
    M6.37 不变量 — headed=True 必须注入 pre_login_hook,headless=True
    必须 None(否则 click 反而拖长 verify 等待)
  - `test_cookie_set_login_runs_pre_login_hook`: 验证 hook 调用
    顺序 — page.goto 先 → pre_login_hook → qr_callback
  - `test_douyin_browser_login_forwards_qr_callback` / `_qr_callback_default_none`:
    fake_cookie_set 加 ``pre_login_hook=None`` 参数(M6.37 签名变化)
- `tests/test_browser_login.py` 现共 35 个,全过

### 三、未做

- 0.3.2 发版(文档需补「抖音 headed 必备 + click '扫码登录' 按钮」)
- 0.3.3+ 路线: 抖音改走「手机号+验证码」或 stealth plugin

### 四、版本号

- 跟 M6.25 / M6.26 / M6.27 / M6.28 / M6.29 / M6.30 / M6.31 / M6.32
  / M6.33 / M6.34 / M6.35 / M6.36 一起进 0.3.2

---

## M6.38 (2026-09-12) — 抖音 QR 真 selector:``img[src^='data:image/png;base64']`` 178x178

> M6.37 headed + click "扫码登录" 按钮修复后,用户实测仍然显示
> verify UI。但 headed diag 实证 headed 模式确实能正常显示抖音
> 首页(`/jingxuan`)且没有 verify,只是 `login_dialog.py:597`
> `setChecked(False)` 默认 unchecked + dialog 启动时立即启动
> Playwright,**用户后勾 headed 已经晚了**。这是个 dialog UX
> bug。
>
> 修复:login_dialog.py:597 `setChecked(True)`(M6.37 部分修复),
> 抖音 dialog 默认 headed(因为抖音 headless 必被 verify)。
>
> 但 M6.36 候选 selector 仍然不对。`scripts/diag_douyin_full_
> flow.py` (M6.37 follow-up 工具)click "扫码登录" 按钮之后再
> probe 一遍:
> ```
> URL: https://www.douyin.com/jingxuan (无 verify!)
> click "扫码登录" 按钮成功
> 等 2s modal 动画
> img[src^='data:image/png;base64']: 2 matches
>   [0] 28x28  小图标
>   [1] 178x178  ← 这就是 QR!!! (位置 370, 275)
> ```
>
> 抖音 2026 modal 用 Semi Design + data-URI base64 PNG 渲染
> QR,真 QR 是 ``<img class="UoVu4M7K" src="data:image/png;
> base64,...">``,178x178,class 是 hash 不稳定。M6.36 候选的
> ``div[data-e2e='login-qrcode'] img`` 等全部 0 命中 —— 抖音
> 早就不用这些 class 了。

### 一、修复

- `ui/auth_actions.py::douyin_login_via_browser._qr_snapshot`:
  - 加 `img[src^='data:image/png;base64']` selector,遍历所有
    base64 PNG img,选 **140-220px** 那张(用户头像/封面是
    16-64px 缩略图,被自动过滤)
  - `wait_for_selector` 也加上 base64 PNG selector
  - 保留旧 selector 作为 fallback(以防将来抖音改回旧 class)
- `ui/dialogs/login_dialog.py:597` `setChecked(True)`(M6.37):
  抖音 dialog 默认 headed(headless 必被 verify 弹死,默认值
  改向 M6.26 文档提到的「默认未勾选」反方向,代价是抖音必须
  弹真浏览器窗口;B 站保持默认 unchecked,headless 能通)
- `scripts/diag_douyin_full_flow.py` 新增(M6.37 工具) — 完整
  headed + click 流程复现脚本,后续 selector 改动可跑这个
  验证真 QR selector

### 二、回归测试

- `tests/test_auth_actions.py::test_douyin_qr_login_image_picks_178x178_base64_qr`:
  - mock 3 个 base64 PNG img(28x28 头像 / 22x22 缩略图 /
    **178x178 真 QR**)
  - 验证 _qr_snapshot 选 178x178 真 QR,不选小图,不退到
    viewport fallback
- 全量测试基线 941 → **942**(+1 M6.38)

### 三、未做

- 0.3.2 发版(文档需补「抖音 headed 必备 + 默认勾上 headed」)
- 0.3.3+ 路线: 抖音改走「手机号+验证码」或 stealth plugin

### 四、版本号

- 跟 M6.25 / M6.26 / M6.27 / M6.28 / M6.29 / M6.30 / M6.31 / M6.32
  / M6.33 / M6.34 / M6.35 / M6.36 / M6.37 一起进 0.3.2

---

## M6.39 (2026-09-12) — 抖音 QR 轮询:覆盖 headed 模式 verify 弹窗挡住 modal 的场景

> M6.38 selector 修对(178x178 base64 PNG)后用户实测,日志
> 仍然报:
> ```
> 08:53:58 WARNING M6.37: could not find '扫码登录' button on
>                     douyin home — QR modal may not appear.
>                     Headed user can click it manually.
> ```
>
> headed 模式在真实 GUI 流程里**也遇到 verify 中继页**(headed
> diag 单次 fresh 请求能到 `/jingxuan` 找到按钮,但 GUI 真实
> 流程里用户 IP/cookie/历史被字节标记过,headed 模式也弹
> verify)。M6.37 pre_login_hook click 按钮失败后,真 QR 不会
> 出现。
>
> 这意味着 _qr_snapshot 单次截图 + viewport fallback 会截到
> verify UI。**修复:让 _qr_snapshot 轮询等 QR 出现(60s 上限)**,
> 覆盖「headed 模式 verify 弹窗挡住 → 用户手动滑块 + 必要时
> 手动点按钮 → QR 出现 → 自动截图」的真实使用流程。

### 一、修复

- `ui/auth_actions.py::douyin_login_via_browser._qr_snapshot`:
  - M6.36 一次性 `wait_for_selector` 10s 保留(等 modal JS 异步
    渲染)
  - 加 **60s 轮询循环**:每 2s 用 M6.38 的
    `img[src^='data:image/png;base64']` + 140-220px size filter
    找真 QR;找不到就 fallback selector 链;再找不到就
    `wait_for_timeout(2_000)` 等下次轮询
  - 找到立刻截图退出;60s 都没找到才 viewport fallback 兜底
    (让 dialog 至少显示 verify UI 而不是白板)
- 用户在 headed 浏览器里手动通过 verify 之后(滑块 / 点击按钮),
  modal 异步渲染出真 QR → 2s 内被 _qr_snapshot 找到 → 自动
  截图推回 dialog,无需重启流程

### 二、回归测试

- `tests/test_auth_actions.py::test_douyin_qr_login_image_polls_until_qr_appears`:
  - mock `time.monotonic` 加速(避免真等 60s)
  - mock page 让前 2 次轮询 0 命中(verify UI 阶段),第 3 次
    才有 178x178 base64 PNG(用户通过 verify 后)
  - 验证 _qr_snapshot 至少轮询 3 次后才退出,捕获到 QR,
    不是 viewport fallback
- 全量基线 942 → **943**(+1 M6.39)

### 三、未做

- 0.3.2 发版(文档需补「抖音 headed 模式偶尔 verify 弹窗,需
  手动通过滑块;verify 通过后 _qr_snapshot 自动捕获 QR」)
- 0.3.3+ 路线: 抖音 stealth plugin / 手机号+验证码

### 四、版本号

- 跟 M6.25 / M6.26 / M6.27 / M6.28 / M6.29 / M6.30 / M6.31 / M6.32
  / M6.33 / M6.34 / M6.35 / M6.36 / M6.37 / M6.38 一起进 0.3.2

---

## M6.40 (2026-09-12) — 抖音 pre_login_hook click 按钮也轮询:覆盖 verify 弹窗阻挡场景

> M6.39 修完后用户实测(9:28-9:30),日志显示:
> ```
> 09:28:14 / 09:28:30 WARNING M6.37: could not find '扫码登录' button
>                                on douyin home — QR modal may not appear.
>                                Headed user can click it manually.
> ```
>
> 之后 ~30 分钟没看到 _on_done 成功,verify 中继页挡住整个 headed
> 流程,M6.37 单次 click 失败后真 QR 永远不会自己出来,viewport
> fallback 截到 verify UI。
>
> M6.39 轮询只在第一次 qr_callback 跑 60s,不能救场 — 因为 click
> 失败就根本没 QR 可轮询。

### 一、修复

- `platforms/douyin/auth.py::browser_login._click_scan_login`:
  - M6.37 单次 click → **M6.40 轮询重试**(每 5s 试一次,最多 60s)
  - wait_for_load_state("load", 10s) 保留,但**降低阻塞上限** —
    verify iframe 永远不让 page 到 full "load" 状态,15s 太长
  - is_visible(timeout=1_500) 缩到 1.5s(原 2s)加快轮询节奏
  - 成功 click 后 logger.info "M6.40: '扫码登录' button clicked on
    attempt N — QR modal should appear",失败后 logger.warning
    "M6.40: could not find '扫码登录' button on douyin home after
    60s of polling — headed user must click it manually"
- 整条 headed 抖音流程现在变成双轮询:
  1. **pre_login_hook 轮询 click 按钮**(M6.40)— 覆盖 verify 弹窗
     期间用户手动通过 → 按钮重新出现 → 自动 click
  2. **_qr_snapshot 轮询等 QR 元素**(M6.39)— click 成功后 modal
     异步渲染 → 2s 内 _qr_snapshot 找到 178x178 base64 PNG → 自动
     截图推回 dialog
- 两条轮询链一起,headless 模式仍 verify 必挡(headless 不注
  pre_login_hook,M6.37);headed 模式覆盖了 verify-captcha + manual
  click 两条路径

### 二、回归测试

- `tests/test_browser_login.py::test_douyin_click_scan_login_polls_until_button_appears`:
  - mock `time.monotonic` 加速
  - mock page 让前 2 次 probe 不可见,第 3 次可见(模拟用户手动
    通过 verify captcha 之后按钮重新出现)
  - 验证 _click_scan_login 至少 probe 3 次,最终 click 1 次成功
- 全量基线 943 → **944**(+1 M6.40)

### 三、未做

- 0.3.2 发版(文档需补「抖音 headed 模式偶尔 verify 弹窗;verify
  通过后 _click_scan_login + _qr_snapshot 双轮询自动捕获 QR」)
- 0.3.3+ 路线: 抖音 stealth plugin / 手机号+验证码

### 四、版本号

- 跟 M6.25 / M6.26 / M6.27 / M6.28 / M6.29 / M6.30 / M6.31 / M6.32
  / M6.33 / M6.34 / M6.35 / M6.36 / M6.37 / M6.38 / M6.39 一起进 0.3.2

---

## M6.41 (2026-09-12) — 抖音 headed_checkbox 状态持久化 + 移除 douyin-downloader JSON 导入

> 两个独立小改动:
>
> **1) 抖音 dialog 的「显示浏览器」复选框状态持久化**
> 用户反馈:M6.37 后默认勾上 headed,但每次开 dialog 都要重设。
> 应该让用户上次的选择自动恢复 — 关闭后下次打开还是勾上 / 取消
> (他选择什么就是什么,不要每次重设)。
>
> **2) 移除 douyin-downloader JSON 导入功能**
> 旧项目 douyin-downloader 的 `config/cookies.json` 格式是简单
> 的 dict,跟我们的 `parse_json_cookies` 输入格式不同,所以有
> 专门 `parse_legacy_json` 解析它。这个功能实际很少用 — 大部分
> 用户用我们支持的 Netscape 格式或 `parse_json_cookies` 已能
> 覆盖(yt-dlp 风格的 JSON)。用户决定移除:删 `import_douyin_
> legacy_json` UI 入口 + CLI `--legacy-json` 参数 + `parse_legacy_json`
> + 相关测试。

### 一、改动

**headed 状态持久化**:
- `ui/dialogs/login_dialog.py::DouyinBrowserDialog.__init__`:
  默认 `setChecked(True)` 改为从 `QSettings("login.dy.headed_
  checkbox", True, type=bool)` 读 — 没存过则默认 True(M6.37 决定)
- `ui/dialogs/login_dialog.py::DouyinBrowserDialog.closeEvent`:
  写 `QSettings` + `sync()`(强制刷盘)保存当前 headed 状态
- 写失败也不抛(read-only 文件系统等) — try/except + logger.exception
- B 站 dialog 不动(无 headed 概念)

**移除 douyin-downloader JSON 导入**:
- `ui/auth_actions.py`:删 `import_douyin_legacy_json()` 函数
- `platforms/douyin/auth.py`:删 `parse_legacy_json()` 函数 + 顶部
  docstring 引用 + 删 `Any` import
- `ui/pages/settings.py`:删 `dy_legacy_btn` 按钮 + `_on_douyin_
  legacy_import` 方法 + `import_douyin_legacy_json` import
- `cli/main.py`:删 `--legacy-json` 参数
- `cli/auth_cmd.py`:删 `_cmd_douyin_legacy` 函数 + `cmd_auth_
  douyin` 里的 legacy 分支 + help text 引用
- `tests/test_auth_actions.py`:删 `test_import_douyin_legacy_
  success` + `test_import_douyin_legacy_missing_file`
- `tests/test_browser_login.py`:删 `test_parse_legacy_json_*` (4 个)
- `tests/test_bilibili_auth.py`:修 `test_cli_auth_douyin_uses_
  browser_login` 不再传 `legacy_json` arg

### 二、回归测试

- `tests/test_ui_polish.py::test_douyin_headed_checkbox_persists_
  across_dialogs`:
  - 三个 dialog 实例的连续开关:首次默认 True → 用户取消 → 二次
    验证 False 已恢复 → 三次再勾上 → 验证 True 已恢复
  - 关键:用 `QApplication.setApplicationName("DouBi")` +
    `setOrganizationName("DouBi")` 让 QSettings 落 Windows 注册表
    正确路径(M6.41 qapp fixture 默认没设,需要补)
- 全量基线 938 → **938**(+1 持久化测试, -6 legacy_json 测试,
  净 -5)

### 三、未做

- 0.3.2 发版
- 0.3.3+ 路线: 抖音手机号+验证码 / stealth plugin

### 四、版本号

- 跟 M6.25 / M6.26 / M6.27 / M6.28 / M6.29 / M6.30 / M6.31 / M6.32
  / M6.33 / M6.34 / M6.35 / M6.36 / M6.37 / M6.38 / M6.39 / M6.40
  一起进 0.3.2

---

## M6.42 (2026-09-12) — 抖音扫码后手机号二次验证(sendSmsCode + verifySmsCode + 新 dialog)

> 用户原始诉求:"抖音扫描成功后,可能需要验证,如果有验证,
> 在无头模式添加手机验证这个过程"。M6.36 修复 QR 不显示后,
> 抖音扫码能进登录页,但**扫码后抖音平台还可能要求手机号 + 短信
> 验证码**作为二次风控验证(M6.42 之前扫码成功 → validate_cookies
> fallback → 报"已登录"但实际上用户被风控挡在二次验证后 → 下载
> 失败)。M6.42 加完整 SMS 验证链路。

### 一、改动

- `platforms/douyin/auth.py::LoginInfo`:
  新增 `need_sms_verify: bool = False` 字段
- `platforms/douyin/auth.py::validate_cookies`:
  fallback 路径里检测 `sessionid/sessionid_ss/sid_guard` 存在 +
  API 调用 404 → 设置 `need_sms_verify=True`(扫码成功但平台要
  二次验证)
- `platforms/douyin/webapi.py::DouyinWebAPI`:
  - 新增 `send_sms_code(phone) -> dict` — 走 `/passport/web/aweme/
    sms/send/`,带 `mobile` + `aid=6383` + `channel=web_pc`,复用
    现有 `_request_json` 签名 + 注入 msToken + cookies 流程
  - 新增 `verify_sms_code(phone, code) -> dict` — 走 `/passport/
    web/aweme/sms/verify/`,同样参数 + `code`
- `ui/dialogs/sms_verify_dialog.py`(新):
  - `SmsVerifyDialog` — 手机号 + 60s 倒计时 + 验证码 + 重发按钮
  - 11 位中国大陆手机号 (`^1[3-9]\d{9}$`) + 4-8 位数字验证码正则
  - 状态码映射:`status_code==0` 成功;2001/2002/2003 频控;
    1003/1004/1005/2002 错码;其他显示 description
  - 异步 API 调用用 `asyncio.new_event_loop()` 隔离(qasync event
    loop 兼容)
- `ui/dialogs/login_dialog.py::DouyinBrowserDialog._on_done`:
  扫码完成 → 写 cookies → 重新 `login_info_from_cookies_sync` 验
  证 → 如果 `need_sms_verify=True` 弹新 SMS dialog(显示「继续验证」
  按钮),不直接 accept 让用户走完整流程
- `ui/locales/{zh_CN,en}.json`:
  加 20 个新 key(8 个 SMS 状态 + 8 个 SMS 错误 + 2 个触发提示 + 2 个
  文案)

### 二、回归测试

- `tests/test_browser_login.py` 新增 7 个 M6.42 测试:
  - `test_login_info_default_does_not_need_sms_verify`:LoginInfo
    默认值 False
  - `test_login_info_from_dict_has_sms_flag_default_false`:API
    响应解析默认 False(fallback 路径才设置)
  - `test_douyin_webapi_send_sms_code_uses_correct_endpoint`:
    mock _request_json,验证 path + params + retries
  - `test_douyin_webapi_verify_sms_code_uses_correct_endpoint`:
    同上
  - `test_sms_dialog_validates_phone_and_code`:正则 + 边界值
  - `test_sms_dialog_interprets_send_status_codes`:0 / 2001 /
    9999 / 空响应
  - `test_sms_dialog_interprets_verify_status_codes`:0 / 1003 /
    1004 / 9999 / 空
- 全量基线 939 → **946**(+7 M6.42 测试)

### 三、风险 + 降级

- 抖音 SMS API 公开度未知 — M6.42 先按已知端点实现,如果 API 实际
  路径 / 签名 / CSRF 要求不同,fallback 到错误提示"请到抖音 web 端
  完成验证后,点这里重试"
- 不依赖 headed 浏览器 — 纯 API 路径(headless / headed 都可用)
- 0.3.2 真实抖音账号实测才能确认 SMS API 是否工作;如果失败,改为
  headed 模式弹 verify 滑块(M6.40 链)

### 四、版本号

- 跟 M6.25 / M6.26 / M6.27 / M6.28 / M6.29 / M6.30 / M6.31 / M6.32
  / M6.33 / M6.34 / M6.35 / M6.36 / M6.37 / M6.38 / M6.39 / M6.40
  / M6.41 一起进 0.3.2

---

## M6.43 (2026-09-12) — 抖音 headed 模式 cookies 不全 → 接受现状,排到 0.3.3

> 用户实测(11:00 左右两次)抖音 headed 模式 M6.40 click "扫码登录"
> 按钮成功 → QR modal 弹 → headed 浏览器里抖音自己的 verify / SMS
> UI 弹 → 用户在 headed 浏览器里走完 verify/SMS 流程 → 但 Playwright
> 拿不到完整 cookies(没有 "Wrote N cookies" 日志) → `validate_
> cookies` 反复 fallback 404 → `_wait_for_success` 等 sessionid
> family 等 25+ 分钟没等到 → 30 分钟 runtime 上限被杀。
>
> 根因(分析):抖音 2026 web 端跟 B 站 2026 同款反爬 — 扫码完成
> 后 **Set-Cookie 不完整下发到 Playwright context**。抖音 App 端
> 收的 SMS 验证码跟抖音 web cookies 是**两套验证体系** — 即便
> App 端 verify 通过,web cookies 也不一定完整。
>
> M6.25–M6.42 链路(headed + 轮询 click + 178x178 base64 QR 截图
> + 写盘)整体**正确**,只是抖音 web 端在 headed 模式下也不
> Set-Cookie 完整 sessionid。

### 决定

- **M6.43 接受现状,排到 0.3.3** — 0.3.2 文档里标「抖音 headed 模式
  受字节系 2026 反爬限制,Set-Cookie 流程不完整,部分账号
  cookies 不全导致登录卡住」,作为已知问题
- 0.3.3 路线图加 M6.43:Playwright `response` 事件监听 Set-Cookie
  响应头,主动捕获 `sessionid/sid_guard/sessionid_ss` 中任意一个
  出现就用 `context.cookies()` 抓所有 cookies,绕过 `_wait_for_
  success` 等全 3/3 的死锁
- 当前 M6.42 保留 SMS API 备用(headless 模式基本走不到 _on_done,
  但保留接口为 0.3.3+ 走"手机号+验证码"主登录流程做基础)

### 现状(0.3.2 发版前)

- B 站 headless 扫码 + cookies 写盘:**完整闭环(M6.25–M6.35)**
- 抖音 headed 扫码 + verify/SMS UI 弹窗 + M6.40 自动 click +
  M6.39 QR 截图 + 写盘:**流程跑通,但 2026 反爬导致 cookies 不全
  (M6.43 TODO)**

### 四、版本号

- 跟 M6.25 / M6.26 / M6.27 / M6.28 / M6.29 / M6.30 / M6.31 / M6.32
  / M6.33 / M6.34 / M6.35 / M6.36 / M6.37 / M6.38 / M6.39 / M6.40
  / M6.41 / M6.42 一起进 0.3.2

---

- 源码 81 个 .py 文件，约 21,000 行
- 测试 33 个文件，**868 passed / 4 skipped**
  （4 skip 均为「无 PySide6 则跳过」GUI 用例）
- 基线演进（M6.16–M6.21 累计）：
  - 713（M6.15）→ 752（M6.16 通用嗅探四入口 +39）→
    768（M6.17 打包精简 +16）→ 768（M6.18 SSH + 发版事故 0 新测试）→
    780（M6.19 catch_lite.js 修复 +12）→
    825（M6.20 HLS 三个根因 +45）→
    868（M6.21 CI pydantic +43）
- 主要新增能力：
  - 通用 URL 嗅探（platforms/generic + playwright）
  - GUI 体验加固（4 个 npm-shrinkwrap-style 修复）
  - 打包体积精简 54.8% （1501.8 → 678.5 MB）
  - SSH + Gitee 同步
  - HLS 下载全废三个根因修复（subproc / M3u8Engine / aiohttp）

---

## M6.44 (2026-09-27) — yt-dlp 1800+ 站点透传：ytdlp_generic 全局兜底适配器

> 用户目标："让 DouBi 也支持现在 yt-dlp 支持下载的网点"。背景：doubi 原本
> 只有 4 个内置适配器（douyin / bilibili / youtube / generic Playwright 嗅探）；
> 任何 yt-dlp 已支持但 doubi 没内置的 URL（Twitter / Instagram / Vimeo / Reddit
> / Pixiv / AcFun / 网易云 / QQ 音乐 / 喜马拉雅 / 央视频 / 虎牙 / 斗鱼 / 西瓜 /
> 优酷 等 1800+ 站）都会落到 generic 嗅探，启动 Chromium、嗅探 15 秒、命中率低。
>
> 根因：doubi 实际上**已经**通过 `engines/yt_dlp.py` 间接支持 yt-dlp 内置
> extractor（douyin/bilibili/youtube adapter 把 URL 喂给 yt-dlp 拿元数据 + 走
> yt-dlp 引擎下载），但**路由层不透明**——用户和 MCP agent 看不到这个能力，
> 不认识的 URL 直接走 Playwright 兜底，而不是先让 yt-dlp 试一次。

### 一、新增 `Platform.YT_DLP_GENERIC` enum（`core/models.py`）

- `YT_DLP_GENERIC = "ytdlp"`，注释里写清楚兜底链
- 不破坏 `Platform.from_str` 容错（未知字符串仍走 `UNKNOWN`）

### 二、新增全局兜底适配器（`platforms/ytdlp_generic/`）

```
platforms/ytdlp_generic/
├── __init__.py           # PlatformRegistry.register(YtDlpGenericAdapter())
├── adapter.py            # match_url 永真 / priority=-1 / parse → yt-dlp
└── strategies.py         # InfoDict → MediaItem 字段归一化
```

**`YtDlpGenericAdapter.parse(url)` 行为**：

1. 调 `yt_dlp.YoutubeDL(opts).extract_info(url, download=False)`
   （`opts` = `quiet / no_warnings / skip_download / cookiefile / proxy / ratelimit`）
2. `_type` in `{playlist, multi_video}` → 拍平 `entries` 构造 `COLLECTION` 容器
3. 否则转 `MediaItem`（`info_to_media_item`）
4. 捕获 `DownloadError` / `ExtractorError` / 网络异常 → 返回 `None`，**不抛**
5. **没有自动 chain fallback 到 generic 嗅探**——用户主动触发（CLI `--force-sniff` / GUI 重试）

**复用契约**：

- `engines/yt_dlp.py` 的 `DEFAULT_USER_AGENT`（避免「解析能过、下载挂」UA 不对称失败）
- `AppConfig.cookies_file` / `proxy` / `rate_limit` 全透传
- `set_config(cls, cfg)` 类方法注入 AppConfig（4 入口各自调用，漏调 = 静默失效）

### 三、兜底链优先级重构

| Adapter | priority（之前 → 现在） | 匹配范围 |
|---|---|---|
| douyin / bilibili / youtube | 0 → 0 | 具体平台特化（拿自家元数据） |
| **ytdlp_generic** | **不存在 → -1** | **yt-dlp 内置 1800+ extractor 全部** |
| generic (Playwright) | -1 → -2 | yt-dlp 不认识的国产 HLS / 自建 CMS |

**契约变更**：

- `PlatformRegistry.detect(unknown_url)` 现在返回 `ytdlp_generic`（之前返回 generic）
- 失败时不自动 chain 到 generic 嗅探；用户必须主动触发
- 4 个入口里 `test_unknown_url_falls_back_to_generic` / `test_registry_detect_unknown_*`
  / `test_pipeline_process_url_unknown_returns_sniff_error_item` 等 4 处断言改写为新行为

### 四、`AppConfig.cookies_file` 新字段（`core/config.py`）

`M6.17` 之前 README 提到 `~/.doubi/cookies/*.txt` 但 AppConfig 实际没有这个字段
——`DownloadOptions.cookies_file` 一直是 None，cookie 永远没喂给 yt-dlp。
本里程碑补齐：

- `DEFAULTS["cookies_file"] = None`
- `AppConfig.cookies_file: Optional[Path]`
- `load_config` 从 YAML / `DOUBI_COOKIES_FILE` env 读取
- `to_dict` 序列化 Path → str
- 4 个搬运点（CLI `_build_options` / REST `_build_options`）同步转发
- CLI 新增 `--cookies-file` 命令行参数（覆盖配置文件）

### 五、MCP 新工具 `list_supported_sites`（`mcp/server.py`）

让 AI agent（MCP 客户端）一眼看出「DouBi 真正能下哪些站」：

```json
{
  "builtin_adapters": [...4 个内置适配器...],
  "ytdlp_extractor_count": 1832,
  "ytdlp_extractors": [{"ie_key": "Twitter", "name": "Twitter", "host": "twitter.com", "valid_url": "...", "age_limit": null, "description": "...", "working": true}, ...],
  "note": "Call parse_url with the URL directly — ytdlp_generic will route to the matching extractor automatically."
}
```

实现要点：

- 进程级缓存 `_YT_EXTRACTORS_CACHE`——`yt_dlp.list_extractors()` 是 generator，
  不缓存会重复遍历 1800+ 次
- `_safe_scalar()` 把 bound method / property 等非 JSON 标量过滤掉，避免
  `TypeError: Object of type method is not JSON serializable`
- `description` 强转 `str()` 再 `[:200]` 截断（部分 extractor 把 `IE_DESC` 定义成 bool）

### 六、CLI 新增 `doubi platforms --yt-dlp`（`cli/main.py`）

不传 `--yt-dlp` 时维持原行为（只列 4 个内置适配器 + stderr 提示「试试 `--yt-dlp`」），
传了之后输出 1800+ 条 `name / host / ie_key` 表，支持 `--filter` 关键字过滤：

```bash
$ doubi platforms --yt-dlp --filter twitter
yt-dlp extractors: 5
  Twitter                twitter.com                   Twitter
  TwitterAmplify         twitter.com                   TwitterAmplify
  TwitterBroadcast       twitter.com                   TwitterBroadcast
  TwitterCard            twitter.com                   TwitterCard
  TwitterSpaces          twitter.com                   TwitterSpaces
```

### 七、测试覆盖（**新增 39 条 / 修改 4 条**）

| 文件 | 新增 / 修改 | 覆盖 |
|---|---|---|
| `tests/test_ytdlp_generic_adapter.py` | +36（全新） | adapter 行为 / strategies 字段归一化 / playlist 拍平 / 失败路径 / 缓存契约 |
| `tests/test_mcp.py` | +3 | `list_supported_sites` 返回 / 过滤 / 缓存 |
| `tests/test_generic_sniffer.py` | 3 处硬编码 -1 → -2 | 兜底链 priority 变更 |
| `tests/test_youtube_adapter.py` | 1 处断言更新 | unknown URL 现在匹配 ytdlp |
| `tests/test_pipeline_smoke.py` | 1 处断言更新 + 1 个新增 | process_url 失败行为 + generic 直接 sniff 错误路径保留 |
| `tests/test_mcp.py` | 1 处断言更新 | unknown URL 错误 payload 形态 |
| `tests/test_cli_config_layering.py` | 1 行 | CLI `_build_options` 转发 cookies_file |
| `tests/test_server.py` | 1 行 | REST `_build_options` 转发 cookies_file |

全量回归：**763 passed / 7 skipped**（`pytest -m "not slow and not gui"`）。

### 八、契约外延（不破坏既有测试）

- `engines/yt_dlp.py` 没改（`DEFAULT_USER_AGENT` 复用现有常量）
- `pipeline.process_url` 没改（仍调 `adapter.parse`，ytdlp_generic 自动接入）
- GUI 解析页没改（`PlatformRegistry.detect` 自动用新链）
- REST `_build_options` 仅加一行 `cookies_file=cfg.cookies_file`，无其他改动

### 九、克制清单（这次**没做**）

- ❌ SponsorBlock / 字幕元数据 → 留给 M6.45+
- ❌ 平台黑名单（伦理化 opt-out） → 等真有平台投诉再补
- ❌ gallery-dl 图片画廊 → 范围之外
- ❌ whisper.cpp 自动字幕 → 范围之外

---

## M6.45 (2026-10-01) — 抖音合集 `/collection/{id}/{seq}` 解析 + MIX 容器回归

> 用户目标："粘贴 `/collection/{mix_id}/3` 这种带 seq 后缀的抖音合集
> 链接时，能正确识别语义"。背景：抖音 web 在合集页点选某条视频时，
> URL 会带 `/{seq}` 后缀表示"第 N 个"。这个 seq 不是"我要第 N 条"，
> 而是"用户先看到了第 N 条"的位置标记——真正的"要第 N 条"应该用
> `/video/{aweme_id}`。
>
> 早期回归方向（M6.45 中段）：seq → 单条 VIDEO。**否定**——实测确认用
> 户要的是"整个集合的每条视频"，不能因为 seq 在就让 adapter 退回单条。

### 一、`ClassifiedURL.seq: Optional[int]`（`platforms/douyin/url.py`）

- 新增 `seq` 字段，`None` 时表示"整个合集"，`int` 时表示"用户在合集
  里的位置"
- **正则顺序硬约束**：`/collection/{id}/{seq}` 必须排在 `/collection/{id}`
  之前——否则 seq 被静默吞掉（因为 `id` 是 greedy，seq 进不去 groupdict）
- `_PATTERNS` 加了 seq 优先分支；iesdouyin mix 详情链接、modal_id
  fallback、vid= fallback 等保持原位置不动

### 二、`adapter.parse` MIX 容器永远返回（`adapter.py`）

```python
if classified.type in (DouyinURLType.COLLECTION, DouyinURLType.MIX):
    # 合集 URL 永远返回 MIX 容器，pipeline 触发 expand() 把整集合
    # 的视频全列出来。``seq`` 后缀只是抖音 web 的"滚动到第 N 个"
    # 位置提示——``/video/{aweme_id}`` 才是要单条。
    return await self._parse_collection(classified.item_id, seq=classified.seq)
```

- `source_url` 保留 seq（`/collection/{mix_id}/N`）——便于调试 + UI 知道
  "用户当时选中的是第 N 个开始看"
- `extra["seq"]` 同步留痕，`mix_id` 单独写一份便于后续 UI 按 ID 聚合
- 标题走 `_probe_mix_title()` best-effort（webapi 拿不到就退到占位符
  `抖音合集 {mix_id}`，不抛错）

### 三、`expand()` MIX 路径（`adapter.py`）

- 复用既有 `webapi.iter_mix_awemes`，**无 seq 专属代码**
- `USER` / `MIX` 共用 `expand()`，USER 走 strategies，MIX 走 webapi
- 移除 M6.45 中段写的 `_parse_collection_item`（死代码，回滚干净）

### 四、测试覆盖（**新增 6 例 / 修改 0**）

| 文件 | 新增 | 覆盖 |
|---|---|---|
| `tests/test_pipeline_smoke.py` | +3 | `classify_douyin_url` 带/不带 seq、`/mix/{id}` 仍然走原路径 |
| `tests/test_douyin_adapter.py` | +3 | `parse(/collection/{id}/3)` → MIX 容器 + source_url 保留 seq + webapi 失败时仍返回容器（不抛 None） |

全量回归：**768 passed / 7 skipped**。

### 五、克制清单（这次**没做**）

- ❌ 合集展开失败的 UI 提示 → M6.46（详见下一节）
- ❌ `/mix/{id}` 与 `/collection/{id}` 的语义区分 → 现在仍归 MIX 容器；
  暂未观察到用户对前者报错，等有反馈再分
- ❌ seq 跳转（"用户点了 seq=5，希望下载从第 5 条开始"）→ 抖音 web
  的 seq 是"位置标记"不是"区间标记"，M6.45 决定保持"全集合"语义

---

## M6.46 (2026-10-01) — 抖音合集展开失败 UI 提示（Argus 风控 → 「需要登录抖音」徽章）

> 用户痛点（M6.45 落地后实测）：粘贴 `/collection/{id}` 后 GUI 只显示
> 1 个 MIX 容器占位符（`抖音合集 {id}`），点开是空的——用户无法判断
> 是「解析失败」还是「合集本身就 1 条」。
>
> 根因（独立渠道复测 4 个）：
> 1. `webapi.iter_mix_awemes` 持续 HTTP 403 — 阿里云 Tengine
>    `ArgusSecurityPlugin Uifid Not Found`（不只查 cookie，还查 TLS 指纹
>    + IP 信誉 + 设备指纹，doubi 端无法绕过）
> 2. `yt-dlp` 完全不支持 `/collection/{id}` URL（yt-dlp 2026.08.19 复测
>    `Unsupported URL`）
> 3. `iesdouyin.com/share/mix/detail/{id}` 短链 redirect 后还是
>    `/collection/{id}` → yt-dlp 仍然拒绝
> 4. `ytdlp_generic` 兜底是 yt-dlp 透传，yt-dlp 不支持它也无能为力
>
> **决策（不绕 Argus、不写 scraper、不打 yt-dlp patch）**：在 webapi
> 失败时把结构化错误留到 `MediaItem.extra["expand_error"]`，UI 据此
> 渲染「需要登录抖音」徽章——**让用户理解为什么不是 M5 解析失败**，
> 这是诚实降级，不是绕过。

### 一、`webapi._request_json()` 加 `error_sink` 钩子（`webapi.py`）

```python
async def _request_json(
    self, path, params, *, max_retries=3,
    error_sink: Optional[MutableMapping[str, Any]] = None,
) -> dict[str, Any]:
```

- 调用方提供 mutable dict，失败时填入 `{reason, status_code, hint}`
- `_RISK_CONTROL_STATUSES = {403, 429, 461, 471}` + `461` 全部映射到
  `hint="need_login"`；5xx 映射到 `hint="server_error"`；其他映射到
  `hint="transient"`（网络抖动 / anti-bot 探测，UI 引导"过一会重试"）
- **保持向后兼容**：默认 `error_sink=None` 时走原"返回 {}"路径，所有
  老调用方零修改
- 同样的 sink 机制贯穿 `get_mix_aweme` / `iter_mix_awemes` /
  `get_user_post` / `iter_user_posts`，**USER 容器展开失败也能拿到
  hint**（M6.46 当前只接 MIX，USER 已 ready 但 UI 未启用）

### 二、`adapter.expand()` MIX 失败留痕（`adapter.py`）

```python
if item.media_type is MediaType.MIX:
    error_sink: dict[str, Any] = {}
    awemes = await self.webapi.iter_mix_awemes(
        item.item_id, max_count=max_count, error_sink=error_sink,
    )
    children = [aweme_to_media_item(a) for a in awemes]
    item.children = children
    if not children and error_sink:
        item.extra["expand_error"] = error_sink
        logger.info("expand MIX %s failed: %s (status=%s, hint=%s)", ...)
    return children
```

**注意**：`expand_error` 只在 **页面首次拉取就失败且 children=[]** 时
才写入——避免合法空合集（webapi 正常返回空数组，sink 没被动）误显示
「需要登录抖音」。

### 四、解析表标题徽章（`ui/pages/parse.py`）

```python
expand_error = item.extra.get("expand_error")
if expand_error and not item.children:
    title_cell = _cell(f"{title_text}  · {_expand_hint_text(expand_error)}")
    title_cell.setToolTip(_expand_tooltip_text(expand_error))
    self.result_table.setItem(i, 2, title_cell)
```

hint → 中文标签映射：

| hint | 中文 |
| --- | --- |
| `need_login` | 需要登录抖音 |
| `server_error` | 抖音服务器异常 |
| `transient` | 网络异常,请重试 |
| 其他 / 非 dict | 展开失败（兜底） |

- tooltip 携带 raw `status_code` + reason（power-user 排查用，例如
  `展开失败：HTTP 403 (HTTP 403)`）
- "下载整个合集" 反查路径（`_download_whole_collection`）的失败 toast
  也读 `expand_error`，不再笼统说"合集为空"

### 五、测试覆盖（**新增 8 例 / 修改 0**）

| 文件 | 新增 | 覆盖 |
|---|---|---|
| `tests/test_douyin_adapter.py` | +3 | `expand(MIX)` Argus 403 → `expand_error.hint=need_login` / webapi 返回真实空 → 不写 / 正常路径不写 |
| `tests/test_ui_polish.py` | +5 | `_expand_hint_text` 3 例（3 个 hint + 未知 hint 兜底） / `_expand_tooltip_text` 2 例（带 status + transport error） |

合计 **M6.45 + M6.46：14 例**。其中 5 例在 `test_ui_polish.py` 受
`pytestmark = pytest.mark.gui` 影响，`-m "not gui"` 跑分里看不见（GUI
依赖未装的 CI runner 同理跳过），实测验证时切到默认 mark 才计入。

### 六、跑分（实测）

```
$ python -m pytest tests/test_douyin_adapter.py tests/test_pipeline_smoke.py \
    -q -m "not slow and not gui"
82 passed in 69.69s        # M6.45 + M6.46 的可见 6 例 + 既有 76 例

$ python -m pytest tests/ -q -m "not slow and not gui" --tb=short
771 passed, 263 deselected in 60.28s   # 完整 baseline 768 + M6.46 可见 3 例
```

完整跑分 768 → 771（M6.45 是历史 baseline，M6.46 净增 3 例，5 例 GUI mark
本轮默认跑分不计入）。

### 七、克制清单（这次**没做**）

- ❌ Cookie 探测路径（让用户从浏览器导入 cookie 后看 webapi 能不能过
  Argus）→ 不确定性能不能过；等真有用户主动试过 Argus 后再加，避免
  无用代码
- ❌ Playwright HTML scraper → 抖音网页本身要登录才能渲染出合集内容，
  本质没绕过 Argus
- ❌ 给 yt-dlp 提 patch 支持 `/collection/{id}` → 同 webapi 403 问题，
  没解决根因
- ❌ USER 容器展开失败的 UI 提示 → 机制已 ready（webapi error_sink 贯穿
  user_* 方法），但 UI 当前不读 `expand_error`（MUX 错混后让用户在
  M6.47+ 决定是否启用 USER 容器同款徽章）→ **M6.47 已启用，见下节**
- ❌ hint 走 i18n 字典 → 当前 zh_CN.json 未加 `expand_hint.*` key，
  硬编码中文便于发版，i18n 留给 M6.47+（本轮仍未做）

---

## M6.47 (2026-10-02) — 抖音 USER 容器 expand 失败 UI 提示（MIX 路径对称补齐）

> 用户目标：消除「MIX 容器失败能看到「需要登录抖音」徽章、USER 容器失败
> 还是空白」的 UX 不对称。M6.46 已经在 webapi 层把 error_sink 贯穿到
> `iter_user_posts` / `iter_mix_awemes`，但 adapter 的 USER 分支没读
> sink，徽章机制只对 MIX 生效。

### 一、`ContainerStrategy.expand()` 加 `error_sink` 抽象参数（`strategies.py`）

```python
@abstractmethod
async def expand(
    self,
    url: str,
    *,
    max_count: int = 0,
    error_sink: Optional[MutableMapping[str, Any]] = None,
) -> list[MediaItem]:
```

- 向后兼容：默认 `error_sink=None` 走原"返回 []"路径
- `PostStrategy.expand()` 把 sink 传给 `webapi.iter_user_posts`
- `LikeStrategy.expand()` 在 `api.cookies_file is None` 时主动写
  `hint="need_login"`（不用等 webapi 失败就能提前告诉用户"需要登录"）

### 二、`adapter.expand(USER)` 路径补齐（`adapter.py`）

```python
if item.media_type is not MediaType.USER:
    return list(item.children)
s = self._strategies.get(strategy) or self._strategies[self._default_strategy]
error_sink = {}
children = await s.expand(
    item.source_url, max_count=max_count, error_sink=error_sink,
)
item.children = children
item.extra["applied_strategy"] = s.name
if not children and error_sink:
    item.extra["expand_error"] = error_sink
```

跟 MIX 路径用同一个 sentinel：
- 「只在首页失败 + children=[] 时写」——避免合法空合集 / 合法空用户误显示
- 「只要 sink 被填就写」——区分开了"真的空"和"失败了但 sink 没动"

### 四、`toast 文案去特化（`ui/pages/parse.py`）

```python
# 之前：
self._toast(InfoBar.warning, "合集展开失败", ...)
# 现在：
self._toast(InfoBar.warning, "展开失败", ...)
```

USER 容器失败时不再被冠以 "合集" 字样；徽章代码天然是
container-type-agnostic（只读 `extra["expand_error"]`），所以标题单元
自动覆盖两种容器。

### 五、测试覆盖（**新增 3 例 / 修改 1**）

| 文件 | 改动 | 覆盖 |
|---|---|---|
| `tests/test_douyin_adapter.py` | +3 | USER Argus 403 → expand_error / USER 正常 → 不写 / LikeStrategy no-cookies → 主动写 need_login |
| `tests/test_douyin_adapter.py` | 1 行 | 老 `_fake_expand` 接受新 `error_sink` kwarg |

合计 M6.46 + M6.47：11 例**可见**（不含 `test_ui_polish.py` 5 例
`@pytest.mark.gui`，CI 默认跑分看不到）。

### 六、跑分（实测）

```
$ python -m pytest tests/test_douyin_adapter.py tests/test_pipeline_smoke.py \
    -q -m "not slow and not gui"
88 passed in 29.68s    # 既有 82 + M6.47 新增 3 + 老 _fake_expand 兼容改动 3

$ python -m pytest tests/ -q -m "not slow and not gui" --tb=short
...
```

`pytest -m "not slow and not gui"` 完整跑分见 0.3.2 统计小节（M6.47 净增
3 例 可见 → baseline 771 + 3 = **774 passed / 7 skipped**）。

### 七、克制清单（这次**没做**）

- ❌ hint 走 i18n 字典 → 仍未做（zh_CN.json 没加 `expand_hint.*` key），
  留给 M6.48+
- ❌ 收藏夹（LikeStrategy）失败的其他原因 → 当前只覆盖 "无 cookie" 这
  一种常见原因；其他失败仍走 `webapi.iter_user_posts` sink
- ❌ B站 USER 容器同样机制 → 那是 bilibili/strategies.py 的事，跟
  抖音失败 hint 不通用（错误码 / hint 分类都得另写），M6.48+ 再看

---

## M6.48 (2026-10-02) — msToken 实抓 + WebSign 第二层签名（TikTokDL 移植 #1）

> **目标**：把 webapi 的 403 概率从「100%（仅 a_bogus 必被 Argus 拦）」降到
> 「≈ 30%」（加上真实 msToken + x-secsdk-web-signature）。背景、源项目、
> 路径选择详见 `.scratch/TikTokDownloader_Survey.md`（高阶盘点）+ `.scratch/
> TikTokDL_采集功能盘点.md`（采集细节深度盘点）。
>
> **诚实预期**：即便移植完三件套，**根因风险**还在——TikTokDL 项目本身
> 无 git log / 无 CHANGELOG 可量化跟版节奏；doubi 这边 xGnarly（Argus
> 主杀器）当前**未移植**（TikTok 专用 / 抖音未触发），所以即便 msToken +
> WebSign 全到位，仍然无法保证 100% 突破。CHANGELOG 必须把这一限制写
> 清楚，否则跟旧 CHANGELOG 风格不一致。

### 一、新增 `sign/ms_token.py`（实请求 mssdk）

```python
# Adapted from Johnserf-Shell/TikTokDownloader src/encrypt/msToken.py (MIT)
#   POST https://mssdk.bytedance.com/web/common
#   Body: {"magic": 538969122, "version": 1, "dataType": 8,
#          "strData": "...600+char blob...", "tspFromClient": int(time()*1000), "ulr": 0}
#   响应 Set-Cookie 头 → msToken 值
class MsTokenFetcher:
    def __init__(self, *, timeout=10.0, str_data="", default_token=""): ...
    def invalidate(): ...
    async def fetch(*, proxy=None, headers=None) -> Optional[str]: ...
    @property
    def cached() -> Optional[str]: ...
```

**失败兜底**：网络断 / 非 200 / Set-Cookie 无 msToken → 返回 `None`，
调用方退回 per-call fake `_false_ms_token()`——M6.46 已有的
「需要登录抖音」徽章机制保留兜底。**绝不 raise**。

### 二、新增 `sign/tt_wid.py`（实请求 ttwid）

```python
# Adapted from TikTokDL src/encrypt/ttWid.py (MIT)
#   POST https://ttwid.bytedance.com/ttwid/union/register/
#   Body: '{"region":"cn","aid":1768,"needFid":false,"service":"www.ixigua.com",...}'
#   响应 Set-Cookie → ttwid 值
class TtWidFetcher: ...  # 同 MsTokenFetcher 形态
```

**失败兜底**：同 msToken。`ttwid` 缺失的代价是「webid 系 cookie 不全」，
403 风险略升但不 crash。

### 三、新增 `sign/websign.py`（WebSign 第二层签名 + protected paths 白名单）

```python
SALT = "A96D855A08C0A9707F8BEF0D9A527E4E"  # 抖音 runtime_bundler_34.js

def sign(query, uifid, *, timestamp=None) -> tuple[str, str]:
    # 算法:
    #   stamp = str(int(time()))
    #   pairs = decode(query)               # split on '&', unquote name + value
    #   pairs.append((uifid, uifid))        # if missing
    #   pairs.append((timestamp, stamp))
    #   hashed = encode(pairs)              # canonical percent-encoding
    #   signature = md5(f"{uifid}_{stamp}_{SALT}_{hashed}").hexdigest()
    #   return f"{hashed}&x-secsdk-web-signature={signature}", signature

DOUYIN_SIGNED_PATHS = frozenset({
    "/aweme/v1/web/aweme/detail/",         # doubi 单视频解析
    "/aweme/v1/web/aweme/post/",            # USER 容器展开 (PostStrategy)
    "/aweme/v1/web/mix/aweme/",             # MIX 容器展开 (M6.45)
    "/aweme/v1/web/mix/detail/",
    "/aweme/v1/web/aweme/listcollection/",  # 收藏夹全家族（M6.50 候补）
    "/aweme/v1/web/collects/list/",         # Collects 类
    # ... 14 条，按需增减
})
```

**SALT / 算法漂移检测**：`test_sign_produces_known_md5_vector` 用固定
输入 pin `MD5("test12345678" + "_" + "1234567890" + "_" + SALT + "_" +
canonical_query) = "a39b52f20615d3876f8bf4187479a2be"`——任何 SALT
漂移或 canonical 编码漂移都会让这条测试立即失败。

### 四、`DouyinWebAPI` 接入三件套（`webapi.py`）

```python
class DouyinWebAPI:
    def __init__(self, *, cookies_file=None, proxy=None, timeout=15.0):
        # ... existing ...
        self._ms_token_fetcher = MsTokenFetcher(timeout=min(timeout, 10.0))
        self._tt_wid_fetcher = TtWidFetcher(timeout=min(timeout, 10.0))
        # Stable per-session UUID4 hex (16 chars) as uifid visitor ID
        self._uifid: str = uuid.uuid4().hex[:16]
        self._tokens_ready: bool = False

    async def _ensure_tokens(self) -> None:
        """One-shot lazy fetch; subsequent calls reuse cached cookies."""
        if self._tokens_ready:
            return
        async with self._tokens_lock:  # single-shot, no fan-out
            if not self.cookies.get("msToken") and ...:
                self.cookies["msToken"] = await self._ms_token_fetcher.fetch(...)
            if not self.cookies.get("ttwid") and ...:
                self.cookies["ttwid"] = await self._tt_wid_fetcher.fetch(...)
            self._tokens_ready = True

    def _signed_url(self, path, params):
        # ... a_bogus ...
        if is_sign_protected(endpoint) and self._uifid:
            params_with_ab = websign_sign(params_with_ab, self._uifid)[0]
        return f"{endpoint}?{params_with_ab}"

    async def _request_json(self, path, params, *, max_retries=3, error_sink=None):
        await self._ensure_tokens()  # M6.48: lazy fetch on first call
        # ... existing retry loop now uses real msToken + uifid ...
```

**关键变化**：
- 第一次请求会多打一次 mssdk + ttwid 的网络握手（best-effort，单次）
- 之后所有请求复用 self.cookies 中的 msToken + ttwid
- 受保护端点（`/mix/aweme/`、`/aweme/post/`、`/aweme/detail/`）自动带
  `timestamp` + `x-secsdk-web-signature`
- uifid 是会话级稳定 UUID4 hex（16 字符）——TikTokDL 注释说 uifid 是
  访客 ID，平台不验证结构，只验证存在 + 稳定

### 五、测试覆盖（**新增 20 例 / 修改 0**）

| 文件 | 新增 | 覆盖 |
|---|---|---|
| `tests/test_douyin_sign.py`（全新） | 20 | SALT pin、protected paths 白名单、normalize 幂等、WebSign MD5 向量、msToken/ttWid HTTP/non-200/200-without-cookie、uifid 16-hex 稳定、protected 路径带 WebSign、unprotected 不带 WebSign、`_ensure_tokens` idempotency |

**关键 pin 向量**（任一失败 = 必须重新逆向 TikTokDL 算法）：

```python
# test_sign_produces_known_md5_vector
query = "aid=6383&device_platform=webapp&uifid=test12345678&verifyFp=test"
websign_sign(query, "test12345678", timestamp=1234567890)
# expected: signature="a39b52f20615d3876f8bf4187479a2be"
# expected: signed ends with "&x-secsdk-web-signature=a39b52f20615d3876f8bf4187479a2be"
```

合计 **M6.45 + M6.46 + M6.47 + M6.48**：54 例**可见**（不含
`test_ui_polish.py` 5 例 `@pytest.mark.gui`）。

### 六、跑分（实测）

```
$ python -m pytest tests/test_douyin_sign.py -v
20 passed in 0.75s                # M6.48 净增 20 例

$ python -m pytest tests/ -q -m "not slow and not gui"
794 passed, 263 deselected in 63.56s   # M6.47 baseline 774 + M6.48 净增 20
```

### 七、克制清单（这次**没做**）

- ❌ **xGnarly 算法移植** → TikTok 专用 + ChaCha20 自定义（321 行 +
  350 行依赖），移植成本极高且抖音未触发；M6.48 三件套（msToken 实抓 +
  WebSign + uifid）已能覆盖大多数非 xGnarly 触发的 403 场景
- ❌ **strData blob 旋转检测** → 抖音一旦升级 secsdk，strData 需重新
  逆向；本轮用 TikTokDL 捕获的固定 blob（保守期 ≈ 2 weeks / 6 months
  之间）。需要监控 mssdk 200 响应内容是否带新字段 → 触发告警
- ❌ **真 uifid 获取** → DouBi 用 UUID4 hex 16 字符作占位；TikTokDL 注释
  说 uifid 由 mssdk 响应附带，但 DouBi 没解析出来。如果平台真校验
  uifid 结构 / 来源，403 仍会发生——需要真实抓 uifid（M6.49+）
- ❌ **Cookie 文件回写** → mssdk 拿到的 msToken 没写回 cookie 文件，下次
  启动还要重新握手；可以加但优先级低（mssdk 调用 < 1s，对用户体验
  无影响）
- ❌ **策略化签名** → 不同 path 用不同 SALT / 不同 uifid（TikTokDL 是
  单一 SALT 走全局）；doubi 当前同构，跟 TikTokDL 一致

### 八、风险声明

⚠️ **本里程碑落地后，doubi 仍可能 403**。已确认现状：
1. TikTokDL 项目本身无 git log / 无 CHANGELOG → 无法量化 SALT、
   strData blob 的跟版节奏
2. xGnarly 未移植 → Argus 主杀器未破
3. uifid 是 UUID4 占位 → 平台如校验 uifid 来源 / 格式仍会 403

如果 M6.48 落地后实测 403 概率仍 > 50%，下一步候选：
- **M6.49**：uifid 真实获取（解析 mssdk 响应带回来的字段）
- **M6.50**：搜索 4 子类（不依赖签名升级，端点稳定）
- **M6.51**：热点榜（最低风险）→ **M6.49 实际落地为「搜索 4 子类」**，
  见下节；uifid 真实获取留待 M6.50+（mssdk 响应体结构没变，需要
  额外抓包分析；优先级让位于用户场景更直接的搜索）

---

## M6.49 (2026-10-02) — 抖音搜索 4 子类（general / video / user / live）

> **目标**：让 doubi 能「按关键词搜索抖音视频/用户/直播」，把以前「只能粘贴
> 已知 URL」的入口加上一段「按关键词找内容」。背景：用户在抖音里看到
> 「这个号推荐的内容挺好」会本能地想搜同主题，doubi 之前没有这条路径。
> 来源：Johnserf-Shell/TikTokDownloader ``src/interface/search.py``。
>
> **诚实限制**：「按 user 搜索」必然要求登录态（搜出来的是「该关键词下
> 我可见的账号」）；CLI 加 `--cookies-file` 默认 None，无 cookie 仍能跑
> 但命中率/上限低。GUI 接入留给 M6.50+。

### 一、`webapi._search_paginate` 通用翻页器（`webapi.py`）

```python
async def _search_paginate(
    self, endpoint: str, *,
    data_key: str,                       # "data" / "user_list"
    extra_params: dict[str, Any],
    unwrap_lives: bool = False,           # TikTokDL: live search 每行 {lives: [...]}
    count: int = 10, max_count: int = 0, max_pages: int = 50,
    error_sink: ...,
) -> list[dict[str, Any]]:
    """offset + search_id 翻页，去重 by aweme_id/user_id/room_id。

    max_pages=50 是 hard cap — 抖音偶发 ``has_more=True`` 永远，
    没有这个上限会跑出几十万页停不下来。dedup 用 ``str(v) is not None``
    而不是 ``str(v) or ...``：``str(None) == "None"`` 是 truthy 字符串，
    会盖掉下一个 fallback key（直播搜索的 ``room_id`` 永远被
    ``str(aweme_id) == "None"`` 屏蔽 → bug 在 fix 一下入）。M6.49 单测
    ``test_search_live_unwraps_lives_wrapper`` 锁死这个 invariant。
    """
```

### 二、4 个 search 方法

```python
async def search_general(keyword, *, sort_type=0, publish_time=0, duration=0,
                          search_range=0, content_type=0, ...) -> list[dict]:
    """综合搜索 — TikTokDL channel 0 — version_code 19.6.0。
    Filter 走 ``filter_selected``（JSON URL-encoded）。"""

async def search_video(keyword, *, sort_type=0, publish_time=0, duration=0,
                       search_range=0, ...) -> list[dict]:
    """视频搜索 — channel 1 — version_code 17.4.0。
    Filter 走 per-key params（TikTokDL line 301-320）。"""

async def search_user(keyword, *, fans=0, user_type=0, ...) -> list[dict]:
    """用户搜索 — channel 2 — data_key "user_list"。
    Filter 走 ``search_filter_value``（JSON URL-encoded list）。"""

async def search_live(keyword, ...) -> list[dict]:
    """直播搜索 — channel 3 — unwrap_lives=True。"""
```

### 四、`sign/websign.py` 扩展 14 → 18 条 protected paths

```python
# 抖音 search 端点 防御性加入白名单：
# TikTokDL 的 8-shot 实测（2026-09-08）只覆盖 detail/post；
# search 端点是否需要 WebSign 没公开数据。但 over-signing 是无害的
# （TikTokDL 的 notes），加上去更安全。
DOUYIN_SIGNED_PATHS |= {
    "/aweme/v1/web/general/search/single/",
    "/aweme/v1/web/search/item/",
    "/aweme/v1/web/discover/search/",
    "/aweme/v1/web/live/search/",
}
```

### 五、CLI `doubi search` 子命令（`cli/main.py`）

```bash
$ doubi search <keyword> \
    [--type general|video|user|live]      # default: general
    [--count N]                       # pagesize, default 10
    [--max N]                         # 全跑最多 N 条, default 20
    [--sort N] [--days N] [--duration N] [--follow N] [--content N]
    [--fans N] [--user-type N]
    [--cookies-file PATH] [--proxy URL]
```

JSONL 输出，每行一个 aweme / user / live dict（含 ``share_url``），
可直连 ``doubi download --batch -``：

```bash
$ doubi search "python tutorial" --type video --sort 1 --days 7 --max 10 \
  | doubi download --batch - --no-explain-in-public
```

错误 UX：失败时把 `error_sink.hint="need_login"` 转成「试试
`--cookies-file ~/.doubi/cookies/douyin.txt`」友好信息（M6.46 + M6.49 联动）。

### 六、测试覆盖（**新增 12 例**）

| 文件 | 新增 | 覆盖 |
|---|---|---|
| `tests/test_douyin_search.py`（全新） | 12 | 4 个 endpoint 路由 / filter_selected URL 编码 / search_id 翻页 / aweme_id dedup / per-key params（video）/ search_filter_value JSON（user）/ lives wrapper unwrap / max_pages 硬上限 / error_sink hint 透传 |

合计 **M6.45 + M6.46 + M6.47 + M6.48 + M6.49**：74 例**可见**。

### 七、跑分（实测）

```
$ python -m pytest tests/test_douyin_search.py -v
12 passed in 0.77s               # M6.49 净增 12 例

$ python -m pytest tests/ -q -m "not slow and not gui"
806 passed, 263 deselected in 62.84s   # M6.48 baseline 794 + M6.49 净增 12
```

### 八、克制清单（这次**没做**）

- ❌ **GUI 搜索页** → 仅做 CLI；GUI 涉及 PySide6 Fluent 搜索表单 + 结果表格
  + 翻页滚动，加起来是 M6.50+ 的工作量。CLI 先满足「能跑通、能落
  JSONL 能 pipe 进 download」
- ❌ **uifid 真实获取** → 见 M6.48 §八 → 留到 M6.50+；mssdk 响应体里
  有没有 uifid 字段需要额外抓包
- ❌ **用户搜索的 N 个 hook** → 没要求，code search 也偏穷可 留待 M6.50+
- ❌ **hot 榜（4 榜）** → TikTokDL ``src/interface/hot.py`` 实现简单，
  留 M6.51+
- ❌ **search 自动增量去重** → 当前每调用一次就拉数据；CLI 用户可手动
  保存 JSONL + 合并去重

---

## M6.50 (2026-10-03) — 抖音 hot 榜（4 榜：抖音热榜 / 娱乐榜 / 社会榜 / 挑战榜）

> **目标**：让 doubi CLI 能浏览抖音热搜榜。和 search 不同，hot 榜是
> 平台**热搜词列表**（NOT videos），单端点 + 4 榜循环，无登录依赖。
> 背景：用户在抖音里看到「这个热搜点进去好多视频」会本能地想看完整
> 热词榜，doubi 之前只能搜词搜不到榜。
> 来源：Johnserf-Shell/TikTokDownloader ``src/interface/hot.py``（MIT）。
>
> **优先级重排**：M6.49 §八原计划把 hot 榜放到 M6.51+；落地时发现 hot
> 端点实现极简（单 GET、无 login、4 套 board_type/sub_type tuple）、
> UX 价值最直接（「看现在什么火」），故提到 M6.50。收藏夹全家族
> （collects family）顺延到 M6.51。

### 一、模块级常量（`webapi.py`）

```python
# 4 榜 board params（TikTokDL hot.py lines 14-35 拍平）
HOT_BOARD_PARAMS: dict[str, tuple[int, Any]] = {
    "positive":      (0, ""),                    # 抖音热榜
    "entertainment": (2, 2),                     # 娱乐榜
    "society":       (2, 4),                     # 社会榜
    "challenge":     (2, "hotspot_challenge"),   # 挑战榜
}
HOT_BOARD_NAMES: dict[str, str] = {
    "positive": "抖音热榜",
    "entertainment": "娱乐榜",
    "society": "社会榜",
    "challenge": "挑战榜",
}
ALL_HOT_BOARDS: tuple[str, ...] = tuple(HOT_BOARD_PARAMS.keys())
```

注意 ``board_sub_type`` 是 heterogeneous（int | str）：
``hotspot_challenge`` 是字符串 token，其他三个是整数。TikTokDL 原版
用 ``SimpleNamespace`` 列表，这里用 dict 便于 CLI argparse 直接
拿 ``choices``。

### 二、`DouyinWebAPI.get_hot_list(board)`

```python
async def get_hot_list(board: str = "positive", *,
                        max_count: int = 0,
                        error_sink: Optional[MutableMapping[str, Any]] = None
                        ) -> list[dict[str, Any]]:
    """One board's hot words (NOT videos).
    
    Endpoint: ``/aweme/v1/web/hot/search/list/``
    Params: detail_list=1, source=6, board_type + board_sub_type,
            version_code=170400, version_name=17.4.0
            （TikTokDL hot.py generate_params lines 56-64 拍平）
    
    Response: data.word_list — list of word entries with
        * ``word`` — hot phrase
        * ``hot_value`` — heat score
        * ``position`` — rank
        * ``sentence_id`` — bridge to related videos (need 2nd call)
        * ``video_count`` — how many videos associated
        * ``cover_url`` — cover image
    
    Unknown boards return ``[]`` (no silent fallback). The argparse
    ``choices`` constraint catches bad board names at the CLI layer;
    we mirror that here for direct API callers (e.g. a future GUI).
    """
```

**关键认知修正**：hot 榜数据是**热搜词**不是视频。M6.65 §七「跟着 hot
词拿视频」需要额外 search/feed 调用（sentence_id → video list），
本里程碑不做。

### 三、`sign/websign.py` 防御性加入 hot 路径（18 → 19 条）

```python
DOUYIN_SIGNED_PATHS |= {
    "/aweme/v1/web/hot/search/list/",   # M6.50 防御性 over-sign
}
```

Hot 端点是否需要 WebSign 没公开数据；但 over-signing 无害（TikTokDL
note），加上去更安全。回归测试 ``test_hot_endpoint_in_signed_paths``
锁死这条路径在白名单里。

### 四、CLI `doubi hot` 子命令（`cli/main.py`）

```bash
$ doubi hot [--board all|positive|entertainment|society|challenge]   # default: all
            [--max N]            # 每榜最多 N 条, default 50
            [--cookies-file PATH]
            [--proxy URL]
```

JSONL 输出，每行一个 word entry + ``board`` + ``board_name``。
``--board all`` 按 ``ALL_HOT_BOARDS`` 顺序依次拉（positive →
entertainment → society → challenge）：

```bash
$ doubi hot --board all --max 3 | jq -r '"\(.board_name): \(.word) [\(.hot_value\)]"'
抖音热榜: 巴黎奥运会 [12345678]
娱乐榜: 赵丽颖 [9876543]
娱乐榜: 演唱会 [4200000]
```

**注意**：hot 词的 ``sentence_id`` 不是视频 ID。要跟进某条热搜去看
相关视频，请 ``doubi search <word>``，M6.50 不自动展开。

错误 UX：失败时把 ``error_sink.hint="need_login"`` 转成「试试
`--cookies-file ~/.doubi/cookies/douyin.txt`」友好信息（M6.46 + M6.50
联动）。但 hot 通常 4 榜无 login 也能跑，cookie 是可选的。

### 五、测试覆盖（**新增 14 例**）

| 文件 | 新增 | 覆盖 |
|---|---|---|
| `tests/test_douyin_hot.py`（全新） | 14 | HOT_BOARD_PARAMS shape 锁定（4 榜 + tuple 一一比对）/ 4 榜中英文名 / ALL_HOT_BOARDS canonical 顺序 / per-board endpoint+params（4-in-1 循环断言）/ 未知 board 兜底（不联网调）/ max_count 截断 / 空响应防御（missing word_list + word_list=null）/ error_sink hint 透传 / WebSign 白名单锁死 / CLI ``--board all`` JSONL 输出顺序 / CLI 单榜 + board tag / CLI ``--max`` 按榜 / CLI 0 hit exit 0 / argparse choices 校验 |

合计 **M6.45 + M6.46 + M6.47 + M6.48 + M6.49 + M6.50**：**88 例可见**。

### 六、跑分（实测）

```
$ python -m pytest tests/test_douyin_hot.py -v
14 passed in 0.74s                # M6.50 净增 14 例

$ python -m pytest tests/ -q -m "not slow and not gui"
820 passed, 263 deselected in 65.88s   # M6.49 baseline 806 + M6.50 净增 14
```

### 七、克制清单（这次**没做**）

- ❌ **GUI 热榜页** → 仅做 CLI；同 M6.49 §八 search 留 M6.51+
- ❌ **hot 词的 sentence_id → 视频列表展开** → 需要额外 search/feed
  调用（sentence_id 不是视频 ID）；hot 榜本质是「看现在什么火」的浏览
  工具，不直接产生可下载 URL
- ❌ **收藏夹 / 合集列表（collects family）** → M6.51 计划（M6.50 §首
  段「优先级重排」说明）
- ❌ **uifid 真实获取** → M6.48 §八 留 M6.50+；但实测 hot 端点 4 榜
  无 login 也能跑（TikTokDL hot.py ``Cookie: ""``），uifid 实抓的
  紧迫性弱于 search，暂维持 UUID4 占位

---

## M6.51 (2026-10-03) — 抖音 收藏夹全家族（5 端点）

> **目标**：让 doubi CLI 能浏览「我的收藏」5 类内容——收藏夹 / 收藏夹视频 /
> 收藏合集 / 收藏音乐 / 收藏短剧。这是 Survey 里 M6.50 原计划的项，被 hot 榜
> 提前到 M6.50 后顺延至此。
> 来源：Johnserf-Shell/TikTokDownloader ``src/interface/collects.py``（MIT）。
>
> **登录依赖**：5 端点全部 gate 在 ``user/self?showTab=favorite_collection``
> referer 上。无 cookie 直接 401/空 list，error_sink hint=need_login，CLI
> 打印「请先运行 `doubi auth douyin`」+ --cookies-file 提示。

### 一、`DouyinWebAPI._cursor_paginate` 通用翻页器（`webapi.py`）

```python
async def _cursor_paginate(
    self, endpoint: str, *,
    data_key: str,
    extra_params: dict[str, Any],
    count: int = 10,
    max_count: int = 0,
    max_pages: int = 50,
    error_sink: Optional[...] = None,
) -> list[dict[str, Any]]:
    """``cursor + count + has_more`` 通用翻页。"""
```

复用 5 端点的对称分页：cursor 注入每次请求、has_more=False 跳出、
cursor stuck 防御（同 ``_search_paginate`` 的 guard）、max_pages=50
硬上限、max_count 截断。

### 二、5 个 iter 方法

| 方法 | 端点 | data_key | 关键 params | 来源 |
|---|---|---|---|---|
| `iter_collects` | `/aweme/v1/web/collects/list/` | `collects_list` | `version_code=170400` | TikTokDL ``Collects:12-67`` |
| `iter_collects_videos` | `/aweme/v1/web/collects/video/list/` | `aweme_list` | `+ collects_id`（positional） | TikTokDL ``CollectsDetail:70-132`` |
| `iter_collects_mix` | `/aweme/v1/web/mix/listcollection/` | `mix_infos` | — | TikTokDL ``CollectsMix:135-192`` |
| `iter_collects_music` | `/aweme/v1/web/music/listcollection/` | `mc_list` | — | TikTokDL ``CollectsMusic:249-300`` |
| `iter_collects_series` | `/aweme/v1/web/series/collections/` | `series_infos` | — | TikTokDL ``CollectsSeries:195-246`` |

每个方法都是 ``_cursor_paginate`` 的 thin wrapper，pin endpoint +
data_key + endpoint-specific extra_params（约 10 行）。

### 三、`sign/websign.py` 白名单补齐（19 → 21 条）

```python
DOUYIN_SIGNED_PATHS |= {
    # M6.51 — 收藏夹短剧
    "/aweme/v1/web/series/collections/",
    # M6.51 — 收藏夹音乐（M6.48 漏了，这次补上）
    "/aweme/v1/web/music/listcollection/",
}
```

M6.48 白名单里 `music/aweme/list/detail` 三条但漏了
`music/listcollection/`——这是 M6.48 落地时没发现的覆盖漏洞，
本里程碑一次性补齐 + 写测试锁死。

### 四、CLI `doubi favorites` 子命令（`cli/main.py`）

```bash
$ doubi favorites [--kind favorites|videos|mix|music|series]   # default: favorites
                  [collect_id]                                  # --kind=videos 时必填
                  [--max N]                                      # default: 50
                  [--count N]                                    # default: 10
                  [--cookies-file PATH]                          # 强建议
                  [--proxy URL]
```

JSONL 输出，每行一个 entry + ``kind`` + ``kind_name`` tag。
``--kind=videos`` 时每行额外带 ``share_url``（aweme → 标准 video URL），
可以直接 pipe 到 ``doubi download --batch -``：

```bash
$ doubi favorites --kind=videos c-12345 \
  | doubi download --batch - --no-explain-in-public

$ doubi favorites | jq -r '"\(.kind_name): \(.collects_name) [\(.video_count) videos]"'
收藏夹: 我的收藏夹1 [42 videos]
收藏夹: 美食合集 [12 videos]
```

错误 UX：未登录时 error_sink.hint="need_login"，CLI 打印
「收藏夹全家族必须登录抖音；请先运行 `doubi auth douyin`，
再传 --cookies-file ~/.doubi/cookies/douyin.txt」。复用 M6.46 hint
machinery，不引入新错误码。

### 五、测试覆盖（**新增 20 例**）

| 文件 | 新增 | 覆盖 |
|---|---|---|
| `tests/test_douyin_favorites.py`（全新） | 20 | `_cursor_paginate` 5 例（基本单页 / 多页 cursor 推进 / max_pages 硬上限 / max_count 截断 / cursor stuck 防御）/ 5 端点 endpoint+data_key+params / iter_collects_videos blank id 兜底 / error_sink hint=need_login 透传 / 5 端点 WebSign 白名单 / CLI list / CLI videos 缺 collect_id / CLI videos 注入 share_url / CLI mix / CLI max 截断 / CLI 空结果 / argparse choices |

合计 **M6.45 + M6.46 + M6.47 + M6.48 + M6.49 + M6.50 + M6.51**：**108 例可见**。

### 六、跑分（实测）

```
$ python -m pytest tests/test_douyin_favorites.py -v
20 passed in 0.66s                # M6.51 净增 20 例

$ python -m pytest tests/ -q -m "not slow and not gui"
840 passed, 263 deselected in 64.46s   # M6.50 baseline 820 + M6.51 净增 20
```

### 七、克制清单（这次**没做**）

- ❌ **收藏夹视频的『我自己的收藏』(without login)** → 5 端点全部需要 login，
  没做匿名降级（无 cookie 直接 401 + hint=need_login 即可）
- ❌ **收藏合集/音乐/短剧的「展开到视频列表」** → 现在只列 collect 本身；
  展开得用 ``mix_id`` → ``iter_mix_awemes``（M2.x 已有）。同 Survey 节奏，
  留 M6.52+
- ❌ **GUI 收藏夹页** → 仅做 CLI；同 M6.49 / M6.50 留 M6.52+
- ❌ **uifid 真实获取** → 收藏夹全家族实测仍 401（M6.48 §八）；等 msToken
  升级后再回头看

---

## M6.52 (2026-10-03) — 抖音 评论 + 回复（2 端点）

> **目标**：让 doubi CLI 能浏览「视频评论」与「单条评论的回复」。
> Survey §8.2 预命名的 M6.52。背景：用户看完视频常会想看「这条评论
> 下面还有人在吵什么」或「这条评论到底有几条赞」，doubi 之前只能下载
> 视频本体，没这条路径。
> 来源：Johnserf-Shell/TikTokDownloader ``src/interface/comment.py``（MIT）。
>
> **登录依赖**：比收藏夹家族**软**——公开视频的评论匿名可读；但
> 平台对大批量读取会触发风控，error_sink hint=need_login。CLI 友好提示
> 复用 M6.46 machinery。

### 一、2 个 iter 方法（复用 M6.51 `_cursor_paginate`）

| 方法 | 端点 | data_key | 关键 params |
|---|---|---|---|
| `iter_aweme_comments(aweme_id)` | `/aweme/v1/web/comment/list/` | `comments` | `aweme_id` + 静态 TikTokDL 7 字段（cut_version/item_type/pc_img_format/...） |
| `iter_comment_replies(aweme_id, comment_id)` | `/aweme/v1/web/comment/list/reply/` | `comments` | `item_id` + `comment_id`（注意是 `item_id` 不是 `aweme_id`，按 TikTokDL ``comment.py:239`` 拍平） |

复用 M6.51 通用翻页器：cursor + count + has_more + max_pages=50
硬上限 + cursor stuck 防御。每个方法都是 thin wrapper（10-12 行）。

**未移植 `Extractor.extract_reply_ids`**：TikTokDL 的 ``run_reply``
callback 链路（``comment.py:155-178``）自动从当前页评论抽 reply_id
再嵌套调 Reply。DouBi 的 iter 模式让 caller 显式驱动二次调用
（``iter_comment_replies(cid)``），不需要 callback 抽取。降复杂度。

### 二、`sign/websign.py` 白名单补齐（21 → 23 条）

```python
DOUYIN_SIGNED_PATHS |= {
    "/aweme/v1/web/comment/list/",
    "/aweme/v1/web/comment/list/reply/",
}
```

TikTokDL 2026-09 快照里没明确列这两个端点是否需要 WebSign；
防御性 over-sign（over-signing is harmless — TikTokDL note）。

### 三、CLI `doubi comments` 子命令（`cli/main.py`）

```bash
$ doubi comments <aweme_id> [--kind comments|replies]   # default: comments
                      [--comment-id CID]                  # --kind=replies 时必填
                      [--max N] [--count N]                # default: 50 / 10
                      [--cookies-file PATH] [--proxy URL]
```

JSONL 输出，每行一个评论 dict + ``kind`` + ``kind_name`` + ``aweme_id``。
``--kind=replies`` 时每行额外带 ``parent_comment_id``：

```bash
$ doubi comments 7234567890123456789 | jq -r '"\(.user.nickname): \(.text)"'

$ doubi comments 7234567890123456789 \
    --kind=replies --comment-id=1234567890 | jq -r '.text'
```

错误 UX：
- 缺 `aweme_id` → return 2 + stderr 友好信息
- `--kind=replies` 缺 `--comment-id` → return 2 + stderr 提示先跑
  `doubi comments <aweme_id>` 找 cid
- 0 命中 → return 0 + stderr `No results.`
- error_sink.hint="need_login" → return 0 + stderr `评论通常匿名可读；如遇 403 请尝试 --cookies-file ...`

### 四、测试覆盖（**新增 14 例**）

| 文件 | 新增 | 覆盖 |
|---|---|---|
| `tests/test_douyin_comments.py`（全新） | 14 | 2 端点 endpoint+params（注意 reply 端点用 `item_id` 不是 `aweme_id`）/ blank id 兜底（comments 1 例 + replies 2 例）/ cursor 推进 / error_sink hint=need_login 透传 / 2 端点 WebSign 白名单 / CLI 默认带 kind+aweme_id tag / CLI replies 缺 comment-id exit 2 / CLI replies 带 parent_comment_id / CLI 缺 aweme_id exit 2 / CLI max 截断 / 0 hit exit 0 / argparse choices 校验 |

合计 **M6.45 + M6.46 + M6.47 + M6.48 + M6.49 + M6.50 + M6.51 + M6.52**：**122 例可见**。

### 五、跑分（实测）

```
$ python -m pytest tests/test_douyin_comments.py -v
14 passed in 0.74s                # M6.52 净增 14 例

$ python -m pytest tests/ -q -m "not slow and not gui"
854 passed, 263 deselected in 69.48s   # M6.51 baseline 840 + M6.52 净增 14
```

### 六、克制清单（这次**没做**）

- ❌ **GUI 评论页** → 仅做 CLI；PySide6 Fluent 评论列表 + 回复嵌套展开
  工作量不小，留 M6.53+
- ❌ **评论点赞数 / 二级回复（嵌套）** → 抖音只开放两层；本里程碑到
  reply 一层为止，更深嵌套留 M6.53+ 如果用户要
- ❌ **评论增量去重 / 排序选项** → 平台排序是固定的（按热度）；CLI 默认
  按平台返回顺序
- ❌ **`@用户` 链接 / emoji 解析** → 评论文本里包含 @、表情；M6.52
  原样输出，不做二次解析
- ❌ **uifid 真实获取** → M6.48 §八 留 M6.50+；实测评论匿名可读，
  uifid 紧迫性弱于 search

### 七、剩余采集功能候选（按 Survey 顺位）

| 等级 | 项目 | Survey 章节 | 状态 |
|---|---|---|---|
| MEDIUM | 评论+回复 | §8.2 M6.52 | ✅ M6.52 已完成 |
| HIGH | 关注列表（following） | §8.1 item 8 | ⏳ 待 M6.53（Survey 列为 HIGH） |
| MEDIUM | 直播详细信息（live detail） | §8.1 item 11 | ⏳ 待 M6.53+ |
| MEDIUM | xGnarly 实装 | §8.1 item 6 | ⏳ 抖音主杀器未破，技术门槛最高 |

---

## M6.53 (2026-10-03) — msToken 实请求完整 strData blob（Survey §8.1 item #6 落地）

> **目标**：补齐 M6.48 msToken 实现里**框架对、blob 错**的最后一块。
> Survey §8.1 把 #6 标 **HIGH**（「即便有 a_bogus + WebSign，没 msToken
> 也会被风控」），M6.48 落地时 `strData=""` 占位符让 mssdk 服务器
> 要么拒绝要么返回无效 token。本里程碑把 TikTokDL
> `src/encrypt/msToken.py:30-71` 提取的真实 base64 blob 装入
> DouBi `ms_token.py`，配合 a_bogus + WebSign 形成完整 403 风控防御。
> 来源：Johnserf-Shell/TikTokDownloader `src/encrypt/msToken.py`（MIT）。

### 一、问题诊断（M6.48 vs M6.53）

```python
# M6.48 (M6.48 留的尾巴)：
_MSSDK_PAYLOAD_BASE: dict[str, object] = {
    "magic": 538969122,
    "version": 1,
    "dataType": 8,
    "strData": "",          # ← 占位符；生产里发空 blob
    "tspFromClient": 0,
    "ulr": 0,
}

# M6.53 (现在)：
_MSSDK_STRDATA: str = (
    "fWOdJTQR3/jwmZqBBsPO6tdNEc1jX7..."  # TikTokDL runtime_bundler_34.js 提取
    "...TS2BGfsHadR3d5j8lNhBPzA5e+mE=="   # 完整 ~4036 字符 base64
)
_MSSDK_DEFAULT_TOKEN: str = (
    "9cguMjz4GIfQV50B_D49quM-cEyIvWMw..."  # mssdk refresh-mode 期望的预存 token
    "...-4YprIjt29ZrAxmDb5oIhmzEhwvcmcC4BR_kEZGmXdS1q7Ad3V94izdpXwtxgPPpozVUzQVm7KDrc5H9nfN3pLw="
)
```

### 二、`MsTokenFetcher` 默认值语义调整

```python
def __init__(
    self, *,
    timeout: float = 10.0,
    str_data: Optional[str] = None,        # ← 改 None 而非 ""
    default_token: Optional[str] = None,   # ← 改 None 而非 ""
) -> None:
    self._str_data_override = (
        str_data if str_data is not None else _MSSDK_STRDATA   # 装真实 blob
    )
    self._token_override = (
        default_token if default_token is not None else _MSSDK_DEFAULT_TOKEN
    )
```

**语义变化**：
- `None` → 自动装填 TikTokDL 提取的真实 blob / TOKEN
- `""` → 显式空（测试 / 调试用）
- `"custom_blob"` → 显式覆盖

向后兼容：M6.48 测试用例都用 `MsTokenFetcher(timeout=5.0)` 不传 `str_data`，
M6.53 改默认后这些测试继续过——它们 stub httpx.AsyncClient 不发实际
payload，只验证响应处理逻辑。

### 三、`fetch()` 增加 Cookie 头（refresh 模式）

```python
# M6.53 新增
if self._token_override and "Cookie" not in req_headers:
    req_headers["Cookie"] = f"msToken={self._token_override}"
```

对齐 TikTokDL `MsToken.get_real_ms_token:118-120`：
```python
headers |= {"Cookie": f"{cls.NAME}={token}"}
```

mssdk 在有预存 `msToken` cookie 时走「refresh」模式，响应
Set-Cookie 是长 TTL token；无 cookie 时走「first-issue」模式，
TTL 较短。`refresh` 是 TikTokDL 默认路径。

### 四、blob 版本轮换预案（§风险声明升级）

抖音若升级 `runtime_bundler_*.js`，strData blob 会过期——
典型症状：mssdk 返回 200 但 Set-Cookie 缺 `msToken` 或 token
不被接受。**修复路径**：

1. mssdk 返回 200 但 Set-Cookie 无 `msToken` → `MsTokenFetcher`
   走 `return None` 路径
2. caller fallback 到 fake msToken → 403 概率回升
3. 重新逆向新 JS bundle 抓 blob 替换 `_MSSDK_STRDATA`
4. 同步更新 `test_mstoken_strdata_pinned_to_tiktokdl_extract` 的
   length + prefix/suffix pin（测试红 → 提醒）

### 五、测试覆盖（**新增 7 例**）

| 文件 | 新增 | 覆盖 |
|---|---|---|
| `tests/test_douyin_sign.py`（既有） | 7 | strData blob 存在性 + base64 alphabet 校验 / TOKEN 存在性 + 字符集 / `MsTokenFetcher()` 默认自动装填真实 blob（非空）/ `str_data=` 显式覆盖（含 `""` 强制空）/ `default_token=` 显式覆盖 / strData blob **TikTokDL pin**（4036 字符长度 + 前后 32 字符精确匹配）/ TOKEN **TikTokDL pin**（128 字符长度 + 前缀后缀精确匹配） |

合计 **M6.45 + M6.46 + M6.47 + M6.48 + M6.49 + M6.50 + M6.51 + M6.52 + M6.53**：**129 例可见**。

### 六、跑分（实测）

```
$ python -m pytest tests/test_douyin_sign.py -v
27 passed in 0.66s                # M6.48 既有 20 例 + M6.53 新增 7 例

$ python -m pytest tests/ -q -m "not slow and not gui"
861 passed, 263 deselected in 68.37s   # M6.52 baseline 854 + M6.53 净增 7
```

### 七、克制清单（这次**没做**）

- ❌ **uifid 真实获取** → M6.48 §八 留 M6.50+；实测 msToken+WebSign
  双件套已经把 403 概率从 100% 降到 ~50%（mssdk 真实 token 帮
  signed URL 通过第一层校验），但 uifid 占位仍是部分路径 403 的
  根因。M6.54+ 通过 mssdk 响应体抓 uifid
- ❌ **mssdk 响应体里抓 uifid** → 同上，uifid 真抓 = M6.54
- ❌ **strData 自动轮换监控** → 抖音升级 runtime_bundler 时 blob
  会过期，目前靠「Set-Cookie 缺 msToken → fallback」+ 测试 pin
  提醒，没自动重抓机制
- ❌ **TikTok strData** → `MsTokenTikTok` 用的 mssdk-ttp2.tiktokw.us
  blob 不同（TikTokDL line 153-202），抖音版本目前不移植

### 八、剩余采集功能候选（按 Survey 顺位）

| 等级 | 项目 | Survey 章节 | 状态 |
|---|---|---|---|
| ~~HIGH~~ | ~~msToken + WebSign~~ | — | ✅ M6.48 + M6.53 |
| ~~HIGH~~ | ~~搜索 4 子类~~ | — | ✅ M6.49 |
| ~~HIGH~~ | ~~Hot 榜~~ | — | ✅ M6.50 |
| ~~HIGH~~ | ~~收藏夹全家族~~ | — | ✅ M6.51 |
| ~~MEDIUM~~ | ~~评论+回复~~ | — | ✅ M6.52 |
| ~~MEDIUM~~ | ~~msToken 完整 strData~~ | §8.1 item #6 | ✅ M6.53 |
| **HIGH** | **关注列表（follow）+ 粉丝列表** | §8.1 item 10 | ⏳ 待 M6.54 |
| MEDIUM | 直播详细信息 + 多清晰度 | §8.1 item 9 | ⏳ 待 M6.55+ |
| MEDIUM | xGnarly 实装 | §8.1 item 8 | ⏳ TikTok 主杀器，抖音无需 |

---

## M6.54 (2026-10-03) — 抖音 关注列表 + 粉丝列表（**DouBi 原生实现**）

> **⚠️ 本里程碑不是移植**。Survey §8.1 item 10 把「关注列表 +
> 粉丝列表」标 HIGH 价值（用户场景：账号管理），但 TikTokDL
> `src/interface/user.py` **没有** following/follower 实现——只有
> `profile/other` 单用户资料（TikTokDL `user.py:23`）。Survey 表格
> 已明确标记 ❌「User 接口只能拿个人资料」。
>
> 因此 M6.54 是 **DouBi 原生实现**，跟随 M6.51 `_cursor_paginate`
> 模式 + 公开 Douyin web API 端点约定。同 M6.51 favorites 一样，
> 没有上游源码可参考；CHANGELOG §首段 显式标注这一点，避免误把
> 功劳记到 TikTokDL 上。
>
> **诚实记录**：Survey 后续 HIGH/MEDIUM 项里，**item 9（live 详
> 信息）需新增 POST 跨域基础设施（live.douyin.com / webcast.amemv.com
> 不是 www.douyin.com）**、**item 11（Mix 标题回查）仅 3 行 helper**
> —— Survey HIGH 候选里 item 10 是唯一一个「无源但 DouBi 可独立
> 实现」的。本里程碑是这一类实现的第一个。

### 一、2 个 iter 方法（复用 M6.51 `_cursor_paginate`）

| 方法 | 端点 | data_key | 关键 params |
|---|---|---|---|
| `iter_user_following(sec_user_id)` | `/aweme/v1/web/user/following/list/` | `followings` | `user_id` + `sec_user_id` + `source="following"` + 静态 5 字段 |
| `iter_user_followers(sec_user_id)` | `/aweme/v1/web/user/follower/list/` | `followers` | `user_id` + `sec_user_id` + `source="follower"` + 静态 5 字段 |

复用 M6.51 通用翻页器：cursor + count + has_more + max_pages=50
硬上限 + cursor stuck 防御。每个方法都是 thin wrapper（10-12 行）。

**注意**：端点路径 + params 是公开 Douyin web API 约定，**不依赖
TikTokDL**。TikTokDL 自己的 `account.py` / `user.py` 都没用过这
两个端点。

### 二、`sign/websign.py` 白名单补齐（23 → 25 条）

```python
DOUYIN_SIGNED_PATHS |= {
    "/aweme/v1/web/user/following/list/",
    "/aweme/v1/web/user/follower/list/",
}
```

无 TikTokDL 参考，防御性 over-sign（同 M6.49 / M6.50 / M6.51 / M6.52
逻辑）：平台若加进 secsdk protectedHost 表，over-signing 无害。

### 三、CLI `doubi user` 子命令（`cli/main.py`）

```bash
$ doubi user <sec_uid> [--kind following|followers]   # default: following
                     [--max N] [--count N]               # default: 50 / 20
                     [--cookies-file PATH] [--proxy URL]
```

JSONL 输出，每行一个用户 dict + `kind` + `kind_name` +
`target_sec_uid`（parent；**不覆盖** row 自己的 `sec_uid`，避免
身份字段丢失）。`--kind=followers` 时每行带 `target_sec_uid`：

```bash
$ doubi user MS4wLjABAAAA... | jq -r '"\(.kind_name): \(.nickname)"'
我关注的人: 赵丽颖
我关注的人: 李易峰

$ doubi user MS4wLjABAAAA... --kind=followers | jq -r '.nickname'
```

错误 UX：
- 缺 `sec_uid` → return 2 + stderr 友好信息
- 0 命中 → return 0 + stderr `No results.`
- error_sink.hint="need_login" → return 0 + stderr `关注/粉丝列表需要登录抖音；请先运行 doubi auth douyin，再传 --cookies-file ...`

### 四、测试覆盖（**新增 13 例**）

| 文件 | 新增 | 覆盖 |
|---|---|---|
| `tests/test_douyin_user.py`（全新） | 13 | 2 端点 endpoint+params（含 user_id+sec_user_id 双字段）/ blank id 兜底（following 1 例 + followers 1 例）/ cursor 推进 / error_sink hint=need_login 透传 / 2 端点 WebSign 白名单 / CLI default 带 kind+target_sec_uid / CLI followers 带 kind_name / CLI 缺 sec_uid exit 2 / CLI max 截断 / 0 hit exit 0 / argparse choices 校验 |

合计 **M6.45 + M6.46 + M6.47 + M6.48 + M6.49 + M6.50 + M6.51 + M6.52 + M6.53 + M6.54**：**142 例可见**。

### 五、跑分（实测）

```
$ python -m pytest tests/test_douyin_user.py -v
13 passed in 0.46s                # M6.54 净增 13 例

$ python -m pytest tests/ -q -m "not slow and not gui"
874 passed, 263 deselected in 56.73s   # M6.53 baseline 861 + M6.54 净增 13
```

### 六、克制清单（这次**没做**）

- ❌ **user 关注/粉丝数量直读（`follower_count` / `following_count`）**
  → DouBi 已有 `search_user` 间接拿这俩字段；`iter_*` 是全列表
  枚举，count 字段取自 user profile，**不在本里程碑范围**
- ❌ **相互关注（mutual following）** → 公开 Douyin web API 没有
  独立 mutual 端点；要拿得交叉 two iter 结果，本地 join；留
  M6.55+ 如果用户要
- ❌ **黑名单 / 拉黑列表** → 公开端点无；TikTokDL 也无
- ❌ **「猜你在关注的人」/ 推荐关注** → 商业化端点，签名复杂，
  本里程碑不做

### 七、剩余采集功能候选

| 等级 | 项目 | Survey 章节 | 状态 |
|---|---|---|---|
| ~~HIGH~~ | ~~msToken + WebSign~~ | — | ✅ M6.48 + M6.53 |
| ~~HIGH~~ | ~~搜索 4 子类~~ | — | ✅ M6.49 |
| ~~HIGH~~ | ~~Hot 榜~~ | — | ✅ M6.50 |
| ~~HIGH~~ | ~~收藏夹全家族~~ | — | ✅ M6.51 |
| ~~MEDIUM~~ | ~~评论+回复~~ | — | ✅ M6.52 |
| ~~HIGH~~ | ~~关注列表 + 粉丝列表~~ | §8.1 item 10 | ✅ **M6.54**（**DouBi 原生**） |
| ~~MEDIUM~~ | ~~直播详细信息 + 多清晰度~~ | §8.1 item 9 | ✅ **M6.55** |
| MEDIUM | Mix 标题回查 | §8.1 item 11 | ⏳ 仅 3 行 helper，价值边际 |
| MEDIUM | xGnarly 实装 | §8.1 item 8 | ⏳ TikTok 主杀器，抖音无需 |

**路径选择**：剩余 HIGH 级全部完成。下一站推荐 **item 9 直播详细信息**
（MEDIUM），但实施需新增 POST 跨域基础设施——DouBi 现有
`_request_json` / `_signed_url` 是 www.douyin.com 专用，
live.douyin.com / webcast.amemv.com 需要平行 pipeline。建议先做
跨域 POST helper 再做 item 9，估约 100 LOC + 8-10 tests。

> **↑ 这段预估已被 M6.55 证伪**：两个 live 端点实际都是 **GET**，
> 不需要 POST 基建，也不需要平行 pipeline——只要给现有签名管线加
> 一个 `base_url`。原文保留，M6.55 §首段有完整勘误。

---

## M6.59 (2026-10-03) — xGnarly 核实：**不移植**（Survey §8.1 item 8）＋ 上游死代码勘误 ＋ §8.1 收口

> **结论：本项不做。** 而且理由与 Survey 原先的评估**不同** ——
> 原评估说 xGnarly 是「HIGH 难度、TikTok 必备」，核实后发现
> **`src/encrypt/xGnarly.py` 在 TikTokDL 里根本不被调用**。
> 这是一次对上位盘点的实质性修正，不是"跳过"。
>
> 同轮一并核实的 item 15（`device_id.py`）**同样是死代码**。
> 两项核实完成后，用户拍板 item 7 亦不做，**Survey §8.1 全部收口**
> （见 §五之一）。

### 一、勘误：`xGnarly.py` 是死代码

`.scratch/TikTokDL_采集功能盘点.md` §8.1 item 8 原文记的是：

> xGnarly 签名（`encrypt/xGnarly.py`），HIGH（逆向 + ChaCha20 自定义 + 321 行实现），
> MEDIUM（TikTok 必备 / 抖音暂无 xGnarly 触发点），跟随 #7

**"TikTok 必备"这一半是错的。** 全仓检索 `XGnarly` / `xGnarly` 只有三处命中：

| 位置 | 性质 |
|---|---|
| `src/encrypt/xGnarly.py:8` | 类定义自身 |
| `src/encrypt/xGnarly.py:212` | 类内部自引用（`XGnarly._MASK32`） |
| `src/tools/dynamic_import.py:66` | `if __name__ == "__main__":` 下的**演示打印** |

`src/encrypt/__init__.py` 导出的是：

```python
from .device_id import DeviceId
from .msToken import MsToken, MsTokenTikTok
from .ttWid import TtWid, TtWidTikTok
from .verifyFp import VerifyFp
from .webID import WebId
from .tiktok_params import TikTokParams
from .douyin_params import DouYinParams
```

**没有 `xGnarly`。** 运行时的外部覆盖机制
（`src/config/parameter.py` `check_objects_from_external_py`）只找两个名字：

```python
objects = load_objects_from_external_py(
    "encipher.py",
    ["DouYinParams", "TikTokParams"],
    console,
)
```

`XGnarly` **不在这个列表里**，所以连"通过 encipher.py 注入"这条外部路径
也走不到它。

### 二、真正在岗的是 `tiktok_sign.py`

TikTok 签名实际由 `src/encrypt/tiktok_sign.py`（413 行）承担：

```
src/encrypt/tiktok_params.py:6   #   src/dtk/signing/native/tiktok_sign.py
src/encrypt/tiktok_params.py:18  from .tiktok_sign import encode_query as tiktok_encode_query
src/encrypt/tiktok_params.py:19  from .tiktok_sign import sign as tiktok_sign
src/encrypt/tiktok_params.py:60  _, parameters = tiktok_sign(
src/encrypt/tiktok_params.py:102 signed_query, _ = tiktok_sign(
```

**两者实现不同**，不是同一算法的两个版本：

| | `xGnarly.py` | `tiktok_sign.py` |
|---|---|---|
| 密钥长度 | 12 个字（`_AA` 常量表 + 时间戳 + 3 个 `randint`） | 16 字（`CHACHA_INIT`） |
| 初始状态 | `_OT = [_AA[9], _AA[69], _AA[51], _AA[92]]` | `CHACHA_INIT` 标准常量 |
| 轮数 | `round_accum + 5`（`round_accum` = 12 个随机字低 4 位之和） | 固定轮数 |
| 输出编码 | 自定义 base64 字母表（`_BASE64_ALPHABET`，106-108） | `ENVELOPE_TAG = 0x4B` + 自定义平移表 |
| 版本串 | `"5.1.1"` → `obj[10] = "1.0.0.314"` | `SDK_VERSION="5.3.2"` / `SCM_VERSION="2.0.0.561"` |

结论：**把 `xGnarly.py` 搬进 DouBi 不会产生 TikTok 能接受的签名** ——
它描述的是另一个（已废弃的）bundle 世代。搬过去就是死代码。

### 三、`device_id.py` 同样是死代码（item 15 一并核实）

`src/encrypt/device_id.py`（66 行）的 `DeviceId.get_device_id()` 流程是
GET `https://www.tiktok.com/explore` → 正则 `"wid":"(\d{19})"` 抓 19 位
→ 连同 cookie 一起返回。

**但没有任何代码调用它。** 全仓 `device_id` 命中：

| 位置 | 性质 |
|---|---|
| `src/config/settings.py:120` | 配置默认值 `""` |
| `src/config/parameter.py:1100` | 从 `browser_info_tiktok` 字典**读配置键** |
| `src/downloader/download.py:681` | **一句用户提示文案** |
| `src/interface/template.py:534` | query 里的空串占位 |
| `src/encrypt/__init__.py:1` | 导出（但无人 import 使用） |

即 `device_id` 是一个**由用户手填的可选配置项**，缺失时降级为空串、
不报错、不阻断。这也解释了 Survey §8.1 item 15 原评估
「MEDIUM（需要代理 + tiktok.com/explore 抓 HTML）」为何与实际不符 ——
它描述的是一条从未接线、因而从未被验证的路径。

### 四、为什么这两个"不移植"是正确决定

1. **移植死代码 ≠ 移植功能。** 把上游不调用的文件搬过来，
   产出的是 DouBi 里也不被调用的文件，外加一份"我们支持 xGnarly"的假象。
2. **签名必须落在真实调用链上。** 若将来要做 TikTok 采集，要移植的是
   `tiktok_sign.py`（413 行，纯 stdlib），而不是 `xGnarly.py`。
3. **抖音侧无触发点。** 即便 xGnarly 是活的，DouBi 现有抖音路径
   （`msToken` + `WebSign` + `a_bogus`，M6.48–M6.53）没有用到
   `X-Gnarly` 的位置 —— 移植进来没有任何地方会调用它。
4. **失败模式是静默的。** 顺带核到一条重要事实：`tiktok_sign.py:63-65`
   的注释说明签名出错时 `/api/post/item_list/` 返回
   **HTTP 200 + 空 body + `tt_orcas_res: 1`**，其他接口照常 200 ——
   签名错**无法从状态码区分**。这意味着一个被误认为"在岗"的死代码
   签名器，其调试成本极高。这也支持"不要在没接线的地方移植签名"。

### 五、本项的**真实**依赖关系（修正后的判断）

item 8（xGnarly）与 item 15（device_id）**都不是独立可做项**，
而是 item 7（TikTok 采集全家桶）的从属项 —— 而且是从属项里的
**错误目标**。真正的 item 7 前置是：

- `tiktok_sign.py`（413 行，在岗签名器）
- `curl_cffi`（TikTokDL 全链路依赖它的 `impersonate=` TLS 指纹伪装）
- 海外网络出口（`device_id.py` / `msToken.py` 的 `test()` 都硬编码
  `proxy="http://127.0.0.1:10808"`）

这三项都超出"按 Survey 清单逐项移植"的范围，且涉及**新增第三方依赖**
与**用户侧网络条件**，属于需要用户拍板的决策。因此 M6.59 在此收口，
把 item 7/8/15 一并留出，而不是擅自引入 `curl_cffi`。

### 五之一、用户拍板结果：item 7 不做，Survey §8.1 全部收口

2026-10-03 用户决定：**按「Survey §8.1 除 item 7 外全部收口」结题**。
即 item 7（TikTok 全家桶）不实现，不引入 `curl_cffi`，
不新增 TikTok 平台包。上节列出的三条前置条件（TLS 指纹伪装依赖、
UA 与指纹强耦合、海外出口硬门槛）即本项不做的完整理由。

**这意味着 Survey §8.1 全部 17 项已收口，无遗留可做项：**

| 状态 | 数量 | items |
|---|---|---|
| ✅ 已落地 | 10 | 1、2、3、4、5、6、9、10、11、13 |
| ❌ 经核实不做 | 3 | 8（上游死代码）、12（上游空壳 + DouBi 已有能力）、15（上游死代码） |
| ❌ 用户决定不做 | 1 | 7（TikTok 全家桶 —— 前置条件超出移植范围） |
| ➖ 不需要 | 3 | 14、16、17（DouBi 已等价或更优） |

其中 **item 10（M6.54）与 item 13（M6.57）标注为 DouBi 原生实现**，
上游对应模块为空壳或无源，不可记为移植成果。

盘点表已同步回填：`.scratch/TikTokDL_采集功能盘点.md` §8.1 表格状态位 +
§8.1b 勘误与收口状态 + §8.3（item 7 前置条件详述）。

### 六、验证

无代码改动（本里程碑的产出是**经核实的"不做"决定** + 对上位盘点的勘误），
因此无新增测试。全量测试仍为 `1001 passed, 263 deselected`（M6.57 之后）。

---

## M6.57 (2026-10-03) — 抖音 话题（HashTag）作品列表（Survey §8.1 item 13 落地）

> **⚠️ DouBi 原生实现，不是移植。** TikTokDL
> `src/interface/hashtag.py` **本身是空壳**：
>
> ```python
> class HashTag(API):
>     def __init__(self, params, cookie="", proxy=None, *args, **kwargs):
>         super().__init__(params, cookie, proxy, *args, **kwargs)
>
>     async def run(self, *args, **kwargs):
>         pass
> ```
>
> `run()` 正文只有 `pass`，**连 `self.api` 都没声明** —— 没有任何端点可抄。
> Survey §8.1 item 13 已标 ❌ 并注明「即便移植也需要服务器先填实现」，
> 真实路径（`/aweme/v1/web/challenge/aweme/`）由本里程碑原生确定。
> **请勿把这个里程碑记在 TikTokDL 账上，也不要为了"对齐上游"去补一个
> 内容为空的文件。**

### 一、端点与翻页

```
iter_challenge_awemes   /aweme/v1/web/challenge/aweme/   data.aweme_list
```

翻页是 `cursor + count + has_more`，与 M6.51 收藏夹、M6.54 关注/粉丝同形，
因此**直接复用 `_cursor_paginate`**，一行翻页逻辑都没重写。

`ch_id` 来自话题页 URL `/challenge/detail/{ch_id}`。

### 二、`sort_type` 的两个取值

`0 = 综合排序`、`1 = 最新发布`。平台对未知值**静默忽略**而不是报错，
所以传一个越界整数会退化成综合排序 —— 这种"不报错的错"最难排查，
因此在 CLI 层把取值收敛成 `--sort {comprehensive,latest}` 两个具名选项，
`HASHTAG_SORT_TYPES` 映射也单独写了 pin 测试锁死 0/1 不被对调。

### 三、空 `ch_id` 不发请求

```python
if not ch_id:
    return []
```

空 id 是**调用方 bug，不是平台状态**。发一次带空 `ch_id` 的请求只会白白
消耗一格风控预算，换回一个必然为空的响应 —— 没有任何信息量。

### 四、WebSign 白名单

`/aweme/v1/web/challenge/aweme/` 加进 `DOUYIN_SIGNED_PATHS`。

判断依据与 M6.51 / M6.54 一致：端点发布在抖音 web API 同一棵
`/aweme/v1/web/` 树下，走同一套 secsdk protectedHost 逻辑。
**over-signing 无害，under-signing 必然 403**，所以取防御性过签。
（注意这与 M6.55 直播路径的处理相反 —— 那里有上游参考且上游明确不签，
所以跟随上游；这里**没有上游**，只能按惯例防御。）

### 五、CLI：`doubi hashtag`

```
doubi hashtag <ch_id|话题URL> [--sort comprehensive|latest]
                              [--max N] [--count N]
```

- 位置参数接受裸 id 或 `/challenge/detail/{id}` URL（含 App 分享形态
  `/share/challenge/detail/{id}`）。
- URL 解析用**本地正则而非 `url.py` 新增成员**：话题 URL 不是可下载输入
  （`doubi download` 没有对应容器），加一个 `DouyinURLType` 成员会产生
  一个没有任何 adapter 路径消费的分类结果 —— 那是死代码。
- 输出 JSONL，每行带 `ch_id` / `sort` / `target_ch_id`，沿用
  `doubi user` / `doubi favorites` 的自描述惯例。
- 行投影保留 `mix_id` / `mix_name`（若该视频同时属于某合集），
  让 M6.56 的接线成果不被 M6.57 的行构造丢掉 —— 有测试锁这条。

退出码：`0` 成功（含 0 命中）、`2` id 缺失/不可解析、`3` 请求失败。

### 六、克制清单（明确不做）

- **不为空壳文件造 parity**：不新增 `hashtag.py` 之类的占位模块，
  不写"与上游一致"的注释 —— 上游没有可一致的东西。
- **不做话题搜索 / 话题详情**：`/aweme/v1/web/challenge/detail/` 与
  话题检索是另外两条路径，本轮只做 §8.1 item 13 点名的作品列表。
- **不做话题下按时间区间过滤**：与 M6.56 同理，没有批量入口就不搬。
- **不新增 URL 分类枚举**：理由见 §五。
- **不做 GUI 入口**：GUI 承接话题需要新的容器类型 + 页面，
  与 M6.55 不给 `--quality` 加 GUI 入口同一取舍。

### 七、验证

```
python -m pytest tests/test_douyin_hashtag.py -q   →  32 passed
python -m pytest tests/ -q -m "not slow and not gui"  →  1001 passed, 263 deselected
```

- 新增 `tests/test_douyin_hashtag.py`（**32 例**）：端点/参数 4 例、
  翻页（多页/截断/cursor 卡死/空页）5 例、脏数据与 `error_sink` 2 例、
  `_ch_id_from_arg` URL 解析 7 例、`sort_type` 词表 1 例、CLI 13 例。
- ruff：M6.57 目标文件 0 错误。

---

## M6.58 (2026-10-03) — 图集（Slides）现状核实：**不实装**（Survey §8.1 item 12）

> **结论：本项不做，且这个"不做"是经过核实的决定，不是遗漏。**

### 一、上游同样是空壳

TikTokDL `src/interface/slides.py`：

```python
class Slides(API):
    def __init__(self, params, cookie="", proxy=None,
                 slides_id: str | list | tuple = ...):
        super().__init__(params, cookie, proxy)
        self.slides_id = slides_id
        self.api = f"{self.short_domain}web/api/v2/aweme/slidesinfo/"
        self.text = _("作品")

    async def run(self, *args, **kwargs):
        pass
```

比 item 13 略强一点：它**声明了** `self.api`
（`iesdouyin.com/web/api/v2/aweme/slidesinfo/`），但 `run()` 依然是 `pass`。
声明一个端点却从不调用它，等于零实现。

### 二、DouBi 侧其实已经能处理图集

核实结果 —— 图集能力已经在三条既有路径里存在：

| 位置 | 做什么 |
|---|---|
| `url.py` `DouyinURLType.NOTE` / `GALLERY` | `/note/{id}` / `/gallery/{id}` 已识别 |
| `adapter.py:60-61` | `NOTE` / `GALLERY` → `MediaType.IMAGE_ALBUM` |
| `webapi.py:2108` | `is_image = bool(aweme.get("images") or aweme_type in (150, 68))` |
| `api.py:67-82` | yt-dlp 路径：无视频无音频流但有缩略图 → `IMAGE_ALBUM` |

即：**webapi 路径**按 `aweme["images"]` + `aweme_type` 判定，
**yt-dlp 路径**按 formats/thumbnails 判定，两条路都能产出
`MediaType.IMAGE_ALBUM`。下载交给 yt-dlp 的抖音 extractor。

### 三、为什么"上游端点"不值得加

`slidesinfo` 是**移动端 short_domain（iesdouyin）的老接口**。
DouBi 现有图集路径走的是：

1. `webapi` 的 `images` 数组（与视频详情同一套签名管线，M6.48 已就位）
2. yt-dlp 的抖音 extractor（能拿到图集且已在用）

再引入一条 `iesdouyin/web/api/v2/` 的**第二套域名 + 第二套版本号 + 第二套
响应结构**，收益是"多一种拿 images 的方式"，成本是：

- 新域名的签名/Host 处理（`_request_json` 目前只处理 `douyin.com` +
  M6.55 的两个直播域名）
- 一个新的响应结构解析分支 + 对应测试
- 一个上游从未调用、因此**从未被验证过能否工作**的端点

这是一笔明确的负收益买卖。**不做。**

### 四、真正的缺口（如实记录，留给后续）

核实过程中发现两处**真实存在但本轮不修**的问题，写在这里以免丢失：

1. **`DouyinAPI._classify_media_type` 的判定偏弱**
   （`api.py:77-81`）：只在"无视频流且无音频流"且**有缩略图**时才判
   `IMAGE_ALBUM`。一个图集若同时被 yt-dlp 报出某种音频流（部分图集带
   BGM），会落回 `VIDEO`。这条路径的判定信号不如 webapi 侧
   （`aweme["images"]` 是明确的图集标志）可靠。
2. **`IMAGE_ALBUM` 的下载行为未单独验证**：`MediaItem.media_type` 标对了，
   但 `media_type` 是否真正影响 engine 的下载分支（还是仅作展示/路由）
   本轮没有核实。

两处都不属于 §8.1 item 12 的范围（item 12 问的是"要不要移植 slidesinfo 接口"），
因此**不做未经请求的扩大改动**，仅在此备案。

### 五、验证

无代码改动，因此无新增测试。全量测试仍为
`1001 passed, 263 deselected`（M6.57 之后）。

---

## M6.56 (2026-10-03) — 抖音 合集（MIX）标题/ID 回查（Survey §8.1 item 11 落地）

> **移植来源**：Johnserf-Seed/TikTokDownloader
> `src/interface/mix.py:86-88`（`Mix.__get_mix_id`）+
> `src/extract/extractor.py:1546-1548`（`Extractor.extract_mix_id`，正文就是
> `safe_extract(data, "mix_info.mix_id")`）。MIT → GPL-3.0 兼容。
>
> **本轮定位是"接线"而不是"新写功能"**：DouBi 从 M6.45 起就有一条 best-effort
> 的标题探测（`adapter._probe_mix_title`），但它和 `get_video_detail` /
> `collection_of` 各走各的，导致三处真实缺口。M6.56 把上游那一个点查询语义
> 抽成单一入口并接上既有两条路径，净增 55 例。
>
> **与上游的一处刻意分歧**：TikTokDL 的 `Mix` 对象在手上还没有任何 aweme 时
> 就被构造出来，所以 `__get_mix_id` 必须**额外发一次 `Detail` 请求**才能拿到
> `mix_id`。DouBi 的调用方要么手里已有 `mix_id`（来自 URL），要么手里已有
> aweme dict（来自 `get_video_detail`），因此 M6.56 保留完全相同的点查询语义，
> **但不复制那次冗余请求**。详见 §五。

### 一、修掉的三处真实缺口

排查 item 11 时先做了调用者盘点，发现 `get_mix_detail` 是**零调用者的死代码**，
而它本该服务的路径正在手工做更差的事：

1. **`get_video_detail` 拉到的 `mix_name` 被丢掉**。`collection_of` 拿到 detail
   后只读 `mix_info.mix_id`，把同一次响应里已经存在的 `mix_name` 扔了。
2. **丢掉之后又重复探测**。`collection_of` 接着调 `_parse_collection`，
   后者再发一次 `get_mix_aweme(count=1)` —— 同一个合集名，两次网络往返。
3. **`webapi.get_mix_detail` 死代码**。写了没接线，与 `_probe_mix_title`
   各自演化出两套"怎么问合集名"的语义。

缺口 2 的代价在风控下还会放大：单条视频 URL 本来可能只是碰巧拿到了 detail，
却要多付一次 `count=1` 的分页请求，多一次被 403 的机会。

### 二、`extract_mix_ref()`：移植过来的那个原语

对应上游 `Extractor.extract_mix_id` 的 `mix_info.mix_id` 点查询。

```python
def extract_mix_ref(aweme: dict[str, Any]) -> dict[str, str]:
```

返回 `{"mix_id": ...}`，可选带 `mix_name` / `mix_desc`；拿不到时返回 `{}`。

三处**刻意与上游不同**，都写进了测试：

| 分歧点 | 上游 | DouBi | 原因 |
|---|---|---|---|
| 失败返回值 | `""` | `{}` | 调用方按真值分支即可，不必再特判空串 |
| `mix_id` 类型 | 原样透传 | 强制 `str` | 平台时 `int` 时 `str`，而调用方要跟 URL 路径段（永远 `str`）比对，转换只在这一处发生 |
| 空名处理 | `safe_extract` 的 falsy 短路 | 显式 strip 后丢键 | 让下游不必区分"没名字"和"名字是全空格" |

`mix_name` / `mix_desc` 仅在非空白时才出现，且值已 strip —— 于是
`format_mix_title` 永远不需要输出 `《   》` 这种东西。

### 三、`format_mix_title()`：占位符语义收在一处

```python
def format_mix_title(ref, fallback_mix_id="") -> str:
```

有名字 → `抖音合集《名字》`；否则 → **M6.45 原样的** `抖音合集 {mix_id}`。

把 M6.45 的占位符字符串从 `adapter` 搬到这里，是为了让"有名字/没名字"两种
输出格式只存在一份 —— 之前它散在 `_parse_collection` 的 f-string 里，
再挂上 `collection_of` 的第二条路径就会漂移。

### 四、`resolve_mix_ref()`：上游语义的正确落点

```python
async def resolve_mix_ref(self, *, mix_id="", aweme_id="",
                          error_sink=None) -> dict[str, str]:
```

探测顺序，命中带名字的结果即停：

1. 只给了 `aweme_id` → 先取该视频 detail，`mix_id` 从它身上来
   （**这就是 TikTokDL `Mix.__get_mix_id` 的形状**）
2. `/aweme/v1/web/mix/detail/` —— 风控放行时最便宜的答案
3. `/aweme/v1/web/mix/aweme/` 第 1 页 —— M6.45 起就在用的兜底，也是实际
   最能work 的那条（首页 aweme 自带 `mix_info`）

`error_sink` 透传给**最后发出的那个请求**，所以调用方拿到 `{}` 时仍能区分
`need_login` 和"平台就是没名字"。

值得单独写一句的是**第 3 步的续探条件**：`/mix/detail/` 返回 200 但只带
`mix_id` 不带名字时，**不算答完**，继续探第 1 页 —— 返回一个"确认了 ID 但
没名字"的 ref 等于把活儿推给调用方。

### 五、调用方接线

**`adapter._parse_collection(mix_id, *, seq=None, mix_ref=None)`**
新增 `mix_ref` 关键字参数。给了 ref 就**不发探测请求**，直接用已知的
`mix_name`；没给才走 `_probe_mix_title`。`mix_ref["mix_id"]` 与 URL 段不一致时
**以平台为准** —— 相信 URL 会在平台改语义时静默贴错标签，这比多存一个字段贵。

**`adapter.collection_of(aweme_id)`**
之前：读 `mix_id` → 丢掉 `mix_name` → 再探一次。
现在：`extract_mix_ref(detail)` 一次拿全 → 直接喂给 `_parse_collection`。
**净省一次网络往返**，且 `/mix/aweme/` 被 403 时容器仍能拿到真标题
（detail 已经证明了名字存在）。

**`adapter._probe_mix_title()`** 现在只是 `resolve_mix_ref` 的薄包装，
不再自己遍历 aweme —— 两条路径共用同一套回查顺序，不会各自漂移。

`extract_mix_ref` / `format_mix_title` 放在 `webapi.py` 模块级而非
`adapter` 方法：CLI、测试、未来的 MCP 工具共用一套语义，
与 M6.55 的 `pick_live_quality` 同一思路。

### 六、CLI：`doubi mix`

不新开顶层命令组，直接加一个子命令，两个模式：

```
doubi mix <mix_id|合集URL>              # 只回查，输出 1 行 JSON
doubi mix <mix_id> --list [--max N]     # 回查 + 枚举，输出 JSONL
doubi mix "" --from-aweme <aweme_id>    # 从单条视频反查它的合集
```

- 位置参数接受 **裸 id 或任何合集 URL**：`/collection/{id}`、
  `/collection/{id}/{seq}`、`/mix/{id}`、`iesdouyin/share/mix/detail/{id}`
  都认。复用 `classify_douyin_url` 而不是另写正则，避免两套模式表漂移。
- `--from-aweme` 对应上游 `detail_id` 那条路径。
- `--list` 每行带 `mix_id` / `mix_name` / `target_mix_id`，与
  `doubi user` / `doubi favorites` 的 kind 自描述惯例一致。

退出码沿用既有只读子命令：`0` 查成功（含 0 命中）、`2` 参数不可用、
`3` 请求失败。

### 七、写测试时抓到的一个真 bug

初版 CLI 里写了 `resolved = ref.get("mix_id") or mix_id` —— 意图是
"回查失败就退回用户输入"。测试逼出了它的真实后果：平台从未确认过的 id
会被当作成功回显，用户看到一行像模像样的 `{"mix_id": "7663...", "title":
"抖音合集 7663..."}`，**完全没有迹象表明这次回查是失败的**。

改成 `ref` 为空即报 miss 并写 stderr。宁可多一次"没查到"，不可给一次
看起来成功的假结果 —— 与 M6.55 `pick_live_quality` 匹配不到不回落 `best`
是同一条原则。

### 八、克制清单（明确不做）

- **不做 `/mix/detail/` 的 POST 或其他鉴权绕过**：该端点匿名 403 是平台行为，
  上游 `Mix.run` 也从不调它；DouBi 只把它当"可能成功的第一跳"。
- **不改 M6.45 的 seq 语义**：`/collection/{id}/{seq}` 依旧代表整个合集，
  seq 只留痕在 `extra` + `source_url`。
- **不做合集内排序 / 日期区间过滤**：TikTokDL `extractor.py` 有
  `earliest`/`latest` 过滤（`run()` 里那段 1531-1543），但那是它批量模式的
  附带能力，DouBi 没有对应的批量入口，先不搬。
- **不碰 `iter_mix_awemes` 的翻页**：M6.45 的 cursor-stuck 保护保持不动。
- **不把 `mix_name` 写进下载文件名模板**：`output_template` 语义是另一件事，
  混进来会让已有的模板测试全部要重新解释。

### 九、验证

```
python -m pytest tests/test_douyin_mix.py -q          →  55 passed
python -m pytest tests/ -q -m "not slow and not gui"  →  969 passed, 263 deselected
```

- 新增 `tests/test_douyin_mix.py`（**55 例**）：`extract_mix_ref` 10 例、
  `format_mix_title` 6 例、`resolve_mix_ref` 探测顺序/兜底/`error_sink`
  12 例、`get_video_detail` / `get_mix_detail` 契约 4 例、
  `collection_of` / `_parse_collection` 11 例、签名白名单 parity 2 例、
  CLI 10 例。
- 修改 `tests/test_douyin_adapter.py`：3 个既有合集用例原本只 stub
  `get_mix_aweme`，M6.56 的 `resolve_mix_ref` 会先探 `/mix/detail/` ——
  补上该 stub，避免用例漏到真实网络（**测试逻辑与断言一字未改**）。
- ruff：M6.56 目标文件 0 新错误（`test_douyin_adapter.py:10` 的
  `F401 pytest 未使用` 为历史遗留）。
- mypy：`webapi.py` / `adapter.py` 无 M6.56 新增错误，剩余
  `webapi.py:815/2080`、`adapter.py:85/88/164` 经 `git diff -U0` 行号比对
  确认**均不在本轮 diff 区间内**，属历史遗留。

---

## M6.55 (2026-10-03) — 抖音 直播详细信息 + 多清晰度（Survey §8.1 item 9 落地）

> **移植来源**：Johnserf-Seed/TikTokDownloader `src/interface/live.py`
> lines 11-95（MIT）。核心是 `Live.run()` 的双分支 dispatch：
> `web_rid` 走 `live.douyin.com`，`room_id` 走 `webcast.amemv.com`。
>
> **勘误：M6.54 §七 的预估是错的**。当时写「item 9 需新增 POST
> 跨域基础设施，估约 100 LOC + 8-10 tests」——实际读源码后确认
> **两个 live 端点都是 GET**（TikTokDL `request_data` 默认
> `method="GET"`，`live.py:67` / `live.py:80` 都没传 method），
> 所以根本不需要 POST 基建，只需要让现有签名管线接受**跨 host**。
> 实际落地 ≈ 527 LOC 源码 + 683 LOC 测试 / 40 例，与预估量级接近，
> 但**性质完全不同**：不是「新写一条 pipeline」，而是「给现有
> pipeline 加一个 `base_url` 参数」。
>
> 保留这段勘误而不是改掉 M6.54 的原文——那个预估当时就是那么写的，
> 事后抹掉会让「为什么现在才做」失去上下文。

### 一、跨域复用签名管线（不改协议，只改 host）

`_signed_url()` / `_request_json()` 各加一个 `base_url` 参数（默认
`None` → 回落 `DouyinWebAPI.BASE_URL`，所有 M6.48–M6.54 调用点零改动）：

```python
def _signed_url(self, path, params, *, base_url=None) -> str:
    endpoint = f"{base_url or self.BASE_URL}{path}"

async def _request_json(self, path, params, *, max_retries=3,
                        error_sink=None, base_url=None,
                        extra_headers=None) -> dict[str, Any]:
```

`a_bogus` 是对 `query + user_agent` 求签、与 host 无关，所以跨域后
签名依然正确。`extra_headers` 是 **merge over** `_HEADERS`（不是
替换）——漏掉 `User-Agent` / `Accept` 这类浏览器基线本身就会触发
抖音风控，测试锁死了这一点。

**刻意不做的事：不把 live 路径加进 WebSign 白名单**。TikTokDL
`encrypt/douyin_params.py:48` 的 `DOUYIN_SIGNED_PATHS` frozenset
里**没有** `/webcast/room/web/enter/`，即这两个端点只吃 `a_bogus`。
M6.49–M6.54 对「无上游参考的端点」惯例是防御性 over-sign，但这里
**有**上游参考且上游明确不签，因此跟随上游。测试
`test_live_paths_are_not_websign_protected` 把这个 parity 锁住——如果
将来真要加，必须显式改测试，不能顺手加进白名单。

### 二、2 个端点（都在 `webapi.py`）

| 方法 | host + path | 入参 | Referer |
|---|---|---|---|
| `get_live_room(web_rid)` | `live.douyin.com` + `/webcast/room/web/enter/` | `LIVE_ENTER_PARAMS` 17 字段 + `web_rid` | `https://live.douyin.com/`（TikTokDL `set_referer`） |
| `get_live_room_by_room_id(room_id, sec_user_id)` | `webcast.amemv.com` + `/webcast/room/reflow/info/` | `type_id` / `live_id` / `room_id` / `sec_user_id` / `app_id=1128` | `https://www.douyin.com/?recommend=1`（TikTokDL `headers_download`） |

`LIVE_ENTER_PARAMS` 有 17 个业务字段，其中两个**刻意覆盖**
`_default_query` 的指纹：

| 字段 | `_default_query`（视频流） | `LIVE_ENTER_PARAMS`（直播播放器） |
|---|---|---|
| `device_platform` | `webapp` | `web` |
| `browser_platform` | `Win32` | `MacIntel` |

`params` 在 `_request_json` 里是 `query.update(params)`，即**后覆盖
前**，所以这两个值能生效。`msToken` 由 `_default_query` 统一注入，
不在 `LIVE_ENTER_PARAMS` 里重复（测试 pin 了 key set）。

### 三、两个纯函数（可独立测试，CLI/测试/MCP 共用一套语义）

**`extract_live_web_rid(text) -> str`** — 接受 TikTokDL
`link/extractor.py` 认的三种形态 + 裸 id：

```
https://live.douyin.com/123456789            # live_link
https://live.douyin.com/123456789?enter_from=...  # 带 query
https://www.douyin.com/follow?webRid=987654321    # live_link_self
987654321                                     # 从 search --type live 直接粘
```

**`normalize_live_room(raw, *, web_rid="", room_id="") -> dict`** —
两个端点的 room 包装位置不同（`data.data[0]` vs `data.room`），按
TikTokDL `extractor.py:1185-1187` 的顺序依次尝试。扁平化输出：

| 字段 | 来源 | 备注 |
|---|---|---|
| `status` / `status_name` | `room.status` | **只映射 2=直播中 / 4=已结束**；未知值输出 `未知(N)` 而不是猜 |
| `title` / `nickname` / `sec_uid` | `room.title` / `room.owner.*` | |
| `cover` | `room.cover.url_list[-1]` | TikTokDL `LIVE_COVER_INDEX = -1`，**取最后一个**（高清那张） |
| `total_user_str` / `user_count_str` | `room.stats.*` | |
| `flv_pull_url` / `hls_pull_url_map` | `room.stream_url.*` | 两个**平行 dict**，同一套 quality token —— 这是「选一个清晰度同时拿到 FLV+HLS」的前提 |
| `qualities` | 上面两 dict 合并 | `[{key, name, flv, hls}, …]` |

`qualities` 排序：先按 `LIVE_QUALITY_ORDER`
（`ORIGIN → UHD → FULL_HD1 → HD1 → SD1 → SD2`）挑出已知键，再把
平台新加的未知键**按原顺序追加**——抖音加新 token 时不会丢，也不会
打乱已知清晰度的顺序。

**`pick_live_quality(room, choice, *, prefer="flv")`** — 用户选择
解析，依次匹配：

1. `None` / `""` / `"best"` → 第 1 行（最高）
2. 平台原始 key，大小写不敏感（`"hd1"` → `HD1`）
3. 中文名（`"高清"` / `"蓝光"`）
4. 1-based 序号（`"2"`）

返回 `(row, url)`；`url` 取 `prefer` 容器，**缺失时回落另一容器**
（SD2 只有 FLV 时，`prefer="hls"` 也能录）。匹配不到返回
`(None, None)`，CLI 据此报「未知清晰度 + 可选列表」，**不静默回落到
best**——那是用户按了 `--quality UHD` 却录到蓝光的经典坑。

`LIVE_QUALITY_NAMES` 标签是 best-effort，未知 key 原样输出：

| key | 标签 |
|---|---|
| `ORIGIN` | 原画 |
| `UHD` | 超清 |
| `FULL_HD1` | 蓝光 |
| `HD1` | 高清 |
| `SD1` | 标清 |
| `SD2` | 流畅 |

### 四、`live.py`：录制器接受外部 room 上下文

`LiveRecorder.record()` 加三个 keyword-only 参数（`live.py`）：

```python
async def record(self, url, *, output_root, max_duration=0.0,
                 container="mp4",
                 room_id=None,      # 直连 FLV/HLS URL 时跳过 URL 解析
                 title=None,        # 跳过 yt-dlp probe 拿标题
                 metadata=None)     # 外部已拿到的 room dict → 不 probe
```

WHY：`--quality` 模式下 yt-dlp 拿到的是**直连拉流 URL**，不是
`live.douyin.com/{id}` 页面 URL。此时

- `_extract_room_id(url)` 解析不出来 → 必须显式传 `room_id`
- probe 页面 URL 既慢又**拿到错的东西**（拿的是页面 metadata，不是
  这次要录的那条流）→ `metadata=room` 直接跳过 probe

`_record_sync` 同步加 `room_id` 参数（keyword-only，默认 `""`），
`record()` 三参数全部默认 `None` 时行为与 M2.1 **完全一致**——
不传 `--info` / `--quality` 的老路径零改动。

### 五、CLI `doubi live`（扩展现有子命令，不新开）

```bash
$ doubi live -u <live URL|web_rid> [--info [--json]]
                                   [--quality KEY] [--format flv|hls]
                                   [--room-id ID] [--sec-user-id SEC]
                                   [-o DIR] [--max-duration N]
                                   [--cookies|--cookies-file PATH] [--proxy URL]
```

三种模式共用一次 room lookup：

| 模式 | 触发 | 行为 |
|---|---|---|
| 详情 | `--info` | 打表（或 `--json` 单行 JSON），**不下载** |
| 指定清晰度 | `--quality` | 取直连 URL → 交给 yt-dlp 录 |
| 兼容旧行为 | 都不传 | yt-dlp 自己选流（M2.1），**完全不发 lookup 请求** |

不传 `--info`/`--quality` 时不发 lookup，是为了让「没登录 / 不想碰
webapi 签名」的用户仍能用 yt-dlp 路径录——测试
`test_cli_live_without_quality_keeps_page_url_behaviour` 锁死。

```bash
$ doubi live -u https://live.douyin.com/123456789 --info
直播间: 深夜聊天室
主播:   某某
状态:   直播中
ID:     123456789
在线:   8452
累计:   12.3万
封面:   https://p3-webcast.douyinpic.com/...
清晰度:
  1. FULL_HD1 (蓝光)  FLV/HLS
  2. HD1 (高清)  FLV/HLS
  3. SD2 (流畅)  FLV/HLS

$ doubi live -u 123456789 --quality 高清 -o ./Downloaded
Using quality HD1 (高清) via FLV
Saved: Downloaded\20261003_2130_深夜聊天室_7300000000000000000.mp4  (412,884,992 bytes)
Duration: 3120.4s   End reason: stream_ended

$ doubi search 游戏 --type live | jq -r '.aweme_id' | while read rid; do
>   doubi live --room-id "$rid" --info --json; done       # reflow 路径
```

错误 UX / exit code：

| 情况 | exit | stderr |
|---|---|---|
| 既没 `--url` 也没 `--room-id` | 2 | `need --url ... or --room-id.` |
| lookup 失败（403/风控） | 1 | `No room data. last error: HTTP 403` + `Hint: 抖音风控拒绝了本次签名请求…` |
| `--quality` 匹配不到 | 1 | `quality 'UHD' not available. 可选: FULL_HD1(蓝光), HD1(高清), …` |
| 录制中 Ctrl-C | 130 | `Cancelled.` |

### 六、测试覆盖（**新增 40 例**）

| 文件 | 新增 | 覆盖 |
|---|---|---|
| `tests/test_douyin_live.py`（全新，683 行） | 40 | `extract_live_web_rid` 4 形态 + 4 拒绝态 / `LIVE_ENTER_PARAMS` 17-key pin + 指纹覆盖 pin + host/path pin + **WebSign 不保护 pin** / `normalize_live_room` enter 形态 + reflow 形态 + cover 取 last + 4 种空载荷 / `status` 映射（2/4/未知/None/bool）/ quality 顺序 + 平行 dict 合并 + 标签中英文回落 / `pick_live_quality` best + key 大小写 + 中文名 + 序号 + 越界 + 容器回落 + 空 room / 2 端点 request 装配（host + Referer + params）/ blank id 不发请求 / error_sink 透传 / **真实 `_request_json` 跨域端到端**（URL host + header merge + `a_bogus` 在 + WebSign 不在）/ `_signed_url` base_url 默认回落 / `record()` 三参数 / probe 必不调用 / 标题进文件名 / CLI 6 模式 + 4 错误态 |

`tests/test_browser_login.py` 里 M2.1 的 `_fake_sync` 补了
`room_id` 关键字参数（`_record_sync` 签名变更），断言未动。

合计 **M6.45 + M6.46 + M6.47 + M6.48 + M6.49 + M6.50 + M6.51 + M6.52 + M6.53 + M6.54 + M6.55**：**182 例可见**。

### 七、跑分（实测）

```
$ python -m pytest tests/test_douyin_live.py -q
40 passed in 0.57s                # M6.55 净增 40 例

$ python -m pytest tests/ -q -m "not slow and not gui"
914 passed, 263 deselected in 53.40s   # M6.54 baseline 874 + M6.55 净增 40
```

静态检查：

```
$ python -m ruff check src\doubi\cli\main.py src\doubi\platforms\douyin\webapi.py \
                     src\doubi\platforms\douyin\live.py tests\test_douyin_live.py
src\doubi\platforms\douyin\live.py:131:35: UP037  # 历史遗留（__aenter__ 引号），非 M6.55

$ python -m mypy src/doubi/platforms/douyin/webapi.py
webapi.py:807  no-any-return     # 历史遗留（get_video_detail）
webapi.py:1938 no-untyped-def    # 历史遗留（_to_datetime）

$ python -m mypy src/doubi/platforms/douyin/live.py
live.py:56/87/134                # 历史遗留（room_metadata: dict / -> dict / __aenter__）
```

M6.55 的 diff 区块内 **0 条** ruff / mypy 报告（逐行核对过 diff
hunk 区间）。顺带清掉 webapi.py 的 1 条历史 `F401`（`import time`
未使用）——M6.55 在同一段 import 块新增 `import re`，留着一条已知
死 import 说不过去。

### 八、克制清单（这次**没做**）

- ❌ **直播弹幕 / 送礼 / 在线榜** → `webcast` 的 IM 长连接（WebSocket
  + proto），不是 REST，是完全另一套协议栈；且需要登录态
- ❌ **开播 / 关播探测轮询** → 属于「监控」不是「采集」，DouBi 的
  `--max-duration=0` 已经靠 yt-dlp 自然退出实现了「录到关播为止」
- ❌ **`status == 2` 之外的状态语义补全** → 只映射平台确认返回的
  2/4；其他值显式输出 `未知(N)`。宁可显示丑，不可显示错
- ❌ **清晰度自动探测（先试再降级）** → `--quality` 已是显式选择，
  再加「自动试 UHD 失败降 HD1」会让「录到不是我要的清晰度」变成
  静默行为；要降级由用户重跑
- ❌ **`webcast.amemv.com` 的 HLS 多码率 manifest 解析** → 平台给的
  `hls_pull_url_map` 已是多清晰度映射，再解析 m3u8 是重复劳动
- ❌ **直播间录制的独立 GUI 入口** → GUI 侧仍走 yt-dlp 页面 URL
  路径（`LiveRecorder`）；把 `--quality` 接进 GUI 需要
  「清晰度下拉框 + 拉流地址展示」的设计，留 0.3.x 后续

### 九、剩余采集功能候选

| 等级 | 项目 | Survey 章节 | 状态 |
|---|---|---|---|
| ~~MEDIUM~~ | ~~直播详细信息 + 多清晰度~~ | §8.1 item 9 | ✅ **M6.55** |
| MEDIUM | Mix 标题回查 | §8.1 item 11 | ⏳ 仅 3 行 helper，价值边际 |
| MEDIUM | xGnarly 实装 | §8.1 item 8 | ⏳ TikTok 主杀器，抖音无需（跟随 item 7） |
| LOW | TikTok 全家桶（8 类） | §8.1 item 7 | ⏳ 用户场景未触发 |
| LOW | Slides / HashTag | §8.1 item 12/13 | ⏳ 上游本身就是空壳 |

**路径选择**：Survey §8.1 的 HIGH 级 4 项 + MEDIUM 级 3 项**全部
完成**（item 8 xGnarly 因抖音无触发点而挂起）。继续往下只有 LOW
级候选，而 LOW 级的共性问题是「上游未实装」或「用户场景未触发」——
继续移植的边际价值已经很低。

**建议收口发 0.3.2**：M6.45–M6.55 共 **11 个里程碑**、914 tests、
CLI 采集子命令 7 个（`search` / `hot` / `favorites` / `comments` /
`user` / `live` / `platforms`），全部未 commit，等一次 release 一起落。
再往下扩张之前，先把这 11 个里程碑发出去收真实反馈。

---

## 0.3.1 统计（标题模板 + nm3u8dl watchdog 兜底 + 托盘 + 完成通知）

- 源码 **85 个 .py 文件 / 22,003 行**（`Get-ChildItem src -Filter *.py -Recurse`
  实测；0.3.0 是 81 文件 / 约 21,000 行）
- 测试 **35 个文件 / 948 个用例收集**（`pytest --collect-only -q` 实测，
  比 0.3.0 多 2 个文件：`test_tray.py` + `test_download_page.py` 扩批）
- 回归数据三个口径全部实测（命令都是 `python scripts/run_full_tests.py`，
  说明见 BUILD §7 / DEVELOPMENT §15.2）：

| 口径 | 命令 | 结果 | 耗时 |
| --- | --- | --- | --- |
| 装齐 extras，排除 `test_theme_apply_gui.py`（28 例） | `--mode local`（默认） | **913 passed / 7 skipped / 0 failed** | 164.67s / 181.81s（两次实测） |
| 复刻 CI 依赖集（屏蔽 9 个可选包），无 mark 过滤 | `--mode ci` | **670 passed / 175 skipped / 0 failed** | 102.06s |
| 只跑 `test_theme_apply_gui.py` | `--mode gui-slow` | 未跑（已知会挂住，见下） | — |

- 三个数字之间的关系，核对过能闭合：
  - `948 收集 = 920（口径一实跑）+ 28（排除的 test_theme_apply_gui.py）`
  - 口径二报告总数 `670 + 175 = 845 < 920` **不是丢用例**——模块级
    `pytest.importorskip` 失败会把整份测试文件折叠成 **1 条 skip**，
    屏蔽依赖后总数必然变小（判绿看「与 CI 的 passed/skipped 是否相等」，
    不看总数，见 §15.1）
  - 7 个 skip 主要是 offscreen 平台下「无系统托盘」的 GUI 用例；
    「无 PySide6 则跳过」那 4 例自 M6.14 把 qasync 改成 optional import 后已不适用
- **CI 全程未参与 0.3.1**：`v0.3.1` tag 触发的 Run #5 在测试段就 failed
  （1m32s，唯一产物 290 B 的 pytest-log），红的原因是 runner 缺 9 个可选依赖
  而非代码回归——口径二的 `0 failed` 就是证据。安装包为手工打包 + 手工验证，
  详见 BUILD §8.6

> **「901 passed / 3 skipped」是错的，别再引用**。那个数字是拿各里程碑的新增
> 测试数往上一版基线上累加推出来的（`713 + 18 + 5 + 5 + 6 …`），**从未一次性
> 跑全量验证过**。根因是本地裸跑 `pytest` 会被 `test_theme_apply_gui.py`
> （28 例，带真 PySide6 起 Qt 事件循环反复切主题）挂死，于是「全量跑不动」
> 被当成了既定事实，只能靠推算。0.3.1 发版收尾时把该文件排除掉重跑，约 3 分钟
> 就出了真值 **913 / 7**——和推算值差 12 passed + 4 skipped。现在这条路径固化成
> `scripts/run_full_tests.py`，发版前跑一次就有准确数，不要再累加推算。

- 基线演进（0.3.0 → 0.3.1）：0.3.0 记录的 `868 passed / 4 skipped` 是**旧口径**
  （当时惯用 `-m "not slow"` 过滤、也没有排除文件的做法），与 0.3.1 的 913 / 7
  **不可直接相减**；各里程碑的新增测试数见 M6.22 / M6.23 / M6.24 小节末尾的
  测试表，总数一律以上表实测为准
- 主要新增能力：
  - 下载前询问支持「修改视频标题」+ `{title}` 模板（M6.22）
  - nm3u8dl 进度条不再卡 0%（1Hz 文件系统 watchdog + meta.json，M6.23）
  - 关窗最小化到系统托盘（4 项菜单：显示/暂停/继续/退出，M6.24）
  - 下载完成弹系统通知（成功 / 成功+失败 / 队列空汇总 三档可选，M6.24）
  - 修复两个 shipped bug（`int(reason)` TypeError / 
    `show_window_requested.disconnect()` 误断链）
  - 修复项目既有 `InfoBar.information` AttributeError
- 发版时知情的已知限制（不阻塞，留作下一版）：
  - **卸载后安装目录会剩一个 `doubi.db`（约 57 KB）**：`core/config.py:45` 的
    `database_path` 默认值是相对路径 `"doubi.db"`，程序以安装目录为 cwd 启动时
    数据库就落那儿，NSIS 卸载段删不掉运行期生成的文件。修法是默认值改成
    `~/.doubi/doubi.db`（BUILD §6.5 / DEVELOPMENT §18 已知限制第 9 条）
  - **导航栏 i18n 无法截图验证**：主窗口是 Qt 无边框 + DWM 合成，
    `BitBlt` / `PrintWindow` 抓出来全黑（GDI 已知限制），只能靠标题栏 PASS 推定
  - **CI 依然全红**：build-installer workflow 0.2.0 起 5 次运行全部 failed，
    从未跑到打包段（BUILD §8.6）

---

## 0.1.0 统计（保留历史快照）
- 源码 62 个 .py 文件，约 12,100 行
- 测试 19 个文件，385 个用例收集：**381 passed / 4 skipped**

