"""Tests for M6.50 抖音 hot 榜: 4 boards (抖音热榜 / 娱乐榜 / 社会榜 / 挑战榜).

The endpoint is ``/aweme/v1/web/hot/search/list/`` and returns
``data.word_list`` — a list of *hot-word* entries (NOT videos). Each
row has ``word``, ``hot_value``, ``position``, ``sentence_id``,
``video_count``, ``cover_url``.

Adapted from Johnserf-Shell/TikTokDownloader ``src/interface/hot.py``
(MIT). TikTokDL's hot.py is single-page (no cursor / search_id); we
preserve that contract — one HTTP GET per board.

These tests monkey-patch ``DouyinWebAPI._request_json`` so no real
network traffic. The hot endpoint is in the M6.48 ``DOUYIN_SIGNED_PATHS``
whitelist (defensively added in M6.50); a regression in either M6.48
or M6.50's whitelist write would cascade into ``test_hot_endpoint_in_signed_paths``.
"""

from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from doubi.platforms.douyin.webapi import (  # noqa: E402
    ALL_HOT_BOARDS,
    DouyinWebAPI,
    HOT_BOARD_NAMES,
    HOT_BOARD_PARAMS,
)
from doubi.platforms.douyin.sign import DOUYIN_SIGNED_PATHS  # noqa: E402


def _word_row(word: str, *, hot_value: int = 1000, position: int = 1,
              sentence_id: str = "", video_count: int = 10,
              cover_url: str = "") -> dict:
    """Hot-word entry the platform returns in ``data.word_list``."""
    return {
        "word": word,
        "hot_value": hot_value,
        "position": position,
        "sentence_id": sentence_id or f"sid-{word}",
        "video_count": video_count,
        "cover_url": cover_url or f"https://p.douyin.com/cover/{word}.jpg",
    }


def _hot_page(rows: list[dict]) -> dict:
    """Synthesize the platform's hot page dict shape."""
    return {"word_list": rows}


# ---------------------------------------------------------------------------
# module-level constants (HOT_BOARD_PARAMS / NAMES / ALL_HOT_BOARDS)
# ---------------------------------------------------------------------------


def test_hot_board_params_match_tiktokdl():
    """Pin the 4 boards' (board_type, board_sub_type) tuples against
    TikTokDL ``src/interface/hot.py`` lines 14-35.

    These are the only 4 boards the platform exposes via this endpoint;
    adding a new board means updating both the module-level map and
    this test.
    """
    assert HOT_BOARD_PARAMS == {
        "positive": (0, ""),
        "entertainment": (2, 2),
        "society": (2, 4),
        "challenge": (2, "hotspot_challenge"),
    }


def test_hot_board_names_have_chinese_labels():
    """Each board has a display name used by the CLI's ``--board all``
    JSONL stream (record.board_name). Without these the row is opaque."""
    assert set(HOT_BOARD_NAMES.keys()) == set(ALL_HOT_BOARDS)
    assert HOT_BOARD_NAMES["positive"] == "抖音热榜"
    assert HOT_BOARD_NAMES["entertainment"] == "娱乐榜"
    assert HOT_BOARD_NAMES["society"] == "社会榜"
    assert HOT_BOARD_NAMES["challenge"] == "挑战榜"


def test_all_hot_boards_is_canonical_order():
    """Order matters because ``--board all`` iterates this tuple in
    order; the platform returns roughly the same shape per board so
    the user-facing ordering should be ``positive → entertainment →
    society → challenge`` (TikTokDL's default board_params order)."""
    assert ALL_HOT_BOARDS == ("positive", "entertainment", "society", "challenge")


# ---------------------------------------------------------------------------
# DouyinWebAPI.get_hot_list
# ---------------------------------------------------------------------------


async def test_get_hot_list_calls_endpoint_with_correct_board_params(monkeypatch):
    """Each board maps to its own (board_type, board_sub_type) and
    the endpoint carries the static param shape TikTokDL pins
    (detail_list=1, source=6, version_code=170400, version_name=17.4.0).
    """
    api = DouyinWebAPI()
    captured: dict = {}

    async def _fake(path, params, *, max_retries=3, error_sink=None):
        captured["path"] = path
        captured["params"] = params
        return _hot_page([_word_row("foo")])

    monkeypatch.setattr(api, "_request_json", _fake)

    for board in ALL_HOT_BOARDS:
        results = await api.get_hot_list(board)
        assert captured["path"] == "/aweme/v1/web/hot/search/list/"
        assert captured["params"]["board_type"] == HOT_BOARD_PARAMS[board][0]
        assert captured["params"]["board_sub_type"] == HOT_BOARD_PARAMS[board][1]
        assert captured["params"]["detail_list"] == "1"
        assert captured["params"]["source"] == "6"
        assert captured["params"]["version_code"] == "170400"
        assert captured["params"]["version_name"] == "17.4.0"
        assert len(results) == 1
        assert results[0]["word"] == "foo"


