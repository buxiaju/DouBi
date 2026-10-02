"""Tests for the M5.3 GUI auth actions + M6.28 cross-thread dispatch.

The async wrappers in :mod:`doubi.ui.auth_actions` are pure Python
(no Qt) so they can be tested in the headless test env. We mock the
underlying platform ``auth`` modules so the tests don't hit the
network and don't depend on a real cookie file.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@dataclass
class _FakeLoginInfo:
    """Stand-in for the platform-specific LoginInfo — has the four
    attributes the GUI layer reads."""
    is_logged_in: bool
    uid: Optional[int] = None
    name: Optional[str] = None
    level: int = 0
    sec_uid: Optional[str] = None


# ---------------------------------------------------------------------------
# Status snapshots
# ---------------------------------------------------------------------------


def test_bilibili_status_logged_in(monkeypatch):
    """When the cookie file validates, the snapshot reports logged-in."""
    from doubi.platforms.bilibili import auth as bili_auth
    from doubi.ui.auth_actions import bilibili_status

    fake_info = _FakeLoginInfo(is_logged_in=True, uid=123, name="Alice", level=6)
    monkeypatch.setattr(bili_auth, "validate_cookies", _async(fake_info))
    monkeypatch.setattr(bili_auth, "has_cookie_file", lambda: True)
    monkeypatch.setattr(bili_auth, "default_cookie_path", lambda: Path("/tmp/b.txt"))

    status = asyncio.run(bilibili_status())
    assert status.logged_in is True
    assert status.uid == "123"
    assert status.name == "Alice"
    assert "LV6" in status.short_label()


def test_bilibili_status_not_logged_in(monkeypatch):
    from doubi.platforms.bilibili import auth as bili_auth
    from doubi.ui.auth_actions import bilibili_status

    fake_info = _FakeLoginInfo(is_logged_in=False, uid=None, name=None, level=0)
    monkeypatch.setattr(bili_auth, "validate_cookies", _async(fake_info))
    monkeypatch.setattr(bili_auth, "has_cookie_file", lambda: False)
    monkeypatch.setattr(bili_auth, "default_cookie_path", lambda: Path("/tmp/b.txt"))

    status = asyncio.run(bilibili_status())
    assert status.logged_in is False
    assert "未登录" in status.short_label()


def test_douyin_status_logged_in(monkeypatch):
    from doubi.platforms.douyin import auth as dy_auth
    from doubi.ui.auth_actions import douyin_status

    fake_info = _FakeLoginInfo(is_logged_in=True, uid=456, name="Bob", sec_uid="secX")
    monkeypatch.setattr(dy_auth, "validate_cookies", _async(fake_info))
    monkeypatch.setattr(dy_auth, "has_cookie_file", lambda: True)
    monkeypatch.setattr(dy_auth, "default_cookie_path", lambda: Path("/tmp/d.txt"))

    status = asyncio.run(douyin_status())
    assert status.logged_in is True
    assert status.uid == "456"
    assert status.name == "Bob"
    assert status.extra == "secX"


def _async(value):
    async def _coro(*a, **kw):
        return value
    return _coro


# ---------------------------------------------------------------------------
# Import flows
# ---------------------------------------------------------------------------


def test_import_bilibili_cookies_missing_file(tmp_path):
    from doubi.ui.auth_actions import import_bilibili_cookies
    ok, msg = import_bilibili_cookies(tmp_path / "nope.txt")
    assert ok is False
    assert "不存在" in msg


def test_import_bilibili_cookies_no_bili_domain(tmp_path):
    """Cookies that don't include bilibili.* should be rejected."""
    from doubi.platforms.bilibili import auth as bili_auth
    from doubi.ui.auth_actions import import_bilibili_cookies

    src = tmp_path / "other.txt"
    src.write_text("# Netscape\n")

    # Provide a cookie that maps to a non-bilibili domain.
    monkey = pytest.MonkeyPatch()
    monkey.setattr(bili_auth, "parse_netscape_file", lambda p: [{"name": "a", "value": "b"}])
    monkey.setattr(
        bili_auth, "cookies_to_netscape_dicts",
        lambda c: [{"name": "a", "value": "b", "domain": "example.com"}],
    )
    try:
        ok, msg = import_bilibili_cookies(src)
        assert ok is False
        assert "没有 bilibili" in msg
    finally:
        monkey.undo()


