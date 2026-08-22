# DouBi 开发文档（面向 AI / 开发者）

> 目标：任何有能力的 AI 或开发者读完本文档，就能安全地修改、扩展、维护 DouBi，而不需要重新逆向整个项目。
> 版本对应：M0–M6.1（2026-08-22 快照）。配套文档：`docs/ARCHITECTURE.md`（分层图）、`docs/QUICKSTART.md`（用户操作）、`docs/CHANGELOG.md`（变更史）、`INTEGRATION_PLAN.md`（整合原始方案）。

---

## 目录

1. [项目是什么](#1-项目是什么)
2. [技术栈与运行要求](#2-技术栈与运行要求)
3. [顶层结构](#3-顶层结构)
4. [核心数据模型（一切的基础）](#4-核心数据模型)
5. [核心数据流（一条 URL 的生命周期）](#5-核心数据流)
6. [平台适配器（如何新增一个平台）](#6-平台适配器)
7. [下载引擎（如何新增/更换引擎）](#7-下载引擎)
8. [Pipeline（编排层）](#8-pipeline)
9. [存储层](#9-存储层)
10. [配置系统](#10-配置系统)
11. [登录体系](#11-登录体系)
12. [四端入口（CLI / GUI / REST / MCP）](#12-四端入口)
13. [GUI 内部结构](#13-gui-内部结构)
14. [B 站风控专题（最重要的实战知识）](#14-b-站风控专题)
15. [测试体系](#15-测试体系)
16. [代码约定与常见坑](#16-代码约定与常见坑)
17. [如何安全地修改项目（改动检查单）](#17-如何安全地修改项目)
18. [已知限制与路线图](#18-已知限制与路线图)

---

## 1. 项目是什么

DouBi 是一个**多形态统一的多平台视频/媒体下载器**：同一个内核（`doubi` 库）同时驱动四种使用形态：

| 形态 | 命令 | 依赖 | 典型用途 |
|---|---|---|---|
| 内核库 | `import doubi` | 无额外 | 程序化调用 |
| CLI | `doubi ...` | 无额外 | 脚本 / 批量 |
| 桌面 GUI | `doubi-gui` | PySide6 + qfluentwidgets + qasync | 日常使用 |
| REST 服务 | `doubi-serve` | fastapi + uvicorn | 远程 / Web 调用 |
| MCP 工具 | `doubi-mcp` | 无（stdlib） | Claude Desktop / Cursor 等 AI 客户端 |

**核心设计原则**（改代码前必须理解）：

1. **平台无关内核**：`core/` 不认识任何平台的 URL 或 API。所有平台知识都在 `platforms/<name>/` 内。
2. **引擎无关**：`core/` 不认识 yt-dlp。`Engine` 抽象类（`engines/base.py`）是唯一接口。
3. **四端共享同一 `DownloadPipeline`**：任何新功能只要加在 `core`，四个端自动获得。
4. **自注册**：平台适配器在 `platforms/douyin/__init__.py`、`platforms/bilibili/__init__.py` 里 import 时注册进 `PlatformRegistry`。
5. **`MediaItem` 是唯一"工作单元"**：单条视频、容器（用户主页/收藏夹/合集）、直播都是 MediaItem，只是 `media_type` 和 `children` 不同。
6. **yt-dlp 是下载引擎 + 元数据源**：登录、签名、4K、DASH 合并全部交给它，我们不重复实现。
7. **ffmpeg 兜底**：优先系统 ffmpeg，否则用 `imageio-ffmpeg` 内置静态二进制合并 bestvideo+bestaudio。

---

## 2. 技术栈与运行要求

- Python ≥ 3.10（开发环境 3.13.15）
- 核心依赖：`yt-dlp`、`aiohttp`、`httpx`、`rich`、`pyyaml`、`python-dateutil`、`aiosqlite`、`qrcode`
- GUI 额外：`PySide6`、`PySide6-Fluent-Widgets[full]`、`qasync`、`psutil`、`playwright`
- REST 额外：`fastapi`、`uvicorn`、`pydantic`
- 开发：`pytest` + `pytest-asyncio` + `ruff`

**Windows 环境特别注意**（本仓库在 Windows 上开发）：
- PowerShell 下 `Set-Content` 会用 ANSI 编码破坏中文/UTF-8 字节。**写中文文件用 Python 脚本**，不要用 PowerShell 管道改文件。
- 测试用 `QT_QPA_PLATFORM=offscreen` 无头跑 GUI 组件。
- Playwright 是可选依赖，`pip install "doubi[gui]"` 后还需 `python -m playwright install chromium`。

---

## 3. 顶层结构

```
DouBi/
├── pyproject.toml                 # 打包 + 依赖 + console scripts + pytest/ruff 配置
├── INTEGRATION_PLAN.md            # 原始整合方案（M0–M6 里程碑）
├── doubi.spec                     # PyInstaller 打包配置
├── README.md / docs/{ARCHITECTURE,QUICKSTART,CHANGELOG}.md
├── src/doubi/
│   ├── __init__.py                # __version__
│   ├── core/                      # ★ 平台无关内核（大部分业务逻辑在这）
│   │   ├── models.py              #   所有数据模型（见 §4）
│   │   ├── registry.py            #   PlatformRegistry（自注册表）
│   │   ├── pipeline.py            #   DownloadPipeline（编排，见 §8）
│   │   ├── config.py              #   配置加载（见 §10）
│   │   ├── naming.py              #   文件名模板渲染 + 净化
│   │   ├── logger.py              #   日志设置
│   │   ├── engine_loader.py       #   build_default_pipeline() 工厂
│   │   ├── storage/               #   database / file_layout / manifest / migrate
│   │   └── auth/                  #   browser_login.py（Playwright 自动登录）
│   ├── engines/                   # 下载引擎（见 §7）
│   │   ├── base.py                #   Engine ABC + EngineProgress
│   │   └── yt_dlp.py              #   YtDlpEngine（默认引擎）
│   ├── platforms/                 # 平台适配器（见 §6）
│   │   ├── base.py                #   PlatformAdapter ABC
│   │   ├── douyin/                #   adapter / api / auth / strategies / url / live
│   │   └── bilibili/              #   adapter / api / auth / strategies / url / qr_login / wbi
│   ├── cli/                       # main.py（download/auth/live/migrate/platforms）+ auth_cmd.py
│   ├── server/                    # app.py（FastAPI）+ jobs.py（JobManager）+ schemas.py
│   ├── mcp/                       # server.py（stdio JSON-RPC 2.0）
│   └── ui/                        # PySide6 GUI（见 §13）
│       ├── app.py                 #   qasync 事件循环入口
│       ├── main_window.py         #   MSFluentWindow 壳 + 页面注册 + TaskManager 持有
│       ├── task_manager.py        #   TaskManager（GUI 下载任务状态）
│       ├── workers.py             #   DownloadWorker（GUI 任务包装）
│       ├── auth_actions.py        #   登录流程的纯 Python 包装
│       ├── pages/                 #   parse / download / history / settings
│       └── dialogs/               #   login_dialog.py
└── tests/                         # 15 个测试文件（见 §15）
```

**统计**：~55 个 .py 文件，约 10,000 行；253 个测试全部通过。

---

## 4. 核心数据模型

全部在 `src/doubi/core/models.py`。这是所有层的"通用语言"。

### 4.1 枚举

- `Platform(str, Enum)`：`DOUYIN / BILIBILI / YOUTUBE / TIKTOK / XIAOHONGSHU / WEIBO / UNKNOWN`。注意 `Platform.from_str()` 容错解析。
- `MediaType(str, Enum)`：`VIDEO / IMAGE_ALBUM / AUDIO / LIVE / LIVE_REPLAY / BANGUMI / COURSE / FAVLIST / MIX / MUSIC / USER / COLLECTION`。**`USER` 和 `FAVLIST`/`MIX` 是"容器"类型**——代表一个能展开成多个子项的 URL。

### 4.2 关键 dataclass

```python
@dataclass
class MediaItem:
    platform: Platform
    item_id: str                 # aweme_id / bvid / epid / mix_id ...
    title: str
    author: Author = Author()
    cover_url: Optional[str] = None
    duration: Optional[float] = None      # 秒
    publish_time: Optional[datetime] = None
    media_type: MediaType = MediaType.VIDEO
    source_url: str = ""                  # 用户给的原始 URL
    streams: list[Stream] = []
    children: list["MediaItem"] = []      # 容器时填充
    extra: dict[str, Any] = {}            # 平台私有扩展
    output_template: Optional[str] = None # 下载前由 pipeline 渲染好的文件名基名
    def is_container(self) -> bool: return bool(self.children)
```

⚠️ 注意：`is_container()` 只看 `children` 是否非空。**但 pipeline 判断容器用的是 `media_type is MediaType.USER` 或 `_CONTAINER_TYPES`**（见 §8）。容器在 parse 阶段 `children` 为空，expand 后才填充。

```python
@dataclass
class DownloadOptions:   # 从 UI/CLI/REST 一路传到引擎的配置袋
    output_root: Path = Path("./Downloaded")
    output_dir_template: str = "{platform}/{author}/{media_type}"
    filename_template: str = "{title}_{item_id}"
    container: str = "mp4"                # "mp4" | "mkv"
    max_quality: str = "best"             # "8k" | "4k" | "1080p" | "best" | "worst"
    format_id: Optional[str] = None       # 引擎原生 format 选择器（覆盖 max_quality）
    write_thumbnail: bool = True
    write_metadata_json: bool = True
    write_nfo: bool = False
    write_danmaku: bool = False
    write_subtitles: bool = False
    concurrent_fragments: int = 4
    rate_limit: Optional[str] = None      # "5M"
    proxy: Optional[str] = None
    cookies_file: Optional[Path] = None
    user_agent: Optional[str] = None
    database: Optional[Path] = None       # None = 关闭 DB 去重
    manifest: Optional[Path] = None       # None = 关闭 JSONL manifest
    extra: dict = {}
```

还有 `Author`、`Stream`、`DownloadJob`（批任务）、`ProgressCallback`（类型别名）。

---

## 5. 核心数据流（一条 URL 的生命周期）

以 `doubi download -u <url>` 为例：

```
URL
 → PlatformRegistry.detect(url)          # 按 url_patterns 找到适配器（registry.py）
 → adapter.parse(url)                    # 平台适配器解析
     ├─ 单条 → MediaItem(media_type=VIDEO/IMAGE_ALBUM/...)
     └─ 容器 → MediaItem(media_type=USER/FAVLIST/MIX, children=[])
 → DownloadPipeline.process_url(url, options):
     ├─ item.is_container() or item.media_type is USER?
     │    → adapter.expand(item, strategy)   # 展开成 children
     │    → process_batch(children)          # 递归下载每个子项
     └─ 单条:
          → naming.set_item_output_template(item, options)  # 渲染文件名基名
          → engine.download(item, options)                  # 默认 YtDlpEngine
          → Database.record_download(...)                   # media_item 表（去重）
          → ManifestWriter.record(...)                      # JSONL 追加
```

**GUI 特有路径**（M5.4 之后，解析与下载解耦）：

```
解析页: URL → pipeline.parse_and_expand(url, strategy=None)
         → (item, children)  # 单条: (item, [])；容器: (parent, children)
         → 用户勾选 → TaskManager.add(item, options)
下载页: TaskManager → DownloadWorker → pipeline.download_item(item, options)
         → 进度/完成信号 → 任务卡片 UI
```

`parse_and_expand` 的返回值约定（GUI 和 CLI 都依赖）：
- 单条 → `(item, [])`
- 容器 → `(container_parent, [child, child, ...])`
- 解析失败 → `(None, [])`

---

## 6. 平台适配器

### 6.1 接口（`platforms/base.py`）

```python
class PlatformAdapter(ABC):
    name: str                 # "douyin" / "bilibili"
    platform: Platform
    display_name: str         # "抖音" / "哔哩哔哩"
    url_patterns: list[Pattern]

    def match_url(self, url) -> bool        # 用 url_patterns 匹配
    @abstractmethod
    async def parse(self, url) -> MediaItem | None
    def build_engine_url(self, item) -> str  # 默认返回 item.source_url
    def supported_media_types(self) -> list[str]
```

约定：
- `parse()` 应**捕获自己的异常**并返回 `None`（带日志），不要往外抛网络错误。
- 容器 URL 的 parse 只返回一个"壳" MediaItem（`media_type=USER` 等，children 空），展开逻辑在 `expand()`。
- `expand(item, *, strategy=None, max_count=0)` 是可选方法（抖音/B 站都有），返回 children 列表并副作用修改 `item.children`。

### 6.2 抖音适配器（`platforms/douyin/`）

| 文件 | 职责 |
|---|---|
| `url.py` | `DouyinURLType` + `classify_douyin_url()`（video/note/gallery/collection/mix/music/live/short/user） |
| `api.py` | `DouyinAPI`：异步包装 yt-dlp 提取元数据 + `to_media_item()`/`flat_to_media_item()` 转换 |
| `auth.py` | Cookie 文件管理（Netscape/JSON/legacy）、`validate_cookies()`（调 user/info/self） |
| `adapter.py` | `DouyinAdapter`：URL 匹配、parse、expand（post/like 策略）、短链解析 |
| `strategies.py` | `PostStrategy`（用户主页作品）/ `LikeStrategy`（点赞列表），走 yt-dlp flat 展开 |
| `live.py` | `LiveRecorder`：抖音直播录制（max_duration、room.json sidecar） |

URL 分类示例：
- `https://www.douyin.com/video/{aweme_id}` → VIDEO
- `https://www.douyin.com/user/{sec_uid}` → USER（容器）
- `https://v.douyin.com/xxx` → SHORT（先解析重定向再分类）

### 6.3 B 站适配器（`platforms/bilibili/`）

| 文件 | 职责 |
|---|---|
| `url.py` | `BilibiliURLType` + `classify_bilibili_url()`（video/bangumi/course/list/space/favlist/watch_later/history/popular/short） |
| `api.py` | `BilibiliAPI`：异步 yt-dlp 包装 + `generate_buvid3()`（匿名标识）+ `to_media_item()` + view API 系列 `fetch_view_data()` / `extract_playlist_meta()` / `fetch_ugc_season()` / `parse_ugc_season()` |
| `auth.py` | Cookie 管理 + `validate_cookies()`（调 `/x/web-interface/nav`） |
| `adapter.py` | `BilibiliAdapter`：parse / expand / 短链 |
| `strategies.py` | ★ 核心：`SpaceStrategy` / `FavlistStrategy` / `WatchLaterStrategy` / `MixStrategy`（见 §14 风控） |
| `qr_login.py` | B 站扫码登录（QRCode/QRSession/wait_for_login） |
| `wbi.py` | WBI 签名（`sign_query` / `fetch_wbi_keys` / `compute_w_rid`） |

**容器 → 默认策略映射**（`adapter.py` 的 `_DEFAULT_STRATEGY`）：
```
SPACE → space    FAVLIST → favlist    WATCH_LATER → watch_later
LIST  → mix      HISTORY → favlist    POPULAR → space
```

**一个 `/video/BVxxx` 链接可能展开成三种形态**。`_parse_single()` 会**无条件**调一次官方 view API（`/x/web-interface/view?bvid=`，`api.fetch_view_data`），因为 yt-dlp 带 cookie 时返回的 `entries` 可能为空、`uploader` 也可能缺失。拿到 `data` 后按优先级判定：

1. **带分类的合集**（`data.ugc_season.sections` 长度 **> 1**）→ `_build_season_container()`：容器是 `MediaType.COLLECTION`，`item_id = f"ugcseason{season_id}"`，每个 **episode** 成为一个 child（每个 episode 自己是独立 BV，可能又有上百个分P，但**只展开到分集这一层**）。child 的 `extra` 带 `collection_title`（合集名）+ `section_title`（分类名），供 `item_leaf_parts()` 拼三层目录。
   - 数据形状：`ugc_season.{id,title}` → `sections[].{id,title}` → `episodes[].{id,aid,bvid,cid,title,page{part,duration}}`。
   - `api.parse_ugc_season(data)` 负责归一化（纯函数、可脱网测试），跳过没有 `bvid` 的 episode（没 bvid 就没法拼 `source_url`）。
2. **普通分P视频**（`data.pages` 长度 > 1）→ 原有逻辑，`extra["is_multi_page"] = True`，每个 page 一个 child，`source_url` 形如 `...?p=N`。
3. **单个视频** → `MediaType.VIDEO`，无 children。

> ⚠️ 判定阈值是 `len(sections) > 1`。B 站给**没有分类**的普通合集也返回 `ugc_season`，只是 `sections` 只有一项、标题恒为「正片」——用 `season is not None` 会让每个普通合集都凭空多一层「正片」目录。
>
> ⚠️ child 的 `item_id` 用各 episode 的 `bvid`（实测同一合集内互异）。`TaskManager` 按 `item_id` 去重，撞车会导致下载任务被静默丢弃。

### 6.4 如何新增一个平台（例如 YouTube）

1. 建目录 `platforms/youtube/`，写 `url.py`（分类）、`api.py`（元数据，通常直接 yt-dlp）、`adapter.py`、可选 `strategies.py`、`auth.py`。
2. `adapter.py` 继承 `PlatformAdapter`，设置 `name/platform/display_name/url_patterns`，实现 `parse()`。
3. 在 `platforms/youtube/__init__.py` 里 `from .adapter import YoutubeAdapter; PlatformRegistry.register(YoutubeAdapter())`。
4. 在 `platforms/__init__.py`（或 `core/engine_loader.py`）里 import 新包触发注册。
5. `Platform` 枚举加 `YOUTUBE = "youtube"`（已经预置了）。
6. 测试：复制 `tests/test_douyin_adapter.py` 的骨架，mock 掉网络。

---

## 7. 下载引擎

### 7.1 接口（`engines/base.py`）

```python
class Engine(ABC):
    name: str
    def supports(self, item: MediaItem) -> bool
    async def download(self, item, options, *, on_progress=None) -> bool
```

- `on_progress` 收到 `EngineProgress(fraction, message, extra)`，pipeline 会包装成 `ProgressEvent`。
- **引擎必须非阻塞**：同步 I/O 要用 `asyncio.to_thread` 卸载（`YtDlpEngine.download` 就是这么做的）。

### 7.2 YtDlpEngine（默认，`engines/yt_dlp.py`）

关键点：
- `_build_opts()` 把 `DownloadOptions` 映射成 yt-dlp opts：
  - `outtmpl` = `resolve_item_dir(item, options) / (base + PART_INDEX_SUFFIX + ".%(ext)s")`，base 优先 `item.output_template`，否则 `options.filename_template`。
  - `PART_INDEX_SUFFIX = "%(playlist_index&_P{:03d}|)s"` —— **条件占位符**，用于防止分P互相覆盖。引擎没有设 `noplaylist`，所以下载一个裸 BV 链接时 yt-dlp 会枚举它的全部分P，而 base 是固定的，不加分P号会让 N 个分P写同一个文件名。语义：`playlist_index` 有值时插入 `_P007`，无值时插入空串。因此**单视频文件名完全保持原样，向后兼容**。旧的 `?p=N` 子项在 yt-dlp 里是单视频（`_type=None`、`playlist_index=None`），同样不受影响。
  - `format` = `format_id` 或 `_quality_to_format(max_quality)`（默认 `"bestvideo*+bestaudio/best"`）。
  - `merge_output_format` = `container`。
  - `writethumbnail` / `writeinfojson` 直接透传。**两者默认 `False`**（`config.DEFAULTS` 与 `DownloadOptions`），因为用户要求下载目录里只留视频，不要中间产物。
- **中间产物清理**：下载成功后 `_cleanup_intermediates(item, options)` 扫描 item 目录，删掉 `.part` / `.ytdl` / `.temp` 残留（中断或重试后遗留），以及未被显式开启的 `*.info.json`（B 站分P会写 playlist 级别的那份，yt-dlp 自己不清）和缩略图。用户手动开了 `write_thumbnail` / `write_metadata_json` 时对应文件会保留。
- **ffmpeg 兜底**：`_resolve_ffmpeg_location()` 先 `shutil.which("ffmpeg")`，否则 `imageio_ffmpeg.get_ffmpeg_exe()`。
- **目录预创建**（M5.4 修复）：`_download_sync` 开头 `resolve_item_dir(item, options).mkdir(parents=True, exist_ok=True)`。**不要删掉这个**——B 站分P视频 yt-dlp 会在下载前写 playlist info.json，`write_json_file` 不建目录，没有预创建就 FileNotFoundError。
- 进度钩子：每 ≥0.5% 才 emit 一次，避免刷爆 UI。
- `supports()` 只检查 `bool(item.source_url)`。

### 7.3 如何新增一个引擎（例如 aria2）

1. 继承 `Engine`，实现 `supports` / `download`。
2. 在 `engine_loader.build_default_engine()` 里按配置切换（现在是硬编码 `YtDlpEngine()`）。
3. 在 `DownloadOptions.extra` 里放引擎私有参数。

---

## 8. Pipeline（编排层）

文件：`src/doubi/core/pipeline.py`（约 330 行）。这是四端共享的核心。

### 8.1 公开 API

```python
class DownloadPipeline:
    def __init__(self, engine, max_concurrent: int = 3): ...

    async def parse(self, url) -> MediaItem | None          # 解析单条
    async def parse_and_expand(self, url, *, strategy=None, max_count=0)
        -> tuple[MediaItem | None, list[MediaItem]]          # GUI 解析页入口
    async def process_url(self, url, options, *, on_progress=None,
                          job_id=None, container_strategy="post",
                          container_max=0) -> MediaItem | None  # 容器递归下载
    async def download_item(self, item, options, *, on_progress=None,
                            job_id=None) -> bool              # 已解析项直接下载
    async def process_batch(self, items, options, *, on_progress=None) -> DownloadJob
```

- `parse_and_expand`：strategy=None 时由适配器按 URL 类型自选默认策略（GUI 不需要用户选策略）。
- `download_item`：GUI"下载选中"用——**不重新 parse**，避免把容器 URL 再当父项。
- 内部 `_download_with_progress`：渲染文件名 → DB 去重检查（`is_downloaded`）→ `engine.download` → 成功后 `_record_success`（DB + manifest）。
- `ProgressEvent`：`job_id / item / phase / fraction / message / timestamp / extra`。phase 有 `parsing|expanding|downloading|merging|postprocess|done|failed`。

### 8.2 容器判定

pipeline 判断"这是不是容器"用两种方式：
- `item.is_container()`（`children` 非空）——但 parse 完时容器 children 是空的
- `item.media_type is MediaType.USER`

所以**容器解析逻辑**：B 站适配器在 `parse()` 里就根据 `_CONTAINER_TYPES` 把容器 URL 变成 `MediaType.USER/FAVLIST/MIX` 的壳 item，pipeline 看到这个 media_type 就去调 `adapter.expand()`。**改容器相关逻辑时要同时看 adapter.py 和 pipeline.py**。

---

## 9. 存储层

### 9.1 SQLite（`core/storage/database.py`）

`Database` 类持有 `doubi.db`，三张表：

```
media_item      (platform, item_id) 主键 · title/author_id/author_name/cover_url/
                duration/publish_time/media_type/payload(JSON)/last_download_time/
                last_save_dir/extra(JSON)
task            task_id 主键 · platform/status/total/succeeded/failed/started_at/
                finished_at/config_snapshot
increment_checkpoint  (platform, user_id, mode) 主键 · last_item_id/last_check_time
```

- **去重核心**：`is_downloaded(platform, item_id)` → 已下载则跳过。
- 关键方法：`record_download(...)`、`list_recent(limit)`、`count()`、`initialize()`、`close()`。
- **aosqlite 连接要 try/finally close**，否则 "Event loop closed" 报错。
- WAL 模式。

### 9.2 文件布局（`core/storage/file_layout.py`）

```
<output_root>/
└── {platform}/{author}/{media_type}/
    ├── {collection_title}/                ← 普通合集：所有分集共享这一个目录
    │   ├── 第1集.mp4
    │   └── 第2集.mp4
    ├── {collection_title}/                ← 带分类的合集（ugc_season，多 section）
    │   └── {section_title}/               ← 分类名，如「模拟电子技术」
    │       └── {episode_title}/           ← 分集名，如「1-2章」
    │           ├── 1-2章_BV1oxdwBBE3B_P001.mp4
    │           └── 1-2章_BV1oxdwBBE3B_P002.mp4
    └── {video_title}/                     ← 单个视频：目录名 = 视频名
        └── {video_title}.mp4
```

- `resolve_item_dir(item, options)` → 绝对路径，**会自动 mkdir**。叶子路径由 `item_leaf_parts(item)` 决定（返回一个**列表**，逐级拼接）：
  - `collection_title` + `section_title` 都有 → `[合集名, 分类名, 分集名]` 三层（带分类的合集）；
  - 只有 `collection_title` → `[合集名]` 单层（**同一合集的所有分集因此落进同一个文件夹**）；
  - 都没有 → `[item.title]` 单层（单个视频）。
  - **不再带 `{date}_` 前缀和 `_{item_id}` 后缀。**
- `section_title_of(item)` 读 `item.extra["section_title"]`，空白字符串视作不存在（回退到扁平的合集目录）。该 key 由 `BilibiliAdapter._build_season_container()` 写入。
- **判定"带分类"必须用 `len(sections) > 1`，不能用 `season is not None`**：B 站给没有分类的普通合集也返回 `ugc_season`，但 `sections` 只有一项且标题恒为「正片」。用 `is not None` 会把所有普通合集误判成分类合集，凭空多出一层「正片」目录。
- 合集分组只在这一层做。`core/naming.py` 只渲染 basename，**绝不输出路径分隔符**——曾经在 naming 里加 `collection_title/` 前缀，与本层叠加会导致合集名出现两次。
- `already_downloaded_on_disk(save_dir, basename=None)` → 文件系统级二次去重（用户删了 DB 行但保留文件时兜底）。合集共享目录后**必须传 `basename`**（即 `item.output_template`），否则第1集的文件会让后面每一集都被误判成"已下载"。匹配方式是 `p.name.startswith(basename)` 而非精确 stem 比较，因为引擎会追加 `_P001` 分P后缀（同理 `pipeline.py` 里挑 manifest 文件也用前缀匹配）。
- 组件净化：非法字符 → `_`，去尾点/空格，超 120 字符截断。
- **同名单视频会共享目录**（去掉 item_id 的代价），这是用户明确要求"文件夹名就是视频名"后接受的取舍。

### 9.3 Manifest（`core/storage/manifest.py`）

`download_manifest.jsonl`，追加写 + fsync。人可读的下载记录（与 SQLite 互不替代）。

### 9.4 迁移（`core/storage/migrate.py`）

`doubi migrate --from douyin|bilibili --path <legacy> --into <new>`，把旧 douyin-downloader / Bili23 数据库行搬进 `media_item`。

---

## 10. 配置系统

`core/config.py`。分层：**env > YAML 文件 > 默认值**。

- `load_config(path=None, env_prefix="DOUBI_")` → `AppConfig` dataclass。
- 默认 YAML 位置 `~/.doubi/config.yml`（GUI 设置页写入）。
- 环境变量前缀 `DOUBI_`，如 `DOUBI_OUTPUT_ROOT`、`DOUBI_PROXY`、`DOUBI_DATABASE_PATH`。
- `DEFAULTS` 字典 + `_coerce()` 类型转换。
- **新增配置项**：加进 `DEFAULTS` 字典 + `AppConfig` 字段 + `load_config` 里的构建参数 + 设置页表单 + `_build_options()`（每端都要同步！）。

`DownloadOptions` 是**运行期**配置（每次下载传一份），`AppConfig` 是**全局**配置。两者的字段高度重合但不同步——GUI 的 `_build_options()` 负责从 `AppConfig` 构造 `DownloadOptions`（见 `pages/parse.py`、`pages/download.py`、`server/app.py` 各有自己的 `_build_options()`）。

---

## 11. 登录体系

### 11.1 Cookie 落盘约定

- `~/.doubi/cookies/{douyin,bilibili}.txt`（Netscape 格式）
- yt-dlp 通过 `cookiefile` 选项直接消费
- 环境变量可覆盖：`DOUBI_BILIBILI_COOKIES`（B 站）、抖音类似

### 11.2 登录方式

| 平台 | 方式 | 实现 |
|---|---|---|
| B 站 | 扫码（二维码 + 轮询） | `qr_login.py` + `auth.py` |
| B 站 | Playwright 自动抓取 | `core/auth/browser_login.py` 的 `URLChangeLogin` |
| B 站 | 手动导入 cookie 文件 | `doubi auth bilibili --import cookies.txt`（Netscape/JSON） |
| 抖音 | Playwright 浏览器登录 | `browser_login.py` 的 `CookieSetLogin`（轮询 4 个关键 cookie） |
| 抖音 | 手动导入 | `--import` 或 `--legacy-json`（旧 douyin-downloader 的 cookies.json） |

### 11.3 登录态校验

- B 站：`validate_cookies()` 调 `https://api.bilibili.com/x/web-interface/nav`，解析 `isLogin/uid/uname/level`。
- 抖音：调 `https://www.douyin.com/aweme/v1/web/user/info/self/`（**注意：此端点未登录时返回 404，`validate_cookies` 会 catch 住当"未登录"处理**，这是预期行为不是 bug）。

### 11.4 GUI 登录入口

设置页 → "账号与登录"卡片（B 站/抖音各一行）：扫码登录 / 导入 Cookie 文件 / 抖音 legacy JSON。底层 `ui/auth_actions.py` 是纯 Python 包装（无 Qt 依赖，可单测）。

---

## 12. 四端入口

### 12.1 CLI（`cli/main.py` + `cli/auth_cmd.py`）

子命令：`platforms` / `download` / `auth` / `live` / `migrate`。

- 入口：`python -m doubi.cli.main` 或 `doubi`。
- **重要**：CLI 顶层 `from .. import platforms` 触发适配器注册。不要移除。

### 12.2 GUI（`ui/app.py`）

- 入口：`doubi-gui` 或 `python -m doubi.ui`。
- qasync 把 asyncio loop 跑在 Qt 主线程；GUI 里 `asyncio.create_task(...)` 直接可用。
- `--no-event-loop` 是开发调试开关。
- **如果没有 PySide6，`is_gui_available()` 返回 False，`main()` 抛 `GUIUnavailableError`**。

### 12.3 REST（`server/app.py`）

- 入口：`doubi-serve`。端点：
  ```
  GET  /api/v1/health
  GET  /api/v1/platforms
  POST /api/v1/download   {url}
  GET  /api/v1/jobs/{job_id}
  GET  /api/v1/jobs
  ```
- `JobManager`（`server/jobs.py`）内存任务队列，`max_concurrency=2`，TTL + cap 剪枝。
- **pydantic 坑**：body schema 必须模块级定义（`server/schemas.py`），路由参数显式 `Body(...)`，否则 pydantic v2 + `from __future__ import annotations` 会把它当 query 参数。

### 12.4 MCP（`mcp/server.py`）

- 入口：`doubi-mcp`。stdio 上行分隔 JSON-RPC 2.0。
- 工具：`platforms` / `parse_url` / `add_to_queue` / `get_status` / `list_jobs`。
- **stdout 只写协议**，日志全走 stderr。
- Windows stdin 用 `loop.run_in_executor(None, sys.stdin.readline)` 读（`connect_read_pipe` 不可靠）。

---

## 13. GUI 内部结构

### 13.1 页面与导航

`main_window.py` 的 `MainWindow(MSFluentWindow)` 注册 4 个页面：

| 导航 | 类 | 文件 | 职责 |
|---|---|---|---|
| 解析（默认首页） | `ParsePage` | `pages/parse.py` | URL 输入 → 解析 → 结果表勾选 → 加入下载 |
| 下载 | `DownloadPage` | `pages/download.py` | 任务管理（下载中/已完成 tab） |
| 历史 | `HistoryPage` | `pages/history.py` | SQLite 查询 + 刷新 + 打开目录 |
| 设置 | `SettingsPage` | `pages/settings.py` | 账号登录 + 运行配置 + 主题 |

每个页面模块暴露 `build_<page>_widgets()` 返回 `(class_, factory)`，Qt import 都在函数内**延迟加载**（无 PySide6 也能 import 模块）。

### 13.2 TaskManager（`ui/task_manager.py`）

- MainWindow 创建**一个** `TaskManager(pipeline)`，`parse_interface` 和 `download_interface` 共享。
- 职责：持有 active/completed 任务状态，去重（同 platform+item_id 不重复下载），发 Qt 信号。
- 信号：`task_added / task_progress / task_finished / task_failed / task_removed`。
- `TaskInfo`：task_id/item/options/status/fraction/title/error/created_at/finished_at。
- `DownloadPage` 是纯观察者：监听信号渲染 TaskRow（状态+标题+进度条+消息+移除按钮），任务完成时**复用同一行 widget** 从"下载中"布局挪到"已完成"（M5.4 修复，避免闪烁）。

### 13.3 关键交互流程

```
解析页：
  输入 URL → [解析] → pipeline.parse_and_expand(url)（strategy=None）
  → 结果表（勾选，全选/全不选/行号范围 1-5,7,9-12，搜索过滤，右键菜单）
  → [下载选中] → task_manager.add(item, opts)   ← 此时跳下载页可见任务

下载页：
  TaskManager → asyncio task → pipeline.download_item
  → 信号 → TaskRow 更新（进度条/状态）
```

**结果表行模型（ugc_season 三层结构）**

- **顶层行** = 一个合集分类（`extra._from_ugc_season_section=True`）。
  - checkbox 强制三态（`Qt.PartiallyChecked`）且 `Qt.ItemIsUserCheckable` 被去掉，**用户不能勾选也不能取消**——容器本身不该被直接送进下载队列（pipeline 会以 `Refusing to download container` 拒绝）。
  - 标题前缀 `▸ <分类> (<N> 分集)`。Hover 显示「分类容器不可直接下载 — 展开后勾选下面的分集」。
- **右键任意行** → 上下文菜单。每个菜单项的**可见条件**与它 handler 期望的行号语义必须严格对齐：

| 菜单项 | 可见条件 | handler |
| --- | --- | --- |
| `展开分类` / `折叠分类` | `is_top_row`（**行身份**判据，见下文陷阱）且 `_from_ugc_season_section`；按 `top_item.children` 是否非空切换文案 | `_expand_section_row` / `_collapse_section` |
| `展开分P` / `折叠分P` | `_episode_key_for_row(row) is not None` 且 `_from_ugc_season`；按 key 是否在 `_expanded_episode_rows` 里切换文案 | `_expand_episode_row` / `_collapse_episode` |
| `解析此项` / `在浏览器中打开` / `作为单个视频下载` / `查看元数据` / `查看封面` | 所有行 | 各自 handler；作用对象是 `episode_item or top_item` |

  容器项的「作为单个视频下载」会被 disabled 并改文案「（不可用，先展开）」。

**展开状态必须用稳定键，绝不能用行号（踩过的坑）**

树形表格里，任何兄弟节点的插入/删除都会让「行号」这个 key 静默失效。曾经的 bug：4 个 section 时先展开 section2（row=2）建立 `_expanded_rows[2]`，再展开 section0（row=0）插入 3 行 → section2 位移到 row=5 → `_expanded_rows.get(5)` 返回 `None` → section2 的 episodes 从映射里凭空消失。表象就是「展开逻辑混乱」。

现在的键设计（`parse.py`）：

| dict | key | value |
| --- | --- | --- |
| `_expanded_rows` | `(top_idx,)` | 该 section 展开出的 episodes |
| `_expanded_episode_rows` | `(top_idx, child_idx)` | 该 episode 展开出的 pages |

`child_idx` 是 episode 在 section 展开列表里的**位置**，与表格全局行号无关。

派生的五套只读缓存，全部在 `_refresh_row_mapping()` 里一次性重建：

| dict | 用途 |
| --- | --- |
| `_row_to_top_idx` | row → 顶层索引；**子行（episode/page）指向其所属 section** |
| `_top_to_row` | 顶层索引 → row |
| `_top_id_to_row` | 顶层 `item_id` → row，供 `_find_row_for_top_item` 做 O(1) 查找 |
| `_row_to_episode_key` | row → `(top_idx, child_idx)`，**仅** episode 行有值 |
| `_row_to_page_key` | row → `(top_idx, child_idx, page_idx)`，**仅** page 行有值 |

**交错布局：episode 行不连续，禁止偏移量算术（踩过的坑）**

`_expand_episode_row` / `_expand_section_row` 都用 `insert_at = row + 1` 把子行插在父行正下方，所以真实布局是**交错的**：

```
row0  sec0
row1  ep00        ← 展开了分P
row2   pg0
...
row6   pg4
row7  ep01        ← 不再是 row0+1+1
row8  ep02
row9  sec1
```

曾经的 bug：`_episode_key_for_row` 用 `offset = row - top_row - 1` 反算 `child_idx`，`_collapse_section` 用 `ep_row = row + 1 + child_idx`。ep00 一旦展开 5 页，`_episode_key_for_row(7)` 就返回 `None` → ep01/ep02 的右键菜单里「展开分P / 折叠分P」整项消失。用户报的表象是「分P能展开，分章能展开折叠分章」。

**修法：唯一真相收敛到 `_refresh_row_mapping` 的那一次遍历**，把 `row → key` 全部物化成上表的 dict，其余函数退化为 `dict.get(row)`：

- `_episode_key_for_row(row)` → `self._row_to_episode_key.get(row)`
- `_resolve_episode_for_row(row)` → 先查 episode key，miss 再退到 page key 的前两位（page 行的 owner）
- `_resolve_page_for_row(row)` → 新增，返回 page 行自己的 MediaItem
- `_collapse_section` → 用累加游标 `ep_row += 1 + page_count` 而不是 `row + 1 + child_idx`

**新增行归属缓存后，两处发射逻辑也必须跟着改**：`_resolve_download_targets` 和 `_selected_items` 都要**先** `_resolve_page_for_row`，命中就只发射那一个 page；episode 行若 pages 已展开则直接 `continue`（交由 page 行自己发射）。否则 page 行会因 `ep_key is None` 落进 episode 分支，把整集重复入队（实测多出一个 `ep00`）。

**改 `_fill_result_table` / `_expand_section_row` / `_collapse_section` / `_expand_episode_row` / `_collapse_episode` 这五个地方，都必须在 `blockSignals(False)` 之后调 `_refresh_row_mapping()`**，否则右键菜单会用陈旧行号点错项。

**折叠 section 要连带删除 page 行**：`_collapse_section` 不能只 `removeRow(row+1)` × `len(episodes)`——展开在 episode 之下的 page 行会残留（实测折叠后 `rowCount()` 应为 4，实际得到 9）。正确做法是先收集 `rows_to_remove`（episode 行 + 其 page 行），再 `sorted(rows_to_remove, reverse=True)` **自底向上**删除，避免删除过程中索引偏移。

**测试断言粒度决定 bug 逃逸率**：交错布局这个 bug 之所以完整逃逸，是因为旧测试只断言 `_row_to_top_idx` 和 `rowCount()`，从不断言 `_episode_key_for_row` / `_resolve_download_targets`。而 `rowCount()` 无法区分「删对了行」和「删错了行但数量相同」——必须断言存活行的**内容**。

回归测试见 `tests/test_row_mapping_cache.py`：

| 测试 | 覆盖 |
| --- | --- |
| `test_row_mapping_full_cycle` | 展开/折叠全循环，逐步断言 `_row_to_top_idx` 精确值 |
| `test_interleaved_page_rows_resolve_correctly` | 交错布局下每一行的 episode key / owner 解析 |
| `test_collapse_section_removes_exactly_the_child_rows` | 折叠后**存活行标题列表**，而非只看行数 |
| `test_download_targets_with_interleaved_pages` | 下载目标无重复、page 行只发射自己 |
| `test_only_section_rows_are_section_rows` | 只有 section 自己的行是 section 行，episode/page 行不是 |
| `test_collapse_section_ignores_non_top_rows` | 对子行调用 `_collapse_section` 必须是 no-op |

写这类测试要注意两点：stub 不能写 `return list(section_item.children)`——`adapter.expand_section` 有 children 非空短路，而 `_collapse_section` 会清空 children，第二次展开就会拿到空列表；另外 section 行的标题列渲染带装饰（`parse.py` 里 `f"▸ {title_text}  ({...} 分集)"`），读 column 2 得到的是 `'▸ sec0  (3 分集)'`，断言前要归一化。

**`_row_to_top_idx` 语义陷阱：判「是不是 section 行」必须用行身份（踩过的坑）**

`_row_to_top_idx` 的语义是「**这一行归属哪个顶层 section**」，所以 episode 行和 page 行也会映射到其所属 section 的 `top_idx`。这是刻意设计——任何一行都能问出「我属于哪个分类」。代价是：

> **`_resolve_top_item_for_row(child_row)` 返回的是 section 容器对象，不是那一行本身。**

因此**绝不能**用「resolved item 是不是 section」来判断「这一行是不是 section 行」。正确判据只有一个：

```python
top_idx = self._row_to_top_idx.get(row)
is_top_row = top_idx is not None and row == self._top_to_row.get(top_idx)
```

曾经的 bug：`_on_table_context_menu` 里「折叠分类 / 展开分类」只 gate 在 `top_item.extra.get("_from_ugc_season_section")` 上，于是右键**分章行**也会弹出「折叠分类」。点它 → `_collapse_section` 拿**分章的行号**查到 section 的 `top_idx` → `pop(_expanded_rows[(top_idx,)])` → 从「分章行 + 1」开始删行 → 把该分章的分P行连同后面的兄弟分章一起吃掉，表格与缓存彻底失步。用户报的表象是「分章取消可以折叠分类，不然他会把其他的分章给折叠了」。

**修法用纵深防御，三层都做**：

1. **菜单层**：`_on_table_context_menu` 用 `is_top_row` gate「折叠分类 / 展开分类」。（「展开分P / 折叠分P」那块本来就用 `_episode_key_for_row` 这个精确判据，无需改。）
2. **handler 层硬防护**：`_collapse_section` / `_expand_section_row` 在 `top_idx is None` 检查之后，再加 `if row != self._top_to_row.get(top_idx): logger.warning(...); return`。将来别处误传子行行号也只会留日志，不会损坏表格。
3. **语义修正**：`_is_section_row` 同样补上行身份检查（该函数当前无调用方，纯防御，避免将来误用）。

**教训**：菜单项的显示条件与其 handler 期望的行号语义必须严格对齐。显示用宽松判据、handler 用严格行号，就会造出「点了就坏」的破坏性操作。另外 `_on_table_context_menu` 在改动前**整个 tests/ 目录零覆盖**（grep `context_menu` 无命中），这是本轮 bug 完整逃逸的直接原因。

### 13.4 GUI 测试要点

- `QT_QPA_PLATFORM=offscreen` 无头运行。
- `asyncio.create_task` 在测试里没有 running loop → 测试里 monkeypatch 成同步执行（见 `test_parse_and_expand_gui.py` 的 `_make_create_task_sync`）。
- 异步测试用 `pytest-asyncio` 的 async test（`pyproject.toml` 已配 `asyncio_mode="auto"`），保证 `asyncio.get_event_loop()` 拿到同一 loop。

---

## 14. B 站风控专题（最重要的实战知识）

这是本项目踩坑最多的领域。**改 B 站相关代码前必读。**

### 14.1 现状：三类 URL 各自用什么通道

| URL 类型 | 实现通道 | 注意 |
|---|---|---|
| 单视频 `/video/BVxxx` | yt-dlp `api.fetch()` | 稳定，登录后有更高画质 |
| 合集 `/list/ml{id}` | **B 站官方 API** `/x/series/archives`（`MixStrategy`） | 先从 `/list/` HTML 用正则 `"mid":(\d+)` 抓 UP 主 mid，再分页调 API |
| 用户空间 `space.bilibili.com/{mid}` | **B 站官方 API** `/x/space/arc/search`（`SpaceStrategy`） | 已重写，不再走 yt-dlp（yt-dlp 的 `BilibiliSpaceVideo` 会 412） |
| 收藏夹/稍后再看/历史 | yt-dlp flat（`FavlistStrategy` 等） | **必须登录**，无 cookie 返回空 |

### 14.2 风控码速查

- **HTTP 412**：`Request is blocked by server`。yt-dlp 直连空间/合集页面时常见。应对：改用官方 API 通道，不用 yt-dlp 的 HTML extractor。
- **`code=-799`**：`请求过于频繁，请稍后再试`。官方 API 返回。应对：**WBI 签名**（`wts` + `w_rid`）。
- **`code=-400`**：`请求错误`。参数不合法——注意 **series/archives API 不接受 WBI 签名**（加了反而 -400），只有 space/arc/search 需要 WBI。
- **抖音 user/info/self 404**：未登录预期行为，`validate_cookies` 已 catch。

### 14.3 WBI 签名（`wbi.py`）

- 从 `/x/web-interface/nav` 拿 `wbi_img.img_url / sub_url` 两个图片 URL，取文件名作为 key。
- `sign_query(params, keys)` 给 params 加 `wts`（unix 秒）+ `w_rid`（md5）。
- `_get_wbi_keys()` 在策略实例上缓存（避免每次请求都打 /nav）。
- 策略里的重试逻辑：**先无签名请求，遇到 -799 再补签名重试一次**（见 `SpaceStrategy`/`MixStrategy` 的 expand）。

### 14.4 Cookie 合并陷阱（M5.4 修复过，别回退）

`BilibiliAPI._single_opts()` / `fetch_flat()`：
- **有 cookies 文件时**：`opts["cookiefile"]` + **不加** `http_headers.Cookie`（否则会**覆盖**文件里所有 cookie，SESSDATA 全丢，退化为匿名 → 412/-799）。
- **无 cookies 文件时**：才用 `http_headers = {"Cookie": f"buvid3={self._buvid3}"}` 兜底。
- `_build_cookie_header()`（strategies 里）：合并文件 cookie + buvid3，供 httpx 直连用。

### 14.5 buvid3

`generate_buvid3()` 生成匿名标识（uuid 风格 + `infoc` 后缀），每次 `BilibiliAPI()` 新建时生成。能轻微缓解 412，但不是根治——真正要稳定得登录（SESSDATA）或走官方 API + WBI。

---

## 15. 测试体系

16 个测试文件，284 个测试收集，**280 passed / 4 skipped**（`python -m pytest`）。pytest-asyncio `mode=auto`。4 个 skip 全是「无 PySide6 则跳过」的 GUI 用例。

| 文件 | 用例数 | 覆盖 |
|---|---|---|
| `test_bilibili_adapter.py` | 56 | B 站 URL 分类 / 策略（mock httpx）/ adapter |
| `test_bilibili_auth.py` | 41 | cookie 解析 / 校验 |
| `test_storage.py` | 37 | database / file_layout / manifest / migrate |
| `test_douyin_adapter.py` | 34 | 抖音 URL 分类 / parse / expand / `parse_and_expand`（含模块级 `_SpyEngine`） |
| `test_browser_login.py` | 24 | Playwright 登录流程 |
| `test_pipeline_smoke.py` | 18 | registry / URL 分类 / pipeline 解析 / CLI 冒烟 |
| `test_mcp.py` | 15 | JSON-RPC 协议 |
| `test_server.py` | 11 | FastAPI 端点 |
| `test_ui_workers.py` | 11 | GUI 可用性 / DownloadWorker |
| `test_ui_empty_parse.py` | 9 | ParsePage 空解析提示（需 PySide6，offscreen） |
| `test_auth_actions.py` | 8 | GUI 登录包装 |
| `test_row_mapping_cache.py` | 6 | **行映射缓存 / 交错布局 / 行身份判据**（见 §13.3） |
| `test_task_manager.py` | 6 | TaskManager 状态机 |
| `test_parse_and_expand_gui.py` | 4 | ParsePage 解析→表格（单视频/容器） |
| `test_download_page.py` | 2 | DownloadPage 渲染 / 全部删除 |
| `test_ytdlp_engine.py` | 2 | engine 目录预创建 |

**GUI 测试模式**：`QT_QPA_PLATFORM=offscreen` + `QApplication.instance() or QApplication(sys.argv)` fixture。无 PySide6 时 `pytest.skip`。

**测试纪律**：
- 网络相关必须 mock（httpx.AsyncClient / yt-dlp 模块 / asyncio）。
- 新增平台策略测试：mock `httpx.AsyncClient` 返回假 JSON（参考 `test_bilibili_adapter.py::test_mix_strategy_extracts_ml_id`）。
- 写含中文的测试文件用 write 工具（UTF-8），不要 PowerShell 改。
- **断言要断到最细的可观测量**。`rowCount()` / `len(targets)` 这类聚合量无法区分「做对了」和「做错了但数量凑巧相同」——树形表格的两个 bug 都是这样逃逸的。断言存活行的**标题列表**、断言 `_episode_key_for_row` 的**精确返回值**。
- **「某操作应为 no-op」用快照-循环-比对模式**：先快照全部相关状态（标题列表 + 各 dict），对每个非法输入循环调用并断言状态未变，最后用合法输入确认功能本身仍正常（否则可能"因为整个功能坏了"而假绿）。
- **右键菜单等 GUI 分支逻辑必须有测试**。`_on_table_context_menu` 长期零覆盖，直接导致「分章行出现折叠分类」这个破坏性 bug 完整逃逸到用户手里。

**PowerShell 常用命令**（注意 PS 里没有 `head`，用 `Select-Object -Last N`）：

```powershell
# 全量
python -m pytest --no-header -q 2>&1 | Select-Object -Last 20
# 单文件
python -m pytest tests/test_row_mapping_cache.py --no-header -q 2>&1 | Select-Object -Last 45
# 只收集不执行，核对用例数
python -m pytest --collect-only -q 2>&1 | Select-Object -Last 3
```

---

## 16. 代码约定与常见坑

### 16.1 约定

- `from __future__ import annotations` 全项目统一。
- dataclass + 类型注解，字段用默认工厂（`field(default_factory=...)`）。
- 日志用模块级 `logger = logging.getLogger("doubi.<path>")`。
- Qt import 延迟到 `build_*` 函数内（保持无 GUI 也能 import）。
- 平台私有扩展放 `extra` dict，不要加顶层字段（除非所有平台都需要）。
- 模块级辅助函数避免闭包捕获页面状态（GUI 页面模块的 helpers 放函数外）。

### 16.2 常见坑（全部踩过）

1. **pydantic body 路由推断失败**：`from __future__ import annotations` 下 FastAPI 会把 body schema 当 query。必须模块级定义 schema + 显式 `Body(...)`（见 `server/app.py`）。
2. **PowerShell 写中文乱码**：`Set-Content` 用 ANSI。写文件用 write/edit 工具或 Python。
3. **yt-dlp 不识别 `{title}` 花括号模板**：pipeline 先用 `naming.set_item_output_template()` 渲染成 `item.output_template`（纯字符串），engine 才追加 `%(ext)s`。
4. **`http_headers.Cookie` 覆盖 cookiefile**：见 §14.4。
5. **GUI 平台注册为空**：所有形态必须走 `build_default_pipeline()`（内部 import `platforms` 触发自注册）。不要裸 `DownloadPipeline(engine=YtDlpEngine())`。
6. **分P视频 playlist info.json 写目录失败**：engine 下载前预创建目录（§7.2）。
7. **aiosqlite Event loop closed**：`try/finally: await db.close()`。
8. **qtimer/qasync 删除**：测试结束时可能 "Signal source has been deleted"——无头测试里及时 `app.processEvents()` + drain tasks。
9. **Windows 路径长度**：目录组件上限 120 字符（`file_layout.py`），文件名 200（`naming.py`）。B 站长标题很容易撞上限。
10. **ruff line-length=100**：`[tool.ruff.lint] ignore=["E501"]` 放宽了行宽。
11. **树形表格用行号做 key / 做偏移量算术**：兄弟节点一插入，行号全部失效。展开状态必须用稳定键（`(top_idx,)` / `(top_idx, child_idx)`），行号只能是 `_refresh_row_mapping()` 派生的只读缓存。详见 §13.3。
12. **拿「某行 resolve 出的 item 是什么类型」当「这一行是什么行」**：`_row_to_top_idx` 让子行也指向所属 section，所以子行也能 resolve 出 section 对象。判行身份只能用 `row == _top_to_row.get(top_idx)`。详见 §13.3。
13. **`item.output_template` 只有一个写入点**：`naming.py:115`（`set_item_output_template`），读取点只有 `engines/yt_dlp.py` 和 `pipeline.py`。不要在 naming 里塞目录前缀——会与 `file_layout` 叠加导致合集名出现两层（踩过）。

---

## 17. 如何安全地修改项目（改动检查单）

无论改什么，按这个顺序自查：

### 改动前
1. 跑一遍 `python -m pytest` 确认基线全绿。
2. 找到受影响的所有端（core 改动 = 四端都受影响；只改 `pages/` = 只影响 GUI）。

### 改动中
3. **加新平台**：看 §6.4。
4. **改 B 站策略**：先读 §14。确保 cookie 合并不破坏、WBI 重试在、目录预创建在。
5. **加配置项**：`config.py` DEFAULTS + AppConfig + load_config + GUI 设置页 + 每端 `_build_options()`，五处都要动。
6. **改数据模型**：`models.py` 加字段时用 `field(default_factory=...)` 保持向后兼容；检查 `database.py` 的 `record_download` 是否要同步新字段。
7. **新 GUI 页面**：`pages/<name>.py` 暴露 `build_<name>_widgets()` → `pages/__init__.py` 导出 → `main_window.py` 注册。
8. **改解析页结果表（树形结构）**：三条铁律——① 任何增删行之后必须在 `blockSignals(False)` 之后调 `_refresh_row_mapping()`；② 不要用行号做字典 key，也不要用 `base + index` 反算行号；③ 判「这是不是 section 行」用 `row == _top_to_row.get(top_idx)`，不要看 resolve 出的 item 类型。改完跑 `tests/test_row_mapping_cache.py`。

### 改动后
9. 写/更新测试（新逻辑必须配测试；GUI 用 offscreen 模式）。
10. `python -m pytest` 全绿，且**用例总数只增不减**（减少 = 有测试被意外跳过或删掉）。
11. 更新 `docs/CHANGELOG.md`（按 M 里程碑分节）。
12. 若修的是「踩坑类」bug，把根因与判据写进 `docs/DEVELOPMENT.md` 对应小节 —— 光修代码不写文档，下一个人（或下一轮 AI）会原地重犯。
13. 用 `python -m doubi.ui` 手动冒烟 GUI（如果有改动 UI）。

### 提交前清理
- 删除临时调试脚本（`_diag*.py`、`_probe*.py`、`_repro*.py`、`_win_check.log` 等）。PowerShell 删不掉时用 Python：`python -c "import os; os.remove('...')"`。
- 不要提交 `doubi.db`、`Downloaded/`、`download_manifest.jsonl`、`_test_live/`（运行产物）。

---

## 18. 已知限制与路线图

### 已知限制

1. **B 站匿名风控**：UP 主页 / 合集枚举在无登录时受限（412 / -799），登录后稳定。已用官方 API + WBI 签名缓解，但 IP 级限流仍需等待窗口（几分钟）。
2. **抖音 user/info/self 404**：该端点已失效，`validate_cookies` 只能靠 catch 处理成"未登录"，无法确认有效登录态（下载本身走 yt-dlp 不受影响）。
3. **GUI 尚未实现**：全部暂停、断点续传（重启后恢复未完成任务）、已完成列表排序、弹幕/字幕/章节/NFO 下载（`DownloadOptions` 里字段已预留）。
4. **REST/MCP 的容器支持弱**：`process_url` 会展开容器，但 `_execute_download` 只算 succeeded=1。
5. **没有 i18n**：全中文硬编码。
6. **配置只读一次**：GUI 保存后需重启才生效的部分（代理等）没有提示重启。

### 对齐 Bili23 的路线图（已识别未做）

按 ROI 排序：
1. **下载选项弹窗**（每次下载前可调画质/音质/编码/附加内容，临时覆盖全局设置）——M5.4 之后最高优先。
2. **解析历史**（记录近期解析过的链接，一键重解析）。
3. **剪贴板监听**（复制链接自动弹"是否解析"）。
4. **头像/账号入口**（左下角显示登录态，一键登出）。
5. **附加内容下载**（弹幕 XML/ASS、字幕、封面、章节、NFO 刮削给 Jellyfin/Plex）。
6. **收藏页**（收藏夹/追番/稍后再看/历史记录，点击跳解析）。
7. **纯编号解析**（直接输入 av/BV/ep/ss/md 号）。
8. **重复下载 / 文件重名策略**、**画质音质编码优先级**、**CDN 切换**、**更新检查**。

### 建议的新功能（核心之外）

- 新平台：YouTube（`Platform.YOUTUBE` 已预留）、小红书、微博。
- 新引擎：aria2 多线程下载。
- 直播：抖音已支持，B 站直播录制未做。

---

*文档生成时间：2026-08-22 · 与 `docs/CHANGELOG.md` 的 M6.1 快照对应。维护者更新本文档时，保持"结构 + 关键 API + 踩坑记录"三要素即可，避免写与代码重复的长篇源码引用。*
