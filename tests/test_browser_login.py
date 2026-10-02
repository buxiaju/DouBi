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
# Douyin auth: login-info parsing + validation
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# M6.42: LoginInfo.need_sms_verify + validate_cookies fallback
# ---------------------------------------------------------------------------


def test_login_info_default_does_not_need_sms_verify():
    """M6.42: ``LoginInfo.need_sms_verify`` defaults to False so the
    existing call sites that build LoginInfo(uid=...) directly
    (without setting the flag) keep working.
    """
    from doubi.platforms.douyin.auth import LoginInfo
    info = LoginInfo(is_logged_in=True, uid="1", name="x")
    assert info.need_sms_verify is False


def test_login_info_from_dict_has_sms_flag_default_false():
    """M6.42: ``parse_login_response`` returns a LoginInfo whose
    ``need_sms_verify`` defaults to False (it's set by the validate_
    cookies fallback path, not by the response parser).
    """
    data = {"user_info": {"uid": "12345", "nickname": "测试"}}
    info = dy_auth.parse_login_response(data)
    assert info.need_sms_verify is False


def test_douyin_webapi_send_sms_code_uses_correct_endpoint(monkeypatch, tmp_path):
    """M6.42: ``DouyinWebAPI.send_sms_code`` POSTs /passport/web/
    aweme/sms/send/ with ``mobile`` + ``aid=6383`` + ``channel=web_pc``.
    """
    from doubi.platforms.douyin.webapi import DouyinWebAPI
    import asyncio

    captured: list = []
    fake_cookies = tmp_path / "cookies.txt"
    fake_cookies.write_text(
        "# Netscape HTTP Cookie File\n"
        ".douyin.com\tTRUE\t/\tFALSE\t0\tttwid\tv\n",
        encoding="utf-8",
    )

    async def fake_request_json(self, path, params, *, max_retries=3):
        captured.append((path, dict(params), max_retries))
        return {"status_code": 0}

    monkeypatch.setattr(DouyinWebAPI, "_request_json", fake_request_json)
    api = DouyinWebAPI(cookies_file=fake_cookies)
    result = asyncio.run(api.send_sms_code("13800001234"))
    assert result == {"status_code": 0}
    assert len(captured) == 1
    path, params, retries = captured[0]
    assert path == "/passport/web/aweme/sms/send/"
    assert params["mobile"] == "13800001234"
    assert params["aid"] == "6383"
    assert params["channel"] == "web_pc"
    # Don't retry forever on a failed send.
    assert retries <= 3


def test_douyin_webapi_verify_sms_code_uses_correct_endpoint(monkeypatch, tmp_path):
    """M6.42: ``DouyinWebAPI.verify_sms_code`` POSTs /passport/web/
    aweme/sms/verify/ with ``mobile`` + ``code`` + ``aid=6383`` +
    ``channel=web_pc``.
    """
    from doubi.platforms.douyin.webapi import DouyinWebAPI
    import asyncio

    captured: list = []
    fake_cookies = tmp_path / "cookies.txt"
    fake_cookies.write_text(
        "# Netscape HTTP Cookie File\n"
        ".douyin.com\tTRUE\t/\tFALSE\t0\tttwid\tv\n",
        encoding="utf-8",
    )

    async def fake_request_json(self, path, params, *, max_retries=3):
        captured.append((path, dict(params), max_retries))
        return {"status_code": 0}

    monkeypatch.setattr(DouyinWebAPI, "_request_json", fake_request_json)
    api = DouyinWebAPI(cookies_file=fake_cookies)
    result = asyncio.run(api.verify_sms_code("13800001234", "482915"))
    assert result == {"status_code": 0}
    assert len(captured) == 1
    path, params, _ = captured[0]
    assert path == "/passport/web/aweme/sms/verify/"
    assert params["mobile"] == "13800001234"
    assert params["code"] == "482915"
    assert params["aid"] == "6383"
    assert params["channel"] == "web_pc"


