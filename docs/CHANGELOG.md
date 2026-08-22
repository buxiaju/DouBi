# Changelog

## 0.1.0 (2026-08-22) — 里程碑快照 M0–M6.1

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

## 统计
- 源码 ~55 个 .py 文件，约 10000 行
- 测试 16 个文件，284 个用例收集：**280 passed / 4 skipped**
  （4 个 skip 均为「无 PySide6 则跳过」的 GUI 用例）

