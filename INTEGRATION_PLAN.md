# Douyin Downloader × Bili23 Downloader 整合方案

> 目标：把两个项目合并为一个"多平台（抖音 + B 站 + 后续可扩展）视频下载器"，同时复用彼此的能力，避免从零造轮子。
>
> 文档版本：v1.0  
> 适用代码基线：douyin-downloader-main（v2.0.0，MIT）、Bili23-Downloader-main（v2.15.0，GPL-3.0）

---

## 1. 两个项目现状摸底

### 1.1 douyin-downloader-main

| 维度 | 现状 |
|---|---|
| 形态 | **CLI**（`python run.py -c config.yml`）+ **REST API 服务**（`--serve --serve-port 8000`），无 GUI |
| 平台 | 抖音（视频、图文、合集、音乐、收藏、直播） |
| 目录结构 | `cli/`、`core/`、`server/`、`auth/`、`storage/`、`control/`、`utils/`、`tools/`、`config/`、`tests/` |
| 关键能力 | 浏览器兜底、OpenAI 转写、评论采集、直播录制、热搜榜、关键词搜索、Bark/TG/Webhook 通知、SQLite 去重、增量下载、并发/重试/限速 |
| 异步模型 | aiohttp + asyncio + aiosqlite（真异步） |
| 配置 | YAML（`config.example.yml`） |
| 协议 | MIT |
| Python | ≥ 3.9 |

代码组织亮点：`core/downloader_factory.py` 工厂分发 + `core/user_modes/*_strategy.py` 策略模式 + `control/{queue_manager, rate_limiter, retry_handler}` 三个独立的横切组件。

### 1.2 Bili23-Downloader-main

| 维度 | 现状 |
|---|---|
| 形态 | **PySide6 + Fluent-Widgets 桌面 GUI**（Win/Mac/Linux），含剪贴板监控、扫码登录、托盘 |
| 平台 | B 站（视频、番剧、课程、收藏夹、UP 主空间、稍后再看、历史、合集、音乐、每周必看、互动视频） |
| 目录结构 | `src/gui/`（界面、组件、对话框）、`src/util/`（network、parse、download、ffmpeg、thread、mcp、format、misc） |
| 关键能力 | 8K/HDR/杜比视界、Hi-Res、AVC/HEVC/AV1、ass 弹幕/字幕嵌入 mkv、封面嵌入、NFO 元数据（Jellyfin/Emby/Kodi）、命名规则引擎、断点续传、限速、CDN 切换、**MCP 服务器**（HTTP + stdio 桥） |
| 异步模型 | httpx + QThread 工作线程（同步网络 + Qt 事件循环） |
| 配置 | `util/common/config.py`（类 QSettings 风格） |
| 协议 | **GPL-3.0** |
| Python | ≥ 3.10 |

代码组织亮点：`util/parse/parser/{video,bangumi,space,favlist,...}.py` 每种内容一个 parser + `util/parse/additional/{cover,danmaku,subtitles,metadata,chapter,player,worker}.py` 抽离出"附加产物"加工 + `util/parse/search_url.py` 把筛选参数"塞进 URL 本身"。

### 1.3 互补性 / 冲突点

| 维度 | 互补性 | 冲突点 |
|---|---|---|
| 平台 | 抖音 vs B 站，互不重叠 | — |
| 形态 | 一个无 GUI + 一个有 GUI → **强互补** | — |
| 异步栈 | aiohttp（异步）vs httpx（线程池同步） | 不同，必须明确选型或封装 |
| 配置 | YAML vs QSettings | 风格不同 |
| License | MIT vs **GPL-3.0** | **关键约束**：合并项目对外分发须保持 GPL-3.0（或抽离出"MIT 内核 + GPL 壳"的边界） |
| 状态管理 | SQLite 去重 vs 任务 DB（`task/db.py`） | 都用 SQLite，但表结构完全不同 |
| 命名 | YYYYMMDD_标题_aweme_id | 规则引擎 + 模板（强大很多） |
| 编码 | 直存 mp4 | ffprobe/ffmpeg 合并为 mp4/mkv，可嵌入 ass/封面 |
| 协议/插件 | 写死 Douyin | parser 列表显式注册，扩展友好 |

> **关键判断**：两个项目**功能高度互补、代码几乎没有直接重叠**。整合的杠杆点不是"共用下载器代码"，而是**统一一个"平台无关的核心层 + 平台适配器"，让两边的优势（GUI / REST / 浏览器兜底 / 转写 / 命名规则 / MCP / 弹幕字幕 / 嵌入）在同一个 UI 里都能被用到**。

---

## 2. 整合目标与原则

### 2.1 产品目标

> **DouBi** — 一个 GUI + CLI + REST 三形态统一的多平台视频下载器，至少原生支持抖音和 B 站。

