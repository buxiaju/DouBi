"""Tests for M6.55 抖音 直播详情 + 多清晰度.

Adapted from Johnserf-Seed/TikTokDownloader ``src/interface/live.py``
lines 11-95 (MIT). Two endpoints, two different hosts:

    get_live_room              live.douyin.com/webcast/room/web/enter/
    get_live_room_by_room_id   webcast.amemv.com/webcast/room/reflow/info/

Neither path is in TikTokDL's ``DOUYIN_SIGNED_PATHS`` frozenset, so both
ride on ``a_bogus`` alone with **no** WebSign — one test below pins that
parity so a future "defensive over-sign" sweep can't silently change the
wire format relative to the reference implementation.

Tests monkey-patch the transport (``DouyinWebAPI._request_json`` or
``httpx.AsyncClient``) so no real traffic leaves the machine.
"""

from __future__ import annotations

import asyncio
import io
import json
import sys
from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from doubi.platforms.douyin import live as dy_live  # noqa: E402
from doubi.platforms.douyin import webapi as w  # noqa: E402
from doubi.platforms.douyin.sign import DOUYIN_SIGNED_PATHS  # noqa: E402


def _enter_body(
    *,
    status: int = 2,
    flv: dict | None = None,
    hls: dict | None = None,
    room_id: str = "7300000000000000000",
    title: str = "深夜直播间",
    nickname: str = "主播小甲",
) -> dict:
    """Shape of the ``live.douyin.com`` enter response (``data.data[0]``)."""
    return {
        "data": {
            "data": [{
                "id_str": room_id,
                "status": status,
                "title": title,
                "owner": {"nickname": nickname, "sec_uid": "SEC-OWNER"},
                "cover": {"url_list": [
                    "https://p.douyin.com/cover-small.jpg",
                    "https://p.douyin.com/cover-large.jpg",
                ]},
                "stats": {"total_user_str": "12.3万", "user_count_str": "8452"},
                "stream_url": {
                    "flv_pull_url": flv if flv is not None else {
                        "FULL_HD1": "https://pull-flv/full_hd1",
                        "HD1": "https://pull-flv/hd1",
                        "SD2": "https://pull-flv/sd2",
                    },
                    "hls_pull_url_map": hls if hls is not None else {
                        "FULL_HD1": "https://pull-hls/full_hd1.m3u8",
                        "HD1": "https://pull-hls/hd1.m3u8",
                        "SD2": "https://pull-hls/sd2.m3u8",
                    },
                },
            }],
        },
    }


# ---------------------------------------------------------------------------
# extract_live_web_rid
# ---------------------------------------------------------------------------


def test_extract_live_web_rid_accepts_all_documented_shapes():
    """All three URL shapes TikTokDL recognises, plus a bare pasted id."""
    # link/extractor.py:44 -- canonical share link
    assert w.extract_live_web_rid("https://live.douyin.com/123456789") == "123456789"
    # ...with a query string appended by the share sheet
    assert w.extract_live_web_rid(
        "https://live.douyin.com/123456789?enter_from=link_share"
    ) == "123456789"
    # link/extractor.py:45 -- the 关注 page's webRid parameter
    assert w.extract_live_web_rid(
        "https://www.douyin.com/follow?webRid=987654321"
    ) == "987654321"
    # bare id pasted from `doubi search --type live` output
    assert w.extract_live_web_rid("  987654321  ") == "987654321"


def test_extract_live_web_rid_rejects_non_live_input():
    assert w.extract_live_web_rid("") == ""
    assert w.extract_live_web_rid("   ") == ""
    assert w.extract_live_web_rid("https://www.douyin.com/video/123") == ""
    assert w.extract_live_web_rid("https://example.com/live/1") == ""
    # A room_id is not a web_rid: no host match, and it is not all digits
    # in the form the caller passes here (sec_uid style strings).
    assert w.extract_live_web_rid("MS4wLjABAAAA") == ""


# ---------------------------------------------------------------------------
# LIVE_ENTER_PARAMS -- parity pins against TikTokDL live.py:45-66
# ---------------------------------------------------------------------------


