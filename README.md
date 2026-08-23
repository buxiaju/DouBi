# DouBi

> 跨平台视频下载器内核 —— 一个 GUI + CLI + REST + MCP 多形态统一的多平台下载器，下载能力由 [yt-dlp](https://github.com/yt-dlp/yt-dlp) 提供。

## 形态

| 形态 | 入口 | 状态 |
|---|---|---|
| 内核（库） | `doubi` | **✓** 平台无关内核 |
| CLI | `doubi download -u URL` | **✓** download / auth / live / migrate / platforms |
| REST 服务 | `doubi serve` | **✓** FastAPI + 内存任务队列 |
| 桌面 GUI | `doubi-gui` | **✓** PySide6 Fluent，6 套主题 |
| MCP 工具 | `doubi-mcp` | **✓** stdio JSON-RPC 2.0 |

## 支持平台

- ✅ **抖音**（`douyin-downloader` 接入；下载走 yt-dlp）
- ✅ **B 站**（`Bili23-Downloader` 接入；下载走 yt-dlp）
- 🚧 计划：YouTube / TikTok 国际版 / 小红书 / 微博 / 快手

## 安装

```bash
# 1) 基础内核 + CLI
pip install -e .

# 2) 桌面 GUI（PySide6 Fluent）
pip install -e ".[gui]"

# 3) REST 服务
pip install -e ".[server]"

# 4) 全装
pip install -e ".[all]"
```

## 快速使用

```bash
# 列出支持的平台
doubi platforms

# 下载单条
doubi download -u "https://www.bilibili.com/video/BV1xx411c7mD" -o ./Downloaded

# 下载抖音
doubi download -u "https://www.douyin.com/video/7123456789012345678" -o ./Downloaded
```

启动图形界面：

```bash
doubi-gui

# 本次启动指定主题（default_light / default_dark / deep_sea / morandi / eye_care / high_contrast）
doubi-gui --theme deep_sea
```

## 主题

GUI 自带 6 套主题包，每套都有自己的底色、文字色与语义色，切换后**整个界面即时生效**
（含切换之后才弹出的对话框和菜单）：

| 主题 | 界面显示 | 底色 |
|---|---|---|
| `default_light` | 默认亮 | 浅灰白 |
| `default_dark` | 默认暗 | 深灰 |
| `deep_sea` | 深海 | 墨蓝 |
| `morandi` | 莫兰迪 | 暖米灰 |
| `eye_care` | 护眼 | 米黄 |
| `high_contrast` | 高对比 | 纯黑 + 亮黄 |

三种切换方式：设置页下拉框、导航栏画笔按钮（循环切换）、启动参数 `--theme`。
**只有在设置页点「保存设置」才会记住**，另两种只在本次运行生效。
详见 [docs/QUICKSTART.md](docs/QUICKSTART.md) 的「换主题」一节。

## 项目结构

```
DouBi/
├── pyproject.toml
├── INTEGRATION_PLAN.md            # 详细整合方案
├── src/doubi/
│   ├── core/                      # 平台无关内核
│   │   ├── models.py              # MediaItem / Stream / DownloadJob
│   │   ├── registry.py            # PlatformRegistry
│   │   ├── pipeline.py            # 解析→派发→下载→后处理
│   │   ├── config.py              # 配置加载
│   │   └── logger.py
│   ├── engines/                   # 下载引擎适配（yt-dlp / aria2 / native）
│   │   ├── base.py
│   │   └── yt_dlp.py
│   ├── platforms/                 # 平台适配器
│   │   ├── base.py                # PlatformAdapter ABC
│   │   ├── douyin/                # 抖音
│   │   └── bilibili/              # B 站
│   ├── cli/                       # 命令行
│   │   └── main.py
│   ├── server/                    # REST（FastAPI）
│   │   ├── app.py
│   │   ├── jobs.py                # JobManager 内存任务队列
│   │   └── schemas.py
│   ├── ui/                        # PySide6 GUI
│   │   ├── app.py                 # 入口（--theme）
│   │   ├── main_window.py
│   │   ├── theme.py               # 6 套主题包 / token 表 / set_theme
│   │   ├── task_manager.py        # 暂停 / 继续 / 取消
│   │   ├── pages/                 # parse / download / history / settings
│   │   └── dialogs/               # login_dialog.py
│   └── mcp/                       # MCP 工具（stdio JSON-RPC）
│       └── server.py
├── docs/                          # ARCHITECTURE / DEVELOPMENT / QUICKSTART / CHANGELOG
└── tests/                         # 19 个测试文件
```

## 文档

| 文档 | 内容 |
|---|---|
| [docs/QUICKSTART.md](docs/QUICKSTART.md) | 装完之后怎么用：CLI / GUI / REST / MCP、换主题、配置项 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 分层、数据流、存储 schema、任务生命周期、主题生效链路 |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | 开发约定、各模块要点、主题系统内幕、测试清单 |
| [docs/CHANGELOG.md](docs/CHANGELOG.md) | 里程碑与缺陷复盘（根因 / 修法 / 判据） |
| [INTEGRATION_PLAN.md](INTEGRATION_PLAN.md) | 原始整合方案 |

## 整合来源

- `douyin-downloader-main` —— URL 解析、命名规则、清单文件、Cookie 编排、UI 入口
- `Bili23-Downloader-main` —— 桌面 GUI（Fluent Design）、MCP、命名规则引擎、附加产物（弹幕/字幕/NFO）
- `yt-dlp` —— 实际下载与媒体探测引擎

## 许可

GPL-3.0。详见 `LICENSE`。

## 致谢

- [jiji262/douyin-downloader](https://github.com/jiji262/douyin-downloader)（MIT）
- [ScottSloan/Bili23-Downloader](https://github.com/ScottSloan/Bili23-Downloader)（GPL-3.0）
- [yt-dlp/yt-dlp](https://github.com/yt-dlp/yt-dlp)（Unlicense）