| 形态 | 入口 | 谁来提供 |
|---|---|---|
| 桌面 GUI | `doubi-gui` | 沿用 Bili23 的 PySide6 Fluent 壳 |
| 命令行 | `doubi-cli` | 沿用 douyin-downloader 的 `run.py` |
| REST 服务 | `doubi serve` | 沿用 douyin-downloader 的 FastAPI |
| MCP 工具 | `doubi-mcp` | 沿用 Bili23 的 MCP stdio 桥 |

### 2.2 设计原则

1. **平台无关的内核 + 平台适配器**：下载流程的核心抽象（解析 → 派发 → 下载 → 合并 → 附加产物）必须不绑定任何平台 API。
2. **零破坏迁移**：两个原项目作为"平台插件"先跑通，主仓至少各跑一条烟囱测试，迁移期间用户可用任一原版。
3. **许可证合规**：对外默认走 GPL-3.0（继承 Bili23），但保证 MIT 协议模块可独立分发。
4. **渐进式合并**：从最容易复用的部分（命名规则、附加产物层、MCP 工具）开始做，最后再搬 GUI 整合。
5. **异步模型二选一时挑"可装回 Qt"的方案**：Qt 主线程必须活，所有 IO 走 worker。
6. **配置向后兼容**：原 `config.yml`（douyin）和原 `QSettings`（bili23）都能被识别导入。

---

## 3. 目标架构

### 3.1 顶层目录

```
DouBi/                                  # 合并后的新根
├── pyproject.toml                      # 统一打包元信息
├── README.md
├── config.example.yml                  # 兼容 douyin 老配置
├── src/
│   ├── doubi/                          # 整合后唯一代码包
│   │   ├── __init__.py
│   │   │
│   │   ├── core/                       # 平台无关内核
│   │   │   ├── models.py               # 统一数据模型（MediaItem, DownloadJob, Platform）
│   │   │   ├── pipeline.py             # 解析 → 派发 → 下载 → 合并 → 附加
│   │   │   ├── registry.py             # PlatformRegistry / DownloaderRegistry
│   │   │   ├── naming.py               # 命名规则引擎（从 Bili23 抽出）
│   │   │   ├── postprocess/            # 附加产物层（从 Bili23 抽出，可裁剪）
│   │   │   │   ├── base.py
│   │   │   │   ├── cover.py            # 封面下载/嵌入
│   │   │   │   ├── danmaku.py          # 弹幕（xml/ass/json）
│   │   │   │   ├── subtitles.py        # 字幕（srt/ass/json）
│   │   │   │   ├── metadata.py         # NFO + 标签
│   │   │   │   ├── chapter.py          # 章节
│   │   │   │   └── worker.py
│   │   │   ├── network/                # 统一网络层（async first）
│   │   │   │   ├── client.py           # 异步 HTTP 客户端（基于 aiohttp + httpx fallback）
│   │   │   │   ├── proxy.py
│   │   │   │   ├── rate_limit.py
│   │   │   │   └── retry.py
│   │   │   ├── storage/                # 统一存储
│   │   │   │   ├── database.py         # SQLite 抽象 + 表迁移
│   │   │   │   ├── file_layout.py      # 输出目录规则
│   │   │   │   └── manifest.py         # download_manifest.jsonl
│   │   │   ├── job/                    # 任务模型与队列
│   │   │   │   ├── job.py
│   │   │   │   ├── queue.py
│   │   │   │   └── manager.py
│   │   │   ├── ffmpeg/                 # ffmpeg 封装
│   │   │   ├── auth/                   # 通用登录态管理
│   │   │   ├── notify/                 # Bark / TG / Webhook
│   │   │   └── browser_fallback.py     # 浏览器兜底（从 douyin 抽）
│   │   │
│   │   ├── platforms/                  # 平台适配器（插件）
│   │   │   ├── base.py                 # PlatformAdapter ABC
│   │   │   ├── douyin/                 # ← 整包迁自 douyin-downloader-main 的 core/auth/utils
│   │   │   │   ├── __init__.py
│   │   │   │   ├── adapter.py          # 实现 PlatformAdapter
│   │   │   │   ├── api.py
│   │   │   │   ├── parsers/            # url_parser → 分类型
│   │   │   │   ├── downloaders/        # video / mix / music / live / user
│   │   │   │   ├── strategies/         # post / like / mix / music / collect
│   │   │   │   ├── auth.py             # cookie_fetcher / ms_token
│   │   │   │   ├── sign.py             # xbogus / abogus / gmssl
│   │   │   │   └── live.py
│   │   │   └── bilibili/               # ← 整包迁自 Bili23 的 util/parse/util/network/util/download
│   │   │       ├── __init__.py
│   │   │       ├── adapter.py
│   │   │       ├── parsers/            # video / bangumi / space / favlist / ...
│   │   │       ├── parsers/parser/     # 原 Bili23 parser 全部迁入
│   │   │       ├── episode/            # 原 episode/ 迁入
│   │   │       ├── additional/         # cover / danmaku / subtitles / chapter / ...
│   │   │       ├── network/            # cdn / download_url / request
│   │   │       ├── downloader/         # downloader / merger / manager
│   │   │       ├── auth/               # 扫码 / 短信 / cookie
│   │   │       └── wbi.py              # wbi 签名
│   │   │
│   │   ├── ui/                         # PySide6 GUI（Bili23 壳子升级）
│   │   │   ├── app.py
│   │   │   ├── main_window.py
│   │   │   ├── pages/                  # 沿用 Bili23 的 interface/ 改名为 pages
│   │   │   │   ├── parse.py            # 粘贴链接 → 选下载项（B 站原 parse 页 + 抖音解析视图）
│   │   │   │   ├── download.py         # 下载列表
│   │   │   │   ├── setting.py
│   │   │   │   └── accounts.py         # 新增：双平台登录态管理
│   │   │   ├── components/             # 沿用 Bili23 的 component/
│   │   │   ├── dialogs/
│   │   │   ├── theme/
│   │   │   └── i18n/                   # 增加 平台标识
│   │   │
│   │   ├── cli/                        # 命令行（douyin-downloader 的 cli 升级为多平台）
│   │   │   ├── main.py
│   │   │   ├── progress.py
│   │   │   └── login.py
│   │   │
│   │   ├── server/                     # REST API（douyin-downloader 的 server 升级）
│   │   │   ├── app.py
│   │   │   ├── routes/
│   │   │   └── jobs.py
│   │   │
│   │   └── mcp/                        # 沿用 Bili23 的 MCP
│   │       ├── server.py
│   │       ├── tools/
│   │       └── stdio_bridge.py
│   │
│   └── res/                           # 资源（图标、qss、i18n）
│
├── tests/
├── scripts/                            # 打包脚本
├── docs/
└── legacy/                             # 整合过渡期，原项目作为子模块保留
    ├── douyin-downloader/  → ../douyin-downloader-main  (git submodule 或软链)
    └── bili23-downloader/  → ../Bili23-Downloader-main  (git submodule 或软链)
```

