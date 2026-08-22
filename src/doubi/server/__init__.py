"""HTTP REST surface for DouBi.

Thin FastAPI wrapper around :mod:`doubi.core.pipeline`. The server
is **stateful** in the sense that submitted jobs are tracked in
memory (via :class:`JobManager`) and survive until the configured
TTL; we deliberately don't persist them to disk so the server
is restart-safe and simple.

Endpoints:

* ``GET  /api/v1/health``         — liveness probe
* ``GET  /api/v1/platforms``      — list registered platform adapters
* ``POST /api/v1/download``       — submit a download job
* ``GET  /api/v1/jobs/{job_id}``  — query one job
* ``GET  /api/v1/jobs``           — list recent jobs

Run via ``doubi serve --host 127.0.0.1 --port 8000`` (or
``python -m doubi.server.app``).
"""

from __future__ import annotations

from .app import build_app, main, run_server

__all__ = ["build_app", "main", "run_server"]