def test_live_enter_params_pins_tiktokdl_key_set():
    """The 17 business params upstream, minus ``web_rid`` (injected per
    call) and ``msToken`` (injected by ``_default_query``).
    """
    expected = {
        "aid", "app_name", "live_id", "device_platform", "language",
        "enter_from", "cookie_enabled", "screen_width", "screen_height",
        "browser_language", "browser_platform", "browser_name",
        "browser_version", "enter_source", "is_need_double_stream",
        "insert_task_id", "live_reason",
    }
    assert set(w.LIVE_ENTER_PARAMS) == expected
    assert "web_rid" not in w.LIVE_ENTER_PARAMS


def test_live_enter_params_override_default_query_fingerprint():
    """``_default_query`` sends ``device_platform=webapp`` and
    ``browser_platform=Win32`` (the video feed). The 直播 web player
    sends ``web`` / ``MacIntel``; ``params`` is merged *after*
    ``_default_query`` so these must win.
    """
    assert w.LIVE_ENTER_PARAMS["device_platform"] == "web"
    assert w.LIVE_ENTER_PARAMS["browser_platform"] == "MacIntel"
    defaults = w._default_query("tok")
    assert defaults["device_platform"] == "webapp"
    assert defaults["browser_platform"] == "Win32"


def test_live_hosts_and_paths_match_tiktokdl():
    assert w.LIVE_ENTER_BASE == "https://live.douyin.com"
    assert w.LIVE_ENTER_PATH == "/webcast/room/web/enter/"
    assert w.LIVE_REFLOW_BASE == "https://webcast.amemv.com"
    assert w.LIVE_REFLOW_PATH == "/webcast/room/reflow/info/"
    assert w.LIVE_REFERER == "https://live.douyin.com/"


def test_live_paths_are_not_websign_protected():
    """Parity pin: TikTokDL deliberately leaves /webcast/* out of
    ``DOUYIN_SIGNED_PATHS``, so these requests carry ``a_bogus`` only.
    Adding them "defensively" would diverge from the reference client
    — if that is ever intended, change this test on purpose.
    """
    assert w.LIVE_ENTER_PATH not in DOUYIN_SIGNED_PATHS
    assert w.LIVE_REFLOW_PATH not in DOUYIN_SIGNED_PATHS


# ---------------------------------------------------------------------------
# normalize_live_room
# ---------------------------------------------------------------------------


def test_normalize_live_room_handles_enter_shape():
    room = w.normalize_live_room(_enter_body(), web_rid="123456789")
    assert room["web_rid"] == "123456789"
    assert room["room_id"] == "7300000000000000000"
    assert room["title"] == "深夜直播间"
    assert room["nickname"] == "主播小甲"
    assert room["sec_uid"] == "SEC-OWNER"
    assert room["status"] == 2
    assert room["status_name"] == "直播中"
    assert room["total_user_str"] == "12.3万"
    assert room["user_count_str"] == "8452"


def test_normalize_live_room_cover_uses_last_url():
    """TikTokDL ``LIVE_COVER_INDEX = -1`` (``custom/internal.py``) —
    the *last* cover url is the high-resolution one.
    """
    room = w.normalize_live_room(_enter_body())
    assert room["cover"] == "https://p.douyin.com/cover-large.jpg"


def test_normalize_live_room_handles_reflow_shape():
    """The share/reflow endpoint wraps the room as ``data.room``
    instead of ``data.data[0]`` (TikTokDL tries both in sequence).
    """
    raw = {"data": {"room": {
        "id_str": "888",
        "status": 4,
        "title": "回放房",
        "owner": {"nickname": "乙"},
        "stream_url": {"flv_pull_url": {"HD1": "https://pull-flv/hd1"}},
    }}}
    room = w.normalize_live_room(raw, room_id="888")
    assert room["room_id"] == "888"
    assert room["status_name"] == "已结束"
    assert room["flv_pull_url"] == {"HD1": "https://pull-flv/hd1"}
    assert room["hls_pull_url_map"] == {}