async def test_get_hot_list_returns_empty_for_unknown_board(monkeypatch):
    """Bad board name must NOT make a network call — return ``[]`` and
    leave the platform untouched. The argparse ``choices`` constraint
    catches this at the CLI layer; we mirror that here for direct API
    callers (e.g. a future GUI)."""
    api = DouyinWebAPI()
    call_count = {"n": 0}

    async def _fake(path, params, *, max_retries=3, error_sink=None):
        call_count["n"] += 1
        return _hot_page([_word_row("never")])

    monkeypatch.setattr(api, "_request_json", _fake)

    results = await api.get_hot_list("sport")
    assert results == []
    assert call_count["n"] == 0


async def test_get_hot_list_caps_max_count(monkeypatch):
    """``max_count`` truncates the platform's page in-place. The platform
    typically returns ~50 rows; ``max_count=3`` must yield exactly 3."""
    api = DouyinWebAPI()

    async def _fake(path, params, *, max_retries=3, error_sink=None):
        return _hot_page([_word_row(f"w{i}") for i in range(50)])

    monkeypatch.setattr(api, "_request_json", _fake)

    results = await api.get_hot_list("positive", max_count=3)
    assert len(results) == 3
    assert [r["word"] for r in results] == ["w0", "w1", "w2"]


async def test_get_hot_list_returns_empty_when_word_list_missing(monkeypatch):
    """Defensive: the platform can return an empty body (e.g. 200 with
    no JSON, or a JSON object with no ``word_list``). The method must
    return ``[]`` and NOT raise."""
    api = DouyinWebAPI()

    async def _fake_empty(path, params, *, max_retries=3, error_sink=None):
        return {}

    async def _fake_non_list(path, params, *, max_retries=3, error_sink=None):
        return {"word_list": None}

    monkeypatch.setattr(api, "_request_json", _fake_empty)
    assert await api.get_hot_list("positive") == []

    monkeypatch.setattr(api, "_request_json", _fake_non_list)
    assert await api.get_hot_list("positive") == []


async def test_get_hot_list_propagates_error_sink(monkeypatch):
    """WebAPI risk-control hints (M6.46) must flow into error_sink so
    the CLI can surface 「需要登录抖音」 / 5xx / transient just like
    the search family."""
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
    results = await api.get_hot_list("entertainment", error_sink=sink)
    assert results == []
    assert sink["hint"] == "need_login"


# ---------------------------------------------------------------------------
# DOUYIN_SIGNED_PATHS whitelist (M6.48 dependency)
# ---------------------------------------------------------------------------


def test_hot_endpoint_in_signed_paths():
    """The hot endpoint must trigger WebSign (M6.48 dependency). The
    whitelist entry is defensive — TikTokDL's hot.py doesn't add WebSign
    explicitly, but the platform may add it to the secsdk protectedHost
    table at any time. Over-signing is harmless (TikTokDL note)."""
    assert "/aweme/v1/web/hot/search/list/" in DOUYIN_SIGNED_PATHS


# ---------------------------------------------------------------------------
# CLI: doubi hot
# ---------------------------------------------------------------------------


def _make_ns(**overrides):
    """Build a minimal argparse.Namespace the _cmd_hot handler accepts."""
    from argparse import Namespace

    ns = Namespace(
        verbose=False,
        config=None,
        command="hot",
        board="all",
        max=50,
        cookies_file=None,
        proxy=None,
    )
    for k, v in overrides.items():
        setattr(ns, k, v)
    return ns


def _patch_hot_api(monkeypatch, *, per_board_pages: dict[str, list[dict]]):
    """Install a fake ``get_hot_list`` keyed on the board name.

    ``per_board_pages`` maps ``board → rows``. The fake ignores other
    args and returns a single page; tests then assert JSONL output.

    DouyinWebAPI is a lazy import inside ``_cmd_hot`` — not at module
    level — so we patch the class on its actual source module.
    """
    from doubi.platforms.douyin.webapi import DouyinWebAPI

    async def _fake_get_hot_list(self, board, *, max_count=0, error_sink=None):
        rows = per_board_pages.get(board, [])
        return rows[:max_count] if max_count else rows

    monkeypatch.setattr(
        DouyinWebAPI, "get_hot_list", _fake_get_hot_list,
    )


