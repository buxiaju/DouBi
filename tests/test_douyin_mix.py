"""Tests for M6.56 抖音 合集（MIX）标题/ID 回查 — Survey item 11.

Adapted from Johnserf-Shell/TikTokDownloader:

    src/interface/mix.py:86-88          Mix.__get_mix_id
    src/extract/extractor.py:1546-1548  Extractor.extract_mix_id

whose body is literally ``safe_extract(data, "mix_info.mix_id")``.

Upstream resolves the id with a *second* network round-trip
(``await self.detail.run()``) because its ``Mix`` object is constructed
before any aweme is in hand. DouBi's caller already holds either the
mix_id (from the URL) or an aweme dict (from ``get_video_detail``), so
M6.56 keeps the same dotted-lookup semantics but drops the redundant
request. The deliberate deltas from upstream are covered by
``test_extract_mix_ref_*`` below and flagged in CHANGELOG M6.56 克己清单.

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

from doubi.platforms.douyin.adapter import DouyinAdapter  # noqa: E402
from doubi.platforms.douyin.sign import DOUYIN_SIGNED_PATHS  # noqa: E402
from doubi.platforms.douyin.webapi import (  # noqa: E402
    DouyinWebAPI,
    extract_mix_ref,
    format_mix_title,
)

MIX_ID = "7663019958858680347"


# ---------------------------------------------------------------------------
# extract_mix_ref — the ported primitive
# ---------------------------------------------------------------------------


def test_extract_mix_ref_reads_dotted_mix_info_mix_id():
    """Parity with TikTokDL ``safe_extract(data, "mix_info.mix_id")``."""
    aweme = {"aweme_id": "1", "mix_info": {"mix_id": MIX_ID, "mix_name": "我的合集"}}
    assert extract_mix_ref(aweme)["mix_id"] == MIX_ID
    assert extract_mix_ref(aweme)["mix_name"] == "我的合集"


def test_extract_mix_ref_coerces_int_mix_id_to_str():
    """The platform sends mix_id as int on some endpoints and str on
    others. Callers compare it against URL path segments (always str),
    so the coercion lives here and nowhere else."""
    ref = extract_mix_ref({"mix_info": {"mix_id": 7663019958858680347}})
    assert ref["mix_id"] == "7663019958858680347"
    assert isinstance(ref["mix_id"], str)


def test_extract_mix_ref_missing_mix_info_returns_empty():
    """A video that is not part of any 合集 — the common case. Upstream
    returns "" here; DouBi returns {} so callers branch on truthiness
    without having to special-case the empty string."""
    assert extract_mix_ref({"aweme_id": "1"}) == {}
    assert extract_mix_ref({"aweme_id": "1", "mix_info": {}}) == {}
    assert extract_mix_ref({"aweme_id": "1", "mix_info": None}) == {}


def test_extract_mix_ref_blank_mix_id_returns_empty():
    """Upstream ``safe_extract`` treats falsy intermediate values as a
    miss, so ``mix_id: ""`` and ``mix_id: 0`` must both fall through."""
    assert extract_mix_ref({"mix_info": {"mix_id": ""}}) == {}
    assert extract_mix_ref({"mix_info": {"mix_id": None}}) == {}


def test_extract_mix_ref_non_dict_input_is_safe():
    """Defensive: enumeration helpers sometimes hand us non-dict items."""
    assert extract_mix_ref(None) == {}          # type: ignore[arg-type]
    assert extract_mix_ref("nope") == {}        # type: ignore[arg-type]
    assert extract_mix_ref({"mix_info": "nope"}) == {}


def test_extract_mix_ref_drops_blank_name_and_desc():
    """Only non-blank optional fields are emitted, so a consumer never
    has to distinguish "no name" from "name that is whitespace"."""
    ref = extract_mix_ref({"mix_info": {"mix_id": MIX_ID, "mix_name": "   ",
                                        "mix_desc": ""}})
    assert ref == {"mix_id": MIX_ID}
    assert "mix_name" not in ref
    assert "mix_desc" not in ref


def test_extract_mix_ref_strips_name_whitespace():
    ref = extract_mix_ref({"mix_info": {"mix_id": MIX_ID, "mix_name": "  名字  "}})
    assert ref["mix_name"] == "名字"


def test_extract_mix_ref_keeps_desc_when_present():
    ref = extract_mix_ref({"mix_info": {"mix_id": MIX_ID, "mix_desc": " 说明 "}})
    assert ref["mix_desc"] == "说明"


def test_extract_mix_ref_does_not_mutate_input():
    aweme = {"mix_info": {"mix_id": MIX_ID, "mix_name": " n "}}
    extract_mix_ref(aweme)
    assert aweme == {"mix_info": {"mix_id": MIX_ID, "mix_name": " n "}}


# ---------------------------------------------------------------------------
# format_mix_title
# ---------------------------------------------------------------------------


def test_format_mix_title_prefers_name():
    assert format_mix_title({"mix_name": "深夜聊天室"}, MIX_ID) == "抖音合集《深夜聊天室》"


def test_format_mix_title_falls_back_to_id():
    """M6.45 behaviour preserved: the pre-M6.56 placeholder was exactly
    ``抖音合集 {mix_id}`` and must not change shape."""
    assert format_mix_title({}, MIX_ID) == f"抖音合集 {MIX_ID}"


def test_format_mix_title_uses_ref_id_when_no_fallback():
    assert format_mix_title({"mix_id": "42"}) == "抖音合集 42"


def test_format_mix_title_no_id_at_all():
    assert format_mix_title({}) == "抖音合集"


def test_format_mix_title_blank_name_ignored():
    """Whitespace is not a name — must not produce 《   》."""
    assert format_mix_title({"mix_name": "   "}, MIX_ID) == f"抖音合集 {MIX_ID}"


def test_format_mix_title_handles_none():
    assert format_mix_title(None, MIX_ID) == f"抖音合集 {MIX_ID}"  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# DouyinWebAPI.resolve_mix_ref — probe ordering
# ---------------------------------------------------------------------------


def _api_with(monkeypatch, *, detail=None, mix_aweme=None, calls=None):
    """Build a DouyinWebAPI whose two probes are stubbed.

    ``calls`` (a list) records which probe ran, in order — several tests
    assert *which* request we avoided, not just what came back.
    """
    api = DouyinWebAPI(timeout=5.0)
    log = calls if calls is not None else []

    async def _fake_get_mix_detail(mix_id):
        log.append(("mix_detail", mix_id))
        return detail

    async def _fake_get_mix_aweme(mix_id, *, cursor=0, count=20, error_sink=None):
        log.append(("mix_aweme", mix_id))
        if mix_aweme is None:
            return {"items": [], "has_more": False, "max_cursor": 0}
        return mix_aweme

    monkeypatch.setattr(api, "get_mix_detail", _fake_get_mix_detail)
    monkeypatch.setattr(api, "get_mix_aweme", _fake_get_mix_aweme)
    return api


def _page(awemes: list[dict]) -> dict:
    return {"items": awemes, "has_more": False, "max_cursor": 0}


def test_resolve_mix_ref_prefers_mix_detail_when_it_has_a_name(monkeypatch):
    """Cheapest happy path: ``/mix/detail/`` answers with a name, so the
    heavier ``/mix/aweme/`` page-1 request is never issued."""
    calls: list = []
    api = _api_with(
        monkeypatch,
        detail={"mix_id": MIX_ID, "mix_name": "深夜聊天室"},
        calls=calls,
    )
    ref = asyncio.run(api.resolve_mix_ref(mix_id=MIX_ID))
    assert ref["mix_name"] == "深夜聊天室"
    assert calls == [("mix_detail", MIX_ID)]


def test_resolve_mix_ref_falls_back_to_aweme_page1(monkeypatch):
    """``/mix/detail/`` is routinely 403'd for anonymous sessions — the
    M6.45 fallback (page-1 awemes carry ``mix_info``) must still run."""
    calls: list = []
    api = _api_with(
        monkeypatch,
        detail=None,
        mix_aweme=_page([{"aweme_id": "1",
                          "mix_info": {"mix_id": MIX_ID, "mix_name": "回退名字"}}]),
        calls=calls,
    )
    ref = asyncio.run(api.resolve_mix_ref(mix_id=MIX_ID))
    assert ref["mix_name"] == "回退名字"
    assert calls == [("mix_detail", MIX_ID), ("mix_aweme", MIX_ID)]


def test_resolve_mix_ref_detail_without_name_still_tries_page1(monkeypatch):
    """A 200 from ``/mix/detail/`` that carries only the id is not an
    answer — keep probing instead of returning a nameless ref."""
    calls: list = []
    api = _api_with(
        monkeypatch,
        detail={"mix_id": MIX_ID},
        mix_aweme=_page([{"aweme_id": "1",
                          "mix_info": {"mix_id": MIX_ID, "mix_name": "补上的名字"}}]),
        calls=calls,
    )
    ref = asyncio.run(api.resolve_mix_ref(mix_id=MIX_ID))
    assert ref["mix_name"] == "补上的名字"
    assert [c[0] for c in calls] == ["mix_detail", "mix_aweme"]


def test_resolve_mix_ref_returns_id_when_nothing_is_named(monkeypatch):
    """Both probes fail to produce a name, but the 合集 exists. Returning
    the id (not {}) lets a caller still build a container."""
    api = _api_with(monkeypatch, detail=None, mix_aweme=_page([]))
    ref = asyncio.run(api.resolve_mix_ref(mix_id=MIX_ID))
    assert ref == {"mix_id": MIX_ID}


def test_resolve_mix_ref_forwarded_error_sink_on_total_miss(monkeypatch):
    """``error_sink`` reaches the last request issued, so a caller can
    tell "need_login" apart from "no such 合集"."""
    api = _api_with(monkeypatch, detail=None, mix_aweme=_page([]))

    async def _fake_with_error(mix_id, *, cursor=0, count=20, error_sink=None):
        if error_sink is not None:
            error_sink.update({"reason": "http_403", "status_code": 403,
                               "hint": "need_login"})
        return _page([])

    monkeypatch.setattr(api, "get_mix_aweme", _fake_with_error)
    sink: dict = {}
    ref = asyncio.run(api.resolve_mix_ref(mix_id=MIX_ID, error_sink=sink))
    assert ref == {"mix_id": MIX_ID}
    assert sink["hint"] == "need_login"


def test_resolve_mix_ref_resolves_id_from_aweme_id(monkeypatch):
    """The TikTokDL ``Mix.__get_mix_id`` shape: caller has only a video,
    the 合集 id comes off that video's own detail."""
    api = DouyinWebAPI(timeout=5.0)
    detail_calls: list = []

    async def _fake_get_video_detail(aweme_id):
        detail_calls.append(aweme_id)
        return {"aweme_id": aweme_id,
                "mix_info": {"mix_id": MIX_ID, "mix_name": "来自单条视频"}}

    async def _no_mix_detail(mix_id):
        return None

    async def _no_mix_aweme(mix_id, *, cursor=0, count=20, error_sink=None):
        return _page([])

    monkeypatch.setattr(api, "get_video_detail", _fake_get_video_detail)
    monkeypatch.setattr(api, "get_mix_detail", _no_mix_detail)
    monkeypatch.setattr(api, "get_mix_aweme", _no_mix_aweme)

    ref = asyncio.run(api.resolve_mix_ref(aweme_id="700"))
    assert ref["mix_id"] == MIX_ID
    assert ref["mix_name"] == "来自单条视频"
    assert detail_calls == ["700"]


