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

def _import_nfo():
    from .storage.nfo import write_nfo
    return write_nfo

def _resolve_platform_cookie_file(platform: Platform) -> Optional[Any]:
    """Best-effort lookup of the platform's persisted cookie file.

    yt-dlp's Douyin / Bilibili extractors refuse to run (or return
    garbage) without cookies, but ``DownloadOptions.cookies_file`` is
    only set by callers that explicitly pass one — every entry point
    (GUI / CLI / REST / MCP) currently builds the options bag without
    it. Resolving per-item here, right before the engine call, means
    the login the user did in the UI actually reaches yt-dlp without
    each surface having to know about ``~/.doubi/cookies``.

    Returns the path (as Path) or ``None``; never raises.
    """
    try:
        from importlib import import_module
        mod = import_module(f"doubi.platforms.{platform.value}.auth")
        loader = getattr(mod, "load_cookie_file", None)
        if loader is None:
            return None
        loaded = loader()
        if not loaded:
            return None
        from pathlib import Path
        return Path(loaded)
    except Exception:
        return None


def _is_cancelled(options: DownloadOptions) -> bool:
    """Has the caller asked us to stop?

    ``cancel_check`` rides on :class:`DownloadOptions` rather than the
    engine signature because the engine runs inside ``asyncio.to_thread``
    where ``Task.cancel()`` cannot reach it. The retry loop must consult
    it: a user-requested stop surfaces as ``ok is False``, exactly like a
    genuine error (``engines.yt_dlp`` swallows its own DownloadCancelled),
    so without this probe a paused download would be silently retried.

    A misbehaving probe must never take the download down with it, hence
    the blanket except: "cannot tell" degrades to "not cancelled", which
    at worst costs one extra attempt.
    """
    probe = getattr(options, "cancel_check", None)
    if probe is None:
        return False
    try:
        return bool(probe())
    except Exception:   # noqa: BLE001
        return False


