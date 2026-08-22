"""``doubi auth`` subcommands.

Subcommands:
    ``doubi auth bilibili``          — show QR + try Playwright auto-extract
                                       (falls back to manual import on --no-browser)
    ``doubi auth bilibili --import`` — import cookies from a Netscape / JSON file
    ``doubi auth douyin``            — Playwright auto-login (or import a
                                       legacy douyin-downloader cookies.json)
    ``doubi auth status``            — show login state for all platforms

M3.1.1: the QR flow now ends with a real Chromium instance that
extracts the cookies automatically. Playwright is an *optional*
dependency — if it's not installed, the CLI falls back to the M3.1
manual-import path with a clear install hint.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import threading
from pathlib import Path
from typing import Optional

from ..core.logger import setup_logger
from ..platforms.bilibili import auth as bili_auth
from ..platforms.bilibili.qr_login import (
    QRStatus,
    QRSession,
    wait_for_login,
)
from ..platforms.douyin import auth as dy_auth


# ---------------------------------------------------------------------------
# doubi auth status
# ---------------------------------------------------------------------------


async def _bili_status() -> dict:
    info = await bili_auth.validate_cookies()
    return {
        "platform": "bilibili",
        "logged_in": info.is_logged_in,
        "uid": info.uid,
        "name": info.name,
        "level": info.level,
        "cookie_file": str(bili_auth.default_cookie_path()),
        "cookie_present": bili_auth.has_cookie_file(),
    }


async def _douyin_status() -> dict:
    info = await dy_auth.validate_cookies()
    return {
        "platform": "douyin",
        "logged_in": info.is_logged_in,
        "uid": info.uid,
        "name": info.name,
        "sec_uid": info.sec_uid,
        "cookie_file": str(dy_auth.default_cookie_path()),
        "cookie_present": dy_auth.has_cookie_file(),
    }


def cmd_auth_status(args: argparse.Namespace) -> int:
    setup_logger("INFO")
    print("Login status:")

    bili = asyncio.run(_bili_status())
    print("  bilibili:")
    print(f"    cookie file : {bili['cookie_file']}")
    print(f"    file exists : {bili['cookie_present']}")
    if bili["logged_in"]:
        print(f"    logged in   : yes (uid={bili['uid']}, name={bili['name']}, level={bili['level']})")
    elif bili["cookie_present"]:
        print("    logged in   : NO (cookies may be expired)")
    else:
        print("    logged in   : no (no cookies)")

    dy = asyncio.run(_douyin_status())
    print("  douyin:")
    print(f"    cookie file : {dy['cookie_file']}")
    print(f"    file exists : {dy['cookie_present']}")
    if dy["logged_in"]:
        print(f"    logged in   : yes (uid={dy['uid']}, name={dy['name']})")
    elif dy["cookie_present"]:
        print("    logged in   : NO (cookies may be expired)")
    else:
        print("    logged in   : no (no cookies)")

    return 0


# ---------------------------------------------------------------------------
# doubi auth bilibili
# ---------------------------------------------------------------------------


def _print_qr(qr_url: str, ascii_qr: str) -> None:
    print()
    print("Scan this QR code with the B 站 app to log in:")
    print()
    print(ascii_qr)
    print()
    print("If you can't scan the terminal, visit this URL in any browser,")
    print("then complete the scan on your phone:")
    print(f"  {qr_url}")
    print()


def _try_browser_login(do_login, *, headless: bool, timeout: float, label: str) -> Optional[list[dict]]:
    """Run a Playwright login in a thread; return cookies or ``None``.

    Returns ``None`` for any failure (Playwright missing, network
    error, timeout, etc.) — the caller falls back to manual import.
    """
    result_box: dict = {}

    def _runner():
        try:
            result_box["cookies"] = do_login(headless=headless, timeout=timeout)
        except Exception as exc:
            result_box["error"] = exc

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join(timeout=timeout + 10)
    if t.is_alive():
        print(f"[!] {label} browser login still running after timeout; aborting.",
              file=sys.stderr)
        return None
    if "error" in result_box:
        print(f"[!] {label} browser login failed: {result_box['error']}", file=sys.stderr)
        return None
    cookies = result_box.get("cookies") or []
    if not cookies:
        print(f"[!] {label} browser login returned no cookies.", file=sys.stderr)
        return None
    return cookies


def _save_and_validate(cookies: list[dict], target: Path, label: str) -> bool:
    """Write cookies to a Netscape file, then validate via the network."""
    if label == "bilibili":
        bili_auth.write_netscape_cookies(cookies, path=target)
        print(f"Saved {len(cookies)} cookies -> {target}")
        info = bili_auth.login_info_from_cookies_sync(target)
        if info.is_logged_in:
            print(f"Logged in as uid={info.uid} name={info.name!r} level={info.level}")
            return True
    else:
        dy_auth.write_netscape_cookies(cookies, path=target)
        print(f"Saved {len(cookies)} cookies -> {target}")
        info = dy_auth.login_info_from_cookies_sync(target)
        if info.is_logged_in:
            print(f"Logged in as uid={info.uid} name={info.name!r}")
            return True
    print("Cookies saved but the platform reports not logged in.", file=sys.stderr)
    return False


async def _do_bilibili_qr(cookie_out: Optional[Path], poll_interval: float, max_wait: float,
                          use_browser: bool, headless: bool) -> int:
    print("Generating QR code...", flush=True)
    async with QRSession() as s:
        qr = await s.generate()
        _print_qr(qr.url, qr.render_ascii())

        if use_browser:
            print()
            print("Also opening a Chromium window so the auto-extract can run...",
                  flush=True)
            print("If you prefer to handle this manually, press Ctrl-C now and run",
                  file=sys.stderr)
            print("  doubi auth bilibili --no-browser", file=sys.stderr)

        print("Waiting for you to scan with the B 站 app (Ctrl-C to cancel)...",
              flush=True)
        try:
            result = await wait_for_login(s, qr.qrcode_key,
                                            poll_interval=poll_interval,
                                            max_wait=max_wait)
        except TimeoutError as e:
            print(f"\n[!] {e}", file=sys.stderr)
            return 1
        except KeyboardInterrupt:
            print("\nCancelled.", file=sys.stderr)
            return 130

    if result.status is not QRStatus.SUCCESS:
        print(f"\n[!] Login did not complete: status={result.status.value} "
              f"({result.message})", file=sys.stderr)
        return 1

    print()
    print("QR scan confirmed by B 站!")

    if use_browser:
        target = cookie_out or bili_auth.default_cookie_path()
        cookies = _try_browser_login(
            bili_auth.browser_login,
            headless=headless,
            timeout=max_wait,
            label="bilibili",
        )
        if cookies is not None and _save_and_validate(cookies, target, "bilibili"):
            return 0
        print("Falling back to manual import.")

    print()
    print("Next step: import the cookies from your browser.")
    print("  1. Open https://www.bilibili.com in Chrome/Edge/Firefox (logged in).")
    print("  2. Use a 'Get cookies.txt LOCALLY' extension to export the")
    print("     bilibili.com cookies as a Netscape file.")
    print("  3. Run:  doubi auth bilibili --import <path-to-cookies.txt>")
    print()
    print(f"  Cookie file target: {cookie_out or bili_auth.default_cookie_path()}")
    return 0


def cmd_auth_bilibili(args: argparse.Namespace) -> int:
    setup_logger("INFO")

    if args.import_file:
        return cmd_auth_bilibili_import(args.import_file, args.output)

    return asyncio.run(_do_bilibili_qr(
        cookie_out=args.output,
        poll_interval=args.poll_interval,
        max_wait=args.timeout,
        use_browser=not args.no_browser,
        headless=args.headless,
    ))


def cmd_auth_bilibili_import(src: Path, dst: Optional[Path]) -> int:
    setup_logger("INFO")
    if not src.exists():
        print(f"Error: file not found: {src}", file=sys.stderr)
        return 1

    suffix = src.suffix.lower()
    cookies = bili_auth.parse_json_cookies(src) if suffix == ".json" else bili_auth.parse_netscape_file(src)

    if not cookies:
        print(f"Error: no cookies parsed from {src}.", file=sys.stderr)
        return 1

    bili_cookies = bili_auth.cookies_to_netscape_dicts(cookies)
    relevant = [c for c in bili_cookies if "bilibili" in c["domain"]]
    if not relevant:
        print(f"Warning: no bilibili.* cookies found in {src}; saving anyway.",
              file=sys.stderr)

    target = dst or bili_auth.default_cookie_path()
    return 0 if _save_and_validate(relevant or bili_cookies, target, "bilibili") else 1


# ---------------------------------------------------------------------------
# doubi auth douyin
# ---------------------------------------------------------------------------


def cmd_auth_douyin(args: argparse.Namespace) -> int:
    setup_logger("INFO")

    if args.import_file:
        return _cmd_douyin_import(args.import_file, args.output)

    if args.legacy_json:
        return _cmd_douyin_legacy(args.legacy_json, args.output)

    target = args.output or dy_auth.default_cookie_path()
    print("Opening a Chromium window to log in to 抖音...", flush=True)
    print("In the browser, click the '登录' button, then scan the QR with the",
          file=sys.stderr)
    print("抖音 app (or use phone verification). The CLI will pick up the",
          file=sys.stderr)
    print("cookies as soon as the login completes.", file=sys.stderr)
    print()
    cookies = _try_browser_login(
        dy_auth.browser_login,
        headless=args.headless,
        timeout=args.timeout,
        label="douyin",
    )
    if cookies is not None and _save_and_validate(cookies, target, "douyin"):
        return 0

    print()
    print("Browser-based login didn't work. Try:")
    print("  - Install Playwright:  pip install playwright && python -m playwright install chromium")
    print("  - Or import a cookie file:  doubi auth douyin --import <cookies.txt>")
    print("  - Or import a legacy douyin-downloader JSON:")
    print("      doubi auth douyin --legacy-json config/cookies.json")
    return 1


def _cmd_douyin_import(src: Path, dst: Optional[Path]) -> int:
    if not src.exists():
        print(f"Error: file not found: {src}", file=sys.stderr)
        return 1
    suffix = src.suffix.lower()
    cookies = dy_auth.parse_json_cookies(src) if suffix == ".json" else dy_auth.parse_netscape_file(src)
    if not cookies:
        print(f"Error: no cookies parsed from {src}.", file=sys.stderr)
        return 1
    target = dst or dy_auth.default_cookie_path()
    return 0 if _save_and_validate(cookies, target, "douyin") else 1


def _cmd_douyin_legacy(src: Path, dst: Optional[Path]) -> int:
    if not src.exists():
        print(f"Error: file not found: {src}", file=sys.stderr)
        return 1
    cookies = dy_auth.parse_legacy_json(src)
    if not cookies:
        print(f"Error: no cookies parsed from {src} (is it a valid cookies.json?).",
              file=sys.stderr)
        return 1
    target = dst or dy_auth.default_cookie_path()
    return 0 if _save_and_validate(cookies, target, "douyin") else 1
