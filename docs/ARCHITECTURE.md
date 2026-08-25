# DouBi 架构说明

> 版本：M6.12 快照（2026-08-24） · 对应 `INTEGRATION_PLAN.md` 的 M0–M6 与 `CHANGELOG.md` 的 M6.1–M6.12

## 1. 分层

```
┌─────────────────────────────────────────────────────────────┐
│ 入口层（可互换，共享同一套 core）                              │
│   cli/        doubi <download|auth|live|serve|mcp>          │
│   ui/         doubi-gui（PySide6 Fluent，7 套主题包）        │
│                theme.py = token 表 + set_theme 全局广播      │
│   server/     doubi-serve（FastAPI REST）                    │
│   mcp/        doubi-mcp（stdio JSON-RPC）                    │
├─────────────────────────────────────────────────────────────┤
│ core/（平台无关内核）                                         │
│   models.py        MediaItem / Stream / DownloadJob / ...   │
│   registry.py      PlatformRegistry（自注册）                 │
│   pipeline.py      解析 → 容器展开 → 下载 → 记录             │
│   naming.py        文件名模板渲染 + 净化                     │
│   engine_loader.py build_default_pipeline()                 │
│   storage/         database.py / file_layout.py /           │
│                    manifest.py / migrate.py                 │
│   auth/            browser_login.py（Playwright）            │
├─────────────────────────────────────────────────────────────┤
│ engines/（传输层）                                            │
│   yt_dlp.py        YtDlpEngine（to_thread 包装）             │
├─────────────────────────────────────────────────────────────┤
│ platforms/（平台适配器，自注册）                               │
│   douyin/    adapter / api / auth / strategies / url / live /
│              webapi（签名 Web API）/ sign（a_bogus / x_bogus）
│   bilibili/  adapter / api / auth / strategies / url /              │
│              qr_login / wbi                                 │
│   youtube/  adapter / url（URL 分类 + yt-dlp extract_info）   │
└─────────────────────────────────────────────────────────────┘
```

## 2. 核心数据流

```
URL → PlatformRegistry.detect() → adapter.parse(url)
   → MediaItem（单条）或容器（USER/FAVLIST/MIX，children=[]）
   → pipeline.process_url():
        容器?（is_container() 或 media_type ∈ {USER, MIX}）
             → adapter.expand(strategy) → process_batch(children)
        单条? → naming.set_item_output_template(item)
              → engine.download(item, options)   # yt-dlp
              → Database.record_download()        # media_item 表
              → ManifestWriter.record()           # JSONL 追加
```

**B 站「带分类的合集」是三层嵌套**（view API 的 `data.ugc_season`），GUI 解析页按需逐层展开：

```
season（合集）
└── sections[].title      分类   ← 容器，不可直接下载
    └── episodes[]        分集   ← 各自是独立 BV
        └── pages[]       分P    ← 同一 BV 内的多个 p
```

判定规则：**必须用 `len(sections) > 1`**。无分类的普通合集也带 `ugc_season`，但 `sections`
只有一项且 title 恒为「正片」——用 `season is not None` 会把普通合集误判成带分类合集。

**抖音合集（mix）是单层容器**（M6.7）：`douyin.com/collection/{mix_id}` 或
`iesdouyin.com/share/mix/detail/{mix_id}/` 分享链 → `MediaType.MIX` 壳（children 解析时不填）。
yt-dlp **没有**抖音合集/用户页抽取器，展开完全走签名 Web API
（`platforms/douyin/webapi.py`，a_bogus 签名 + 反爬重试，详见 `DEVELOPMENT.md` §14.6）。
因为 `is_container()` 只看 children 非空，pipeline 的容器判定必须写成
`is_container() or media_type in (USER, MIX)`——这也是 B 站 LIST 合集的同一形态。

关键约定：

