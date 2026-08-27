# DouBi 快速上手

## 分发形态（无需 Python 环境，下载即跑）

如果你的目标是**直接用软件**（不是开发 / 改代码），从 Release 拿
下面其中一种就行，不用看「安装」节的 pip / Playwright install 命令。

| 形态 | 文件（0.3.0） | 体积 | 启动速度 | 推荐 |
|---|---|---|---|---|
| **NSIS 安装包**（普通用户首选） | `DouBi-Setup-0.3.0.exe` | 441 MB | 快 | 装到 `%LOCALAPPDATA%\DouBi`，开始菜单 / 桌面快捷方式，控制面板正常卸载，卸载不删 `~/.doubi` |
| **Onefile 便携版**（U 盘/网盘） | `doubi-gui.exe` | 615 MB | 慢 1–2 秒（自解压到 `%TEMP%/_MEIxxxxx`） | 免安装，拷到哪都能跑；跨机转移直接复制单文件 |
| Onedir 绿色目录（内网 / 运维） | `doubi-gui/` 整个目录 zip | ~1.5 GB | **最快** | 企业内网分发，解压即可，无需任何安装步骤 |

> 所有形态都**已内置 Playwright Chromium 浏览器**（通用 URL 嗅探需要），
> 首次使用不需要再 `python -m playwright install chromium`。

### 新包到手 10 秒自检（防止 i18n 资源漏打包回归）

0.3.0 首发版曾出现过「打包漏加 i18n JSON → GUI 直接显示英文 key」的
bug，新包到手跑两条肉眼检查就能确认无问题（见 CHANGELOG G7）：

1. **标题栏**：**左上角**标题应为「豆比下载 0.3.0 · 多平台视频下载器」，
   不是「豆比下载 0.3.0 · app.title_suffix」。
2. **左侧导航**：侧边栏从上到下文字是「解析 / 下载 / 历史 / 设置」，
   不是「nav.parse / av.downloads / nav.history / nav.settings」。

如果出现后者，就是打包时的 `--add-data locales` 漏加或 frozen 寻址错，
请换一份带有 `*.sha256` 侧签的正式发版包，不要用私有构建产物。

### 下载后完整性校验（推荐）

PowerShell 对比侧签（无需装任何工具）：

```powershell
# 验证 NSIS 安装包
$e=(Get-Content DouBi-Setup-0.3.0.exe.sha256).Trim()
$a=(Get-FileHash DouBi-Setup-0.3.0.exe -Algorithm SHA256).Hash.ToLower()
$e -eq $a     # 必须 $true
```

得到 `True` 再继续。

## 安装

```bash
# 内核 + CLI（最小）
pip install -e .

# 全功能（GUI + REST + Playwright）
pip install -e ".[all]" && python -m playwright install chromium
```

## 下载

```bash
# B 站单条
doubi download -u "https://www.bilibili.com/video/BV1xx411c7mD" -o ./Downloaded

# 抖音单条
doubi download -u "https://www.douyin.com/video/7123456789012345678" -o ./Downloaded

# YouTube（watch / shorts / youtu.be 短链均可，无需登录）
doubi download -u "https://www.youtube.com/watch?v=dQw4w9WgXcQ" -o ./Downloaded
doubi download -u "https://youtu.be/dQw4w9WgXcQ" -o ./Downloaded

# 批量（文件每行一个 URL）
doubi download --batch urls.txt -o ./Downloaded

# 用户主页 / 收藏夹 / 稍后再看
doubi download -u "https://space.bilibili.com/123456" -o ./Downloaded --strategy space
doubi download -u "https://www.bilibili.com/favlist?fid=999" --strategy favlist
doubi download -u "https://www.bilibili.com/watchlater" --strategy watch_later
doubi download -u "https://www.douyin.com/user/MS4wLjABAAAAxxxx" --strategy post

# 抖音合集（M6.7）——两种链接形态都可以
doubi download -u "https://www.douyin.com/collection/7647083357288957995" -o ./Downloaded
doubi download -u "https://www.iesdouyin.com/share/mix/detail/7647083357288957995/" -o ./Downloaded

# 抖音信息流/弹窗链接（modal_id / vid 就是视频 ID，自动规范化为 /video/{id}）
doubi download -u "https://www.douyin.com/jingxuan?modal_id=7676517073484352822"

# 常用开关
doubi download -u URL --quality 4k --container mkv --concurrent 4
doubi download -u URL --no-database --no-manifest   # 完全跳过记录

# 侧车文件（附加下载）——与主视频并排落盘
doubi download -u URL --nfo            # Kodi/Jellyfin 可识别的 .nfo 元数据
doubi download -u URL --subtitles      # 字幕（自动 + 手动，yt-dlp 产出 .vtt）
doubi download -u URL --danmaku        # B 站弹幕（分P级 .xml，不走 yt-dlp）
doubi download -u URL --nfo --subtitles --danmaku     # 可以叠加

# 目录 / 文件名模板（默认就是下面的值，写进 config 就不用每次加）
doubi download -u URL \
      --output-template "{platform}/{author}/{media_type}" \
      --filename "{title}_{item_id}"

# 限速 / 代理
doubi download -u URL --rate-limit 5M                      # e.g. 5M / 1000K
doubi download -u URL --proxy "http://127.0.0.1:7890"

# 断点续传：默认开启。想「每次都从头下」用这个关
doubi download -u URL --no-resume
```

