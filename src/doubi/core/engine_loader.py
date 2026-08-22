"""Default pipeline factory.

Single source of truth for "what engine + registry + config
should a fresh DouBi installation use". The CLI, the REST
server, and the MCP bridge all go through :func:`build_default_pipeline`
so behavior stays consistent across surfaces.
"""

from __future__ import annotations

from .models import DownloadOptions
from .pipeline import DownloadPipeline
from ..engines.yt_dlp import YtDlpEngine
from ..platforms import douyin, bilibili  # noqa: F401  -- ensure registration


def build_default_engine():
    """The default engine: yt-dlp.

    New engines (e.g. aria2 backend) can be selected by the user
    via config; the server / CLI defaults to yt-dlp because it
    has the broadest platform support.
    """
    return YtDlpEngine()


def build_default_pipeline(max_concurrent: int = 3) -> DownloadPipeline:
    """Build a ready-to-use :class:`DownloadPipeline` with the
    default engine and all built-in platforms registered.

    Importing this function triggers the platform adapter side
    effects (``platforms.douyin`` and ``platforms.bilibili`` self-
    register on import).
    """
    return DownloadPipeline(engine=build_default_engine(),
                             max_concurrent=max_concurrent)
