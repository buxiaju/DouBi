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
from typing import Any, Optional

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
from .webapi import (
    DouyinWebAPI,
    aweme_to_media_item,
    extract_mix_ref,
    format_mix_title,
)

logger = logging.getLogger("doubi.platforms.douyin")


def _mix_ref_title(ref: Optional[dict[str, Any]], mix_id: str = "") -> Optional[str]:
    """Title for a 合集 ref, or ``None`` when it carries no name (M6.56).

    Returning ``None`` (rather than the ``抖音合集 {id}`` placeholder)
    is what lets callers distinguish "resolved a name" from "resolved
    nothing" and decide whether to try another probe.
    """
    if not ref or not str(ref.get("mix_name") or "").strip():
        return None
    return format_mix_title(ref, mix_id)


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
            # 合集 URL 永远返回 MIX 容器，pipeline 触发 expand() 把整
            # 合集的视频全列出来。``seq`` 后缀只是抖音 web 的"滚动到第
            # N 个"的位置提示，不是"我要第 N 条"——``/video/{aweme_id}``
            # 才是要单条。要让用户能完整看到合集的所有视频。
            #
            # M6.45 回归：原本想"seq 解析为单条 VIDEO"，但用户的真实
            # 意图是"显示整个合集每条视频"——退回 MIX 容器是正确的。
            # seq 仍保留在 ``ClassifiedURL.seq`` 备用（debug / / 日志），
            # 但不影响 adapter 行为。
            return await self._parse_collection(
                classified.item_id, seq=classified.seq,
            )

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

    async def _parse_collection(
        self, mix_id: str, *, seq: Optional[int] = None,
        mix_ref: Optional[dict[str, Any]] = None,
    ) -> MediaItem:
        """Build a MIX container for a 合集 URL.

        Children are NOT expanded here — the pipeline calls
        :meth:`expand` when it sees the container.

        Title resolution (M6.56): when the caller already resolved the
        合集 (``mix_ref``, e.g. :meth:`collection_of` coming from a
        single video), that known-good ``mix_name`` is used and **no
        probe is issued**. Otherwise :meth:`_probe_mix_title` runs —
        best-effort, since ``/mix/detail/`` is often 403'd by risk
        control while ``/mix/aweme/`` page 1 carries ``mix_info.mix_name``.

        ``seq`` 保留在 ``source_url`` + ``extra``：抖音 web URL
        ``/collection/{mix_id}/{seq}`` 的 seq 后缀是"滚动到第 N
        个"位置提示，不是"只取第 N 条"。seq 留痕便于调试 + UI 上
        能提示用户"你当时选的是第 N 个开始看"，但 expand() 会把
        整集合都拉下来。
        """
        extra: dict[str, Any] = {"mix_id": mix_id}
        title: Optional[str] = None
        if mix_ref:
            title = _mix_ref_title(mix_ref)
            name = str(mix_ref.get("mix_name") or "").strip()
            if name:
                extra["mix_name"] = name
            # Preserve the platform-side id when it differs from the
            # URL segment (they agree today, but trusting the URL would
            # silently mis-tag a container if that ever changes).
            ref_id = str(mix_ref.get("mix_id") or "").strip()
            if ref_id and ref_id != mix_id:
                extra["mix_id"] = ref_id
        if not title:
            title = await self._probe_mix_title(mix_id)
        source_url = f"https://www.douyin.com/collection/{mix_id}"
        if seq is not None:
            source_url = f"{source_url}/{seq}"
            extra["seq"] = seq
        return MediaItem(
            platform=self.platform,
            item_id=mix_id,
            title=title or f"抖音合集 {mix_id}",
            author=Author(),
            media_type=MediaType.MIX,
            source_url=source_url,
            extra=extra,
        )

    async def _probe_mix_title(self, mix_id: str) -> Optional[str]:
        """尝试从合集第一页拿 ``mix_name``。失败/无名字返回 ``None``。

        抖音 web API 经常 403，所以这是 best-effort，调用方拿到 ``None``
        就回退到占位符标题。

        M6.56 — 委托给 ``DouyinWebAPI.resolve_mix_ref``，与
        ``collection_of`` 共用同一套「先 /mix/detail/ 再 /mix/aweme/
        首页」回查顺序，避免两条路径各自演化出不同语义。
        """
        try:
            ref = await self.webapi.resolve_mix_ref(mix_id=mix_id)
        except Exception:
            logger.debug("mix title probe failed for %s", mix_id, exc_info=True)
            return None
        return _mix_ref_title(ref)

    async def collection_of(self, aweme_id: str) -> Optional[MediaItem]:
        """Return the 合集 container a single video belongs to (or None).

        Lets the GUI offer「下载整个合集」when the user only has a
        link to one video of the collection.

        M6.56 — the aweme detail that we must fetch anyway carries
        ``mix_info``; that name is now threaded into
        :meth:`_parse_collection` instead of being discarded and
        re-probed. Saves one network round-trip per call and gives the
        container its real title even when ``/mix/aweme/`` is 403'd.
        """
        detail = await self.webapi.get_video_detail(aweme_id)
        if not detail:
            return None
        mix_ref = extract_mix_ref(detail)
        mix_id = mix_ref.get("mix_id", "")
        if not mix_id:
            return None
        return await self._parse_collection(mix_id, mix_ref=mix_ref)

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

        Failure handling (M6.46 / M6.47): when enumeration fails due to
        抖音's Argus risk-control (HTTP 403) or other transport issues,
        ``item.extra["expand_error"]`` is stamped with ``{reason,
        status_code, hint}`` keys. The GUI reads the ``hint`` key
        (``need_login`` / ``server_error`` / ``transient``) to surface
        a user-facing message — typically 「需要登录抖音」 — instead
        of leaving the user staring at an empty container card.

        The hint machinery is symmetric for MIX (M6.46) and USER
        containers (M6.47): the abstract ``ContainerStrategy.expand``
        forwards ``error_sink`` to its underlying web-API calls so the
        adapter sees the same reason on either container type.
        """
        if item.media_type is MediaType.MIX:
            # 合集：strategy is irrelevant; enumerate via the signed
            # web API (yt-dlp has no Douyin collection extractor).
            error_sink: dict[str, Any] = {}
            awemes = await self.webapi.iter_mix_awemes(
                item.item_id,
                max_count=max_count,
                error_sink=error_sink,
            )
            children = [aweme_to_media_item(a) for a in awemes]
            item.children = children
            # M6.46: surface the failure reason so the GUI can show
            # 「需要登录抖音」 instead of an empty placeholder MIX card.
            # We only stamp the error when the page-1 fetch actually
            # populated the sink AND we ended up with zero children —
            # otherwise the hint machinery could fire on legitimately
            # empty 合集.
            if not children and error_sink:
                item.extra["expand_error"] = error_sink
                logger.info(
                    "expand MIX %s failed: %s (status=%s, hint=%s)",
                    item.item_id,
                    error_sink.get("reason"),
                    error_sink.get("status_code"),
                    error_sink.get("hint"),
                )
            return children
        if item.media_type is not MediaType.USER:
            return list(item.children)
        # M6.47: USER 容器也走 hint 机制——Argus 风控 / 缺 cookie /
        # yt-dlp 失败 → 同样的「需要登录抖音」徽章，避免 MIX 已支持、
        # USER 还是空白的 UX 不对称。
        s = self._strategies.get(strategy) or self._strategies[self._default_strategy]
        error_sink = {}
        children = await s.expand(
            item.source_url,
            max_count=max_count,
            error_sink=error_sink,
        )
        item.children = children
        item.extra["applied_strategy"] = s.name
        # Same guard as MIX: only fire when expansion produced no children AND
        # the strategy actually populated the sink (legitimately-empty
        # user with 0 public aworks wouldn't).
        if not children and error_sink:
            item.extra["expand_error"] = error_sink
            logger.info(
                "expand USER %s failed: %s (status=%s, hint=%s)",
                item.item_id,
                error_sink.get("reason"),
                error_sink.get("status_code"),
                error_sink.get("hint"),
            )
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