def test_resolve_mix_ref_aweme_without_mix_info_returns_empty(monkeypatch):
    """A video that belongs to no 合集 → {}, and no further probes."""
    api = DouyinWebAPI(timeout=5.0)
    calls: list = []

    async def _fake_get_video_detail(aweme_id):
        return {"aweme_id": aweme_id}

    async def _no_mix_detail(mix_id):
        calls.append("mix_detail")
        return None

    monkeypatch.setattr(api, "get_video_detail", _fake_get_video_detail)
    monkeypatch.setattr(api, "get_mix_detail", _no_mix_detail)

    assert asyncio.run(api.resolve_mix_ref(aweme_id="700")) == {}
    assert calls == []


def test_resolve_mix_ref_no_arguments_returns_empty(monkeypatch):
    """Neither id nor aweme_id → no request at all."""
    calls: list = []
    api = _api_with(monkeypatch, calls=calls)
    assert asyncio.run(api.resolve_mix_ref()) == {}
    assert calls == []


def test_resolve_mix_ref_aweme_lookup_failure_returns_empty(monkeypatch):
    """Detail 403 → we cannot even learn the id; {} not a crash."""
    api = DouyinWebAPI(timeout=5.0)

    async def _fake_get_video_detail(aweme_id):
        return None

    monkeypatch.setattr(api, "get_video_detail", _fake_get_video_detail)
    assert asyncio.run(api.resolve_mix_ref(aweme_id="700")) == {}


