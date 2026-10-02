"""Platform adapters.

Each adapter knows how to recognize, parse, and post-process URLs for a
specific platform. Importing this package also triggers registration of
all built-in adapters into ``doubi.core.registry.PlatformRegistry``.
"""

from __future__ import annotations

# M6.17+：ytdlp_generic 把任意 URL 丢给 yt-dlp 自身 extractor（1800+ 站点）。
# 注册顺序在 generic 之前是因为 priority 都是 -1 时 stable sort 会按 import
# 顺序选——但实际 ytdlp_generic.priority = -1 > generic.priority = -2，所以
# 顺序无关紧要；保留「先具体平台→再通用兜底」的语义可读性。
from . import (
    bilibili,  # noqa: F401  (side-effect: register adapter)
    douyin,  # noqa: F401  (side-effect: register adapter)
    generic,  # noqa: F401  (side-effect: register adapter; priority=-2 末位兜底)
    youtube,  # noqa: F401  (side-effect: register adapter)
    ytdlp_generic,  # noqa: F401  (side-effect: register adapter; priority=-1 中间兜底)
)
from .base import PlatformAdapter

__all__ = ["PlatformAdapter"]
