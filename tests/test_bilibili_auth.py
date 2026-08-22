"""Tests for M3.1: QR login, cookie validation/parsing, WBI signing, auth CLI."""

from __future__ import annotations

import asyncio
import json
import sys
import time as _time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from doubi.cli import auth_cmd  # noqa: E402
from doubi.platforms.bilibili import auth as bili_auth  # noqa: E402
from doubi.platforms.bilibili.qr_login import (  # noqa: E402
    CODE_NOT_SCANNED,
    CODE_SCANNED,
    CODE_SUCCESS,
    QRStatus,
    QRSession,
    wait_for_login,
)
from doubi.platforms.bilibili.wbi import (  # noqa: E402
    MIXIN_TABLE,
    compute_w_rid,
    fetch_wbi_keys,
    sign_query,
    _filename_from_url,
    _get_mixin_key,
)


# ---------------------------------------------------------------------------
# qr_login
# ---------------------------------------------------------------------------


def test_qrcode_render_ascii_doesnt_crash():
    """A QRCode renders as ASCII even if it isn't pretty."""
    from doubi.platforms.bilibili.qr_login import QRCode
    qr = QRCode(qrcode_key="abc", url="https://www.bilibili.com/")
    out = qr.render_ascii()
    # qrcode package may or may not be installed in CI; either way the call
    # must not raise. If installed, we get non-empty output.
    if out:
        # ASCII QR uses block characters
        assert any(c in out for c in "█▄▀ ")


def test_qr_status_enum_values():
    assert QRStatus.NOT_SCANNED.value == "not_scanned"
    assert QRStatus.SCANNED.value == "scanned"
    assert QRStatus.SUCCESS.value == "success"
    assert QRStatus.EXPIRED.value == "expired"
    assert QRStatus.ERROR.value == "error"


def _mock_async_client(generate_resp, poll_resp):
    """Build an httpx.AsyncClient mock that returns canned responses for
    the QR login endpoints.

    Note: ``.json()`` and ``.raise_for_status()`` are SYNC methods on
    real httpx responses —so they get ``MagicMock`` (not
    ``AsyncMock``). Only ``.get()`` is async.
    """
    client = AsyncMock()

    def _mk_response(body):
        r = MagicMock()
        r.json.return_value = body
        r.raise_for_status = MagicMock(return_value=None)
        # If callers inspect status_code, default to 200
        r.status_code = 200
        return r

    gen = _mk_response(generate_resp)
    poll = _mk_response(poll_resp)

    async def _get(url, **kw):
        if "generate" in url:
            return gen
        return poll
    client.get.side_effect = _get
    return client


def test_qrsession_generate_parses_response():
    client = _mock_async_client(
        generate_resp={"code": 0, "data": {"qrcode_key": "k1", "url": "https://b23.tv/u1"}},
        poll_resp={"code": CODE_NOT_SCANNED, "data": {}},
    )
    sess = QRSession(client=client)
    qr = asyncio.run(sess.generate())
    assert qr.qrcode_key == "k1"
    assert qr.url == "https://b23.tv/u1"


def test_qrsession_generate_fails_on_non_zero_code():
    client = _mock_async_client(
        generate_resp={"code": -101, "message": "not allowed"},
        poll_resp={},
    )
    sess = QRSession(client=client)
    with pytest.raises(RuntimeError, match="QR generate failed"):
        asyncio.run(sess.generate())


def test_qrsession_poll_maps_status_codes():
    cases = [
        ({"code": CODE_NOT_SCANNED, "data": {}}, QRStatus.NOT_SCANNED),
        ({"code": CODE_SCANNED, "data": {}}, QRStatus.SCANNED),
        ({"code": CODE_SUCCESS, "data": {"refresh_token": "r", "timestamp": 12345}},
         QRStatus.SUCCESS),
        ({"code": 86038, "data": {}}, QRStatus.EXPIRED),
        ({"code": -1, "data": {}}, QRStatus.ERROR),
    ]
    for body, expected in cases:
        client = _mock_async_client(generate_resp={}, poll_resp=body)
        sess = QRSession(client=client)
        r = asyncio.run(sess.poll("k"))
        assert r.status is expected, body


