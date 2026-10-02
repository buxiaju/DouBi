"""Tests for M6.51 抖音 收藏夹全家族: 5 endpoints.

The 5 endpoints (TikTokDL ``src/interface/collects.py``) are:

    iter_collects        /aweme/v1/web/collects/list/         data.collects_list
    iter_collects_videos /aweme/v1/web/collects/video/list/   data.aweme_list    (+collects_id)
    iter_collects_mix    /aweme/v1/web/mix/listcollection/    data.mix_infos
    iter_collects_music  /aweme/v1/web/music/listcollection/  data.mc_list
    iter_collects_series /aweme/v1/web/series/collections/    data.series_infos

All 5 share the same cursor+count+has_more pagination shape and are
login-gated (referer = ``user/self?showTab=favorite_collection``).
The login gating is exercised through the ``error_sink.hint=need_login``
machinery from M6.46 — the platform's 401 / risk-control responses get
mapped to the same UX as the USER container hint (M6.47).

Tests monkey-patch ``DouyinWebAPI._request_json`` so no real traffic.
Sessions adapt to M6.48's WebSign layer (4 of the 5 paths were already
in the M6.48 whitelist; M6.51 adds ``/aweme/v1/web/series/collections/``).
"""

from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from doubi.platforms.douyin.webapi import DouyinWebAPI  # noqa: E402
from doubi.platforms.douyin.sign import DOUYIN_SIGNED_PATHS  # noqa: E402


def _collect_row(collects_id: str = "") -> dict:
    return {
        "collects_id": collects_id or f"cid-{id(object())}",
        "collects_name": f"我的收藏夹 {collects_id}",
        "video_count": 42,
        "cover_url": "https://p.douyin.com/cover.jpg",
    }


def _aweme_row(aweme_id: str = "") -> dict:
    return {
        "aweme_id": aweme_id or f"aweme-{id(object())}",
        "desc": f"title-{aweme_id}",
    }


def _mix_row(mix_id: str = "") -> dict:
    return {
        "mix_id": mix_id or f"mix-{id(object())}",
        "mix_name": f"合集 {mix_id}",
        "cover_url": "https://p.douyin.com/mix.jpg",
    }


def _mc_row(mc_id: str = "") -> dict:
    return {
        "mc_id": mc_id or f"mc-{id(object())}",
        "mc_name": f"歌单 {mc_id}",
        "mc_cover": "https://p.douyin.com/mc.jpg",
    }


def _series_row(series_id: str = "") -> dict:
    return {
        "series_id": series_id or f"ser-{id(object())}",
        "series_name": f"短剧 {series_id}",
    }


def _page(data_key: str, rows: list[dict], *, has_more: bool = False,
          cursor: int | None = None) -> dict:
    return {
        data_key: rows,
        "cursor": cursor if cursor is not None else 0,
        "has_more": has_more,
    }


# ---------------------------------------------------------------------------
# _cursor_paginate helper (shared by all 5 iter methods)
# ---------------------------------------------------------------------------


async def test_cursor_paginate_basic_single_page(monkeypatch):
    """Single page (has_more=False) → returns the rows, no extra calls."""
    api = DouyinWebAPI()
    calls: list = []

    async def _fake(path, params, *, max_retries=3, error_sink=None):
        calls.append((path, dict(params)))
        return _page("data", [{"aweme_id": "a1"}])

    monkeypatch.setattr(api, "_request_json", _fake)

    rows = await api._cursor_paginate(
        "/aweme/v1/web/foo/",
        data_key="data",
        extra_params={"foo": "bar"},
        count=10,
    )
    assert rows == [{"aweme_id": "a1"}]
    assert len(calls) == 1
    path, sent = calls[0]
    assert path == "/aweme/v1/web/foo/"
    # cursor/count always injected; extra_params merged
    assert sent["cursor"] == 0
    assert sent["count"] == 10
    assert sent["foo"] == "bar"


