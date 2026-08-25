"""YouTube platform adapter.

见 ``adapter.py``。导入本包即注册 YouTubeAdapter。
"""

from __future__ import annotations

from ...core.registry import PlatformRegistry
from .adapter import YouTubeAdapter
from .url import (
    ClassifiedURL,
    YouTubeURLType,
    classify_youtube_url,
    to_watch_url,
)

# Side-effect: register the adapter on import.
# 关键设计：adapter 是「平台 + 适配器实例」一一对应的，所以这里**直接构造**
# 一个实例。不要让 adapter 在 ``__init__`` 里做网络请求——保持「import 廉价」
# 的承诺，否则 ``doubi.platforms`` 包导入会变慢且脆弱（B 站 / 抖音的 cookie
# 文件读取在 adapter ``__init__`` 里——这里**故意不抄**，因为 YouTube 不需要）。
PlatformRegistry.register(YouTubeAdapter())

__all__ = [
    "YouTubeAdapter",
    "ClassifiedURL",
    "YouTubeURLType",
    "classify_youtube_url",
    "to_watch_url",
]