def test_normalize_live_room_returns_empty_for_missing_payload():
    assert w.normalize_live_room({}) == {}
    assert w.normalize_live_room({"data": {}}) == {}
    assert w.normalize_live_room({"data": {"data": []}}) == {}
    # Risk-control HTML / garbage must not raise
    assert w.normalize_live_room({"status_code": 0}) == {}
    assert w.normalize_live_room(None) == {}


def test_live_status_names_map_known_values_and_surface_unknown():
    """Only 2 / 4 are mapped. An unmapped status stays visible as
    ``未知(N)`` rather than being silently guessed.
    """
    assert w._live_status_name(2) == "直播中"
    assert w._live_status_name(4) == "已结束"
    assert w._live_status_name(99) == "未知(99)"
    assert w._live_status_name(None) == "未知"
    assert w._live_status_name(True) == "未知"


# ---------------------------------------------------------------------------
# quality rows
# ---------------------------------------------------------------------------


def test_quality_rows_follow_preferred_order_then_platform_order():
    room = w.normalize_live_room(_enter_body(
        flv={"SD2": "s", "ZZ_UNKNOWN": "z", "HD1": "h", "FULL_HD1": "f"},
    ))
    keys = [r["key"] for r in room["qualities"]]
    # Known keys come out best-first regardless of dict insertion order…
    assert keys[:3] == ["FULL_HD1", "HD1", "SD2"]
    # …and keys 抖音 added after this release are appended verbatim.
    assert keys[3] == "ZZ_UNKNOWN"


def test_quality_rows_merge_parallel_flv_and_hls_maps():
    """The two maps are keyed by the same tokens; a key present in only
    one container still yields a usable row.
    """
    room = w.normalize_live_room(_enter_body(
        flv={"HD1": "https://pull-flv/hd1"},
        hls={"HD1": "https://pull-hls/hd1.m3u8", "SD1": "https://pull-hls/sd1.m3u8"},
    ))
    by_key = {r["key"]: r for r in room["qualities"]}
    assert by_key["HD1"]["flv"] == "https://pull-flv/hd1"
    assert by_key["HD1"]["hls"] == "https://pull-hls/hd1.m3u8"
    assert by_key["SD1"]["flv"] is None
    assert by_key["SD1"]["hls"] == "https://pull-hls/sd1.m3u8"


def test_quality_labels_known_are_chinese_and_unknown_are_verbatim():
    room = w.normalize_live_room(_enter_body(
        flv={"FULL_HD1": "f", "HD1": "h", "SD1": "s1", "SD2": "s2", "WEIRD": "w"},
        hls={},
    ))
    labels = {r["key"]: r["name"] for r in room["qualities"]}
    assert labels["FULL_HD1"] == "蓝光"
    assert labels["HD1"] == "高清"
    assert labels["SD1"] == "标清"
    assert labels["SD2"] == "流畅"
    assert labels["WEIRD"] == "WEIRD"


# ---------------------------------------------------------------------------
# pick_live_quality
# ---------------------------------------------------------------------------


def _room_for_pick() -> dict:
    return w.normalize_live_room(_enter_body(flv={
        "FULL_HD1": "https://pull-flv/full_hd1",
        "HD1": "https://pull-flv/hd1",
        "SD2": "https://pull-flv/sd2",
    }))


def test_pick_live_quality_default_and_best_return_top_row():
    room = _room_for_pick()
    for choice in (None, "", "best", "BEST"):
        row, url = w.pick_live_quality(room, choice)
        assert row is not None and row["key"] == "FULL_HD1"
        assert url == "https://pull-flv/full_hd1"


def test_pick_live_quality_matches_key_case_insensitively_and_by_label():
    room = _room_for_pick()
    assert w.pick_live_quality(room, "hd1")[1] == "https://pull-flv/hd1"
    assert w.pick_live_quality(room, "HD1")[1] == "https://pull-flv/hd1"
    assert w.pick_live_quality(room, "高清")[1] == "https://pull-flv/hd1"
    assert w.pick_live_quality(room, "蓝光")[1] == "https://pull-flv/full_hd1"


