# Changelog

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