async def test_cursor_paginate_multi_page_advances_cursor(monkeypatch):
    """Page 1 reports has_more=True with cursor=10 → page 2 sends cursor=10.
    Page 2 reports has_more=False → loop ends.
    """
    api = DouyinWebAPI()
    state = {"n": 0}
    sent: list[dict] = []

    async def _fake(path, params, *, max_retries=3, error_sink=None):
        sent.append(dict(params))
        state["n"] += 1
        if state["n"] == 1:
            return _page("data", [{"aweme_id": "p1"}], has_more=True, cursor=10)
        return _page("data", [{"aweme_id": "p2"}], has_more=False)

    monkeypatch.setattr(api, "_request_json", _fake)

    rows = await api._cursor_paginate(
        "/aweme/v1/web/foo/", data_key="data", extra_params={},
    )
    assert [r["aweme_id"] for r in rows] == ["p1", "p2"]
    assert sent[0]["cursor"] == 0
    assert sent[1]["cursor"] == 10


async def test_cursor_paginate_hard_cap_max_pages(monkeypatch):
    """If the platform reports has_more=True forever, the inner cap
    (default 50) must stop us — mirrors ``_search_paginate``."""
    api = DouyinWebAPI()
    state = {"n": 0}

    async def _fake(path, params, *, max_retries=3, error_sink=None):
        state["n"] += 1
        # Always say "more" with a fresh cursor to keep advancing.
        return _page("data", [{"aweme_id": f"id-{state['n']}"}],
                     has_more=True, cursor=state["n"] * 10)

    monkeypatch.setattr(api, "_request_json", _fake)

    rows = await api._cursor_paginate(
        "/aweme/v1/web/foo/", data_key="data", extra_params={},
    )
    assert state["n"] == 50
    assert len(rows) == 50


async def test_cursor_paginate_max_count_truncates(monkeypatch):
    """``max_count=3`` truncates after the first 3 rows even if the
    platform says more pages exist."""
    api = DouyinWebAPI()

    async def _fake(path, params, *, max_retries=3, error_sink=None):
        return _page("data", [
            {"aweme_id": "a"}, {"aweme_id": "b"},
            {"aweme_id": "c"}, {"aweme_id": "d"},
        ], has_more=True, cursor=10)

    monkeypatch.setattr(api, "_request_json", _fake)

    rows = await api._cursor_paginate(
        "/aweme/v1/web/foo/", data_key="data", extra_params={},
        max_count=3,
    )
    assert [r["aweme_id"] for r in rows] == ["a", "b", "c"]


async def test_cursor_paginate_stops_when_cursor_stuck(monkeypatch):
    """If the cursor doesn't advance, we must NOT loop forever. Same
    defensive guard as ``_search_paginate``."""
    api = DouyinWebAPI()
    state = {"n": 0}

    async def _fake(path, params, *, max_retries=3, error_sink=None):
        state["n"] += 1
        return _page("data", [{"aweme_id": "a"}],
                     has_more=True, cursor=0)  # stuck

    monkeypatch.setattr(api, "_request_json", _fake)

    rows = await api._cursor_paginate(
        "/aweme/v1/web/foo/", data_key="data", extra_params={},
    )
    assert state["n"] == 1
    assert rows == [{"aweme_id": "a"}]


# ---------------------------------------------------------------------------
# 5 iter methods: endpoint + params + data_key
# ---------------------------------------------------------------------------


async def test_iter_collects_calls_collects_list_endpoint(monkeypatch):
    """``iter_collects`` must hit ``/aweme/v1/web/collects/list/`` and
    read ``data.collects_list``."""
    api = DouyinWebAPI()
    captured: dict = {}

    async def _fake(path, params, *, max_retries=3, error_sink=None):
        captured["path"] = path
        captured["params"] = params
        return _page("collects_list", [_collect_row("c1")])

    monkeypatch.setattr(api, "_request_json", _fake)

    rows = await api.iter_collects()
    assert captured["path"] == "/aweme/v1/web/collects/list/"
    assert captured["params"]["version_code"] == "170400"
    assert captured["params"]["version_name"] == "17.4.0"
    assert rows[0]["collects_id"] == "c1"