def test_pick_live_quality_matches_one_based_index():
    room = _room_for_pick()
    assert w.pick_live_quality(room, "1")[1] == "https://pull-flv/full_hd1"
    assert w.pick_live_quality(room, "2")[1] == "https://pull-flv/hd1"
    assert w.pick_live_quality(room, "3")[1] == "https://pull-flv/sd2"
    # out of range -> no match, not a crash or a silent fallback
    assert w.pick_live_quality(room, "0") == (None, None)
    assert w.pick_live_quality(room, "99") == (None, None)


def test_pick_live_quality_prefers_requested_container_and_falls_back():
    # SD2 exists in FLV only in this fixture.
    room = w.normalize_live_room(_enter_body(
        flv={"SD2": "https://pull-flv/sd2"},
        hls={},
    ))
    row, url = w.pick_live_quality(room, "SD2", prefer="hls")
    assert row is not None
    assert url == "https://pull-flv/sd2"   # fell back to FLV

    room2 = w.normalize_live_room(_enter_body())
    _, url2 = w.pick_live_quality(room2, "HD1", prefer="hls")
    assert url2 == "https://pull-hls/hd1.m3u8"


def test_pick_live_quality_unknown_choice_and_empty_room_return_none():
    room = _room_for_pick()
    assert w.pick_live_quality(room, "不存在的清晰度") == (None, None)
    assert w.pick_live_quality(room, "UHD") == (None, None)
    assert w.pick_live_quality({}, "best") == (None, None)
    assert w.pick_live_quality({"qualities": "nope"}, "best") == (None, None)


# ---------------------------------------------------------------------------
# get_live_room / get_live_room_by_room_id -- request wiring
# ---------------------------------------------------------------------------


async def test_get_live_room_hits_enter_endpoint_with_live_host_and_referer(monkeypatch):
    api = w.DouyinWebAPI()
    captured: dict = {}

    async def _fake(path, params, **kwargs):
        captured["path"] = path
        captured["params"] = params
        captured["kwargs"] = kwargs
        return _enter_body()

    monkeypatch.setattr(api, "_request_json", _fake)
    room = await api.get_live_room("https://live.douyin.com/123456789?x=1")

    assert captured["path"] == w.LIVE_ENTER_PATH
    assert captured["kwargs"]["base_url"] == w.LIVE_ENTER_BASE
    assert captured["kwargs"]["extra_headers"]["Referer"] == w.LIVE_REFERER
    # web_rid is normalised out of the URL, not forwarded raw
    assert captured["params"]["web_rid"] == "123456789"
    assert room["web_rid"] == "123456789"
    assert room["status_name"] == "直播中"


async def test_get_live_room_blank_web_rid_skips_the_request(monkeypatch):
    api = w.DouyinWebAPI()
    called = False

    async def _fake(path, params, **kwargs):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(api, "_request_json", _fake)
    assert await api.get_live_room("https://example.com/nothing") == {}
    assert await api.get_live_room("") == {}
    assert called is False


async def test_get_live_room_forwards_error_sink_to_transport(monkeypatch):
    api = w.DouyinWebAPI()
    seen: dict = {}

    async def _fake(path, params, *, error_sink=None, **kwargs):
        assert error_sink is not None
        error_sink["reason"] = "HTTP 403"
        error_sink["status_code"] = 403
        error_sink["hint"] = "need_login"
        seen["ok"] = True
        return {}

    monkeypatch.setattr(api, "_request_json", _fake)
    sink: dict = {}
    room = await api.get_live_room("123456789", error_sink=sink)

    assert seen["ok"] is True
    assert room == {}
    assert sink["status_code"] == 403
    assert sink["hint"] == "need_login"