def test_resolve_mix_ref_skips_detail_when_name_already_known(monkeypatch):
    """``mix_id`` came from a URL and no aweme was supplied: only the
    two mix probes run — ``get_video_detail`` must not be touched."""
    calls: list = []
    api = _api_with(
        monkeypatch,
        detail={"mix_id": MIX_ID, "mix_name": "名字"},
        calls=calls,
    )

    async def _boom(aweme_id):  # pragma: no cover - must not be called
        raise AssertionError("get_video_detail should not be called")

    monkeypatch.setattr(api, "get_video_detail", _boom)
    ref = asyncio.run(api.resolve_mix_ref(mix_id=MIX_ID))
    assert ref["mix_name"] == "名字"


def test_resolve_mix_ref_page1_wrapper_shapes(monkeypatch):
    """Page-1 items arrive wrapped (``aweme`` / ``aweme_info``) on some
    endpoints — the same unwrapping ``_extract_awemes`` does."""
    for key in ("aweme", "aweme_info"):
        api = _api_with(
            monkeypatch,
            detail=None,
            mix_aweme=_page([{key: {"aweme_id": "1",
                                    "mix_info": {"mix_id": MIX_ID,
                                                 "mix_name": f"via-{key}"}}}]),
        )
        ref = asyncio.run(api.resolve_mix_ref(mix_id=MIX_ID))
        assert ref["mix_name"] == f"via-{key}"