### 3.2 关键抽象

```python
# doubi/core/models.py
@dataclass
class MediaItem:
    platform: Platform          # "douyin" | "bilibili" | ...
    item_id: str                # aweme_id / bvid / epid / ssid
    title: str
    author: Author
    cover_url: str
    duration: int
    publish_time: datetime
    media_type: str             # "video" | "image_album" | "audio" | "bangumi" | ...
    stream_infos: list[Stream]  # 候选流，由平台 adapter 填
    extra: dict                 # 平台特有字段
    children: list["MediaItem"] = field(default_factory=list)  # 合集 / 多 P / 多图

@dataclass
class DownloadJob:
    job_id: str
    items: list[MediaItem]
    options: DownloadOptions
    progress_cb: Callable | None

class PlatformAdapter(Protocol):
    name: str
    display_name: str
    supported_url_patterns: list[re.Pattern]

    async def parse(self, url_or_query: str) -> list[MediaItem]: ...
    async def prepare_streams(self, item: MediaItem, options: DownloadOptions) -> list[Stream]: ...
    async def download_stream(self, stream: Stream, dest: Path, on_progress) -> bool: ...
    def postprocess_pipeline(self) -> list[PostprocessStep]: ...  # 由内核循环调用
```

平台 adapter 的好处：将来加 YouTube / TikTok 国际版 / 小红书 / 微博只需要写一个新 `platforms/<name>/` 目录 + 在 `registry` 注册一行。

### 3.3 异步模型决策

- **内核与平台 adapter 一律 async（asyncio + aiohttp）**。
- **GUI 集成**：Qt 主线程只跑 UI，调用内核通过 `QThread`/`QThreadPool` + `asyncio.run_coroutine_threadsafe` 或 `qasync` 桥（推荐后者：直接 `asyncio.run` 跑在 GUI 线程外的事件循环，Qt 信号桥接）。
- **CLI**：直接 `asyncio.run(main())`，与原 douyin-downloader 完全一致。
- **REST 服务**：FastAPI 本来就跑 asyncio，0 成本。
- **MCP**：Bili23 现有 MCP 在自己线程上跑 asyncio 即可，无需改动。

> 结论：把 douyin 的 aiohttp 异步栈作为"主干"，把 Bili23 的 httpx 调用包成 `to_thread` 或在 adapter 里另起一个 `AsyncClient`（httpx 也支持 async）。两个网络栈可以在 adapter 内共存，不污染内核。

---

## 4. 复用与迁移清单

### 4.1 从 douyin-downloader 复用

