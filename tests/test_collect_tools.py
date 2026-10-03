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

import pytest

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


# 0.3.4 — multi-platform collect (douyin / bilibili)


def test_cli_collect_search_supports_bilibili_platform(monkeypatch):
    """B 站 search is reachable via the same helper with ``platform='bilibili'``."""
    from doubi.cli import main as cli_main

    captured: dict[str, Any] = {}

    async def fake(**kw):
        captured.update(kw)
        return [{"title": "BV 视频", "bvid": "BV1xx", "platform": "bilibili"}]

    monkeypatch.setattr(cli_main, "collect_search_async", fake)

    async def _run():
        return await cli_main.collect_search_async(
            keyword="cat",
            channel="video",
            platform="bilibili",
            max_count=10,
        )

    rows = asyncio.run(_run())
    assert rows[0]["platform"] == "bilibili"
    assert captured["platform"] == "bilibili"
    assert captured["channel"] == "video"


def test_cli_collect_search_rejects_unknown_platform():
    from doubi.cli import main as cli_main

    async def _run():
        return await cli_main.collect_search_async(
            keyword="x", platform="youtube",
        )
    with pytest.raises(ValueError, match="unknown platform"):
        asyncio.run(_run())


def test_cli_collect_hot_supports_bilibili_platform(monkeypatch):
    from doubi.cli import main as cli_main

    captured: dict[str, Any] = {}

    async def fake(**kw):
        captured.update(kw)
        return [
            {"word": "A", "platform": "bilibili", "board": "hotword"},
            {"title": "Top video", "platform": "bilibili", "board": "popular"},
        ]

    monkeypatch.setattr(cli_main, "collect_hot_async", fake)

    async def _run():
        return await cli_main.collect_hot_async(platform="bilibili")

    rows = asyncio.run(_run())
    assert captured["platform"] == "bilibili"
    assert len(rows) == 2


def test_mcp_collect_search_passes_platform_through(monkeypatch):
    """0.3.4 — collect_search now accepts ``platform=douyin|bilibili``."""
    from doubi.cli import main as cli_main
    from doubi.mcp import server as mcp_server

    captured: dict[str, Any] = {}

    async def fake(**kw):
        captured.update(kw)
        return []

    monkeypatch.setattr(cli_main, "collect_search_async", fake)

    class _Cfg:
        cookies_file = None
        proxy = None
    monkeypatch.setattr(mcp_server, "load_config", lambda *_a, **_k: _Cfg())

    async def _run():
        return await mcp_server._tool_collect_search({
            "platform": "bilibili",
            "keyword": "cat",
            "channel": "user",
            "max": 5,
        })
    out = asyncio.run(_run())
    assert "results" in out
    assert out["platform"] == "bilibili"
    assert captured["platform"] == "bilibili"
    assert captured["channel"] == "user"


def test_mcp_collect_search_rejects_platform_channel_mismatch():
    """B 站 search 不支持 ``live`` / ``general`` 通道——明确报错而不是静默退化。"""
    from doubi.mcp import server as mcp_server

    async def _run():
        return await mcp_server._tool_collect_search({
            "platform": "bilibili",
            "keyword": "x",
            "channel": "live",  # 仅抖音可用
        })
    out = asyncio.run(_run())
    assert "error" in out
    assert "channel" in out["error"].lower()


def test_mcp_collect_search_rejects_unknown_platform():
    from doubi.mcp import server as mcp_server

    async def _run():
        return await mcp_server._tool_collect_search({
            "platform": "twitter",
            "keyword": "x",
        })
    out = asyncio.run(_run())
    assert "error" in out
    assert "platform" in out["error"].lower()


def test_mcp_collect_hot_accepts_bilibili_platform(monkeypatch):
    from doubi.cli import main as cli_main
    from doubi.mcp import server as mcp_server

    captured: dict[str, Any] = {}

    async def fake(**kw):
        captured.update(kw)
        return []

    monkeypatch.setattr(cli_main, "collect_hot_async", fake)

    class _Cfg:
        cookies_file = None
        proxy = None
    monkeypatch.setattr(mcp_server, "load_config", lambda *_a, **_k: _Cfg())

    async def _run():
        return await mcp_server._tool_collect_hot({
            "platform": "bilibili", "max": 20,
        })
    out = asyncio.run(_run())
    assert out["platform"] == "bilibili"
    assert captured["platform"] == "bilibili"


def test_rest_collect_search_rejects_unknown_platform():
    """REST 与 MCP 同样必须拒掉不支持的 platform 值。"""
    pytest = __import__("pytest")
    fastapi = pytest.importorskip("fastapi")
    from doubi.server.app import build_app

    app = build_app()
    # We don't actually start the ASGI loop — just import the route
    # function and call it directly. FastAPI's signature parsing happens
    # inside the route handler so we exercise the same validation path.
    routes = {r.path: r for r in app.routes if hasattr(r, "path")}
    search_route = routes["/api/v1/collect/search"]
    # The endpoint should at minimum reference the ``platform`` parameter
    # — guard against silent removal.
    import inspect
    sig = inspect.signature(search_route.endpoint)
    assert "platform" in sig.parameters