# ---------------------------------------------------------------------------
# get_video_detail preserves mix_info (the regression M6.56 fixes)
# ---------------------------------------------------------------------------


def test_get_video_detail_preserves_mix_info(monkeypatch):
    """Before M6.56 the detail dict was returned verbatim too, but
    ``collection_of`` read only ``mix_id`` and threw the name away.
    This pins the contract that ``mix_info`` survives the call."""
    api = DouyinWebAPI(timeout=5.0)

    async def _fake_request_json(path, params=None, **kwargs):
        return {"aweme_detail": {"aweme_id": "1",
                                 "mix_info": {"mix_id": MIX_ID,
                                              "mix_name": "保留下来"}}}

    monkeypatch.setattr(api, "_request_json", _fake_request_json)
    detail = asyncio.run(api.get_video_detail("1"))
    assert detail is not None
    assert extract_mix_ref(detail)["mix_name"] == "保留下来"


def test_get_video_detail_retries_second_aid(monkeypatch):
    """Existing behaviour: aid 6383 then 1128."""
    api = DouyinWebAPI(timeout=5.0)
    seen: list = []

    async def _fake_request_json(path, params=None, **kwargs):
        seen.append(params["aid"])
        if params["aid"] == "6383":
            return {}
        return {"aweme_detail": {"aweme_id": "1"}}

    monkeypatch.setattr(api, "_request_json", _fake_request_json)
    assert asyncio.run(api.get_video_detail("1")) == {"aweme_id": "1"}
    assert seen == ["6383", "1128"]


def test_get_mix_detail_returns_dict_or_none(monkeypatch):
    api = DouyinWebAPI(timeout=5.0)

    async def _empty(path, params=None, **kwargs):
        return {}

    monkeypatch.setattr(api, "_request_json", _empty)
    assert asyncio.run(api.get_mix_detail(MIX_ID)) is None

    async def _wrapped(path, params=None, **kwargs):
        return {"mix_info": {"mix_id": MIX_ID, "mix_name": "N"}}

    monkeypatch.setattr(api, "_request_json", _wrapped)
    assert asyncio.run(api.get_mix_detail(MIX_ID))["mix_name"] == "N"


