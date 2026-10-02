"""Tests for M6.52 抖音 评论 + 回复: 2 endpoints.

The 2 endpoints (TikTokDL ``src/interface/comment.py``) are:

    iter_aweme_comments    /aweme/v1/web/comment/list/         data.comments
    iter_comment_replies   /aweme/v1/web/comment/list/reply/   data.comments
                                                          (+comment_id)

Both share the same cursor+count+has_more pagination shape and the
same ``data_key="comments"`` (the platform treats reply rows as
comment-shaped dicts server-side).

Tests monkey-patch ``DouyinWebAPI._request_json`` so no real traffic.
Both endpoints are in the M6.48 ``DOUYIN_SIGNED_PATHS`` whitelist
(added defensively in M6.52).
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


def _comment_row(cid: str = "", text: str = "", reply_count: int = 0) -> dict:
    return {
        "cid": cid or f"cid-{id(object())}",
        "text": text or f"comment-{cid}",
        "reply_count": reply_count,
        "user": {"nickname": "tester"},
        "create_time": 1700000000,
    }


def _page(rows: list[dict], *, has_more: bool = False,
          cursor: int | None = None) -> dict:
    return {
        "comments": rows,
        "cursor": cursor if cursor is not None else 0,
        "has_more": has_more,
    }


# ---------------------------------------------------------------------------
# iter_aweme_comments
# ---------------------------------------------------------------------------


async def test_iter_aweme_comments_calls_endpoint_with_correct_params(monkeypatch):
    """``iter_aweme_comments`` must hit ``/aweme/v1/web/comment/list/``
    with the static TikTokDL param shape (cut_version=1, item_type=0,
    pc_img_format=webp, version_code=170400, version_name=17.4.0)
    plus the per-aweme ``aweme_id``."""
    api = DouyinWebAPI()
    captured: dict = {}

    async def _fake(path, params, *, max_retries=3, error_sink=None):
        captured["path"] = path
        captured["params"] = params
        return _page([_comment_row("c1")])

    monkeypatch.setattr(api, "_request_json", _fake)

    rows = await api.iter_aweme_comments("aweme-12345")
    assert captured["path"] == "/aweme/v1/web/comment/list/"
    assert captured["params"]["aweme_id"] == "aweme-12345"
    assert captured["params"]["cut_version"] == "1"
    assert captured["params"]["item_type"] == "0"
    assert captured["params"]["pc_img_format"] == "webp"
    assert captured["params"]["version_code"] == "170400"
    assert captured["params"]["version_name"] == "17.4.0"
    assert rows[0]["cid"] == "c1"


async def test_iter_aweme_comments_blank_id_returns_empty(monkeypatch):
    """Empty aweme_id must NOT make a network call — return ``[]``.
    argparse catches this earlier at the CLI layer; we mirror it for
    direct API callers (e.g. a future GUI)."""
    api = DouyinWebAPI()
    call_count = {"n": 0}

    async def _fake(path, params, *, max_retries=3, error_sink=None):
        call_count["n"] += 1
        return _page([_comment_row("never")])

    monkeypatch.setattr(api, "_request_json", _fake)

    rows = await api.iter_aweme_comments("")
    assert rows == []
    assert call_count["n"] == 0


async def test_iter_aweme_comments_paginates_by_cursor(monkeypatch):
    """Page 1 reports has_more=True with cursor=20 → page 2 sends cursor=20.
    Page 2 reports has_more=False → loop ends."""
    api = DouyinWebAPI()
    state = {"n": 0}
    sent: list[dict] = []

    async def _fake(path, params, *, max_retries=3, error_sink=None):
        sent.append(dict(params))
        state["n"] += 1
        if state["n"] == 1:
            return _page([_comment_row("p1")], has_more=True, cursor=20)
        return _page([_comment_row("p2")], has_more=False)

    monkeypatch.setattr(api, "_request_json", _fake)

    rows = await api.iter_aweme_comments("a1")
    assert [r["cid"] for r in rows] == ["p1", "p2"]
    assert sent[0]["cursor"] == 0
    assert sent[1]["cursor"] == 20


# ---------------------------------------------------------------------------
# iter_comment_replies
# ---------------------------------------------------------------------------


async def test_iter_comment_replies_calls_endpoint_with_correct_params(monkeypatch):
    """``iter_comment_replies`` must hit ``/aweme/v1/web/comment/list/reply/``
    with both ``item_id`` + ``comment_id`` (TikTokDL ``comment.py:239-240``)."""
    api = DouyinWebAPI()
    captured: dict = {}

    async def _fake(path, params, *, max_retries=3, error_sink=None):
        captured["path"] = path
        captured["params"] = params
        return _page([_comment_row("r1")])

    monkeypatch.setattr(api, "_request_json", _fake)

    rows = await api.iter_comment_replies("aweme-1", "cid-99")
    assert captured["path"] == "/aweme/v1/web/comment/list/reply/"
    # Reply endpoint uses ``item_id`` (NOT ``aweme_id``) per TikTokDL line 239
    assert captured["params"]["item_id"] == "aweme-1"
    assert captured["params"]["comment_id"] == "cid-99"
    assert captured["params"]["cut_version"] == "1"
    assert captured["params"]["item_type"] == "0"
    assert captured["params"]["version_code"] == "170400"
    assert rows[0]["cid"] == "r1"


async def test_iter_comment_replies_blank_ids_return_empty(monkeypatch):
    """Either id blank → ``[]`` (no network call). Defensive: a future
    GUI might forget to validate the parent cid."""
    api = DouyinWebAPI()
    call_count = {"n": 0}

    async def _fake(path, params, *, max_retries=3, error_sink=None):
        call_count["n"] += 1
        return _page([_comment_row("never")])

    monkeypatch.setattr(api, "_request_json", _fake)

    assert await api.iter_comment_replies("", "cid-1") == []
    assert await api.iter_comment_replies("aweme-1", "") == []
    assert call_count["n"] == 0


# ---------------------------------------------------------------------------
# error_sink propagation
# ---------------------------------------------------------------------------


async def test_iter_aweme_comments_propagates_need_login_hint(monkeypatch):
    """Public comments are usually visible without login, but the
    platform may return risk-control on higher volumes. The hint
    must propagate through error_sink so the CLI can surface the
    M6.46 UX."""
    api = DouyinWebAPI()

    async def _fake(path, params, *, max_retries=3, error_sink=None):
        if error_sink is not None:
            error_sink.clear()
            error_sink["reason"] = "HTTP 403"
            error_sink["status_code"] = 403
            error_sink["hint"] = "need_login"
        return {}

    monkeypatch.setattr(api, "_request_json", _fake)

    sink: dict = {}
    rows = await api.iter_aweme_comments("a1", error_sink=sink)
    assert rows == []
    assert sink["hint"] == "need_login"


# ---------------------------------------------------------------------------
# WebSign whitelist (M6.48 dependency)
# ---------------------------------------------------------------------------


def test_both_comment_endpoints_in_signed_paths():
    """Both comment endpoints must be in DOUYIN_SIGNED_PATHS so the
    M6.48 WebSign layer attaches. Added defensively in M6.52."""
    assert "/aweme/v1/web/comment/list/" in DOUYIN_SIGNED_PATHS
    assert "/aweme/v1/web/comment/list/reply/" in DOUYIN_SIGNED_PATHS


# ---------------------------------------------------------------------------
# CLI: doubi comments
# ---------------------------------------------------------------------------


def _make_ns(**overrides):
    """Build a minimal argparse.Namespace the _cmd_comments handler accepts."""
    from argparse import Namespace

    ns = Namespace(
        verbose=False,
        config=None,
        command="comments",
        aweme_id="aweme-12345",
        kind="comments",
        comment_id=None,
        max=50,
        count=10,
        cookies_file=None,
        proxy=None,
    )
    for k, v in overrides.items():
        setattr(ns, k, v)
    return ns


def _patch_comments_iter(monkeypatch, *, per_kind_rows: dict[str, list[dict]]):
    """Install a fake on each iter method keyed on the kind."""
    from doubi.platforms.douyin.webapi import DouyinWebAPI

    async def _fake_iter_comments(
        self, aweme_id, *, count=10, max_count=0, error_sink=None,
    ):
        rows = per_kind_rows.get("comments", [])
        return rows[:max_count] if max_count else rows

    async def _fake_iter_replies(
        self, aweme_id, comment_id, *, count=3, max_count=0, error_sink=None,
    ):
        rows = per_kind_rows.get("replies", [])
        return rows[:max_count] if max_count else rows

    monkeypatch.setattr(DouyinWebAPI, "iter_aweme_comments", _fake_iter_comments)
    monkeypatch.setattr(
        DouyinWebAPI, "iter_comment_replies", _fake_iter_replies,
    )


async def test_cli_comments_default_emits_records_with_kind_tag(monkeypatch):
    """``doubi comments <aweme_id>`` (default --kind=comments) must
    tag every record with ``kind`` + ``kind_name`` + ``aweme_id``."""
    from doubi.cli.main import _cmd_comments

    _patch_comments_iter(monkeypatch, per_kind_rows={
        "comments": [_comment_row("c1"), _comment_row("c2")],
    })

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = await _cmd_comments(_make_ns(aweme_id="a1", kind="comments"))
    assert rc == 0
    lines = [json.loads(line) for line in buf.getvalue().splitlines() if line]
    assert len(lines) == 2
    assert {r["kind"] for r in lines} == {"comments"}
    assert {r["kind_name"] for r in lines} == {"评论"}
    assert {r["aweme_id"] for r in lines} == {"a1"}
    assert [r["cid"] for r in lines] == ["c1", "c2"]


async def test_cli_comments_replies_requires_comment_id(monkeypatch):
    """``--kind=replies`` without ``--comment-id`` must exit 2 BEFORE
    any network call."""
    from doubi.cli.main import _cmd_comments

    _patch_comments_iter(monkeypatch, per_kind_rows={})

    buf_out, buf_err = io.StringIO(), io.StringIO()
    with redirect_stdout(buf_out):
        with redirect_stderr(buf_err):
            rc = await _cmd_comments(_make_ns(kind="replies", comment_id=None))
    assert rc == 2
    assert "comment-id" in buf_err.getvalue()


async def test_cli_comments_replies_emits_parent_comment_id(monkeypatch):
    """``--kind=replies`` rows must carry the parent ``comment_id``
    so downstream pipelines can correlate replies to the parent."""
    from doubi.cli.main import _cmd_comments

    _patch_comments_iter(monkeypatch, per_kind_rows={
        "replies": [_comment_row("r1"), _comment_row("r2")],
    })

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = await _cmd_comments(_make_ns(
            kind="replies", comment_id="cid-parent", aweme_id="a1",
        ))
    assert rc == 0
    lines = [json.loads(line) for line in buf.getvalue().splitlines() if line]
    assert len(lines) == 2
    assert {r["kind"] for r in lines} == {"replies"}
    assert {r["kind_name"] for r in lines} == {"评论回复"}
    assert {r["parent_comment_id"] for r in lines} == {"cid-parent"}
    assert [r["cid"] for r in lines] == ["r1", "r2"]


async def test_cli_comments_blank_aweme_id_returns_2(monkeypatch):
    """Blank aweme_id must exit 2 (CLI-side guard, BEFORE the webapi's
    ``return []`` defensive check)."""
    from doubi.cli.main import _cmd_comments

    _patch_comments_iter(monkeypatch, per_kind_rows={})

    buf_out, buf_err = io.StringIO(), io.StringIO()
    with redirect_stdout(buf_out):
        with redirect_stderr(buf_err):
            rc = await _cmd_comments(_make_ns(aweme_id=""))
    assert rc == 2
    assert "aweme_id" in buf_err.getvalue()


async def test_cli_comments_max_caps_output(monkeypatch):
    """``--max N`` must cap output rows (symmetric with hot/search)."""
    from doubi.cli.main import _cmd_comments

    _patch_comments_iter(monkeypatch, per_kind_rows={
        "comments": [_comment_row(f"c{i}") for i in range(20)],
    })

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = await _cmd_comments(_make_ns(aweme_id="a1", max=5))
    assert rc == 0
    lines = [json.loads(line) for line in buf.getvalue().splitlines() if line]
    assert len(lines) == 5


async def test_cli_comments_empty_results_returns_zero(monkeypatch):
    """No rows must still exit 0 — *no hits* is not an error."""
    from doubi.cli.main import _cmd_comments

    _patch_comments_iter(monkeypatch, per_kind_rows={"comments": []})

    buf_out, buf_err = io.StringIO(), io.StringIO()
    with redirect_stdout(buf_out):
        with redirect_stderr(buf_err):
            rc = await _cmd_comments(_make_ns(aweme_id="a1"))
    assert rc == 0
    assert buf_out.getvalue() == ""
    assert "No results." in buf_err.getvalue()


def test_cli_comments_parser_lists_kinds():
    """``--kind`` argparse choices must include both surfaces.
    A typo (``--kind xyz``) must be rejected at parse time."""
    from doubi.cli.main import _build_parser

    parser = _build_parser()
    args = parser.parse_args(["comments", "aweme-1"])
    assert args.kind == "comments"  # default
    assert args.max == 50
    assert args.count == 10

    args = parser.parse_args([
        "comments", "aweme-1",
        "--kind", "replies", "--comment-id", "cid-9",
    ])
    assert args.kind == "replies"
    assert args.comment_id == "cid-9"