| 模块 | 处理 |
|---|---|
| `core/api_client.py` | 整包迁入 `platforms/douyin/api.py`，**不抽到内核**（Douyin 特化签名） |
| `core/user_modes/*_strategy.py` | 迁入 `platforms/douyin/strategies/` |
| `core/{video,mix,music,live,...}_downloader.py` | 迁入 `platforms/douyin/downloaders/` |
| `auth/cookie_manager.py`、`ms_token_manager.py` | 迁入 `platforms/douyin/auth/`，**抽一层 `core/auth/base.py`** 给 Bili23 用 |
| `control/queue_manager.py` | 抽象到 `core/job/queue.py`（多平台通用） |
| `control/rate_limiter.py`、`retry_handler.py` | 直接迁 `core/network/` |
| `utils/xbogus.py`、`abogus.py`、`gmssl` | 迁 `platforms/douyin/sign/` |
| `utils/notifier.py` | 迁 `core/notify/`（B 站未来也能用） |
| `storage/database.py` | 表结构迁 `core/storage/`，**新增 platform 列** + 迁移脚本 |
| `storage/file_manager.py` | 与 Bili23 的 `util/common/io/` 合并到 `core/storage/file_layout.py` |
| `tools/cookie_fetcher.py` | 迁 `platforms/douyin/auth/cookie_fetcher.py`（GUI 也可复用） |
| `core/comments_collector.py`、`transcript_manager.py`、`live_*` | 迁 `platforms/douyin/`，transcript 抽到 `core/transcript/` 作为通用可选后处理 |
| `core/browser_fallback.py` | 迁 `core/browser_fallback.py`（bilibili 在登录态受限时可复用） |
| `cli/` | 整体迁 `src/doubi/cli/`，扩展支持 `--platform douyin|bilibili` |
| `server/` | 整体迁 `src/doubi/server/`，扩展 `/api/v1/platforms/{name}/...` |

### 4.2 从 Bili23 复用

| 模块 | 处理 |
|---|---|
| `src/main.py` | 整包迁 `src/doubi/ui/app.py` + 增量支持"双平台"账号切换 |
| `src/gui/**` | 整包迁 `src/doubi/ui/`，**核心扩展**：解析页加"平台"维度、下载页加"平台列"、设置页加"平台账号" |
| `src/util/parse/parser/*.py` | 迁 `platforms/bilibili/parsers/parser/` |
| `src/util/parse/episode/*.py` | 迁 `platforms/bilibili/episode/` |
| `src/util/parse/additional/**/*.py` | **抽出到 `core/postprocess/`**（封面/弹幕/字幕/NFO 是平台无关的） |
| `src/util/parse/search_url.py` | 迁 `core/url_query.py`（通用"参数透传"机制） |
| `src/util/network/*` | 抽到 `core/network/`，异步适配保留双栈 |
| `src/util/ffmpeg/*` | 抽到 `core/ffmpeg/` |
| `src/util/format/file_name.py` | 与 Bili23 `util/common/data/naming_convention.py` 合并为 `core/naming.py`（规则引擎化） |
| `src/util/thread/*` | 抽到 `core/threading/`（QThread 桥 / 线程池） |
| `src/util/mcp/**` | 整体迁 `src/doubi/mcp/`，tool 实现改用 `doubi.core` 接口 |
| `src/util/misc/history.py`、`update.py` | 迁 `core/misc/` |
| `src/util/parse/preview/**` | 迁 `platforms/bilibili/parsers/preview/`（预览是平台特化） |

### 4.3 双栈共存的中间策略

> 在 GUI 还没完全合并前，先让 Bili23 的 `main.py` **调用 douyin-downloader 的 CLI/REST** 作为"抖音工作台"。这样：
>
> - Bili23 的 GUI 加一个 tab 页："抖音" → 内部其实是 `subprocess` 调 `doubi download ...` 或 HTTP POST `/api/v1/download`。
> - 抖音侧后续迭代不阻塞 Bili23 GUI。

这是**第一阶段**最稳的做法，零重写、零破坏。

---

## 5. 实施阶段（建议 6 个里程碑）

### M0 · 立项与双仓对齐（1~2 天）

- [ ] 决定新仓命名（建议 `DouBi`）、许可证（建议 **GPL-3.0**，理由：与 Bili23 兼容、与 douyin MIT 兼容）
- [ ] 把两个原仓作为 git submodule / subtree 放到 `legacy/`
- [ ] 写 `README.md` 整合计划（本文档精简版）
- [ ] 定下"**platform 字段**"为通用抽象的标志（database、文件路径、URL 查询、UI 标签都按此统一）

### M1 · 内核骨架 + 平台抽象（1~2 周）

- [ ] 落地 `doubi/core/`：`models.py` / `registry.py` / `pipeline.py`
- [ ] 写 `PlatformAdapter` ABC + 一个最小 `platforms/dummy/`（用来跑通"解析 → 派发 → 下载 → 完成"）
- [ ] 用 `pytest-asyncio` 跑通"假平台"端到端
- [ ] 决策：是否引入 `qasync`（**推荐**）；先在 `tests/` 验证 asyncio + Qt 桥不打架
- [ ] CI 加 ruff + pytest + 许可证检查（GPL/MIT 兼容）

