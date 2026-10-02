"""Tests for M6.54 抖音 关注列表 + 粉丝列表: 2 endpoints.

**TikTokDL 无源** — Survey §8.1 item 10 explicitly marked the
following/follower endpoints as ❌ (TikTokDL ``User`` only does
``profile/other``). M6.54 is a **DouBi native implementation**
following the public Douyin web API convention + reusing the M6.51
``_cursor_paginate`` helper. CHANGELOG §首段 flags this distinction
explicitly — do not credit this milestone to TikTokDL.

The 2 endpoints are:

    iter_user_following    /aweme/v1/web/user/following/list/    data.followings
    iter_user_followers    /aweme/v1/web/user/follower/list/    data.followers

Both share the same cursor+count+has_more shape (identical to
M6.51 favorites family + M6.52 comments family).

Tests monkey-patch ``DouyinWebAPI._request_json`` so no real traffic.
Both endpoints are in the M6.48 ``DOUYIN_SIGNED_PATHS`` whitelist
(added defensively in M6.54).
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


def _following_row(sec_uid: str = "") -> dict:
    return {
        "sec_uid": sec_uid or f"sec-{id(object())}",
        "nickname": f"user-{sec_uid}",
        "avatar_url": "https://p.douyin.com/avatar.jpg",
    }


def _follower_row(sec_uid: str = "") -> dict:
    return {
        "sec_uid": sec_uid or f"sec-{id(object())}",
        "nickname": f"follower-{sec_uid}",
        "avatar_url": "https://p.douyin.com/avatar.jpg",
    }


def _page(data_key: str, rows: list[dict], *, has_more: bool = False,
          cursor: int | None = None) -> dict:
    return {
        data_key: rows,
        "cursor": cursor if cursor is not None else 0,
        "has_more": has_more,
    }


# ---------------------------------------------------------------------------
# iter_user_following
# ---------------------------------------------------------------------------


async def test_iter_user_following_calls_endpoint_with_correct_params(monkeypatch):
    """``iter_user_following`` must hit
    ``/aweme/v1/web/user/following/list/`` with ``data.followings`` and
    forward ``user_id`` + ``sec_user_id`` (both must be present per
    public Douyin web API convention).
    """
    api = DouyinWebAPI()
    captured: dict = {}

    async def _fake(path, params, *, max_retries=3, error_sink=None):
        captured["path"] = path
        captured["params"] = params
        return _page("followings", [_following_row("s1")])

    monkeypatch.setattr(api, "_request_json", _fake)

    rows = await api.iter_user_following("sec-12345")
    assert captured["path"] == "/aweme/v1/web/user/following/list/"
    assert captured["params"]["user_id"] == "sec-12345"
    assert captured["params"]["sec_user_id"] == "sec-12345"
    assert captured["params"]["source"] == "following"
    assert captured["params"]["version_code"] == "170400"
    assert captured["params"]["version_name"] == "17.4.0"
    assert rows[0]["sec_uid"] == "s1"


async def test_iter_user_following_blank_id_returns_empty(monkeypatch):
    """Empty sec_user_id must NOT make a network call — return ``[]``.
    argparse catches this earlier at the CLI layer; we mirror it for
    direct API callers (e.g. a future GUI)."""
    api = DouyinWebAPI()
    call_count = {"n": 0}

    async def _fake(path, params, *, max_retries=3, error_sink=None):
        call_count["n"] += 1
        return _page("followings", [_following_row("never")])

    monkeypatch.setattr(api, "_request_json", _fake)

    rows = await api.iter_user_following("")
    assert rows == []
    assert call_count["n"] == 0


async def test_iter_user_following_paginates_by_cursor(monkeypatch):
    """Page 1 reports has_more=True with cursor=20 → page 2 sends cursor=20.
    Page 2 reports has_more=False → loop ends.
    """
    api = DouyinWebAPI()
    state = {"n": 0}
    sent: list[dict] = []

    async def _fake(path, params, *, max_retries=3, error_sink=None):
        sent.append(dict(params))
        state["n"] += 1
        if state["n"] == 1:
            return _page("followings", [_following_row("p1")],
                         has_more=True, cursor=20)
        return _page("followings", [_following_row("p2")], has_more=False)

    monkeypatch.setattr(api, "_request_json", _fake)

    rows = await api.iter_user_following("sec-1")
    assert [r["sec_uid"] for r in rows] == ["p1", "p2"]
    assert sent[0]["cursor"] == 0
    assert sent[1]["cursor"] == 20


# ---------------------------------------------------------------------------
# iter_user_followers
# ---------------------------------------------------------------------------


async def test_iter_user_followers_calls_endpoint_with_correct_params(monkeypatch):
    """``iter_user_followers`` must hit
    ``/aweme/v1/web/user/follower/list/`` with ``data.followers``."""
    api = DouyinWebAPI()
    captured: dict = {}

    async def _fake(path, params, *, max_retries=3, error_sink=None):
        captured["path"] = path
        captured["params"] = params
        return _page("followers", [_follower_row("f1")])

    monkeypatch.setattr(api, "_request_json", _fake)

    rows = await api.iter_user_followers("sec-12345")
    assert captured["path"] == "/aweme/v1/web/user/follower/list/"
    assert captured["params"]["user_id"] == "sec-12345"
    assert captured["params"]["sec_user_id"] == "sec-12345"
    assert captured["params"]["source"] == "follower"
    assert rows[0]["sec_uid"] == "f1"


async def test_iter_user_followers_blank_id_returns_empty(monkeypatch):
    """Same defensive guard as ``iter_user_following``."""
    api = DouyinWebAPI()
    call_count = {"n": 0}

    async def _fake(path, params, *, max_retries=3, error_sink=None):
        call_count["n"] += 1
        return _page("followers", [_follower_row("never")])

    monkeypatch.setattr(api, "_request_json", _fake)

    rows = await api.iter_user_followers("")
    assert rows == []
    assert call_count["n"] == 0


# ---------------------------------------------------------------------------
# error_sink propagation (login-gated UX)
# ---------------------------------------------------------------------------


async def test_iter_user_following_propagates_need_login_hint(monkeypatch):
    """The platform gates following/follower on login. A 401 / risk-
    control response must land in error_sink with hint=need_login so
    the CLI can surface 「请先登录抖音」 (M6.46 UX)."""
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
    rows = await api.iter_user_following("sec-1", error_sink=sink)
    assert rows == []
    assert sink["hint"] == "need_login"


# ---------------------------------------------------------------------------
# WebSign whitelist (M6.48 dependency)
# ---------------------------------------------------------------------------


def test_both_user_relation_endpoints_in_signed_paths():
    """Both following + followers endpoints must be in DOUYIN_SIGNED_PATHS
    so the M6.48 WebSign layer attaches. Added defensively in M6.54."""
    assert "/aweme/v1/web/user/following/list/" in DOUYIN_SIGNED_PATHS
    assert "/aweme/v1/web/user/follower/list/" in DOUYIN_SIGNED_PATHS


# ---------------------------------------------------------------------------
# CLI: doubi user
# ---------------------------------------------------------------------------


def _make_ns(**overrides):
    """Build a minimal argparse.Namespace the _cmd_user handler accepts."""
    from argparse import Namespace

    ns = Namespace(
        verbose=False,
        config=None,
        command="user",
        sec_uid="sec-12345",
        kind="following",
        max=50,
        count=20,
        cookies_file=None,
        proxy=None,
    )
    for k, v in overrides.items():
        setattr(ns, k, v)
    return ns


def _patch_user_iter(monkeypatch, *, per_kind_rows: dict[str, list[dict]]):
    """Install fakes on each iter_user_* method keyed on the kind."""
    from doubi.platforms.douyin.webapi import DouyinWebAPI

    async def _fake_iter_following(
        self, sec_user_id, *, count=20, max_count=0, error_sink=None,
    ):
        rows = per_kind_rows.get("following", [])
        return rows[:max_count] if max_count else rows

    async def _fake_iter_followers(
        self, sec_user_id, *, count=20, max_count=0, error_sink=None,
    ):
        rows = per_kind_rows.get("followers", [])
        return rows[:max_count] if max_count else rows

    monkeypatch.setattr(DouyinWebAPI, "iter_user_following", _fake_iter_following)
    monkeypatch.setattr(
        DouyinWebAPI, "iter_user_followers", _fake_iter_followers,
    )


async def test_cli_user_default_following_emits_records_with_kind_tag(monkeypatch):
    """``doubi user <sec_uid>`` (default --kind=following) must tag
    every record with ``kind`` + ``kind_name`` + ``target_sec_uid``.
    The row's own ``sec_uid`` MUST be preserved (not clobbered by
    the parent's id) — otherwise downstream loses row identity.
    """
    from doubi.cli.main import _cmd_user

    _patch_user_iter(monkeypatch, per_kind_rows={
        "following": [_following_row("f1"), _following_row("f2")],
    })

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = await _cmd_user(_make_ns(sec_uid="sec-1", kind="following"))
    assert rc == 0
    lines = [json.loads(line) for line in buf.getvalue().splitlines() if line]
    assert len(lines) == 2
    assert {r["kind"] for r in lines} == {"following"}
    assert {r["kind_name"] for r in lines} == {"我关注的人"}
    # Each row keeps its own sec_uid (NOT clobbered by parent)
    assert [r["sec_uid"] for r in lines] == ["f1", "f2"]
    # The parent (whose relations we're listing) is in target_sec_uid
    assert {r["target_sec_uid"] for r in lines} == {"sec-1"}


async def test_cli_user_followers_kind_emits_records_with_kind_tag(monkeypatch):
    """``--kind=followers`` rows carry ``kind_name="关注我的人"`` and
    preserve the row's own ``sec_uid``.
    """
    from doubi.cli.main import _cmd_user

    _patch_user_iter(monkeypatch, per_kind_rows={
        "followers": [_follower_row("f1")],
    })

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = await _cmd_user(_make_ns(sec_uid="sec-1", kind="followers"))
    assert rc == 0
    lines = [json.loads(line) for line in buf.getvalue().splitlines() if line]
    assert len(lines) == 1
    assert lines[0]["kind"] == "followers"
    assert lines[0]["kind_name"] == "关注我的人"
    assert lines[0]["sec_uid"] == "f1"  # row's own identity preserved
    assert lines[0]["target_sec_uid"] == "sec-1"  # parent


async def test_cli_user_blank_sec_uid_returns_2(monkeypatch):
    """Blank sec_uid must exit 2 (CLI-side guard, BEFORE the webapi's
    ``return []`` defensive check)."""
    from doubi.cli.main import _cmd_user

    _patch_user_iter(monkeypatch, per_kind_rows={})

    buf_out, buf_err = io.StringIO(), io.StringIO()
    with redirect_stdout(buf_out):
        with redirect_stderr(buf_err):
            rc = await _cmd_user(_make_ns(sec_uid=""))
    assert rc == 2
    assert "sec_uid" in buf_err.getvalue()


async def test_cli_user_max_caps_output(monkeypatch):
    """``--max N`` must cap output rows (symmetric with hot/search)."""
    from doubi.cli.main import _cmd_user

    _patch_user_iter(monkeypatch, per_kind_rows={
        "following": [_following_row(f"f{i}") for i in range(20)],
    })

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = await _cmd_user(_make_ns(sec_uid="sec-1", max=5))
    assert rc == 0
    lines = [json.loads(line) for line in buf.getvalue().splitlines() if line]
    assert len(lines) == 5


async def test_cli_user_empty_results_returns_zero(monkeypatch):
    """No rows must still exit 0 — *no hits* is not an error."""
    from doubi.cli.main import _cmd_user

    _patch_user_iter(monkeypatch, per_kind_rows={"following": []})

    buf_out, buf_err = io.StringIO(), io.StringIO()
    with redirect_stdout(buf_out):
        with redirect_stderr(buf_err):
            rc = await _cmd_user(_make_ns(sec_uid="sec-1"))
    assert rc == 0
    assert buf_out.getvalue() == ""
    assert "No results." in buf_err.getvalue()


def test_cli_user_parser_lists_kinds():
    """``--kind`` argparse choices must include both relations.
    A typo (``--kind xyz``) must be rejected at parse time."""
    from doubi.cli.main import _build_parser

    parser = _build_parser()
    args = parser.parse_args(["user", "sec-1"])
    assert args.kind == "following"  # default
    assert args.max == 50
    assert args.count == 20

    args = parser.parse_args([
        "user", "sec-1", "--kind", "followers", "--max", "10",
    ])
    assert args.kind == "followers"
    assert args.max == 10