def test_get_mix_detail_non_dict_payload_is_none(monkeypatch):
    """``data.get("mix_info") or data.get("mix_detail") or data`` can
    degrade to a list/str when the platform sends an error envelope —
    that must not leak a non-dict to the caller."""
    api = DouyinWebAPI(timeout=5.0)

    async def _weird(path, params=None, **kwargs):
        return {"mix_info": "nope"}

    monkeypatch.setattr(api, "_request_json", _weird)
    assert asyncio.run(api.get_mix_detail(MIX_ID)) is None


# ---------------------------------------------------------------------------
# adapter: collection_of / _parse_collection
# ---------------------------------------------------------------------------


def test_collection_of_uses_name_from_detail_without_reprobing(monkeypatch):
    """The whole point of M6.56: one round-trip, real title."""
    a = DouyinAdapter()
    probes: list = []

    async def _fake_get_video_detail(aweme_id):
        return {"aweme_id": aweme_id,
                "mix_info": {"mix_id": MIX_ID, "mix_name": "深夜聊天室"}}

    async def _no_resolve(*args, **kwargs):
        probes.append("resolve")
        return {}

    monkeypatch.setattr(a.webapi, "get_video_detail", _fake_get_video_detail)
    monkeypatch.setattr(a.webapi, "resolve_mix_ref", _no_resolve)

    item = asyncio.run(a.collection_of("700"))
    assert item is not None
    assert item.media_type.value == "mix"
    assert item.item_id == MIX_ID
    assert item.title == "抖音合集《深夜聊天室》"
    assert item.extra["mix_name"] == "深夜聊天室"
    assert probes == []


def test_collection_of_no_mix_info_returns_none(monkeypatch):
    a = DouyinAdapter()

    async def _fake_get_video_detail(aweme_id):
        return {"aweme_id": aweme_id}

    monkeypatch.setattr(a.webapi, "get_video_detail", _fake_get_video_detail)
    assert asyncio.run(a.collection_of("700")) is None


def test_collection_of_detail_failure_returns_none(monkeypatch):
    a = DouyinAdapter()

    async def _fake_get_video_detail(aweme_id):
        return None

    monkeypatch.setattr(a.webapi, "get_video_detail", _fake_get_video_detail)
    assert asyncio.run(a.collection_of("700")) is None


def test_collection_of_expands_whole_collection_not_one_video(monkeypatch):
    """Regression guard for M6.45: even when we resolved via a single
    video, the container must still represent the WHOLE 合集."""
    a = DouyinAdapter()

    async def _fake_get_video_detail(aweme_id):
        return {"mix_info": {"mix_id": MIX_ID, "mix_name": "整集合"}}

    monkeypatch.setattr(a.webapi, "get_video_detail", _fake_get_video_detail)
    item = asyncio.run(a.collection_of("700"))
    assert item is not None
    assert item.needs_expansion()
    assert item.source_url == f"https://www.douyin.com/collection/{MIX_ID}"


def test_collection_of_trusts_platform_id_over_url_segment(monkeypatch):
    """If the platform ever reports a different id than the URL carried,
    the platform wins — silently mis-tagging a container is worse."""
    a = DouyinAdapter()

    async def _fake_get_video_detail(aweme_id):
        return {"mix_info": {"mix_id": "999", "mix_name": "X"}}

    monkeypatch.setattr(a.webapi, "get_video_detail", _fake_get_video_detail)
    item = asyncio.run(a.collection_of("700"))
    assert item is not None
    assert item.extra["mix_id"] == "999"


def test_parse_collection_probes_when_no_ref(monkeypatch):
    """URL-only path keeps the M6.45 probe behaviour."""
    a = DouyinAdapter()
    probes: list = []

    async def _fake_resolve_mix_ref(*, mix_id="", aweme_id="", error_sink=None):
        probes.append(mix_id)
        return {"mix_id": mix_id, "mix_name": "探到的名字"}

    monkeypatch.setattr(a.webapi, "resolve_mix_ref", _fake_resolve_mix_ref)
    item = asyncio.run(a._parse_collection(MIX_ID))
    assert item.title == "抖音合集《探到的名字》"
    assert probes == [MIX_ID]