### M2 · 抖音适配器整体迁入（1~2 周）

- [ ] `platforms/douyin/` 完成整体搬迁（**不重构逻辑**，只换包名和 import 路径）
- [ ] 实现 `platforms/douyin/adapter.py` 暴露 `parse / prepare_streams / download_stream / postprocess_pipeline`
- [ ] 把 douyin 原 `config.example.yml` 导入路径迁过来
- [ ] CLI 跑通原 douyin 全功能（`doubi download -c douyin.yml -u https://...`）
- [ ] REST 服务跑通（`doubi serve --port 8000`）
- [ ] 数据库加 `platform` 列，写迁移脚本，**保留老 dy_downloader.db 可读**

### M3 · B 站适配器整体迁入（1~2 周）

- [ ] `platforms/bilibili/` 整体迁入（同样只搬不改）
- [ ] adapter.py 把 `parser/*.py` 包到统一 `parse()` 后面
- [ ] 命名规则 / 附加产物层抽到 `core/naming.py` 和 `core/postprocess/`
- [ ] CLI 跑通 B 站（`doubi download -c bili.yml -u https://www.bilibili.com/video/BV...`）
- [ ] MCP 跑通，工具列表至少含 `parse / download / task` 三个

### M4 · 统一数据库与输出目录（1 周）

- [ ] 合并 `aweme`（douyin）和 `task`（bili23）表 → 新 `media_item`（`platform` + `item_id` 联合主键）
- [ ] 写迁移脚本：douyin.db、bili23.db → doubi.db
- [ ] 输出目录统一为：
  ```
  Downloaded/
  ├── {platform}/
  │   └── {author}/
  │       └── {media_type}/
  │           └── {date}_{title}_{item_id}/
  │               ├── ...mp4 / ...m4a / ...flv
  │               ├── ...cover.jpg
  │               ├── ...danmaku.xml（可选，B 站）
  │               ├── ...subtitle.srt（可选）
  │               ├── ...nfo（可选）
  │               └── ...data.json
  └── download_manifest.jsonl
  ```
- [ ] `manifest.jsonl` 字段统一：`platform, item_id, author, date, title, media_type, streams, files, tags, ...`

### M5 · GUI 合并（2~3 周，最重的活）

- [ ] Bili23 GUI 主框架迁过来，双开"**B 站工作台** / **抖音工作台**"两个 Pivot 页
- [ ] 解析页：粘贴链接 → 内核 `parse()` 返回 → 通用 `MediaItem` 渲染
- [ ] 下载页：增加"平台"列
- [ ] 设置页：增加"平台账号"分组
- [ ] 剪贴板监控：注册多平台 URL pattern
- [ ] 托盘 + 单实例锁：原 Bili23 已有，保留
- [ ] 主题/i18n：增加 platform 标识字符串
- [ ] GUI 模式下后台调 `core.pipeline`（通过 `qasync`），不阻塞主线程

### M6 · REST + MCP + 打包（1 周）

- [ ] REST 接口扩展：
  - `GET /api/v1/platforms` 列出已注册平台
  - `POST /api/v1/platforms/{name}/parse` 平台解析
  - `POST /api/v1/download` 跨平台下载（`platform` 字段必填）
- [ ] MCP 工具合并 douyin 能力（评论、直播、转写、热搜）作为可选 tool
- [ ] 打包：
  - Windows：`PyInstaller` 或 `nuitka`（Bili23 已用 PyInstaller）
  - macOS / Linux：`nuitka` 优先 / 退回 PyInstaller
  - 集成 `imageio-ffmpeg` 静态二进制（douyin 已用）
  - 文档站：沿用 Bili23 文档站 + 增补 douyin 部分

### M7 · 后续扩展（不断迭代）

- [ ] YouTube adapter（douyin 项目里已有 `Douzy` 工作台，复用 yt-dlp）
- [ ] TikTok 国际版（与抖音共享底层）
- [ ] 小红书 / 微博 / 快手
- [ ] WebUI（用 REST + 静态前端，给 NAS 用户用）

---

## 6. 关键技术决策

### 6.1 异步策略

| 场景 | 方案 |
|---|---|
| 内核与平台 adapter | `asyncio` + `aiohttp`（沿用 douyin） |
| Bili23 现有 httpx 同步代码 | 用 `asyncio.to_thread(httpx_call)` 包一层；不立即全部改 async |
| GUI | `qasync` 桥接 asyncio loop 与 Qt event loop |
| CLI / REST | 直接 `asyncio.run` |
| MCP | 在自己线程起独立 loop（沿用 Bili23 现状） |