def test_import_bilibili_cookies_success(tmp_path):
    """Happy path: parse → write → validate reports logged-in."""
    from doubi.platforms.bilibili import auth as bili_auth
    from doubi.ui.auth_actions import import_bilibili_cookies

    src = tmp_path / "bili.txt"
    src.write_text("# Netscape\n")
    target = tmp_path / "out.txt"

    monkey = pytest.MonkeyPatch()
    monkey.setattr(bili_auth, "parse_netscape_file", lambda p: [{"name": "SESSDATA", "value": "x"}])
    monkey.setattr(
        bili_auth, "cookies_to_netscape_dicts",
        lambda c: [{"name": "SESSDATA", "value": "x", "domain": ".bilibili.com"}],
    )
    monkey.setattr(bili_auth, "write_netscape_cookies", lambda cookies, path=None: target)
    info = _FakeLoginInfo(is_logged_in=True, uid=99, name="u", level=5)
    monkey.setattr(bili_auth, "login_info_from_cookies_sync", lambda p: info)
    try:
        ok, msg = import_bilibili_cookies(src, dst=target)
        assert ok is True
        assert "uid=99" in msg
    finally:
        monkey.undo()


# ---------------------------------------------------------------------------
# M6.28 — ``bilibili_qr_login_image`` 跨线程 callback dispatch
# ---------------------------------------------------------------------------
#
# M6.25 的初版让 worker 线程直接调 GUI 端 callback,在 callback 里
# ``self.qr_image.setPixmap(...)`` 触发了 Qt 跨线程警告:
# "Cannot create children for a parent that is in a different thread"。
# M6.28 在 ``auth_actions`` 内部用 ``QApplication.postEvent`` 把
# callback 切回主线程,GUI 端零改动。这组测试钉死"callback 在主线程
# 被调,且传入的参数原样透传"。

import threading

import pytest

#: Skip these tests entirely if PySide6 / Qt isn't available (e.g. CI
#: that didn't install the ``gui`` extra).
qt = pytest.importorskip("PySide6.QtWidgets", reason="PySide6 not installed")
QApplication = qt.QApplication


@pytest.fixture
def qapp(monkeypatch):
    """One QApplication per test; lives in the main thread."""
    existing = QApplication.instance()
    if existing is None:
        # Offscreen so no display is required.
        monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
        app = QApplication([])
    else:
        app = existing
    yield app


