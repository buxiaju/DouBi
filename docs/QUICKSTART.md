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
```

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
