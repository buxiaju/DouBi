"""Async wrappers around the platform auth modules for the GUI.

The CLI's :mod:`doubi.cli.auth_cmd` orchestrates the same flows but is
optimised for terminal output (printing ASCII QR codes, falling back
to manual cookie import, etc.). For the GUI we want a friendlier
shape: pure async functions that return status dicts or launch
background work, and never block the event loop.

Each function here is independent of Qt so it can be unit-tested
without a ``QApplication``.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("doubi.ui.auth_actions")


# ---------------------------------------------------------------------------
# Status snapshots
# ---------------------------------------------------------------------------


@dataclass
class LoginStatus:
    platform: str
    cookie_file: str
    cookie_present: bool
    logged_in: bool
    uid: Optional[str] = None
    name: Optional[str] = None
    extra: Optional[str] = None   # level (bili) / sec_uid (douyin)

    def short_label(self) -> str:
        if self.logged_in:
            who = self.name or self.uid or "已登录"
            tail = f"（{self.extra}）" if self.extra else ""
            return f"已登录 · {who}{tail}"
        if self.cookie_present:
            return "未登录 · Cookie 已过期"
        return "未登录"


async def bilibili_status() -> LoginStatus:
    from ..platforms.bilibili import auth as bili_auth
    info = await bili_auth.validate_cookies()
    return LoginStatus(
        platform="bilibili",
        cookie_file=str(bili_auth.default_cookie_path()),
        cookie_present=bili_auth.has_cookie_file(),
        logged_in=info.is_logged_in,
        uid=str(info.uid) if info.uid else None,
        name=info.name,
        extra=f"LV{info.level}" if info.level else None,
    )


async def douyin_status() -> LoginStatus:
    from ..platforms.douyin import auth as dy_auth
    info = await dy_auth.validate_cookies()
    return LoginStatus(
        platform="douyin",
        cookie_file=str(dy_auth.default_cookie_path()),
        cookie_present=dy_auth.has_cookie_file(),
        logged_in=info.is_logged_in,
        uid=str(info.uid) if info.uid else None,
        name=info.name,
        extra=info.sec_uid,
    )


# ---------------------------------------------------------------------------
# Cookie import (synchronous — pure file ops)
# ---------------------------------------------------------------------------


def import_bilibili_cookies(src: Path, dst: Optional[Path] = None) -> tuple[bool, str]:
    """Import a Netscape or JSON cookies file for B 站.

    Returns ``(ok, message)``. ``ok=True`` means the file was saved
    *and* the platform reported logged-in afterwards.
    """
    from ..platforms.bilibili import auth as bili_auth
    if not src.exists():
        return False, f"文件不存在：{src}"
    suffix = src.suffix.lower()
    if suffix == ".json":
        cookies = bili_auth.parse_json_cookies(src)
    else:
        cookies = bili_auth.parse_netscape_file(src)
    if not cookies:
        return False, f"未能从 {src.name} 解析到任何 Cookie"

    netscape = bili_auth.cookies_to_netscape_dicts(cookies)
    relevant = [c for c in netscape if "bilibili" in c["domain"]]
    if not relevant:
        return False, f"{src.name} 里没有 bilibili.* 域名 Cookie"

    target = dst or bili_auth.default_cookie_path()
    bili_auth.write_netscape_cookies(relevant, path=target)
    info = bili_auth.login_info_from_cookies_sync(target)
    if info.is_logged_in:
        return True, f"已保存 {len(relevant)} 条 Cookie，登录为 uid={info.uid} {info.name!r}"
    return False, f"Cookie 已保存但 B 站仍报未登录（{target}）"


def import_douyin_cookies(src: Path, dst: Optional[Path] = None) -> tuple[bool, str]:
    from ..platforms.douyin import auth as dy_auth
    if not src.exists():
        return False, f"文件不存在：{src}"
    suffix = src.suffix.lower()
    if suffix == ".json":
        cookies = dy_auth.parse_json_cookies(src)
    else:
        cookies = dy_auth.parse_netscape_file(src)
    if not cookies:
        return False, f"未能从 {src.name} 解析到任何 Cookie"

    target = dst or dy_auth.default_cookie_path()
    dy_auth.write_netscape_cookies(cookies, path=target)
    info = dy_auth.login_info_from_cookies_sync(target)
    if info.is_logged_in:
        return True, f"已保存 {len(cookies)} 条 Cookie，登录为 uid={info.uid} {info.name!r}"
    return False, f"Cookie 已保存但抖音仍报未登录（{target}）"


def import_douyin_legacy_json(src: Path, dst: Optional[Path] = None) -> tuple[bool, str]:
    """Import a ``douyin-downloader``-style ``cookies.json``."""
    from ..platforms.douyin import auth as dy_auth
    if not src.exists():
        return False, f"文件不存在：{src}"
    cookies = dy_auth.parse_legacy_json(src)
    if not cookies:
        return False, f"未能从 {src.name} 解析为 douyin-downloader 格式"
    target = dst or dy_auth.default_cookie_path()
    dy_auth.write_netscape_cookies(cookies, path=target)
    info = dy_auth.login_info_from_cookies_sync(target)
    if info.is_logged_in:
        return True, f"已导入 legacy JSON，登录为 uid={info.uid} {info.name!r}"
    return False, "Cookie 已保存但抖音仍报未登录"


# ---------------------------------------------------------------------------
# B 站 QR login
# ---------------------------------------------------------------------------


async def bilibili_generate_qr() -> tuple[object, object]:
    """Create a :class:`QRSession` and generate a fresh QR code.

    Returns ``(session, qr_code)``; the caller is expected to keep the
    session alive (it's an async context manager) and to call
    :func:`bilibili_wait_for_scan` to wait for the user to scan.
    """
    from ..platforms.bilibili.qr_login import QRSession
    s = QRSession()
    await s.__aenter__()
    qr = await s.generate()
    return s, qr


async def bilibili_wait_for_scan(
    session, qrcode_key: str, *, poll_interval: float = 2.0,
    max_wait: float = 180.0,
) -> object:
    from ..platforms.bilibili.qr_login import wait_for_login
    return await wait_for_login(
        session, qrcode_key,
        poll_interval=poll_interval, max_wait=max_wait,
    )


def bilibili_extract_cookies_via_browser(
    *, headless: bool, timeout: float,
    on_done: Callable[[Optional[list[dict]], Optional[Exception]], None],
) -> threading.Thread:
    """Run Playwright in a background thread; call ``on_done`` on finish.

    ``on_done(cookies, error)`` — exactly one of the two is non-None.
    """
    from ..platforms.bilibili import auth as bili_auth
    box: dict = {}

    def _runner():
        try:
            box["cookies"] = bili_auth.browser_login(
                headless=headless, timeout=timeout,
            )
        except Exception as exc:   # noqa: BLE001
            box["error"] = exc

    def _wrap():
        t = threading.Thread(target=_runner, daemon=True)
        t.start()
        t.join(timeout=timeout + 30)
        if t.is_alive():
            on_done(None, TimeoutError("Playwright 登录超时"))
        elif "error" in box:
            on_done(None, box["error"])
        else:
            cookies = box.get("cookies") or []
            on_done(cookies, None if cookies else RuntimeError("未取到 Cookie"))

    t = threading.Thread(target=_wrap, daemon=True)
    t.start()
    return t


def douyin_login_via_browser(
    *, headless: bool, timeout: float,
    on_done: Callable[[Optional[list[dict]], Optional[Exception]], None],
) -> threading.Thread:
    from ..platforms.douyin import auth as dy_auth

    box: dict = {}

    def _runner():
        try:
            box["cookies"] = dy_auth.browser_login(
                headless=headless, timeout=timeout,
            )
        except Exception as exc:   # noqa: BLE001
            box["error"] = exc

    def _wrap():
        t = threading.Thread(target=_runner, daemon=True)
        t.start()
        t.join(timeout=timeout + 30)
        if t.is_alive():
            on_done(None, TimeoutError("Playwright 登录超时"))
        elif "error" in box:
            on_done(None, box["error"])
        else:
            cookies = box.get("cookies") or []
            on_done(cookies, None if cookies else RuntimeError("未取到 Cookie"))

    t = threading.Thread(target=_wrap, daemon=True)
    t.start()
    return t


# ---------------------------------------------------------------------------
# Cookie file writing helper (used after a successful browser login)
# ---------------------------------------------------------------------------


def bilibili_save_cookies(cookies: list[dict], dst: Optional[Path] = None) -> tuple[bool, str]:
    from ..platforms.bilibili import auth as bili_auth
    target = dst or bili_auth.default_cookie_path()
    bili_auth.write_netscape_cookies(cookies, path=target)
    info = bili_auth.login_info_from_cookies_sync(target)
    if info.is_logged_in:
        return True, f"已登录为 uid={info.uid} {info.name!r}"
    return False, "Cookie 已保存但 B 站仍报未登录"


def douyin_save_cookies(cookies: list[dict], dst: Optional[Path] = None) -> tuple[bool, str]:
    from ..platforms.douyin import auth as dy_auth
    target = dst or dy_auth.default_cookie_path()
    dy_auth.write_netscape_cookies(cookies, path=target)
    info = dy_auth.login_info_from_cookies_sync(target)
    if info.is_logged_in:
        return True, f"已登录为 uid={info.uid} {info.name!r}"
    return False, "Cookie 已保存但抖音仍报未登录"