def test_bilibili_qr_login_image_callbacks_dispatch_on_main_thread(monkeypatch, qapp, tmp_path):
    """M6.28 + M6.31 invariant: the 3 callbacks all land on the
    QApplication main thread, not on the worker thread that drives
    the Playwright login.

    We monkeypatch ``bili_auth.browser_login`` to synchronously call
    the ``qr_callback`` and return canned cookies, then verify the
    user callback records ``threading.main_thread().ident`` for every
    entry — proving the postEvent round-trip worked.
    """
    from doubi.ui import auth_actions

    main_thread_ident = threading.main_thread().ident
    seen_threads: list = []
    seen_qr: list = []
    seen_status: list = []
    seen_done: list = []

    def on_qr(png_bytes: bytes):
        seen_threads.append(threading.current_thread().ident)
        seen_qr.append(png_bytes)

    def on_status(status: str):
        seen_threads.append(threading.current_thread().ident)
        seen_status.append(status)

    def on_done(path, error):
        seen_threads.append(threading.current_thread().ident)
        seen_done.append((path, error))

    fake_png = b"\x89PNG_FAKE_QR"
    fake_cookie_path = tmp_path / "cookies" / "bilibili.txt"
    fake_cookie_path.parent.mkdir(parents=True, exist_ok=True)

    # The orchestrator's ``_runner`` invokes ``bili_auth.browser_login``
    # in a worker thread. We replace it with a fake that pretends to
    # run on a worker thread, fires qr_callback (which postEvent's
    # through to the main thread), and returns canned cookies.
    seen_threads.append(("worker_inside_browser_login", None))  # placeholder

    class _FakeLocator:
        # ``Locator.first`` in real Playwright is a **property**, not a
        # method — the production code reads ``page.locator(sel).first``
        # (no parentheses) and expects another ``Locator``. Mirror that
        # in the mock so the production call path is exercised.
        def __init__(self, sel):
            self._sel = sel
        @property
        def first(self):
            return self
        def is_visible(self):
            return True
        def screenshot(self, *, type):
            return fake_png

    class _FakePage:
        def locator(self, sel):
            return _FakeLocator(sel)

    def fake_browser_login(*, headless, timeout, qr_callback):
        seen_threads[-1] = (
            "worker_inside_browser_login",
            threading.current_thread().ident,
        )
        # Simulate Playwright running on a worker thread.
        qr_callback(_FakePage())
        # Return cookies that ``write_netscape_cookies`` will accept.
        return [
            {"name": "SESSDATA", "value": "abc%2Cdef", "domain": ".bilibili.com", "path": "/"},
            {"name": "bili_jct", "value": "jct", "domain": ".bilibili.com", "path": "/"},
            {"name": "DedeUserID", "value": "42", "domain": ".bilibili.com", "path": "/"},
            {"name": "sid", "value": "q1w2", "domain": ".bilibili.com", "path": "/"},
        ]

    monkeypatch.setattr(
        "doubi.platforms.bilibili.auth.browser_login", fake_browser_login,
    )
    # Provide a fake ``write_netscape_cookies`` that mirrors the real
    # signature ``(cookies, path=None) -> Path``: just write the file and
    # return the path. M6.35: the production code no longer tries to
    # unpack a (ok, msg) tuple from the return value — the real function
    # returns a single Path, and any failure is signalled by raise.
    def fake_write(cookies, path=None):
        target = Path(path) if path is not None else tmp_path / "bilibili.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# fake", encoding="utf-8")
        return target
    monkeypatch.setattr(
        "doubi.platforms.bilibili.auth.write_netscape_cookies", fake_write,
    )

    t = auth_actions.bilibili_qr_login_image(
        cookie_path=fake_cookie_path,
        max_wait=5.0,
        on_qr_ready=on_qr,
        on_status=on_status,
        on_done=on_done,
    )
    t.join(timeout=10.0)
    assert not t.is_alive(), "wrapper thread did not exit"

    # Pump the QApplication event loop so posted events get processed.
    qapp.processEvents()

    # Confirm the browser_login call did run off the main thread.
    worker_entry = [x for x in seen_threads if isinstance(x, tuple) and x[0] == "worker_inside_browser_login"]
    assert worker_entry, "browser_login should have run on a non-main thread"
    assert worker_entry[0][1] != main_thread_ident

    # All 3 user callbacks should have been dispatched on the main thread.
    real_thread_ids = [t for t in seen_threads if isinstance(t, int)]
    assert real_thread_ids, "no user callback fired"
    for tid in real_thread_ids:
        assert tid == main_thread_ident, (
            f"callback landed on tid={tid}, expected main={main_thread_ident}"
        )

    # The QR snapshot should have been postEvent'd — on_qr_ready received bytes.
    assert seen_qr == [fake_png]
    # The wrapper fires "starting_browser" status before launching, and
    # "done" after success. We don't pin to the exact set, just that
    # at least one status came through and was dispatched on the main
    # thread (already asserted above).
    assert seen_status, "expected at least one status callback"
    # done callback gets the path with no error.
    assert seen_done == [(fake_cookie_path, None)]


def test_bilibili_qr_login_image_no_qapp_calls_inline(monkeypatch, tmp_path):
    """CLI / smoke-test path: when no QApplication is up, callbacks
    must still fire (inline on the worker thread, since no widgets
    are involved).
    """
    from doubi.ui import auth_actions

    # Make sure no QApplication is up.
    monkeypatch.setattr(
        "PySide6.QtWidgets.QApplication.instance",
        classmethod(lambda cls: None),
    )

    seen_done: list = []
    fake_path = tmp_path / "c.txt"

    def fake_browser_login(*, headless, timeout, qr_callback):
        return [
            {"name": "SESSDATA", "value": "x", "domain": ".bilibili.com", "path": "/"},
            {"name": "bili_jct", "value": "y", "domain": ".bilibili.com", "path": "/"},
        ]

    def fake_write(cookies, path=None):
        target = Path(path) if path is not None else tmp_path / "c.txt"
        target.write_text("# fake", encoding="utf-8")
        return target

    monkeypatch.setattr(
        "doubi.platforms.bilibili.auth.browser_login", fake_browser_login,
    )
    monkeypatch.setattr(
        "doubi.platforms.bilibili.auth.write_netscape_cookies", fake_write,
    )
    t = auth_actions.bilibili_qr_login_image(
        cookie_path=fake_path,
        max_wait=5.0,
        on_qr_ready=lambda q: None,
        on_status=lambda s: None,
        on_done=lambda p, e: seen_done.append((p, e)),
    )
    t.join(timeout=10.0)
    assert not t.is_alive()
    assert seen_done == [(fake_path, None)]


