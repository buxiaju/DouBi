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
> 累计新增 33 个测试，回归 901 passed / 3 skipped。

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
> 全部回归 901 passed / 3 skipped。

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

回归 713 + 18 + 5 + 5 + 6 = 747 → 901（细化后，详见「0.3.1 统计」）。

---

## 0.3.0 统计（通用嗅探 + GUI 体验加固 + 健壮性扫尾）

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

## 0.3.1 统计（标题模板 + nm3u8dl watchdog 兜底 + 托盘 + 完成通知）

- 源码 85 个 .py 文件，约 22,000 行（M6.22 + 24 累计 + ~1,000 行）
- 测试 35 个文件，**901 passed / 3 skipped**
  （3 skip 均为 offscreen 平台下「无系统托盘」GUI 用例，
   「无 PySide6 则跳过」的 4 例已不再需要——M6.14 把 qasync 依赖
  改为 optional import）
- 基线演进（0.3.0 → 0.3.1）：
  - 868 → 901（+33：M6.22 标题模板 +14 / M6.23 nm3u8dl watchdog +16 / 
    M6.24 托盘 + 通知 + 通知转发 +3）
- 主要新增能力：
  - 下载前询问支持「修改视频标题」+ `{title}` 模板（M6.22）
  - nm3u8dl 进度条不再卡 0%（1Hz 文件系统 watchdog + meta.json，M6.23）
  - 关窗最小化到系统托盘（4 项菜单：显示/暂停/继续/退出，M6.24）
  - 下载完成弹系统通知（成功 / 成功+失败 / 队列空汇总 三档可选，M6.24）
  - 修复两个 shipped bug（`int(reason)` TypeError / 
    `show_window_requested.disconnect()` 误断链）
  - 修复项目既有 `InfoBar.information` AttributeError

---

## 0.1.0 统计（保留历史快照）
- 源码 62 个 .py 文件，约 12,100 行
- 测试 19 个文件，385 个用例收集：**381 passed / 4 skipped**

