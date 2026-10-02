"""Generic platform adapter — 任意 URL 的最末兜底嗅探。

见 ``adapter.py``。导入本包即注册 GenericAdapter 到 PlatformRegistry。
兜底顺序（M6.17+）：具体平台 (priority=0) → ytdlp_generic (priority=-1)
→ generic (priority=-2, Playwright 嗅探)。
"""

from __future__ import annotations

from ...core.registry import PlatformRegistry
from .adapter import GenericAdapter

# Side-effect: register the adapter on import.
# 关键设计：generic 适配器**故意** priority=-2，让 ``PlatformRegistry.detect``
# 在 ytdlp_generic (priority=-1) 也不匹配后才走 generic。这样三层兜底形成
# 链式 fallback：用户输入的 URL 会被最合适的适配器优先解析——具体平台拿
# 自家元数据，ytdlp_generic 覆盖 1800+ 站，generic 嗅探应对 yt-dlp 不识别
# 的国产 HLS / 自建 CMS。
PlatformRegistry.register(GenericAdapter())

__all__ = ["GenericAdapter"]
