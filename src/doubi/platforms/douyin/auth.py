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

The douyin-downloader's legacy ``config/cookies.json`` is converted
to Netscape on import (see :func:`parse_legacy_json`).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

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
    """Result of a douyin login-state check."""

    is_logged_in: bool
    uid: Optional[str] = None
    name: Optional[str] = None
    sec_uid: Optional[str] = None
    avatar_url: Optional[str] = None
    raw: Optional[dict] = None


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
# Legacy douyin-downloader cookies.json (M2.1 import path)
# ---------------------------------------------------------------------------


def parse_legacy_json(path: Path) -> list[dict[str, Any]]:
    """Read douyin-downloader's ``config/cookies.json`` and return cookies.

    The legacy file is a JSON dict like::

        {
            "ttwid": "...",
            "msToken": "...",
            "odin_tt": "...",
            "passport_csrf_token": "...",
            "sid_guard": "...",
            ...
        }

    The cookie domains are inferred (all ``.douyin.com``). Some keys
    are not real cookies (``webId``, ``odin_tt``); we still pass them
    through because yt-dlp / our engine only consumes the known ones.
    """
    if not path.exists():
        return []
    raw = path.read_text(encoding="utf-8", errors="replace").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        logger.warning("legacy cookies.json is not valid JSON: %s", path)
        return []
    if not isinstance(data, dict):
        return []
    return [
        {"name": str(k), "value": str(v), "domain": ".douyin.com",
         "path": "/", "secure": False, "expires": 0}
        for k, v in data.items() if v
    ]


# ---------------------------------------------------------------------------
# Browser-based auto-login (M2.1)
# ---------------------------------------------------------------------------


# Cookies douyin sets after a successful web login. The four "must have"
# ones are enough to identify a logged-in session; we wait for *all*
# of them by default (min_present = len).
_DOUYIN_REQUIRED_COOKIES = ("ttwid", "msToken", "passport_csrf_token", "odin_tt")


def browser_login(
    *,
    headless: bool = False,
    timeout: float = 180.0,
    start_url: str = "https://www.douyin.com/",
    min_present: Optional[int] = None,
) -> list[dict]:
    """Run a Playwright browser to log in to 抖音 and return the cookies.

    Opens Chromium, navigates to ``https://www.douyin.com/`` (the
    login UI lives behind a button on that page), waits for the
    identifying cookies to appear, then extracts and returns them.

    Returns a list of cookie dicts in the same shape that
    :func:`write_netscape_cookies` expects.

    Raises :class:`BrowserLoginError` if Playwright isn't installed
    or the login times out.
    """
    from ...core.auth import CookieSetLogin

    login = CookieSetLogin(
        start_url=start_url,
        required_cookies=_DOUYIN_REQUIRED_COOKIES,
        cookie_domains=[".douyin.com"],
        headless=headless,
        timeout=timeout,
        min_present=min_present,
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


async def validate_cookies(cookies_file: Optional[Path] = None, *, timeout: float = 10.0) -> LoginInfo:
    """Call douyin's user-info endpoint with the cookies and return the result."""
    import httpx

    p = cookies_file or default_cookie_path()
    cookies: dict[str, str] = {}
    if has_cookie_file(p):
        for c in parse_netscape_file(p):
            cookies[c["name"]] = c["value"]
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
        logger.warning("validate_cookies failed: %s", exc)
        return LoginInfo(is_logged_in=False)


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