async def test_get_live_room_by_room_id_hits_reflow_endpoint_with_download_headers(
    monkeypatch,
):
    api = w.DouyinWebAPI()
    captured: dict = {}

    async def _fake(path, params, **kwargs):
        captured["path"] = path
        captured["params"] = params
        captured["kwargs"] = kwargs
        return {"data": {"room": {
            "id_str": "888", "status": 2, "title": "T",
            "stream_url": {"flv_pull_url": {"HD1": "https://pull-flv/hd1"}},
        }}}

    monkeypatch.setattr(api, "_request_json", _fake)
    room = await api.get_live_room_by_room_id("888", sec_user_id="SEC-1")

    assert captured["path"] == w.LIVE_REFLOW_PATH
    assert captured["kwargs"]["base_url"] == w.LIVE_REFLOW_BASE
    # TikTokDL passes params.headers_download here, not the live referer
    assert captured["kwargs"]["extra_headers"] == w.LIVE_REFLOW_HEADERS
    assert captured["kwargs"]["extra_headers"]["Referer"] == "https://www.douyin.com/?recommend=1"
    assert captured["kwargs"]["extra_headers"]["Range"] == "bytes=0-"
    assert captured["params"]["room_id"] == "888"
    assert captured["params"]["sec_user_id"] == "SEC-1"
    assert captured["params"]["app_id"] == "1128"
    assert room["room_id"] == "888"


async def test_get_live_room_by_room_id_blank_skips_the_request(monkeypatch):
    api = w.DouyinWebAPI()
    called = False

    async def _fake(path, params, **kwargs):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(api, "_request_json", _fake)
    assert await api.get_live_room_by_room_id("") == {}
    assert await api.get_live_room_by_room_id("   ") == {}
    assert called is False


# ---------------------------------------------------------------------------
# transport: base_url + header merge (real _request_json path)
# ---------------------------------------------------------------------------


class _FakeResponse:
    status_code = 200
    content = b'{"data": {"data": []}}'

    def json(self):
        return {"data": {"data": []}}


class _FakeClient:
    """Captures the kwargs httpx.AsyncClient was constructed with."""

    last: dict = {}

    def __init__(self, **kwargs):
        _FakeClient.last = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def get(self, url):
        _FakeClient.last["url"] = url
        return _FakeResponse()


async def test_request_json_sends_cross_host_url_and_merges_headers(monkeypatch):
    """End-to-end through the real ``_request_json``: the request must go
    to the overridden host, and ``extra_headers`` must *merge over*
    ``_HEADERS`` rather than replacing it (dropping the browser-looking
    User-Agent / Accept would itself trip 抖音's risk control).
    """
    api = w.DouyinWebAPI()
    api._tokens_ready = True          # skip the mssdk network round-trip
    monkeypatch.setattr(w.httpx, "AsyncClient", _FakeClient)

    body = await api._request_json(
        w.LIVE_ENTER_PATH,
        {"web_rid": "123"},
        max_retries=1,
        base_url=w.LIVE_ENTER_BASE,
        extra_headers={"Referer": w.LIVE_REFERER},
    )

    assert body == {"data": {"data": []}}
    url = _FakeClient.last["url"]
    assert url.startswith("https://live.douyin.com/webcast/room/web/enter/?")
    assert "web_rid=123" in url
    assert "a_bogus=" in url
    # WebSign is NOT applied to this path (parity with TikTokDL)
    assert "x-secsdk-web-signature" not in url

    headers = _FakeClient.last["headers"]
    assert headers["Referer"] == w.LIVE_REFERER          # overridden
    assert headers["User-Agent"] == w._USER_AGENT        # preserved
    assert headers["Accept"] == "*/*"                    # preserved


def test_signed_url_base_url_override_defaults_to_www(monkeypatch):
    api = w.DouyinWebAPI()
    live = api._signed_url("/x/", {"a": "1"}, base_url="https://live.douyin.com")
    assert live.startswith("https://live.douyin.com/x/?")
    # Unchanged behaviour for every pre-M6.55 call site
    assert api._signed_url("/x/", {"a": "1"}).startswith(
        f"{w.DouyinWebAPI.BASE_URL}/x/?"
    )