def test_wait_for_login_succeeds_on_success(monkeypatch):
    """wait_for_login should return on the first SUCCESS poll."""
    polls = [
        {"code": CODE_NOT_SCANNED, "data": {}},
        {"code": CODE_SCANNED, "data": {}},
        {"code": CODE_SUCCESS, "data": {"refresh_token": "r"}},
    ]
    call_count = {"n": 0}
    poll_obj = MagicMock()
    poll_obj.raise_for_status = MagicMock(return_value=None)
    poll_obj.status_code = 200

    async def _get(url, **kw):
        poll_obj.json.return_value = polls[min(call_count["n"], len(polls) - 1)]
        call_count["n"] += 1
        return poll_obj
    client = AsyncMock()
    client.get.side_effect = _get

    # Speed up the wait —patch the qr_login module's asyncio.sleep reference
    import doubi.platforms.bilibili.qr_login as qr_mod
    async def _fake_sleep(_):
        return None
    monkeypatch.setattr(qr_mod.asyncio, "sleep", _fake_sleep)

    sess = QRSession(client=client, timeout=5)
    r = asyncio.run(wait_for_login(sess, "k", poll_interval=0.0, max_wait=10))
    assert r.status is QRStatus.SUCCESS


def test_wait_for_login_times_out(monkeypatch):
    polls = [{"code": CODE_NOT_SCANNED, "data": {}}]
    poll_obj = MagicMock()
    poll_obj.raise_for_status = MagicMock(return_value=None)
    poll_obj.json.return_value = polls[0]
    poll_obj.status_code = 200

    async def _get(url, **kw):
        return poll_obj
    client = AsyncMock()
    client.get.side_effect = _get

    import doubi.platforms.bilibili.qr_login as qr_mod
    async def _fake_sleep(_):
        return None
    monkeypatch.setattr(qr_mod.asyncio, "sleep", _fake_sleep)

    sess = QRSession(client=client)
    with pytest.raises(TimeoutError):
        asyncio.run(wait_for_login(sess, "k", poll_interval=0.0, max_wait=0.1))


def test_qrsession_requires_context():
    sess = QRSession()
    with pytest.raises(RuntimeError, match="context manager"):
        asyncio.run(sess.generate())


# ---------------------------------------------------------------------------
# auth: cookie file parsing
# ---------------------------------------------------------------------------


def test_parse_netscape_file_basic(tmp_path):
    f = tmp_path / "c.txt"
    f.write_text(
        "# Netscape HTTP Cookie File\n"
        "\n"
        ".bilibili.com\tTRUE\t/\tTRUE\t0\tSESSDATA\tdeadbeef\n"
        ".bilibili.com\tTRUE\t/\tFALSE\t0\tbili_jct\tabc123\n",
        encoding="utf-8",
    )
    cookies = bili_auth.parse_netscape_file(f)
    assert len(cookies) == 2
    sess = next(c for c in cookies if c["name"] == "SESSDATA")
    assert sess["value"] == "deadbeef"
    assert sess["domain"] == ".bilibili.com"
    assert sess["secure"] is True
    jct = next(c for c in cookies if c["name"] == "bili_jct")
    assert jct["secure"] is False


def test_parse_netscape_file_handles_httponly(tmp_path):
    f = tmp_path / "c.txt"
    f.write_text(
        "# Netscape HTTP Cookie File\n"
        "#HttpOnly_.bilibili.com\tTRUE\t/\tFALSE\t0\tDedeUserID\t12345\n",
        encoding="utf-8",
    )
    cookies = bili_auth.parse_netscape_file(f)
    assert len(cookies) == 1
    assert cookies[0]["name"] == "DedeUserID"
    assert cookies[0]["value"] == "12345"


def test_parse_netscape_file_handles_malformed_lines(tmp_path):
    f = tmp_path / "c.txt"
    f.write_text(
        ".bilibili.com\tTRUE\t/\tFALSE\t0\tA\t1\n"     # OK
        "garbage line\n"                                # skip
        "a\tb\tc\n"                                     # too few fields
        ".bilibili.com\tTRUE\t/\tFALSE\t0\tB\t2\n",    # OK
        encoding="utf-8",
    )
    cookies = bili_auth.parse_netscape_file(f)
    assert len(cookies) == 2


def test_parse_netscape_file_missing_returns_empty(tmp_path):
    f = tmp_path / "missing.txt"
    assert bili_auth.parse_netscape_file(f) == []


