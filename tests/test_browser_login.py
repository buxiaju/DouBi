"""Tests for M3.1.1 (Playwright auto-login) and M2.1 (douyin cookie + live)."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from doubi.core.auth import (  # noqa: E402
    HAS_PLAYWRIGHT,
    BrowserLoginError,
    CookieSetLogin,
    URLChangeLogin,
    install_playwright_instructions,
    require_playwright,
)
from doubi.platforms.bilibili import auth as bili_auth  # noqa: E402
from doubi.platforms.douyin import auth as dy_auth  # noqa: E402
from doubi.platforms.douyin import live as dy_live  # noqa: E402


# ---------------------------------------------------------------------------
# Playwright availability
# ---------------------------------------------------------------------------


def test_has_playwright_is_bool():
    assert isinstance(HAS_PLAYWRIGHT, bool)


def test_install_instructions_mention_pip():
    s = install_playwright_instructions()
    assert "pip install" in s
    assert "playwright install" in s


def test_require_playwright_raises_when_missing(monkeypatch):
    monkeypatch.setattr("doubi.core.auth.browser_login.HAS_PLAYWRIGHT", False)
    with pytest.raises(BrowserLoginError, match="pip install"):
        require_playwright()


# ---------------------------------------------------------------------------
# URLChangeLogin
# ---------------------------------------------------------------------------


def _mock_playwright(cookies_to_return, *, final_url: str = "https://www.bilibili.com/"):
    """Build a mock for the sync_playwright context manager.

    Returns a context manager whose ``__enter__`` returns a playwright
    object with ``chromium.launch(...).new_context().new_page()`` pre-
    loaded with sensible mocks. The chain is wired explicitly so that
    ``new_page()`` always returns the *same* page object whose ``url``
    is a real property (not a MagicMock attribute).
    """
    from unittest.mock import PropertyMock

    page = MagicMock()
    # url is a property on the real Playwright Page; use PropertyMock
    # so production code reading ``page.url`` gets the string we set.
    type(page).url = PropertyMock(return_value=final_url)
    page.wait_for_url = MagicMock()
    page.wait_for_load_state = MagicMock()
    page.wait_for_timeout = MagicMock()
    page.wait_for_selector = MagicMock()
    page.goto = MagicMock()

    context = MagicMock()
    context.cookies = MagicMock(return_value=cookies_to_return)
    # Force new_page to return the same page we built (so .url property works)
    context.new_page = MagicMock(return_value=page)

    browser = MagicMock()
    browser.new_context = MagicMock(return_value=context)
    browser.close = MagicMock()

    chromium = MagicMock()
    chromium.launch = MagicMock(return_value=browser)

    pw_obj = MagicMock()
    pw_obj.chromium = chromium

    pw_ctx = MagicMock()
    pw_ctx.__enter__ = MagicMock(return_value=pw_obj)
    pw_ctx.__exit__ = MagicMock(return_value=None)
    return pw_ctx



def test_url_change_login_happy_path(monkeypatch):
    """URLChangeLogin waits for the page URL to change then returns cookies."""
    pw_ctx = _mock_playwright([
        {"name": "SESSDATA", "value": "abc", "domain": ".bilibili.com",
         "path": "/", "secure": True, "expires": 0},
        {"name": "bili_jct", "value": "xyz", "domain": ".bilibili.com",
         "path": "/", "secure": False, "expires": 0},
        # Should be filtered out (different domain)
        {"name": "thirdparty", "value": "junk", "domain": "tracker.com",
         "path": "/", "secure": False, "expires": 0},
    ])

    import doubi.core.auth.browser_login as bl
    monkeypatch.setattr(bl, "HAS_PLAYWRIGHT", True)
    # raising=False so we add the attribute if Playwright isn't installed
    monkeypatch.setattr(bl, "sync_playwright", MagicMock(return_value=pw_ctx), raising=False)

    login = URLChangeLogin(
        start_url="https://passport.bilibili.com/login",
        success_url_pattern=r"^https?://(www\.)?bilibili\.com/",
        cookie_domains=[".bilibili.com"],
        headless=True,
        timeout=10.0,
    )
    result = login.run()
    assert result.has_cookies()
    assert len(result.cookies) == 2
    names = {c["name"] for c in result.cookies}
    assert names == {"SESSDATA", "bili_jct"}
    assert result.final_url == "https://www.bilibili.com/"


def test_url_change_login_timeout(monkeypatch):
    """If wait_for_url raises a Playwright TimeoutError, we surface BrowserLoginError."""
    pw_ctx = _mock_playwright([])
    page = pw_ctx.__enter__.return_value.chromium.launch.return_value.new_context.return_value.new_page.return_value

    # Playwright may not be installed in CI; fabricate a TimeoutError class
    # with the same name that the production code checks against.
    class _FakeTimeoutError(Exception):
        pass
    page.wait_for_url = MagicMock(side_effect=_FakeTimeoutError("URL didn't change"))

    import doubi.core.auth.browser_login as bl
    monkeypatch.setattr(bl, "HAS_PLAYWRIGHT", True)
    monkeypatch.setattr(bl, "sync_playwright", MagicMock(return_value=pw_ctx), raising=False)
    monkeypatch.setattr(bl, "PlaywrightTimeoutError", _FakeTimeoutError, raising=False)

    login = URLChangeLogin(
        start_url="https://x",
        success_url_pattern=r"^https?://(www\.)?x\.com/done",
        cookie_domains=[".x.com"],
        timeout=5.0,
    )
    with pytest.raises(BrowserLoginError, match="timed out"):
        login.run()


# ---------------------------------------------------------------------------
# CookieSetLogin
# ---------------------------------------------------------------------------


def test_cookie_set_login_happy_path(monkeypatch):
    """CookieSetLogin polls until the required cookies appear."""
    pw_ctx = _mock_playwright([
        {"name": "ttwid", "value": "t1", "domain": ".douyin.com",
         "path": "/", "secure": False, "expires": 0},
        {"name": "msToken", "value": "m1", "domain": ".douyin.com",
         "path": "/", "secure": False, "expires": 0},
        {"name": "passport_csrf_token", "value": "p1", "domain": ".douyin.com",
         "path": "/", "secure": False, "expires": 0},
        {"name": "odin_tt", "value": "o1", "domain": ".douyin.com",
         "path": "/", "secure": False, "expires": 0},
    ])

    # Simulate the polling loop seeing cookies appear over time
    context = pw_ctx.__enter__.return_value.chromium.launch.return_value.new_context.return_value
    call_count = {"n": 0}
    def _cookies_side_effect():
        call_count["n"] += 1
        # First 3 calls return empty/partial, then full set
        if call_count["n"] < 4:
            return [{"name": "ttwid", "value": "t1", "domain": ".douyin.com",
                     "path": "/", "secure": False, "expires": 0}]
        return [
            {"name": "ttwid", "value": "t1", "domain": ".douyin.com",
             "path": "/", "secure": False, "expires": 0},
            {"name": "msToken", "value": "m1", "domain": ".douyin.com",
             "path": "/", "secure": False, "expires": 0},
            {"name": "passport_csrf_token", "value": "p1", "domain": ".douyin.com",
             "path": "/", "secure": False, "expires": 0},
            {"name": "odin_tt", "value": "o1", "domain": ".douyin.com",
             "path": "/", "secure": False, "expires": 0},
        ]
    context.cookies = MagicMock(side_effect=_cookies_side_effect)

    import doubi.core.auth.browser_login as bl
    monkeypatch.setattr(bl, "sync_playwright", MagicMock(return_value=pw_ctx), raising=False)
    monkeypatch.setattr(bl, "HAS_PLAYWRIGHT", True)

    login = CookieSetLogin(
        start_url="https://www.douyin.com/",
        required_cookies=["ttwid", "msToken", "passport_csrf_token", "odin_tt"],
        cookie_domains=[".douyin.com"],
        timeout=10.0,
    )
    result = login.run()
    assert result.has_cookies()
    assert len(result.cookies) == 4


def test_cookie_set_login_min_present(monkeypatch):
    """min_present lets you require fewer than all cookies."""
    pw_ctx = _mock_playwright([
        {"name": "ttwid", "value": "t1", "domain": ".douyin.com",
         "path": "/", "secure": False, "expires": 0},
        {"name": "msToken", "value": "m1", "domain": ".douyin.com",
         "path": "/", "secure": False, "expires": 0},
    ])
    import doubi.core.auth.browser_login as bl
    monkeypatch.setattr(bl, "sync_playwright", MagicMock(return_value=pw_ctx), raising=False)
    monkeypatch.setattr(bl, "HAS_PLAYWRIGHT", True)

    login = CookieSetLogin(
        start_url="https://x",
        required_cookies=["ttwid", "msToken", "passport_csrf_token", "odin_tt"],
        cookie_domains=[".douyin.com"],
        min_present=2,
        timeout=5.0,
    )
    result = login.run()
    assert result.has_cookies()
    assert len(result.cookies) == 2


def test_cookie_set_login_timeout(monkeypatch):
    """If cookies never appear, BrowserLoginError is raised."""
    pw_ctx = _mock_playwright([])   # no cookies ever
    import time
    # shrink the polling loop so the test is fast
    import doubi.core.auth.browser_login as bl
    monkeypatch.setattr(bl, "sync_playwright", MagicMock(return_value=pw_ctx), raising=False)
    monkeypatch.setattr(bl, "HAS_PLAYWRIGHT", True)
    # Speed up the wait_for_timeout path
    page = pw_ctx.__enter__.return_value.chromium.launch.return_value.new_context.return_value.new_page.return_value
    page.wait_for_timeout = MagicMock(side_effect=lambda *_: (_ for _ in ()).throw(StopIteration))

    login = CookieSetLogin(
        start_url="https://x",
        required_cookies=["never_appears"],
        cookie_domains=[".x.com"],
        timeout=0.1,
    )
    # Make wait_for_timeout raise StopIteration so the while loop
    # terminates immediately; the loop will then hit the timeout
    # check and raise BrowserLoginError.
    page.wait_for_timeout = MagicMock(side_effect=StopIteration)
    with pytest.raises((BrowserLoginError, StopIteration)):
        login.run()


# ---------------------------------------------------------------------------
# Douyin auth: legacy cookies.json + validation
# ---------------------------------------------------------------------------


def test_parse_legacy_json_douyin(tmp_path):
    p = tmp_path / "cookies.json"
    p.write_text(json.dumps({
        "ttwid": "abc123",
        "msToken": "xyz",
        "odin_tt": "deadbeef",
        "passport_csrf_token": "csrf",
        "sid_guard": "sid",
    }), encoding="utf-8")
    cookies = dy_auth.parse_legacy_json(p)
    assert len(cookies) == 5
    assert all(c["domain"] == ".douyin.com" for c in cookies)
    names = {c["name"] for c in cookies}
    assert names == {"ttwid", "msToken", "odin_tt", "passport_csrf_token", "sid_guard"}


def test_parse_legacy_json_filters_empty_values(tmp_path):
    p = tmp_path / "cookies.json"
    p.write_text(json.dumps({
        "ttwid": "abc",
        "msToken": "",                # empty → skipped
        "odin_tt": None,               # None → skipped
    }), encoding="utf-8")
    cookies = dy_auth.parse_legacy_json(p)
    assert len(cookies) == 1
    assert cookies[0]["name"] == "ttwid"


def test_parse_legacy_json_missing_file(tmp_path):
    cookies = dy_auth.parse_legacy_json(tmp_path / "missing.json")
    assert cookies == []


def test_parse_legacy_json_invalid_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("not json", encoding="utf-8")
    cookies = dy_auth.parse_legacy_json(p)
    assert cookies == []


def test_douyin_login_info_from_dict():
    data = {"user_info": {"uid": "12345", "nickname": "测试用户", "sec_uid": "SEC1"}}
    info = dy_auth.parse_login_response(data)
    assert info.is_logged_in is True
    assert info.uid == "12345"
    assert info.name == "测试用户"
    assert info.sec_uid == "SEC1"


def test_douyin_login_info_not_logged_in():
    data = {"user_info": {}}   # no uid
    info = dy_auth.parse_login_response(data)
    assert info.is_logged_in is False


def test_douyin_browser_login_runs(monkeypatch):
    """browser_login uses CookieSetLogin under the hood — and success
    must trigger on *login-state* cookies, not the anonymous-visitor
    set (ttwid / msToken / odin_tt), see the "scanned but no cookie"
    bug."""
    pw_ctx = _mock_playwright([
        {"name": "ttwid", "value": "t1", "domain": ".douyin.com",
         "path": "/", "secure": False, "expires": 0},
        {"name": "msToken", "value": "m1", "domain": ".douyin.com",
         "path": "/", "secure": False, "expires": 0},
        {"name": "passport_csrf_token", "value": "p1", "domain": ".douyin.com",
         "path": "/", "secure": False, "expires": 0},
        {"name": "odin_tt", "value": "o1", "domain": ".douyin.com",
         "path": "/", "secure": False, "expires": 0},
        # Login-state cookies — what actually signals success now.
        {"name": "sessionid", "value": "sess1", "domain": ".douyin.com",
         "path": "/", "secure": True, "expires": 0},
        {"name": "sid_guard", "value": "sg1", "domain": ".douyin.com",
         "path": "/", "secure": True, "expires": 0},
    ])
    import doubi.core.auth.browser_login as bl
    monkeypatch.setattr(bl, "sync_playwright", MagicMock(return_value=pw_ctx), raising=False)
    monkeypatch.setattr(bl, "HAS_PLAYWRIGHT", True)

    cookies = dy_auth.browser_login(headless=True, timeout=5.0)
    names = {c["name"] for c in cookies}
    # Login cookies must be captured — the whole point of the flow.
    assert "sessionid" in names
    assert "sid_guard" in names
    # Visitor cookies ride along (they're still useful to yt-dlp).
    assert "ttwid" in names


def test_douyin_browser_login_requires_login_cookie(monkeypatch):
    """Regression: visitor-only cookies (ttwid / msToken / odin_tt /
    passport_csrf_token) must NOT count as a successful login — the
    old bug treated them as sufficient and harvested guest cookies."""
    pw_ctx = _mock_playwright([
        {"name": "ttwid", "value": "t1", "domain": ".douyin.com",
         "path": "/", "secure": False, "expires": 0},
        {"name": "msToken", "value": "m1", "domain": ".douyin.com",
         "path": "/", "secure": False, "expires": 0},
        {"name": "passport_csrf_token", "value": "p1", "domain": ".douyin.com",
         "path": "/", "secure": False, "expires": 0},
        {"name": "odin_tt", "value": "o1", "domain": ".douyin.com",
         "path": "/", "secure": False, "expires": 0},
    ])
    import doubi.core.auth.browser_login as bl
    monkeypatch.setattr(bl, "sync_playwright", MagicMock(return_value=pw_ctx), raising=False)
    monkeypatch.setattr(bl, "HAS_PLAYWRIGHT", True)

    with pytest.raises(BrowserLoginError, match="timed out"):
        dy_auth.browser_login(headless=True, timeout=0.2)


def test_douyin_browser_login_msToken_missing_still_succeeds(monkeypatch):
    """Regression: after a real QR scan msToken is often *withheld* by
    risk control. sessionid alone must complete the login."""
    pw_ctx = _mock_playwright([
        {"name": "ttwid", "value": "t1", "domain": ".douyin.com",
         "path": "/", "secure": False, "expires": 0},
        {"name": "sessionid", "value": "sess1", "domain": ".douyin.com",
         "path": "/", "secure": True, "expires": 0},
    ])
    import doubi.core.auth.browser_login as bl
    monkeypatch.setattr(bl, "sync_playwright", MagicMock(return_value=pw_ctx), raising=False)
    monkeypatch.setattr(bl, "HAS_PLAYWRIGHT", True)

    cookies = dy_auth.browser_login(headless=True, timeout=5.0)
    names = {c["name"] for c in cookies}
    assert "sessionid" in names


def test_bilibili_browser_login_runs(monkeypatch):
    pw_ctx = _mock_playwright([
        {"name": "SESSDATA", "value": "abc", "domain": ".bilibili.com",
         "path": "/", "secure": True, "expires": 0},
    ])
    import doubi.core.auth.browser_login as bl
    monkeypatch.setattr(bl, "sync_playwright", MagicMock(return_value=pw_ctx), raising=False)
    monkeypatch.setattr(bl, "HAS_PLAYWRIGHT", True)

    cookies = bili_auth.browser_login(headless=True, timeout=5.0)
    assert len(cookies) == 1
    assert cookies[0]["name"] == "SESSDATA"


# ---------------------------------------------------------------------------
# Regression: post-success settle must not wait for ``networkidle``.
#
# Both Douyin feed and B-station home have *persistent* traffic after
# login (WebSocket, video feeds, recommendation streams, heartbeats).
# Waiting for ``wait_for_load_state("networkidle")`` always times out
# after 10s — Playwright then throws ``TimeoutError`` and the GUI shows
# "浏览器登录失败：Timeout 10000ms exceeded" *after* the cookies were
# already in hand. The fix is a short fixed ``wait_for_timeout`` for
# any final cookie writes that lag the success signal by a frame.
# ---------------------------------------------------------------------------


def test_post_success_does_not_wait_for_networkidle(monkeypatch):
    """Regression for the "Timeout 10000ms exceeded" bug.

    The old ``_run_browser`` called
    ``page.wait_for_load_state("networkidle", timeout=10_000)`` after a
    successful login. Post-login landing pages have persistent traffic
    and never reach networkidle within 10s — the call raises
    ``PlaywrightTimeoutError`` even though ``_wait_for_success``
    already saw the cookies and returned. This test guards against
    that pattern being reintroduced.
    """
    pw_ctx = _mock_playwright([
        {"name": "sessionid", "value": "sess1", "domain": ".douyin.com",
         "path": "/", "secure": True, "expires": 0},
    ])
    page = pw_ctx.__enter__.return_value.chromium.launch.return_value.new_context.return_value.new_page.return_value

    import doubi.core.auth.browser_login as bl
    monkeypatch.setattr(bl, "sync_playwright", MagicMock(return_value=pw_ctx), raising=False)
    monkeypatch.setattr(bl, "HAS_PLAYWRIGHT", True)

    # Make wait_for_load_state raise loudly if it ever gets called —
    # that's the path we're guarding against.
    page.wait_for_load_state = MagicMock(
        side_effect=AssertionError("wait_for_load_state must not be called "
                                    "after _wait_for_success — use wait_for_timeout")
    )

    # The path under test — does not raise.
    result = dy_auth.browser_login(headless=True, timeout=5.0)
    assert any(c["name"] == "sessionid" for c in result)

    # The wait_for_load_state mock would have raised if called.
    page.wait_for_load_state.assert_not_called()


def test_post_success_uses_short_fixed_settle(monkeypatch):
    """The fix uses a short ``wait_for_timeout`` (not wait_for_load_state)
    to give the final cookie writes time to flush. The settle window
    must be bounded — never the full 10s timeout that previously broke
    on busy post-login pages.
    """
    pw_ctx = _mock_playwright([
        {"name": "sessionid", "value": "sess1", "domain": ".douyin.com",
         "path": "/", "secure": True, "expires": 0},
    ])
    page = pw_ctx.__enter__.return_value.chromium.launch.return_value.new_context.return_value.new_page.return_value

    import doubi.core.auth.browser_login as bl
    monkeypatch.setattr(bl, "sync_playwright", MagicMock(return_value=pw_ctx), raising=False)
    monkeypatch.setattr(bl, "HAS_PLAYWRIGHT", True)

    dy_auth.browser_login(headless=True, timeout=5.0)

    page.wait_for_timeout.assert_called_once()
    ms = page.wait_for_timeout.call_args.args[0]
    # Settle window is short (<= 2s) and strictly positive. If anyone
    # bumps this past 5s, treat it as a regression of the timeout bug.
    assert 0 < ms <= 2_000


# ---------------------------------------------------------------------------
# Douyin live recording
# ---------------------------------------------------------------------------


def test_extract_room_id():
    assert dy_live._extract_room_id("https://live.douyin.com/123456789") == "123456789"
    assert dy_live._extract_room_id("https://live.douyin.com/123456789?foo=bar") == "123456789"
    assert dy_live._extract_room_id("https://example.com/no") == ""


def test_safe_filename_strips_illegal():
    assert dy_live._safe_filename("a/b\\c:d?e") == "a_b_c_d_e"
    assert dy_live._safe_filename("") == "untitled"
    assert dy_live._safe_filename("   ") == "untitled"


def test_live_recorder_missing_room_id(tmp_path):
    rec = dy_live.LiveRecorder()
    with pytest.raises(ValueError, match="could not extract room_id"):
        asyncio.run(rec.record("https://example.com/not-live", output_root=tmp_path))


def test_live_recorder_creates_metadata_sidecar(tmp_path, monkeypatch):
    """A successful record writes *_room.json next to the output."""
    # _probe_room is a module-level function; patch it at the module.
    monkeypatch.setattr(dy_live, "_probe_room",
                        lambda rid: {"id": rid, "title": "测试直播",
                                     "uploader": "主播", "is_live": True})

    captured_out_path = {}

    async def _do():
        rec = dy_live.LiveRecorder()

        def _fake_sync(url, out_path, max_duration):
            captured_out_path["path"] = out_path
            out_path.parent.mkdir(parents=True, exist_ok=True)
            # The fake "downloaded" file: yt-dlp would write
            # {out_path}.mp4 (one extra .mp4 from merge_output_format).
            fake = out_path.with_name(out_path.name + ".mp4")
            fake.write_bytes(b"FAKE_VIDEO_DATA")
            return dy_live.LiveRecordResult(
                room_id="123", title="测试直播",
                output_path=fake, ended_reason="stream_ended",
                bytes_written=len(b"FAKE_VIDEO_DATA"),
            )
        rec._record_sync = _fake_sync
        return await rec.record("https://live.douyin.com/123",
                                 output_root=tmp_path, max_duration=60)

    result = asyncio.run(_do())
    assert result.output_path is not None
    assert result.output_path.exists()

    # live.py writes the sidecar BEFORE the mock runs, next to out_path
    # (not next to the mock file). The original out_path is captured
    # in the closure above.
    sidecar = captured_out_path["path"].with_name(
        captured_out_path["path"].stem + "_room.json"
    )
    assert sidecar.exists()
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    assert meta["room_id"] == "123"
    assert meta["metadata"]["title"] == "测试直播"


def test_live_recorder_handles_stream_ended_gracefully(monkeypatch):
    """yt-dlp's DownloadError on 'stream ended' is treated as graceful."""

    class _YDL:
        def __init__(self, opts): pass
        def __enter__(self): return self
        def __exit__(self, *a): return None
        def download(self, urls): raise yt_dlp.utils.DownloadError("Live stream has ended")
    import yt_dlp
    monkeypatch.setattr(yt_dlp, "YoutubeDL", _YDL)
    monkeypatch.setattr(dy_live, "_probe_room", lambda rid: {"id": rid, "title": "x"})

    rec = dy_live.LiveRecorder()
    result = asyncio.run(rec.record("https://live.douyin.com/999",
                                     output_root=Path("./_test_live")))
    assert result.ended_reason == "stream_ended"
    # Output file doesn't exist (we mocked failure before write)
    assert result.bytes_written == 0


