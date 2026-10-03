"""Regression tests for the 0.3.6 搜索 / 热榜 「没有结果」 fixes.

Three independent defects were found on 2026-10-03, all of which made the
GUI show an empty table while the underlying data was available:

1. ``BilibiliWebAPI._read_cookie_dicts(None)`` returned ``[]``.
   The GUI / REST / MCP layers pass ``cfg.cookies_file`` straight through
   and that field is ``None`` in a stock ``~/.doubi/config.yml``, so B 站
   search ran with an empty cookie jar and answered ``code=-101``.
   ``DouyinWebAPI`` had always resolved the default path itself — the
   asymmetry was the bug.

2. ``DouyinWebAPI.get_hot_list`` read ``data["word_list"]``, but the
   endpoint nests the rows at ``data["data"]["word_list"]``. Every board
   returned ``[]`` despite ``status_code: 0`` and 51 rows on the wire.

3. The 抖音 search endpoints answer ``200 + status_code: 0 + data: []``
   when the platform gates them, with the reason in
   ``search_nil_info.search_nil_type`` (``verify_check``). That was
   indistinguishable from 「这个关键词没有结果」.

For (3) the fix is *not* to bypass the gate — it was proven server-side
on a logged-in, 1.7-hour-old cookie (see ``test_search_gate_*`` below for
what is asserted). The fix is to stop reporting it silently.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from doubi.platforms.bilibili import webapi as bili_webapi  # noqa: E402
from doubi.platforms.bilibili.webapi import BilibiliWebAPI  # noqa: E402
from doubi.platforms.douyin.webapi import (  # noqa: E402
    DouyinWebAPI,
    _extract_hot_word_list,
    _search_gate_reason,
    _set_error_sink,
)


# ---------------------------------------------------------------------------
# (1) B 站 cookie fallback
# ---------------------------------------------------------------------------


def test_bilibili_read_cookie_dicts_reads_explicit_path(tmp_path):
    """An explicitly passed path is honoured as-is."""
    cookie_file = tmp_path / "bilibili.txt"
    cookie_file.write_text(
        "# Netscape HTTP Cookie File\n"
        ".bilibili.com\tTRUE\t/\tTRUE\t0\tSESSDATA\texplicit-value\n",
        encoding="utf-8",
    )
    dicts = bili_webapi._read_cookie_dicts(str(cookie_file))
    assert any(c.get("name") == "SESSDATA" for c in dicts)


def test_bilibili_read_cookie_dicts_falls_back_to_default(monkeypatch, tmp_path):
    """``None`` must resolve the platform default — this is the 0.3.6 fix.

    Before the fix this returned ``[]``, which silently disabled wbi
    search for every user whose ``config.yml`` still had the stock
    ``cookies_file: null``.
    """
    cookie_file = tmp_path / "bilibili.txt"
    cookie_file.write_text(
        "# Netscape HTTP Cookie File\n"
        ".bilibili.com\tTRUE\t/\tTRUE\t0\tSESSDATA\tdefault-value\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        bili_webapi, "default_cookie_path", lambda: cookie_file, raising=False,
    )
    # The import happens inside the function, so patch the source module.
    from doubi.platforms.bilibili import auth as bili_auth

    monkeypatch.setattr(bili_auth, "default_cookie_path", lambda: cookie_file)

    dicts = bili_webapi._read_cookie_dicts(None)
    assert any(c.get("name") == "SESSDATA" for c in dicts), (
        "None must fall back to default_cookie_path()"
    )


def test_bilibili_read_cookie_dicts_returns_empty_when_default_absent(
    monkeypatch, tmp_path,
):
    """No explicit path AND no default file → ``[]`` (unchanged)."""
    from doubi.platforms.bilibili import auth as bili_auth

    monkeypatch.setattr(
        bili_auth, "default_cookie_path", lambda: tmp_path / "missing.txt",
    )
    assert bili_webapi._read_cookie_dicts(None) == []


def test_bilibili_client_uses_default_when_no_cookies_file(monkeypatch, tmp_path):
    """End-to-end through the class: ``cookies_file=None`` still yields
    cookies, because ``_ensure_client`` goes through ``_read_cookie_dicts``."""
    cookie_file = tmp_path / "bilibili.txt"
    cookie_file.write_text(
        "# Netscape HTTP Cookie File\n"
        ".bilibili.com\tTRUE\t/\tTRUE\t0\tbuvid3\tabc123\n",
        encoding="utf-8",
    )
    from doubi.platforms.bilibili import auth as bili_auth

    monkeypatch.setattr(bili_auth, "default_cookie_path", lambda: cookie_file)

    api = BilibiliWebAPI(cookies_file=None)
    assert api.cookies_file is None
    dicts = bili_webapi._read_cookie_dicts(api.cookies_file)
    cookies = bili_webapi._to_httpx_cookies(dicts)
    assert cookies.get("buvid3") == "abc123"


def test_bilibili_cookie_domain_filter_still_applies():
    """The fallback must not break the domain filter that keeps foreign
    cookies (Google / GitHub / …) off B 站 requests."""
    dicts = [
        {"name": "SESSDATA", "value": "ok", "domain": ".bilibili.com"},
        {"name": "NID", "value": "nope", "domain": ".google.com"},
    ]
    cookies = bili_webapi._to_httpx_cookies(dicts)
    assert cookies == {"SESSDATA": "ok"}


# ---------------------------------------------------------------------------
# (2) 抖音 hot payload nesting
# ---------------------------------------------------------------------------


def test_extract_hot_word_list_reads_nested_layout():
    """The real shape: rows live at ``data.data.word_list``."""
    payload = {"data": {"word_list": [{"word": "a"}, {"word": "b"}]}}
    assert _extract_hot_word_list(payload) == [{"word": "a"}, {"word": "b"}]


def test_extract_hot_word_list_accepts_flat_layout():
    """Defensive: a flat ``data.word_list`` must keep working."""
    payload = {"word_list": [{"word": "flat"}]}
    assert _extract_hot_word_list(payload) == [{"word": "flat"}]


def test_extract_hot_word_list_prefers_nested():
    payload = {"data": {"word_list": [{"word": "nested"}]},
               "word_list": [{"word": "flat"}]}
    assert _extract_hot_word_list(payload) == [{"word": "nested"}]


def test_extract_hot_word_list_returns_none_for_unknown_shape():
    """``None`` (not ``[]``) so callers can tell "bad shape" from "no rows"."""
    assert _extract_hot_word_list({}) is None
    assert _extract_hot_word_list({"data": {}}) is None
    assert _extract_hot_word_list({"data": {"word_list": "not-a-list"}}) is None
    assert _extract_hot_word_list("nope") is None
    assert _extract_hot_word_list(None) is None


async def test_get_hot_list_reads_nested_payload(monkeypatch):
    """The regression itself: a nested response must produce rows.

    Before 0.3.6 ``get_hot_list`` read one level too high and returned
    ``[]`` for this exact payload — which is what the live endpoint sends.
    """
    api = DouyinWebAPI()

    async def _fake(path, params, *, max_retries=3, error_sink=None):
        return {"status_code": 0,
                "data": {"word_list": [{"word": "热词", "hot_value": 42}]}}

    monkeypatch.setattr(api, "_request_json", _fake)
    rows = await api.get_hot_list("positive")
    assert len(rows) == 1
    assert rows[0]["word"] == "热词"


async def test_get_hot_list_nested_respects_max_count(monkeypatch):
    api = DouyinWebAPI()

    async def _fake(path, params, *, max_retries=3, error_sink=None):
        return {"data": {"word_list": [{"word": f"w{i}"} for i in range(10)]}}

    monkeypatch.setattr(api, "_request_json", _fake)
    rows = await api.get_hot_list("positive", max_count=3)
    assert [r["word"] for r in rows] == ["w0", "w1", "w2"]


async def test_get_hot_list_empty_nested_word_list(monkeypatch):
    """An empty nested list is a legitimate "no rows", not an error."""
    api = DouyinWebAPI()

    async def _fake(path, params, *, max_retries=3, error_sink=None):
        return {"data": {"word_list": []}}

    monkeypatch.setattr(api, "_request_json", _fake)
    assert await api.get_hot_list("positive") == []


# ---------------------------------------------------------------------------
# (3) 抖音 search gate is reported, not swallowed
# ---------------------------------------------------------------------------


def test_search_gate_reason_detects_verify_check():
    payload = {"data": [], "status_code": 0,
               "search_nil_info": {"search_nil_type": "verify_check"}}
    assert _search_gate_reason(payload) == "verify_check"


def test_search_gate_reason_detects_params_check():
    payload = {"data": [], "search_nil_info": {"search_nil_type": "params_check"}}
    assert _search_gate_reason(payload) == "params_check"


def test_search_gate_reason_ignores_responses_with_rows():
    """"Has rows" always wins — never report a gate on a successful page."""
    payload = {"data": [{"aweme_id": "1"}],
               "search_nil_info": {"search_nil_type": "verify_check"}}
    assert _search_gate_reason(payload) is None


def test_search_gate_reason_ignores_missing_nil_info():
    """A plain empty result with no gate marker must stay silent, otherwise
    every genuinely-empty keyword would look like risk control."""
    assert _search_gate_reason({"data": []}) is None
    assert _search_gate_reason({"data": [], "search_nil_info": {}}) is None
    assert _search_gate_reason({"data": [], "search_nil_info": None}) is None
    assert _search_gate_reason({}) is None


async def test_search_gate_writes_verify_hint_to_error_sink(monkeypatch):
    """The user-visible contract: 「被拦」 must be distinguishable."""
    api = DouyinWebAPI()

    async def _fake(path, params, *, max_retries=3, error_sink=None):
        return {"data": [], "status_code": 0,
                "search_nil_info": {"search_nil_type": "verify_check"}}

    monkeypatch.setattr(api, "_request_json", _fake)
    sink: dict = {}
    rows = await api.search_general("猫", error_sink=sink)
    assert rows == []
    assert sink["hint"] == "verify"
    assert "verify_check" in sink["reason"]


async def test_search_gate_does_not_fire_on_plain_empty(monkeypatch):
    api = DouyinWebAPI()

    async def _fake(path, params, *, max_retries=3, error_sink=None):
        return {"data": [], "status_code": 0}

    monkeypatch.setattr(api, "_request_json", _fake)
    sink: dict = {}
    rows = await api.search_general("不存在的关键词", error_sink=sink)
    assert rows == []
    assert sink == {}


async def test_search_gate_leaves_sink_untouched_on_success(monkeypatch):
    api = DouyinWebAPI()

    async def _fake(path, params, *, max_retries=3, error_sink=None):
        return {"data": [{"aweme_id": "1"}], "has_more": 0, "cursor": 0}

    monkeypatch.setattr(api, "_request_json", _fake)
    sink: dict = {}
    rows = await api.search_general("猫", error_sink=sink)
    assert len(rows) == 1
    assert sink == {}


def test_set_error_sink_explicit_hint_overrides_status_derivation():
    """``hint=`` must win over the status-code default — the search gate
    arrives as HTTP 200, which would otherwise derive ``transient``."""
    sink: dict = {}
    _set_error_sink(sink, reason="search gated by 抖音 (verify_check)",
                    status_code=0, hint="verify")
    assert sink["hint"] == "verify"


def test_set_error_sink_derives_hint_when_not_given():
    """The pre-0.3.6 derivation must be unchanged for every caller that
    does not pass an explicit hint."""
    sink: dict = {}
    _set_error_sink(sink, reason="HTTP 403", status_code=403)
    assert sink["hint"] == "need_login"

    _set_error_sink(sink, reason="HTTP 502", status_code=502)
    assert sink["hint"] == "server_error"

    _set_error_sink(sink, reason="boom", status_code=None)
    assert sink["hint"] == "transient"


def test_set_error_sink_clears_previous_state():
    sink: dict = {"stale": "value", "hint": "need_login"}
    _set_error_sink(sink, reason="fresh", status_code=None, hint="verify")
    assert set(sink) == {"reason", "status_code", "hint"}
    assert sink["hint"] == "verify"
