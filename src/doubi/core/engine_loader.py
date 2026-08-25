"""Default pipeline factory.

Single source of truth for "what engine + registry + config
should a fresh DouBi installation use". The CLI, the REST
server, and the MCP bridge all go through :func:`build_default_pipeline`
so behavior stays consistent across surfaces.
"""

from __future__ import annotations

from .models import DownloadOptions
from .pipeline import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_BACKOFF,
    DownloadPipeline,
)
from ..engines.yt_dlp import YtDlpEngine
from .. import platforms  # noqa: F401  -- ensure all platform adapters are registered on startup


def build_default_engine():
    """The default engine: yt-dlp.

    New engines (e.g. aria2 backend) can be selected by the user
    via config; the server / CLI defaults to yt-dlp because it
    has the broadest platform support.
    """
    return YtDlpEngine()


def build_default_pipeline(
    max_concurrent: int = 3,
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    retry_backoff: float = DEFAULT_RETRY_BACKOFF,
) -> DownloadPipeline:
    """Build a ready-to-use :class:`DownloadPipeline` with the
    default engine and all built-in platforms registered.

    Importing this function triggers the platform adapter side
    effects (``platforms.douyin`` and ``platforms.bilibili`` self-
    register on import).

    This is also where automatic retry is switched on. ``DownloadPipeline``
    itself defaults to ``max_retries=0`` (one attempt) so it stays a
    predictable primitive; the *product* behavior -- transient network
    failures should not require the user to press "retry" -- belongs to this
    factory, which every surface goes through.
    """
    return DownloadPipeline(
        engine=build_default_engine(),
        max_concurrent=max_concurrent,
        max_retries=max_retries,
        retry_backoff=retry_backoff,
    )
