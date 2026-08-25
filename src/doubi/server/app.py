"""FastAPI app + CLI entry point for the DouBi REST server.

Endpoints:

    GET  /api/v1/health            — liveness probe (never authenticated)
    GET  /api/v1/platforms         — list registered platform adapters
    POST /api/v1/download          — submit a download job
    GET  /api/v1/jobs/{job_id}     — query one job
    GET  /api/v1/jobs              — list recent jobs

Usage::

    $ doubi serve --host 127.0.0.1 --port 8000

鉴权见 :mod:`doubi.server.security`。一句话：绑回环时默认不鉴权（只有本机能
连），一旦绑到别的机器也能连的地址就必须有 token，否则拒绝启动。
"""

from __future__ import annotations

import argparse
import logging
import sys
from contextlib import asynccontextmanager
from typing import Any

from .. import __version__
from ..core.config import load_config
from ..core.engine_loader import build_default_pipeline
from ..core.models import DownloadOptions
from ..core.registry import PlatformRegistry
from .. import platforms  # noqa: F401  -- ensure all platform adapters are registered on startup
from .jobs import JobManager
from .schemas import DownloadRequest
from .security import (
    TOKEN_ENV_VAR,
    InsecureBindingError,
    audit_binding,
    resolve_token,
)

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

    def _on_progress(ev: ProgressEvent) -> None:
        """Log the events that matter; accumulate nothing.

        This used to append every event to a list that nothing ever read.
        That is not merely dead code, it is an unbounded one: the engine
        emits a progress callback several times a second, so a long
        playlist would pile up tens of thousands of ProgressEvent objects
        (each holding a MediaItem) until the job finished.

        JobManager has no progress channel at all -- it only reads the
        result dict this function's caller returns -- so the only place
        per-event detail can usefully go is the log. Retry notices are
        logged at warning level because they are the one thing an operator
        watching a REST job cannot otherwise see: the job simply appears
        to hang for the duration of the backoff.
        """
        if ev.extra.get("retry"):
            logger.warning("job %s: %s", ev.item.item_id or url, ev.message)
        elif ev.phase == "failed":
            logger.warning("job %s failed: %s", ev.item.item_id or url, ev.message)

    item = await pipeline.process_url(url, options, on_progress=_on_progress)

    if item is None:
        # Parse failed, or a single-item download returned False:
        # process_url collapses both into None.
        total, succeeded, failed = 1, 0, 1
        failed_items = []
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
        failed_items = item.extra.get("failed_items") or []
    else:
        total, succeeded, failed = 1, 1, 0
        failed_items = []

    return {
        "total": total,
        "succeeded": succeeded,
        "failed": failed,
        "item_title": item.title if item else None,
        "item_author": item.author.name if item and item.author else None,
        "item_id": item.item_id if item else None,
        # 失败子项的 (platform, item_id, source_url) 列表，供客户端做
        # 子项级重试：``POST /api/v1/download`` 重新提交这些 URL 即可。
        "failed_items": failed_items,
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
        duplicate_policy=cfg.duplicate_policy,
        database=cfg.database_path if cfg.database else None,
        manifest=cfg.manifest_path,
        proxy=cfg.proxy,
        rate_limit=cfg.rate_limit,
    )