* **平台无关**：core 不认识任何平台 URL 或 API；所有平台知识都在 `platforms/<name>/`。
* **引擎无关**：core 不认识 yt-dlp；`Engine` ABC 是唯一接口。
* **`MediaItem.output_template`**：pipeline 在下载前渲染好的文件名基名（含标题/作者/日期净化），引擎只追加 `.%(ext)s`。
* **存储两轨**：SQLite（机器查询）+ JSONL manifest（人可读）同时写，互不替代。
* **AppConfig → DownloadOptions 搬运链是硬边界**：引擎、`file_layout`、pipeline 只认
  `DownloadOptions`，**从不回读 `AppConfig`**。CLI 从命令行参数直构造 options；GUI 的
  `parse.py::_build_options()`、REST 的 `server/app.py::_build_options()` 是两端唯一
  搬运点，漏一个字段等于这个开关在那一端是死的。两端都有
  `test_build_options_covers_every_shared_config_field` 守着，新字段漏转会立刻
  红测。
  **overrides 叠加层**（M6.11）：GUI 的「下载前选项弹窗」用
  `dataclasses.replace(_build_options(), **overrides)` 叠加用户临时修改的 4 个字段
  （画质 / 容器 / 缩略图 / JSON），不绕进 `_build_options` 内部。详见
  `DEVELOPMENT.md §13.8`。

## 3. 多形态统一

| 形态 | 入口 | 依赖 | 说明 |
|---|---|---|---|
| CLI | `doubi` | 无额外 | `download / auth / live / migrate / platforms` |
| GUI | `doubi-gui` | PySide6 + qfluentwidgets + qasync | qasync 把 asyncio loop 跑在 Qt 主线程 |
| REST | `doubi-serve` | fastapi + uvicorn | JobManager 内存任务队列，TTL + cap 剪枝；M6.9 起默认绑 `127.0.0.1` + 可选 token 鉴权 |
| MCP | `doubi-mcp` | 无（stdlib） | 行分隔 JSON-RPC 2.0，stdout 只写协议 |

## 4. 登录体系

* Cookie 落盘约定：`~/.doubi/cookies/{douyin,bilibili}.txt`（Netscape 格式），yt-dlp 通过 `cookiefile` 直接消费。
* B 站两条路：扫码 + Playwright 自动抓取（`URLChangeLogin` 等 URL 变化）或 `--import cookies.txt`。
* 抖音：Playwright `CookieSetLogin` 轮询 4 个关键 cookie（ttwid/msToken/passport_csrf_token/odin_tt）。
* 兼容旧 douyin-downloader 的 `config/cookies.json`（`--legacy-json`）。
* `auth/status` 通过平台 user-info 接口验证登录态（B 站 `/x/web-interface/nav`、抖音 user/info/self）。

## 5. 存储 schema（doubi.db）

```
media_item      (platform, item_id) PK · title/author_id/author_name/
                cover_url/duration/publish_time/media_type/payload/
                last_download_time/last_save_dir/extra
task            task_id PK · platform/status/total/succeeded/failed/
                started_at/finished_at/config_snapshot
increment_checkpoint  (platform, user_id, mode) PK · last_item_id/last_check_time
pending_task    task_id PK · platform/item_id/title/source_url/
                media_type/options_snapshot/created_at    ← M6.10 跨进程恢复
```

**`pending_task`** 表（M6.10）记录「已入队但未完成」的任务，供 GUI 重启后
恢复。任务完成或取消时删除对应行；``options_snapshot`` 是
``DownloadOptions`` 的 JSON 编码快照，保证恢复后与原任务用同一份下载选项。
详见 `DEVELOPMENT.md §13.2.1`。

旧库迁移：`doubi migrate --from douyin --path dy_downloader.db --into doubi.db`
（B 站：`--from bilibili`，best-effort）。

## 6. 输出布局

```
<output_root>/
├── download_manifest.jsonl
└── {platform}/{author}/{media_type}/
    └── {date}_{title}_{item_id}/
        ├── *.mp4 / *.mkv
        ├── *.(cover|avatar).jpg
        ├── *.info.json
        └── *_room.json           # live 录制时
```

模板可配：`DownloadOptions.output_dir_template` / `filename_template`。

**侧车文件（sidecars）** 与主视频并排落盘，默认全关，按需打开：