async def test_iter_collects_videos_passes_collects_id(monkeypatch):
    """``iter_collects_videos`` must forward the collects_id param
    (the only iter_* method that needs an extra path param)."""
    api = DouyinWebAPI()
    captured: dict = {}

    async def _fake(path, params, *, max_retries=3, error_sink=None):
        captured["path"] = path
        captured["params"] = params
        return _page("aweme_list", [_aweme_row("v1")])

    monkeypatch.setattr(api, "_request_json", _fake)

    rows = await api.iter_collects_videos("c-12345")
    assert captured["path"] == "/aweme/v1/web/collects/video/list/"
    assert captured["params"]["collects_id"] == "c-12345"
    assert rows[0]["aweme_id"] == "v1"


async def test_iter_collects_videos_returns_empty_for_blank_id(monkeypatch):
    """Defensive: empty collects_id must NOT make a network call —
    return ``[]``. The CLI catches this earlier with a clearer error,
    but a direct API caller (e.g. a future GUI) might forget."""
    api = DouyinWebAPI()
    call_count = {"n": 0}

    async def _fake(path, params, *, max_retries=3, error_sink=None):
        call_count["n"] += 1
        return _page("aweme_list", [_aweme_row("never")])

    monkeypatch.setattr(api, "_request_json", _fake)

    rows = await api.iter_collects_videos("")
    assert rows == []
    assert call_count["n"] == 0


async def test_iter_collects_mix_endpoint(monkeypatch):
    """``iter_collects_mix`` hits ``/aweme/v1/web/mix/listcollection/``
    with data_key ``mix_infos``."""
    api = DouyinWebAPI()
    captured: dict = {}

    async def _fake(path, params, *, max_retries=3, error_sink=None):
        captured["path"] = path
        captured["params"] = params
        return _page("mix_infos", [_mix_row("m1")])

    monkeypatch.setattr(api, "_request_json", _fake)

    rows = await api.iter_collects_mix()
    assert captured["path"] == "/aweme/v1/web/mix/listcollection/"
    assert captured["params"]["version_code"] == "170400"
    assert rows[0]["mix_id"] == "m1"


async def test_iter_collects_music_endpoint(monkeypatch):
    """``iter_collects_music`` hits ``/aweme/v1/web/music/listcollection/``
    with data_key ``mc_list``."""
    api = DouyinWebAPI()
    captured: dict = {}

    async def _fake(path, params, *, max_retries=3, error_sink=None):
        captured["path"] = path
        return _page("mc_list", [_mc_row("mc1")])

    monkeypatch.setattr(api, "_request_json", _fake)

    rows = await api.iter_collects_music()
    assert captured["path"] == "/aweme/v1/web/music/listcollection/"
    assert rows[0]["mc_id"] == "mc1"


async def test_iter_collects_series_endpoint(monkeypatch):
    """``iter_collects_series`` hits ``/aweme/v1/web/series/collections/``
    with data_key ``series_infos``."""
    api = DouyinWebAPI()
    captured: dict = {}

    async def _fake(path, params, *, max_retries=3, error_sink=None):
        captured["path"] = path
        return _page("series_infos", [_series_row("s1")])

    monkeypatch.setattr(api, "_request_json", _fake)

    rows = await api.iter_collects_series()
    assert captured["path"] == "/aweme/v1/web/series/collections/"
    assert rows[0]["series_id"] == "s1"


# ---------------------------------------------------------------------------
# error_sink propagation (login-gated UX)
# ---------------------------------------------------------------------------


async def test_iter_collects_propagates_need_login_hint(monkeypatch):
    """All 5 endpoints gate on `user/self` referer. A 401 (or any
    risk-control status) must land in error_sink with hint=need_login
    so the CLI can surface 「请先登录抖音」 (M6.46 UX)."""
    api = DouyinWebAPI()

    async def _fake(path, params, *, max_retries=3, error_sink=None):
        if error_sink is not None:
            error_sink.clear()
            error_sink["reason"] = "HTTP 401"
            error_sink["status_code"] = 401
            error_sink["hint"] = "need_login"
        return {}

    monkeypatch.setattr(api, "_request_json", _fake)

    sink: dict = {}
    rows = await api.iter_collects(error_sink=sink)
    assert rows == []
    assert sink["hint"] == "need_login"


