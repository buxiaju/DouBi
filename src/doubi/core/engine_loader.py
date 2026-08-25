"""Default pipeline factory.

Single source of truth for "what engine + registry + config
should a fresh DouBi installation use". The CLI, the REST
server, and the MCP bridge all go through :func:`build_default_pipeline`
so behavior stays consistent across surfaces.
"""

from __future__ import annotations

import logging

from .. import platforms  # noqa: F401  -- ensure all platform adapters are registered on startup
from ..engines.direct_http import DirectHttpEngine
from ..engines.m3u8 import M3u8Engine
from ..engines.yt_dlp import YtDlpEngine
from .pipeline import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_BACKOFF,
    DownloadPipeline,
)

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


def build_extra_engines() -> list:
    """构建引擎路由的额外引擎列表。

    顺序决定优先级——越靠前越先匹配：
    1. Nm3u8dlEngine — 首选，基于 N_m3u8DL-CLI 原生二进制（支持 AES-128 / ChaCha20 / master playlist）
    2. M3u8Engine — 备选，基于 ffmpeg（ffmpeg 优先，aiohttp 兜底）
    3. DirectHttpEngine — 处理直链视频文件（.mp4 / .webm 等）

    这些引擎在 pipeline._select_engine 中被依次尝试，
    都不命中时回退到默认引擎（yt-dlp / aria2）。
    """
    engines = []
    try:
        from ..engines.nm3u8dl import Nm3u8dlEngine
        nm = Nm3u8dlEngine()
        if nm.is_available:
            engines.append(nm)
            logger.info("Nm3u8dlEngine 就绪")
        else:
            logger.info("Nm3u8dlEngine 未找到二进制，跳过")
    except Exception as exc:  # pragma: no cover
        logger.warning("Nm3u8dlEngine 初始化失败: %s", exc)
    try:
        engines.append(M3u8Engine())
    except Exception as exc:  # pragma: no cover
        logger.warning("M3u8Engine 初始化失败: %s", exc)
    try:
        engines.append(DirectHttpEngine())
    except Exception as exc:  # pragma: no cover
        logger.warning("DirectHttpEngine 初始化失败: %s", exc)
    return engines


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
    同时组装额外引擎列表（M3u8Engine / DirectHttpEngine）用于
    generic sniff 场景的引擎路由。
    """
    return DownloadPipeline(
        engine=build_default_engine(cfg),
        max_concurrent=max_concurrent,
        max_retries=max_retries,
        retry_backoff=retry_backoff,
        extra_engines=build_extra_engines(),
    )
