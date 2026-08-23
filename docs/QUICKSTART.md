# DouBi 快速上手

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

# 批量（文件每行一个 URL）
doubi download --batch urls.txt -o ./Downloaded

# 用户主页 / 收藏夹 / 稍后再看
doubi download -u "https://space.bilibili.com/123456" -o ./Downloaded --strategy space
doubi download -u "https://www.bilibili.com/favlist?fid=999" --strategy favlist
doubi download -u "https://www.bilibili.com/watchlater" --strategy watch_later
doubi download -u "https://www.douyin.com/user/MS4wLjABAAAAxxxx" --strategy post

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
doubi live -u "https://live.douyin.com/123456789" -o ./Lives            # 录到下播
doubi live -u "https://live.douyin.com/123456789" --max-duration 3600   # 限时 1 小时
```

## GUI

```bash
doubi-gui                # 或 python -m doubi.ui
doubi-gui --theme deep_sea   # 本次启动强制用「深海」主题
```

### 换主题

内置 6 套主题包，每套都是一整张配色表（背景 / 文字 / 表格斑马纹 / 状态色 / 进度条），不是简单的明暗开关：

| `--theme` 取值 | 界面显示 | 底色 | 适合 |
|---|---|---|---|
| `default_light` | 默认亮 | 浅灰白 | 默认，日常光线 |
| `default_dark` | 默认暗 | 深灰 | 夜间 |
| `deep_sea` | 深海 | 墨蓝 | 夜间，偏冷色 |
| `morandi` | 莫兰迪 | 暖米灰 | 低饱和，久看不累 |
| `eye_care` | 护眼 | 米黄 | 长时间盯屏 |
| `high_contrast` | 高对比 | 纯黑 + 亮黄 | 弱视 / 强光环境 |

三种切换方式：

| 方式 | 立即生效 | 是否记住 |
|---|---|---|
| **设置页**「主题：」下拉框 | 是（选中即预览） | **只有再点「保存设置」才写入 `~/.doubi/config.yml`** |
| **左侧导航栏最下方的画笔按钮** | 是，每点一次循环到下一套，右上角提示切到了哪套 | 否，重启后回到配置里的主题 |
| **命令行 `--theme deep_sea`** | 是 | 否，只影响本次启动 |

所以想让主题固定下来，走设置页并点「保存设置」；画笔按钮和 `--theme` 都只是临时试色。两处控件双向同步——用画笔按钮或 `--theme` 切换，设置页下拉框也会跟着显示当前主题。

优先级（高到低）：`--theme` > `DOUBI_THEME=eye_care` 环境变量 > `~/.doubi/config.yml` > 内置默认（默认亮）。给了 `--theme` 就完全不看后面几项。

> 主题是**全局立即生效**的：已经打开的表格、卡片、下拉框、以及切换之后才新建的对话框和右键菜单都会一起变色，不需要重启。

### 解析页操作

1. 粘贴链接 → **解析**（或 **快速下载**：解析第一个 URL 并直接入队）。
2. 勾选要下载的行，点 **下载选中 (N)**。辅助按钮：**全选** / **全不选** / **按行号选择…**（填 `1-5,7,9-12`）。
3. 顶部搜索框按标题 / 作者过滤。

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
doubi serve --host 127.0.0.1 --port 8000

curl http://127.0.0.1:8000/api/v1/health
curl -X POST http://127.0.0.1:8000/api/v1/download \
     -H 'Content-Type: application/json' -d '{"url": "https://..."}'
curl http://127.0.0.1:8000/api/v1/jobs/{job_id}
curl http://127.0.0.1:8000/api/v1/platforms
```

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