async def test_cli_hot_all_iterates_every_board_in_canonical_order(monkeypatch):
    """``--board all`` (the default) must hit all 4 boards and emit
    rows in HOT_BOARD_PARAMS order. Each JSONL record carries
    ``board`` + ``board_name`` so the stream is self-describing."""
    from doubi.cli.main import _cmd_hot

    pages = {
        "positive": [_word_row("抖音热榜1", position=1)],
        "entertainment": [_word_row("娱乐1", position=1), _word_row("娱乐2", position=2)],
        "society": [_word_row("社会1", position=1)],
        "challenge": [_word_row("挑战1", position=1)],
    }
    _patch_hot_api(monkeypatch, per_board_pages=pages)

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = await _cmd_hot(_make_ns(board="all", max=10))
    assert rc == 0
    lines = [json.loads(line) for line in buf.getvalue().splitlines() if line]
    assert len(lines) == 5
    # Order must match ALL_HOT_BOARDS
    assert [r["board"] for r in lines] == [
        "positive", "entertainment", "entertainment", "society", "challenge",
    ]
    assert [r["board_name"] for r in lines] == [
        "抖音热榜", "娱乐榜", "娱乐榜", "社会榜", "挑战榜",
    ]


async def test_cli_hot_single_board_emits_records_with_board_tag(monkeypatch):
    """Single-board mode (e.g. ``--board entertainment``) must still
    tag every record with ``board`` + ``board_name`` so downstream
    pipelines don't have to special-case the schema."""
    from doubi.cli.main import _cmd_hot

    _patch_hot_api(monkeypatch, per_board_pages={
        "entertainment": [_word_row("赵丽颖")],
    })

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = await _cmd_hot(_make_ns(board="entertainment"))
    assert rc == 0
    lines = [json.loads(line) for line in buf.getvalue().splitlines() if line]
    assert len(lines) == 1
    assert lines[0]["board"] == "entertainment"
    assert lines[0]["board_name"] == "娱乐榜"
    assert lines[0]["word"] == "赵丽颖"


async def test_cli_hot_max_caps_each_board(monkeypatch):
    """``--max`` is *per-board*, not total. With ``--max 1 --board all``,
    we expect at most 1 row from each of the 4 boards (4 rows total)."""
    from doubi.cli.main import _cmd_hot

    pages = {
        b: [_word_row(f"{b}-{i}") for i in range(5)]
        for b in ALL_HOT_BOARDS
    }
    _patch_hot_api(monkeypatch, per_board_pages=pages)

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = await _cmd_hot(_make_ns(board="all", max=1))
    assert rc == 0
    lines = [json.loads(line) for line in buf.getvalue().splitlines() if line]
    assert len(lines) == 4
    # Each board contributed exactly 1 row.
    boards_hit = sorted({r["board"] for r in lines})
    assert boards_hit == sorted(ALL_HOT_BOARDS)


async def test_cli_hot_empty_results_returns_zero(monkeypatch):
    """No rows on any board must still exit 0 — *no hits* is not an
    error. The CLI must print a stderr hint when at least one board's
    error_sink was filled, otherwise a generic "No results." message.
    """
    from contextlib import redirect_stderr

    from doubi.cli.main import _cmd_hot

    _patch_hot_api(monkeypatch, per_board_pages={b: [] for b in ALL_HOT_BOARDS})

    buf_out, buf_err = io.StringIO(), io.StringIO()
    with redirect_stdout(buf_out):
        with redirect_stderr(buf_err):
            rc = await _cmd_hot(_make_ns(board="all"))
    assert rc == 0
    assert buf_out.getvalue() == ""
    assert "No results." in buf_err.getvalue()


def test_cli_hot_parser_lists_all_boards():
    """``--board`` argparse choices must include ``all`` + the 4 boards.
    A typo (``--board sport``) must be rejected at parse time."""
    from doubi.cli.main import _build_parser

    parser = _build_parser()
    args = parser.parse_args(["hot"])
    # default is "all"
    assert args.board == "all"
    assert args.max == 50

    args = parser.parse_args(["hot", "--board", "entertainment", "--max", "10"])
    assert args.board == "entertainment"
    assert args.max == 10
