"""Tests for M6.49 抖音 search: 4 endpoints (general / video / user / live).

Adapter-layer tests cover param shape + filter URL-encoding + dedup.
The transport (httpx) is mocked via ``_request_json`` monkey-patching so
no real network traffic — the platform's search endpoints are subject
to the M6.48 signing layer (msToken + WebSign) and a regression in
M6.48 would cascade into these tests.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from doubi.platforms.douyin.webapi import DouyinWebAPI  # noqa: E402
from doubi.platforms.douyin.sign import DOUYIN_SIGNED_PATHS  # noqa: E402


def _aweme_row(aweme_id: str) -> dict:
    """Aweme-shaped row the search endpoints return."""
    return {"aweme_id": aweme_id, "desc": f"title-{aweme_id}"}


def _user_row(uid: str, sec_uid: str = "") -> dict:
    return {"user_id": uid, "sec_uid": sec_uid or f"sec_{uid}", "nickname": f"user-{uid}"}


def _live_row(room_id: str) -> dict:
    # TikTokDL wraps each row in {lives: [...]} for live search
    return {"lives": [{"room_id": room_id, "title": f"live-{room_id}"}]}


def _make_page(
    data_key: str,
    rows: list[dict],
    *,
    has_more: bool = False,
    cursor: int | None = None,
) -> dict:
    """Synthesize the page dict shape ``_search_paginate`` consumes."""
    page: dict = {
        data_key: rows,
        "cursor": cursor if cursor is not None else 0,
        "has_more": has_more,
    }
    if has_more:
        # log_pb.impr_id is how TikTokDL tracks the next-page token
        page["log_pb"] = {"impr_id": "abc123"}
    return page


# ---------------------------------------------------------------------------
# search_general
# ---------------------------------------------------------------------------


async def test_search_general_calls_general_endpoint_with_keyword(monkeypatch):
    api = DouyinWebAPI()
    captured: dict = {}

    async def _fake(endpoint, params, *, max_retries=3, error_sink=None):
        captured["endpoint"] = endpoint
        captured["params"] = params
        return _make_page("data", [_aweme_row("111")])

    monkeypatch.setattr(api, "_request_json", _fake)

    results = await api.search_general("python")
    assert captured["endpoint"] == "/aweme/v1/web/general/search/single/"
    assert captured["params"]["keyword"] == "python"
    assert captured["params"]["search_channel"] == "aweme_general"
    # version_code for general = 19.6.0 (TikTokDL line 267)
    assert captured["params"]["version_code"] == "190600"
    assert captured["params"]["version_name"] == "19.6.0"
    # No filter active -> is_filter_search stays at "0"
    assert captured["params"]["is_filter_search"] == "0"
    # ``filter_selected`` is omitted when no filter is active
    assert "filter_selected" not in captured["params"]
    assert len(results) == 1


async def test_search_general_encodes_filter_selected(monkeypatch):
    """When any filter is active, ``filter_selected`` must be a
    percent-encoded JSON string and ``is_filter_search`` must flip to 1."""
    api = DouyinWebAPI()
    captured: dict = {}

    async def _fake(endpoint, params, *, max_retries=3, error_sink=None):
        captured["params"] = params
        return _make_page("data", [])

    monkeypatch.setattr(api, "_request_json", _fake)

    await api.search_general(
        "python", sort_type=1, publish_time=7, duration=2,
    )
    p = captured["params"]
    assert p["is_filter_search"] == "1"
    assert "filter_selected" in p
    decoded = json.loads(unquote(p["filter_selected"]))
    assert decoded == {
        "sort_type": "1",
        "publish_time": "7",
        "filter_duration": "2",
        "search_range": "0",
        "content_type": "0",
    }


async def test_search_general_paginates_via_search_id(monkeypatch):
    """Page 2 must carry the ``search_id`` returned in page 1's log_pb."""
    api = DouyinWebAPI()
    page_n = {"n": 0}
    captured: list[dict] = []

    async def _fake(endpoint, params, *, max_retries=3, error_sink=None):
        captured.append(dict(params))
        page_n["n"] += 1
        if page_n["n"] == 1:
            return _make_page(
                "data", [_aweme_row("1")], has_more=True, cursor=10,
            )
        # Page 2: no more
        return _make_page("data", [_aweme_row("2")])

    monkeypatch.setattr(api, "_request_json", _fake)

    results = await api.search_general("k", count=10, max_count=10)
    assert len(results) == 2
    assert "search_id" not in captured[0]  # first page has no prior search_id
    assert captured[1]["search_id"] == "abc123"
    assert captured[1]["offset"] == 10


