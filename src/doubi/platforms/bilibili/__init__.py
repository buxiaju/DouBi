"""Bilibili platform adapter (B 站)."""

from __future__ import annotations

from ...core.registry import PlatformRegistry
from .adapter import BilibiliAdapter

# Side-effect: register the adapter on import
PlatformRegistry.register(BilibiliAdapter())

__all__ = ["BilibiliAdapter"]
