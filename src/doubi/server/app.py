"""FastAPI app + CLI entry point for the DouBi REST server.

Endpoints:

    GET  /api/v1/health            — liveness probe
    GET  /api/v1/platforms         — list registered platform adapters
    POST /api/v1/download          — submit a download job
    GET  /api/v1/jobs/{job_id}     — query one job
    GET  /api/v1/jobs              — list recent jobs

Usage::

    $ doubi serve --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from typing import Any

from .. import __version__
from ..core.config import load_config
from ..core.engine_loader import build_default_pipeline
from ..core.models import DownloadOptions
from ..core.registry import PlatformRegistry
from ..platforms import douyin, bilibili  # noqa: F401  -- ensure registration
from .jobs import JobManager
from .schemas import DownloadRequest

logger = logging.getLogger("doubi.server.app")


# ---------------------------------------------------------------------------
# Executor: a thin wrapper around the core pipeline
# ---------------------------------------------------------------------------


async def _execute_download(url: str, options: DownloadOptions) -> dict:
    """Run one URL through the pipeline; return a small result dict.

    Used by :class:`JobManager` as the per-job callable.
    """
    pipeline = build_default_pipeline()
    from ..core.pipeline import ProgressEvent
    events: list[ProgressEvent] = []

    def _on_progress(ev: ProgressEvent) -> None:
        events.append(ev)

    item = await pipeline.process_url(url, options, on_progress=_on_progress)

    if item is None:
        # Parse failed, or a single-item download returned False:
        # process_url collapses both into None.
        total, succeeded, failed = 1, 0, 1
    elif "child_count" in item.extra:
        # The pipeline took the container branch and recorded how its
        # children fared, so those numbers are the answer.
        #
        # Keying off ``extra`` rather than ``is_container()`` is deliberate:
        # ``is_container()`` is just ``bool(children)``, while the pipeline
        # also routes bare ``MediaType.USER`` items (no children yet) through
        # container expansion — the two judgements disagree. Reading the
        # stats the pipeline actually wrote cannot drift out of sync.
        #
        # The previous code went further astray: it treated
        # ``is_container()`` as *failure*, so a playlist whose every child
        # downloaded fine still reported succeeded=0 / failed=1 / total=1.
        succeeded = int(item.extra.get("downloaded_count") or 0)
        failed = int(item.extra.get("failed_count") or 0)
        total = int(item.extra.get("child_count") or 0)
    else:
        total, succeeded, failed = 1, 1, 0

    return {
        "total": total,
        "succeeded": succeeded,
        "failed": failed,
        "item_title": item.title if item else None,
        "item_author": item.author.name if item and item.author else None,
        "item_id": item.item_id if item else None,
    }


# ---------------------------------------------------------------------------
# FastAPI app builder
# ---------------------------------------------------------------------------


def _build_options() -> DownloadOptions:
    cfg = load_config(None)
    return DownloadOptions(
        output_root=cfg.output_root,
        # Same hazard as the GUI had: the directory layout, proxy and rate
        # limit are read off DownloadOptions, so anything not forwarded here
        # silently falls back to the dataclass default and the user's config
        # file appears to be ignored over REST.
        output_dir_template=cfg.output_dir_template,
        filename_template=cfg.filename_template,
        container=cfg.container,
        max_quality=cfg.max_quality,
        write_thumbnail=cfg.write_thumbnail,
        write_metadata_json=cfg.write_metadata_json,
        # The sidecar switches are honored by the engine / adapter hooks, so
        # forwarding them here is what makes them reachable over REST at all.
        write_nfo=cfg.write_nfo,
        write_danmaku=cfg.write_danmaku,
        write_subtitles=cfg.write_subtitles,
        resume=cfg.resume,
        database=cfg.database_path if cfg.database else None,
        manifest=cfg.manifest_path,
        proxy=cfg.proxy,
        rate_limit=cfg.rate_limit,
    )


def build_app():
    """Build a FastAPI app bound to a default JobManager.

    Imports :mod:`fastapi` / :mod:`pydantic` lazily so the rest of
    DouBi keeps working on systems where these aren't installed.
    """
    try:
        from fastapi import FastAPI, HTTPException, Body
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "FastAPI is not installed. Run: pip install 'doubi[server]'"
        ) from e

    options = _build_options()

    async def _executor(url: str) -> dict[str, Any]:
        return await _execute_download(url, options)

    manager = JobManager(executor=_executor, max_concurrency=2)

    @asynccontextmanager
    async def lifespan(app):
        yield
        await manager.shutdown()

    app = FastAPI(
        title="DouBi API",
        version=__version__,
        description="Multi-platform media downloader REST surface.",
        lifespan=lifespan,
    )
    app.state.job_manager = manager

    @app.get("/api/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/api/v1/platforms")
    async def platforms() -> dict[str, list[dict[str, Any]]]:
        items = []
        for a in PlatformRegistry.all():
            items.append({
                "name": a.name,
                "display_name": a.display_name,
                "media_types": a.supported_media_types(),
            })
        return {"platforms": items}

    @app.post("/api/v1/download")
    async def create_job(req: DownloadRequest = Body(...)) -> dict[str, Any]:
        if not req.url:
            raise HTTPException(status_code=400, detail="url is required")
        job = await manager.submit(req.url)
        return job.to_dict()

    @app.get("/api/v1/jobs/{job_id}")
    async def get_job(job_id: str) -> dict[str, Any]:
        job = await manager.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return job.to_dict()

    @app.get("/api/v1/jobs")
    async def list_jobs() -> dict[str, Any]:
        jobs = await manager.list_jobs()
        return {"jobs": [j.to_dict() for j in jobs]}

    return app


# ---------------------------------------------------------------------------
# Sync entry point for `doubi serve`
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="doubi-serve",
        description="Run the DouBi REST server.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--log-level", default="info",
                        choices=["critical", "error", "warning", "info", "debug"])
    args = parser.parse_args(argv)

    try:
        import uvicorn
    except ImportError:  # pragma: no cover
        print("uvicorn not installed. Run: pip install 'doubi[server]'", file=sys.stderr)
        return 1

    app = build_app()
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)
    return 0


async def run_server(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Async entry point used by the embedded REST mode."""
    import uvicorn
    app = build_app()
    uv_config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(uv_config)
    await server.serve()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