## 下载引擎（M6.15）

默认用 yt-dlp（解析网页 + 下载一体）。也可以切到 aria2 多线程引擎加速大文件下载：

```yaml
# ~/.doubi/config.yml
engine: aria2
aria2_rpc_url: http://127.0.0.1:6800/jsonrpc   # aria2 守护进程地址
aria2_secret: null                              # RPC token，没有就 null
```

> aria2 是纯下载器（不解析网页），只对解析后带 `direct_url` 的 item 生效，
> 其余自动回退 yt-dlp。要先启动 aria2 守护进程（`aria2c --enable-rpc`）。
> 适合大文件 / 慢源加速，不适合取代 yt-dlp 的网页解析。

## 登录

```bash
doubi auth bilibili          # 扫码 + Playwright 自动抓 cookies
doubi auth douyin            # 浏览器内登录 + 自动抓 cookies
doubi auth status            # 查看两个平台登录态

# 手动导入（Playwright 不可用时）
doubi auth bilibili --import cookies.txt
doubi auth douyin --import cookies.txt
doubi auth douyin --legacy-json config/cookies.json   # 旧 douyin-downloader 用户
```

## Live 录制

```bash
doubi live -u "https://live.douyin.com/123456789" -o ./Lives            # 抖音，录到下播
doubi live -u "https://live.douyin.com/123456789" --max-duration 3600   # 限时 1 小时

# B 站直播（M6.15）——直播 URL 直接用 download 子命令即可
doubi download -u "https://live.bilibili.com/12345" -o ./Lives
doubi download -u "https://live.bilibili.com/h5/12345" -o ./Lives       # h5 前缀也认
```

> B 站直播走 yt-dlp 的 `BiliBiliLive` extractor。直播流是 HLS，引擎自动
> 启用 `live_from_start`（从开播点时移录制）并提高断流重连次数。
> 真实直播录制效果取决于直播状态与网络，建议先用小房间测试。

## GUI

```bash
doubi-gui                # 或 python -m doubi.ui
doubi-gui --theme deep_sea   # 本次启动强制用「深海」主题
```

### 换主题

内置 7 套主题包，每套都是一整张配色表（背景 / 文字 / 表格斑马纹 / 状态色 / 进度条），不是简单的明暗开关：

| `--theme` 取值 | 界面显示 | 底色 | 适合 |
|---|---|---|---|
| `default_light` | 默认亮 | 浅灰白 | 默认，日常光线 |
| `default_dark` | 默认暗 | 深灰 | 夜间 |
| `doubi` | 豆比紫 | 深紫 | 品牌主题，与桌面图标配色一致 |
| `deep_sea` | 深海 | 墨蓝 | 夜间，偏冷色 |
| `morandi` | 莫兰迪 | 暖米灰 | 低饱和，久看不累 |
| `eye_care` | 护眼 | 米黄 | 长时间盯屏 |
| `high_contrast` | 高对比 | 纯黑 + 亮黄 | 弱视 / 强光环境 |

表格顺序就是设置页下拉框与导航栏循环切换的顺序：两套系统默认主题排最前面，
品牌主题 `doubi` 紧随其后。

`doubi` 是品牌主题——配色直接取自应用图标（深紫底 + 琥珀橙主色），其他 6 套是
通用主题。

### 0.3.0 GUI 行为提示（3 条）

从 0.3.0 起，GUI 默认打开就具备下面三个用户体验增强（CHANGELOG G2）：