# ---------------------------------------------------------------------------
# WebSign whitelist (M6.48 dependency)
# ---------------------------------------------------------------------------


def test_all_five_endpoints_in_signed_paths():
    """The 5 favorites endpoints must all be in DOUYIN_SIGNED_PATHS so
    the M6.48 WebSign layer attaches. ``series/collections/`` was
    added defensively in M6.51; the other 4 were in M6.48."""
    expected = {
        "/aweme/v1/web/collects/list/",
        "/aweme/v1/web/collects/video/list/",
        "/aweme/v1/web/mix/listcollection/",
        "/aweme/v1/web/series/collections/",
        "/aweme/v1/web/music/listcollection/",
    }
    assert expected.issubset(DOUYIN_SIGNED_PATHS)


# ---------------------------------------------------------------------------
# CLI: doubi favorites
# ---------------------------------------------------------------------------


def _make_ns(**overrides):
    """Build a minimal argparse.Namespace the _cmd_favorites handler accepts."""
    from argparse import Namespace

    ns = Namespace(
        verbose=False,
        config=None,
        command="favorites",
        kind="favorites",
        collect_id=None,
        max=50,
        count=10,
        cookies_file=None,
        proxy=None,
    )
    for k, v in overrides.items():
        setattr(ns, k, v)
    return ns


def _patch_favorites_iter(monkeypatch, *, per_kind_rows: dict[str, list[dict]]):
    """Install a fake on each iter_collects_* method keyed on the kind.

    ``per_kind_rows`` maps ``kind → rows``. ``videos`` must supply a
    non-empty list even if the test doesn't care (the handler's
    collect_id guard runs before us).
    """
    from doubi.platforms.douyin.webapi import DouyinWebAPI

    async def _fake_iter_collects(self, *, count=10, max_count=0, error_sink=None):
        rows = per_kind_rows.get("favorites", [])
        return rows[:max_count] if max_count else rows

    async def _fake_iter_collects_videos(
        self, collects_id, *, count=10, max_count=0, error_sink=None,
    ):
        rows = per_kind_rows.get("videos", [])
        return rows[:max_count] if max_count else rows

    async def _fake_iter_collects_mix(self, *, count=12, max_count=0, error_sink=None):
        rows = per_kind_rows.get("mix", [])
        return rows[:max_count] if max_count else rows

    async def _fake_iter_collects_music(self, *, count=20, max_count=0, error_sink=None):
        rows = per_kind_rows.get("music", [])
        return rows[:max_count] if max_count else rows

    async def _fake_iter_collects_series(self, *, count=12, max_count=0, error_sink=None):
        rows = per_kind_rows.get("series", [])
        return rows[:max_count] if max_count else rows

    monkeypatch.setattr(DouyinWebAPI, "iter_collects", _fake_iter_collects)
    monkeypatch.setattr(
        DouyinWebAPI, "iter_collects_videos", _fake_iter_collects_videos,
    )
    monkeypatch.setattr(DouyinWebAPI, "iter_collects_mix", _fake_iter_collects_mix)
    monkeypatch.setattr(
        DouyinWebAPI, "iter_collects_music", _fake_iter_collects_music,
    )
    monkeypatch.setattr(
        DouyinWebAPI, "iter_collects_series", _fake_iter_collects_series,
    )


async def test_cli_favorites_list_emits_records_with_kind_tag(monkeypatch):
    """``doubi favorites`` (default --kind=favorites) must tag every
    record with ``kind`` + ``kind_name`` so downstream consumers don't
    have to special-case the schema."""
    from doubi.cli.main import _cmd_favorites

    _patch_favorites_iter(monkeypatch, per_kind_rows={
        "favorites": [_collect_row("c1"), _collect_row("c2")],
    })

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = await _cmd_favorites(_make_ns(kind="favorites"))
    assert rc == 0
    lines = [json.loads(line) for line in buf.getvalue().splitlines() if line]
    assert len(lines) == 2
    assert {r["kind"] for r in lines} == {"favorites"}
    assert {r["kind_name"] for r in lines} == {"收藏夹"}
    assert [r["collects_id"] for r in lines] == ["c1", "c2"]


