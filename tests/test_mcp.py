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
    # 用 == 而非 >= 是刻意的：新增工具时这里必须同步更新，删掉工具时也会立刻变红。
    assert names == {
        "platforms", "parse_url", "add_to_queue", "get_status", "list_jobs",
        "sniff_status", "list_supported_sites",   # M6.17+ 暴露 yt-dlp 1800+ extractor
        "collect_search", "collect_hot",          # 0.3.3 P1-4：采集能力对上 CLI
    }


def test_every_advertised_tool_has_a_handler():
    """``tools/list`` 宣告的每个工具都必须在 ``_HANDLERS`` 里有实现。

    历史坑：往 ``TOOLS`` 加了描述却忘了注册 handler，客户端能看到工具、一调用就
    报 method not found。两张表必须严格同集。
    """
    assert set(mcp_server.TOOLS) == set(mcp_server._HANDLERS)


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


def test_call_parse_url_unknown_returns_ytdlp_error(monkeypatch):
    """不认识的 URL 现在先走 ytdlp_generic（M6.17+）——yt-dlp 也解析不了时
    返回带 ``error`` 字段的失败 payload，pipeline 不再自动 chain 到 generic 嗅探。

    行为变化：

    * M6.16: registry.detect → generic (priority=-1) → sniff 失败 → 错误 item
    * M6.17+: registry.detect → ytdlp_generic (priority=-1) → yt-dlp DownloadError → 返回 ``{"error": "..."}``

    0.3.3 修：本用例原先拿 ``https://example.com/x`` 真跑 yt-dlp，靠真实网络
    请求失败来凑出 ``error``。网络被黑洞时整个全量跑挂死在这里（实测 >2min
    无返回），而且绿灯与否取决于当时能不能连上 example.com。这里把 yt-dlp
    换成「一进 with 就抛 DownloadError」的桩，断言的仍是它真正想验证的那条
    链路：yt-dlp 解析失败 ⇒ 返回 error 字段。
    """
    import yt_dlp

    class _BoomYDL:
        def __init__(self, opts):        # noqa: ARG002 - 对齐真实签名即可
            pass

        def __enter__(self):
            raise yt_dlp.utils.DownloadError("simulated: 无法解析该 URL")

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(yt_dlp, "YoutubeDL", _BoomYDL)

    async def _run():
        return await mcp_server._dispatch({
            "jsonrpc": "2.0", "id": 12, "method": "tools/call",
            "params": {"name": "parse_url", "arguments": {"url": "https://example.com/x"}},
        })
    resp = asyncio.run(_run())
    payload = json.loads(resp["result"]["content"][0]["text"])
    # ytdlp_generic 解析失败 → 返回 error 字段（不是 MediaItem payload）
    assert "error" in payload, (
        f"M6.17+ ytdlp_generic 解析失败应返回 error 字段，实际 {payload!r}"
    )


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
    # 0.3.3 修：本用例原先收了 monkeypatch 却一次没用——`example.com` 会命中
    # ytdlp_generic（它的 match_url 永真，见 registry 兜底链），于是真的发起一次
    # yt-dlp 网络请求；"failed" 只是真请求报错后的副产物。网络被黑洞时整个全量
    # 跑会挂死在这里（实测 >2min 无返回），而且绿灯与否取决于当时的网络。
    import yt_dlp

    class _BoomYDL:
        def __init__(self, opts):        # noqa: ARG002 - 对齐真实签名即可
            pass

        def __enter__(self):
            raise yt_dlp.utils.DownloadError("simulated: 无法解析该 URL")

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(yt_dlp, "YoutubeDL", _BoomYDL)

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


# ===========================================================================
# list_supported_sites (M6.17+)
# ===========================================================================


def test_call_list_supported_sites_returns_both_lists():
    """list_supported_sites 同时返回内置适配器和 yt-dlp extractor 列表。"""
    async def _run():
        return await mcp_server._dispatch({
            "jsonrpc": "2.0", "id": 70, "method": "tools/call",
            "params": {"name": "list_supported_sites", "arguments": {}},
        })
    resp = asyncio.run(_run())
    payload = json.loads(resp["result"]["content"][0]["text"])
    # 4 个内置适配器：douyin / bilibili / youtube / ytdlp
    names = {a["name"] for a in payload["builtin_adapters"]}
    assert {"douyin", "bilibili", "youtube", "ytdlp"}.issubset(names)
    # yt-dlp 列表非空，且 extractor 数量 > 1000（保守）
    assert payload["ytdlp_extractor_count"] > 1000
    assert len(payload["ytdlp_extractors"]) == payload["ytdlp_extractor_count"]
    # 第一个 extractor 至少有 name / host 字段
    sample = payload["ytdlp_extractors"][0]
    assert "name" in sample and "host" in sample


def test_call_list_supported_sites_filter_narrows_results():
    """``filter`` 关键字按 name/host 过滤 yt-dlp extractor 列表。"""
    async def _run():
        return await mcp_server._dispatch({
            "jsonrpc": "2.0", "id": 71, "method": "tools/call",
            "params": {"name": "list_supported_sites",
                       "arguments": {"filter": "twitter"}},
        })
    resp = asyncio.run(_run())
    payload = json.loads(resp["result"]["content"][0]["text"])
    # 至少命中 1 条 Twitter 相关
    assert payload["ytdlp_extractor_count"] >= 1
    for e in payload["ytdlp_extractors"]:
        combined = (e.get("name", "") + e.get("host", "") + e.get("description", "")).lower()
        assert "twitter" in combined, f"filter 没过滤掉 {e}"


def test_call_list_supported_sites_caches_within_process(monkeypatch):
    """同一进程多次调用应命中缓存（不再遍历 yt_dlp.list_extractors）。

    验证手法：把 ``yt_dlp.list_extractors`` mock 成 ``call_count`` 自增的
    函数——第二次调用 list_supported_sites 不应再触发它。
    """
    import yt_dlp as _yt
    call_count = {"n": 0}

    real = _yt.list_extractors

    def counting_list_extractors():
        call_count["n"] += 1
        yield from real()

    monkeypatch.setattr(_yt, "list_extractors", counting_list_extractors)
    # 重置缓存：上一次单测已经把真实 list_extractors 跑过了，缓存非空，
    # 后续测试会直接命中缓存——这次我们要测的是「缓存命中后不再调」。
    mcp_server._YT_EXTRACTORS_CACHE = None

    payload1 = _call_list_supported_sites_sync()
    payload2 = _call_list_supported_sites_sync()
    # list_extractors 只应被第一次调用触发（建立缓存）；第二次直接命中
    assert call_count["n"] == 1, (
        f"缓存未生效，list_extractors 被调用 {call_count['n']} 次"
    )
    # 两次返回的 extractor 数量 / 内容相同（json.dumps/loads 丢失 object identity，
    # 所以这里用 == 比较语义而不是 is 比较身份）
    assert payload1["ytdlp_extractor_count"] == payload2["ytdlp_extractor_count"]
    assert len(payload1["ytdlp_extractors"]) == len(payload2["ytdlp_extractors"])


def _call_list_supported_sites_sync() -> dict:
    """测试用 helper：同步触发 list_supported_sites 工具，返回 payload dict。"""
    async def _run():
        return await mcp_server._dispatch({
            "jsonrpc": "2.0", "id": 80, "method": "tools/call",
            "params": {"name": "list_supported_sites", "arguments": {}},
        })
    resp = asyncio.run(_run())
    return json.loads(resp["result"]["content"][0]["text"])