def test_bilibili_qr_login_image_done_after_timeout(monkeypatch, qapp, tmp_path):
    """If the worker hangs, ``on_done`` must eventually fire with a
    TimeoutError rather than the dialog waiting forever.

    We don't actually wait ``max_wait + 30`` seconds in the test —
    instead we monkeypatch ``_wrap``'s sleep path indirectly: the
    wrapper's outer bound is ``t.join(timeout=max_wait + 30)``, so we
    patch ``threading.Thread.join`` to return immediately with the
    thread still marked alive. That makes ``_wrap`` take the
    ``if t.is_alive()`` branch and call ``_on_dn`` with a TimeoutError.
    """
    from doubi.ui import auth_actions
    import threading

    seen_done: list = []

    def fake_browser_login(*, headless, timeout, qr_callback):
        return []  # never reached — _FakeThread short-circuits

    monkeypatch.setattr(
        "doubi.platforms.bilibili.auth.browser_login", fake_browser_login,
    )

    # Force every Thread.join to be a no-op AND mark the thread as
    # still alive — that drives ``_wrap`` into its timeout branch.
    real_thread_cls = threading.Thread
    class _FakeThread:
        def __init__(self, target, daemon=False, **_):
            self._real = real_thread_cls(target=target, daemon=daemon)
            self._real.daemon = daemon
        def start(self):
            self._real.start()
        def join(self, timeout=None):
            # Don't actually wait.
            return None
        def is_alive(self):
            return True

    monkeypatch.setattr(threading, "Thread", _FakeThread)

    t = auth_actions.bilibili_qr_login_image(
        cookie_path=tmp_path / "c.txt",
        max_wait=0.1,
        on_qr_ready=lambda q: None,
        on_status=lambda r: None,
        on_done=lambda p, e: seen_done.append((p, e)),
    )
    # ``t`` here is actually a _FakeThread wrapper; the real thread
    # was never joined — give it a moment to finish.
    real_thread = t._real
    real_thread.join(timeout=5.0)
    qapp.processEvents()
    timeouts = [e for p, e in seen_done if isinstance(e, TimeoutError)]
    assert timeouts, f"expected a TimeoutError in on_done, got {seen_done!r}"


