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

## 0.2.0 (2026-08-23) — M6.4 / M6.5 / M6.6 品牌化与打包

> 这一轮的共同主题是「让用户看到的和用到的，跟内核一样讲究」。
> 改 UI / 改图标 / 改打包每块都有独立动因，但都遵循一条原则：所有视觉
> 元素有可解释的取舍（写进 DEVELOPMENT 跟代码一起活），不是「我看着
> 不舒服就改了」。

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

## 0.2.0 统计
- 源码 65 个 .py 文件，约 13,400 行
- 测试 21 个文件，445 个用例收集：**423 passed / 4 skipped**
  （4 个 skip 均为「无 PySide6 则跳过」的 GUI 用例）
- 基线演进：381（M6.3）→ 403（M6.4 UI 美化 + 22 个新测试）
  → 423（M6.5 图标管线 + 20 个新测试）→ 423（M6.6 打包，无测试）

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

## 0.1.0 统计（保留历史快照）
- 源码 62 个 .py 文件，约 12,100 行
- 测试 19 个文件，385 个用例收集：**381 passed / 4 skipped**

