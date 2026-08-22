"""Douyin platform adapter (抖音).

Provides URL pattern recognition and (eventually) rich metadata extraction.
Downloads are delegated to the configured engine (default: yt-dlp), so we
no longer need x-bogus / a-bogus signing in the adapter — yt-dlp handles
those.
"""

from __future__ import annotations

from ...core.registry import PlatformRegistry
from .adapter import DouyinAdapter
from .url import DouyinURLType, classify_douyin_url

# Side-effect: register the adapter on import
PlatformRegistry.register(DouyinAdapter())

__all__ = [
    "DouyinAdapter",
    "DouyinURLType",
    "classify_douyin_url",
]