# Retry defaults live on the *factory* (engine_loader.build_default_pipeline),
# not here: a bare ``DownloadPipeline(...)`` stays a single-attempt primitive
# so callers that want exactly one engine call keep getting exactly one.
# yt-dlp already retries internally ("retries": 3, see engines.yt_dlp), so
# these outer attempts multiply that budget -- keep them small.
DEFAULT_MAX_RETRIES = 2
DEFAULT_RETRY_BACKOFF = 2.0

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

    def __init__(
        self,
        engine: Any,
        max_concurrent: int = 3,
        *,
        max_retries: int = 0,
        retry_backoff: float = DEFAULT_RETRY_BACKOFF,
    ):
        """
        ``max_retries`` counts *extra* engine attempts, so 0 (the default)
        means the historical behavior: one call, no retry. The surfaces opt
        in through :func:`core.engine_loader.build_default_pipeline`; keeping
        the primitive at 0 is what lets tests with deterministically failing
        stub engines stay fast and keep their call-count assertions exact.
        """
        self.engine = engine
        self._sem = asyncio.Semaphore(max_concurrent)
        self._max_retries = max(0, int(max_retries))
        self._retry_backoff = max(0.0, float(retry_backoff))

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

        if item.needs_expansion():
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
        if item.needs_expansion():
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

        if item.needs_expansion():
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
        # Count once and derive both the tallies and the status from the
        # same numbers. Previously the status was computed from ad-hoc
        # any()/any() scans while the counts stayed at their placeholder
        # values, so callers had no way to learn what actually happened.
        job.succeeded = sum(1 for r in results if r is True)
        job.failed = len(results) - job.succeeded
        # 记录失败子项的标识，供上层做子项级重试。``source_url`` 在
        # 容器展开时由 adapter 设置；没有 URL 时用 item_id 兜底。
        job.failed_items = [
            (it.platform.value, it.item_id, it.source_url or it.item_id)
            for it, r in zip(items, results)
            if r is not True
        ]
        if job.failed and not job.succeeded:
            job.status = "failed"
        else:
            job.status = "completed"  # includes partial success
        job.progress = 1.0
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
            container.extra["downloaded_count"] = 0
            container.extra["failed_count"] = 0
            container.extra["child_count"] = 0
            self._emit(on_progress, ProgressEvent(
                job_id=job_id, item=container, phase="done",
                fraction=1.0, message="Container expanded to 0 items",
            ))
            return container

        self._emit(on_progress, ProgressEvent(
            job_id=job_id, item=container, phase="expanding",
            fraction=1.0, message=f"Expanded to {len(children)} items",
        ))

        # Recurse: treat children as a fresh batch.
        #
        # The job that comes back carries the only trustworthy account of
        # what happened to the children, so it must not be discarded:
        # ``downloaded_count`` used to be ``len(children)``, i.e. the number
        # of items *attempted*, which reported a fully failed playlist as a
        # complete success. Callers (REST executor, CLI summary) read these
        # keys to build their own totals.
        child_job = await self.process_batch(children, options, on_progress=on_progress)
        container.extra["downloaded_count"] = child_job.succeeded
        container.extra["failed_count"] = child_job.failed
        container.extra["child_count"] = len(children)
        container.extra["failed_items"] = child_job.failed_items
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
        #
        # ``async with Database(...)`` instead of a hand-rolled
        # initialize()/try/finally: Database already implements the protocol,
        # and every hand-written copy of that boilerplate is another chance to
        # forget the ``finally`` -- which is exactly how pitfall #7
        # ("aiosqlite Event loop closed") comes back.
        #
        # The two DB touch points (this probe, and _record_success afterwards)
        # stay two short cycles rather than one spanning the download on
        # purpose: a transfer can run for hours, and aiosqlite backs every
        # open connection with a live thread.
        if options.database:
            try:
                from .storage.database import Database
                async with Database(options.database) as db:
                    if await db.is_downloaded(item.platform.value, item.item_id):
                        policy = getattr(options, "duplicate_policy", "skip")
                        if policy == "redownload":
                            logger.info("[%s] already in DB but policy=redownload; "
                                        "re-downloading %s/%s",
                                        job_id[:8], item.platform.value, item.item_id)
                        else:
                            logger.info("[%s] already in DB; skipping %s/%s",
                                        job_id[:8], item.platform.value, item.item_id)
                            self._emit(on_progress, ProgressEvent(
                                job_id=job_id, item=item, phase="done",
                                fraction=1.0, message="already downloaded (DB)",
                            ))
                            return True
            except Exception as exc:
                logger.debug("DB check failed (continuing): %s", exc)

        self._emit(on_progress, ProgressEvent(
            job_id=job_id, item=item, phase="downloading",
            fraction=0.0, message=f"Starting {item.source_url}",
        ))

        # Per-item cookie injection: if the caller did not pin a cookie
        # file explicitly, attach the one persisted by the platform's
        # login flow (see _resolve_platform_cookie_file). Applies only
        # to the engine call — everything downstream of the download
        # (DB / manifest / NFO) does not care about cookies.
        engine_options = options
        if options.cookies_file is None:
            cookie_file = _resolve_platform_cookie_file(item.platform)
            if cookie_file is not None:
                from dataclasses import replace as _dc_replace
                engine_options = _dc_replace(options, cookies_file=cookie_file)
                logger.debug("[%s] using %s cookies: %s",
                             job_id[:8], item.platform.value, cookie_file)

        # Retry loop. Three non-obvious rules:
        #
        # 1. A retry must trigger on ``ok is False`` too, not just on a
        #    raised exception. ``engines.yt_dlp`` funnels *every* real-world
        #    failure into ``return False``, so an exception-only retry would
        #    be dead code in production.
        # 2. The backoff sleep sits *outside* ``self._sem``. Sleeping while
        #    holding the semaphore would park a concurrency slot doing
        #    nothing for the whole backoff, starving healthy downloads.
        # 3. The engine's detailed error (``"yt-dlp error: HTTP 403"`` etc.)
        #    must not be swallowed. The engine reports it through the
        #    progress hook, so we wrap the progress callback with a
        #    closure that captures the latest error-y message into
        #    ``last_engine_error``. Without this the final event always
        #    says ``"engine returned False"`` — the GUI can't tell a 403
        #    from a timeout from a filesystem error.
        attempts = self._max_retries + 1
        ok = False
        last_error = ""
        # Shared mutable bag — the lambda closes over it, so each engine
        # attempt writes into the same box and the loop below reads it
        # after await returns. A plain ``str`` local wouldn't work because
        # ``var = "..."`` in the lambda re-binds it instead of mutating.
        last_engine_error: dict[str, str] = {"msg": ""}

        for attempt in range(1, attempts + 1):
            last_engine_error["msg"] = ""   # reset per attempt

            def _wrap_engine_progress(ev):
                # Engine-side signal of a hard failure. engines.yt_dlp emits
                # either ``"yt-dlp error: <exc>"`` (exception branch) or
                # ``"yt-dlp reported error"`` (progress-hook status=error).
                # Both precede ``return False`` and carry actionable info
                # that the generic fallback doesn't.
                if ev.message and (
                    ev.message.startswith("yt-dlp error:")
                    or ev.message.startswith("yt-dlp reported")
                ):
                    last_engine_error["msg"] = ev.message
                # Always re-emit outward: the UI needs every progress tick.
                if on_progress:
                    on_progress(ProgressEvent(
                        job_id=job_id, item=item,
                        phase="downloading", fraction=ev.fraction,
                        message=ev.message, extra=ev.extra or {},
                    ))

            async with self._sem:
                try:
                    ok = await self.engine.download(
                        item, engine_options,
                        on_progress=_wrap_engine_progress,
                    )
                    # Priority order: caller-supplied specific text > the
                    # generic placeholder. If the engine raised we'd land
                    # in the except below; if it returned False cleanly we
                    # rely on the progress-hook capture. Both branches
                    # fall through to "engine returned False" only when
                    # nothing more specific exists.
                    if ok:
                        last_error = ""
                    else:
                        last_error = (
                            last_engine_error["msg"].strip()
                            or "engine returned False"
                        )
                except Exception as exc:
                    logger.exception("[%s] engine.download raised: %s", job_id[:8], exc)
                    ok = False
                    last_error = (
                        last_engine_error["msg"].strip()
                        or f"Exception: {exc}"
                    )

            if ok:
                break

            # A stop the user requested reaches us as ``ok is False`` -- the
            # engine reports failure after swallowing its own cancellation.
            # Indistinguishable from a genuine error without this probe, and
            # retrying here would mean re-downloading what the user paused.
            if _is_cancelled(options):
                logger.info("[%s] cancelled; not retrying %s/%s",
                            job_id[:8], item.platform.value, item.item_id)
                break

            if attempt >= attempts:
                break

            delay = self._retry_backoff * (2 ** (attempt - 1))
            logger.warning("[%s] attempt %d/%d failed (%s); retrying in %.1fs",
                           job_id[:8], attempt, attempts, last_error, delay)
            # fraction=0.0 is honest: the next attempt restarts the transfer
            # (from the ``.part`` file when resume is on, but from 0% as far
            # as the engine's own progress reporting is concerned).
            self._emit(on_progress, ProgressEvent(
                job_id=job_id, item=item, phase="downloading",
                fraction=0.0,
                message=f"retrying ({attempt}/{self._max_retries}) in {delay:.0f}s: {last_error}",
                extra={"retry": attempt, "max_retries": self._max_retries,
                       "delay": delay, "reason": last_error},
            ))
            # Interruptible on purpose: ``Task.cancel()`` lands here, which is
            # how ui.task_manager stops an attempt that is between retries.
            await asyncio.sleep(delay)

        # M4: post-download persistence
        if ok:
            await self._run_post_download(item, options, job_id, on_progress)
            await self._record_success(item, options, job_id)

        self._emit(on_progress, ProgressEvent(
            job_id=job_id, item=item,
            phase="done" if ok else "failed",
            fraction=1.0 if ok else 0.0,
            message="ok" if ok else (last_error or "engine returned False"),
        ))
        return ok

    async def _run_post_download(
        self, item: MediaItem, options: DownloadOptions, job_id: str, on_progress
    ) -> None:
        """Produce the opt-in sidecars the engine cannot produce itself.

        Two kinds, both gated on their ``DownloadOptions`` switch:

        * **NFO** — platform-agnostic, generated from the MediaItem
          because yt-dlp has no NFO writer (``writeinfojson`` emits
          yt-dlp's own schema, which media libraries cannot read).
        * **Platform post-processing** — delegated to the adapter via
          the optional :meth:`PlatformAdapter.post_download` hook. B 站
          danmaku lives there because it needs a ``cid`` and a signed
          API call that only the adapter knows how to make.

        Sidecars are best-effort by design: the media file is already on
        disk, so a metadata failure must never turn a successful
        download into a failed one. Every branch therefore swallows its
        exception and only logs.
        """
        basename = item.output_template
        if options.write_nfo and basename:
            try:
                resolve_item_dir, _ = _import_file_layout()
                write_nfo = _import_nfo()
                path = write_nfo(item, resolve_item_dir(item, options), basename)
                if path is not None:
                    logger.debug("[%s] wrote NFO %s", job_id[:8], path.name)
            except Exception as exc:   # noqa: BLE001
                logger.warning("[%s] NFO generation failed: %s", job_id[:8], exc)

        # Platform-specific post-processing (danmaku, transcripts, ...).
        # PlatformRegistry.get() keys on the Platform enum, not its value.
        try:
            adapter = PlatformRegistry.get(item.platform)
        except Exception:   # noqa: BLE001
            adapter = None
        if adapter is None:
            return
        hook = getattr(adapter, "post_download", None)
        if hook is None:
            return
        # The base class defines a no-op post_download, so calling it
        # unconditionally would emit a misleading "postprocess" event on
        # every single download. Only adapters that actually override it
        # have work to do.
        if not self._overrides_post_download(adapter):
            return
        self._emit(on_progress, ProgressEvent(
            job_id=job_id, item=item, phase="postprocess",
            fraction=1.0, message="post-processing",
        ))
        try:
            await hook(item, options)
        except Exception as exc:   # noqa: BLE001
            logger.warning("[%s] post_download hook failed: %s", job_id[:8], exc)

    @staticmethod
    def _overrides_post_download(adapter: Any) -> bool:
        """True if ``adapter`` supplies its own ``post_download``.

        Compares the bound method's underlying function against the base
        class's, which is import-free and works for subclasses, mocks
        and monkeypatched instances alike.
        """
        try:
            from ..platforms.base import PlatformAdapter
        except Exception:   # noqa: BLE001
            return True     # cannot prove it's the default; let it run
        own = getattr(type(adapter), "post_download", None)
        return own is not None and own is not PlatformAdapter.post_download

    async def _record_success(
        self, item: MediaItem, options: DownloadOptions, job_id: str
    ) -> None:
        """Write the item to DB + manifest after a successful download."""
        # DB
        if options.database:
            try:
                from .storage.database import Database
                async with Database(options.database) as db:
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