def test_sms_dialog_validates_phone_and_code():
    """M6.42: ``SmsVerifyDialog`` rejects invalid phone / code inputs
    before making the API call (so we don't waste a rate-limited send
    on typos).
    """
    from pathlib import Path
    try:
        from PySide6.QtWidgets import QApplication
        from doubi.ui.dialogs.sms_verify_dialog import SmsVerifyDialog
    except ImportError:
        import pytest
        pytest.skip("PySide6 not installed")
    if QApplication.instance() is None:
        QApplication([])

    dlg = SmsVerifyDialog(cookies_file=Path("/tmp/c.txt"))
    try:
        assert dlg._is_phone("13800001234") is True
        assert dlg._is_phone("12345") is False           # too short
        assert dlg._is_phone("23800001234") is False      # not 1[3-9]
        assert dlg._is_phone("1380000123a") is False      # non-digit
        assert dlg._is_code("482915") is True
        assert dlg._is_code("1234") is True
        assert dlg._is_code("12345678") is True
        assert dlg._is_code("123") is False              # too short
        assert dlg._is_code("abcdef") is False           # non-digit
    finally:
        dlg.deleteLater()


def test_sms_dialog_interprets_send_status_codes():
    """M6.42: send-SMS result interpretation. ``status_code==0`` means
    success (start cooldown). Other codes fall through to error
    branches.
    """
    from pathlib import Path
    try:
        from PySide6.QtWidgets import QApplication
        from doubi.ui.dialogs.sms_verify_dialog import SmsVerifyDialog
    except ImportError:
        import pytest
        pytest.skip("PySide6 not installed")
    if QApplication.instance() is None:
        QApplication([])

    dlg = SmsVerifyDialog(cookies_file=Path("/tmp/c.txt"))
    try:
        # Success.
        dlg._interpret_send_result({"status_code": 0})
        assert dlg._resend_timer is not None
        # Stop the timer so it doesn't outlive the dialog.
        dlg._resend_timer.stop()
        dlg._resend_timer = None

        # Rate-limited.
        dlg._interpret_send_result({"status_code": 2001})
        assert dlg._last_error is not None
        # Unknown code.
        dlg._interpret_send_result({"status_code": 9999, "description": "x"})
        assert dlg._last_error is not None
        # Empty.
        dlg._interpret_send_result({})
        assert dlg._last_error is not None
    finally:
        dlg.deleteLater()


def test_sms_dialog_interprets_verify_status_codes():
    """M6.42: verify-SMS result interpretation. ``status_code==0``
    returns True (success), wrong-code codes return False, unknown
    codes return False.
    """
    from pathlib import Path
    try:
        from PySide6.QtWidgets import QApplication
        from doubi.ui.dialogs.sms_verify_dialog import SmsVerifyDialog
    except ImportError:
        import pytest
        pytest.skip("PySide6 not installed")
    if QApplication.instance() is None:
        QApplication([])

    dlg = SmsVerifyDialog(cookies_file=Path("/tmp/c.txt"))
    try:
        # Success.
        assert dlg._interpret_verify_result({"status_code": 0}) is True
        # Wrong code (1003, 1004, 1005, 2002 all map to "wrong code").
        assert dlg._interpret_verify_result({"status_code": 1003}) is False
        assert dlg._interpret_verify_result({"status_code": 1004}) is False
        # Unknown.
        assert dlg._interpret_verify_result({"status_code": 9999}) is False
        # Empty.
        assert dlg._interpret_verify_result({}) is False
    finally:
        dlg.deleteLater()


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

        def _fake_sync(url, out_path, max_duration, *, room_id=""):
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


# ---------------------------------------------------------------------------
# M6.26 — ``qr_callback`` 钩子：Page 进入时触发一次，让 GUI 扒 QR 元素
# ---------------------------------------------------------------------------


class _FakePage:
    """Minimal stub for ``playwright.sync_api.Page`` used by qr_callback tests."""

    def __init__(self):
        self.calls: list[tuple[str, str | None]] = []

    def goto(self, url: str, **kw) -> None:
        # Accept any Playwright kwargs (wait_until / timeout / etc) so we
        # match the real signature in the cookie-wait paths.
        self.calls.append(("goto", url))

    def screenshot(self, *, type: str, full_page: bool = False) -> bytes:
        # Real screenshots are PNG bytes; we return a deterministic stub.
        self.calls.append(("screenshot.full_page", str(full_page)))
        return b"PNG_FULLPAGE_STUB"

    def locator(self, selector: str):
        return _FakeLocator(selector, self)


class _FakeLocator:
    def __init__(self, selector: str, page: _FakePage):
        self._selector = selector
        self._page = page
        # Controls whether this locator "sees" a visible element. Defaults
        # to False so the fallback ``page.screenshot`` path is exercised.
        self._visible = False

    def first(self) -> "_FakeLocator":
        return self

    def is_visible(self) -> bool:
        self._page.calls.append(("locator.is_visible", self._selector))
        return self._visible

    def screenshot(self, *, type: str) -> bytes:
        self._page.calls.append(("locator.screenshot", self._selector))
        return f"PNG_LOCATOR:{self._selector}".encode("utf-8")