### 6.2 数据库

- 用 `aiosqlite`（沿用 douyin），GUI 模式下连接由内核线程持有，UI 通过 `Signal` 拿结果
- 统一表：
  ```sql
  CREATE TABLE media_item (
      platform TEXT NOT NULL,
      item_id TEXT NOT NULL,
      PRIMARY KEY (platform, item_id),
      title TEXT,
      author_id TEXT,
      author_name TEXT,
      publish_time INTEGER,
      media_type TEXT,
      payload JSON,           -- 平台原始数据
      last_download_time INTEGER,
      last_save_dir TEXT
  );
  CREATE TABLE task (
      task_id TEXT PRIMARY KEY,
      platform TEXT,
      status TEXT,
      total INTEGER,
      done INTEGER,
      failed INTEGER,
      created_at INTEGER,
      finished_at INTEGER
  );
  ```
- 提供 `legacy/...` 迁移脚本，把 `aweme` 表读出来转写

### 6.3 命名规则引擎

- 直接把 Bili23 的 `util/common/data/naming_convention.py` 抽到 `core/naming.py`
- 抖音侧 `utils/naming.py` 重写为注册到引擎的"抖音命名规则"
- 模板语法保持 Bili23 风格：`{title}/{author}/{date}` 等

### 6.4 浏览器兜底

- 把 douyin 的 `control/browser_fallback.py` 抽到 `core/browser_fallback.py`
- 改为通用 API：`async def fetch_via_browser(url: str, pattern: re.Pattern, max_scrolls: int) -> list[str]`
- B 站登录态校验需要时可以复用（扫码后 Cookie 注入流程）

### 6.5 通知 / 推送

- `core/notify/` 统一：Bark / Telegram / Webhook（douyin 已有）
- 抽 `NotificationEvent` 通用事件：`{platform, item_id, status, message, media_path}`
- GUI 内部也监听同一事件总线（Qt Signal 桥），可显示气泡

### 6.6 MCP 设计

- 沿用 Bili23 MCP：`util/mcp/tools/{parse,download,task}.py`
- 新增工具：
  - `parse_url(url)` — 自动识别平台
  - `add_to_queue(items, options)` — 跨平台入队
  - `search_douyin(keyword, max)` — 来自 douyin
  - `get_hot_board(platform, top)` — 来自 douyin，扩展到 B 站热门
  - `transcribe(item_id)` — 来自 douyin 的可选能力
- stdio 桥接沿用 Bili23 `stdio_bridge.py`

### 6.7 许可证与发布

- 主仓：`GPL-3.0`
- 在 `LICENSE` 主文件下加 `THIRD_PARTY_LICENSES.md`，明确：
  - douyin-downloader 原始模块：MIT
  - Bili23-Downloader 原始模块：GPL-3.0
  - 整合后新增的模块：GPL-3.0
- 商标与品牌：**整合产品**叫 `DouBi`（不沿用任一原项目商标），避免商标冲突
- 协议中保留两位原作者致谢（README 顶部 Credits 区）

### 6.8 测试策略

- 每个平台 adapter 单独测试：`tests/platforms/douyin/`, `tests/platforms/bilibili/`
- 内核端到端测试：`tests/core/test_pipeline_e2e.py`（用 dummy platform + 本地 HTTP fixture）
- GUI 测试：保留 Bili23 现有 `tests/`（若已有），新增"双平台 tab 切换"测试
- 回归对比：原 douyin / bili23 全功能跑回归，确保迁移后行为一致（用录制的网络响应 fixture）

---

## 7. 风险与缓解

| 风险 | 严重度 | 缓解 |
|---|---|---|
| **GPL-3.0 传染**：合并后原 MIT 区域也被要求 GPL | 高 | 写明"MIT 模块"边界（`platforms/douyin/` 可作为独立子包分发）；或在 LICENSE 中声明 MIT 部分以"系统库例外"独立 |
| 异步模型不统一：aiohttp vs httpx 同步 | 中 | 全部 adapter 用 `to_thread` 包装老同步代码，逐步 async 化 |
| `qasync` 与 QThread 共存复杂度 | 中 | M1 阶段先 spike，跑一个 Qt + asyncio 联动的最小例子 |
| Bili23 GUI 强耦合到 `util/` 内部模块，迁出难度大 | 高 | M5 阶段先做"同进程双形态"（GUI 内调 douyin 的 subprocess/REST），把 GUI 改双平台 tab 放到 M5 末尾，减小一次性改动量 |
| 两个项目对 `aweme_id` / `bvid` 等 ID 命名不一致 | 低 | 统一为 `MediaItem.item_id`（按平台区分） |
| 抖音 xbogus / a-bogus 签名算法经常变化 | 高 | 把签名模块独立成 `platforms/douyin/sign/`，**只动这一个目录**就能跟接口变更 |
| 打包体积：PySide6 + aiohttp + imageio-ffmpeg + protobuf 等 | 中 | 拆 `[gui]`、`[cli]`、`[server]`、`[mcp]`、`[all]` 可选依赖；GUI 单独发布 |
| 国际化：原 Bili23 自带 zh_CN/zh_TW/en，Bili23 资源文件迁移 | 低 | 直接迁 `res/i18n/`，增加 `platform.douyin.*` 字符串 |
| **两位原作者态度**：是否愿意合并 / 改协议 | **高** | 先 PR 提案 + Discord/QQ 群沟通；不合并也行，"双形态同进程"已经是双赢 |