# ---------------------------------------------------------------------------
# LiveRecorder: explicit room_id / title / metadata (M6.55)
# ---------------------------------------------------------------------------


def test_recorder_accepts_direct_pull_url_via_room_id(tmp_path, monkeypatch):
    """A direct FLV pull URL carries no room id, so ``record`` must
    accept one explicitly instead of failing to parse the URL.
    """
    captured: dict = {}

    def _fake_probe(room_id):
        captured["probed"] = room_id
        return {"id": room_id, "title": "来自 probe"}

    monkeypatch.setattr(dy_live, "_probe_room", _fake_probe)

    def _fake_sync(self, url, out_path, max_duration, *, room_id=""):
        captured["url"] = url
        captured["room_id"] = room_id
        captured["out_path"] = out_path
        return dy_live.LiveRecordResult(
            room_id=room_id, title="", output_path=out_path,
        )

    monkeypatch.setattr(dy_live.LiveRecorder, "_record_sync", _fake_sync)

    rec = dy_live.LiveRecorder()
    result = asyncio.run(rec.record(
        "https://pull-flv/full_hd1",
        output_root=tmp_path,
        room_id="7300000000000000000",
    ))

    assert captured["url"] == "https://pull-flv/full_hd1"
    assert captured["room_id"] == "7300000000000000000"
    assert "7300000000000000000" in captured["out_path"].name
    assert result.room_id == "7300000000000000000"


def test_recorder_metadata_skips_the_ytdlp_probe(tmp_path, monkeypatch):
    """Passing ``metadata`` must avoid the yt-dlp probe round-trip — the
    web API already gave us an authoritative record, and probing the
    *page* URL when recording a pull URL would be plain wrong.
    """
    def _boom(room_id):                     # pragma: no cover - must not run
        raise AssertionError("_probe_room must not be called when metadata is given")

    monkeypatch.setattr(dy_live, "_probe_room", _boom)
    monkeypatch.setattr(
        dy_live.LiveRecorder, "_record_sync",
        lambda self, url, out_path, max_duration, *, room_id="": (
            dy_live.LiveRecordResult(room_id=room_id, title="", output_path=out_path)
        ),
    )

    metadata = {"title": "Web API 标题", "status_name": "直播中"}
    rec = dy_live.LiveRecorder()
    result = asyncio.run(rec.record(
        "https://pull-flv/hd1",
        output_root=tmp_path,
        room_id="888",
        metadata=metadata,
    ))

    assert result.room_metadata == metadata
    assert result.title == "Web API 标题"
    # The metadata title reached the on-disk filename, so the user can
    # tell recordings apart without opening the sidecar.
    assert "Web API 标题" in result.output_path.name
    assert result.output_path.name.endswith("_888.mp4")


def test_recorder_title_override_wins_over_probe(tmp_path, monkeypatch):
    monkeypatch.setattr(
        dy_live, "_probe_room", lambda rid: {"id": rid, "title": "probe 标题"},
    )
    monkeypatch.setattr(
        dy_live.LiveRecorder, "_record_sync",
        lambda self, url, out_path, max_duration, *, room_id="": (
            dy_live.LiveRecordResult(room_id=room_id, title="", output_path=out_path)
        ),
    )

    rec = dy_live.LiveRecorder()
    result = asyncio.run(rec.record(
        "https://live.douyin.com/999",
        output_root=tmp_path,
        title="Web API 标题",
    ))
    assert result.title == "Web API 标题"


def test_recorder_still_requires_a_room_id_from_somewhere(tmp_path):
    rec = dy_live.LiveRecorder()
    with pytest.raises(ValueError, match="could not extract room_id"):
        asyncio.run(rec.record("https://example.com/not-live", output_root=tmp_path))


# ---------------------------------------------------------------------------
# CLI: doubi live
# ---------------------------------------------------------------------------


