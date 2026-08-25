"""Generic platform adapter — 任意 URL 的兜底嗅探。

见 ``adapter.py``。导入本包即注册 GenericAdapter 到 PlatformRegistry。
priority=-1 让 douyin / bilibili / youtube 等具体平台先匹配。
"""

from __future__ import annotations

from ...core.registry import PlatformRegistry
from .adapter import GenericAdapter

# Side-effect: register the adapter on import.
# 关键设计：generic 适配器**故意** priority=-1，让 ``PlatformRegistry.detect``
# 在所有 normal-priority 适配器都不匹配后才走 generic。这样用户输入
# Bilibili / YouTube / Douyin 的 URL 仍然会先匹配到对应平台的适配器，
# 走平台特化的解析路径（拿到正确的标题、UP 主、合集结构等），
# 不会误走 generic 嗅探。
PlatformRegistry.register(GenericAdapter())

__all__ = ["GenericAdapter"]
