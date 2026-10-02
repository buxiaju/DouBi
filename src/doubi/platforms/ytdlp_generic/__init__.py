"""yt-dlp 通用兜底适配器 —— 把任意 URL 丢给 yt-dlp extractor。

见 ``adapter.py``。导入本包即注册 YtDlpGenericAdapter 到 PlatformRegistry。
兜底顺序（M6.17+）：具体平台 (priority=0) → ytdlp_generic (priority=-1)
→ generic Playwright 嗅探 (priority=-2)。
"""

from __future__ import annotations

from ...core.registry import PlatformRegistry
from .adapter import YtDlpGenericAdapter

# Side-effect: register the adapter on import.
# 关键设计：ytdlp_generic priority=-1，介于具体平台 (priority=0) 与
# generic (priority=-2) 之间。``PlatformRegistry.detect`` 的 stable sort
# 保证：
#   1. 抖音 / B 站 / YouTube URL → 走具体平台（拿自家元数据）
#   2. Twitter / Instagram / Vimeo / 任意 yt-dlp 认识的 URL → 走 ytdlp_generic
#   3. 都不认识 → 走 generic Playwright 嗅探
PlatformRegistry.register(YtDlpGenericAdapter())

__all__ = ["YtDlpGenericAdapter"]
