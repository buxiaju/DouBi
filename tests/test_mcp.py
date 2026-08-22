"""Tests for the M6 MCP stdio bridge.

We don't spin up a real stdio transport (that's tested by hand
with Claude Desktop). Instead, we test the JSON-RPC dispatcher
directly: call :func:`_dispatch` with crafted request dicts and
verify the responses.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from doubi.mcp import server as mcp_server  # noqa: E402


# ---------------------------------------------------------------------------
# initialize / tools/list
# ---------------------------------------------------------------------------


def test_initialize_returns_protocol_version():
    async def _run():
        return await mcp_server._dispatch({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
        })
    resp = asyncio.run(_run())
    assert resp["id"] == 1
    assert "result" in resp
    assert resp["result"]["serverInfo"]["name"] == "doubi"
    assert "protocolVersion" in resp["result"]


def test_tools_list_includes_all_registered():
    async def _run():
        return await mcp_server._dispatch({
            "jsonrpc": "2.0", "id": 2, "method": "tools/list",
        })
    resp = asyncio.run(_run())
    names = {t["name"] for t in resp["result"]["tools"]}
    assert names == {"platforms", "parse_url", "add_to_queue", "get_status", "list_jobs"}


def test_unknown_method_returns_error():
    async def _run():
        return await mcp_server._dispatch({
            "jsonrpc": "2.0", "id": 3, "method": "no/such/method",
        })
    resp = asyncio.run(_run())
    assert "error" in resp
    assert resp["error"]["code"] == -32601


def test_invalid_jsonrpc_version_returns_error():
    async def _run():
        return await mcp_server._dispatch({
            "jsonrpc": "1.0", "id": 4, "method": "tools/list",
        })
    resp = asyncio.run(_run())
    assert "error" in resp
    assert resp["error"]["code"] == -32600


def test_notification_returns_none():
    async def _run():
        return await mcp_server._dispatch({
            "jsonrpc": "2.0", "method": "some/notification",
        })
    resp = asyncio.run(_run())
    assert resp is None


# ---------------------------------------------------------------------------
# tools/call — platform
# ---------------------------------------------------------------------------


def test_call_platforms_returns_douyin_and_bilibili():
    async def _run():
        return await mcp_server._dispatch({
            "jsonrpc": "2.0", "id": 10, "method": "tools/call",
            "params": {"name": "platforms", "arguments": {}},
        })
    resp = asyncio.run(_run())
    assert "result" in resp
    payload = json.loads(resp["result"]["content"][0]["text"])
    names = {p["name"] for p in payload["platforms"]}
    assert "douyin" in names
    assert "bilibili" in names


def test_call_parse_url_missing_argument_returns_error_in_content():
    async def _run():
        return await mcp_server._dispatch({
            "jsonrpc": "2.0", "id": 11, "method": "tools/call",
            "params": {"name": "parse_url", "arguments": {}},
        })
    resp = asyncio.run(_run())
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert "error" in payload
    assert "url" in payload["error"]


def test_call_parse_url_unknown_returns_error_in_content():
    async def _run():
        return await mcp_server._dispatch({
            "jsonrpc": "2.0", "id": 12, "method": "tools/call",
            "params": {"name": "parse_url", "arguments": {"url": "https://example.com/x"}},
        })
    resp = asyncio.run(_run())
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert "error" in payload
    assert "no platform matches" in payload["error"]


def test_call_parse_url_bilibili_succeeds():
    from doubi.platforms.bilibili.adapter import BilibiliAdapter

    async def _fake_parse(self, url):
        from doubi.core.models import MediaItem, MediaType, Platform, Author
        return MediaItem(
            platform=Platform.BILIBILI, item_id="BV1xx411c7mD", title="测试",
            author=Author(name="UP"), media_type=MediaType.VIDEO, source_url=url,
        )
    original = BilibiliAdapter.parse
    BilibiliAdapter.parse = _fake_parse
    try:
        async def _run():
            return await mcp_server._dispatch({
                "jsonrpc": "2.0", "id": 13, "method": "tools/call",
                "params": {"name": "parse_url",
                           "arguments": {"url": "https://www.bilibili.com/video/BV1xx"}},
            })
        resp = asyncio.run(_run())
        payload = json.loads(resp["result"]["content"][0]["text"])
        assert payload["platform"] == "bilibili"
        assert payload["item_id"] == "BV1xx411c7mD"
        assert payload["title"] == "测试"
    finally:
        BilibiliAdapter.parse = original


# ---------------------------------------------------------------------------
# tools/call — add_to_queue
# ---------------------------------------------------------------------------


def test_call_add_to_queue_with_missing_url_returns_error():
    async def _run():
        return await mcp_server._dispatch({
            "jsonrpc": "2.0", "id": 20, "method": "tools/call",
            "params": {"name": "add_to_queue", "arguments": {}},
        })
    resp = asyncio.run(_run())
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert "error" in payload


def test_call_add_to_queue_with_unknown_url_reports_failed(monkeypatch):
    async def _run():
        return await mcp_server._dispatch({
            "jsonrpc": "2.0", "id": 21, "method": "tools/call",
            "params": {"name": "add_to_queue",
                       "arguments": {"url": "https://example.com/x"}},
        })
    resp = asyncio.run(_run())
    payload = json.loads(resp["result"]["content"][0]["text"])
    # We don't fail outright — the call returns a job record with
    # status="failed" because no platform matched.
    assert payload["status"] == "failed"
    assert "job_id" in payload


def test_call_get_status_unknown_job():
    async def _run():
        return await mcp_server._dispatch({
            "jsonrpc": "2.0", "id": 30, "method": "tools/call",
            "params": {"name": "get_status",
                       "arguments": {"job_id": "no-such-id"}},
        })
    resp = asyncio.run(_run())
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert "error" in payload
    assert "not found" in payload["error"]


def test_call_list_jobs_empty():
    async def _run():
        # Reset job store (note: not thread-safe; tests run serially)
        mcp_server._JOBS.clear()
        return await mcp_server._dispatch({
            "jsonrpc": "2.0", "id": 40, "method": "tools/call",
            "params": {"name": "list_jobs", "arguments": {}},
        })
    resp = asyncio.run(_run())
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["jobs"] == []


def test_call_unknown_tool_returns_error():
    async def _run():
        return await mcp_server._dispatch({
            "jsonrpc": "2.0", "id": 50, "method": "tools/call",
            "params": {"name": "no_such_tool", "arguments": {}},
        })
    resp = asyncio.run(_run())
    assert "error" in resp
    assert resp["error"]["code"] == -32601


def test_tool_handler_exception_is_caught(monkeypatch):
    """A raising tool handler returns isError=True, not a crash."""
    def _raise(arguments):
        raise RuntimeError("tool exploded")
    monkeypatch.setitem(mcp_server._HANDLERS, "platforms", _raise)

    async def _run():
        return await mcp_server._dispatch({
            "jsonrpc": "2.0", "id": 60, "method": "tools/call",
            "params": {"name": "platforms", "arguments": {}},
        })
    resp = asyncio.run(_run())
    assert resp["result"]["isError"] is True
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert "tool exploded" in payload["error"]