async def test_search_general_dedupes_by_aweme_id(monkeypatch):
    """Platform echoes the same row across pages; dedupe by aweme_id."""
    api = DouyinWebAPI()
    page_n = {"n": 0}

    async def _fake(endpoint, params, *, max_retries=3, error_sink=None):
        page_n["n"] += 1
        if page_n["n"] == 1:
            return _make_page(
                "data", [_aweme_row("1"), _aweme_row("2")], has_more=True, cursor=10,
            )
        return _make_page("data", [_aweme_row("2"), _aweme_row("3")])

    monkeypatch.setattr(api, "_request_json", _fake)

    results = await api.search_general("k", count=10, max_count=5)
    assert [r["aweme_id"] for r in results] == ["1", "2", "3"]


# ---------------------------------------------------------------------------
# search_video
# ---------------------------------------------------------------------------


async def test_search_video_endpoint_and_filter_pieces(monkeypatch):
    api = DouyinWebAPI()
    captured: dict = {}

    async def _fake(endpoint, params, *, max_retries=3, error_sink=None):
        captured["endpoint"] = endpoint
        captured["params"] = params
        return _make_page("data", [_aweme_row("v1")])

    monkeypatch.setattr(api, "_request_json", _fake)

    results = await api.search_video(
        "tutorial", sort_type=1, publish_time=7, duration=3, search_range=2,
    )
    assert captured["endpoint"] == "/aweme/v1/web/search/item/"
    assert captured["params"]["search_channel"] == "aweme_video_web"
    # version_code for video = 17.4.0 (TikTokDL line 296)
    assert captured["params"]["version_code"] == "170400"
    # ``search_video`` does NOT use ``filter_selected`` JSON — it
    # spreads each filter into its own param (TikTokDL lines 301-320).
    assert "filter_selected" not in captured["params"]
    assert captured["params"]["sort_type"] == "1"
    assert captured["params"]["publish_time"] == "7"
    assert captured["params"]["filter_duration"] == "3"
    assert captured["params"]["search_range"] == "2"
    assert captured["params"]["is_filter_search"] == "1"
    assert len(results) == 1


async def test_search_video_no_filter_does_not_set_filter_params(monkeypatch):
    api = DouyinWebAPI()
    captured: dict = {}

    async def _fake(endpoint, params, *, max_retries=3, error_sink=None):
        captured["params"] = params
        return _make_page("data", [])

    monkeypatch.setattr(api, "_request_json", _fake)
    await api.search_video("k")
    assert "sort_type" not in captured["params"]
    assert "publish_time" not in captured["params"]
    assert "filter_duration" not in captured["params"]
    assert "search_range" not in captured["params"]
    assert captured["params"]["is_filter_search"] == "0"


# ---------------------------------------------------------------------------
# search_user
# ---------------------------------------------------------------------------


async def test_search_user_uses_user_list_data_key(monkeypatch):
    api = DouyinWebAPI()
    captured: dict = {}

    async def _fake(endpoint, params, *, max_retries=3, error_sink=None):
        captured["endpoint"] = endpoint
        captured["params"] = params
        # user search data_key is "user_list", not "data"
        return _make_page("user_list", [_user_row("u1", "sec1")])

    monkeypatch.setattr(api, "_request_json", _fake)

    results = await api.search_user("美食")
    assert captured["endpoint"] == "/aweme/v1/web/discover/search/"
    assert captured["params"]["search_channel"] == "aweme_user_web"
    assert len(results) == 1
    assert results[0]["sec_uid"] == "sec1"