---

## 8. 最小可用路径（M0 ~ M3 也可独立发布）

如果不想做最重的 GUI 整合（M5），**只完成 M0 ~ M3 也能立刻带来价值**：

```
doubi download -c config.yml -u "https://www.bilibili.com/video/BVxxxx"   # B 站
doubi download -c config.yml -u "https://www.douyin.com/video/7xxx"       # 抖音
doubi serve --port 8000                                                    # REST 双平台
doubi-mcp --stdio                                                          # MCP 双平台
```

发布物只是一个 CLI + 服务 + MCP，**Bili23 GUI 仍独立维护**（短期），待 GUI 整合稳定后再合并。

---

## 9. 总结

- 整合的**核心**是建一层 `core/` 平台无关内核 + `platforms/<name>/` 适配器。
- 两个项目**几乎不重复**，合并主要是"统一抽象"而不是"删代码"。
- **最重**的活是 M5（GUI 合并），可以放到最后做，前期以"GUI 调用 CLI/REST"的方式平滑过渡。
- 许可证需明确（建议 GPL-3.0 主仓 + MIT 子模块边界）。
- 异步模型用 `asyncio` 主干 + `to_thread` 兜底，`qasync` 桥 GUI。
- 风险最高的是 Bili23 GUI 的解耦，可以分阶段做（先 subprocess 调内核，再换 in-process 调用）。

整合后获得的能力 = Bili23 GUI 体验 + 抖音全功能下载 + 多平台 REST/MCP + 命名规则引擎 + 附加产物（弹幕/字幕/NFO）+ 浏览器兜底 + 转写 + 直播 + 评论 + 通知推送。

---

## 附录 A · 模块映射表（详细）

| douyin-downloader-main | → 整合后位置 |
|---|---|
| `cli/main.py` | `src/doubi/cli/main.py` |
| `cli/progress_display.py` | `src/doubi/cli/progress.py` |
| `cli/login_flow.py` | `src/doubi/cli/login.py` |
| `core/api_client.py` | `src/doubi/platforms/douyin/api.py` |
| `core/url_parser.py` | `src/doubi/platforms/douyin/parsers/url.py` |
| `core/user_modes/*` | `src/doubi/platforms/douyin/strategies/` |
| `core/{video,mix,music,live,live_replay,user}_downloader.py` | `src/doubi/platforms/douyin/downloaders/` |
| `core/downloader_base.py` | `src/doubi/core/downloader_base.py`（双平台共用） |
| `core/downloader_factory.py` | `src/doubi/core/registry.py`（升级为多平台工厂） |
| `core/comments_collector.py` | `src/doubi/platforms/douyin/comments.py` |
| `core/transcript_manager.py` | `src/doubi/core/transcript.py`（通用）+ `platforms/douyin/hook.py` |
| `core/metadata.py` | `src/doubi/platforms/douyin/metadata.py` |
| `core/audio_extraction.py`、`ffmpeg.py`、`silent_audio.py` | `src/doubi/core/ffmpeg/`（拆细） |
| `core/discovery.py` | `src/doubi/platforms/douyin/discovery.py` |
| `core/retry_executor.py` | `src/doubi/core/network/retry.py` |
| `server/app.py`、`jobs.py` | `src/doubi/server/{app,jobs}.py` |
| `auth/cookie_manager.py`、`ms_token_manager.py` | `src/doubi/platforms/douyin/auth/` |
| `storage/database.py` | `src/doubi/core/storage/database.py`（加 platform 列） |
| `storage/file_manager.py`、`metadata_handler.py` | `src/doubi/core/storage/file_layout.py`、`platforms/douyin/metadata_handler.py` |
| `control/queue_manager.py` | `src/doubi/core/job/queue.py` |
| `control/rate_limiter.py` | `src/doubi/core/network/rate_limit.py` |
| `control/retry_handler.py` | `src/doubi/core/network/retry.py` |
| `utils/xbogus.py`、`abogus.py` | `src/doubi/platforms/douyin/sign/` |
| `utils/cookie_utils.py`、`helpers.py`、`validators.py`、`naming.py` | `src/doubi/platforms/douyin/utils/` + 抽 `core/naming.py` |
| `utils/notifier.py` | `src/doubi/core/notify/` |
| `utils/logger.py` | `src/doubi/core/logger.py` |
| `utils/paid_content.py` | `src/doubi/platforms/douyin/paid_content.py` |
| `tools/cookie_fetcher.py` | `src/doubi/platforms/douyin/auth/cookie_fetcher.py` |
| `config/` | `src/doubi/core/config/`（合并 Yaml + QSettings） |

