# DouBi 架构说明

> 版本：M6 快照（2026-08-22） · 对应 `INTEGRATION_PLAN.md` 的 M0–M6

## 1. 分层

```
┌─────────────────────────────────────────────────────────────┐
│ 入口层（可互换，共享同一套 core）                              │
│   cli/        doubi <download|auth|live|serve|mcp>          │
│   ui/         doubi-gui（PySide6 Fluent）                    │
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
│   douyin/    adapter / api / auth / strategies / url / live │
│   bilibili/  adapter / api / auth / strategies / url /      │
│              qr_login / wbi                                 │
└─────────────────────────────────────────────────────────────┘
```

## 2. 核心数据流

```
URL → PlatformRegistry.detect() → adapter.parse(url)
   → MediaItem（单条）或容器（USER/FAVLIST/MIX，children=[]）
   → pipeline.process_url():
        容器? → adapter.expand(strategy) → process_batch(children)
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

关键约定：

* **平台无关**：core 不认识任何平台 URL 或 API；所有平台知识都在 `platforms/<name>/`。
* **引擎无关**：core 不认识 yt-dlp；`Engine` ABC 是唯一接口。
* **`MediaItem.output_template`**：pipeline 在下载前渲染好的文件名基名（含标题/作者/日期净化），引擎只追加 `.%(ext)s`。
* **存储两轨**：SQLite（机器查询）+ JSONL manifest（人可读）同时写，互不替代。

## 3. 多形态统一

| 形态 | 入口 | 依赖 | 说明 |
|---|---|---|---|
| CLI | `doubi` | 无额外 | `download / auth / live / migrate / platforms` |
| GUI | `doubi-gui` | PySide6 + qfluentwidgets + qasync | qasync 把 asyncio loop 跑在 Qt 主线程 |
| REST | `doubi-serve` | fastapi + uvicorn | JobManager 内存任务队列，TTL + cap 剪枝 |
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
```

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