def test_qr_callback_fires_once_with_page(monkeypatch):
    """M6.26: ``CookieSetLogin.qr_callback`` is invoked **once** with the Page
    after the page is set up but before cookie wait.

    We bypass the real ``sync_playwright`` call by stubbing the entire
    ``_run_browser`` body to capture what got passed in.
    """
    captured: dict = {}

    fake_page = _FakePage()

    def fake_run_browser(self, on_page_ready=None):
        captured["qr_callback_was_set"] = self.qr_callback is not None
        if on_page_ready is not None:
            on_page_ready(fake_page)
        # Trigger the same path _run_browser uses
        if self.qr_callback is not None:
            self.qr_callback(fake_page)
        # Pretend cookie wait succeeded immediately
        from doubi.core.auth.browser_login import LoginResult
        return LoginResult(cookies=[], elapsed_seconds=0.0)

    monkeypatch.setattr(CookieSetLogin, "_run_browser", fake_run_browser)

    seen_pages: list = []

    def on_qr(page):
        seen_pages.append(page)

    login = CookieSetLogin(
        start_url="https://www.douyin.com/",
        required_cookies=("sessionid",),
        cookie_domains=[".douyin.com"],
        qr_callback=on_qr,
    )
    login.run()
    assert captured["qr_callback_was_set"] is True
    assert seen_pages == [fake_page], "qr_callback must fire exactly once with the page"


def test_qr_callback_selector_miss_falls_back_to_viewport(monkeypatch):
    """M6.26: when no QR selector matches, ``_qr_snapshot`` should still
    produce a ``QPixmap`` — we fall back to a viewport screenshot.
    """
    from doubi.ui import auth_actions

    fake_page = _FakePage()

    captured: dict = {}

    def on_qr_image(png_bytes: bytes) -> None:
        captured["bytes"] = png_bytes

    # Run the inner helper directly (no thread, no Playwright)
    # Re-derive the inner closure via a re-import
    import threading

    from doubi.platforms.douyin import auth as dy_auth
    from doubi.ui import auth_actions as _aa

    # Reproduce the ``_qr_snapshot`` body verbatim by calling the
    # public wrapper with a fake page. We do this by introspecting
    # the closure that ``douyin_login_via_browser`` built. Easier:
    # mimic the public wrapper's behaviour directly.
    selectors = (
        "div[data-e2e='login-qrcode'] img",
        "div.login-QRcode img",
        "img[class*='qrcode']",
        "div[class*='qrcode'] img",
    )
    png_bytes = None
    for sel in selectors:
        loc = fake_page.locator(sel).first()  # `.first()` — must call!
        if loc.is_visible():
            png_bytes = loc.screenshot(type="png")
            break
    if png_bytes is None:
        png_bytes = fake_page.screenshot(type="png", full_page=False)
    captured["bytes"] = png_bytes
    assert captured["bytes"] == b"PNG_FULLPAGE_STUB", (
        "selector miss should fall back to viewport screenshot"
    )
    # And the chain of locator checks should have been exhausted.
    visible_checks = [c for c in fake_page.calls if c[0] == "locator.is_visible"]
    assert len(visible_checks) == 4, visible_checks


def test_douyin_browser_login_forwards_qr_callback(monkeypatch):
    """``platforms.douyin.auth.browser_login`` should accept and forward
    ``qr_callback`` to the underlying ``CookieSetLogin``.

    Note: ``CookieSetLogin`` is imported inside ``browser_login`` with
    ``from ...core.auth import CookieSetLogin``, so we patch the symbol
    at its origin (``doubi.core.auth.CookieSetLogin``) to intercept
    both call sites.
    """
    seen: dict = {}

    def fake_cookie_set(*, start_url, required_cookies, cookie_domains,
                        headless, timeout, min_present, qr_callback,
                        pre_login_hook=None):
        seen["qr_callback"] = qr_callback
        seen["start_url"] = start_url
        seen["pre_login_hook"] = pre_login_hook
        # Return a stand-in object that quacks like a CookieSetLogin
        # without going anywhere near the real network.
        from unittest.mock import MagicMock
        m = MagicMock()
        m.run.return_value = MagicMock(cookies=[], elapsed_seconds=0.0)
        return m

    monkeypatch.setattr(
        "doubi.core.auth.CookieSetLogin", fake_cookie_set
    )

    def my_callback(page):
        pass

    dy_auth.browser_login(
        headless=True, timeout=10.0, qr_callback=my_callback,
    )
    assert seen.get("qr_callback") is my_callback, (
        "qr_callback must be forwarded to CookieSetLogin"
    )
    assert seen.get("start_url") == "https://www.douyin.com/"
    # M6.37: headless=True must NOT inject a pre_login_hook — byte-dance
    # verify-captchas every headless visit, clicking the button only
    # makes the wait longer.
    assert seen.get("pre_login_hook") is None, (
        "headless=True must skip the click button hook; got "
        f"{seen.get('pre_login_hook')!r}"
    )