```
<output_root>/
├── download_manifest.jsonl
└── {platform}/{author}/{media_type}/
    └── {date}_{title}_{item_id}/
        ├── *.mp4 / *.mkv                         # 主视频（container 选项）
        ├── *.(cover|avatar).jpg                  # write_thumbnail
        ├── *.info.json                           # write_metadata_json
        ├── *.nfo                                 # write_nfo（Kodi/Jellyfin 格式）
        ├── *.vtt                                 # write_subtitles（yt-dlp 产出）
        └── *.xml                                 # write_danmaku（B站，platforms 层独立下载）
```

* **字幕**走 yt-dlp 的 `writesubtitles` / `writeautomaticsub` / `subtitleslangs`，
  由引擎直接产出（可适用于任何平台）。
* **弹幕** 是 B 站专属，不走引擎：platforms 层在 `adapter.post_download` 钩子中按
  **分P 的 cid**（而非 BV 号）调用官方端点 `fetch_danmaku_xml` → `write_danmaku`
  落盘。原因：弹幕是分P级资源，有单独接口，天然装不进 yt-dlp 选项。
* **NFO**（Kodi/Jellyfin 刮削）在 `core/storage/nfo.py`，由 pipeline 在主视频完成
  后写出，与平台无关。
* **断点续传**：`resume=True` 时 yt-dlp 开 `continuedl`，且 `.part` / `.ytdl` 中间
  文件只在完成后清理；取消（协作式）也不清它们，保证后续 resume 可以接上。
  **跨进程恢复**（M6.10）：GUI 重启后会读 `pending_task` 表，询问用户是否恢复
  未完成任务——恢复出来的任务一律是 `paused` 状态（不自动开下），`.part` 文件
  仍在磁盘上，用户确认后断点续传。详见 `DEVELOPMENT.md §13.2.1`。

**合集会额外铺开目录层级**，由 `core/storage/file_layout.py` 依据 `item_leaf_parts()`
生成，与 `naming.py` 的职责严格分离：

```
bilibili/{author}/video/
└── {合集名}/{分类名}/{分集名}/
    └── {分集名}_{BV号}_P007.mp4      ← _P007 是分P序号
```

* **`naming.render_filename()` 只产 basename，绝不输出路径分隔符。** 往 naming 里加目录
  前缀会与 file_layout 叠加，导致合集名出现两层（踩过的坑，勿回退）。
* 分P序号由 yt-dlp 模板 `%(playlist_index&_P{:03d}|)s` 生成——单集（`playlist_index=None`）
  时该段渲染为空串，完全向后兼容；写成 `_P%(playlist_index)03d` 会在单集时得到丑陋的 `_PNA`。
* 合集共享目录时，断点检测 `already_downloaded_on_disk()` 必须传 `basename`，否则同目录下
  任何一个已完成文件都会让整个合集被误判为已下载。

## 7. 任务生命周期（暂停 / 继续 / 取消）

`TaskManager` 跑在 GUI 页面内部，使用同一个 `asyncio` loop（qasync 桥接 Qt）。
核心 API：`add()` / `pause(task_id)` / `resume(task_id)` / `pause_all()` / `resume_all()`
/ `remove(task_id)`。

### 为什么取消只能是协作式

`YtDlpEngine.download` 的主体是 `await asyncio.to_thread(self._download_sync, ...)`。
`Task.cancel()` 只能在下一个 await 点触发，而已进入引擎线程内部的传输**再也不会
回到事件循环**。所以中断只能**靠轮询**：把一个 `cancel_check` 回调塞进
`DownloadOptions`，yt-dlp 的 progress hook 每一个进度 tick 都调它，返回 `True`
就抛 `DownloadCancelled` 退出。

### 双机制停止

```
TaskManager.pause(task_id)
    ├── 1. _stop_attempt(task_id):
    │       ├── flag.stopped = True        ← 已进引擎线程的传输：下一个 progress tick 必停
    │       └── task.cancel()             ← 还卡在并发信号量排队上的：立刻离开 asyncio
    └── 2. 同步改 status / 发 task_progress 信号（UI 立刻响应，不等下一个 tick）
```