def test_parse_collection_placeholder_when_probe_returns_id_only(monkeypatch):
    """Probe resolved the id but no name → M6.45 placeholder, unchanged."""
    a = DouyinAdapter()

    async def _fake_resolve_mix_ref(*, mix_id="", aweme_id="", error_sink=None):
        return {"mix_id": mix_id}

    monkeypatch.setattr(a.webapi, "resolve_mix_ref", _fake_resolve_mix_ref)
    item = asyncio.run(a._parse_collection(MIX_ID))
    assert item.title == f"抖音合集 {MIX_ID}"
    assert "mix_name" not in item.extra


def test_parse_collection_probe_exception_falls_back(monkeypatch):
    """A raising probe must not bubble — the container still gets built."""
    a = DouyinAdapter()

    async def _boom(*, mix_id="", aweme_id="", error_sink=None):
        raise RuntimeError("HTTP 403")

    monkeypatch.setattr(a.webapi, "resolve_mix_ref", _boom)
    item = asyncio.run(a._parse_collection(MIX_ID))
    assert item.title == f"抖音合集 {MIX_ID}"
    assert item.needs_expansion()


def test_parse_collection_seq_still_tracked(monkeypatch):
    """M6.45 seq semantics untouched by M6.56."""
    a = DouyinAdapter()

    async def _fake_resolve_mix_ref(*, mix_id="", aweme_id="", error_sink=None):
        return {"mix_id": mix_id, "mix_name": "N"}

    monkeypatch.setattr(a.webapi, "resolve_mix_ref", _fake_resolve_mix_ref)
    item = asyncio.run(a._parse_collection(MIX_ID, seq=3))
    assert item.extra["seq"] == 3
    assert item.source_url == f"https://www.douyin.com/collection/{MIX_ID}/3"


def test_parse_collection_seq_survives_mix_ref_path(monkeypatch):
    """seq + a caller-supplied ref together (no probe at all)."""
    a = DouyinAdapter()
    item = asyncio.run(a._parse_collection(
        MIX_ID, seq=7, mix_ref={"mix_id": MIX_ID, "mix_name": "带 seq"},
    ))
    assert item.title == "抖音合集《带 seq》"
    assert item.extra["seq"] == 7


def test_parse_collection_parse_still_returns_mix_for_collection_url(monkeypatch):
    """End-to-end through ``parse()`` — the URL classifier still yields a
    MIX container and the title now carries the real name."""
    a = DouyinAdapter()

    async def _fake_resolve_mix_ref(*, mix_id="", aweme_id="", error_sink=None):
        return {"mix_id": mix_id, "mix_name": "我的测试合集"}

    monkeypatch.setattr(a.webapi, "resolve_mix_ref", _fake_resolve_mix_ref)
    item = asyncio.run(a.parse(f"https://www.douyin.com/collection/{MIX_ID}"))
    assert item is not None
    assert item.media_type.value == "mix"
    assert "我的测试合集" in item.title
    assert item.extra["mix_id"] == MIX_ID


# ---------------------------------------------------------------------------
# signature parity
# ---------------------------------------------------------------------------


def test_mix_paths_remain_websign_protected():
    """M6.48+ parity: both mix endpoints are in the signed-path
    whitelist. M6.56 added no new endpoint, so this pins that the
    refactor did not disturb the set."""
    assert "/aweme/v1/web/mix/aweme/" in DOUYIN_SIGNED_PATHS
    assert "/aweme/v1/web/mix/detail/" in DOUYIN_SIGNED_PATHS


def test_resolve_mix_ref_issues_no_new_endpoints(monkeypatch):
    """Every path touched by resolve_mix_ref must already be whitelisted
    — a refactor that quietly starts signing a new path would change
    request byte-for-byte behaviour."""
    api = DouyinWebAPI(timeout=5.0)
    paths: list = []

    async def _fake_request_json(path, params=None, **kwargs):
        paths.append(path)
        return {}

    monkeypatch.setattr(api, "_request_json", _fake_request_json)
    asyncio.run(api.resolve_mix_ref(mix_id=MIX_ID))
    assert paths, "resolution must issue at least one request"
    for path in paths:
        assert path in DOUYIN_SIGNED_PATHS, path


# ---------------------------------------------------------------------------
# CLI: doubi mix
# ---------------------------------------------------------------------------


def _run_cli(argv: list[str]) -> tuple[int, str, str]:
    from doubi.cli.main import main

    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