1. **主窗口自动居中** —— 用 `QGuiApplication.primaryScreen().availableGeometry()`
   计算可用区域（已扣任务栏高度），再 `moveCenter` 居中，不会出现"写了居中结
   果窗口只露右下角"的 bug。
2. **完成 + 缺本地文件 → 「缺失」徽标 + 重新下载** —— 历史里下载完成的视频，
   如果你在文件管理器里手动删了，再打开「下载-已完成」tab，那条记录会标成
   红色 **缺失** 徽标，提示「文件已删除」，右侧按钮变成 **重新下载**（之前
   只有失败 / 取消才能重试）。
3. **静默异常兜底** —— 就算设置页面某个 Qt 槽抛出未处理异常，应用也不会
   像 0.2.x 那样悄无声息闪退；异常会完整写入日志文件，下载中的任务不会被
   跨层误杀。出问题时先看 `~/.doubi/logs/`。

> 窗口居中、缺失重新下载、异常兜底，这三条在 0.3.0 安装包 / onefile
> / onedir 三形态里都是默认开启的，不需要加命令行开关。

三种切换方式：

| 方式 | 立即生效 | 是否记住 |
|---|---|---|
| **设置页**「主题：」下拉框 | 是（选中即预览） | **只有再点「保存设置」才写入 `~/.doubi/config.yml`** |
| **左侧导航栏最下方的画笔按钮** | 是，每点一次循环到下一套，右上角提示切到了哪套 | 否，重启后回到配置里的主题 |
| **命令行 `--theme deep_sea`** | 是 | 否，只影响本次启动 |

所以想让主题固定下来，走设置页并点「保存设置」；画笔按钮和 `--theme` 都只是临时试色。两处控件双向同步——用画笔按钮或 `--theme` 切换，设置页下拉框也会跟着显示当前主题。

优先级（高到低）：`--theme` > `DOUBI_THEME=eye_care` 环境变量 > `~/.doubi/config.yml` > 内置默认（默认亮）。给了 `--theme` 就完全不看后面几项。

> 主题是**全局立即生效**的：已经打开的表格、卡片、下拉框、以及切换之后才新建的对话框和右键菜单都会一起变色，不需要重启。

### 换语言（M6.14）

设置页「外观」卡片有「语言」下拉框（简体中文 / English）。选完点「保存设置」
写入配置，**重启应用后生效**——已渲染的控件不会自动重译，所以语言属于
「重启生效」档（和 `database_path` 一样）。

> 当前已迁移导航标签、窗口标题、tooltip 等核心可见字符串。其余 UI 字符串
> 仍为中文，会逐步迁移到词表。基础设施（`tr()` + JSON 词表）已就绪。

### 解析页操作

1. 粘贴链接 → **解析**（或 **快速下载**：解析第一个 URL 并直接入队）。
2. 勾选要下载的行，点 **下载选中 (N)**。辅助按钮：**全选** / **全不选** / **按行号选择…**（填 `1-5,7,9-12`）。
3. 顶部搜索框按标题 / 作者过滤。

支持的抖音链接形态（M6.7）：

| 链接 | 解析结果 |
|---|---|
| `douyin.com/video/{id}` | 单条视频 |
| `douyin.com/jingxuan?modal_id={id}` 等带 `modal_id` 的页面 | 单条视频（自动规范化） |
| `douyin.com/user/{sec_uid}?...&modal_id={id}&vid={id}`（主页合集 tab 复制的链接） | 单条视频（不会误展开成整个主页） |
| `douyin.com/collection/{mix_id}` | 合集容器，展开为合集内全部视频 |
| `www.iesdouyin.com/share/mix/detail/{mix_id}/`（APP 分享合集） | 同上 |
| `douyin.com/user/{sec_uid}` | 用户容器（全部作品） |

### 下载抖音合集

两种方式：

1. **直接粘贴合集链接**（上表后两种形态）→ 解析 → 勾选下载。
2. **从单条视频反查**：解析任意一条合集内的视频（比如从用户主页合集 tab 复制的那种带
   `modal_id` 的链接），在结果表该行上**右键 → 「下载整个合集」**——程序会自动查出这条
   视频属于哪个合集，把整个合集展开成表格供勾选。

> 抖音合集的列举走签名 Web API（自动处理 a_bogus 签名与反爬重试），无需登录即可列举；
> 高清画质建议先在设置页完成抖音扫码登录。

