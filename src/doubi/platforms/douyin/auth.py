"""Douyin auth: cookie file management.

Douyin doesn't require cookies for public videos, but for private
content (收藏夹, 喜欢列表) and to bypass rate limits, the user must
log in. We follow the convention that cookie files live in
``~/.doubi/cookies/douyin.txt`` in Netscape format — yt-dlp reads
them directly via the ``cookiefile`` option.

M2.1 adds:

* :func:`validate_cookies`      — call /web/api/v2/user/info/ to check
* :func:`browser_login`         — Playwright-driven auto-login
* :func:`login_info_from_cookies`— return mid / name / isLogin
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger("doubi.platforms.douyin.auth")

# Project-wide cookie directory under the user's home.
DEFAULT_COOKIE_DIR: Path = Path.home() / ".doubi" / "cookies"
DEFAULT_COOKIE_FILE: Path = DEFAULT_COOKIE_DIR / "douyin.txt"

# Environment variable overrides (handy in CI / containers).
ENV_COOKIE_FILE = "DOUBI_DOUYIN_COOKIES"
ENV_COOKIE_DIR = "DOUBI_COOKIE_DIR"


def default_cookie_path() -> Path:
    """Return the cookie file path, honoring env overrides."""
    p = os.environ.get(ENV_COOKIE_FILE)
    if p:
        return Path(p).expanduser()
    return DEFAULT_COOKIE_FILE


def ensure_cookie_dir() -> Path:
    """Create the cookie directory if missing. Returns the dir path."""
    override = os.environ.get(ENV_COOKIE_DIR)
    d = Path(override).expanduser() if override else DEFAULT_COOKIE_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def has_cookie_file(path: Optional[Path] = None) -> bool:
    """True if a non-empty cookie file exists at ``path`` (or default)."""
    p = path or default_cookie_path()
    try:
        return p.exists() and p.stat().st_size > 0
    except OSError:
        return False


def load_cookie_file(path: Optional[Path] = None) -> Optional[str]:
    """Return the cookie file path as a string, or ``None`` if missing.

    Engine code passes this directly to yt-dlp's ``cookiefile`` option.
    """
    p = path or default_cookie_path()
    if not has_cookie_file(p):
        return None
    return str(p)


def write_netscape_cookies(cookies: list[dict], path: Optional[Path] = None) -> Path:
    """Write a list of cookie dicts to a Netscape-format file.

    Each cookie dict should have at least ``name``, ``value``, and
    ``domain``. ``path``, ``secure``, ``expires`` are optional. This
    helper is used by the M2.1 login flow; in M2 it's exposed for
    tests and for users migrating from douyin-downloader's JSON
    cookie file.
    """
    p = path or default_cookie_path()
    ensure_cookie_dir()
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Netscape HTTP Cookie File", "# https://curl.haxx.se/rfc/cookie_spec.html", ""]
    for c in cookies:
        domain = c.get("domain", "")
        # Netscape "include subdomains" flag: TRUE for ".example.com"
        flag = "TRUE" if domain.startswith(".") else "FALSE"
        path_v = c.get("path", "/")
        secure = "TRUE" if c.get("secure") else "FALSE"
        expires = str(int(c.get("expires", 0)))
        name = c.get("name", "")
        value = c.get("value", "")
        lines.append("\t".join([domain, flag, path_v, secure, expires, name, value]))
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Wrote %d cookies to %s", len(cookies), p)
    return p


# ---------------------------------------------------------------------------
# Login state
# ---------------------------------------------------------------------------


@dataclass
class LoginInfo:
    """Result of a douyin login-state check.

    M6.42: added ``need_sms_verify`` flag — True when the user has
    successfully scanned the QR (we have ``sessionid`` family cookies)
    but the platform still requires SMS-code second-factor
    authentication. Detected by ``validate_cookies`` when the user-info
    endpoint returns 404 (typical signature of "logged in but device
    needs verification") while a login-state cookie is present in
    the file.
    """

    is_logged_in: bool
    uid: Optional[str] = None
    name: Optional[str] = None
    sec_uid: Optional[str] = None
    avatar_url: Optional[str] = None
    raw: Optional[dict] = None
    need_sms_verify: bool = False


def parse_login_response(data: dict) -> LoginInfo:
    """Parse the JSON body of douyin's user-info endpoint."""
    user = (data or {}).get("user_info") or {}
    return LoginInfo(
        is_logged_in=bool(user.get("uid")),
        uid=str(user["uid"]) if user.get("uid") else None,
        name=user.get("nickname"),
        sec_uid=user.get("sec_uid"),
        avatar_url=(user.get("avatar_thumb") or {}).get("url_list", [None])[0]
                 if isinstance(user.get("avatar_thumb"), dict) else None,
        raw=data,
    )


def cookies_to_netscape_dicts(cookies: list[dict]) -> list[dict]:
    """Normalize cookies to the schema :func:`write_netscape_cookies` expects."""
    out: list[dict] = []
    for c in cookies:
        out.append({
            "domain": c.get("domain") or ".douyin.com",
            "path": c.get("path") or "/",
            "secure": bool(c.get("secure", False)),
            "expires": int(c.get("expires", 0) or 0),
            "name": c["name"],
            "value": str(c["value"]),
        })
    return out


# ---------------------------------------------------------------------------
# Browser-based auto-login (M2.1)
# ---------------------------------------------------------------------------


# Cookies that only appear after a *successful* douyin login. The
# previous set (ttwid / msToken / passport_csrf_token / odin_tt) was
# wrong on both ends: ttwid / odin_tt / passport_csrf_token are set
# for anonymous visitors too, while msToken is generated by JS and
# is often *withheld* under automation (risk control). Net effect:
# after a real QR scan the wait loop never saw 4/4 and timed out,
# closing the browser with the login cookies unharvested; conversely
# the four visitor cookies alone could trigger a false "success".
#
# sessionid / sessionid_ss / sid_guard are only set on a logged-in
# session; with min_present=1 any one of them is a decisive signal.
_DOUYIN_LOGIN_COOKIES = ("sessionid", "sessionid_ss", "sid_guard")


def browser_login(
    *,
    headless: bool = False,
    timeout: float = 180.0,
    start_url: str = "https://www.douyin.com/",
    min_present: Optional[int] = None,
    qr_callback: Optional[Callable[["object"], None]] = None,
) -> list[dict]:
    """Run a Playwright browser to log in to 抖音 and return the cookies.

    Opens Chromium, navigates to ``https://www.douyin.com/`` (the
    login UI lives behind a button on that page), waits for the
    *login-state* cookies (``sessionid`` & friends) to appear, then
    extracts and returns them.

    M6.37: 抖音 web 端 2026 起反爬升级,headless 模式必被弹到
    字节系滑块验证码中继页(rmc.bytedance.com/verifycenter/...),
    没有 QR 可截。**headless 模式已被实测证明不可用**,用户必须
    勾 GUI dialog 底下的「显示浏览器(反爬降级)」复选框走 headed
    模式。headed 模式下抖音正常显示首页(``/jingxuan``),需要
    点 "扫码登录" 按钮才会弹出 QR modal —— 这一步由本函数注入
    ``pre_login_hook`` 完成(headless 模式下不 click,反正都过
    不了 verify)。

    If ``qr_callback`` is provided it is invoked **once** with the
    Playwright ``Page`` after the page is loaded (and after the
    pre_login_hook) but before the cookie wait. The M6.26 GUI uses
    this to take a screenshot of the QR element and surface it in
    the dialog (see :func:`doubi.ui.auth_actions.douyin_login_via_browser`).

    Returns a list of cookie dicts in the same shape that
    :func:`write_netscape_cookies` expects.

    Raises :class:`BrowserLoginError` if Playwright isn't installed
    or the login times out.
    """
    from ...core.auth import CookieSetLogin

    # M6.37: headed 模式下,点击 "扫码登录" 按钮弹出 QR modal。
    # headless 模式下字节系 verify 必弹,click 也没用,所以跳过。
    # M6.40: 改为 **轮询重试 click**(每 5s 试一次,最多 60s),覆盖
    # "verify 弹窗挡住 → 用户手动通过 verify → 按钮重新出现 → 自动
    # click → QR modal 弹出" 的真实 headed 流程。单次 click 失败
    # 后真 QR 永远不会自己出来,viewport fallback 截到 verify UI。
    pre_login_hook: Optional[Callable[["object"], None]] = None
    if not headless:
        def _click_scan_login(page) -> None:
            """Click the "扫码登录" entry to surface the QR modal.

            Byte-dance renames the class hashes across releases, so we
            try a small set of text-based selectors (oldest-stable
            first). All selectors run inside try/except so a missed
            click doesn't crash the flow.

            M6.40: poll-and-retry — even if the first pass fails (e.g.
            verify-captcha iframe is overlaying the page), the headed
            user might unblock it within seconds. We retry every 5s
            for up to 60s, so the user can manually complete the
            captcha and the click then fires automatically.
            """
            import time
            scan_login_selectors = (
                "xpath=//*[normalize-space(text())='扫码登录']",
                "xpath=//*[contains(text(),'扫码登录')]",
                "xpath=//span[contains(text(),'扫码')]",
                "xpath=//div[contains(text(),'扫码')]",
                "xpath=//a[contains(text(),'登录')]",
            )
            # M6.40: ensure the page is at least at "load" state once
            # so React/Semi can hydrate, but don't block here too long
            # — the verify iframe can keep the page from reaching a
            # full "load" event when overlayed.
            try:
                page.wait_for_load_state("load", timeout=10_000)
            except Exception:  # noqa: BLE001
                pass
            deadline = time.monotonic() + 60.0
            attempts = 0
            while time.monotonic() < deadline:
                attempts += 1
                for sel in scan_login_selectors:
                    try:
                        el = page.locator(sel).first
                        if el.is_visible(timeout=1_500):
                            el.click(timeout=5_000)
                            # Give the modal time to animate in. The
                            # QR is rendered async after the click.
                            page.wait_for_timeout(1_500)
                            logger.info(
                                "M6.40: '扫码登录' button clicked on "
                                "attempt %d — QR modal should appear",
                                attempts,
                            )
                            return
                    except Exception:  # noqa: BLE001
                        continue
                # No selector hit this pass. Sleep 5s and retry — the
                # user may be solving a verify captcha in the headed
                # window right now.
                try:
                    page.wait_for_timeout(5_000)
                except Exception:  # noqa: BLE001
                    break
            logger.warning(
                "M6.40: could not find '扫码登录' button on douyin home "
                "after 60s of polling — headed user must click it "
                "manually. Verify-captcha may be blocking the page."
            )
        pre_login_hook = _click_scan_login

    login = CookieSetLogin(
        start_url=start_url,
        required_cookies=_DOUYIN_LOGIN_COOKIES,
        cookie_domains=[".douyin.com"],
        headless=headless,
        timeout=timeout,
        min_present=min_present if min_present is not None else 1,
        qr_callback=qr_callback,
        pre_login_hook=pre_login_hook,
    )
    result = login.run()
    return [
        {
            "domain": c["domain"],
            "path": c.get("path", "/"),
            "secure": bool(c.get("secure", False)),
            "expires": int(c.get("expires", 0) or 0),
            "name": c["name"],
            "value": str(c["value"]),
        }
        for c in result.cookies
    ]


# ---------------------------------------------------------------------------
# Validation (requires network)
# ---------------------------------------------------------------------------


NAV_URL = "https://www.douyin.com/aweme/v1/web/user/info/self/"

# Login-state cookies: only written by douyin for authenticated sessions.
# Used as the offline fallback when the self-info API is unreachable or
# blocked by risk control (it frequently answers 404 to plain requests
# that lack the ``a_bogus`` signature).
_LOGIN_STATE_COOKIES = ("sessionid", "sessionid_ss", "sid_guard")


def _login_state_from_cookie_file(p: Path) -> LoginInfo:
    """Judge login state from cookie presence alone (offline fallback).

    The network check via :func:`validate_cookies` is the preferred path,
    but douyin's self-info endpoint sits behind risk control and often
    returns 404 to unsigned API clients.  Session cookies are the only
    reliable offline signal: they simply don't exist for guest sessions.

    M6.42: distinguishes "not logged in" from "scanned QR but the
    platform requires SMS second-factor".  In the latter case, the
    cookies are present (so ``is_logged_in`` is True under the
    offline heuristic) **but** :func:`validate_cookies` will flag
    ``need_sms_verify=True`` because the API path failed with 404
    despite the session cookies being there.
    """
    if not has_cookie_file(p):
        return LoginInfo(is_logged_in=False)
    names = {c["name"] for c in parse_netscape_file(p)}
    matched = [n for n in _LOGIN_STATE_COOKIES if n in names]
    return LoginInfo(
        is_logged_in=bool(matched),
        raw={"fallback": "cookie_presence", "matched": matched},
    )


async def validate_cookies(cookies_file: Optional[Path] = None, *, timeout: float = 10.0) -> LoginInfo:
    """Call douyin's user-info endpoint with the cookies and return the result.

    If the endpoint is unreachable or rejected by risk control, fall back
    to :func:`_login_state_from_cookie_file` so a valid session cookie
    file still reports logged-in (uid/name stay unknown in that case).

    M6.42: when the fallback path is hit and the cookie file does
    contain login-state cookies (``sessionid`` family), we now set
    ``need_sms_verify=True`` to signal "the user has scanned the QR
    successfully, but the platform still wants SMS-code second
    factor" — see ``LoginInfo.need_sms_verify``.  Without this flag
    we cannot distinguish the two failure modes and the GUI would
    silently show "已登录" while the session is half-broken.
    """
    import httpx

    p = cookies_file or default_cookie_path()
    cookies: dict[str, str] = {}
    has_login_state = False
    has_file = has_cookie_file(p)
    if has_file:
        for c in parse_netscape_file(p):
            cookies[c["name"]] = c["value"]
            if c["name"] in _LOGIN_STATE_COOKIES:
                has_login_state = True
    # 没有 Cookie 文件时**不要联网**：_login_state_from_cookie_file 的结果
    # 就是「未登录」，请求 NAV_URL 只会白等一轮超时再走到同一个分支。
    # 与 bilibili 侧同款短路，避免设置页在无 Cookie 环境下意外触网。
    if not has_file:
        logger.debug("validate_cookies: no cookie file at %s, skipping network", p)
        return _login_state_from_cookie_file(p)
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            cookies=cookies,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36"
                ),
            },
        ) as client:
            resp = await client.get(NAV_URL)
            resp.raise_for_status()
            return parse_login_response(resp.json())
    except Exception as exc:
        logger.warning(
            "validate_cookies API check failed (%s); falling back to cookie presence", exc,
        )
        info = _login_state_from_cookie_file(p)
        # M6.42: surface the "scanned but needs SMS" case so the GUI
        # can offer the SMS dialog.  We only set this when the user
        # clearly has login-state cookies — a totally empty cookie
        # file means the scan never completed at all.
        if has_login_state and not info.is_logged_in:
            info.need_sms_verify = True
        return info