def test_cli_mix_json_output(monkeypatch):
    """``doubi mix <id>`` prints a single JSON object describing the 合集."""
    async def _fake_resolve_mix_ref(self, *, mix_id="", aweme_id="", error_sink=None):
        return {"mix_id": mix_id, "mix_name": "深夜聊天室"}

    monkeypatch.setattr(DouyinWebAPI, "resolve_mix_ref", _fake_resolve_mix_ref)
    code, out, err = _run_cli(["mix", MIX_ID])
    assert code == 0
    payload = json.loads(out.strip())
    assert payload["mix_id"] == MIX_ID
    assert payload["mix_name"] == "深夜聊天室"
    assert payload["title"] == "抖音合集《深夜聊天室》"
    assert err == ""


def test_cli_mix_accepts_full_collection_url(monkeypatch):
    """A pasted ``/collection/{id}`` URL works without the user having to
    extract the id by hand."""
    seen: list = []

    async def _fake_resolve_mix_ref(self, *, mix_id="", aweme_id="", error_sink=None):
        seen.append(mix_id)
        return {"mix_id": mix_id, "mix_name": "N"}

    monkeypatch.setattr(DouyinWebAPI, "resolve_mix_ref", _fake_resolve_mix_ref)
    code, out, _ = _run_cli(
        ["mix", f"https://www.douyin.com/collection/{MIX_ID}/3"],
    )
    assert code == 0
    assert seen == [MIX_ID]
    assert json.loads(out.strip())["mix_id"] == MIX_ID


def test_cli_mix_accepts_iesdouyin_share_url(monkeypatch):
    """The APP「分享合集」form classifies as COLLECTION too."""
    seen: list = []

    async def _fake_resolve_mix_ref(self, *, mix_id="", aweme_id="", error_sink=None):
        seen.append(mix_id)
        return {"mix_id": mix_id, "mix_name": "N"}

    monkeypatch.setattr(DouyinWebAPI, "resolve_mix_ref", _fake_resolve_mix_ref)
    code, _, _ = _run_cli([
        "mix", f"https://www.iesdouyin.com/share/mix/detail/{MIX_ID}/?a=1",
    ])
    assert code == 0
    assert seen == [MIX_ID]


def test_cli_mix_unrelated_url_is_rejected(monkeypatch):
    """A /video/ URL is not a 合集 — exit 2 with a clear message rather
    than passing the whole URL through as an id."""
    code, out, err = _run_cli(["mix", "https://www.douyin.com/video/700"])
    assert code == 2
    assert out == ""
    assert "Error:" in err


def test_cli_mix_from_aweme_resolves_id(monkeypatch):
    seen: list = []

    async def _fake_resolve_mix_ref(self, *, mix_id="", aweme_id="", error_sink=None):
        seen.append(aweme_id)
        return {"mix_id": MIX_ID, "mix_name": "来自视频"}

    monkeypatch.setattr(DouyinWebAPI, "resolve_mix_ref", _fake_resolve_mix_ref)
    # positional is required by argparse; pass an empty marker and rely
    # on --from-aweme
    code, out, _ = _run_cli(["mix", "", "--from-aweme", "700"])
    assert code == 0
    assert seen == ["700"]
    assert json.loads(out.strip())["mix_id"] == MIX_ID


def test_cli_mix_unresolvable_reports_zero_not_error(monkeypatch):
    """Not-found is a normal result, not a crash — exit 0 + stderr note."""
    async def _fake_resolve_mix_ref(self, *, mix_id="", aweme_id="", error_sink=None):
        if error_sink is not None:
            error_sink.update({"reason": "http_403", "status_code": 403,
                               "hint": "need_login"})
        return {}

    monkeypatch.setattr(DouyinWebAPI, "resolve_mix_ref", _fake_resolve_mix_ref)
    code, out, err = _run_cli(["mix", MIX_ID])
    assert code == 0
    # A failed lookup must NOT echo the input id back as if it resolved.
    assert out == ""
    assert "http_403" in err
    assert "need_login" in err


