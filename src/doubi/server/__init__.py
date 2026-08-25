"""HTTP REST surface for DouBi.

Thin FastAPI wrapper around :mod:`doubi.core.pipeline`. The server
is **stateful** in the sense that submitted jobs are tracked in
memory (via :class:`JobManager`) and survive until the configured
TTL; we deliberately don't persist them to disk so the server
is restart-safe and simple.

Endpoints:

* ``GET  /api/v1/health``         — liveness probe (never authenticated)
* ``GET  /api/v1/platforms``      — list registered platform adapters
* ``POST /api/v1/download``       — submit a download job
* ``GET  /api/v1/jobs/{job_id}``  — query one job
* ``GET  /api/v1/jobs``           — list recent jobs

除 ``/health`` 外的端点在配置了 token 时全部需要鉴权，见
:mod:`doubi.server.security`。默认只绑 ``127.0.0.1``；绑到本机之外可达的地址
而又没有 token 时，服务会拒绝启动。

Run via ``doubi serve --host 127.0.0.1 --port 8000`` (or
``python -m doubi.server.app``).
"""

from __future__ import annotations

# Lazy import: ``app`` -> ``schemas`` -> ``pydantic`` / ``fastapi`` is the
# heavy optional chain. Eagerly importing it here forced every consumer of
# ``doubi.server`` (including ``doubi.server.security`` which only uses
# stdlib) to require pydantic, breaking collection in environments where
# the server extras aren't installed (CI, the CLI-only path, tests of the
# security primitives). Use PEP 562 module-level ``__getattr__`` to defer
# the import until the names are actually referenced.
__all__ = ["build_app", "main", "run_server"]


def __getattr__(name: str):  # noqa: D401
    if name in {"build_app", "main", "run_server"}:
        from . import app as _app
        for _n in ("build_app", "main", "run_server"):
            globals()[_n] = getattr(_app, _n)
        return globals()[name]
    raise AttributeError(f"module 'doubi.server' has no attribute {name!r}")
