"""0.3.3 P1-4 — MCP / REST collection tools (search + hot).

These cover the *glue* between the public MCP / REST surface and the
shared core functions in ``cli.main``. The actual fetching code is
exercised end-to-end by the existing ``tests/test_douyin_*`` suite;
here we just pin the contract:

* MCP advertises both ``collect_search`` and ``collect_hot``.
* Both have a handler.
* Both honour the shared option schema and surface them through
  ``collect_search_async`` / ``collect_hot_async``.
* REST exposes the same two paths under ``/api/v1/collect/*``.

The actual HTTP round-trip is covered by ``tests/test_server.py``; we
keep these tests narrow so they don't get dragged into the slow
fastapi-test-client startup that other tests already trigger.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def test_mcp_advertises_both_collect_tools():
    from doubi.mcp import server as mcp_server

    assert "collect_search" in mcp_server.TOOLS
    assert "collect_hot" in mcp_server.TOOLS
    # The existing test_every_advertised_tool_has_a_handler guard
    # already enforces TOOLS == _HANDLERS, but pin the new pair
    # explicitly so a future edit that *accidentally* drops the handler
    # still gets caught at this layer too.
    assert "collect_search" in mcp_server._HANDLERS
    assert "collect_hot" in mcp_server._HANDLERS


def test_cli_exposes_collect_helpers():
    from doubi.cli import main as cli_main

    assert callable(getattr(cli_main, "collect_search_async", None))
    assert callable(getattr(cli_main, "collect_hot_async", None))


def test_collect_search_handles_missing_keyword():
    from doubi.mcp import server as mcp_server

    async def _run():
        return await mcp_server._tool_collect_search({"keyword": ""})
    out = asyncio.run(_run())
    assert "error" in out
    assert "keyword" in out["error"].lower()


def test_collect_search_rejects_unknown_channel():
    from doubi.mcp import server as mcp_server

    async def _run():
        return await mcp_server._tool_collect_search(
            {"keyword": "x", "channel": "bogus"},
        )
    out = asyncio.run(_run())
    assert "error" in out
    assert "channel" in out["error"].lower()


def test_collect_search_delegates_to_shared_core(monkeypatch):
    # Capture the kwargs passed to ``collect_search_async`` so we
    # pin the contract without making a real network call.
    from doubi.cli import main as cli_main
    from doubi.mcp import server as mcp_server

    captured: dict[str, Any] = {}

    async def fake_collect_search_async(**kwargs):
        captured.update(kwargs)
        return [{"aweme_id": "abc", "title": "hi"}]

    monkeypatch.setattr(
        cli_main, "collect_search_async", fake_collect_search_async,
    )
    # The handler reads ``load_config(None)`` for cookies / proxy; mock
    # it out so the test stays isolated.
    class _Cfg:
        cookies_file = None
        proxy = None

    monkeypatch.setattr(mcp_server, "load_config", lambda *_a, **_k: _Cfg())

    async def _run():
        return await mcp_server._tool_collect_search({
            "keyword": "  hello ", "channel": "video", "max": 7,
        })
    out = asyncio.run(_run())
    assert "results" in out
    assert out["results"] == [{"aweme_id": "abc", "title": "hi"}]
    assert captured["keyword"] == "hello"     # whitespace stripped
    assert captured["channel"] == "video"
    assert captured["max_count"] == 7


def test_collect_hot_delegates_to_shared_core(monkeypatch):
    from doubi.cli import main as cli_main
    from doubi.mcp import server as mcp_server

    captured: dict[str, Any] = {}

    async def fake_collect_hot_async(**kwargs):
        captured.update(kwargs)
        return [{"word": "AI", "hot_value": 1, "board": "positive"}]

    monkeypatch.setattr(
        cli_main, "collect_hot_async", fake_collect_hot_async,
    )

    class _Cfg:
        cookies_file = None
        proxy = None

    monkeypatch.setattr(mcp_server, "load_config", lambda *_a, **_k: _Cfg())

    async def _run():
        return await mcp_server._tool_collect_hot({"board": "positive", "max": 5})
    out = asyncio.run(_run())
    assert out["board"] == "positive"
    assert out["results"][0]["word"] == "AI"
    assert captured["board"] == "positive"
    assert captured["max_count"] == 5


def test_rest_endpoints_registered():
    # The REST layer mirrors the MCP pair. Verify the routes are
    # wired into the FastAPI app without spinning up uvicorn.
    pytest = __import__("pytest")
    fastapi = pytest.importorskip("fastapi")
    from doubi.server.app import build_app

    app = build_app()
    paths = {route.path for route in app.routes if hasattr(route, "path")}
    assert "/api/v1/collect/search" in paths
    assert "/api/v1/collect/hot" in paths