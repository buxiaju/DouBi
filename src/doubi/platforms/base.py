"""Platform adapter base class.

A platform adapter is responsible for:
    1. Recognizing its own URLs (via :attr:`url_patterns`).
    2. Parsing a URL into a normalized :class:`MediaItem` (or a tree
       of :class:`MediaItem` for containers like users / favlists).
    3. (Optionally) building the URL the engine should fetch — useful
       when a platform's public URL is different from its direct
       media URL.
    4. (Eventually) providing platform-specific post-processing steps
       such as NFO generation, danmaku download, or transcript upload.

Adapters are registered into :class:`doubi.core.registry.PlatformRegistry`
on import. See ``doubi/platforms/douyin/__init__.py`` for an example.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Pattern

from ..core.models import MediaItem, Platform


class PlatformAdapter(ABC):
    """Base class for platform adapters."""

    #: Stable identifier (e.g. ``"douyin"``, ``"bilibili"``).
    name: str = "base"
    #: Platform enum value.
    platform: Platform = Platform.UNKNOWN
    #: Human-readable name shown in UIs.
    display_name: str = "Base"
    #: URL patterns that this adapter recognizes.
    url_patterns: list[Pattern[str]] = []

    def match_url(self, url: str) -> bool:
        if not url:
            return False
        return any(p.search(url) for p in self.url_patterns)

    @abstractmethod
    async def parse(self, url: str) -> MediaItem | None:
        """Parse ``url`` into a :class:`MediaItem` (or container).

        Return ``None`` if the URL is recognized but cannot be parsed
        (the registry already matched it; something is genuinely wrong
        with the input). Raise only on programmer error / network
        failure that callers cannot recover from — adapters should
        catch their own exceptions and return ``None`` with a logged
        error.
        """
        raise NotImplementedError

    # ---- optional hooks ----------------------------------------------

    def build_engine_url(self, item: MediaItem) -> str:
        """Return the URL the engine should fetch.

        Default: use the item's ``source_url`` unchanged. Override
        when the public URL is not what the engine (yt-dlp) can
        handle — e.g. you need to look up an internal ID first.
        """
        return item.source_url

    def supported_media_types(self) -> list[str]:
        """Optional hint for UIs listing what this platform can download."""
        return []

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<{type(self).__name__} platform={self.platform.value} name={self.name!r}>"