只靠 `task.cancel()` 会丢正在传输的那一批；只靠 flag 会漏掉还没进引擎的。
两者缺一不可。

### 停止标志按「尝试」持有，不是按 task_id

暂停时，旧的工作线程可能**仍在引擎内部，还没看到 flag**；如果 resume() 直接复用
同一个 flag 并清掉它，旧线程会在稍后的 tick 中发现 flag=False，误以为可以继续——
两个线程（旧 + 新 resume 出来的）就会**同时写一个 `.part` 文件，互相损坏数据**。

因此：每次 `_spawn()` 都造一个新的 `_StopFlag`，塞进 `replace(options, cancel_check=flag)`
并在 `_flags[task_id] = flag` 处只保留**当前这一次尝试**。旧尝试看到 flag 停下时，
它的句柄在 `_forget()` 里必须先判 `self._tasks.get(task_id) is task`，否则会把新
尝试的句柄一起清理掉——这是**陈旧尝试守卫**。

### 协作停止的结果判据

引擎自己吞掉了 `DownloadCancelled`，不会往外抛异常，`download()` 结束后只给一个
`ok is False`。但失败也是 `ok is False`，所以必须区分：

```
ok = await asyncio.to_thread(self.engine.download, ...)
if flag.stopped and not ok:
    status = paused              ← 真的被暂停了
elif not ok:
    status = failed              ← 传输失败
else:
    status = succeeded           ← 完成（flag.stopped 可能是一个迟到的暂停）
```

关键：`not ok` 不能省。一个**已经传完**的文件，下一秒才看到暂停 flag，如果只看
`flag.stopped` 会把它误标成 `paused`，然后永远无事可做（死锁）。

### `paused` 是非终态

它：
1. 保留 `_active[task_id]` 的位置（终态会移走，释放 slot 给更多并发）；
2. 保留磁盘上的 `.part` / `.ytdl`，这样 resume 才能真续传，而不是从头再来。

要丢弃任务（含 part 文件）用 `remove()`，不是 `pause()`。

## 8. 主题的全局生效链路

`ui/theme.py` 是**唯一的颜色真相源**：7 套 `ThemePack`，每套自带一张完整 token 表
（`bg_base` / `bg_layer` / `text_primary` / `border` / 语义色…）和自己的明度 `dark`。
没有独立的「亮/暗/跟随系统」开关——明度是主题包的属性，不是正交维度。

### 为什么不能只调 `setTheme()`

qfluentwidgets 只有 `Theme.LIGHT` / `Theme.DARK` 两套内置色板，`setThemeColor()` 又
只改强调色。**两个 API 加起来也表达不了 7 套底色**，所以 `set_theme()` 必须在它们之上
再补四步，才能让「每一处颜色」都跟着主题走：

```
set_theme(name)
    ├── 1. setTheme(DARK/LIGHT)     ← 按 pack.dark 定明度，让库内控件走对的分支
    ├── 2. setThemeColor(accent)    ← 强调色
    ├── 3. 两个 monkey patch        ← 必须早于任何刷新
    │       ├── CardWidget / SimpleCardWidget 的自绘取色 → 接到 token
    │       └── styleSheetManager.register → 让「切换之后」才创建的控件也拿到新色
    ├── 4. _apply_app_qss(pack)     ← 全局 QSS 覆盖原生控件
    ├── 5. _apply_window_background + _refresh_fluent_widgets（含关 Mica）
    └── 6. _notify()                ← 通知订阅者重刷把颜色烘进了 stylesheet 的控件
```

顺序是硬约束：第 3 步早于第 5 步，否则卡片重算底色时取到的还是库里硬编码的
`QColor(255,255,255,170)`。五层失效点的完整根因与判据见 `DEVELOPMENT.md §13.4.2`。

### 广播为什么是「订阅」而不是「遍历控件树」

有些控件把颜色**烘进了自己的 stylesheet**（Qt 里控件自身样式表优先级高于
`QApplication` 全局样式表，全局只是兜底），单靠铺 QSS 刷不动它们。所以 `theme.py`
维护一份回调表，`subscribe_theme(widget, cb)`：