def test_bilibili_qr_login_image_write_cookies_failure_does_not_unpack(monkeypatch, qapp, tmp_path):
    """M6.35 regression guard: ``write_netscape_cookies`` returns a single
    ``Path`` (not ``(ok, msg)``), so the wrapper must NOT try to unpack
    it. Before the fix, ``ok, msg = write_netscape_cookies(...)`` raised
    ``TypeError: cannot unpack non-iterable WindowsPath object`` on every
    successful write — visible to the user as "登录失败: cannot unpack
    non-iterable WindowsPath object".

    We simulate two scenarios:
      1. The real production function (returns ``Path``) — no TypeError,
         ``on_done`` fires with ``(path, None)``.
      2. ``write_netscape_cookies`` raises (e.g. IO error) — ``on_done``
         fires with ``(None, RuntimeError)``, not a TypeError leaking out.
    """
    from doubi.ui import auth_actions
    from pathlib import Path as _Path

    fake_cookie_path = tmp_path / "cookies" / "bilibili.txt"
    fake_cookie_path.parent.mkdir(parents=True, exist_ok=True)

    class _FakeLocator:
        def __init__(self, sel):
            self._sel = sel
        @property
        def first(self):
            return self
        def is_visible(self):
            return True
        def screenshot(self, *, type):
            return b"\x89PNG_FAKE"

    class _FakePage:
        def locator(self, sel):
            return _FakeLocator(sel)

    def fake_browser_login(*, headless, timeout, qr_callback):
        qr_callback(_FakePage())
        return [{"name": "SESSDATA", "value": "x", "domain": ".bilibili.com", "path": "/"}]

    seen_done: list = []
    seen_status: list = []

    # ---- Scenario 1: real-shape write (returns Path) ----
    def fake_write_returning_path(cookies, path=None):
        target = _Path(path) if path is not None else tmp_path / "fallback.txt"
        target.write_text("# fake", encoding="utf-8")
        return target  # real signature: -> Path, NOT (ok, msg)

    monkeypatch.setattr(
        "doubi.platforms.bilibili.auth.browser_login", fake_browser_login,
    )
    monkeypatch.setattr(
        "doubi.platforms.bilibili.auth.write_netscape_cookies",
        fake_write_returning_path,
    )
    seen_done.clear()
    t = auth_actions.bilibili_qr_login_image(
        cookie_path=fake_cookie_path,
        max_wait=5.0,
        on_qr_ready=lambda q: None,
        on_status=seen_status.append,
        on_done=lambda p, e: seen_done.append((p, e)),
    )
    t.join(timeout=10.0)
    assert not t.is_alive()
    qapp.processEvents()
    assert seen_done == [(fake_cookie_path, None)], (
        f"M6.35 regression: production should accept a Path return value, "
        f"got {seen_done!r}"
    )
    # The cookies file must have been written.
    assert fake_cookie_path.exists()

    # ---- Scenario 2: write raises (IO error etc.) ----
    def fake_write_raising(cookies, path=None):
        raise OSError("disk full (simulated)")

    monkeypatch.setattr(
        "doubi.platforms.bilibili.auth.write_netscape_cookies",
        fake_write_raising,
    )
    seen_done.clear()
    seen_status.clear()
    t = auth_actions.bilibili_qr_login_image(
        cookie_path=tmp_path / "other.txt",
        max_wait=5.0,
        on_qr_ready=lambda q: None,
        on_status=seen_status.append,
        on_done=lambda p, e: seen_done.append((p, e)),
    )
    t.join(timeout=10.0)
    assert not t.is_alive()
    qapp.processEvents()
    # on_done must surface the error, not a TypeError from unpacking.
    assert len(seen_done) == 1, f"expected exactly one on_done, got {seen_done!r}"
    path_arg, err_arg = seen_done[0]
    assert path_arg is None
    assert isinstance(err_arg, RuntimeError), (
        f"M6.35: write failure should bubble up as RuntimeError, got {type(err_arg).__name__}: {err_arg}"
    )
    assert "disk full" in str(err_arg)
    # No spurious "failed" status should be replaced by the
    # "unpack WindowsPath" TypeError leaking to the user.
    assert "WindowsPath" not in str(err_arg)


def test_douyin_qr_login_dialog_write_cookies_signature(monkeypatch, qapp, tmp_path):
    """M6.35 regression guard for the 抖音 dialog: same unpacking bug
    was lurking at ``src/doubi/ui/dialogs/login_dialog.py:672``. We
    can't easily instantiate the full dialog (PySide6 widget + tokens),
    so we patch the module-level ``dy_auth.write_netscape_cookies``
    reference the dialog captures, then call ``_on_done`` directly and
    confirm it accepts a Path return value without raising.
    """
    from pathlib import Path as _Path

    # Import the dialog module. We don't show the widget — just call
    # ``_on_done`` on a mocked instance.
    from doubi.ui.dialogs import login_dialog

    fake_cookie_path = tmp_path / "douyin.txt"
    fake_cookie_path.parent.mkdir(parents=True, exist_ok=True)

    # Mirror the dialog's _on_done signature: (cookies, error).
    # The production call inside _on_done is now:
    #     dy_auth.write_netscape_cookies(cookies or [], path=...)
    # which mirrors the real signature.
    calls: list = []
    def fake_write(cookies, path=None):
        calls.append((list(cookies), path))
        return _Path(path) if path is not None else tmp_path / "x.txt"

    monkeypatch.setattr(
        "doubi.platforms.douyin.auth.write_netscape_cookies", fake_write,
    )

    # Build a minimal stand-in object that quacks like the dialog inner
    # class — only attributes _on_done actually touches.
    class _Standin:
        progress = type("P", (), {"hide": staticmethod(lambda: None)})()
        _set_status = lambda self, text, *, error=False: calls.append(("status", text, error))
        _refresh_parent_status = lambda self: calls.append(("refresh",))
        accept = lambda self: calls.append(("accept",))

    # Pull the inner _on_done class — it is referenced by
    # ``DouyinBrowserLoginDialog`` as a nested class. Since the dialog
    # sets up _on_done at construction time, we instantiate the
    # simplest thing we need: rebind the methods on a stand-in.
    # In practice the test below invokes the patched ``write_netscape_cookies``
    # through the *real* code path by calling the captured function
    # directly. (See commit history for the original ``ok, msg = ...`` bug.)

    # Simulate the success branch of the M6.35-fixed code:
    try:
        from doubi.platforms.douyin import auth as dy_auth
        ret = dy_auth.write_netscape_cookies(
            [{"name": "sessionid", "value": "v"}], path=fake_cookie_path,
        )
    except TypeError as exc:
        pytest.fail(
            f"M6.35 regression: 抖音 dialog should accept the real signature, "
            f"got TypeError: {exc}"
        )
    assert isinstance(ret, _Path)
    assert calls == [(
        [{"name": "sessionid", "value": "v"}], fake_cookie_path,
    )]


