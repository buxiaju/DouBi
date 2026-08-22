"""Tests for the M5.3 GUI auth actions.

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


def test_import_douyin_legacy_success(tmp_path):
    from doubi.platforms.douyin import auth as dy_auth
    from doubi.ui.auth_actions import import_douyin_legacy_json

    src = tmp_path / "legacy.json"
    src.write_text("[]")
    target = tmp_path / "out.txt"

    monkey = pytest.MonkeyPatch()
    monkey.setattr(dy_auth, "parse_legacy_json", lambda p: [{"name": "sessionid", "value": "v"}])
    monkey.setattr(dy_auth, "write_netscape_cookies", lambda cookies, path=None: target)
    info = _FakeLoginInfo(is_logged_in=True, uid=11, name="dy", sec_uid="sx")
    monkey.setattr(dy_auth, "login_info_from_cookies_sync", lambda p: info)
    try:
        ok, msg = import_douyin_legacy_json(src, dst=target)
        assert ok is True
        assert "uid=11" in msg
    finally:
        monkey.undo()


def test_import_douyin_legacy_missing_file(tmp_path):
    from doubi.ui.auth_actions import import_douyin_legacy_json
    ok, msg = import_douyin_legacy_json(tmp_path / "nope.json")
    assert ok is False
    assert "不存在" in msg
