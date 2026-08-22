# DouBi

> 跨平台视频下载器内核 —— 一个 GUI + CLI + REST + MCP 多形态统一的多平台下载器，下载能力由 [yt-dlp](https://github.com/yt-dlp/yt-dlp) 提供。

## 形态

| 形态 | 入口 | 状态 |
|---|---|---|
| 内核（库） | `doubi` | **M1 ✓** 本骨架 |
| CLI | `doubi download -u URL` | **M1 ✓** 最小可用 |
| REST 服务 | `doubi serve` | M6 |
| 桌面 GUI | `DouBi Desktop` | M5 |
| MCP 工具 | `doubi-mcp` | M6 |

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
│   ├── server/                    # REST（占位，M6 落地）
│   ├── ui/                        # PySide6 GUI（占位，M5 落地）
│   └── mcp/                       # MCP 工具（占位，M6 落地）
└── tests/
    └── test_pipeline_smoke.py
```

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
