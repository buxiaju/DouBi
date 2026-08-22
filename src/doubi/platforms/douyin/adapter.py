"""Douyin platform adapter.

M2 additions over the M1 skeleton:
    * Real metadata fetch via :class:`DouyinAPI` for single-item URLs
    * Container expansion (user URL → list of child MediaItems) via
      :class:`ContainerStrategy` (default: :class:`PostStrategy`)
    * Cookie file lookup via :mod:`auth`

Scope still in M2.1+:
    * ``/user/self?showTab=favorite_collection`` (collect / collectmix)
    * Browser fallback for paginated user modes
    * Live recording
    * Comments collection
    * Transcript upload
"""

from __future__ import annotations

import logging
import re
from typing import Optional

import httpx

from ...core.models import (
    Author,
    MediaItem,
    MediaType,
    Platform,
)
from ..base import PlatformAdapter
from .api import DouyinAPI
from .auth import load_cookie_file
from .strategies import ContainerStrategy, LikeStrategy, PostStrategy
from .url import DouyinURLType, classify_douyin_url

logger = logging.getLogger("doubi.platforms.douyin")


_TYPE_TO_MEDIA: dict[DouyinURLType, MediaType] = {
    DouyinURLType.VIDEO:      MediaType.VIDEO,
    DouyinURLType.NOTE:       MediaType.IMAGE_ALBUM,
    DouyinURLType.GALLERY:    MediaType.IMAGE_ALBUM,
    DouyinURLType.COLLECTION: MediaType.MIX,
    DouyinURLType.MIX:        MediaType.MIX,
    DouyinURLType.MUSIC:      MediaType.MUSIC,
    DouyinURLType.LIVE:       MediaType.LIVE,
    DouyinURLType.SHORT:      MediaType.VIDEO,    # resolved then re-classified
    DouyinURLType.USER:       MediaType.USER,
}


class DouyinAdapter(PlatformAdapter):
    name = "douyin"
    platform = Platform.DOUYIN
    display_name = "抖音"
    url_patterns = [
        re.compile(r"https?://(?:www\.)?douyin\.com/(?:video|note|gallery|collection|mix|music|user)/"),
        re.compile(r"https?://live\.douyin\.com/\d+"),
        re.compile(r"https?://v\.douyin\.com/"),
    ]

    def __init__(self):
        cookies_file = load_cookie_file()
        self.api = DouyinAPI(cookies_file=cookies_file)
        self._strategies: dict[str, ContainerStrategy] = {
            "post": PostStrategy(self.api),
            "like": LikeStrategy(self.api),
        }
        self._default_strategy = "post"

    # ------------------------------------------------------------------
    # introspection
    # ------------------------------------------------------------------

    def supported_media_types(self) -> list[str]:
        return [t.value for t in (
            MediaType.VIDEO, MediaType.IMAGE_ALBUM, MediaType.MIX,
            MediaType.MUSIC, MediaType.LIVE, MediaType.USER,
        )]

    def available_strategies(self) -> list[ContainerStrategy]:
        return list(self._strategies.values())

    def get_strategy(self, name: str) -> Optional[ContainerStrategy]:
        return self._strategies.get(name)

    # ------------------------------------------------------------------
    # parse
    # ------------------------------------------------------------------

    async def parse(self, url: str) -> Optional[MediaItem]:
        classified = classify_douyin_url(url)

        # Short link → resolve → re-classify
        if classified.type is DouyinURLType.SHORT:
            resolved = await self._resolve_short_url(url)
            if not resolved:
                logger.error("Failed to resolve short URL: %s", url)
                return None
            classified = classify_douyin_url(resolved)
            url = resolved

        if classified.type is DouyinURLType.UNKNOWN:
            logger.error("Unrecognized Douyin URL: %s", url)
            return None

        if classified.type is DouyinURLType.USER:
            return await self._parse_user(url, classified.item_id)

        return await self._parse_single(url, classified)

    # ------------------------------------------------------------------
    # single-item URL
    # ------------------------------------------------------------------

    async def _parse_single(self, url: str, classified) -> Optional[MediaItem]:
        media_type = _TYPE_TO_MEDIA.get(classified.type, MediaType.VIDEO)

        info = await self.api.fetch(url)
        if info is None:
            # Couldn't get metadata (network error, private, deleted).
            # Return a minimal item so the engine can still try — yt-dlp
            # often succeeds with a bare URL even when extract_info fails.
            logger.info("No metadata for %s; returning minimal item", url)
            return MediaItem(
                platform=self.platform,
                item_id=classified.item_id,
                title="",
                author=Author(),
                media_type=media_type,
                source_url=url,
            )

        item = self.api.to_media_item(info, url)
        # Preserve our URL-derived media_type when yt-dlp's guess is ambiguous
        if media_type is not MediaType.VIDEO:
            item.media_type = media_type
        return item

    # ------------------------------------------------------------------
    # user URL → container
    # ------------------------------------------------------------------

    async def _parse_user(self, url: str, sec_uid: str) -> MediaItem:
        """Build a USER container. Children are *not* expanded here —
        the pipeline will call :meth:`expand` when it sees the container.
        """
        return MediaItem(
            platform=self.platform,
            item_id=sec_uid,
            title=f"抖音用户 {sec_uid}",
            author=Author(id=sec_uid, name=""),
            cover_url=None,
            duration=None,
            publish_time=None,
            media_type=MediaType.USER,
            source_url=url,
            extra={"available_strategies": list(self._strategies.keys())},
        )

    async def expand(self, item: MediaItem, *, strategy: str = "post", max_count: int = 0) -> list[MediaItem]:
        """Expand a USER container using the named strategy.

        Returns the children list. Mutates ``item.children`` as a side
        effect so callers that keep the item see the expansion.
        """
        if item.media_type is not MediaType.USER:
            return list(item.children)
        s = self._strategies.get(strategy) or self._strategies[self._default_strategy]
        children = await s.expand(item.source_url, max_count=max_count)
        item.children = children
        item.extra["applied_strategy"] = s.name
        return children

    # ------------------------------------------------------------------
    # short URL
    # ------------------------------------------------------------------

    async def _resolve_short_url(self, url: str) -> Optional[str]:
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=10.0,
                headers={"User-Agent": "Mozilla/5.0"},
            ) as client:
                resp = await client.get(url)
                if resp.status_code >= 400:
                    logger.warning("Short URL returned %s: %s", resp.status_code, url)
                    return None
                return str(resp.url)
        except httpx.HTTPError as exc:
            logger.warning("Short URL resolution failed for %s: %s", url, exc)
            return None