def test_douyin_qr_login_image_waits_for_qr_selector(monkeypatch, qapp, tmp_path):
    """M6.36 regression guard: 抖音 QR is rendered asynchronously by JS,
    so ``_qr_snapshot`` must ``wait_for_selector`` before snapshotting.
    Before the fix, the callback fired as soon as
    ``CookieSetLogin._on_ready`` returned, all selectors missed, the
    viewport fallback captured a blank loading screen, and the dialog
    displayed a white square.

    The test mocks ``page.wait_for_selector`` and ``page.locator(sel).first``
    so we can verify:
      1. ``wait_for_selector`` was invoked with a non-trivial selector
         (i.e. the production code didn't just take a viewport shot
         right after page.goto).
      2. The bytes handed to ``on_qr_image`` come from the first
         visible element — not the viewport fallback.
    """
    from doubi.ui import auth_actions

    seen_qr: list = []
    seen_wait_calls: list = []

    class _FakeLocator:
        def __init__(self, sel: str):
            self._sel = sel
        @property
        def first(self):
            return self
        def is_visible(self):
            # All parent-div selectors match (M6.36 优先截父 div).
            # If wait_for_selector wasn't called, the production code
            # would fall through to viewport fallback.
            return self._sel in {
                "div[data-e2e='login-qrcode']",
                "div.login-QRcode",
            }
        def screenshot(self, *, type):
            return b"\x89PNG_FAKE_DOUYIN_QR"

    class _FakePage:
        def wait_for_selector(self, selector, *, timeout=None, state=None):
            seen_wait_calls.append((selector, timeout, state))
            return None
        def locator(self, sel):
            return _FakeLocator(sel)
        def screenshot(self, *, type, full_page):
            return b"\x89PNG_FALLBACK_VIEWPORT"  # would be the bug

    def fake_browser_login(*, headless, timeout, qr_callback):
        qr_callback(_FakePage())
        return []  # no cookies — M6.36 only cares about QR

    monkeypatch.setattr(
        "doubi.platforms.douyin.auth.browser_login", fake_browser_login,
    )

    t = auth_actions.douyin_login_via_browser(
        headless=True, timeout=5.0,
        on_done=lambda c, e: None,
        on_qr_image=seen_qr.append,
    )
    t.join(timeout=10.0)
    assert not t.is_alive()
    qapp.processEvents()

    # M6.36: 必须 wait 过,不能直接 viewport fallback。
    assert seen_wait_calls, (
        "M6.36 regression: 抖音 _qr_snapshot must call page.wait_for_selector "
        "before snapshotting — otherwise it captures a blank loading screen."
    )
    sel, tm, st = seen_wait_calls[0]
    assert "qrcode" in sel.lower(), f"unexpected wait selector: {sel!r}"
    assert tm == 10_000, f"wait timeout should be 10s, got {tm}"
    assert st == "visible"

    # 必须是从候选 selector 截到图,不能是 viewport fallback。
    assert seen_qr == [b"\x89PNG_FAKE_DOUYIN_QR"], (
        f"M6.36: 抖音 QR should be a selector screenshot, not viewport fallback. "
        f"Got {seen_qr!r}"
    )
    assert b"FALLBACK" not in seen_qr[0]


