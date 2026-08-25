"""Platform registry — global lookup table for platform adapters.

Adapters self-register on import (see ``doubi.platforms.douyin.__init__``
etc.). The registry is intentionally a class with class-level state so
that ``doubi.core`` stays importable without triggering platform
package imports (avoiding the chicken-and-egg of ``platforms/__init__``
importing ``core``).
"""

from __future__ import annotations

import logging
import threading
from typing import Iterable, Optional

from .models import Platform

logger = logging.getLogger("doubi.core.registry")


class PlatformRegistry:
    """Thread-safe registry of platform adapters."""

    _lock = threading.RLock()
    _by_platform: dict[Platform, "PlatformAdapter"] = {}  # type: ignore[name-defined]
    _by_name: dict[str, "PlatformAdapter"] = {}            # type: ignore[name-defined]

    # ------------------------------------------------------------------ API

    @classmethod
    def register(cls, adapter: "PlatformAdapter") -> "PlatformAdapter":  # type: ignore[name-defined]
        with cls._lock:
            existing = cls._by_platform.get(adapter.platform)
            if existing is not None and existing is not adapter:
                logger.debug(
                    "Replacing platform adapter for %s: %r -> %r",
                    adapter.platform, existing, adapter,
                )
            cls._by_platform[adapter.platform] = adapter
            cls._by_name[adapter.name] = adapter
            logger.info(
                "Registered platform adapter: %s (%s) -> %s",
                adapter.name, adapter.display_name, adapter.platform.value,
            )
            return adapter

    @classmethod
    def get(cls, platform: Platform) -> "PlatformAdapter":  # type: ignore[name-defined]
        with cls._lock:
            adapter = cls._by_platform.get(platform)
        if adapter is None:
            raise KeyError(f"No adapter registered for platform: {platform!r}")
        return adapter

    @classmethod
    def get_by_name(cls, name: str) -> "PlatformAdapter":  # type: ignore[name-defined]
        with cls._lock:
            adapter = cls._by_name.get(name)
        if adapter is None:
            raise KeyError(f"No adapter registered with name: {name!r}")
        return adapter

    @classmethod
    def all(cls) -> list["PlatformAdapter"]:  # type: ignore[name-defined]
        with cls._lock:
            return list(cls._by_platform.values())

    @classmethod
    def detect(cls, url: str) -> Optional["PlatformAdapter"]:  # type: ignore[name-defined]
        """Return the first adapter whose URL patterns match ``url``.

        Adapters are tried in descending :attr:`priority` order — generic
        兜底适配器（priority=-1, match_url 永真）排最后，确保 douyin /
        bilibili / youtube 等具体平台先匹配。
        """
        with cls._lock:
            adapters: Iterable = list(cls._by_platform.values())
        # 高 priority 先匹配；同 priority 保持注册顺序（stable sort）。
        adapters = sorted(adapters, key=lambda a: -a.priority)
        for adapter in adapters:
            try:
                if adapter.match_url(url):
                    return adapter
            except Exception:  # pragma: no cover - defensive
                logger.exception("match_url raised on %s", adapter)
        return None

    @classmethod
    def clear(cls) -> None:
        """Test helper — wipe all registered adapters."""
        with cls._lock:
            cls._by_platform.clear()
            cls._by_name.clear()

    @classmethod
    def __len__(cls) -> int:
        with cls._lock:
            return len(cls._by_platform)