def login_info_from_cookies_sync(cookies_file: Optional[Path] = None) -> LoginInfo:
    """Synchronous wrapper around :func:`validate_cookies`."""
    import asyncio
    return asyncio.run(validate_cookies(cookies_file))


# ---------------------------------------------------------------------------
# Cookie file parsing
# ---------------------------------------------------------------------------


def parse_netscape_file(path: Path) -> list[dict[str, Any]]:
    """Read a Netscape-format cookie file into a list of dicts.

    Same shape as :func:`doubi.platforms.bilibili.auth.parse_netscape_file`
    — duplicated here to keep the two platform adapters independent.
    """
    cookies: list[dict[str, Any]] = []
    if not path.exists():
        return cookies
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_"):]
        elif line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        domain, include_sub, path_v, secure, expires, name, value = parts[:7]
        cookies.append({
            "domain": domain,
            "include_subdomains": include_sub.upper() == "TRUE",
            "path": path_v,
            "secure": secure.upper() == "TRUE",
            "expires": int(expires) if expires.isdigit() else 0,
            "name": name,
            "value": value,
        })
    return cookies


def parse_json_cookies(path: Path) -> list[dict[str, Any]]:
    """Read a JSON list of cookies (browser-extension format).

    Mirrors :func:`doubi.platforms.bilibili.auth.parse_json_cookies`.
    """
    if not path.exists():
        return []
    raw = path.read_text(encoding="utf-8", errors="replace").strip()
    if not raw:
        return []
    data = json.loads(raw)
    if isinstance(data, dict) and "cookies" in data:
        data = data["cookies"]
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for c in data:
        if not isinstance(c, dict):
            continue
        name = c.get("name")
        if not name:
            continue
        value = c.get("value", "")
        domain = c.get("domain") or c.get("host") or ".douyin.com"
        if not domain.startswith("."):
            if domain.count(".") >= 1:
                domain = "." + domain
        out.append({
            "name": name,
            "value": str(value),
            "domain": domain,
            "path": c.get("path", "/"),
            "secure": bool(c.get("secure", False)),
            "expires": int(c.get("expires", 0) or 0),
        })
    return out
