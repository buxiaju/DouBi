"""Bilibili auth: cookie file management + login state query.

M3.1 adds:
    * :func:`validate_cookies`  — call /x/web-interface/nav to check
    * :func:`login_info_from_cookies` — return uid / name / isLogin
    * :func:`parse_netscape_file`  — read cookies.txt into dicts
    * :func:`parse_json_cookies`   — read browser-exported JSON

M3.1 still does NOT automate the QR scan (Playwright is M3.1.1).
The user runs ``doubi auth bilibili``, sees the QR, scans with the
B 站 app, then runs ``doubi auth bilibili --import <cookies.txt>``
to ingest the cookies the browser sees.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("doubi.platforms.bilibili.auth")

DEFAULT_COOKIE_DIR: Path = Path.home() / ".doubi" / "cookies"
DEFAULT_COOKIE_FILE: Path = DEFAULT_COOKIE_DIR / "bilibili.txt"

ENV_COOKIE_FILE = "DOUBI_BILIBILI_COOKIES"

# Endpoints
NAV_URL = "https://api.bilibili.com/x/web-interface/nav"


# ---------------------------------------------------------------------------
# Cookie path helpers (carried over from M3)
# ---------------------------------------------------------------------------


def default_cookie_path() -> Path:
    p = os.environ.get(ENV_COOKIE_FILE)
    if p:
        return Path(p).expanduser()
    return DEFAULT_COOKIE_FILE


def ensure_cookie_dir() -> Path:
    d = DEFAULT_COOKIE_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def has_cookie_file(path: Optional[Path] = None) -> bool:
    p = path or default_cookie_path()
    try:
        return p.exists() and p.stat().st_size > 0
    except OSError:
        return False


def load_cookie_file(path: Optional[Path] = None) -> Optional[str]:
    p = path or default_cookie_path()
    if not has_cookie_file(p):
        return None
    return str(p)


def default_cookie_file() -> Path:
    """Helper for backward-compat with write_netscape_cookies."""
    return default_cookie_path()


def write_netscape_cookies(cookies: list[dict], path: Optional[Path] = None) -> Path:
    """Write a list of cookie dicts to a Netscape-format file."""
    p = path or default_cookie_file()
    ensure_cookie_dir()
    lines = ["# Netscape HTTP Cookie File", "# https://curl.haxx.se/rfc/cookie_spec.html", ""]
    for c in cookies:
        domain = c.get("domain", "")
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
# Cookie file parsers
# ---------------------------------------------------------------------------


def parse_netscape_file(path: Path) -> list[dict[str, Any]]:
    """Read a Netscape-format cookie file into a list of dicts.

    Each dict has ``name``, ``value``, ``domain``, ``path``, ``secure``,
    ``expires`` keys. Comments and blank lines are skipped. Cookies
    with ``HttpOnly`` markers (prefixed with ``#HttpOnly_``) are
    preserved with the same name.
    """
    cookies: list[dict[str, Any]] = []
    if not path.exists():
        return cookies
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") and "HttpOnly" not in line.split(" ", 1)[0]:
            # Pure comment (no HttpOnly marker) — skip
            if line.startswith("#") and not line.startswith("#HttpOnly_"):
                continue
            if not line:
                continue
        # Strip the HttpOnly_ prefix
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_"):]
        elif line.startswith("#"):
            # Pure comment line — skip
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

    Accepts the formats produced by:
        * "Get cookies.txt LOCALLY" (JSON export with name/value/domain)
        * EditThisCookie (JSON array)
        * Most browser cookie-export extensions
    """
    if not path.exists():
        return []
    raw = path.read_text(encoding="utf-8", errors="replace").strip()
    if not raw:
        return []
    # Tolerate a top-level "cookies" key
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
        if not name:        # empty / missing name → skip
            continue
        # value may be None (browser-side "delete cookie" markers); preserve as "None"
        value = c.get("value", "")
        domain = c.get("domain") or c.get("host") or ".bilibili.com"
        if not domain.startswith("."):
            # Cookies for subdomains should have a leading dot to match
            # all subdomains in Netscape format
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


# ---------------------------------------------------------------------------
# Login state
# ---------------------------------------------------------------------------


@dataclass
class LoginInfo:
    """Result of a login-state check."""

    is_logged_in: bool
    uid: Optional[int] = None
    name: Optional[str] = None
    level: Optional[int] = None
    vip_status: Optional[int] = None
    raw: Optional[dict] = None


def parse_login_response(data: dict) -> LoginInfo:
    """Parse the JSON body of /x/web-interface/nav into a LoginInfo."""
    code = data.get("code")
    is_login = bool(data.get("data", {}).get("isLogin")) if code == 0 else False
    d = data.get("data") or {}
    return LoginInfo(
        is_logged_in=is_login,
        uid=d.get("mid"),
        name=d.get("uname"),
        level=d.get("level_info", {}).get("current_level") if isinstance(d.get("level_info"), dict) else None,
        vip_status=d.get("vipStatus"),
        raw=data,
    )


def cookies_to_netscape_dicts(cookies: list[dict]) -> list[dict]:
    """Normalize cookies to the schema :func:`write_netscape_cookies` expects."""
    out: list[dict] = []
    for c in cookies:
        out.append({
            "domain": c.get("domain") or ".bilibili.com",
            "path": c.get("path") or "/",
            "secure": bool(c.get("secure", False)),
            "expires": int(c.get("expires", 0) or 0),
            "name": c["name"],
            "value": str(c["value"]),
        })
    return out


# ---------------------------------------------------------------------------
# Browser-based auto-login (M3.1.1)
# ---------------------------------------------------------------------------


# URL B 站 sends the user to after a successful scan-and-confirm.
# Any path on bilibili.com (other than the login page itself) means
# the session is established.
_BILI_SUCCESS_URL = re.compile(r"^https?://(www\.)?bilibili\.com/(?!login|blackboard|main/app|index|auth)")


def browser_login(
    *,
    headless: bool = False,
    timeout: float = 180.0,
    user_data_dir: Optional[Path] = None,
) -> list[dict]:
    """Run a Playwright browser to log in to B 站 and return the cookies.

    Opens Chromium, navigates to ``https://passport.bilibili.com/login``,
    waits for the user to scan the QR with the B 站 app, then extracts
    the resulting cookies (filtered to the ``.bilibili.com`` domain).

    Returns a list of cookie dicts in the same shape that
    :func:`write_netscape_cookies` expects.

    Raises :class:`BrowserLoginError` if Playwright isn't installed
    or the login times out.
    """
    from ...core.auth import URLChangeLogin

    login = URLChangeLogin(
        start_url="https://passport.bilibili.com/login",
        success_url_pattern=_BILI_SUCCESS_URL.pattern,
        cookie_domains=[".bilibili.com"],
        headless=headless,
        timeout=timeout,
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


async def validate_cookies(cookies_file: Optional[Path] = None, *, timeout: float = 10.0) -> LoginInfo:
    """Call /x/web-interface/nav with the cookies at ``cookies_file`` and return the result.

    Returns a :class:`LoginInfo` with ``is_logged_in=False`` if the file
    is missing, empty, or the network call fails.
    """
    import httpx

    p = cookies_file or default_cookie_path()
    # httpx accepts a dict of name→value cookies; domain / path are inferred
    # from the URL we hit.
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
    """Synchronous wrapper around :func:`validate_cookies`.

    Useful for the CLI's ``auth status`` command.
    """
    import asyncio
    return asyncio.run(validate_cookies(cookies_file))