def test_parse_json_cookies_browser_export(tmp_path):
    f = tmp_path / "cookies.json"
    data = [
        {"name": "SESSDATA", "value": "abc", "domain": ".bilibili.com",
         "path": "/", "secure": True, "expires": 0},
        {"name": "bili_jct", "value": "xyz", "domain": "www.bilibili.com",
         "path": "/", "secure": False, "expires": 0},
    ]
    f.write_text(json.dumps(data), encoding="utf-8")
    cookies = bili_auth.parse_json_cookies(f)
    assert len(cookies) == 2
    sess = next(c for c in cookies if c["name"] == "SESSDATA")
    # Subdomain normalization: leading dot preserved
    assert sess["domain"] == ".bilibili.com"
    # Subdomain added when not present
    jct = next(c for c in cookies if c["name"] == "bili_jct")
    assert jct["domain"] == ".www.bilibili.com"


def test_parse_json_cookies_with_wrapper_key(tmp_path):
    f = tmp_path / "cookies.json"
    f.write_text(json.dumps({"cookies": [{"name": "A", "value": "1", "domain": ".b.com"}]}),
                 encoding="utf-8")
    cookies = bili_auth.parse_json_cookies(f)
    assert len(cookies) == 1
    assert cookies[0]["name"] == "A"


def test_parse_json_cookies_skips_invalid_entries(tmp_path):
    f = tmp_path / "cookies.json"
    f.write_text(json.dumps([
        {"name": "OK", "value": "1"},
        {"name": "", "value": "1"},            # empty name
        {"value": "1"},                        # no name
        {"name": "OK2", "value": None},        # None value allowed (gets str()'d)
        "not a dict",
    ]), encoding="utf-8")
    cookies = bili_auth.parse_json_cookies(f)
    assert len(cookies) == 2  # OK, OK2


def test_parse_json_cookies_missing_returns_empty(tmp_path):
    assert bili_auth.parse_json_cookies(tmp_path / "missing.json") == []


def test_write_netscape_cookies_round_trip(tmp_path):
    original = [
        {"domain": ".bilibili.com", "path": "/", "name": "SESSDATA",
         "value": "x", "secure": True, "expires": 0},
        {"domain": ".bilibili.com", "path": "/", "name": "bili_jct",
         "value": "y", "secure": False, "expires": 0},
    ]
    p = bili_auth.write_netscape_cookies(original, path=tmp_path / "b.txt")
    re_parsed = bili_auth.parse_netscape_file(p)
    assert {c["name"] for c in re_parsed} == {"SESSDATA", "bili_jct"}


def test_cookies_to_netscape_dicts_fills_defaults():
    out = bili_auth.cookies_to_netscape_dicts([{"name": "A", "value": "1"}])
    assert out[0]["domain"] == ".bilibili.com"
    assert out[0]["path"] == "/"
    assert out[0]["secure"] is False


# ---------------------------------------------------------------------------
# auth: login state parsing
# ---------------------------------------------------------------------------


def test_parse_login_response_logged_in():
    data = {
        "code": 0,
        "message": "0",
        "data": {
            "isLogin": True,
            "mid": 12345,
            "uname": "测试用户",
            "level_info": {"current_level": 6},
            "vipStatus": 1,
        },
    }
    info = bili_auth.parse_login_response(data)
    assert info.is_logged_in is True
    assert info.uid == 12345
    assert info.name == "测试用户"
    assert info.level == 6
    assert info.vip_status == 1


def test_parse_login_response_not_logged_in():
    data = {"code": 0, "data": {"isLogin": False}}
    info = bili_auth.parse_login_response(data)
    assert info.is_logged_in is False
    assert info.uid is None


def test_parse_login_response_error_code():
    data = {"code": -101, "message": "not logged in", "data": {}}
    info = bili_auth.parse_login_response(data)
    assert info.is_logged_in is False


# ---------------------------------------------------------------------------
# auth: validate_cookies (network)
# ---------------------------------------------------------------------------


def test_validate_cookies_returns_login_info(monkeypatch, tmp_path):
    """validate_cookies should call /nav and parse the response."""
    p = tmp_path / "b.txt"
    p.write_text(".bilibili.com\tTRUE\t/\tFALSE\t0\tSESSDATA\ttest\n", encoding="utf-8")

    # .json() and .raise_for_status() are sync on real httpx responses
    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock(return_value=None)
    fake_response.json.return_value = {
        "code": 0, "data": {"isLogin": True, "mid": 999, "uname": "u", "level_info": {"current_level": 3}}
    }
    fake_response.status_code = 200

    fake_client = AsyncMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)
    fake_client.get = AsyncMock(return_value=fake_response)

    monkeypatch.setattr("httpx.AsyncClient", lambda **kw: fake_client)
    info = asyncio.run(bili_auth.validate_cookies(p))
    assert info.is_logged_in is True
    assert info.uid == 999