| Bili23-Downloader-main | → 整合后位置 |
|---|---|
| `src/main.py` | `src/doubi/ui/app.py` |
| `src/gui/interface/main_window.py` | `src/doubi/ui/main_window.py` |
| `src/gui/interface/parse.py` | `src/doubi/ui/pages/parse.py` |
| `src/gui/interface/download.py` | `src/doubi/ui/pages/download.py` |
| `src/gui/interface/setting.py` | `src/doubi/ui/pages/setting.py`（新增"平台账号"分组） |
| `src/gui/component/**` | `src/doubi/ui/components/` |
| `src/gui/dialog/**` | `src/doubi/ui/dialogs/` |
| `src/util/network/{request,cdn,download_url,proxy}.py` | `src/doubi/core/network/` + `src/doubi/platforms/bilibili/network/` |
| `src/util/parse/parser/*.py` | `src/doubi/platforms/bilibili/parsers/parser/` |
| `src/util/parse/episode/*.py` | `src/doubi/platforms/bilibili/episode/` |
| `src/util/parse/additional/{cover,danmaku,subtitles,metadata,chapter,player,worker}.py` | `src/doubi/core/postprocess/`（**抽离**） |
| `src/util/parse/additional/file/*.py` | `src/doubi/core/postprocess/file/` |
| `src/util/parse/preview/*.py` | `src/doubi/platforms/bilibili/parsers/preview/` |
| `src/util/parse/search_url.py` | `src/doubi/core/url_query.py` |
| `src/util/parse/worker.py` | `src/doubi/core/postprocess/worker.py` |
| `src/util/download/{downloader,manager,merger,parse_worker}.py` | `src/doubi/platforms/bilibili/downloader/` |
| `src/util/download/task/{db,info,manager,options,query_worker,reparse_worker,hash_id}.py` | `src/doubi/core/job/{db,info,manager,options,query_worker,reparse_worker,hash_id}.py` + `platforms/bilibili/hook.py` |
| `src/util/download/cover/*.py` | `src/doubi/core/postprocess/cover.py` |
| `src/util/ffmpeg/{command,runner}.py` | `src/doubi/core/ffmpeg/` |
| `src/util/format/{file_name,time,units}.py` | `src/doubi/core/format/` |
| `src/util/common/{config,enum,icon,serializer,signal_bus,style_sheet,timestamp,translator,_json}.py` | `src/doubi/core/common/` |
| `src/util/common/data/*.py` | `src/doubi/core/data/` + `platforms/bilibili/data/` |
| `src/util/common/io/{directory,file}.py` | `src/doubi/core/storage/io/` |
| `src/util/thread/{async_,dispatcher,pool,worker_base}.py` | `src/doubi/core/threading/` |
| `src/util/mcp/**` | `src/doubi/mcp/` |
| `src/util/misc/{history,update,web,macos,dm_pb2}.py` | `src/doubi/core/misc/` + `platforms/bilibili/proto/` |
| `src/res/**` | `src/res/` |

## 附录 B · 命名建议

- 整合后产品名：`DouBi`（Douyin + Bilibili 的合成，谐音"豆币"友好）
- 包名：`doubi`
- CLI：`doubi`（保留子命令 `download` / `serve` / `mcp`）
- 桌面：`DouBi Desktop`（沿用 Bili23 的 Fluent 风格）
- REST 根：`/api/v1`
- MCP 服务名：`doubi-mcp`

## 附录 C · 第一周落地清单

如果只能挤出一周，最低可交付的整合 demo：

- [ ] Day 1：新仓 `DouBi` 初始化；`legacy/` 留两个原项目指针
- [ ] Day 2：实现 `core/models.py` + `core/registry.py` + `PlatformAdapter` ABC
- [ ] Day 3：迁 douyin 的 `cli/main.py` + `core/api_client.py` 到 `platforms/douyin/`，**保证 `python -m doubi.cli` 能跑通原 douyin 命令**
- [ ] Day 4：迁 B 站的 `util/parse/parser/video.py` + `util/network/request.py` 到 `platforms/bilibili/`，**保证能用 B 站链接完成"解析 → 拉流地址"**
- [ ] Day 5：合并数据库表 + 文件目录到 `core/storage/`
- [ ] Day 6：写 `tests/test_pipeline_smoke.py` 跑通 dummy + douyin + bili23 三个端到端
- [ ] Day 7：整理 `README.md` 整合说明 + 跑 CI

一周后即可对外发 v0.1.0 "DouBi"。
