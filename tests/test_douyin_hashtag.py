"""Tests for M6.57 抖音 话题（HashTag）作品列表 — Survey item 13.

**TikTokDL 无源** — this is NOT a port. TikTokDL
``src/interface/hashtag.py`` is an empty shell:

    class HashTag(API):
        def __init__(self, params, cookie="", proxy=None, *args, **kwargs):
            super().__init__(params, cookie, proxy, *args, **kwargs)

        async def run(self, *args, **kwargs):
            pass

``run()`` is ``pass`` and ``self.api`` is never even declared, so there
is no endpoint to copy. Survey §8.1 item 13 marks it ❌ and notes the
real path is ``/aweme/v1/web/challenge/aweme/``. M6.57 is therefore a
**DouBi native implementation** following the public Douyin web API
convention + reusing the M6.51 ``_cursor_paginate`` helper. CHANGELOG
M6.57 §首段 flags this explicitly — do not credit this milestone to
TikTokDL, and do not "restore parity" with a file that has no content.

Tests monkey-patch ``DouyinWebAPI._request_json`` so no real traffic.
"""

from __future__ import annotations

import asyncio
import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from doubi.cli.main import HASHTAG_SORT_TYPES, _ch_id_from_arg  # noqa: E402
from doubi.platforms.douyin.sign import DOUYIN_SIGNED_PATHS  # noqa: E402
from doubi.platforms.douyin.webapi import DouyinWebAPI  # noqa: E402

CH_ID = "1598294112437763"
ENDPOINT = "/aweme/v1/web/challenge/aweme/"


def _aweme(aweme_id: str, *, desc: str = "话题视频") -> dict:
    return {
        "aweme_id": aweme_id,
        "desc": desc,
        "create_time": 1700000000,
        "video": {"duration": 12000},
        "author": {"sec_uid": f"sec-{aweme_id}", "nickname": f"作者{aweme_id}"},
        "statistics": {"play_count": 100, "digg_count": 9},
    }


def _page(rows: list[dict], *, has_more: bool = False, cursor: int = 0) -> dict:
    return {"aweme_list": rows, "has_more": has_more, "cursor": cursor}


# ---------------------------------------------------------------------------
# coefficient: the endpoint is signed
# ---------------------------------------------------------------------------


def test_challenge_path_is_websign_protected():
    """M6.57 added the path to the M6.48 whitelist. The endpoint sits
    under the same ``/aweme/v1/web/`` tree as search / collects, so we
    follow the defensive over-sign convention (M6.51 / M6.54): signing
    an unprotected path is harmless, under-signing a protected one 403s.
    """
    assert ENDPOINT in DOUYIN_SIGNED_PATHS


# ---------------------------------------------------------------------------
# iter_challenge_awemes
# ---------------------------------------------------------------------------


def test_iter_challenge_awemes_hits_expected_endpoint(monkeypatch):
    api = DouyinWebAPI(timeout=5.0)
    seen: list[tuple[str, dict]] = []

    async def _fake_request_json(path, params=None, **kwargs):
        seen.append((path, dict(params or {})))
        return _page([_aweme("700")])

    monkeypatch.setattr(api, "_request_json", _fake_request_json)
    rows = asyncio.run(api.iter_challenge_awemes(CH_ID))

    assert len(rows) == 1
    assert seen[0][0] == ENDPOINT
    params = seen[0][1]
    assert params["ch_id"] == CH_ID
    assert params["count"] == 20
    assert params["cursor"] == 0
    assert params["sort_type"] == 0


def test_iter_challenge_awemes_blank_id_issues_no_request(monkeypatch):
    """A blank ch_id is a caller bug, not a platform condition — issuing
    the request would just burn a risk-control budget slot."""
    api = DouyinWebAPI(timeout=5.0)
    called = False

    async def _boom(path, params=None, **kwargs):
        nonlocal called
        called = True
        return _page([_aweme("700")])

    monkeypatch.setattr(api, "_request_json", _boom)
    assert asyncio.run(api.iter_challenge_awemes("")) == []
    assert asyncio.run(api.iter_challenge_awemes("   ".strip())) == []
    assert called is False


def test_iter_challenge_awemes_latest_sort(monkeypatch):
    api = DouyinWebAPI(timeout=5.0)
    seen: list[dict] = []

    async def _fake_request_json(path, params=None, **kwargs):
        seen.append(dict(params or {}))
        return _page([_aweme("700")])

    monkeypatch.setattr(api, "_request_json", _fake_request_json)
    asyncio.run(api.iter_challenge_awemes(CH_ID, sort_type=1))
    assert seen[0]["sort_type"] == 1