def _make_ns(**overrides) -> Namespace:
    ns = Namespace(
        verbose=False,
        config=None,
        command="live",
        url=None,
        room_id=None,
        sec_user_id=None,
        output=Path("./Downloaded"),
        max_duration=0.0,
        cookies=None,
        proxy=None,
        info=False,
        json=False,
        quality=None,
        format="flv",
    )
    for k, v in overrides.items():
        setattr(ns, k, v)
    return ns


def _patch_live_room(monkeypatch, room: dict, sink: dict | None = None):
    """Patch the webapi lookup used by ``_cmd_live``."""
    if sink is None:
        sink = {}

    async def _fake_get_room(self, web_rid, *, error_sink=None, **kwargs):
        if error_sink is not None:
            error_sink.update(sink)
        return room

    async def _fake_get_room_by_id(
        self, room_id, *, sec_user_id="", error_sink=None, **kwargs,
    ):
        if error_sink is not None:
            error_sink.update(sink)
        return room

    monkeypatch.setattr(w.DouyinWebAPI, "get_live_room", _fake_get_room)
    monkeypatch.setattr(
        w.DouyinWebAPI, "get_live_room_by_room_id", _fake_get_room_by_id,
    )


def test_cli_live_requires_url_or_room_id():
    from doubi.cli.main import _cmd_live

    err = io.StringIO()
    with redirect_stderr(err):
        rc = _cmd_live(_make_ns())
    assert rc == 2
    assert "--room-id" in err.getvalue()


def test_cli_live_info_json_emits_one_object(monkeypatch):
    from doubi.cli.main import _cmd_live

    room = w.normalize_live_room(_enter_body(), web_rid="123")
    _patch_live_room(monkeypatch, room)

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = _cmd_live(_make_ns(url="https://live.douyin.com/123", info=True, json=True))

    assert rc == 0
    lines = [ln for ln in buf.getvalue().splitlines() if ln]
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["status_name"] == "直播中"
    assert [row["key"] for row in payload["qualities"]] == [
        "FULL_HD1", "HD1", "SD2",
    ]
    assert payload["qualities"][0]["flv"] == "https://pull-flv/full_hd1"


def test_cli_live_info_table_lists_qualities_with_containers(monkeypatch):
    from doubi.cli.main import _cmd_live

    room = w.normalize_live_room(_enter_body(), web_rid="123")
    _patch_live_room(monkeypatch, room)

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = _cmd_live(_make_ns(url="123", info=True))

    out = buf.getvalue()
    assert rc == 0
    assert "深夜直播间" in out
    assert "主播小甲" in out
    assert "直播中" in out
    assert "FULL_HD1" in out and "蓝光" in out
    assert "1. FULL_HD1 (蓝光)  FLV/HLS" in out


def test_cli_live_info_reports_no_qualities_when_room_has_none(monkeypatch):
    from doubi.cli.main import _cmd_live

    _patch_live_room(monkeypatch, {"title": "空", "nickname": "n",
                                   "status_name": "已结束", "qualities": []})
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = _cmd_live(_make_ns(url="123", info=True))
    assert rc == 0
    assert "未返回拉流地址" in buf.getvalue()


def test_cli_live_reports_lookup_failure_with_risk_control_hint(monkeypatch):
    from doubi.cli.main import _cmd_live

    _patch_live_room(monkeypatch, {}, sink={
        "reason": "HTTP 403", "status_code": 403, "hint": "need_login",
    })
    err = io.StringIO()
    with redirect_stderr(err):
        rc = _cmd_live(_make_ns(url="123", info=True))
    text = err.getvalue()
    assert rc == 1
    assert "HTTP 403" in text
    assert "风控" in text


def test_cli_live_quality_unknown_exits_1_and_lists_choices(monkeypatch):
    from doubi.cli.main import _cmd_live

    room = w.normalize_live_room(_enter_body(), web_rid="123")
    _patch_live_room(monkeypatch, room)

    err = io.StringIO()
    with redirect_stderr(err):
        rc = _cmd_live(_make_ns(url="123", quality="UHD"))
    text = err.getvalue()
    assert rc == 1
    assert "UHD" in text
    assert "FULL_HD1(蓝光)" in text      # the 可选 list