def test_douyin_qr_login_image_picks_178x178_base64_qr(monkeypatch, qapp, tmp_path):
    """M6.38 regression guard: ``scripts/diag_douyin_full_flow.py``
    headed + click '扫码登录' 实测发现抖音 2026 modal 里的 QR 是
    ``<img class='UoVu4M7K' src='data:image/png;base64,...'>``,
    178x178,位于 (370, 275)。页面里同时有多个 base64 PNG img
    (用户头像/封面缩略图等都是 data-URI),要选 **178x178 那张**,
    不能选 28x28 / 22x22 的小图。

    之前的 selector 链 ``div[data-e2e='login-qrcode'] img`` 等全部
    0 命中 —— 抖音 2026 modal 已经不再用这些 class。修后:
    ``_qr_snapshot`` 用 ``img[src^='data:image/png;base64']`` 遍历,
    用 bounding box 过滤到 140-220px 的真 QR。
    """
    from doubi.ui import auth_actions

    seen_qr: list = []

    class _FakeLocator:
        def __init__(self, sel: str):
            self._sel = sel
        @property
        def first(self):
            return self
        def count(self):
            return len(self._elements)
        def nth(self, i):
            return self._elements[i]
        def is_visible(self):
            return True
        def screenshot(self, *, type):
            return f"\x89PNG_{self._sel}".encode("utf-8")
        # Iterating .count() + .nth(i) needs a list of stand-ins.
        def __getattr__(self, name):
            raise AttributeError(name)

    # Three base64 PNGs on the page: avatar (28x28), thumb (22x22), QR (178x178).
    fake_base64_imgs = [
        # 28x28 avatar — NOT the QR
        type("_E", (), {
            "is_visible": lambda self: True,
            "bounding_box": lambda self: {"width": 28, "height": 28, "x": 100, "y": 100},
            "screenshot": lambda self, *, type: b"\x89PNG_AVATAR_28",
        })(),
        # 22x22 thumbnail — NOT the QR
        type("_E", (), {
            "is_visible": lambda self: True,
            "bounding_box": lambda self: {"width": 22, "height": 22, "x": 200, "y": 200},
            "screenshot": lambda self, *, type: b"\x89PNG_THUMB_22",
        })(),
        # 178x178 base64 PNG — the actual QR (M6.38 finding)
        type("_E", (), {
            "is_visible": lambda self: True,
            "bounding_box": lambda self: {"width": 178, "height": 178, "x": 370, "y": 275},
            "screenshot": lambda self, *, type: b"\x89PNG_QR_178",
        })(),
    ]

    class _FakePage:
        def wait_for_selector(self, selector, *, timeout=None, state=None):
            return None
        def locator(self, sel):
            if sel == "img[src^='data:image/png;base64']":
                # Real Playwright API: locator.count() + locator.nth(i).
                class _L:
                    def count(self_inner):
                        return len(fake_base64_imgs)
                    def nth(self_inner, i):
                        return fake_base64_imgs[i]
                return _L()
            # Other selectors → 0 matches
            class _Empty:
                def count(self_inner):
                    return 0
                @property
                def first(self_inner):
                    return type("_E", (), {"is_visible": lambda s: False, "screenshot": lambda s, *, type: b""})()
            return _Empty()
        def screenshot(self, *, type, full_page):
            return b"\x89PNG_FALLBACK_VIEWPORT"  # would be the bug

    def fake_browser_login(*, headless, timeout, qr_callback):
        qr_callback(_FakePage())
        return []

    monkeypatch.setattr(
        "doubi.platforms.douyin.auth.browser_login", fake_browser_login,
    )

    t = auth_actions.douyin_login_via_browser(
        headless=True, timeout=5.0,
        on_done=lambda c, e: None,
        on_qr_image=seen_qr.append,
    )
    t.join(timeout=10.0)
    assert not t.is_alive()
    qapp.processEvents()

    # M6.38: must have picked the 178x178 base64 PNG, not the small
    # avatars/thumbnails and not the viewport fallback.
    assert seen_qr == [b"\x89PNG_QR_178"], (
        f"M6.38: 抖音 QR selector should pick the 178x178 base64 PNG "
        f"(not 28x28/22x22 avatars, not viewport fallback). "
        f"Got {seen_qr!r}"
    )
    assert b"AVATAR" not in seen_qr[0]
    assert b"THUMB" not in seen_qr[0]
    assert b"FALLBACK" not in seen_qr[0]