async def test_cli_favorites_videos_requires_collect_id(monkeypatch):
    """``--kind=videos`` without a collect_id must exit 2 BEFORE any
    network call (argparse lets the positional pass, the handler
    guards)."""
    from doubi.cli.main import _cmd_favorites

    _patch_favorites_iter(monkeypatch, per_kind_rows={})

    buf_out, buf_err = io.StringIO(), io.StringIO()
    with redirect_stdout(buf_out):
        with redirect_stderr(buf_err):
            rc = await _cmd_favorites(_make_ns(kind="videos", collect_id=None))
    assert rc == 2
    assert "collect_id" in buf_err.getvalue()


async def test_cli_favorites_videos_emits_share_url(monkeypatch):
    """``--kind=videos`` rows must carry a ``share_url`` so they can
    pipe straight into ``doubi download --batch -``."""
    from doubi.cli.main import _cmd_favorites

    _patch_favorites_iter(monkeypatch, per_kind_rows={
        "videos": [_aweme_row("a1")],
    })

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = await _cmd_favorites(_make_ns(kind="videos", collect_id="c1"))
    assert rc == 0
    lines = [json.loads(line) for line in buf.getvalue().splitlines() if line]
    assert len(lines) == 1
    assert lines[0]["share_url"] == "https://www.douyin.com/video/a1"
    assert lines[0]["kind_name"] == "收藏夹视频"


async def test_cli_favorites_mix_emits_records_with_kind_tag(monkeypatch):
    """``--kind=mix`` rows carry mix_id + kind_name=收藏合集 (no
    share_url because 合集 IDs aren't directly downloadable URLs)."""
    from doubi.cli.main import _cmd_favorites

    _patch_favorites_iter(monkeypatch, per_kind_rows={
        "mix": [_mix_row("m1")],
    })

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = await _cmd_favorites(_make_ns(kind="mix"))
    assert rc == 0
    lines = [json.loads(line) for line in buf.getvalue().splitlines() if line]
    assert len(lines) == 1
    assert lines[0]["kind_name"] == "收藏合集"
    assert lines[0]["mix_id"] == "m1"
    # No share_url for non-video kinds
    assert "share_url" not in lines[0]


async def test_cli_favorites_max_caps_output(monkeypatch):
    """``--max N`` must cap output rows (symmetric with hot/search)."""
    from doubi.cli.main import _cmd_favorites

    _patch_favorites_iter(monkeypatch, per_kind_rows={
        "favorites": [_collect_row(f"c{i}") for i in range(20)],
    })

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = await _cmd_favorites(_make_ns(kind="favorites", max=5))
    assert rc == 0
    lines = [json.loads(line) for line in buf.getvalue().splitlines() if line]
    assert len(lines) == 5


async def test_cli_favorites_empty_results_returns_zero(monkeypatch):
    """No rows must still exit 0 — *no hits* is not an error.
    Without error_sink hints, prints a generic "No results." message.
    """
    from doubi.cli.main import _cmd_favorites

    _patch_favorites_iter(monkeypatch, per_kind_rows={"favorites": []})

    buf_out, buf_err = io.StringIO(), io.StringIO()
    with redirect_stdout(buf_out):
        with redirect_stderr(buf_err):
            rc = await _cmd_favorites(_make_ns(kind="favorites"))
    assert rc == 0
    assert buf_out.getvalue() == ""
    assert "No results." in buf_err.getvalue()


def test_cli_favorites_parser_lists_all_kinds():
    """``--kind`` argparse choices must include the 5 families plus
    the default. A typo (``--kind xyz``) must be rejected at parse time.
    """
    from doubi.cli.main import _build_parser

    parser = _build_parser()
    args = parser.parse_args(["favorites"])
    assert args.kind == "favorites"  # default
    assert args.max == 50

    args = parser.parse_args(["favorites", "--kind", "series"])
    assert args.kind == "series"

    args = parser.parse_args(["favorites", "--kind", "videos", "c-12345"])
    assert args.kind == "videos"
    assert args.collect_id == "c-12345"