async def test_search_user_filter_serializes_user_type_lists(monkeypatch):
    """``fans`` and ``user_type`` map to ``search_filter_value`` with
    *list-of-strings* values (TikTokDL line 121-131), not raw integers."""
    api = DouyinWebAPI()
    captured: dict = {}

    async def _fake(endpoint, params, *, max_retries=3, error_sink=None):
        captured["params"] = params
        return _make_page("user_list", [])

    monkeypatch.setattr(api, "_request_json", _fake)

    await api.search_user("food", fans=3, user_type=2)
    p = captured["params"]
    assert p["is_filter_search"] == "1"
    assert "search_filter_value" in p
    decoded = json.loads(unquote(p["search_filter_value"]))
    # douyin_user_fans=3 → "1w_10w"; douyin_user_type=2 → "enterprise_user"
    assert decoded["douyin_user_fans"] == ["1w_10w"]
    assert decoded["douyin_user_type"] == ["enterprise_user"]


# ---------------------------------------------------------------------------
# search_live
# ---------------------------------------------------------------------------


async def test_search_live_unwraps_lives_wrapper(monkeypatch):
    """Live search wraps items as ``{lives: [...]}``; we must unwrap to
    get the actual room dict (TikTokDL ``append_response_video:395``)."""
    api = DouyinWebAPI()
    captured: dict = {}

    async def _fake(endpoint, params, *, max_retries=3, error_sink=None):
        captured["endpoint"] = endpoint
        captured["params"] = params
        return _make_page("data", [_live_row("r1"), _live_row("r2")])

    monkeypatch.setattr(api, "_request_json", _fake)

    results = await api.search_live("唱歌")
    assert captured["endpoint"] == "/aweme/v1/web/live/search/"
    assert captured["params"]["search_channel"] == "aweme_live"
    assert len(results) == 2
    assert {r["room_id"] for r in results} == {"r1", "r2"}


# ---------------------------------------------------------------------------
# Cross-cutting: protected-paths whitelist + max_pages hard stop
# ---------------------------------------------------------------------------


def test_all_four_search_endpoints_are_in_websign_whitelist():
    """Search endpoints must trigger WebSign (M6.48 dependency)."""
    assert "/aweme/v1/web/general/search/single/" in DOUYIN_SIGNED_PATHS
    assert "/aweme/v1/web/search/item/" in DOUYIN_SIGNED_PATHS
    assert "/aweme/v1/web/discover/search/" in DOUYIN_SIGNED_PATHS
    assert "/aweme/v1/web/live/search/" in DOUYIN_SIGNED_PATHS


async def test_search_pagination_hard_stops_at_max_pages(monkeypatch):
    """If the platform reports has_more=True forever (we saw this in
    the wild), the hard ``max_pages`` cap prevents an infinite loop."""
    api = DouyinWebAPI()
    call_count = {"n": 0}

    async def _fake(endpoint, params, *, max_retries=3, error_sink=None):
        call_count["n"] += 1
        # Always say "more" with no log_pb to keep search_id from updating
        return _make_page("data", [_aweme_row(f"id-{call_count['n']}")],
                         has_more=True, cursor=call_count["n"] * 10)

    monkeypatch.setattr(api, "_request_json", _fake)

    # max_count never satisfied because each page returns 1 fresh row,
    # but the inner cap (default 50) must stop us.
    results = await api.search_general("k", count=10, max_count=10000)
    # Internal default max_pages = 50, so we must have stopped at 50 calls
    assert call_count["n"] == 50, (
        f"expected hard cap at 50 pages, got {call_count['n']}"
    )
    assert len(results) == 50


async def test_search_propagates_error_sink(monkeypatch):
    """WebAPI risk-control hints (M6.46) must flow into error_sink."""
    api = DouyinWebAPI()

    async def _fake(endpoint, params, *, max_retries=3, error_sink=None):
        # Simulate 403 from webapi._request_json's perspective: it would
        # write to error_sink before returning {}. Here we mimic that.
        if error_sink is not None:
            error_sink.clear()
            error_sink["reason"] = "HTTP 403"
            error_sink["status_code"] = 403
            error_sink["hint"] = "need_login"
        return {}

    monkeypatch.setattr(api, "_request_json", _fake)

    sink: dict = {}
    results = await api.search_general("k", error_sink=sink)
    assert results == []
    assert sink["hint"] == "need_login"
