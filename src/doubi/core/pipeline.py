"""Core pipeline: parse → expand (containers) → render filename → download → record.

The pipeline is the only place that knows about *all five* of those
steps. Adapters know how to parse a URL; engines know how to fetch a
single MediaItem. The pipeline glues them together and handles
container recursion (USER / favlist / mix → child items), the
filename-rendering policy, and the post-download persistence
(Database + ManifestWriter).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from .models import (
    DownloadJob,
    DownloadOptions,
    MediaItem,
    MediaType,
    Platform,
)
from .registry import PlatformRegistry

# Lazy imports to keep `doubi.core` importable without optional deps
def _import_naming():
    """Lazy import: avoid circular import + let platforms opt out."""
    from .naming import set_item_output_template
    return set_item_output_template

def _import_file_layout():
    from .storage.file_layout import resolve_item_dir, resolve_save_dir
    return resolve_item_dir, resolve_save_dir

def _import_manifest():
    from .storage.manifest import ManifestWriter
    return ManifestWriter

logger = logging.getLogger("doubi.core.pipeline")


# ---------------------------------------------------------------------------
# Progress events
# ---------------------------------------------------------------------------


@dataclass
class ProgressEvent:
    """A single progress notification emitted by the pipeline."""

    job_id: str
    item: MediaItem
    phase: str                            # parsing | expanding | downloading | merging | postprocess | done | failed
    fraction: float = 0.0                 # 0.0 - 1.0
    message: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class DownloadPipeline:
    """Orchestrates ``parse → expand → download`` for one or more URLs / items."""

    def __init__(self, engine: Any, max_concurrent: int = 3):
        self.engine = engine
        self._sem = asyncio.Semaphore(max_concurrent)

    # ---- public API ---------------------------------------------------

    async def parse(self, url: str) -> MediaItem | None:
        """Parse a URL into a MediaItem using the matching platform adapter."""
        adapter = PlatformRegistry.detect(url)
        if adapter is None:
            logger.error("No platform adapter matched URL: %s", url)
            return None
        try:
            return await adapter.parse(url)
        except Exception:
            logger.exception("Adapter %s raised while parsing %s", adapter.name, url)
            return None

    async def process_url(
        self,
        url: str,
        options: DownloadOptions,
        *,
        on_progress=None,
        job_id: Optional[str] = None,
        container_strategy: str = "post",
        container_max: int = 0,
    ) -> Optional[MediaItem]:
        """Parse a single URL, then download it (recursing into containers)."""
        job_id = job_id or uuid.uuid4().hex

        item = await self.parse(url)
        if item is None:
            self._emit(on_progress, ProgressEvent(
                job_id=job_id,
                item=MediaItem(platform=Platform.UNKNOWN, item_id="", title="", source_url=url),
                phase="failed", fraction=0.0, message="No adapter matched or parse failed",
            ))
            return None

        if item.is_container() or item.media_type is MediaType.USER:
            return await self._process_container(
                item, options, on_progress, job_id,
                strategy=container_strategy, max_count=container_max,
            )

        ok = await self._download_with_progress(item, options, on_progress, job_id)
        return item if ok else None

    async def download_item(
        self,
        item: MediaItem,
        options: DownloadOptions,
        *,
        on_progress=None,
        job_id: Optional[str] = None,
    ) -> bool:
        """Download an already-parsed item directly (no re-parse).

        Used by the GUI's "download selected" flow, where items were
        already expanded into a picker table — re-parsing would either
        re-fetch or, worse, treat a container URL as the parent again.
        """
        job_id = job_id or uuid.uuid4().hex

        # Hard guard: containers can NEVER be downloaded directly. The
        # GUI must expand containers before adding children to
        # TaskManager. If this check fires, it means a bug earlier in
        # the UI pipeline let a COLLECTION / FAVLIST / USER / MIX item
        # through. Fail loudly and clearly instead of silently handing
        # the engine an un-dereferenceable playlist URL (which used to
        # surface as the vague "engine returned False").
        if item.is_container() or item.media_type is MediaType.USER:
            msg = (
                f"Refusing to download container item "
                f"(media_type={item.media_type!r}, "
                f"children={len(item.children)}, item_id={item.item_id!r}). "
                f"Expand the container first and download its children individually."
            )
            logger.error("[%s] %s", job_id[:8], msg)
            self._emit(on_progress, ProgressEvent(
                job_id=job_id, item=item, phase="failed",
                fraction=0.0, message=msg,
                extra={"reason": "container_not_downloadable"},
            ))
            return False

        return await self._download_with_progress(item, options, on_progress, job_id)

    async def parse_and_expand(
        self,
        url: str,
        *,
        strategy: Optional[str] = None,
        max_count: int = 0,
    ) -> tuple[Optional[MediaItem], list[MediaItem]]:
        """Parse a URL, then expand a container into its children.

        Returns ``(item, children)``:

        * single item  -> ``(item, [])``
        * container    -> ``(container, [child, child, ...])``
        * parse failed -> ``(None, [])``

        ``strategy=None`` lets each platform adapter pick its own
        default expansion (B 站: space / mix / favlist per URL type;
        抖音: post). This is the GUI's "解析" entry point: it gives
        the UI a flat list of *downloadable* items to present to the
        user for selection (matching the Bili23 parse-and-pick
        workflow).
        """
        item = await self.parse(url)
        if item is None:
            return None, []

        if item.is_container() or item.media_type is MediaType.USER:
            adapter = PlatformRegistry.get(item.platform)
            expand = getattr(adapter, "expand", None)
            if callable(expand):
                children = await expand(item, strategy=strategy, max_count=max_count)
            else:
                children = list(item.children)
            return item, children

        return item, []

    async def process_batch(
        self,
        items: list[MediaItem],
        options: DownloadOptions,
        *,
        on_progress=None,
    ) -> DownloadJob:
        """Download a batch of already-parsed items, honoring concurrency."""
        job = DownloadJob(
            job_id=uuid.uuid4().hex,
            items=list(items),
            options=options,
            status="running",
            started_at=datetime.now(),
        )

        async def _one(it: MediaItem) -> bool:
            return await self._download_with_progress(it, options, on_progress, job.job_id)

        results = await asyncio.gather(*[_one(it) for it in items], return_exceptions=True)

        job.finished_at = datetime.now()
        any_ok = any(r is True for r in results)
        any_bad = any(r is False or isinstance(r, Exception) for r in results)
        if any_bad and not any_ok:
            job.status = "failed"
        elif any_bad:
            job.status = "completed"  # partial success
        else:
            job.status = "completed"
        return job

    # ---- internals ----------------------------------------------------

    async def _process_container(
        self,
        container: MediaItem,
        options: DownloadOptions,
        on_progress,
        job_id: str,
        *,
        strategy: str,
        max_count: int,
    ) -> MediaItem:
        """Expand a container, then process its children as a batch."""
        adapter = PlatformRegistry.get(container.platform)

        self._emit(on_progress, ProgressEvent(
            job_id=job_id, item=container, phase="expanding",
            fraction=0.0, message=f"Expanding container ({strategy})...",
        ))

        # DouyinAdapter exposes .expand(); other adapters just use .children
        expand = getattr(adapter, "expand", None)
        if callable(expand):
            children = await expand(container, strategy=strategy, max_count=max_count)
        else:
            children = list(container.children)

        if not children:
            logger.warning("[%s] container %s expanded to 0 items", job_id[:8], container.source_url)
            self._emit(on_progress, ProgressEvent(
                job_id=job_id, item=container, phase="done",
                fraction=1.0, message="Container expanded to 0 items",
            ))
            return container

        self._emit(on_progress, ProgressEvent(
            job_id=job_id, item=container, phase="expanding",
            fraction=1.0, message=f"Expanded to {len(children)} items",
        ))

        # Recurse: treat children as a fresh batch
        await self.process_batch(children, options, on_progress=on_progress)
        container.extra["downloaded_count"] = len(children)
        return container

    async def _download_with_progress(
        self,
        item: MediaItem,
        options: DownloadOptions,
        on_progress,
        job_id: str,
        *,
        index: int = 0,
    ) -> bool:
        # Render filename once, right before the engine call, so any
        # metadata fetched by the adapter is honored.
        try:
            set_template = _import_naming()
            set_template(item, options, index=index)
        except Exception:
            logger.debug("naming hook not available; engine will use raw template")

        # Dedup: skip if the DB already has this (platform, item_id) row.
        if options.database:
            try:
                from .storage.database import Database
                db = Database(options.database)
                await db.initialize()
                try:
                    if await db.is_downloaded(item.platform.value, item.item_id):
                        logger.info("[%s] already in DB; skipping %s/%s",
                                    job_id[:8], item.platform.value, item.item_id)
                        self._emit(on_progress, ProgressEvent(
                            job_id=job_id, item=item, phase="done",
                            fraction=1.0, message="already downloaded (DB)",
                        ))
                        return True
                finally:
                    await db.close()
            except Exception as exc:
                logger.debug("DB check failed (continuing): %s", exc)

        self._emit(on_progress, ProgressEvent(
            job_id=job_id, item=item, phase="downloading",
            fraction=0.0, message=f"Starting {item.source_url}",
        ))

        async with self._sem:
            try:
                ok = await self.engine.download(
                    item, options,
                    on_progress=(
                        lambda ev: on_progress(ProgressEvent(
                            job_id=job_id, item=item,
                            phase="downloading", fraction=ev.fraction,
                            message=ev.message, extra=ev.extra or {},
                        )) if on_progress else None
                    ),
                )
            except Exception as exc:
                logger.exception("[%s] engine.download raised: %s", job_id[:8], exc)
                self._emit(on_progress, ProgressEvent(
                    job_id=job_id, item=item, phase="failed",
                    fraction=0.0, message=f"Exception: {exc}",
                ))
                return False

        # M4: post-download persistence
        if ok:
            await self._record_success(item, options, job_id)

        self._emit(on_progress, ProgressEvent(
            job_id=job_id, item=item,
            phase="done" if ok else "failed",
            fraction=1.0 if ok else 0.0,
            message="ok" if ok else "engine returned False",
        ))
        return ok

    async def _record_success(
        self, item: MediaItem, options: DownloadOptions, job_id: str
    ) -> None:
        """Write the item to DB + manifest after a successful download."""
        # DB
        if options.database:
            try:
                from .storage.database import Database
                db = Database(options.database)
                await db.initialize()
                try:
                    # Compute relative save dir under output_root
                    _, resolve_save_dir = _import_file_layout()
                    save_dir = str(resolve_save_dir(item, options))
                    await db.record_download(
                        platform=item.platform.value,
                        item_id=item.item_id,
                        save_dir=save_dir,
                        title=item.title or None,
                        author_id=item.author.id if item.author else None,
                        author_name=item.author.name if item.author else None,
                        cover_url=item.cover_url,
                        duration=item.duration,
                        publish_time=int(item.publish_time.timestamp()) if item.publish_time else None,
                        media_type=item.media_type.value if item.media_type else None,
                        payload=item.extra.get("payload"),
                        extra={k: v for k, v in (item.extra or {}).items()
                               if k not in ("payload",)},   # avoid double-storing
                    )
                    logger.debug("[%s] recorded %s/%s in DB", job_id[:8],
                                 item.platform.value, item.item_id)
                finally:
                    await db.close()
            except Exception as exc:
                logger.warning("DB record failed: %s", exc)

        # Manifest
        if options.manifest:
            try:
                ManifestWriter = _import_manifest()
                resolve_item_dir, _ = _import_file_layout()
                item_dir = resolve_item_dir(item, options)
                # A collection's episodes share one item_dir, so restrict the
                # listing to files belonging to *this* item; otherwise every
                # episode's manifest row would list its siblings' files too.
                # The match is a prefix so the engine's per-part suffix
                # (``_P007``, see engines.yt_dlp.PART_INDEX_SUFFIX) is kept.
                stem = item.output_template or None
                files = sorted(
                    p.name for p in item_dir.iterdir()
                    if p.is_file() and (stem is None or p.name.startswith(stem))
                )
                rel_paths = [str((item_dir / name).relative_to(options.output_root))
                             for name in files]
                mw = ManifestWriter(options.manifest)
                mw.record(item, file_names=files, file_paths=rel_paths)
            except Exception as exc:
                logger.warning("manifest write failed: %s", exc)

    # ---- helpers ------------------------------------------------------

    @staticmethod
    def _emit(callback, event: ProgressEvent) -> None:
        if callback is None:
            return
        try:
            callback(event)
        except Exception:
            logger.exception("progress callback raised; ignoring")