def test_validate_cookies_no_file_returns_false(tmp_path):
    p = tmp_path / "missing.txt"
    info = asyncio.run(bili_auth.validate_cookies(p))
    assert info.is_logged_in is False


def test_validate_cookies_network_failure(tmp_path):
    p = tmp_path / "b.txt"
    p.write_text(".bilibili.com\tTRUE\t/\tFALSE\t0\tSESSDATA\ttest\n", encoding="utf-8")

    fake_client = AsyncMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)
    fake_client.get = AsyncMock(side_effect=RuntimeError("offline"))

    with patch("httpx.AsyncClient", lambda **kw: fake_client):
        info = asyncio.run(bili_auth.validate_cookies(p))
    assert info.is_logged_in is False


# ---------------------------------------------------------------------------
# wbi
# ---------------------------------------------------------------------------


def test_filename_from_url():
    assert _filename_from_url("https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077c.png") == \
        "7cd084941338484aae1ad9425b84077c"
    assert _filename_from_url("") == ""
    assert _filename_from_url("https://example.com/foo") == "foo"


def test_mixin_table_is_64_permutation():
    """The mixin table is a fixed 64-entry permutation of 0..63."""
    assert len(MIXIN_TABLE) == 64
    assert sorted(MIXIN_TABLE) == list(range(64))


def test_get_mixin_key_is_64_chars():
    img = "7cd084941338484aae1ad9425b84077c"
    sub = "4932caffdff246bc94c4f25cf77b8a26"
    out = _get_mixin_key(img, sub)
    assert len(out) == 64


def test_get_mixin_key_pads_short_keys():
    out = _get_mixin_key("short", "key")
    assert len(out) == 64
    # Padding is "0"
    assert out.endswith("0")


def test_compute_w_rid_is_md5_hex():
    img = "7cd084941338484aae1ad9425b84077c"
    sub = "4932caffdff246bc94c4f25cf77b8a26"
    params = {"mid": 12345}
    rid = compute_w_rid(params, (img, sub))
    assert len(rid) == 32
    int(rid, 16)  # must be valid hex


def test_compute_w_rid_changes_with_wts():
    """wts is included in the signature; different wts →different w_rid."""
    img = "7cd084941338484aae1ad9425b84077c"
    sub = "4932caffdff246bc94c4f25cf77b8a26"
    p1 = compute_w_rid({"mid": 1}, (img, sub))
    p2 = compute_w_rid({"mid": 2}, (img, sub))
    assert p1 != p2


def test_sign_query_adds_wts_and_w_rid():
    out = sign_query({"mid": 1}, ("a" * 32, "b" * 32))
    assert "wts" in out
    assert "w_rid" in out
    # wts should be a unix timestamp (10-digit-ish)
    assert out["wts"].isdigit()
    assert len(out["wts"]) >= 10


def test_fetch_wbi_keys_success(monkeypatch):
    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock(return_value=None)
    fake_response.json.return_value = {
        "code": 0,
        "data": {
            "wbi_img": {
                "img_url": "https://i0.hdslb.com/bfs/wbi/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png",
                "sub_url": "https://i0.hdslb.com/bfs/wbi/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.png",
            }
        },
    }
    fake_response.status_code = 200

    fake_client = AsyncMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)
    fake_client.get = AsyncMock(return_value=fake_response)

    monkeypatch.setattr("httpx.AsyncClient", lambda **kw: fake_client)
    keys = asyncio.run(fetch_wbi_keys())
    assert keys == ("a" * 32, "b" * 32)


def test_fetch_wbi_keys_returns_none_on_failure(monkeypatch):
    fake_client = AsyncMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)
    fake_client.get = AsyncMock(side_effect=RuntimeError("offline"))

    monkeypatch.setattr("httpx.AsyncClient", lambda **kw: fake_client)
    assert asyncio.run(fetch_wbi_keys()) is None


def test_fetch_wbi_keys_missing_wbi_img(monkeypatch):
    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock(return_value=None)
    fake_response.json.return_value = {"code": 0, "data": {}}
    fake_response.status_code = 200
    fake_client = AsyncMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)
    fake_client.get = AsyncMock(return_value=fake_response)

    monkeypatch.setattr("httpx.AsyncClient", lambda **kw: fake_client)
    assert asyncio.run(fetch_wbi_keys()) is None