* 回调随 `widget.destroyed` 自动摘除，页面销毁后不留悬挂引用；
* `_notify()` 逐个调用并**吞掉单个回调的异常**——一个页面刷新失败不能让其余页面停在旧色；
* 同时挂到 qfluentwidgets 的 `qconfig.themeChanged`，这样第三方或系统直接调
  `setTheme()` 时自绘颜色也能跟上。

### 启动与持久化

`app.py`：`theme_name = args.theme or load_config(None).theme`，因此优先级为
`--theme` > `DOUBI_THEME` > `~/.doubi/config.yml` > 内置默认。`set_theme()` 在启动时
**故意调两次**：第一次在建窗口之前（让各页面构造时就能读到 token），但那时还没有顶层
窗口可刷底色，所以建完窗口后必须再调一次。

落盘只发生在设置页的「保存设置」（`_on_save()` 写 `data["theme"]`）；下拉框选中和
导航栏画笔按钮都只是**即时预览，不写配置**。

## 9. 图标管线

图标有三种形态，对应三个文件 + 两个角色：

| 文件 | 角色 | 运行时 | 谁来读 |
| --- | --- | --- | --- |
| `ui/resources/icon.svg` | 设计源稿（含 filter / clipPath） | 不参与渲染 | 设计参考 |
| `ui/resources/icon_template.svg` | 渲染模板（QtSvg 安全子集 + 7 个换色锚点） | **是** | QtSvg |
| `ui/resources/icon.png` | 1024px 兜底位图 | QtSvg 不可用时 | Qt |
| `ui/resources/icon.ico` | 多档位 .ico（16/32/48/64/128/256） | 操作系统 | **打包后**的 .exe 资源段 |

```
当前主题主色
   ↓
icon_palette(accent) → 7 色调色板
   ↓
icon_svg(accent) → 一次正则替换换色
   ↓
render_icon_pixmap(size) → QtSvg 矢量渲染
   ↓
load_app_icon(sizes) → 装填到 QIcon 8 档
   ↓
setWindowIcon + setWindowIcon on QApplication
   ↓
windowIconChanged 信号 → 标题栏 / 任务栏 / Alt+Tab 同步换色
```

**主题感知**：标题栏图标 / 关于对话框 / 登录对话框 / 闪屏的图标**全部**
跟着主题走——切到「深海」会看到青绿底 + 薄荷脸的豆比，切到「高对比」会看到
亮黄底 + 深色脸的豆比。**豆比紫主题特殊**：它本身就是从图标反推的，
`_active_accent()` 检测到 `name == "doubi"` 时返回 `None`，让图标走品牌
原色——否则用主色 `#f59e6a` 二次推导会让图标偏色、丢原图味道。

**主窗口图标放大**：qfluentwidgets `FluentTitleBar.setIcon` 把 pixmap 尺寸
写死 18px。`main_window._enlarge_titlebar_icon(TITLEBAR_ICON_SIZE=28)`
断开旧信号、改用 28px 闭包；切主题时新闭包自动被信号触发，不会再被
18px 覆盖。

**关键设计取舍**：
- **矢量优先，PNG 是兜底**。`render_icon_pixmap` 走 QtSvg，**16px 标题栏
  图标和 256px 闪屏图标同样锐利**。PNG 仅在 QtSvg 不可用时兜底。
- **不强制依赖 PIL**。`build_ico.py` 手写 ICONDIR / ICONDIRENTRY，
  绕开 `Pillow 12.3.0 + Python 3.13 + Windows` 的
  `STATUS_STACK_BUFFER_OVERRUN` 崩溃。
- **`BRAND_PALETTE` 与模板字面量逐字一致**。换色是一次正则替换，
  锚点要是不一致会漏色——`test_icon_template_exists_and_holds_all_anchors`
  守这条。

详细技术细节（QtSvg 滤镜 bug / 7 套主题预览图 / 任务栏图标资源嵌入）见
[docs/ICONS.md](./ICONS.md)。
