"""Default pipeline factory.

Single source of truth for "what engine + registry + config
should a fresh DouBi installation use". The CLI, the REST
server, and the MCP bridge all go through :func:`build_default_pipeline`
so behavior stays consistent across surfaces.
"""

from __future__ import annotations

import logging

from .models import DownloadOptions
from .pipeline import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_BACKOFF,
    DownloadPipeline,
)
from ..engines.yt_dlp import YtDlpEngine
from .. import platforms  # noqa: F401  -- ensure all platform adapters are registered on startup

logger = logging.getLogger("doubi.core.engine_loader")


def build_default_engine(cfg=None):
    """按配置选择下载引擎。

    ``cfg`` 是 :class:`AppConfig`。``None`` 时回退到 yt-dlp（兼容老调用）。

    aria2 引擎需要外部 aria2 守护进程运行，且只对有 ``direct_url`` 的
    item 生效——它不取代 yt-dlp 的网页解析能力。选错引擎名时回退到
    yt-dlp 而不是抛错，让应用始终能起来。
    """
    engine_name = getattr(cfg, "engine", "yt-dlp") if cfg else "yt-dlp"
    if engine_name == "aria2":
        from ..engines.aria2 import Aria2Engine
        rpc_url = getattr(cfg, "aria2_rpc_url", None) or "http://127.0.0.1:6800/jsonrpc"
        secret = getattr(cfg, "aria2_secret", None)
        logger.info("使用 aria2 引擎 (RPC: %s)", rpc_url)
        return Aria2Engine(rpc_url=rpc_url, secret=secret)
    # 未知引擎名回退 yt-dlp，避免配置写错让应用起不来。
    if engine_name not in ("yt-dlp", "ytdlp", ""):
        logger.warning("未知引擎 %r，回退 yt-dlp", engine_name)
    return YtDlpEngine()


def build_default_pipeline(
    max_concurrent: int = 3,
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    retry_backoff: float = DEFAULT_RETRY_BACKOFF,
    cfg=None,
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

    ``cfg`` 传入时按 ``cfg.engine`` 选择引擎（yt-dlp / aria2）。
    """
    return DownloadPipeline(
        engine=build_default_engine(cfg),
        max_concurrent=max_concurrent,
        max_retries=max_retries,
        retry_backoff=retry_backoff,
    )