def test_cli_live_quality_records_the_selected_stream(monkeypatch, tmp_path):
    """``--quality hd1 --format flv`` must hand yt-dlp the *direct* pull
    URL plus the room context (room_id / title / metadata) that the pull
    URL itself cannot provide.
    """
    from doubi.cli.main import _cmd_live

    room = w.normalize_live_room(_enter_body(), web_rid="123")
    _patch_live_room(monkeypatch, room)

    captured: dict = {}

    async def _fake_record(self, url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return dy_live.LiveRecordResult(
            room_id=kwargs.get("room_id") or "", title="",
            ended_reason="stream_ended", bytes_written=123,
        )

    monkeypatch.setattr(dy_live.LiveRecorder, "record", _fake_record)

    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = _cmd_live(_make_ns(
            url="https://live.douyin.com/123",
            quality="hd1",
            format="flv",
            output=tmp_path,
        ))

    assert rc == 0
    assert captured["url"] == "https://pull-flv/hd1"
    assert captured["room_id"] == "7300000000000000000"
    assert captured["title"] == "深夜直播间"
    assert captured["metadata"] is room
    assert "HD1" in err.getvalue()


def test_cli_live_quality_hls_uses_the_m3u8_url(monkeypatch, tmp_path):
    from doubi.cli.main import _cmd_live

    room = w.normalize_live_room(_enter_body(), web_rid="123")
    _patch_live_room(monkeypatch, room)

    captured: dict = {}

    async def _fake_record(self, url, **kwargs):
        captured["url"] = url
        return dy_live.LiveRecordResult(
            room_id="1", title="", ended_reason="stream_ended",
        )

    monkeypatch.setattr(dy_live.LiveRecorder, "record", _fake_record)

    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        rc = _cmd_live(_make_ns(url="123", quality="best", format="hls",
                                output=tmp_path))
    assert rc == 0
    assert captured["url"] == "https://pull-hls/full_hd1.m3u8"


def test_cli_live_without_quality_keeps_page_url_behaviour(monkeypatch, tmp_path):
    """No ``--info`` / ``--quality`` → M2.1 behaviour, no room lookup at
    all (so an unauthenticated user can still record via yt-dlp).
    """
    from doubi.cli.main import _cmd_live

    lookup_called = False

    async def _fake_get_room(self, web_rid, *, error_sink=None, **kwargs):
        nonlocal lookup_called
        lookup_called = True
        return {}

    monkeypatch.setattr(w.DouyinWebAPI, "get_live_room", _fake_get_room)

    captured: dict = {}

    async def _fake_record(self, url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return dy_live.LiveRecordResult(
            room_id="999", title="", ended_reason="stream_ended",
        )

    monkeypatch.setattr(dy_live.LiveRecorder, "record", _fake_record)

    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        rc = _cmd_live(_make_ns(url="https://live.douyin.com/999", output=tmp_path))

    assert rc == 0
    assert lookup_called is False
    assert captured["url"] == "https://live.douyin.com/999"
    assert captured["room_id"] is None
    assert captured["metadata"] is None


def test_cli_live_room_id_mode_uses_the_reflow_lookup(monkeypatch, tmp_path):
    from doubi.cli.main import _cmd_live

    room = w.normalize_live_room(_enter_body(), web_rid="123")
    seen: dict = {}

    async def _fake_get_room_by_id(
        self, room_id, *, sec_user_id="", error_sink=None, **kwargs,
    ):
        seen["room_id"] = room_id
        seen["sec_user_id"] = sec_user_id
        return room

    monkeypatch.setattr(w.DouyinWebAPI, "get_live_room_by_room_id", _fake_get_room_by_id)

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = _cmd_live(_make_ns(room_id="7300000000000000000",
                                sec_user_id="SEC-1", info=True, json=True))

    assert rc == 0
    assert seen == {"room_id": "7300000000000000000", "sec_user_id": "SEC-1"}
    assert json.loads(buf.getvalue())["room_id"] == "7300000000000000000"