def test_iter_challenge_awemes_paginates_until_has_more_false(monkeypatch):
    """cursor + count + has_more, same shape as the M6.51 favorites
    family. Two pages then stop."""
    api = DouyinWebAPI(timeout=5.0)
    calls: list[int] = []

    async def _fake_request_json(path, params=None, **kwargs):
        cursor = params["cursor"]
        calls.append(cursor)
        if cursor == 0:
            return _page([_aweme("700"), _aweme("701")], has_more=True, cursor=2)
        return _page([_aweme("702")], has_more=False, cursor=2)

    monkeypatch.setattr(api, "_request_json", _fake_request_json)
    rows = asyncio.run(api.iter_challenge_awemes(CH_ID))

    assert [r["aweme_id"] for r in rows] == ["700", "701", "702"]
    assert calls == [0, 2]


def test_iter_challenge_awemes_max_count_truncates(monkeypatch):
    api = DouyinWebAPI(timeout=5.0)

    async def _fake_request_json(path, params=None, **kwargs):
        return _page([_aweme("700"), _aweme("701"), _aweme("702")],
                     has_more=True, cursor=3)

    monkeypatch.setattr(api, "_request_json", _fake_request_json)
    rows = asyncio.run(api.iter_challenge_awemes(CH_ID, max_count=2))
    assert [r["aweme_id"] for r in rows] == ["700", "701"]


def test_iter_challenge_awemes_stuck_cursor_does_not_loop(monkeypatch):
    """Defensive: a cursor that never advances must terminate, not spin
    — the M6.51 helper's protection is inherited here.

    ``cursor == 0`` is both the page-1 value and the stuck value, so the
    helper stops as soon as the *response* reports 0 rather than making
    a second request that would return the same page forever.
    """
    api = DouyinWebAPI(timeout=5.0)
    pages = 0

    async def _fake_request_json(path, params=None, **kwargs):
        nonlocal pages
        pages += 1
        return _page([_aweme(f"70{pages}")], has_more=True, cursor=0)

    monkeypatch.setattr(api, "_request_json", _fake_request_json)
    rows = asyncio.run(api.iter_challenge_awemes(CH_ID))
    assert len(rows) == 1
    assert pages == 1


def test_iter_challenge_awemes_empty_page_stops(monkeypatch):
    api = DouyinWebAPI(timeout=5.0)

    async def _fake_request_json(path, params=None, **kwargs):
        return {"aweme_list": [], "has_more": True, "cursor": 5}

    monkeypatch.setattr(api, "_request_json", _fake_request_json)
    assert asyncio.run(api.iter_challenge_awemes(CH_ID)) == []


def test_iter_challenge_awemes_drops_non_dict_rows(monkeypatch):
    api = DouyinWebAPI(timeout=5.0)

    async def _fake_request_json(path, params=None, **kwargs):
        return {"aweme_list": [_aweme("700"), "junk", None, 42],
                "has_more": False, "cursor": 0}

    monkeypatch.setattr(api, "_request_json", _fake_request_json)
    rows = asyncio.run(api.iter_challenge_awemes(CH_ID))
    assert [r["aweme_id"] for r in rows] == ["700"]


def test_iter_challenge_awemes_forwarded_error_sink(monkeypatch):
    """``error_sink`` reaches ``_request_json`` so the CLI can tell
    need_login apart from a genuinely empty 话题."""
    api = DouyinWebAPI(timeout=5.0)

    async def _fake_request_json(path, params=None, error_sink=None, **kwargs):
        if error_sink is not None:
            error_sink.update({"reason": "http_403", "status_code": 403,
                               "hint": "need_login"})
        return {}

    monkeypatch.setattr(api, "_request_json", _fake_request_json)
    sink: dict = {}
    rows = asyncio.run(api.iter_challenge_awemes(CH_ID, error_sink=sink))
    assert rows == []
    assert sink["hint"] == "need_login"


def test_iter_challenge_awemes_counts_as_str(monkeypatch):
    """``ch_id`` is coerced to str so an int-from-JSON never produces a
    duplicate param encoding."""
    api = DouyinWebAPI(timeout=5.0)
    seen: list[dict] = []

    async def _fake_request_json(path, params=None, **kwargs):
        seen.append(dict(params or {}))
        return _page([])

    monkeypatch.setattr(api, "_request_json", _fake_request_json)
    asyncio.run(api.iter_challenge_awemes(1598294112437763))  # type: ignore[arg-type]
    assert seen[0]["ch_id"] == "1598294112437763"
    assert isinstance(seen[0]["ch_id"], str)