def test_cli_mix_list_emits_jsonl(monkeypatch):
    """``--list`` enumerates the 合集 and tags every row with the mix id."""
    awemes = [
        {"aweme_id": "700", "desc": "第一条", "create_time": 1700000000,
         "video": {"duration": 15000},
         "author": {"sec_uid": "sec-1", "nickname": "作者甲"},
         "statistics": {"play_count": 10, "digg_count": 2},
         "mix_info": {"mix_id": MIX_ID, "mix_name": "深夜聊天室"}},
        {"aweme_id": "701", "desc": "第二条",
         "author": {"sec_uid": "sec-2", "nickname": "作者乙"}},
    ]

    async def _fake_resolve_mix_ref(self, *, mix_id="", aweme_id="", error_sink=None):
        return {"mix_id": mix_id, "mix_name": "深夜聊天室"}

    async def _fake_iter_mix_awemes(self, mix_id, *, max_count=0, error_sink=None):
        return awemes

    monkeypatch.setattr(DouyinWebAPI, "resolve_mix_ref", _fake_resolve_mix_ref)
    monkeypatch.setattr(DouyinWebAPI, "iter_mix_awemes", _fake_iter_mix_awemes)

    code, out, err = _run_cli(["mix", MIX_ID, "--list"])
    assert code == 0, err
    lines = [json.loads(ln) for ln in out.strip().splitlines()]
    assert len(lines) == 2
    assert lines[0]["aweme_id"] == "700"
    assert lines[0]["title"] == "第一条"
    assert lines[0]["author"] == "作者甲"
    assert lines[0]["author_sec_uid"] == "sec-1"
    assert lines[0]["mix_id"] == MIX_ID
    assert lines[0]["mix_name"] == "深夜聊天室"
    assert lines[0]["target_mix_id"] == MIX_ID
    assert lines[0]["duration"] == 15.0
    assert lines[0]["source_url"] == "https://www.douyin.com/video/700"
    assert lines[1]["aweme_id"] == "701"


def test_cli_mix_list_empty_is_not_an_error(monkeypatch):
    """The probe proved the 合集 exists, so an empty page is a result."""
    async def _fake_resolve_mix_ref(self, *, mix_id="", aweme_id="", error_sink=None):
        return {"mix_id": mix_id, "mix_name": "空合集"}

    async def _fake_iter_mix_awemes(self, mix_id, *, max_count=0, error_sink=None):
        return []

    monkeypatch.setattr(DouyinWebAPI, "resolve_mix_ref", _fake_resolve_mix_ref)
    monkeypatch.setattr(DouyinWebAPI, "iter_mix_awemes", _fake_iter_mix_awemes)
    code, out, err = _run_cli(["mix", MIX_ID, "--list"])
    assert code == 0
    assert out == ""
    assert "No videos." in err


def test_cli_mix_list_failure_exits_3(monkeypatch):
    async def _fake_resolve_mix_ref(self, *, mix_id="", aweme_id="", error_sink=None):
        return {"mix_id": mix_id, "mix_name": "N"}

    async def _boom(self, mix_id, *, max_count=0, error_sink=None):
        raise RuntimeError("network down")

    monkeypatch.setattr(DouyinWebAPI, "resolve_mix_ref", _fake_resolve_mix_ref)
    monkeypatch.setattr(DouyinWebAPI, "iter_mix_awemes", _boom)
    code, _, err = _run_cli(["mix", MIX_ID, "--list"])
    assert code == 3
    assert "network down" in err


def test_cli_mix_lookup_failure_exits_3(monkeypatch):
    async def _boom(self, *, mix_id="", aweme_id="", error_sink=None):
        raise RuntimeError("network down")

    monkeypatch.setattr(DouyinWebAPI, "resolve_mix_ref", _boom)
    code, _, err = _run_cli(["mix", MIX_ID])
    assert code == 3
    assert "network down" in err


def test_cli_mix_no_arguments_exits_2():
    """argparse enforces the positional itself, so a missing mix_id
    never reaches our handler."""
    with pytest.raises(SystemExit) as exc:
        _run_cli(["mix"])
    assert exc.value.code == 2


def test_mix_help_is_registered():
    """The subcommand exists and advertises both modes."""
    from doubi.cli.main import _build_parser

    parser = _build_parser()
    out = io.StringIO()
    with redirect_stdout(out):
        with pytest.raises(SystemExit) as exc:
            parser.parse_args(["mix", "--help"])
    assert exc.value.code == 0
    text = out.getvalue()
    assert "--from-aweme" in text
    assert "--list" in text
    assert "--cookies-file" in text
