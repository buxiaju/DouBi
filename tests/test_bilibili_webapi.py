"""0.3.4 — B 站 search / hot / popular webapi tests.

The webapi layer does pure httpx I/O. We mock ``httpx.AsyncClient`` so
no test here ever touches the real network. Each test stubs one HTTP
response shape and asserts the normalised record schema.

Covered:

* :class:`BilibiliWebAPI.search` (video / user channels, error paths)
* :class:`BilibiliWebAPI.get_hotword`
* :class:`BilibiliWebAPI.get_popular`
* :class:`BilibiliWebAPI.get_ranking`
* cookie filtering (only ``.bilibili.com`` cookies get attached)
* WBI signing applied (URL has ``wts`` + ``w_rid`` query params)
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from doubi.platforms.bilibili import webapi as bili_webapi  # noqa: E402


def _mock_client(json_payload: dict | list, *, status_code: int = 200):
    """Create an httpx.AsyncClient mock that returns ``json_payload``."""
    response = MagicMock()
    response.status_code = status_code
    response.json = MagicMock(return_value=json_payload)
    client = MagicMock()
    client.get = AsyncMock(return_value=response)
    client.aclose = AsyncMock()
    return client


def _patch_wbi_keys(monkeypatch, keys=("img_key_aaa", "sub_key_bbb")):
    """Skip the real ``/nav`` roundtrip; pretend we have keys."""
    async def _fake_fetch(*_a, **_k):
        return keys
    monkeypatch.setattr(bili_webapi, "fetch_wbi_keys", _fake_fetch)


# -----------------------------------------------------------------------
# search
# -----------------------------------------------------------------------


def test_search_video_returns_normalised_records(monkeypatch):
    _patch_wbi_keys(monkeypatch)
    payload = {
        "code": 0,
        "data": {
            "result": [
                {
                    "title": "<em>hello</em> world",
                    "bvid": "BV1xx411c7mD",
                    "id": 12345,
                    "author": "Some Uploader",
                    "mid": 999,
                    "duration": "1:23",
                    "play": 10000,
                    "pubdate": 1700000000,
                },
                {
                    "title": "second hit",
                    "id": 67890,
                    "author": "Another",
                    "mid": 111,
                    "duration": "5:00",
                    "play": 5000,
                    "pubdate": 1700000001,
                },
            ],
        },
    }
    client = _mock_client(payload)
    api = bili_webapi.BilibiliWebAPI(timeout=5.0, http_client=client)
    rows = asyncio_run(api.search("hello", channel="video"))
    assert len(rows) == 2
    # schema keys
    assert rows[0]["title"] == "hello world"  # <em> stripped
    assert rows[0]["item_id"] == "BV1xx411c7mD"
    assert rows[0]["share_url"] == "https://www.bilibili.com/video/BV1xx411c7mD"
    assert rows[0]["platform"] == "bilibili"
    assert rows[0]["channel"] == "video"
    assert rows[0]["result_type"] == "video"
    assert rows[0]["author"]["name"] == "Some Uploader"
    assert rows[0]["author"]["mid"] == 999
    # second row uses ``id`` (no bvid) — share_url falls back to /video/av1xx
    assert rows[1]["share_url"] == "https://www.bilibili.com/video/av67890"


def test_search_user_returns_normalised_records(monkeypatch):
    _patch_wbi_keys(monkeypatch)
    payload = {
        "code": 0,
        "data": {
            "result": [
                {
                    "uname": "作者A",
                    "mid": 123456,
                    "fans": 50000,
                    "level": 6,
                    "usign": "我在 B 站记录生活",
                },
            ],
        },
    }
    client = _mock_client(payload)
    api = bili_webapi.BilibiliWebAPI(timeout=5.0, http_client=client)
    rows = asyncio_run(api.search("key", channel="user"))
    assert len(rows) == 1
    rec = rows[0]
    assert rec["title"] == "作者A"
    assert rec["channel"] == "user"
    assert rec["result_type"] == "user"
    assert rec["item_id"] == "123456"
    assert rec["share_url"] == "https://space.bilibili.com/123456"
    assert rec["author"]["name"] == "作者A"
    assert rec["fans"] == 50000


def test_search_rejects_unknown_channel():
    client = _mock_client({})
    api = bili_webapi.BilibiliWebAPI(timeout=5.0, http_client=client)
    with pytest.raises(ValueError, match="unknown bilibili search channel"):
        asyncio_run(api.search("x", channel="bogus"))


def test_search_uses_wbi_signing(monkeypatch):
    """Verify the request URL carries wts + w_rid (= WBI signing applied).

    We assert via a captured GET URL rather than mocking the whole client:
    the test reads ``client.get.call_args`` to see what was actually sent.
    """
    _patch_wbi_keys(monkeypatch)
    captured = {}

    async def _fake_get(url, *_a, **_k):
        captured["url"] = url
        resp = MagicMock()
        resp.json = MagicMock(return_value={"code": 0, "data": {"result": []}})
        return resp

    client = MagicMock()
    client.get = AsyncMock(side_effect=_fake_get)
    client.aclose = AsyncMock()
    api = bili_webapi.BilibiliWebAPI(timeout=5.0, http_client=client)
    asyncio_run(api.search("cat", channel="video"))
    assert "wts=" in captured["url"]
    assert "w_rid=" in captured["url"]
    assert "search_type=video" in captured["url"]


def test_search_handles_fetch_wbi_keys_failure(monkeypatch):
    """When we can't get WBI keys, search returns [] with an error sink entry."""

    async def _fake_fetch(*_a, **_k):
        return None
    monkeypatch.setattr(bili_webapi, "fetch_wbi_keys", _fake_fetch)
    sink: dict[str, Any] = {}
    client = _mock_client({})
    api = bili_webapi.BilibiliWebAPI(timeout=5.0, http_client=client)
    rows = asyncio_run(api.search("x", channel="video", error_sink=sink))
    assert rows == []
    assert "fetch_wbi_keys failed" in sink["error"]