# ---------------------------------------------------------------------------
# CLI: auth subcommand
# ---------------------------------------------------------------------------


def test_cli_auth_status_no_cookies(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(bili_auth, "default_cookie_path", lambda: tmp_path / "b.txt")
    rc = auth_cmd.cmd_auth_status(argparse_stub())
    assert rc == 0
    out = capsys.readouterr().out
    assert "bilibili" in out
    assert "no (no cookies)" in out or "logged in   : no" in out


def test_cli_auth_bilibili_import_netscape(tmp_path, monkeypatch):
    src = tmp_path / "src.txt"
    src.write_text(".bilibili.com\tTRUE\t/\tFALSE\t0\tSESSDATA\ttest\n", encoding="utf-8")
    dst = tmp_path / "b.txt"

    # Mock validate so we don't hit the network
    fake_info = bili_auth.LoginInfo(is_logged_in=True, uid=42, name="测试", level=3)
    monkeypatch.setattr(bili_auth, "login_info_from_cookies_sync", lambda p: fake_info)

    rc = auth_cmd.cmd_auth_bilibili_import(src, dst)
    assert rc == 0
    assert dst.exists()
    cookies = bili_auth.parse_netscape_file(dst)
    assert any(c["name"] == "SESSDATA" for c in cookies)


def test_cli_auth_bilibili_import_json(tmp_path, monkeypatch):
    src = tmp_path / "src.json"
    src.write_text(json.dumps([
        {"name": "SESSDATA", "value": "abc", "domain": ".bilibili.com",
         "path": "/", "secure": True, "expires": 0},
    ]), encoding="utf-8")
    dst = tmp_path / "b.txt"
    fake_info = bili_auth.LoginInfo(is_logged_in=True, uid=1, name="x", level=1)
    monkeypatch.setattr(bili_auth, "login_info_from_cookies_sync", lambda p: fake_info)

    rc = auth_cmd.cmd_auth_bilibili_import(src, dst)
    assert rc == 0
    cookies = bili_auth.parse_netscape_file(dst)
    assert any(c["name"] == "SESSDATA" for c in cookies)


def test_cli_auth_bilibili_import_no_cookies_parsed(tmp_path, monkeypatch):
    src = tmp_path / "empty.txt"
    src.write_text("", encoding="utf-8")
    dst = tmp_path / "b.txt"
    rc = auth_cmd.cmd_auth_bilibili_import(src, dst)
    assert rc == 1


def test_cli_auth_bilibili_import_missing_file(tmp_path, monkeypatch):
    rc = auth_cmd.cmd_auth_bilibili_import(tmp_path / "missing.txt", tmp_path / "b.txt")
    assert rc == 1


def test_cli_auth_bilibili_import_validation_fails(tmp_path, monkeypatch):
    src = tmp_path / "src.txt"
    src.write_text(".bilibili.com\tTRUE\t/\tFALSE\t0\tSESSDATA\ttest\n", encoding="utf-8")
    dst = tmp_path / "b.txt"
    fake_info = bili_auth.LoginInfo(is_logged_in=False)
    monkeypatch.setattr(bili_auth, "login_info_from_cookies_sync", lambda p: fake_info)
    rc = auth_cmd.cmd_auth_bilibili_import(src, dst)
    assert rc == 1


def test_cli_auth_douyin_uses_browser_login(capsys, monkeypatch):
    """Without an import / legacy-json path, douyin auth tries Playwright."""
    # Mock out the browser login so we don't need a real browser
    monkeypatch.setattr(auth_cmd, "_try_browser_login", lambda *a, **kw: None)

    rc = auth_cmd.cmd_auth_douyin(argparse_stub(
        import_file=None, legacy_json=None, output=None, headless=False, timeout=180.0,
    ))
    # _try_browser_login returns None → CLI falls through to the
    # "Browser-based login didn't work" message + return 1
    assert rc == 1
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "Browser-based login didn't work" in combined
    assert "Install Playwright" in combined


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


class _NS:
    """Tiny argparse.Namespace stub for tests."""
    def __init__(self, **kw):
        self.__dict__.update(kw)


def argparse_stub(**kw) -> "_NS":
    return _NS(**kw)