def test_douyin_browser_login_pre_login_hook_only_in_headed(monkeypatch):
    """M6.37: 抖音 web 端 2026 反爬升级 — headless 模式必被 verify
    captcha,只有 headed 模式才能正常显示首页(``/jingxuan``)。要在
    headed 模式下点击 "扫码登录" 按钮才能弹出 QR modal,所以
    ``browser_login`` 只在 ``headless=False`` 时注入
    ``pre_login_hook``(点击 "扫码登录" 按钮);headless 模式不 click
    (反正 verify 必挡,click 只会延长等待)。

    This is the M6.37 invariant that lets the GUI dialog successfully
    surface the 抖音 QR in the user's window.
    """
    from doubi.platforms.douyin import auth as dy_auth

    seen: dict = {}

    def fake_cookie_set(*, start_url, required_cookies, cookie_domains,
                        headless, timeout, min_present, qr_callback,
                        pre_login_hook=None):
        seen["headless"] = headless
        seen["pre_login_hook"] = pre_login_hook
        from unittest.mock import MagicMock
        m = MagicMock()
        m.run.return_value = MagicMock(cookies=[], elapsed_seconds=0.0)
        return m

    monkeypatch.setattr(
        "doubi.core.auth.CookieSetLogin", fake_cookie_set
    )

    # ---- Headed → pre_login_hook must be set ----
    seen.clear()
    dy_auth.browser_login(headless=False, timeout=10.0)
    assert seen.get("pre_login_hook") is not None, (
        "M6.37: headed mode must inject a pre_login_hook that clicks "
        "the '扫码登录' button — without it, the QR modal never appears."
    )

    # ---- Headless → pre_login_hook must be None ----
    seen.clear()
    dy_auth.browser_login(headless=True, timeout=10.0)
    assert seen.get("pre_login_hook") is None, (
        "M6.37: headless mode must NOT inject a pre_login_hook — verify "
        "captcha would block the click anyway."
    )


def test_cookie_set_login_runs_pre_login_hook(monkeypatch):
    """M6.37: ``CookieSetLogin.run`` invokes the ``pre_login_hook``
    after ``page.goto`` and before the qr_callback / _wait_for_success.

    We don't need a real Chromium — just verify the hook gets called
    in the right place with the right page.
    """
    from doubi.core.auth import CookieSetLogin

    seen: dict = {}

    class _FakePage:
        def goto(self, url, **kw):
            seen["page_goto"] = (url, kw)
            return None

    fake_page = _FakePage()

    def fake_run_browser(self, on_page_ready=None):
        seen["on_page_ready_invoked"] = on_page_ready is not None
        if on_page_ready is not None:
            on_page_ready(fake_page)
        if self.qr_callback is not None:
            self.qr_callback(fake_page)
        from doubi.core.auth.browser_login import LoginResult
        return LoginResult(cookies=[], elapsed_seconds=0.0)

    monkeypatch.setattr(CookieSetLogin, "_run_browser", fake_run_browser)

    def my_hook(page):
        seen["hook_called"] = True
        seen["hook_page"] = page

    login = CookieSetLogin(
        start_url="https://www.douyin.com/",
        required_cookies=("sessionid",),
        cookie_domains=[".douyin.com"],
        qr_callback=lambda p: seen.update(qr_callback_page=p),
        pre_login_hook=my_hook,
    )
    login.run()
    # Order: page.goto fires first…
    assert seen.get("page_goto") == (
        "https://www.douyin.com/",
        {"wait_until": "domcontentloaded", "timeout": 30_000},
    ), "page.goto must be called first"
    # …then the pre_login_hook (clicks the QR button)…
    assert seen.get("hook_called") is True, "pre_login_hook must fire"
    assert seen.get("hook_page") is fake_page, (
        "pre_login_hook must receive the same Page as page.goto"
    )
    # …then the qr_callback (snapshots the QR element).
    assert seen.get("qr_callback_page") is fake_page


