"""Container expansion strategies for Douyin.

When the user gives us a user-level URL (e.g.
``/user/{sec_uid}``), the adapter turns it into a ``MediaItem`` of
type ``USER`` with an empty ``children`` list. A *strategy* expands
that container by enumerating the right slice of the user's content
and returning a list of fully-formed ``MediaItem`` children.

M2 ships two strategies:

* :class:`PostStrategy`   — the user's published videos
* :class:`LikeStrategy`   — videos the user has liked (login required)

Both use yt-dlp's flat-playlist extraction under the hood, so we
inherit its support for whatever URL forms the platform serves. If
yt-dlp cannot enumerate the URL (e.g. a 403, or a missing
"like" playlist), the strategy returns ``[]`` and logs a warning
rather than raising.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Optional

from ...core.models import (
    Author,
    MediaItem,
    MediaType,
    Platform,
)
from .api import DouyinAPI
from .url import DouyinURLType, classify_douyin_url

logger = logging.getLogger("doubi.platforms.douyin.strategies")


class ContainerStrategy(ABC):
    """Base class for container-expansion strategies."""

    #: Strategy name (e.g. ``"post"``, ``"like"``). Used by the CLI flag
    #: ``--strategy post`` and by config files.
    name: str = "base"

    #: Short human description shown in ``doubi platforms`` output.
    description: str = ""

    #: Whether this strategy needs an authenticated session.
    requires_login: bool = False

    def __init__(self, api: DouyinAPI):
        self.api = api

    @abstractmethod
    async def expand(self, url: str, *, max_count: int = 0) -> list[MediaItem]:
        """Return a list of children for the user URL.

        ``max_count=0`` means "all available". Callers should
        truncate the result if a limit was requested.
        """
        raise NotImplementedError

    # ---- shared helpers ---------------------------------------------

    @staticmethod
    def _extract_sec_uid(url: str) -> Optional[str]:
        classified = classify_douyin_url(url)
        if classified.type is DouyinURLType.USER:
            # The named group may include extra query string; strip everything
            # after the first '?' or '&' that isn't part of the sec_uid.
            raw = classified.item_id
            for sep in ("?", "&"):
                if sep in raw:
                    raw = raw.split(sep, 1)[0]
            return raw or None
        return None


# ---------------------------------------------------------------------------
# PostStrategy
# ---------------------------------------------------------------------------


class PostStrategy(ContainerStrategy):
    """A user's published videos."""

    name = "post"
    description = "Download a user's published videos"
    requires_login = False

    async def expand(self, url: str, *, max_count: int = 0) -> list[MediaItem]:
        sec_uid = self._extract_sec_uid(url)
        if not sec_uid:
            logger.warning("PostStrategy: not a user URL: %s", url)
            return []

        playlist_items = f"1:{max_count}" if max_count and max_count > 0 else None
        info = await self.api.fetch_flat(url, playlist_items=playlist_items)
        if not info:
            logger.info("PostStrategy: yt-dlp returned no info for %s", url)
            return []

        entries = info.get("entries") or []
        if not entries and info.get("id"):
            # yt-dlp sometimes returns the parent as a single item if the
            # page doesn't look like a playlist. Treat as a single child.
            entries = [info]

        items: list[MediaItem] = []
        for e in entries:
            child = self.api.flat_to_media_item(e, fallback_url=url)
            if child.item_id:
                items.append(child)
        if max_count:
            items = items[:max_count]
        logger.info("PostStrategy[%s]: %d items", sec_uid, len(items))
        return items


# ---------------------------------------------------------------------------
# LikeStrategy
# ---------------------------------------------------------------------------


class LikeStrategy(ContainerStrategy):
    """A user's liked videos (requires login)."""

    name = "like"
    description = "Download a user's liked videos (login required)"
    requires_login = True

    async def expand(self, url: str, *, max_count: int = 0) -> list[MediaItem]:
        sec_uid = self._extract_sec_uid(url)
        if not sec_uid:
            logger.warning("LikeStrategy: not a user URL: %s", url)
            return []

        if not self.api.cookies_file:
            logger.warning(
                "LikeStrategy: no cookies configured. "
                "Run `doubi auth douyin` (M2.1) or set DOUBI_DOUYIN_COOKIES."
            )
            return []

        # yt-dlp does not have a dedicated "user likes" extractor for
        # Douyin; the closest is to call the underlying web API. For
        # M2 we attempt the same user URL and rely on yt-dlp doing its
        # best; logged-in users will see the likes tab.
        playlist_items = f"1:{max_count}" if max_count and max_count > 0 else None
        info = await self.api.fetch_flat(url, playlist_items=playlist_items)
        if not info:
            return []

        entries = info.get("entries") or []
        items = [self.api.flat_to_media_item(e, fallback_url=url) for e in entries if e.get("id")]
        if max_count:
            items = items[:max_count]
        logger.info("LikeStrategy[%s]: %d items", sec_uid, len(items))
        return items