def test_search_handles_non_zero_response_code(monkeypatch):
    _patch_wbi_keys(monkeypatch)
    payload = {"code": -352, "message": "wbi 校验失败"}
    sink: dict[str, Any] = {}
    client = _mock_client(payload)
    api = bili_webapi.BilibiliWebAPI(timeout=5.0, http_client=client)
    rows = asyncio_run(api.search("x", channel="video", error_sink=sink))
    assert rows == []
    assert "-352" in sink["error"]


# -----------------------------------------------------------------------
# hotword
# -----------------------------------------------------------------------


def test_hotword_returns_normalised_records():
    payload = {
        "code": 0,
        "list": [
            {
                "keyword": "doubi 1",
                "show_name": "doubi 1 — 详情",
                "pos": 1,
                "word_type": 5,
                "icon": "http://example/i.png",
            },
            {
                "keyword": "doubi 2",
                "show_name": "doubi 2",
                "pos": 2,
                "word_type": 8,
                "icon": "",
            },
        ],
    }
    client = _mock_client(payload)
    api = bili_webapi.BilibiliWebAPI(timeout=5.0, http_client=client)
    rows = asyncio_run(api.get_hotword())
    assert len(rows) == 2
    assert rows[0]["word"] == "doubi 1"
    assert rows[0]["show_name"] == "doubi 1 — 详情"
    assert rows[0]["position"] == 1
    assert rows[0]["word_type"] == 5
    assert rows[0]["share_url"].startswith(
        "https://search.bilibili.com/all?keyword=",
    )
    assert "doubi" in rows[0]["share_url"]  # URL-encoded keyword
    assert rows[0]["platform"] == "bilibili"
    assert rows[0]["channel"] == "hotword"


# -----------------------------------------------------------------------
# popular
# -----------------------------------------------------------------------


def test_popular_returns_normalised_records():
    payload = {
        "code": 0,
        "data": {
            "list": [
                {
                    "bvid": "BV1xx",
                    "title": "<em>best</em> ever",
                    "owner": {"name": "Author 1", "mid": 100},
                    "stat": {"view": 9000, "danmaku": 30, "like": 100},
                    "duration": 300,
                    "pubdate": 1700000000,
                },
            ],
        },
    }
    client = _mock_client(payload)
    api = bili_webapi.BilibiliWebAPI(timeout=5.0, http_client=client)
    rows = asyncio_run(api.get_popular())
    assert len(rows) == 1
    rec = rows[0]
    assert rec["title"] == "best ever"
    assert rec["share_url"] == "https://www.bilibili.com/video/BV1xx"
    assert rec["channel"] == "popular"
    assert rec["author"]["name"] == "Author 1"
    assert rec["play"] == 9000


# -----------------------------------------------------------------------
# ranking
# -----------------------------------------------------------------------


def test_ranking_returns_normalised_records():
    payload = {
        "code": 0,
        "data": {
            "list": [
                {
                    "bvid": "BV1a",
                    "title": "Top 1",
                    "owner": {"name": "TopAuthor", "mid": 200},
                    "score": 12345,
                    "stat": {"view": 50000, "danmaku": 100, "like": 500},
                    "duration": 200,
                    "pubdate": 1700000000,
                },
            ],
        },
    }
    client = _mock_client(payload)
    api = bili_webapi.BilibiliWebAPI(timeout=5.0, http_client=client)
    rows = asyncio_run(api.get_ranking())
    assert len(rows) == 1
    rec = rows[0]
    assert rec["score"] == 12345
    assert rec["hot_value"] == 12345
    assert rec["position"] == 1
    assert rec["channel"] == "ranking"


# -----------------------------------------------------------------------
# cookie filtering
# -----------------------------------------------------------------------


def test_cookie_filter_keeps_only_bilibili_domain(tmp_path, monkeypatch):
    """httpx shouldn't be asked to send google / github cookies."""
    cookie_file = tmp_path / "bilibili.txt"
    cookie_file.write_text(
        "\n".join([
            "# Netscape HTTP Cookie File",
            "",
            ".bilibili.com\tTRUE\t/\tFALSE\t0\tbuvid3\tB-3",
            ".bilibili.com\tTRUE\t/\tFALSE\t0\tSESSDATA\ts-data",
            ".google.com\tTRUE\t/\tFALSE\t0\tNID\tg-cookie",
            ".github.com\tTRUE\t/\tFALSE\t0\tuser_session\tgh-cookie",
            ".api.bilibili.com\tTRUE\t/\tFALSE\t0\tacf\tauth",
            "",
        ]),
        encoding="utf-8",
    )

    kept = bili_webapi._to_httpx_cookies(
        bili_webapi._read_cookie_dicts(str(cookie_file)),
    )
    # All three .bilibili.com variants match; .google.com and .github.com filtered out.
    assert set(kept.keys()) == {"buvid3", "SESSDATA", "acf"}


# -----------------------------------------------------------------------
# helpers
# -----------------------------------------------------------------------


def asyncio_run(coro):
    import asyncio
    return asyncio.run(coro)