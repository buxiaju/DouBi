# DouBi 开发文档（面向 AI / 开发者）

> 目标：任何有能力的 AI 或开发者读完本文档，就能安全地修改、扩展、维护 DouBi，而不需要重新逆向整个项目。
> 版本对应：M0–M6.15（2026-08-25 快照）。配套文档：`docs/ARCHITECTURE.md`（分层图）、`docs/QUICKSTART.md`（用户操作）、`docs/CHANGELOG.md`（变更史）、`docs/ICONS.md`（图标管线）、`docs/BUILD.md`（打包）、`INTEGRATION_PLAN.md`（整合原始方案）。

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
14. [平台风控专题（B 站 + 抖音，最重要的实战知识）](#14-平台风控专题b-站--抖音最重要的实战知识)
15. [测试体系](#15-测试体系)（§15.1 可选依赖与 CI 口径差异）
16. [代码约定与常见坑](#16-代码约定与常见坑)
17. [如何安全地修改项目（改动检查单）](#17-如何安全地修改项目)
18. [已知限制与路线图](#18-已知限制与路线图)
19. [§13 节内子目录](#13-节内子目录)

### §13 节内子目录

- **§13.1** 页面与导航
- **§13.2** TaskManager
- **§13.3** 关键交互流程（结果表行模型 / 稳定键 / 交错布局陷阱 / 行身份判据）
- **§13.4** 主题系统
  - §13.4.1 数据结构（主题包）
  - §13.4.2 五层失效点
  - §13.4.3 公开 API
  - §13.4.4 接线与启动优先级
  - §13.4.5 新增一套主题要动哪里
  - §13.4.6 排版 / 间距 / 圆角 常量与辅助 QSS
  - §13.4.7 共享组件
- **§13.5** 图标管线（`ui/resources/`）
  - §13.5.1 三个文件，三种用途
  - §13.5.2 资源模块 API
  - §13.5.3 主窗口图标全链路
  - §13.5.4 模板回归守卫
- **§13.6** 打包成 Windows .exe
- **§13.7** GUI 测试要点

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
- 核心依赖：`yt-dlp`、`aiohttp`、`httpx`、`rich`、`pyyaml`、`python-dateutil`、`aiosqlite`、`qrcode`、`gmssl`（sm3，抖音 a_bogus 签名用——在 adapter→webapi→sign 的 **import 链顶层**，缺失则整个程序起不来，2026-08 起为硬依赖）
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
│   │   ├── yt_dlp.py              #   YtDlpEngine（默认引擎）
│   │   └── aria2.py               #   Aria2Engine（M6.15，多线程分片下载）
│   ├── platforms/                 # 平台适配器（见 §6）
│   │   ├── base.py                #   PlatformAdapter ABC
│   │   ├── douyin/                #   adapter / api / auth / strategies / url / live
│   │   └── bilibili/              #   adapter / api / auth / strategies / url / qr_login / wbi
│   │                              #   （M6.15 起 url.py 识别 live.bilibili.com 直播）
│   ├── cli/                       # main.py（download/auth/live/migrate/platforms）+ auth_cmd.py
│   ├── server/                    # app.py（FastAPI）+ jobs.py（JobManager）+ schemas.py
│   ├── mcp/                       # server.py（stdio JSON-RPC 2.0）
│   └── ui/                        # PySide6 GUI（见 §13）
│       ├── app.py                 #   qasync 事件循环入口
│       ├── main_window.py         #   MSFluentWindow 壳 + 页面注册 + TaskManager 持有
│       ├── task_manager.py        #   TaskManager（GUI 下载任务状态）
│       ├── workers.py             #   DownloadWorker（GUI 任务包装）
│       ├── auth_actions.py        #   登录流程的纯 Python 包装
│       ├── theme.py               #   主题包 / token 表 / set_theme（见 §13.4）
│       ├── i18n.py                #   JSON 词表 + tr() 翻译（M6.14，见 §17）
│       ├── locales/               #   zh_CN.json / en.json 词表
│       ├── pages/                 #   parse / download / history / settings
│       └── dialogs/               #   login_dialog.py
└── tests/                         # 25 个测试文件（见 §15）
```

**统计**（截至 0.1.0 / M6.8）：`src/` 70 个 .py 文件，约 15,200 行；
`pytest --collect-only -q` 收集 **454** 个用例。
数字会随开发漂移，改动较大时自己重取：

```bash
python -m pytest --collect-only -q | Select-Object -Last 1
```

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
     ├─ item.is_container() or media_type ∈ {USER, MIX}?
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
| `webapi.py` | ★ M6.7：**签名 Web API 客户端**（httpx + a_bogus）。合集/用户作品分页枚举、视频详情反查合集、`aweme_to_media_item()` 归一化。见 §14.6 |
| `sign/` | a_bogus / x_bogus 签名算法（移植自 douyin-downloader-main，MIT；abogus.py 依赖 `gmssl` 的 sm3） |
| `auth.py` | Cookie 文件管理（Netscape/JSON/legacy）、`validate_cookies()`（API 失败时降级为 session cookie 存在性判定） |
| `adapter.py` | `DouyinAdapter`：URL 匹配、parse、expand（post/like 策略 + MIX 合集分支）、`collection_of()` 反查、短链解析、modal_id → canonical 重写 |
| `strategies.py` | `PostStrategy`（用户主页作品）/ `LikeStrategy`（点赞列表）。M6.7 起 PostStrategy 优先走 `webapi.iter_user_posts`（yt-dlp flat 路径已静默失效，保留兜底） |
| `live.py` | `LiveRecorder`：抖音直播录制（max_duration、room.json sidecar） |

URL 分类示例：
- `https://www.douyin.com/video/{aweme_id}` → VIDEO
- `https://www.douyin.com/user/{sec_uid}` → USER（容器）
- `https://www.douyin.com/collection/{mix_id}`、`https://www.iesdouyin.com/share/mix/detail/{mix_id}/` → COLLECTION（合集容器，M6.7）
- `https://www.douyin.com/jingxuan?modal_id={aweme_id}`、`/user/{sec_uid}?...&modal_id={id}&vid={id}` → VIDEO（**modal_id / vid 就是 aweme_id**；这两条规则必须排在 USER 之前，否则用户页带 modal_id 的单视频链接会触发整个主页的容器展开）
- `https://v.douyin.com/xxx` → SHORT（先解析重定向再分类）

**抖音合集解析**（M6.7）：`parse()` 把 COLLECTION/MIX 路由到 `_parse_collection(mix_id)`，
返回 `MediaType.MIX` 壳（children 空、`extra={"mix_id": ...}`）；标题 best-effort——从
`get_mix_aweme` 第一页 items 的 `mix_info.mix_name` 探测（`/mix/detail/` 端点本身被风控 403，
不可用），失败则退化为 `抖音合集 {mix_id}`。`expand()` 的 MIX 分支走
`webapi.iter_mix_awemes` 分页枚举。`collection_of(aweme_id)` 供 GUI「右键 → 下载整个合集」
反查：调 `get_video_detail` 取 `mix_info.mix_id` 再返回合集容器。

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

### 7.3 Aria2Engine（`engines/aria2.py`，M6.15）

aria2 是纯下载器，不解析网页。`Aria2Engine.supports()` 只认有
`item.extra["direct_url"]` 的 item——没有直链的 item 自动回退 yt-dlp。

**RPC 协议**：通过 JSON-RPC 2.0 over HTTP 控制 aria2 守护进程：

* `aria2.addUri(uris, options)` → 返回 GID（任务 ID）
* `aria2.tellStatus(gid)` → 查进度（轮询，间隔 1 秒）
* `aria2.remove(gid)` → 取消任务

**客户端注入**：`Aria2RpcClient` 是 Protocol，生产用 `_HttpxAria2Client`
（基于 httpx），测试用内存 Mock（不依赖 aria2 二进制）。

**参数映射**（`_build_options`）：

| DownloadOptions | aria2 参数 |
| --- | --- |
| `concurrent_fragments` | `split` + `max-connection-per-server` |
| `rate_limit` | `max-download-limit`（透传 `5M` 格式） |
| `proxy` | `all-proxy` |
| `user_agent` | `user-agent` |
| `resume` | `continue` |

**取消**：`cancel_check` 返回 True 时调 `remove(gid)`，和 yt-dlp 一样是协作式。

### 7.4 引擎选择（`engine_loader.build_default_engine(cfg)`）

按 `cfg.engine` 选择引擎：

| 配置值 | 引擎 | 说明 |
| --- | --- | --- |
| `yt-dlp`（默认） | `YtDlpEngine` | 解析+下载一体，平台覆盖最广 |
| `aria2` | `Aria2Engine` | 多线程分片下载，只接 `direct_url` |
| 其他 | `YtDlpEngine` | 未知引擎名回退，避免配置写错让应用起不来 |

`build_default_pipeline(cfg=...)` 透传 cfg 给 `build_default_engine`。
CLI / REST / GUI 三端都走这个工厂，行为一致。

### 7.5 如何新增一个引擎

1. 继承 `Engine`，实现 `supports` / `download`。
2. 在 `config.py::DEFAULTS` 加引擎名（如 `"my_engine"`）和引擎私有配置字段。
3. 在 `engine_loader.build_default_engine(cfg)` 里加分支。
4. 测试用 Mock（参考 `test_aria2_engine.py`），不依赖真实二进制。

---

## 8. Pipeline（编排层）

文件：`src/doubi/core/pipeline.py`（约 330 行）。这是四端共享的核心。

### 8.1 公开 API

```python
class DownloadPipeline:
    def __init__(self, engine, max_concurrent: int = 3, *,
                 max_retries: int = 0,                  # 0 = 单次尝试，不重试
                 retry_backoff: float = 2.0): ...

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
- 内部 `_download_with_progress`：渲染文件名 → DB 去重检查（`is_downloaded`）→ **重试循环**（`engine.download`，失败则退避后重试）→ 成功后 `_record_success`（DB + manifest）。
- `ProgressEvent`：`job_id / item / phase / fraction / message / timestamp / extra`。phase 有 `parsing|expanding|downloading|merging|postprocess|done|failed`。

#### 8.1.1 自动重试与退避（M6.9 新增，改这块先读完本节）

四条硬约束，任意一条改错都会造成难查的行为退化：

1. **重试触发条件是 `ok is False`，不只是抛异常。** `YtDlpEngine.download` 把**所有**真实失败
   （含网络错误）都转成 `return False`，只判 `except` 等于永不重试。
2. **`DownloadPipeline` 自身默认 `max_retries=0`**（单次尝试），保持它是一个可预测的原语；
   自动重试这个**产品行为**只在 `core/engine_loader.build_default_pipeline()` 里打开
   （`DEFAULT_MAX_RETRIES = 2` / `DEFAULT_RETRY_BACKOFF = 2.0`）。
   这不是审美偏好而是成本决策：把类默认值改成 2，测试里那些「必然失败」的桩会全部乘上
   重试预算——实测让重试套件从 0.76s 涨到 12.79s，并弄坏 2 个测试。
   重试预算是**乘法**的：yt-dlp 内部已有 `retries: 3 / fragment_retries: 3`，
   外层每多一次尝试就把内层预算再乘一遍，所以外层默认值必须小。
3. **退避的 `await asyncio.sleep(delay)` 必须在 `async with self._sem` 之外。**
   否则一个正在退避的任务会占着并发额度睡觉，`max_concurrent=1` 时直接把队列堵死。
   由 `test_backoff_releases_the_semaphore` 用真实 sleep 的任务交错来钉死。
4. **用户取消也表现为 `ok is False`**，所以重试前必须先探测 `options.cancel_check`
   （`core/models.py`），否则「暂停」会被当成失败继续重试。探针本身抛异常时视为未取消
   （不能让一个坏探针杀掉下载）。

退避是指数的：`delay = retry_backoff * 2 ** (attempt - 1)`。最后一次尝试后不再 sleep。
每次重试会额外发一个通知事件，形状固定（GUI/CLI/REST 都按 `extra["retry"]` 识别）：

```python
ProgressEvent(phase="downloading", fraction=0.0,
              message="retrying (1/2) in 2s: engine returned False",
              extra={"retry": 1, "max_retries": 2,
                     "delay": 2.0, "reason": "engine returned False"})
```

注意 `phase` 是 `downloading` 而非新 phase——新增 phase 会让所有形态的 `_on_progress`
分支落到 else 里。CLI 因此必须把 `elif ev.extra.get("retry")` 分支放在 `--verbose`
分支**之前**，否则 `fraction=0.0` 的通知会被当成普通进度丢掉。

回归测试：`tests/test_pipeline_retry.py`（16 条，覆盖上述 4 条约束 + 工厂默认值 + clamp，
8/8 变异杀死）。`test_pipeline_smoke.py` 的桩永远成功，**结构上无法**发现重试循环的问题，
别指望它。

### 8.2 容器判定

pipeline 判断"这是不是容器"用两种方式：
- `item.is_container()`（`children` 非空）——但 parse 完时容器 children 是空的
- `item.media_type is MediaType.USER or item.media_type is MediaType.MIX`（M6.7 起含 MIX）

所以**容器解析逻辑**：适配器在 `parse()` 里把容器 URL 变成 `MediaType.USER/FAVLIST/MIX`
的壳 item（children 空），pipeline 看到这些 media_type 就去调 `adapter.expand()`。
判定出现在**三个地方**（`run()` / `download_item()` 的容器拒绝守卫 / `parse_and_expand()`），
改容器判定必须三处同步——漏一处会出现「能解析出 children 但下载时被拒绝」或反之。
**改容器相关逻辑时要同时看 adapter.py 和 pipeline.py**。

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

#### 13.2.1 跨进程恢复（M6.10）

重启后接续上次没下完的任务。三层，各自的边界很清楚：

| 层 | 位置 | 职责 |
|---|---|---|
| 持久层 | `core/storage/database.py` | `pending_task` 表 + `PendingTaskRow` + options 快照的编解码；任务入列时写行，终态时删行 |
| 状态层 | `ui/task_manager.py` | `list_restorable()` 读、`restore()` 复位成任务、`discard_restorable()` 忘掉、`_reseed_counter()` 防 id 相撞 |
| 交互层 | `ui/main_window.py` | `_offer_restore()`（构造函数尾部 `singleShot(0, ...)` 触发）+ `_restore_flow()` 弹窗询问 |

几个刻意的决定，改之前先读理由：

- **恢复出来的任务一律是 `paused`，绝不自动开跑**。刚重启是用户意图最不确定的时刻（可能只是想看看历史、可能换了网络），自动续传等于替他做决定。`.part` 文件在两种选择下都留着，所以「先问后续」不损失任何东西。
- **「不恢复」必须落库**（`discard_restorable`）。只在内存里跳过的话，下次启动会拿同一批任务再问一遍，用户要一直答「不」到手动清库为止。这是唯一一条「漏了不报错、但用户天天骂」的分支。
- **`restore()` 必须 `_reseed_counter()`**。`_counter` 是进程内自增的，重启后从 0 起，而恢复回来的任务带着上次的 `T0001`；不把计数器顶到恢复过的最大值，下一个新任务就会撞上一个已存在的 id（去重表和行映射会一起错乱）。撞上时 `restore()` 还会重新 key 一次（`task_manager.py:513-519`），那是第二层保险，不是替代品。
- **`_offer_restore` 用 `asyncio.get_running_loop()` 而不是 `get_event_loop()`**，没有运行中的循环就静默跳过。这样测试里直接 `MainWindow()` 不会凭空起一个恢复流程；测试要验流程时直接 `await window._restore_flow()`。
- **`self._restore_task = task` 那句不能删**：asyncio 只持弱引用，不留名字任务可能在跑到一半时被回收。

测试见 `tests/test_ui_restore.py`（12 个用例，5 轮破坏验证：删 `discard_restorable` / 断开 `task_added` / 删 `_reseed_counter` / 改成自动续传 / 删标题截断，各自只让对应的用例变红）。

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
| `下载整个合集` | 抖音 VIDEO 行（M6.7）：右键合集内任意一条视频反查并展开整个合集 | `_download_whole_collection`：`adapter.collection_of(item_id)` → `adapter.expand(container)` → `_fill_result_table(children)` |
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

### 13.4 主题系统（`ui/theme.py`）

**改任何界面配色前必读。** 这是整个 GUI 里最反直觉的一块：token 表写对了界面也可能一片白。

#### 13.4.1 数据结构：主题包，而非明暗开关

界面没有「亮/暗/自动」三选一，只有**命名主题包**。每个包自带明度：

```python
@dataclass(frozen=True)
class ThemePack:
    name: str    # 持久化用的稳定 key，写进 YAML，如 deep_sea
    label: str   # 界面显示名，如「深海」
    dark: bool   # 自带明度，决定 setTheme(Theme.DARK / LIGHT)
    accent: str  # 主色，喂给 setThemeColor()
    tokens: dict[str, Any]
```

7 套内置主题（`THEMES` 的键序 = 界面展示序 = 导航栏按钮的循环序）：

| key | label | dark | accent | bg_base | bg_layer |
|---|---|---|---|---|---|
| `default_light` | 默认亮 | ✗ | `#0078d4` | `#f3f3f3` | `#ffffff` |
| `default_dark` | 默认暗 | ✓ | `#4cc2ff` | `#202020` | `#2b2b2b` |
| `doubi` | 豆比紫 | ✓ | `#f59e6a` | `#1a1230` | `#251a3d` |
| `deep_sea` | 深海 | ✓ | `#2dd4bf` | `#0f1c24` | `#162b36` |
| `morandi` | 莫兰迪 | ✗ | `#8c7b6b` | `#eceae5` | `#f7f5f1` |
| `eye_care` | 护眼 | ✗ | `#3f7d58` | `#f5f1e8` | `#fbf8f1` |
| `high_contrast` | 高对比 | ✓ | `#ffd60a` | `#000000` | `#0d0d0d` |

**`doubi` 是品牌主题**——配色从 `resources/icon.svg` 反推，深紫底 + 琥珀橙
主色与图标本身是同一色系。注意它**不是**通过 `accent` 二次推导回来的：`icon_palette("doubi")`
直接返回 `BRAND_PALETTE`，否则用主色 `#f59e6a` 反推会让图标偏色，丢原图的味道。
详情见 §13.6。

token 键位（`_light_tokens()` / `_dark_tokens()` 是公共骨架，各主题只需给 5 个背景/文字值，语义色按需覆写）：

| 组 | 键 | 用途 |
|---|---|---|
| 背景 | `bg_base` / `bg_layer` / `bg_hover` / `bg_elevated` | 窗口底 / 卡片 / 悬停 / 浮起态 |
| 文字 | `text_primary` / `text_muted` | 正文 / 次级说明（走 `muted_qss()`） |
| 强调 | `accent` / `accent_soft` / `accent_strong` | 主色 / 浅底（hover/选中态） / 深色（pressed） |
| 表格 | `row_odd` / `row_even` | 交替行，用 `rgba` 以便叠在任何底色上 |
| 状态 | `status_{running,paused,completed,failed,cancelled}_{fg,bg}` | 任务状态徽标 |
| 进度 | `progress_{normal,success,error,paused}` | 自绘进度条 |
| 尺寸 | `radius` / `radius_card` / `radius_pill` / `row_height` | 圆角 / 行高 |
| 阴影 | `shadow_sm` / `shadow_md` / `shadow_lg` | 卡片 / 浮层 / 弹窗 |
| 装饰 | `gradient_header` | `header_qss()` 用的 hero 渐变，None 时退纯色 |

**M6.4 补全的字段**：`accent_soft` / `accent_strong` / `bg_elevated` / `radius_card` /
`radius_pill` / `shadow_*` / `gradient_header` 之前在 `ThemePack` dataclass 里没声明，
取色代码会 AttributeError。**所有 7 套主题的这些字段都必须存在**——`test_every_theme_has_full_token_set`
守着这条，新主题漏字段当场红测。

**语义色必须随明度重算，不能跨明度复用**：`#c02b2b` 这类暗红在深色底上几乎不可读，所以暗色骨架统一提亮到 `#ff6b6b` 一档。

#### 13.4.2 五层失效点（「每处颜色都要跟着变」的真正难点）

用户报的表象是「整体的背景没有变，解析口的颜色一直都是白色」。token 表当时**全是对的**——失效点全在 qfluentwidgets 的实现细节里，五层缺一层就有地方发白：

| # | 失效点 | 为什么 QSS / token 管不着 | 解法 |
|---|---|---|---|
| 1 | `setTheme()` 只有亮/暗两套 | 库内置调色板只有 `Theme.LIGHT` / `Theme.DARK`，`setThemeColor()` 只改强调色。六套主题的 `bg_base` 从来没生效过，用户只看到强调色在变 | `app_qss()` 把 token 表翻译成全局 QSS |
| 2 | Win11 **Mica** 毛玻璃 | 开启时 `_normalBackgroundColor()` 返回**全透明**，`setCustomBackgroundColor` 画了也看不见 | `_apply_window_background()` 先 `setMicaEffectEnabled(False)` 再设色 |
| 3 | 控件自带 QSS 压住全局 QSS | Qt 里**控件自己的样式表优先级高于 `QApplication` 的全局样式表**（全局表是优先级最低的兜底），而 fluent 给每个控件单独 `setStyleSheet` → `app_qss()` 只对原生 Qt 控件有效。`line_edit.qss` 的 `:focus` 更是写死纯 `white`，这就是「解析口一直是白色」 | `_refresh_fluent_widgets()` 用官方 `setCustomStyleSheet(w, light, dark)` 逐个覆盖 |
| 4 | 卡片底色是**自绘**的 | `CardWidget.paintEvent` 里 `painter.setBrush(self.backgroundColor)`，取值来自硬编码的 `QColor(255,255,255,170)`——半透明白，任何 QSS 都碰不到 | `_patch_fluent_card_background()` 猴补丁替换取色方法 |
| 5 | 切主题**之后**才创建的控件 | 下拉弹窗、右键菜单、登录对话框都是懒创建的，构造时向 `styleSheetManager.register` 领了库自带的亮色 QSS，错过刷新时机 → 又白回去 | `_patch_style_sheet_register()` 包一层 `register`，控件一登记就补当前主题 QSS |

三个关键库内部事实，值得单独记住：

- **`setCustomStyleSheet(widget, lightQss, darkQss)` 是官方留的覆盖口**：它写入控件属性 `lightCustomQss` / `darkCustomQss`，而 `StyleSheetCompose.content()` 把 `CustomStyleSheet` 拼在**最后**，同选择器后者胜。所以能干净覆盖而不必改库文件；反过来读 `widget.property("lightCustomQss")` 就是断言「这个控件被上过色」的可靠手段。
- **遍历对象选 `styleSheetManager.widgets`（一个 `WeakKeyDictionary`）而不是 `app.allWidgets()`**：前者正好是「被库设过样式表、因而压住了全局 QSS」的那批控件，一个不多一个不少；后者会把成百上千个原生子控件白刷一遍。卡片例外——它的颜色是自绘的、不保证登记在 manager 里，所以 `_iter_cards()` 老实走 `allWidgets()`。
- **`SimpleCardWidget` 自己重写过那三个取色方法**，只补 `CardWidget` 不生效，两个类都得显式覆盖。

#### 13.4.3 公开 API

| 函数 | 用途 |
|---|---|
| `theme_names()` / `theme_labels()` | key 列表 / 显示名列表，顺序一致，用来填下拉与 `--theme` 的 `choices` |
| `resolve_theme(value)` | 任意输入归一为合法 key：接受 key、显示名，以及兼容旧配置的 `light`/`dark`/`auto`。**无法识别时记 warning 并回退默认**，绝不因一个坏配置值让 GUI 起不来 |
| `get_theme(name)` / `current_theme()` / `current_theme_name()` | 取包 / 取当前包 / 取当前 key（可直接写配置） |
| `token(key, default=None)` | 取当前主题的一个 token |
| `muted_qss(size=12)` | 次级说明文字的 QSS。替代了各页面散落的 `setStyleSheet("color: gray;")`——字面量 `gray` 在暗底上对比度不足且换主题不刷新 |
| `app_qss(pack=None)` | 整套全局 QSS |
| `set_theme(name)` | **唯一的切换入口**，返回生效的 `ThemePack` |
| `subscribe_theme(widget, callback)` | 订阅主题变化，随 `widget` 销毁自动解绑；同时挂到库的 `themeChanged` 上 |

**`set_theme()` 内部六步顺序不能动**：

```python
setTheme(Theme.DARK if pack.dark else Theme.LIGHT)
setThemeColor(pack.accent)
_patch_fluent_card_background()   # 两个补丁必须早于刷新：
_patch_style_sheet_register()     # 卡片重算时取色方法要已被替换，
                                  # register 钩子要赶在后续控件创建之前就位
_apply_app_qss(pack)              # 铺全局 QSS（覆盖原生控件）
_apply_window_background(pack)    # 关 Mica + 刷主窗口自绘底色
_refresh_fluent_widgets(pack)     # 逐个覆盖现存 fluent 控件 + 重算卡片
_notify()                         # 通知订阅者刷新把颜色烘进 stylesheet 的控件
```

无 PySide6 时 `set_theme()` 只更新内部状态就返回，因此配置/解析逻辑在无 Qt 环境下也能测。

#### 13.4.4 接线与启动优先级

- **配置项**：`config.py` 的 `DEFAULTS["theme"] = "default_light"` + `AppConfig.theme` + `load_config` 的 `theme=str(data["theme"])` + 环境变量映射 `DOUBI_THEME`。
- **CLI**：`app.py` 的 `--theme` 用 `choices=theme_names()`，`default=None`——只有显式传参才覆盖。实际取值是 `args.theme or load_config(None).theme`，所以完整优先级是 **`--theme` > `DOUBI_THEME` > 配置文件 > `default_light`**（env 与文件之间的先后由 `load_config` 内部决定，`--theme` 在其外层短路）。`theme.py` 不 import Qt，所以能在 GUI 可用性检查之前安全导入，`--help` 也能列出主题。
- **持久化只发生在「保存设置」**：设置页下拉是 `_on_theme_combo_changed` → `set_theme()`，**选中即预览但不落盘**；只有 `_on_save()` 才 `data["theme"] = theme_name` 并写 `~/.doubi/config.yml`。导航栏画笔按钮同理，只切不存。改这块时别把「预览」误当成「已保存」。
- **`app.py` 里 `set_theme(theme_name)` 故意调了两次**，别当重复代码删掉：第一次在建窗口之前（各页面构造时要按当前 token 取色），但那时 `_apply_window_background` 遍历不到任何顶层窗口，主窗口底色和 Mica 关闭落不下去；窗口建好后必须再刷一次。
- **设置页下拉 ↔ 导航栏按钮双向同步**：`SettingsPage` 用 `subscribe_theme(self, self._sync_theme_combo)` 反向同步，`_syncing_theme` 标志位抑制信号回环（程序改动下拉时不该再触发一次 `set_theme`）。`MainWindow._cycle_theme()` 只调 `set_theme`，**不伸手进别的页面调私有方法**。
- **导航栏按钮只连一次线**：`navigationInterface.addWidget(onClick=self._cycle_theme)` 已经接过信号，再额外 `clicked.connect(self._cycle_theme)` 会让一次点击前进两个主题。

#### 13.4.5 新增一套主题要动哪里

只动 `theme.py`：在 `THEMES` 里加一项，背景/文字 5 个值传给 `_light_tokens()` / `_dark_tokens()`，语义色按需 `**骨架, "status_running_fg": ...` 覆写。`theme_names()` / `theme_labels()` / 下拉框 / `--theme` 的 `choices` / 导航栏循环全部自动跟上，`tests/test_theme_apply_gui.py` 也会自动为新主题参数化出 4 个用例。

#### 13.4.6 排版 / 间距 / 圆角 常量与辅助 QSS

M6.4 把散落的字号 / 间距 / 圆角也收到 `theme.py` 里。`accent_soft` 那五个新 token 之外还导出了两组常量：

| 常量 | 值序列 | 用途 |
| --- | --- | --- |
| `TYPE_H1/H2/H3/BODY/CAPTION/TINY` | 24/20/16/13/12/10 | 页面级排版尺度，**单调**递增（H1 最大） |
| `SPACE_XS/SM/MD/LG/XL/XXL` | 4/8/12/16/24/32 | 间距尺度，**单调**递增 |
| `RADIUS_DEFAULT/CARD/PILL` | 4/8/20 | 圆角三档（控件 / 卡片 / 胶囊） |

- 调整这些值会让全应用随之变化——不要在某个页面里覆盖成字面量。
- 辅助 QSS 函数取代散落的 `setStyleSheet("color: gray;")`：
  - `heading_qss(level=1..3)` — 页面级标题
  - `body_qss()` — 正文字号 / 字色
  - `muted_qss()` — 次级说明（暗色骨架上重算灰度，避免「字面 gray 对比度不足」）
  - `card_qss(elevated=False)` — CardWidget 边框 / 背景
  - `header_qss(level=1..3)` — 标题区渐变（`gradient_header` 存在时走渐变，否则退纯色）
- 这些函数**不带 Qt 副作用**：返回的是字符串，调用方 `widget.setStyleSheet(...)`。
  这样可以把整段 QSS 拼出来一次塞给一个布局，而不是给每个 widget 单独调一次。
- `test_typography_constants_are_exposed` + `test_helper_qss_functions_return_strings`
  + `test_header_qss_uses_gradient_or_fallback` 三道测试守着：常量存在且单调、函数
  返回非空、渐变/纯色分支都覆盖。

#### 13.4.7 共享组件（`ui/widgets.py`）

解析 / 下载 / 历史 / 设置四个页面 + 三个对话框要复用同一套设计语言，
于是有了 `ui/widgets.py`。每个组件是一个工厂函数，**不依赖 PySide6 也能
import**——class 体在工厂内部，模块顶层只暴露 `build_*` 函数。

| 工厂 | 类 | 用途 |
| --- | --- | --- |
| `build_page_header()` | `PageHeader` | 页面级「标题 + 副标题 + 右侧动作」三段式，四个页面统一 |
| `build_empty_state()` | `EmptyState` | 居中占位态（图标 + 主标 + 副标），空表格 / 空列表用 |
| `build_stat_chip()` | `StatChip` | 顶部统计小方块（"3 个正在下载"），4 种 kind 颜色 |
| `build_platform_badge()` | `PlatformBadge` | 圆形彩色平台徽标（B 站蓝 / 抖音红） |
| `build_section_divider()` | `SectionDivider` | 卡片内的「细横线 + 副标题」分组分隔 |

**API 约定**：

```python
Header = build_page_header()       # 工厂调用一次拿 class
header = Header(parent)            # class 实例化
header.set_title("下载")
header.set_subtitle("...")
header.add_action(my_button)       # 右侧动作槽
```

**关键设计取舍**：

- **不取代 qfluentwidgets**。`PushButton` / `LineEdit` / `ComboBox` 这些
  还在直接用，共享组件是「需要统一表达力」时用。强行包一层会让我们失去
  fluent 控件的样式跟随能力。
- **延迟 import Qt**。`class _PageHeader(QWidget)` 写在工厂里，
  `from doubi.ui.widgets import build_page_header` 在无 PySide6 的 CI 环境
  也能跑（headless 装 PySide6 的 tox task 之外，配置 / 解析单元测试都是
  这样的）。
- **构造函数接 parent**：遵循 Qt 父子关系约定，主题广播时通过
  `subscribe_theme` 跟 `parent.destroyed` 信号自动解绑。
- **StatChip 的 `set_kind` 是枚举式的字符串**（`"running"` /
  `"paused"` / `"completed"` / `"failed"`），不是 enum。**字符串可读性
  高 + 不需要 import 复杂 enum**，单元测试时直接 `set_kind("running")`
  就能验；4 种 kind 都用 `test_stat_chip_set_value_and_kind` 守住。

### 13.5 图标管线（`ui/resources/`）

#### 13.5.1 三个文件，三种用途

`ui/resources/` 目录里有三种图标，**用途完全不同**：

| 文件 | 用途 | 运行时 | 何时生效 |
| --- | --- | --- | --- |
| `icon.svg` | 设计源稿（含 filter / clipPath） | 不参与 | — |
| `icon_template.svg` | 渲染模板（QtSvg 安全子集 + 7 个换色锚点） | 是 | 标题栏 / 关于 / 登录对话框 / 闪屏 |
| `icon.png` | 1024px 兜底位图 | 仅在 QtSvg 不可用时 | PyInstaller 打包后兜底 |
| `icon.ico` | Windows .exe 资源图标 | 操作系统 | Windows 任务栏（仅打包后生效） |

**设计源稿** (`icon.svg`)：用户提供 1124×1124 的设计稿，带 `<filter>`
投影 + `<clipPath>` 裁剪 + `<feGaussianBlur>` 等。**不直接渲染**——Qt 只
实现 SVG Tiny 1.2，实测 `feColorMatrix` 投影层被当成「实心黑圆角矩形」
画在最上层，29% 像素变纯黑，整张图标糊掉。保留它作为视觉参考 / 重设计
参考。

**渲染模板** (`icon_template.svg`)：同一张图重写为 QtSvg 安全子集：
- 去掉 `<filter>` / `<clipPath>` / `<fe*>`（clipPath 本来就是 no-op，
  裁剪框完全包住两个腮红椭圆）
- viewBox 收紧到 `50 30 1024 1024`，让圆角方块**出血铺满**画布
  （源稿四周 4.5% 是死边——图标在标题栏 / 任务栏里看着偏小就是这段
  留白吃掉的）
- 投影由 `rim-light` 描边近似（视觉损失可忽略）
- 7 个品牌色 hex 既是模板字面量，**也是换色锚点**——`icon_svg(accent)`
  一次正则替换完成。`BRAND_PALETTE` 必须与模板**逐字一致**（含大小写），
  否则漏色

**兜底 PNG** (`icon.png`)：从模板 SVG 渲染 1024×1024，仅在 QtSvg 不可用
时（如极老的 PySide6 发行版）走这条。运行时检测到 QtSvg 失败会自动
退化，调用方什么都不用改。

**Windows .ico** (`icon.ico`)：多档位 PNG 合集，用于 PyInstaller 打包时
嵌进 .exe 资源段——这是 Windows 任务栏读取「应用分组图标」的唯一渠道。
详见 [docs/BUILD.md](../BUILD.md)。

#### 13.5.2 资源模块 API

```python
from doubi.ui.resources import (
    APP_NAME, APP_DISPLAY_NAME, APP_VERSION, APP_COPYRIGHT,  # 品牌元数据
    BRAND_PALETTE,                                            # 7 色 → 语义名
    icon_path, icon_source_path, icon_template_path,          # 路径
    icon_palette, icon_svg,                                   # 换色
    render_icon_pixmap, load_app_icon, load_splash_pixmap,    # 渲染
    clear_icon_cache,                                         # 测试 / 热替换
)
```

**`icon_palette(accent=None)`** 按主色推导整套图标配色：

- 底板渐变 = 主色色相 ±20°，亮度 0.63 → 0.68
- 呆毛 = 同色相再沉一档（亮度 0.52）
- 脸 = 主色色相的极浅色（亮度 0.90），冷色主题下自然变成薄荷/淡蓝奶油色
- **腮红 / 舌头 / 眼睛恒定**——这三是吉祥物辨识度的核心，跟主题变色
  会丢掉可爱感。主题识别度由占比 70% 以上的底板承担，已经足够
- 饱和度不是照抄主色而是压缩到 `0.42 + 0.55 * s`：莫兰迪这类低饱和主题
  如果强行拉满会变成刺眼的橙色，与主题气质相悖
- `accent=None` / 不可解析 / 脏色值 → **退化到 `BRAND_PALETTE`**
  （不抛异常，不让一个错误配置把整个 GUI 起不来）

**`icon_svg(accent=None)`** 换色 + 返回 SVG 文本：

- 一次**正则替换**完成，不是逐色 `str.replace`——后者在「A 被换成 B，
  B 又被下一轮替换」时会产生二次命中，产出错色
- 替换锚点是模板里的 7 个品牌色字面量；**这些字面量必须与 `BRAND_PALETTE`
  完全一致**（`test_icon_template_exists_and_holds_all_anchors` 守着）

**`render_icon_pixmap(size, accent=None, *, themed=True)`** 渲染单张图：

- `themed=True` 时 `_active_accent()` 自动从 `current_theme()` 取主色
- `themed=False` 固定品牌原色
- `size <= 0` → 返回 `None`（不抛）
- 按 `(size, accent)` 缓存到 `_pixmap_cache`，同一主题切来切去不会重复渲染

**`load_app_icon(size=None, ...)`** 装填 QIcon：

- `size=None` 时填入 `ICON_SIZES` 全部 8 档位（16/20/24/32/40/48/64/
  96/128/256）——Qt 在标题栏 / 任务栏 / Alt+Tab 各挑最合适的一档，
  避免系统强制缩放产生锯齿与白边
- `size=N` 时只装填一档（用于对话框 / 闪屏）
- 按 `accent` 缓存到 `_icon_cache`

**`load_splash_pixmap(w, h, ...)`** 闪屏专用：`min(w, h)` 边长的矢量渲染——
比「渲染大图再缩放」少一次重采样。

**`_active_accent()`**：根据当前主题返回图标主色。**豆比紫主题下返回
`None`**——它本身取自图标，再用主色二次推导只会偏离原图。这是产品
决定，不是技术 bug。

#### 13.5.3 主窗口图标全链路

```
set_theme(...)
  → subscribe_theme(self, _refresh_app_icon) 自动触发
  → load_app_icon() 渲染新配色
  → self.setWindowIcon(icon)
  → QApplication.setWindowIcon(icon)         ← 任务栏 / Alt+Tab 同步
  → windowIconChanged 信号
  → qfluentwidgets.FluentTitleBar.setIcon(icon)
  → iconLabel.setPixmap(QIcon(icon).pixmap(18, 18))    ← 这里
```

**`qfluentwidgets.FluentTitleBar.setIcon` 把 pixmap 尺寸写死 18px**——
48px 高的标题栏里 18px 图标明显偏小。修法（`main_window.py::MainWindow._enlarge_titlebar_icon`）：

1. `iconLabel.setFixedSize(28, 28)`（`TITLEBAR_ICON_SIZE` 常量）
2. 断开 `windowIconChanged → title_bar.setIcon` 的旧连接
3. 改用 `set_icon(icon)` 闭包，按新尺寸重设 pixmap
4. 全程防御性处理（拿不到 `iconLabel` 就放弃，不影响主窗口）

**为什么必须断开旧信号**：qfluentwidgets 在 `FluentTitleBar.__init__` 里
`self.window().windowIconChanged.connect(self.setIcon)`。如果只改
`iconLabel` 尺寸没换槽函数，下一次 `setWindowIcon` 触发信号，旧
`setIcon` 会把 `iconLabel.pixmap` 打回 18px。`_enlarge_titlebar_icon`
一定要在 `disconnect → connect` 这一对操作之间完成，顺序反了会
丢信号。

**关于 / 登录对话框补 setWindowIcon**：这三个 dialog 之前没设
`windowIcon`，Windows 任务栏 / Alt+Tab 会回退到 **python.exe 的双蛇 logo**
（用户报的「Python 终端图标」就是这个）。修法是 `self.setWindowIcon(load_app_icon())`
+ 工厂函数顶部 import `load_app_icon`。防御性写法：

```python
icon = load_app_icon()
if icon is not None and not icon.isNull():
    self.setWindowIcon(icon)
```

——`load_app_icon` 在 QtSvg 不可用时返回 None，dialog 仍然能跑，只是
没有自定义图标（Windows 用 python.exe 双蛇兜底）。

#### 13.5.4 模板回归守卫

Qt 只实现 SVG Tiny 1.2，**任何**新贡献的 SVG 都可能踩 filter 坑。守卫：

- `test_icon_template_has_no_unsupported_svg_features` 剥掉 XML 注释
  后查 `<filter` / `<clipPath` / `filter=` / `clip-path=` / `<fe`。
  这条测试抓过「在模板注释里写 `<filter>` 也算」这种假阳性——剥注释
  后再查。
- `test_render_icon_pixmap_size_and_no_black_block` 渲染 128px 后
  统计纯黑像素占比 < 5%。`feColorMatrix` bug 的症状就是 29% 像素
  变纯黑，>5% 阈值足够抓回归。
- `test_icon_template_exists_and_holds_all_anchors` 模板必须含
  全部 7 个品牌色字面量——漏一个 `icon_svg(accent)` 替换会漏色。

### 13.6 打包成 Windows .exe 与安装包（`scripts/build_exe.py` / `build_installer.py`）

详见 [docs/BUILD.md](../BUILD.md)。要点：

- **入口用「构建期生成的启动壳」，不是包内文件、也不是 `--module`**。
  `app.py` 内部是 `from .theme import ...` 相对导入，直接把它当入口，
  它会被当成顶层 `__main__`，`doubi` 父包不存在，相对 import 直接挂
  `ImportError`。启动壳位于包外面，用绝对导入 `from doubi.ui.app import main`
  进包，包结构就完整保留了。
  **PyInstaller 没有 `--module` 选项**（6.22.2 报 `unrecognized arguments`）。
- **必传 `--icon src/doubi/ui/resources/icon.ico`**——这是 Windows
  任务栏读取「应用分组图标」的唯一渠道。`QApplication.setWindowIcon`
  改不了任务栏，必须靠 .exe 资源。
- 第三方 Qt 库（qframelesswindow / qfluentwidgets）有隐藏的 QRC 资源
  / 插件，PyInstaller 默认钩子抓不全，`--collect-all <pkg>` 显式补一遍。
- 产物 `dist/doubi-gui.exe` 约 235 MB，PyInstaller onefile 把 Python
  runtime 全打包，正常体积。
- **发给最终用户走安装包**：`python scripts/build_installer.py` 先出
  onedir 产物，再用仓库内置的便携版 NSIS（`tools/nsis/`）压成
  `dist/DouBi-Setup-<version>.exe`（约 213 MB）。免 UAC 装到
  `%LOCALAPPDATA%\DouBi`，注册表只写 HKCU，卸载零残留而 `~/.doubi` 保留。
- **版本号只有一处真源**：`pyproject.toml` 的 `version` 被
  `build_installer.py` 读走并 `/D` 注入 NSIS；UI 侧是
  `src/doubi/ui/resources/__init__.py` 的 `APP_VERSION`。改版本要同时动这两处，
  历史上曾漂移成「UI 显示 0.6.0 而安装包写 0.1.0」。



### 13.7 GUI 测试要点

- `QT_QPA_PLATFORM=offscreen` 无头运行。
- `asyncio.create_task` 在测试里没有 running loop → 测试里 monkeypatch 成同步执行（见 `test_parse_and_expand_gui.py` 的 `_make_create_task_sync`）。
- 异步测试用 `pytest-asyncio` 的 async test（`pyproject.toml` 已配 `asyncio_mode="auto"`），保证 `asyncio.get_event_loop()` 拿到同一 loop。
- **主题测试刻意依赖库的私有接口**（`_normalBackgroundColor` / `_isMicaEnabled` / `lightCustomQss`）。这不是偷懒：断言 `THEMES` 里的色值毫无意义（token 表一直是对的，界面照样发白），只有断言「控件实际生效的颜色」才守得住 §13.4.2 那五层。上游哪天把这些改名，测试必须**当场红掉**，而不是界面悄悄变回白色。
- **会改全局状态的 GUI 测试要自己收尾**。`test_theme_apply_gui.py` 用 autouse fixture 在每个用例后 `set_theme("default_light")`，否则同进程的其他 GUI 测试会被残留主题污染。
- **循环里做断言必须加「至少查到一个」的守卫**：`assert checked, "主窗口里一个 fluent 控件都没找到，测试失去意义"`。少了这一行，一旦控件找不到，整个用例会因为循环体没执行而假绿。
- **GUI 集成测试反复 `build_main_window()` 前，先确认窗口真的拆掉了**：M6.5
  那阵曾想加 4 个 titlebar 测试，每个新建一个 MainWindow 后 deleteLater。
  实测：pytest 的 `qapp` 是 module-scope 复用，`deleteLater` 排队但
  不会被事件循环执行（除非手动送事件），下一个测试
  set_theme 时广播到 4~5 个死回调，`Mica 样式 + QSS 全树重算` 累加
  起来从「慢」劣化到「hang」。两条出路：**共享一个 module-scope 的 window
  fixture**（`test_theme_apply_gui.py`），或者**在拆卸时补
  `QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)`**
  把析构真的兑现（`test_ui_restore.py`，实测回调数每轮归零）。根因与
  实测数字见坑位 31 —— 贵的不是「构造」，是**没死透的旧窗口**。

### 13.9 YouTube 适配器（M6.12，`platforms/youtube/`）

- **URL 分类**：watch / shorts / embed / live / youtu.be 五种视频形态 +
  /@handle / /channel/UC... 频道 + /playlist 三类容器。11 字符 video ID
  必须用 `(?:[&#]|$)` 或 `(?:[?#]|$)` 锚定——否则 ``watch?v=IDextra``
  这类 12 字符 URL 会被错认为合法。**坑位 34**
- **元数据获取**：`adapter.parse` 内调
  ``asyncio.to_thread(yt_dlp.YoutubeDL.extract_info(download=False))``，
  仿浏览器 UA。任何异常（SSL / 限流 / 解析失败）都降级为占位 item——
  ``title="YouTube <id>"``、``author.name=""``、``duration=None``，
  并在 ``extra["meta_extract_failed"]=True`` 标记。**不让 ``parse``
  抛异常穿过到 pipeline**，否则用户看到的是「解析失败」弹窗，可 URL
  是合法的、网络只是临时不通——参见 YouTubeAdapter 自身的 try/except
- **故意不实现**：channel / playlist 容器展开（yt-dlp 自己处理）、
  danmaku / 字幕 / NFO post-processing（YouTube 字幕由 ``writesubtitles``
  选项拉）、cookie 注入（YouTube 不需要）。``post_download`` 保留为
  空实现但**显式存在**——让读 adapter 的人知道「这里**特意**没做事」
  而不是「忘了写」
- **架构验真**：YouTube adapter 总共不到 200 行，对比 B 站 / 抖音各自
  1000+ 行（容器策略 / 签名 / cookie）。证明架构允许「按平台复杂度
  调整 adapter 厚度」——同一套 base / registry / pipeline 不变
- **测试** ``tests/test_youtube_adapter.py`` 31 例：URL 分类 11 类用
  parametrize、`to_watch_url` 归一化、parse 单元路径 + 降级路径、
  registry 路由、ad-hoc 破坏验证。**全部不联网**——`_extract_meta`
  用 monkeypatch 替换

### 13.10 注册收敛（M6.12）

- 原 3 处 ``from ..platforms import douyin, bilibili`` 的副作用 import
  （``server/app.py`` / ``mcp/server.py`` / ``core/engine_loader.py``）
  合并为单点 ``from .. import platforms``。**新增 platform 时只需改
  ``platforms/__init__.py`` 一处即可**，3 个上层模块不需要任何改动

### 13.8 下载前选项对话框（M6.11，`ui/pages/parse.py::_PromptOptionsDialog`）

- 触发：设置页「主题与外观」里 `prompt_before_download` SwitchButton，
  默认 **False**。启动时主窗口读初值下发，用户切换后通过
  `promptBeforeDownloadChanged` 信号实时下发，不必重启
- 入口：解析页「快速下载」「下载选中」两处都先调 `_ask_prompt_overrides()`，
  用户取消 → 整批不入队；用户确认 → 用 `collect_prompt_overrides(dlg)`
  拿到 4 字段 dict，调 `_options_for_overrides(overrides)`
- 右键菜单「作为单视频下载」**不**接弹窗——右键本身已是明确操作
- **单一边界保证**：overrides 永远叠在已搬运好的 `DownloadOptions` 上，
  按 `dataclasses.fields(DownloadOptions)` 白名单过滤；任何「绕过
  `_build_options` 直接拼 options」的尝试都会撞守卫测试
  `test_build_options_covers_every_shared_config_field`
- 选项集合复用设置页 `["mp4","mkv"]` / `["best","8k","4k","1080p","720p","480p"]`——
  两处选项列表不一致就是 bug
- 测试 `tests/test_prompt_options.py` 11 例（弹窗 `exec()` 会进模态
  循环，offscreen 下卡死，所以只覆盖非模态面：构造 / 字段收集 /
  ParsePage 集成 / YAML 往返）

---

## 14. 平台风控专题（B 站 + 抖音，最重要的实战知识）

这是本项目踩坑最多的领域。**改 B 站 / 抖音相关代码前必读。**

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

### 14.6 抖音 Web API 签名与反爬（M6.7，`platforms/douyin/webapi.py` + `sign/`）

抖音合列举/用户作品列举**没有 yt-dlp 抽取器**（2026.08 版离线 `ie.suitable()` 验证：user /
collection URL 均落到 generic fallback），只能走签名 Web API。

**通道速查**：

| 需求 | 端点 | 说明 |
|---|---|---|
| 合集分页列举 | `GET /aweme/v1/web/mix/aweme/?mix_id=&cursor=&count=` | 主力通道，实测可用 |
| 合集详情 | `GET /aweme/v1/web/mix/detail/` | **实测 403（风控）**，不要依赖；合集标题改从列举第一页的 `mix_info.mix_name` 探测 |
| 视频详情 | `GET /aweme/v1/web/aweme/detail/` | `aid` 参数 6383 / 1128 两候选，用于 `collection_of()` 反查 |
| 用户作品 | `GET /aweme/v1/web/aweme/post/` | `iter_user_posts` 分页枚举 |

**签名（a_bogus）**：
- 值由 **query string + User-Agent + 浏览器指纹** 计算，实现在 `sign/abogus.py`
  （865 行，sm3 依赖 `gmssl` 包，pip 装的不是标准库）。
- msToken 策略：优先取 cookie 文件里的 msToken；没有则用 **182 随机字符伪 token** 兜底
  （参考项目同款做法，风控放行）。
- `_signed_url()` 签名失败时**降级为不签名**发出（不阻断主流程），由重试层兜底。

**反爬信号与重试（`_request_json`）**：
- **HTTP 200 但 body 为空 = 反爬**（最阴险的一种，不是成功也不是失败）→ 重新签名重试。
- 403 / 429 / 461 / 471 / 5xx 同样进重试；延迟 1s / 2s / 5s 递增，最多 3 次。
- **每次尝试都重新取 msToken**——同一 token 连发更容易被识别。

**分页枚举（`iter_mix_awemes` / `iter_user_posts`）**：
- 响应归一化为 `{items, has_more, max_cursor}`；用 `max_cursor` 翻页直到 `has_more=False`。
- **cursor 卡死保护**：服务端偶发返回与上页相同的 cursor 却仍有 has_more，直接 break，
  否则死循环。

**归一化（`aweme_to_media_item`）**：
- `source_url` 一律写成 canonical `https://www.douyin.com/video/{aweme_id}`——下载阶段
  走 yt-dlp，它只认这个形态。
- title 取 `desc` 首行（多行文案会把文件名撑爆）；duration 从 ms 转 s；
- `mix_info` 写进 `extra["mix_id"] / extra["mix_name"]`（供 GUI 反查与目录用）。

---

## 15. 测试体系

27 个测试文件，676 个测试收集，M6.12 实测 **672 passed / 4 skipped**（`python -m pytest -q`，`QT_QPA_PLATFORM=offscreen`，耗时 ~25 分钟）。pytest-asyncio `mode=auto`。skip 全是「无 PySide6 则跳过」的 GUI 用例。

> 全量跑一次接近半小时，主要成本在真实 `asyncio.sleep` 的退避与超时用例上。日常改动请按 §15 表格挑相关文件跑；**只有在动了 `pipeline.py` / `engine_loader.py` / `models.py` 这类被四个界面共享的文件后，才有必要付全量的代价**。

| 文件 | 用例数 | 覆盖 |
|---|---|---|
| `test_server_security.py` | 81 | **REST 鉴权与绑定**：token 恒定时间比较 / 缺失与错误 token / 公网绑定告警 / `--allow-insecure` 逃生阀（参数化占大头） |
| `test_bilibili_adapter.py` | 56 | B 站 URL 分类 / 策略（mock httpx）/ adapter |
| `test_storage.py` | 55 | database / file_layout / manifest / migrate / **`pending_task` 表与 options 快照编解码** / **取消时的连接泄漏与毒化回归（坑位 27·28）** |
| `test_ui_polish.py` | 45 | UI 品牌化 / 组件工厂 / **EmptyState 间距回归（防静默回退）** / 图标管线 |
| `test_douyin_adapter.py` | 43 | 抖音 URL 分类（modal_id / vid / 分享链）/ parse / expand / `parse_and_expand` / 登录态 cookie 降级判定 |
| `test_bilibili_auth.py` | 41 | cookie 解析 / 校验 |
| `test_task_manager.py` | 31 | TaskManager 状态机 / 暂停恢复的双机制与 stale 守卫 / fraction 倒退守卫（坑位 26）/ **跨进程恢复的状态层：`list_restorable` · `restore` · `discard_restorable` · `_reseed_counter`** |
| `test_theme_apply_gui.py` | 28 | **主题真落到像素上：窗口底色 / 现存控件 / 卡片自绘 / 切换后新建控件**（需 PySide6，offscreen；跑一次 ~3 分钟，全量慢主要慢在这里） |
| `test_pipeline_smoke.py` | 28 | registry / URL 分类 / pipeline 解析 / **引擎 cookie 注入** / CLI 冒烟 |
| `test_browser_login.py` | 28 | Playwright 登录流程（含 networkidle 陷阱回归） |
| `test_config_theme.py` | 26 | **配置地基（`to_dict` / env 覆盖 / YAML 往返）+ 主题注册表 / `resolve_theme` 兼容旧值 / token 键一致 / 无 Qt 也能 `set_theme`**（见 §13.4） |
| `test_server.py` | 19 | FastAPI 端点 |
| `test_sidecars.py` | 17 | 附属文件：NFO 生成/开关 + B 站弹幕（bvid/cid 定位、deflate 解码、失败不抛） |
| `test_cli_config_layering.py` | 17 | **CLI 配置分层**：命令行 > 环境变量 > 配置文件 > 默认值，`--x/--no-x` 三态开关不再把「未指定」当 False |
| `test_pipeline_retry.py` | 16 | **重试与退避**（见 §8.1.1）：`ok is False` 也重试 / 指数退避 / 退避不占并发额度 / 取消不重试 / 工厂默认值与 clamp。**8/8 变异杀死** |
| `test_mcp.py` | 15 | JSON-RPC 协议 |
| `test_ui_context_menu.py` | 12 | 解析页右键菜单（含 `UnboundLocalError` 回归；`QMenu.exec` 需子类化替身，见 §14） |
| `test_ui_restore.py` | 12 | **跨进程恢复的交互层（见 §13.2.1）**：空库/缺文件不问 / 恢复即暂停且不自动下载 / 「不恢复」落库只问一次 / 恢复后新任务 id 不撞 / 标题截断与兜底（需 PySide6，offscreen） |
| `test_ui_empty_parse.py` | 12 | ParsePage 空解析提示（需 PySide6，offscreen） |
| `test_ytdlp_engine.py` | 11 | engine 目录预创建 / 字幕与断点续传选项 / 取消不算错误 / `.part` 保留策略 |
| `test_youtube_adapter.py` | 31 | **YouTube 适配器（M6.12）**：watch / shorts / embed / live / youtu.be / @handle / channel / playlist 分类 / 11 字符 ID 定长校验 / 占位降级路径 / `detect` 路由（不联网，monkeypatch） |
| `test_ui_workers.py` | 11 | GUI 可用性 / DownloadWorker |
| `test_prompt_options.py` | 11 | **下载前选项对话框（M6.11）**：弹窗 seed / `collect_prompt_overrides` 字段收敛 / `_options_for_overrides` 不污染其他字段 / 关闭后等于 `_build_options` / YAML 往返（需 PySide6，offscreen） |
| `test_auth_actions.py` | 8 | GUI 登录包装 |
| `test_version_single_source.py` | 7 | **版本号单一真源**：`pyproject.toml` 为唯一源，`APP_VERSION` 派生且不漂移 |
| `test_row_mapping_cache.py` | 6 | **行映射缓存 / 交错布局 / 行身份判据**（见 §13.3） |
| `test_download_page.py` | 5 | DownloadPage 渲染 / 全部删除 |
| `test_parse_and_expand_gui.py` | 4 | ParsePage 解析→表格（单视频/容器） |

**GUI 测试模式**：`QT_QPA_PLATFORM=offscreen` + `QApplication.instance() or QApplication(sys.argv)` fixture。无 PySide6 时 `pytest.skip`。改全局状态的 GUI 测试（主题就是典型）必须用 autouse fixture 复位，否则先跑的用例会污染后跑的——详见 §13.5。

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

> 坑：`Select-Object -Last N` 会**缓冲到进程退出**才输出。后台跑一个长任务时
> 屏幕上一直空白，看着像挂了其实在跑；判断是否真挂要看 `-q` 的
> `[ NN%]` 进度是否停滞（改成 `| Tee-Object log.txt` 可以边跑边看）。

### 15.1 可选依赖：测试里必须 `importorskip`（M6.21 血的教训）

`pyproject.toml` 把依赖分成三档，**只有基础依赖在任何环境里都装得到**：

| 档位 | 内容 | 测试里能否裸导入 |
|---|---|---|
| `[project] dependencies` | yt-dlp / aiohttp / **httpx** / rich / pyyaml / python-dateutil / aiosqlite / qrcode / gmssl / playwright | **可以** |
| `optional-dependencies.gui` | PySide6 / PySide6-Fluent-Widgets / psutil / qasync | 不行 |
| `optional-dependencies.server` | **fastapi / uvicorn / pydantic** | 不行 |

CI（`.github/workflows/build.yml`）只装 `pip install .` + `pytest pytest-asyncio
ruff`，**不带任何 extras**。所以：

- 任何会走到 gui / server 档依赖的测试，**入口处必须**
  `pytest.importorskip("pydantic")` 之类的守卫。既有范例：
  `test_server.py:24-26`、`test_server_security.py:277-278`、
  `test_prompt_options.py:40`、`test_version_single_source.py:92`。
- **`importorskip` 放函数内、不要放模块顶层**，除非整个文件都依赖它。
  `test_config_forwarding.py` 就是反例边界：同一个文件里 CLI / MCP 两条守卫
  只用 stdlib，其中一条还是纯源码文本断言，不该被 REST 的可选依赖连坐。
- **懒导入不能替代 `importorskip`**。`server/__init__.py` 是 PEP 562 懒导入模块
  （见 §12.3），那只挡住「`import doubi.server.security` 被 pydantic 连坐」，
  挡不住 `from doubi.server import app`——后者要的就是重型链本身。
  0.3.0 发版 CI 就是这么红的：`app.py → schemas.py → from pydantic import ...`，
  而 `schemas.py` 的模型**必须**定义在模块顶层（Pydantic v2 要把注解解析成真类型）。

**本地跑绿 ≠ CI 会绿**，两边测试集互不包含：

| | 本地惯用 | CI |
|---|---|---|
| 命令 | `pytest -m "not slow"` | `pytest -q --maxfail=5`（**无 mark 过滤**） |
| 依赖 | 装齐 extras | 只有基础依赖 |
| `test_theme_apply_gui.py` | 真起 Qt 事件循环，**极慢甚至挂住** | 无 PySide6 → skip |
| 耗时参考 | 10 分钟+ | 45.82s |

发版前把关要用**模拟 CI 依赖集**的跑法（写个临时脚本，往 `sys.meta_path`
插一个 `find_spec` 对 pydantic/fastapi/uvicorn/PySide6/qfluentwidgets/qasync/psutil
抛 `ModuleNotFoundError` 的 Blocker，并清掉 `sys.modules` 里已导入的同名模块，
再 `pytest.main(["-q", "--maxfail=5"])`）。M6.21 实测 **629 passed / 146 skipped
/ 104.79s**，与 CI 的 `628 passed + 1 failed + 146 skipped` 逐项对齐——
**passed+failed 相等且 skipped 相等**两个条件同时成立，才能说环境等价且没有
测试被多跳过（只看前者，可能是「少收集了用例而变绿」；只看后者，可能是
「把报错掩盖成 skip」）。

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
5. **GUI 平台注册为空**：所有形态必须走 `build_default_pipeline()`（内部 import `platforms` 触发自注册）。不要裸 `DownloadPipeline(engine=YtDlpEngine())`。**M6.9 起这个工厂还负责打开自动重试**（见 §8.1.1），裸构造的 pipeline 除了平台注册为空，还会静默丢掉重试能力——`cli/main.py` 曾经就是这样，已修。
6. **分P视频 playlist info.json 写目录失败**：engine 下载前预创建目录（§7.2）。
7. **aiosqlite Event loop closed**：用 `async with Database(path) as db:`（`Database` 实现了异步上下文管理器协议，`initialize()` 幂等、`close()` 自带空守卫）。手写 `try/finally: await db.close()` 也对（`ui/pages/history.py` 就是，语义完全等价），但四行里漏一行就复现这个错误，没有理由不用 `async with`。反过来，**不要让一个 DB 连接跨越整个下载**：aiosqlite 每个打开的连接背后是一个活线程，而一次下载可能跑几小时——`pipeline.py` 里去重探测与 `_record_success` 故意是两个短周期。**注意 `async with` 只保证「一定会调用 `close()`」，不保证「`close()` 一定跑完」**——取消可以打断它，见坑位 27 / 28。
8. **qtimer/qasync 删除**：测试结束时可能 "Signal source has been deleted"——无头测试里及时 `app.processEvents()` + drain tasks。
9. **Windows 路径长度**：目录组件上限 120 字符（`file_layout.py`），文件名 200（`naming.py`）。B 站长标题很容易撞上限。
10. **ruff line-length=100**：`[tool.ruff.lint] ignore=["E501"]` 放宽了行宽。
11. **树形表格用行号做 key / 做偏移量算术**：兄弟节点一插入，行号全部失效。展开状态必须用稳定键（`(top_idx,)` / `(top_idx, child_idx)`），行号只能是 `_refresh_row_mapping()` 派生的只读缓存。详见 §13.3。
12. **拿「某行 resolve 出的 item 是什么类型」当「这一行是什么行」**：`_row_to_top_idx` 让子行也指向所属 section，所以子行也能 resolve 出 section 对象。判行身份只能用 `row == _top_to_row.get(top_idx)`。详见 §13.3。
13. **`item.output_template` 只有一个写入点**：`naming.py:115`（`set_item_output_template`），读取点只有 `engines/yt_dlp.py` 和 `pipeline.py`。不要在 naming 里塞目录前缀——会与 `file_layout` 叠加导致合集名出现两层（踩过）。
14. **`asyncio.to_thread` 里的活干不掉**：`YtDlpEngine.download` 是 `await asyncio.to_thread(self._download_sync, ...)`。`Task.cancel()` 只能在**下一个 await 点**生效，而线程里的 yt-dlp 根本不回到事件循环，所以取消**永远打不断已开始的传输**。唯一可行的是协作式取消：`DownloadOptions.cancel_check` 由进度钩子每个 tick 轮询。推论有两条：① 进度钩子必须**无条件注册**（哪怕调用方没传 `on_progress`），否则没人轮询；② `TaskManager._stop_attempt` 必须**双机制**——先置 flag（够得到线程里的传输），再 `task.cancel()`（覆盖「还没进引擎」的窗口，如卡在并发信号量上）。
15. **停止标志按「尝试」持有，不能按 task_id**：暂停中的 worker 可能仍在引擎线程里跑，而 `resume()` 已经 spawn 了新尝试。若两次尝试共享一个 flag，`resume()` 清 flag 就等于**复活旧线程** → 两个写者抢同一个 `.part` 文件。所以 `_flags` 每次 spawn 都装一个新的 `_StopFlag`，并配 stale 守卫（`_forget` 只在 `_tasks.get(task_id) is task` 时清理），否则将死的旧尝试会把 `paused` 盖到新尝试的 `running` 上。
16. **协作式停止表现为 `ok is False`，不是异常**：引擎自己吞掉了 `DownloadCancelled`，所以「这是暂停还是真失败」只能靠查 flag。判据必须写成 `flag.stopped and not ok`——少了 `not ok`，一个**已经下完**的文件会被迟到的暂停请求标成 `paused`，任务就永远停在那里无事可做。
17. **`add()` / `resume()` 只是排程**：协程体在下一次 loop yield 才开始跑。测试里紧跟着 `pause()` 会在协程碰到 pipeline 之前就把它取消掉（曾因此假失败 6 个用例）。这**不是生产 bug**（真实环境永远有 loop 在跑），修在测试侧：用 `_started()` 补一次 `await asyncio.sleep(0)`。
18. **`_build_options()` 漏字段是「静默失效」，不是报错**：引擎与 `file_layout` 只认 `DownloadOptions`，**从不读 `AppConfig`**，所以每端的 `_build_options()` 是唯一搬运环节。曾实际漏掉：GUI 少 `write_nfo` / `write_danmaku` / `write_subtitles` / `resume` / `output_dir_template`，REST 少 `output_dir_template` / `proxy` / `rate_limit`——表现是控件能点、配置能改，但毫无效果。判据是「`AppConfig` 与 `DownloadOptions` 的同名字段交集必须逐个抵达 options」，已由两端的结构性测试固定下来。
19. **结构性测试必须用非默认值填充，否则是假保险**：`test_build_options_covers_every_shared_config_field` 第一版直接拿 `AppConfig()` 原值比对，把 `resume=self._cfg.resume` 删掉竟然照样通过——两个 dataclass 的 `resume` 默认值都是 `True`，「漏转发」和「转发了」结果完全相等。凡是「拿默认对象比对默认值」的测试都有这个盲区：**先把每个字段推离默认值再比**，并对没覆盖到的字段类型 `pytest.fail`（而不是跳过），否则新类型一进来检查强度就悄悄降级。改完后分别删 `resume`、`max_quality` 各验证一次变红，才算这层保险是真的。
20. **抖音 modal_id / vid 规则必须排在 USER 规则之前**（`url.py::_PATTERNS`）：用户主页「合集」tab 打开的单视频链接形如 `/user/{sec_uid}?...&modal_id={id}&vid={id}`，先匹配 USER 会把单视频误判成用户容器，触发整个主页的作品展开。顺序即语义。
21. **抖音风控的「空 200」**：HTTP 200 + 空 body 不是成功，是反爬拦截（见 §14.6）。任何抖音 Web API 响应解析前必须判空，命中则重新签名重试。
22. **容器判定必须用 `needs_expansion()`，不要散写**：容器解析时 children 刻意不填（惰性展开），`is_container()` 只看 children 非空会漏掉 `USER`/`MIX` 这类无 children 的惰性容器。M6.14 起统一为 `item.needs_expansion()`——它同时覆盖「children 非空」和「`media_type ∈ CONTAINER_MEDIA_TYPES`」两种情况。新增一种惰性容器类型时，把它加进 `CONTAINER_MEDIA_TYPES` 即可，pipeline 各处 `needs_expansion()` 调用点自动跟上；不要再回到 `is_container() or media_type in (...)` 的散写。
23. **登录成功后的落地页永远到不了 networkidle**：feed 流 / WebSocket 长连接 / 心跳是常态。Playwright 里不要用 `wait_for_load_state("networkidle")` 当「登录完成」信号，用固定短 settle 或直接轮询 `context.cookies()`。
24. **判定平台登录态要用「登录后才会出现的 cookie」**：sessionid / sessionid_ss / sid_guard（抖音）；不要用设备标识（ttwid / odin_tt——游客也有）或 JS 风控 token（msToken——自动化下经常不写入）。名单错向两个方向都翻过车：真登录抓不到 + 游客误判成功。
25. **引擎阶段的 cookie 与解析阶段是两条通道**：解析在 adapter（自己读 cookie 文件），下载在 engine（只认 `DownloadOptions.cookies_file`）。四个入口都不传 cookies_file 时引擎裸跑。M6.7 起在 pipeline 层懒加载注入（显式指定优先），修一处救四端。
26. **`ProgressEvent.fraction` 不一定是「测量值」，也可能只是「消息的占位」**：重试通知带 `fraction=0.0`，因为那一刻确实没有传输在进行。GUI 原先无条件 `info.fraction = ev.fraction`，于是每次瞬时失败都把停在 80% 的进度条打回 0，看起来像「从头重下」——而 `resume=True` 时它并没有。**新增任何"通知型"事件都必须检查四端的 fraction 消费者**（当前全库只有 3 处读 `ev.fraction`：`ui/task_manager.py`、`cli/main.py`、`pipeline.py` 的引擎事件转发）。守卫要写成「按 `extra["retry"]` 判定」，**不能**写成「fraction 变小就忽略」——续传的下一次尝试本就会报更小的值，单调钳制会把进度条冻在过期高点。`"retry"` 这个键是重试通知独占的（引擎侧 extra 只用 `speed`/`eta`/`filename`/`cancelled`），可以安全当判据。由 `test_task_manager.py` 的 4 个用例钉死（含一个「正常事件仍允许倒退」的反向用例）。
27. **`asyncio.shield` 挡不住 runner 级别的取消，而「打开连接」被取消会泄漏一个裸 sqlite3 句柄**：`shield` 只切断**从 awaiter 传来**的取消，对「把 loop 上每个 task 全部 cancel 一遍」的清扫（`asyncio.Runner` 关闭、pytest-asyncio teardown）完全无效——被 shield 的内层 task 自己也在那张名单上。于是 `Database.initialize()` 里那次 connect 会**直接**在工作线程起步阶段被取消，而 aiosqlite 的补救路径 `Connection.stop()` 里 `close_and_stop` 带 `if self._connection is not None` 守卫，此刻 `_connection` 还是 `None`——**它什么都没关**；随后 connector 照样跑完，造出一个**真实句柄**，工作线程带着它死在 `core.py` 的 `66 → 72 → 75` 双投递级联上（第 66 行往已关闭的 loop 投递失败，被 72 行的 `except BaseException` 接住，75 行又往**同一个死 loop** 投一次），`__del__` 在第 99 行静默 early-return，最后只剩 CPython 一句 `ResourceWarning: unclosed database`。**能可靠关掉那只句柄的唯一时机，是它在工作线程上诞生的那一瞬**——从别的线程关会撞 sqlite3 的同线程守卫，事后往队列里塞一个 close 又永远追不上工作线程自己的死亡。所以守卫必须放进 `connector` **内部**（`_guarded_open`），并且这次打开要**手工驱动**（`wrapper._tx.put_nowait((None, _guarded_open))`），因为结果投递也得由我们自己做、自己用 `except RuntimeError` 兜住。「放弃」必须是一个**显式声明**的状态（`abandoned` 标志 + 锁），而且要在 `sqlite3.connect` 前后**各查一次**——它在飞行途中就可能被声明。由 `test_a_handle_born_after_the_cancellation_is_still_closed` 钉死：用 `threading.Event` 在工作线程里卡住 `sqlite3.connect`，并且**必须先等 `entered` 再取消**，否则测的是「connector 还在队列里」那条容易得多的分支。
28. **`close()` 可以被取消，但不可以被中止；`self._conn = None` 写在 `await` 之后会把对象永久毒化**：`aiosqlite.Connection.close()` 把真正的 `sqlite3.close` 排进工作线程、并在自己的 `finally` 里清掉 `_connection`，所以一次穿过我们 `await` 的取消**回调不到这些动作**——句柄照样关掉、工作线程照样退休（实测，两种时序都验过：取消发生在关闭已抵达工作线程之后，和取消发生在它还没走远之前）。**这里没有句柄泄漏。**真正被取消毁掉的是原先写在 `await` 之后的 `self._conn = None`：跳过它，`Database` 就抱着一具尸体，而且是**永久**抱着——`initialize()` 开头 `if self._conn is not None: return`，重新打开成了静默空操作，此后每一次查询都抛 `ValueError: no active connection`，一辈子好不了。修法只有一个字：**顺序**，先摘引用再 await，这样被取消的关闭只是「早退」，不是「致命」。`initialize()` 失败清理路径本来就是对的（`self._conn = None` 在 `await asyncio.shield(conn.close())` 之前），无需改。目前生产侧四处构造全是「用完即弃」的短周期（`task_manager.py` / `pipeline.py` 的 `async with`、`history.py` 的 try/finally），毒化只是潜伏、还没咬人——但**挂死或永久报错严格地比崩溃更糟**。这条的测试断言只能落在**复用**上（取消后 `initialize()` + `count()` 必须成功）：查句柄、查工作线程、查 warning 在修复前后都一样通过，等于没测。
29. **多场景探针里的 monkeypatch 必须逐场景撤销**：查坑位 28 时给 `sqlite3.Connection` 做了计数子类（`close` 是只读属性，实例上 patch 不了，只能靠 `factory=` 在 connect 时注入），结果读数是「关闭 0 次」，看着像发现了新泄漏。实际是探针自己污染：第一个场景结束时没把 `sqlite3.connect` 还原，第二个场景捕获到的「原始」connect 其实是前者的 gated 版本，它会把 `kwargs["factory"]` 覆写回自己的子类，计数器根本没挂上。还原后读数变成 1，泄漏是假的。**一切「疑似新 bug」先怀疑工装**——尤其当工装动过全局状态。同理，`ResourceWarning` / `gc.collect()` 本身会改变症状是否出现，验证必须固定三个严格开关：`-W error::pytest.PytestUnhandledThreadExceptionWarning -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning`。
30. **切页动画会让 `currentWidget()` 在 300ms 内继续返回旧页**：qfluentwidgets 的 `window/stacked_widget.py::StackedWidget.setCurrentWidget(widget, popOut=True)` —— `popOut` **默认就是 True** —— 转发到 `PopUpAniStackedWidget.setCurrentIndex(..., needPopOut=True, ...)`，而那条分支**不调** `super().setCurrentIndex()`，只记下 `self._nextIndex` 并把当前页动画出去，真正的 `QStackedWidget.setCurrentIndex` 推到 `__onAniFinished` 里执行。于是「断言跳转到了某页」在调用后立刻查会失败。修在测试侧：fixture 里 `win.stackedWidget.setAnimationEnabled(False)`，走 `if not self.isAnimationEnabled: return super().setCurrentIndex(index)` 那条同步快路。**不要改成 sleep 等动画**（慢，且是按时间赌），也不要把断言弱化成「调用过 setCurrentWidget」——那就不再验证用户到底看见了什么。注意启动时切到首页不受影响：`index == currentIndex()` 会提前 return，根本没有动画，所以这个坑只在「运行中切页」的测试里现身。
31. **`deleteLater()` 在不转 Qt 事件循环的测试里等于没拆**：它只是 post 一个 `DeferredDelete` 事件，没人消费队列就永远不析构，`destroyed` 信号不发，于是 `subscribe_theme()` 挂的主题回调**一个都不会解绑**。实测：连建 3 个 MainWindow 后 `theme._callbacks` 是 57，`deleteLater()` 之后仍是 57；补一句 `QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)` 才降到 0（单个窗口贡献 19 个回调）。这正是 §13.7 那条「不要反复 `build_main_window()`」的成因——问题不在「反复构造」，而在**残留的死回调**，后续任何 `set_theme()` 都要广播到一堆指向已弃控件的闭包上，从「慢」劣化到「hang」。所以按函数建主窗口是**可行**的，前提是拆卸时把这一种事件真的送出去（`tests/test_ui_restore.py` 的 `window` fixture 就是这么做的）。选 `sendPostedEvents` 而不是 `processEvents`，是因为后者会连带跑其他排队事件，扩大测试间的耦合面。
32. **qfluentwidgets 的 `MessageBoxBase` 没有 `view` widget，只有 `viewLayout`**：项目里这个版本（1.x）的 `MessageBoxBase.__init__` 直接 `self.viewLayout = QVBoxLayout()` 然后 `self.vBoxLayout.addLayout(self.viewLayout, 1)`——没有 `self.view`。GitHub 上 README 的示例（包括 `addWidget(self.view)`、`viewLayout.addLayout(...)` 的混用）是不同版本的混合印象，**看本地源码为准**。同理，按钮文案默认是 `OK / Cancel`（`PrimaryPushButton(self.tr('OK'))`），不是 `yesButton / cancelButton` 之外另有标签入口——直接在子类的 `__init__` 末尾 `self.yesButton.setText("下载")` 改掉。**别去 `setWindowTitle`**——它会被父类的 `MaskDialogBase.__initWidget` 重新设一次，运行时看不见，但写测试时容易掉进去。
33. **qfluentwidgets 的 `SwitchButton` 暴露的是 `checkedChanged(bool)`，不是 `toggled(bool)`**：`SwitchButton` 不是 `QCheckBox`，它**重命名了** Qt 标准的 `toggled` 信号；`hasattr(switch, 'toggled')` 是 False，`self.prompt_before_download.toggled.connect(...)` 会抛 `AttributeError`。同理 `QAbstractButton` 的 `stateChanged(int)` 在它身上也没有。只能 `checkedChanged` / 自定义 `clicked` 那一套。看到现有设置页用 `self.database.isChecked()` 读值、用 `self.database.setChecked(cfg.database)` 写值，但**没接信号**——说明旧代码要么不需要在切换时做事，要么把状态变化归到「点保存按钮」一次性读取而不是每个控件的信号回调。新增「切换即生效」的偏好时，记得连的是 `checkedChanged`。
34. **YouTube video ID 必须定长 + 锚定**：ID 是 11 字符 `[A-Za-z0-9_-]`，但单写 `{11}` 不够——``watch?v=dQw4w9WgXcQextra`` 会把前 11 个字符匹配上，剩 ``extra`` 被当成「后续参数」，于是你**以为**拿到合法 video ID 实际是合法 ID + 尾巴。正确做法：watch 模式后面接 ``(?:[&#]|$)``（参数分隔符或字符串结尾），短链 youtu.be 模式后面接 ``(?:[?#]|$)``。这是 YouTube adapter 第一个回归测试期望（``test_sabotage_wrong_id_length_misses_url``）就专门盯着的——任何「我去掉那个锚」都会让 12 字符 ID 测试变红。

---

## 16.5 i18n 基础设施（M6.14）

### 设计取舍：为什么不用 Qt `.ts` / `.qm`

Qt 的 `tr()` 绑死 `QObject` 子类——模块级函数（CLI、REST、日志）用不了，
翻译覆盖面被「有没有继承 QObject」切一刀；`lupdate` / `lrelease` 两步构建
依赖工具链，CI 上多一层麻烦。

改用 **JSON 词表 + 模块级 `tr()`**：

* 词表是普通 JSON，人能直接读改，无需编译步骤。
* `tr()` 是模块级纯函数，任何代码都能调（GUI / CLI / REST / 日志通用）。
* 回退顺序：当前语言 → `zh_CN`（源语言/兜底）→ key 本身。

### 核心文件

| 文件 | 职责 |
| --- | --- |
| `ui/i18n.py` | `tr()` / `translate()` / `set_language()` / `available_languages()` |
| `ui/locales/zh_CN.json` | 源语言词表（key 的来源） |
| `ui/locales/en.json` | 英文词表 |

### 新增可译字符串

1. 往 `locales/zh_CN.json` 加 `"my.key": "中文文案"`。
2. 往 `locales/en.json` 加同一把 key（漏译会被测试守卫红测）。
3. 代码里 `from ..i18n import tr; tr("my.key")`。

**无需改 `i18n.py`**——词表运行时首次访问加载并缓存。

### 启动接入

`ui/app.py` 在建窗口前调 `set_language(load_config(None).language)`，
和 `set_theme()` 同位——导航标签等首次渲染就走正确词表。

### 设置页语言选择

外观卡片有语言下拉框，保存时写入 `cfg.language`。**切语言需重启生效**
（已渲染的 Qt 控件不会自动重译），与 `database_path` / `theme` 同属
「重启生效」档，设置页有提示。

### 测试守卫

`tests/test_i18n.py`（14 例）钉死：

* 词表是合法 JSON 且每个语言文件结构正确。
* 非源语言必须覆盖源语言全部 key（漏译红测）。
* `tr` 能取到译文、找不到时回退到源语言再回退到 key 本身。
* `set_language` 切换后后续 `tr` 走新语言，未知语言回退源语言。
* 语言枚举 / 标签 API 稳定（设置页下拉依赖它）。

## 16.6 B 站直播录制（M6.15）

### 三层适配

直播走和点播同一套 pipeline，区别只在三层：

| 层 | 改动 | 文件 |
| --- | --- | --- |
| URL 识别 | `BilibiliURLType.LIVE`，匹配 `live.bilibili.com/{room_id}` | `platforms/bilibili/url.py` |
| 类型映射 | `LIVE → MediaType.LIVE`；`_classify_media_type` 识别 `BiliBiliLive` extractor | `platforms/bilibili/adapter.py`、`api.py` |
| 引擎参数 | 直播流不 `merge_output_format`、`live_from_start`、`fragment_retries=10` | `engines/yt_dlp.py::_build_opts` |

### 直播与点播在引擎层的区别

```python
is_live = item.media_type == MediaType.LIVE
if is_live:
    # HLS 无片尾，中途 remux 会失败
    opts["live_from_start"] = True          # 从开播点时移录制
    opts["fragment_retries"] = 10            # 断流重连
else:
    opts["merge_output_format"] = options.container
```

### URL pattern 顺序

LIVE pattern（`live.bilibili.com/{room_id}`）必须排在 SPACE（`bilibili.com/{数字}`）
**之前**——两者都是纯数字，顺序错了 SPACE 会吞掉直播房间号。这是
`test_classify_bilibili_live_not_confused_with_space` 守卫的边界。

### 测试边界

`test_bilibili_adapter.py` +8 例覆盖 URL 识别（plain/h5/query）、不误吞 SPACE、
`match_url`、类型映射、extractor 识别、`supported_media_types`。真实直播循环
（断流重连、时移边界）需真实直播流，留给集成测试。

## 16.7 aria2 多线程引擎（M6.15）

### 实现要点

| 文件 | 职责 |
| --- | --- |
| `engines/aria2.py` | `Aria2Engine` + `Aria2RpcClient` Protocol + `_HttpxAria2Client` |
| `core/config.py` | `engine` / `aria2_rpc_url` / `aria2_secret` 配置字段 |
| `core/engine_loader.py` | `build_default_engine(cfg)` 按配置选引擎 |

### RPC 客户端注入

`Aria2RpcClient` 是 Protocol，`Aria2Engine(rpc_client=...)` 接受注入：

* 生产：`_HttpxAria2Client`（基于 httpx，直接发 JSON-RPC）。
* 测试：内存 Mock（`_MockRpcClient`），不依赖 aria2 二进制。

这样 `download()` 的所有逻辑（addUri 参数构造、进度轮询、取消）都能用
Mock 单测，参考 `tests/test_aria2_engine.py`（18 例）。

### `supports()` 的直链守卫

```python
def supports(self, item: MediaItem) -> bool:
    return bool(item.extra.get("direct_url") or item.source_url)
```

aria2 不解析网页——没有直链的 item 回退 yt-dlp。直链由 yt-dlp 解析阶段
注入 `item.extra["direct_url"]`。

### 引擎选择回退

`build_default_engine(cfg)` 未知引擎名回退 yt-dlp，避免配置写错让应用起不来：

```python
if engine_name == "aria2":
    return Aria2Engine(rpc_url=..., secret=...)
# 未知引擎名回退 yt-dlp
return YtDlpEngine()
```

---

## 17. 如何安全地修改项目（改动检查单）

无论改什么，按这个顺序自查：

### 改动前
1. 跑一遍 `python -m pytest` 确认基线全绿。
2. 找到受影响的所有端（core 改动 = 四端都受影响；只改 `pages/` = 只影响 GUI）。

### 改动中
3. **加新平台**：看 §6.4。
4. **改 B 站策略**：先读 §14。确保 cookie 合并不破坏、WBI 重试在、目录预创建在。
5. **加配置项**：`config.py` DEFAULTS + AppConfig + load_config + GUI 设置页 + 每端 `_build_options()`，五处都要动。**第五处最容易忘**，而且忘了不报错——引擎和 `file_layout` 只读 `DownloadOptions`，从不读 `AppConfig`，所以漏转发的字段在那一端就是个死开关（详见 §16 第 18 条）。现在 GUI 与 REST 各有一个 `test_build_options_covers_every_shared_config_field` 结构性测试守着这一步，漏了会变红。
6. **改数据模型**：`models.py` 加字段时用 `field(default_factory=...)` 保持向后兼容；检查 `database.py` 的 `record_download` 是否要同步新字段。
7. **新 GUI 页面**：`pages/<name>.py` 暴露 `build_<name>_widgets()` → `pages/__init__.py` 导出 → `main_window.py` 注册。
8. **改解析页结果表（树形结构）**：三条铁律——① 任何增删行之后必须在 `blockSignals(False)` 之后调 `_refresh_row_mapping()`；② 不要用行号做字典 key，也不要用 `base + index` 反算行号；③ 判「这是不是 section 行」用 `row == _top_to_row.get(top_idx)`，不要看 resolve 出的 item 类型。改完跑 `tests/test_row_mapping_cache.py`。
9. **加一套主题**：与第 5 条相反，**只动 `theme.py` 的 `THEMES`**，下拉框 / `--theme` 的 `choices` / 导航栏循环 / GUI 测试参数化全部自动跟上（见 §13.4.5）。
10. **改主题落地逻辑**：`set_theme()` 的六步顺序是硬约束（两个 monkey patch 必须早于刷新），`app.py` 里两次 `set_theme()` 都不能删——理由见 §13.4.3 / §13.4.4。新增带色控件时，**颜色不要烘进控件自身的 stylesheet**；非要烘就得 `subscribe_theme()` 注册重刷，否则切主题后残留旧色。
11. **写任何「持有外部资源的 async 清理」**：动 `await` 与「置空 / 释放」两句的先后顺序前，先问一句「这里被取消会怎样」。判据是**先摘引用，再 await**——反过来写，一次取消就跳过置空，对象带着一具尸体活下去（坑位 28）。同理，不要指望 `asyncio.shield` 能保住清理：它只挡 awaiter 传来的取消，runner 级别的全量清扫照样打断（坑位 27）。这类 bug 的共同点是**症状不在崩溃现场**——要么只剩一句 `ResourceWarning`，要么完全无声、下次复用才炸。

### 改动后
12. 写/更新测试（新逻辑必须配测试；GUI 用 offscreen 模式）。
13. `python -m pytest` 全绿，且**用例总数只增不减**（减少 = 有测试被意外跳过或删掉）。
14. 更新 `docs/CHANGELOG.md`（按 M 里程碑分节）。
15. 若修的是「踩坑类」bug，把根因与判据写进 `docs/DEVELOPMENT.md` 对应小节 —— 光修代码不写文档，下一个人（或下一轮 AI）会原地重犯。
16. **修完 bug 先破坏一次修复，确认测试真的变红**。这一步不是形式：坑位 19 那个结构性测试的第一版、以及取消泄漏那三种断言设计（查 `db._conn`、查 `was_closed`、`gc.collect()` 后查 `ResourceWarning`），在修复前后**都一样通过**，等于什么都没测。有多重防御时要**同时**破坏全部，只拆一层会被另一层兜住。
17. 用 `python -m doubi.ui` 手动冒烟 GUI（如果有改动 UI）。

### 提交前清理
- 删除临时调试脚本（`_diag*.py`、`_probe*.py`、`_repro*.py`、`_win_check.log` 等）。PowerShell 删不掉时用 Python：`python -c "import os; os.remove('...')"`。
- 不要提交 `doubi.db`、`Downloaded/`、`download_manifest.jsonl`、`_test_live/`（运行产物）。

### 推送：本仓库有两个远端，别推错
- `Github` → `git@github.com:buxiaju/DouBi.git`（**不叫 `origin`**）
- `origin` → `https://gitee.com/buxiaju/dou-bi.git`（Gitee）
- 默认分支是 **`master`**，且本地 `master` 的 upstream 是 `origin/master`，
  所以裸跑 `git push` 会推到 **Gitee**。推 GitHub 要写全：
  `git push Github master:master`。
- 发版打 tag 的顺序、SSH 配置、标签打错的补救，见 `docs/BUILD.md` §8.1–§8.4。

---

## 18. 已知限制与路线图

### 已知限制

1. **B 站匿名风控**：UP 主页 / 合集枚举在无登录时受限（412 / -799），登录后稳定。已用官方 API + WBI 签名缓解，但 IP 级限流仍需等待窗口（几分钟）。
2. **抖音 user/info/self 404**：该端点被风控（无签名调用必 404），`validate_cookies` 已降级为「session cookie 存在性」判定（sessionid / sessionid_ss / sid_guard 任一存在即已登录）——只能判"有登录痕迹"，无法确认 cookie 是否仍有效（下载本身走 yt-dlp 不受影响）。同类问题：抖音合集标题是 best-effort（`/mix/detail/` 被风控 403，合集名从列举第一页的 `mix_info.mix_name` 探测，失败时退化为 `抖音合集 {mix_id}`）。
3. **GUI 尚未实现**：已完成列表排序、章节下载。
   （M6.2 已补上：全部/单任务暂停恢复、弹幕、字幕、NFO；**M6.10 已补上跨进程恢复**，见 §13.2.1）
4. **REST/MCP 的容器支持**：容器统计已修正（读 pipeline 写的 `child_count` / `downloaded_count` / `failed_count`），但仍是「整个容器一个 job」，无法单独重试其中某一子项。
5. ~~**没有 i18n**~~ **M6.14 已做**（见 §16.5）：自研 JSON 词典 + `tr()`，
   内置 `zh_CN` / `en`，设置页可切换。新增字符串仍需手工补两份词典，
   漏补时回退到 key 本身（打包期漏收 locales 会让全 UI 显示 key，
   见 CHANGELOG G7）。
6. **配置只读一次**：GUI 保存后需重启才生效的部分（代理等）没有提示重启。
7. **CI 自动化但本地打包仍需手动**：「手动 dispatch 跑 build.yml」可发现
   「现在的 master 分支能不能成功打包」，但日常 dev 迭代还是要本地跑
   ``scripts/build_installer.py``——CI 不是 dev loop 的替代品，只是不
   再依赖人记得跑。
8. **发布流程仍是手工序列**：推 commit → 打 tag → 填 Release 正文 → 传资产
   全靠人按顺序执行，没有守卫。0.3.0 因此踩了两个坑（tag 建在 release
   commit 之前导致源码包错版本；Release 正文粘贴截断丢了 SHA256 校验段）。
   补救靠 `docs/BUILD.md` §8.3 的固定顺序和 §7 的「发布后线上核对」清单，
   **不是代码层面的保证**。另外强推 `v*` tag 会触发 CI 重建并可能覆盖
   已验证的安装包资产（§8.4）。

### 对齐 Bili23 的路线图（已识别未做）

按 ROI 排序：
1. ~~**下载选项弹窗**~~ **M6.11 已做**（见 §13.8）：开关默认关，开关后下载前弹 4 字段（画质/容器/缩略图/JSON）；右键菜单与「直接 add()」路径不接弹窗。
2. ~~**YouTube 适配器**~~ **M6.12 已做**（见 §13.9）：最低成本扩张样板，不到 200 行 adapter + 31 例测试，URL 全形态覆盖。
3. **解析历史**（记录近期解析过的链接，一键重解析）。
4. **剪贴板监听**（复制链接自动弹"是否解析"）。
5. **头像/账号入口**（左下角显示登录态，一键登出）。
6. **附加内容下载**（弹幕 XML/ASS、字幕、封面、章节、NFO 刮削给 Jellyfin/Plex）。
7. **收藏页**（收藏夹/追番/稍后再看/历史记录，点击跳解析）。
8. **纯编号解析**（直接输入 av/BV/ep/ss/md 号）。
8. **重复下载 / 文件重名策略**、**画质音质编码优先级**、**CDN 切换**、**更新检查**。

### 建议的新功能（核心之外）

- 新平台：YouTube（`Platform.YOUTUBE` 已预留）、小红书、微博。
- 新引擎：aria2 多线程下载。
- 直播：抖音已支持，B 站直播录制未做。

---

*文档生成时间：2026-08-25 · 与 `docs/CHANGELOG.md` 的 M6.13 快照对应。维护者更新本文档时，保持"结构 + 关键 API + 踩坑记录"三要素即可，避免写与代码重复的长篇源码引用。*