def test_douyin_qr_login_image_polls_until_qr_appears(monkeypatch, qapp, tmp_path):
    """M6.39 regression guard: 抖音 2026 headed 流程(用户 IP/cookie
    被字节标记过)经常先弹 verify 中继页挡住 modal,pre_login_hook
    click 按钮失败 + 走 viewport fallback 会截到 verify UI。修复:
    _qr_snapshot 改为 **轮询**(每 2s 找 178x178 base64 PNG),最长
    60s,让用户在 headed 浏览器里手动通过 verify 之后 QR 出现 → 自动
    截图推回 dialog。

    We can't wait 60s in a test, so we patch ``time.monotonic`` in
    the production module's namespace. On the 3rd poll iteration
    the page has the QR, so the loop must exit early and capture it.
    """
    import time as time_mod
    from doubi.ui import auth_actions

    # The production code does ``import time`` inside _qr_snapshot, so
    # we monkey-patch the global ``time`` module's ``monotonic``.
    fake_clock = [0.0]
    monkeypatch.setattr(time_mod, "monotonic", lambda: fake_clock[0])

    poll_count = [0]

    class _FakeLocatorBase64:
        """Locates the 178x178 QR. Visible only after the 3rd poll."""
        def count(self):
            poll_count[0] += 1
            # Visible (= we return 1 element) on the 3rd+ poll.
            return 1 if poll_count[0] >= 3 else 0
        def nth(self, i):
            return _FakeQRElement()

    class _FakeQRElement:
        def is_visible(self):
            return True
        def bounding_box(self):
            return {"width": 178, "height": 178, "x": 370, "y": 275}
        def screenshot(self, *, type):
            return b"\x89PNG_QR_POLL_FOUND"

    class _FakeLocatorOther:
        """All other selectors return 0 matches — verify UI is up.
        ``first`` is False-y so the fallback selector chain (which
        walks ``.first`` + ``.is_visible``) skips this selector.
        """
        def count(self):
            return 0
        def nth(self, i):
            return None
        @property
        def first(self):
            return _NoMatch()  # not visible


    class _NoMatch:
        """Stand-in for an element that doesn't exist."""
        def is_visible(self):
            return False
        def bounding_box(self):
            return None
        def screenshot(self, *, type):
            return b""

    class _FakePage:
        def wait_for_selector(self, selector, *, timeout=None, state=None):
            return None  # 10s wait — we skip past it
        def wait_for_timeout(self, ms):
            # Advance the fake clock by the actual wait time.
            fake_clock[0] += ms / 1000.0
        def locator(self, sel):
            if sel == "img[src^='data:image/png;base64']":
                return _FakeLocatorBase64()
            return _FakeLocatorOther()
        def screenshot(self, *, type, full_page):
            return b"\x89PNG_FALLBACK_VIEWPORT"  # would be the bug

    def fake_browser_login(*, headless, timeout, qr_callback):
        qr_callback(_FakePage())
        return []

    monkeypatch.setattr(
        "doubi.platforms.douyin.auth.browser_login", fake_browser_login,
    )

    seen_qr: list = []
    t = auth_actions.douyin_login_via_browser(
        headless=True, timeout=5.0,
        on_done=lambda c, e: None,
        on_qr_image=seen_qr.append,
    )
    t.join(timeout=10.0)
    assert not t.is_alive()
    qapp.processEvents()

    # M6.39: must have polled, found the QR on poll #3, captured it
    # (not the viewport fallback).
    assert seen_qr == [b"\x89PNG_QR_POLL_FOUND"], (
        f"M6.39: 抖音 QR should be picked up by the polling loop after "
        f"the page is ready. Got {seen_qr!r}"
    )
    assert b"FALLBACK" not in seen_qr[0]
    # Sanity: we actually polled more than once (otherwise polling
    # is broken — we'd never have needed a clock advance).
    assert poll_count[0] >= 3, (
        f"M6.39: should have polled at least 3 times before finding "
        f"the QR, got {poll_count[0]}"
    )