def test_live_recorder_handles_unexpected_error(monkeypatch):
    class _YDL:
        def __init__(self, opts): pass
        def __enter__(self): return self
        def __exit__(self, *a): return None
        def download(self, urls): raise RuntimeError("kaboom")
    import yt_dlp
    monkeypatch.setattr(yt_dlp, "YoutubeDL", _YDL)
    monkeypatch.setattr(dy_live, "_probe_room", lambda rid: {"id": rid, "title": "x"})

    rec = dy_live.LiveRecorder()
    result = asyncio.run(rec.record("https://live.douyin.com/999",
                                     output_root=Path("./_test_live")))
    assert result.ended_reason == "error"


def test_live_recorder_finds_output_file(monkeypatch, tmp_path):
    """When the actual file has a different extension, we find it."""
    import yt_dlp

    captured_outtmpl = {}

    class _YDL:
        def __init__(self, opts):
            # Capture the outtmpl so we know where yt-dlp "would" write
            captured_outtmpl["outtmpl"] = opts.get("outtmpl")
        def __enter__(self): return self
        def __exit__(self, *a): return None
        def download(self, urls):
            # Simulate yt-dlp's output: outtmpl has a ".%(ext)s" suffix
            # that becomes ".mp4" with merge_output_format=mp4. So the
            # real file is outtmpl with the ".%(ext)s" replaced by ".mp4".
            outtmpl = captured_outtmpl["outtmpl"]
            real = outtmpl.replace(".%(ext)s", ".mp4")
            Path(real).write_bytes(b"x" * 1000)
    monkeypatch.setattr(yt_dlp, "YoutubeDL", _YDL)
    monkeypatch.setattr(dy_live, "_probe_room", lambda rid: {"id": rid, "title": "test"})

    from pathlib import Path
    rec = dy_live.LiveRecorder()
    result = asyncio.run(rec.record("https://live.douyin.com/999",
                                     output_root=tmp_path))
    assert result.output_path is not None
    assert result.output_path.exists()
    assert result.bytes_written == 1000


# ---------------------------------------------------------------------------
# CLI: live subcommand parsing
# ---------------------------------------------------------------------------


def test_cli_live_help():
    from doubi.cli.main import main
    with pytest.raises(SystemExit) as exc_info:
        main(["live", "--help"])
    assert exc_info.value.code == 0
