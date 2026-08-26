"""DouBi - Multi-platform media downloader.

Layout:
    doubi.core          平台无关内核（models / registry / pipeline / config / logger）
    doubi.engines       下载引擎适配（yt-dlp 等）
    doubi.platforms     平台适配器（douyin / bilibili / ...）
    doubi.cli           命令行入口
    doubi.server        REST 服务（M6）
    doubi.ui            桌面 GUI（M5）
    doubi.mcp           MCP 工具（M6）
"""

from __future__ import annotations

__version__ = "0.3.0"
__all__ = ["__version__"]