### 下载「带分类的合集」

B 站合集可能有三层：**合集 → 分类 → 分集 → 分P**。表格默认只显示第一层，**逐层展开都靠右键菜单**（没有双击展开）：

| 右键的行 | 菜单项 | 结果 |
|---|---|---|
| 分类行（`▸ 名称  (N 分集)`） | **展开分类** / **折叠分类** | 在其下方插入 / 移除该分类的分集行 |
| 分集行 | **展开分P** / **折叠分P** | 在其下方插入 / 移除该分集的分P行 |
| 任意行 | 解析此项 / 在浏览器中打开 / 作为单个视频下载 / 查看元数据 / 查看封面 | — |

> **分类行是容器，勾选框不可点**（悬停提示"分类容器不可直接下载 — 展开后勾选下面的分集"）。要下载整个分类，先展开再勾选下面的分集；**全选**也会自动跳过容器行。

### 下载页操作

1. 每一行最右是「暂停/继续」按钮——**文案表达下一步动作**：
   - 正在下载 → 显示「暂停」，点下去立刻进入 `pausing` 状态，随后变 `paused`
   - 已暂停 → 显示「继续」，点下去**断点续传**从 `.part` 的位置接着下，不重来
   - 已完成 / 失败 → 按钮隐藏（但占位宽度不变，表格不跳列）
2. 顶部有「全部暂停 / 全部继续」按钮：
   - 只要还有正在下载的，一律点「暂停」（混合列表不会「暂停一批又恢复另一批」）
   - 全部都暂停了，按钮才切到「全部继续」
3. 顶部摘要写「N 个正在下载，M 个已暂停」。
4. 左侧的「移除」只会从列表拿掉并删除 `.part`；暂停是保留文件、等待继续。

下载结果的目录层级会还原合集结构：

```
bilibili/{作者}/video/{合集名}/{分类名}/{分集名}/{分集名}_{BV号}_P007.mp4
```

单分P视频不带 `_P00N` 后缀。

## REST API

```bash
# 默认绑 127.0.0.1——只本机能访问。对外暴露时必须设 token。
doubi serve --host 127.0.0.1 --port 8000

# 带 token 对外开放（token 用 secrets.compare_digest 比较，防计时侧信道）
doubi serve --host 0.0.0.0 --port 8000 --token s3cret

curl http://127.0.0.1:8000/api/v1/health
curl -X POST http://127.0.0.1:8000/api/v1/download \
     -H 'Content-Type: application/json' -d '{"url": "https://..."}'
curl http://127.0.0.1:8000/api/v1/jobs/{job_id}
curl http://127.0.0.1:8000/api/v1/platforms

# 对外暴露时所有请求都要带 Authorization 头
curl -H "Authorization: Bearer s3cret" http://0.0.0.0:8000/api/v1/health
```

> 默认 `--host 127.0.0.1`，只本机能访问。如果 `--host` 指向了非回环地址
> 且**没有设 `--token`**，启动时会**拒绝启动**——避免无意中把一个能往磁盘
> 写文件的接口挂到局域网上。要强制跳过这个守卫用 `--allow-insecure`。

> `/api/v1/download` 会读取 `~/.doubi/config.yml` 配置文件。M6.2 起，**GUI 设置页里的每一个选项**（目录模板、字幕 / NFO / 弹幕、限速、代理、断点续传）在 REST 端都会同样生效——过去这两端曾静默忽略一部分配置，现在已有结构性测试保证以后新增字段不会再掉。

## MCP（给 Claude Desktop / Cursor 用）

```bash
doubi mcp
# 工具: platforms / parse_url / add_to_queue / get_status / list_jobs
```

Claude Desktop `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "doubi": {
      "command": "doubi",
      "args": ["mcp"]
    }
  }
}
```

## 数据与位置

| 项 | 位置 |
|---|---|
| Cookie | `~/.doubi/cookies/*.txt` |
| 配置 | `~/.doubi/config.yml`（GUI 设置页写入） |
| 数据库 | `doubi.db`（工作目录，可 `--database` 改） |
| 清单 | `download_manifest.jsonl`（工作目录，可 `--manifest` 改） |

## 旧库迁移

```bash
doubi migrate --from douyin  --path /path/to/dy_downloader.db --into doubi.db
doubi migrate --from bilibili --path /path/to/bili23_task.db   --into doubi.db
```