def test_iter_challenge_awemes_custom_count(monkeypatch):
    api = DouyinWebAPI(timeout=5.0)
    seen: list[dict] = []

    async def _fake_request_json(path, params=None, **kwargs):
        seen.append(dict(params or {}))
        return _page([])

    monkeypatch.setattr(api, "_request_json", _fake_request_json)
    asyncio.run(api.iter_challenge_awemes(CH_ID, count=7))
    assert seen[0]["count"] == 7


# ---------------------------------------------------------------------------
# _ch_id_from_arg
# ---------------------------------------------------------------------------


def test_ch_id_from_bare_id():
    assert _ch_id_from_arg(CH_ID) == CH_ID


def test_ch_id_from_web_url():
    assert _ch_id_from_arg(f"https://www.douyin.com/challenge/detail/{CH_ID}") == CH_ID


def test_ch_id_from_web_url_with_query():
    url = f"https://www.douyin.com/challenge/detail/{CH_ID}?enter_from=search"
    assert _ch_id_from_arg(url) == CH_ID


def test_ch_id_from_mobile_share_url():
    url = f"https://www.iesdouyin.com/share/challenge/detail/{CH_ID}/?a=1"
    assert _ch_id_from_arg(url) == CH_ID


def test_ch_id_from_unrelated_url_is_empty():
    """A /video/ URL is not a 话题 — return "" so the caller errors out
    instead of passing the whole URL through as an id."""
    assert _ch_id_from_arg("https://www.douyin.com/video/700") == ""
    assert _ch_id_from_arg("https://www.douyin.com/user/someone") == ""


def test_ch_id_from_blank_is_empty():
    assert _ch_id_from_arg("") == ""
    assert _ch_id_from_arg("   ") == ""


def test_ch_id_strips_surrounding_whitespace():
    assert _ch_id_from_arg(f"  {CH_ID}  ") == CH_ID


# ---------------------------------------------------------------------------
# sort vocabulary
# ---------------------------------------------------------------------------


def test_sort_types_match_platform_values():
    """Pin the two values the platform accepts. ``0`` is 综合排序 and
    ``1`` is 最新发布; swapping them would silently change what the
    user sees without any error."""
    assert HASHTAG_SORT_TYPES == {"comprehensive": 0, "latest": 1}


# ---------------------------------------------------------------------------
# CLI: doubi hashtag
# ---------------------------------------------------------------------------


def _run_cli(argv: list[str]) -> tuple[int, str, str]:
    from doubi.cli.main import main

    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


def test_cli_hashtag_emits_jsonl(monkeypatch):
    async def _fake_iter(self, ch_id, *, count=20, max_count=0, sort_type=0,
                         error_sink=None):
        return [
            _aweme("700", desc="第一条"),
            _aweme("701", desc="第二条"),
        ]

    monkeypatch.setattr(DouyinWebAPI, "iter_challenge_awemes", _fake_iter)
    code, out, err = _run_cli(["hashtag", CH_ID])
    assert code == 0, err
    lines = [json.loads(ln) for ln in out.strip().splitlines()]
    assert len(lines) == 2
    assert lines[0]["aweme_id"] == "700"
    assert lines[0]["title"] == "第一条"
    assert lines[0]["author"] == "作者700"
    assert lines[0]["author_sec_uid"] == "sec-700"
    assert lines[0]["ch_id"] == CH_ID
    assert lines[0]["target_ch_id"] == CH_ID
    assert lines[0]["sort"] == "comprehensive"
    assert lines[0]["source_url"] == "https://www.douyin.com/video/700"


def test_cli_hashtag_accepts_url(monkeypatch):
    seen: list[str] = []

    async def _fake_iter(self, ch_id, *, count=20, max_count=0, sort_type=0,
                         error_sink=None):
        seen.append(ch_id)
        return [_aweme("700")]

    monkeypatch.setattr(DouyinWebAPI, "iter_challenge_awemes", _fake_iter)
    code, _, _ = _run_cli([
        "hashtag", f"https://www.douyin.com/challenge/detail/{CH_ID}",
    ])
    assert code == 0
    assert seen == [CH_ID]