def build_app(*, token: str | None = None):
    """Build a FastAPI app bound to a default JobManager.

    Imports :mod:`fastapi` / :mod:`pydantic` lazily so the rest of
    DouBi keeps working on systems where these aren't installed.

    Args:
        token: 显式 token。为 None 时回落到 ``DOUBI_API_TOKEN`` 环境变量；
            两处都没有则本次运行不鉴权。

    鉴权是否开启由「有没有 token」单独决定，与监听地址无关。地址的安全性
    在启动入口（:func:`main` / :func:`run_server`）用
    :func:`~doubi.server.security.audit_binding` 把关——``build_app`` 自己
    不知道会被绑到哪，把两件事分开才不会出现「测试里能构造出 app、真跑起来
    却是敞口」的错位。
    """
    try:
        from fastapi import Body, Depends, FastAPI, HTTPException

        from .deps import make_token_guard
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "FastAPI is not installed. Run: pip install 'doubi[server]'"
        ) from e

    options = _build_options()
    expected_token = resolve_token(token)

    # 闸门必须来自 .deps：那里 ``Request`` 是模块级名字，注解才能被 FastAPI
    # 正确求值。定义在本函数里会因为 ``from __future__ import annotations``
    # 退化成一个必填 query 参数，让所有受保护路由变成 422。详见 deps 模块。
    #
    # 错误信息刻意不区分「没带 token」和「token 不对」，避免帮攻击者确认
    # 某个 token 是否存在。
    require_token = make_token_guard(expected_token)

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
    #: 供测试与运维自检：不暴露 token 本身，只暴露「开没开」。
    app.state.auth_enabled = expected_token is not None

    # ``/health`` 刻意不鉴权：容器编排 / 反向代理的存活探针通常无法携带
    # 凭据，而它只回 status 与版本号，没有任何可被滥用的能力。
    @app.get("/api/v1/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            # 让运维一眼看出这个实例到底有没有开鉴权，不必去翻启动参数。
            "auth_required": expected_token is not None,
        }

    @app.get("/api/v1/platforms", dependencies=[Depends(require_token)])
    async def platforms() -> dict[str, list[dict[str, Any]]]:
        items = []
        for a in PlatformRegistry.all():
            items.append({
                "name": a.name,
                "display_name": a.display_name,
                "media_types": a.supported_media_types(),
            })
        return {"platforms": items}

    @app.post("/api/v1/download", dependencies=[Depends(require_token)])
    async def create_job(req: DownloadRequest = Body(...)) -> dict[str, Any]:
        if not req.url:
            raise HTTPException(status_code=400, detail="url is required")
        job = await manager.submit(req.url)
        return job.to_dict()

    @app.get("/api/v1/jobs/{job_id}", dependencies=[Depends(require_token)])
    async def get_job(job_id: str) -> dict[str, Any]:
        job = await manager.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return job.to_dict()

    @app.get("/api/v1/jobs", dependencies=[Depends(require_token)])
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
    parser.add_argument("--host", default="127.0.0.1",
                        help="监听地址（默认 127.0.0.1，仅本机可连）")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--log-level", default="info",
                        choices=["critical", "error", "warning", "info", "debug"])
    parser.add_argument("--token", default=None,
                        help=f"API token；留空则读环境变量 {TOKEN_ENV_VAR}")
    parser.add_argument("--allow-insecure", action="store_true",
                        help="允许在没有 token 的情况下监听非回环地址（危险）")
    args = parser.parse_args(argv)

    token = resolve_token(args.token)

    # 审查放在 import uvicorn 和 build_app() **之前**：拒绝启动的路径应该
    # 尽早、尽轻地返回，不要先把 app 建起来（那会读配置、连数据库）再放弃。
    try:
        warning = audit_binding(args.host, token=token, allow_insecure=args.allow_insecure)
    except InsecureBindingError as e:
        print(str(e), file=sys.stderr)
        return 2
    if warning:
        print(f"警告: {warning}", file=sys.stderr)

    try:
        import uvicorn
    except ImportError:  # pragma: no cover
        print("uvicorn not installed. Run: pip install 'doubi[server]'", file=sys.stderr)
        return 1

    app = build_app(token=token)
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)
    return 0


async def run_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    *,
    token: str | None = None,
    allow_insecure: bool = False,
) -> None:
    """Async entry point used by the embedded REST mode.

    与 :func:`main` 走同一套安全审查。嵌入式模式（GUI 内起 REST）同样可能被
    改成绑 0.0.0.0，漏掉这里就等于留了一条绕过检查的后门。

    Raises:
        InsecureBindingError: 地址对外可达但没有鉴权，且未显式豁免。
    """
    import uvicorn

    resolved = resolve_token(token)
    warning = audit_binding(host, token=resolved, allow_insecure=allow_insecure)
    if warning:
        logger.warning(warning)

    app = build_app(token=resolved)
    uv_config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(uv_config)
    await server.serve()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
