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
from .webapi import DouyinWebAPI, aweme_to_media_item

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
        # Feed pages opening a video in a modal: /jingxuan?modal_id=...
        re.compile(r"https?://(?:www\.)?douyin\.com/[^?\s]*[?&][^\s]*?modal_id=\d+"),
        # Mobile share links: iesdouyin.com/share/mix/detail/{id}/ ...
        re.compile(r"https?://(?:www\.)?iesdouyin\.com/share/(?:mix|video|note)/"),
    ]

    def __init__(self):
        cookies_file = load_cookie_file()
        self.api = DouyinAPI(cookies_file=cookies_file)
        self.webapi = DouyinWebAPI(cookies_file=cookies_file)
        self._strategies: dict[str, ContainerStrategy] = {
            "post": PostStrategy(self.api, webapi=self.webapi),
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

        # modal_id URLs (e.g. /jingxuan?modal_id=...) classify as VIDEO but
        # are NOT recognized by yt-dlp's extractor — rewrite to the canonical
        # /video/{id} form before fetching metadata or downloading.
        if (
            classified.type is DouyinURLType.VIDEO
            and classified.item_id
            and f"/video/{classified.item_id}" not in url
        ):
            url = f"https://www.douyin.com/video/{classified.item_id}"

        if classified.type in (DouyinURLType.COLLECTION, DouyinURLType.MIX):
            return await self._parse_collection(classified.item_id)

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
    # collection (合集) URL → MIX container
    # ------------------------------------------------------------------

    async def _parse_collection(self, mix_id: str) -> MediaItem:
        """Build a MIX container for a 合集 URL.

        Children are NOT expanded here — the pipeline calls
        :meth:`expand` when it sees the container. The title is
        probed best-effort from the first page (``/mix/detail/`` is
        often 403'd by risk control, but ``/mix/aweme/`` page 1
        carries ``mix_info.mix_name``).
        """
        title = f"抖音合集 {mix_id}"
        try:
            page = await self.webapi.get_mix_aweme(mix_id, count=1)
            for raw in page["items"]:
                aweme = raw if raw.get("aweme_id") else (
                    raw.get("aweme_info") or raw.get("aweme") or {}
                )
                name = ((aweme.get("mix_info") or {}).get("mix_name") or "").strip()
                if name:
                    title = f"抖音合集《{name}》"
                    break
        except Exception:
            logger.debug("mix title probe failed for %s", mix_id, exc_info=True)
        return MediaItem(
            platform=self.platform,
            item_id=mix_id,
            title=title,
            author=Author(),
            media_type=MediaType.MIX,
            source_url=f"https://www.douyin.com/collection/{mix_id}",
            extra={"mix_id": mix_id},
        )

    async def collection_of(self, aweme_id: str) -> Optional[MediaItem]:
        """Return the 合集 container a single video belongs to (or None).

        Lets the GUI offer「下载整个合集」when the user only has a
        link to one video of the collection.
        """
        detail = await self.webapi.get_video_detail(aweme_id)
        if not detail:
            return None
        mix_id = (detail.get("mix_info") or {}).get("mix_id")
        if not mix_id:
            return None
        return await self._parse_collection(str(mix_id))

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
        """Expand a USER or MIX container using the named strategy.

        Returns the children list. Mutates ``item.children`` as a side
        effect so callers that keep the item see the expansion.
        """
        if item.media_type is MediaType.MIX:
            # 合集：strategy is irrelevant; enumerate via the signed
            # web API (yt-dlp has no Douyin collection extractor).
            awemes = await self.webapi.iter_mix_awemes(
                item.item_id, max_count=max_count,
            )
            children = [aweme_to_media_item(a) for a in awemes]
            item.children = children
            return children
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