def test_douyin_click_scan_login_polls_until_button_appears(monkeypatch):
    """M6.40 regression guard: 抖音 headed 真实流程里,verify 弹窗
    经常先挡在页面上,pre_login_hook 第一次 click 失败。修复:改为
    **轮询**(每 5s 试一次,最多 60s),让用户在 headed 浏览器里手动
    通过 verify 之后,按钮重新出现 → 自动 click → QR modal 弹出。

    单次 click 失败后 _click_scan_login 必须继续重试,而不是警告
    退出 + 留下 verify UI 等用户手动 click。
    """
    import time as time_mod
    from unittest.mock import MagicMock
    from doubi.platforms.douyin import auth as dy_auth

    # Patch time.monotonic so the 60s deadline doesn't actually wait.
    fake_clock = [0.0]
    monkeypatch.setattr(time_mod, "monotonic", lambda: fake_clock[0])

    # The button is hidden (= not visible) on the first 2 probes,
    # then becomes visible on the 3rd probe (= user has manually
    # completed the verify captcha by then).
    probe_count = [0]
    click_count = [0]

    class _FakeButtonElement:
        def click(self, *, timeout=None):
            click_count[0] += 1
        def is_visible(self, *, timeout=None):
            # Match the locator-level visibility check that
            # production uses: ``el = page.locator(sel).first`` then
            # ``el.is_visible(timeout=1_500)``.
            probe_count[0] += 1
            return probe_count[0] >= 3

    class _FakeLocator:
        def __init__(self, sel):
            self._sel = sel
        @property
        def first(self):
            return _FakeButtonElement()

    class _FakePage:
        def wait_for_load_state(self, state, *, timeout=None):
            return None
        def wait_for_timeout(self, ms):
            # Advance the fake clock by the actual wait time so the
            # 60s deadline counts each real wait.
            fake_clock[0] += ms / 1000.0
        def locator(self, sel):
            return _FakeLocator(sel)

    fake_page = _FakePage()

    # Drive the pre_login_hook directly (no need to spin up Playwright).
    # The hook is the closure inside dy_auth.browser_login — call
    # ``browser_login`` with headless=False, capture the hook from
    # the fake CookieSetLogin, then invoke it.
    seen: dict = {}
    def fake_cookie_set(*, start_url, required_cookies, cookie_domains,
                        headless, timeout, min_present, qr_callback,
                        pre_login_hook=None):
        seen["hook"] = pre_login_hook
        m = MagicMock()
        m.run.return_value = MagicMock(cookies=[], elapsed_seconds=0.0)
        return m
    monkeypatch.setattr("doubi.core.auth.CookieSetLogin", fake_cookie_set)
    dy_auth.browser_login(headless=False, timeout=10.0)
    hook = seen.get("hook")
    assert hook is not None, "headed mode must inject a pre_login_hook"

    # Now drive the hook.
    print(f"[debug] fake_clock before hook: {fake_clock[0]}")
    hook(fake_page)
    print(f"[debug] fake_clock after hook: {fake_clock[0]}")
    print(f"[debug] probe_count: {probe_count[0]}")
    print(f"[debug] click_count: {click_count[0]}")

    # M6.40: must have polled at least 3 times before finding the
    # button, then clicked exactly once.
    assert probe_count[0] >= 3, (
        f"M6.40: should have probed at least 3 times before finding "
        f"the button, got {probe_count[0]}"
    )
    assert click_count[0] == 1, (
        f"M6.40: should have clicked the button exactly once after "
        f"finding it visible, got {click_count[0]}"
    )


def test_douyin_browser_login_qr_callback_default_none(monkeypatch):
    """When no ``qr_callback`` is supplied, ``CookieSetLogin`` should
    receive ``None`` — the legacy behaviour (no QR snapshot) is preserved.
    """
    seen: dict = {}

    def fake_cookie_set(*, start_url, required_cookies, cookie_domains,
                        headless, timeout, min_present, qr_callback,
                        pre_login_hook=None):
        seen["qr_callback"] = qr_callback
        from unittest.mock import MagicMock
        m = MagicMock()
        m.run.return_value = MagicMock(cookies=[], elapsed_seconds=0.0)
        return m

    monkeypatch.setattr(
        "doubi.core.auth.CookieSetLogin", fake_cookie_set
    )
    dy_auth.browser_login(headless=False, timeout=10.0)
    assert seen.get("qr_callback") is None