def test_cli_hashtag_sort_latest_maps_to_1(monkeypatch):
    seen: list[int] = []

    async def _fake_iter(self, ch_id, *, count=20, max_count=0, sort_type=0,
                         error_sink=None):
        seen.append(sort_type)
        return [_aweme("700")]

    monkeypatch.setattr(DouyinWebAPI, "iter_challenge_awemes", _fake_iter)
    code, out, _ = _run_cli(["hashtag", CH_ID, "--sort", "latest"])
    assert code == 0
    assert seen == [1]
    assert json.loads(out.strip().splitlines()[0])["sort"] == "latest"


def test_cli_hashtag_default_sort_is_comprehensive(monkeypatch):
    seen: list[int] = []

    async def _fake_iter(self, ch_id, *, count=20, max_count=0, sort_type=0,
                         error_sink=None):
        seen.append(sort_type)
        return []

    monkeypatch.setattr(DouyinWebAPI, "iter_challenge_awemes", _fake_iter)
    _run_cli(["hashtag", CH_ID])
    assert seen == [0]


def test_cli_hashtag_forwards_max_and_count(monkeypatch):
    seen: list[tuple[int, int]] = []

    async def _fake_iter(self, ch_id, *, count=20, max_count=0, sort_type=0,
                         error_sink=None):
        seen.append((count, max_count))
        return []

    monkeypatch.setattr(DouyinWebAPI, "iter_challenge_awemes", _fake_iter)
    _run_cli(["hashtag", CH_ID, "--max", "5", "--count", "3"])
    assert seen == [(3, 5)]


def test_cli_hashtag_bad_url_exits_2():
    code, out, err = _run_cli(["hashtag", "https://www.douyin.com/video/700"])
    assert code == 2
    assert out == ""
    assert "Error:" in err


def test_cli_hashtag_missing_arg_exits_2():
    with pytest.raises(SystemExit) as exc:
        _run_cli(["hashtag"])
    assert exc.value.code == 2


def test_cli_hashtag_empty_result_is_not_error(monkeypatch):
    async def _fake_iter(self, ch_id, *, count=20, max_count=0, sort_type=0,
                         error_sink=None):
        return []

    monkeypatch.setattr(DouyinWebAPI, "iter_challenge_awemes", _fake_iter)
    code, out, err = _run_cli(["hashtag", CH_ID])
    assert code == 0
    assert out == ""
    assert "No results." in err


def test_cli_hashtag_need_login_hint(monkeypatch):
    async def _fake_iter(self, ch_id, *, count=20, max_count=0, sort_type=0,
                         error_sink=None):
        if error_sink is not None:
            error_sink.update({"reason": "http_403", "status_code": 403,
                               "hint": "need_login"})
        return []

    monkeypatch.setattr(DouyinWebAPI, "iter_challenge_awemes", _fake_iter)
    code, _, err = _run_cli(["hashtag", CH_ID])
    assert code == 0
    assert "http_403" in err
    assert "need_login" in err
    assert "doubi auth douyin" in err


def test_cli_hashtag_failure_exits_3(monkeypatch):
    async def _boom(self, ch_id, *, count=20, max_count=0, sort_type=0,
                    error_sink=None):
        raise RuntimeError("network down")

    monkeypatch.setattr(DouyinWebAPI, "iter_challenge_awemes", _boom)
    code, _, err = _run_cli(["hashtag", CH_ID])
    assert code == 3
    assert "network down" in err


def test_cli_hashtag_carries_mix_context_when_present(monkeypatch):
    """A 话题 video that is also inside a 合集 keeps its mix fields —
    the M6.56 plumbing must survive the M6.57 row projection."""
    aweme = _aweme("700")
    aweme["mix_info"] = {"mix_id": "999", "mix_name": "所属合集"}

    async def _fake_iter(self, ch_id, *, count=20, max_count=0, sort_type=0,
                         error_sink=None):
        return [aweme]

    monkeypatch.setattr(DouyinWebAPI, "iter_challenge_awemes", _fake_iter)
    code, out, _ = _run_cli(["hashtag", CH_ID])
    assert code == 0
    record = json.loads(out.strip())
    assert record["mix_id"] == "999"
    assert record["mix_name"] == "所属合集"


def test_hashtag_help_is_registered():
    from doubi.cli.main import _build_parser

    parser = _build_parser()
    out = io.StringIO()
    with redirect_stdout(out):
        with pytest.raises(SystemExit) as exc:
            parser.parse_args(["hashtag", "--help"])
    assert exc.value.code == 0
    text = out.getvalue()
    assert "--sort" in text
    assert "--max" in text
    assert "--cookies-file" in text
