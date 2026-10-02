"""Browser-based auto-login flow (M3.1.1).

The QR-code flow without a browser leaves the user with a manual
"export cookies.txt from your browser" step. This module closes
that loop by opening the QR URL in a real Chromium instance and
extracting the cookies the platform sets after the user scans
the QR with their phone.

Two flavors are provided:

* :class:`URLChangeLogin` — used by B 站: navigate to the QR URL,
  wait for the page to redirect to a "login success" URL pattern.
* :class:`CookieSetLogin` — used by 抖音: navigate to a landing
  page, wait for the specific cookies the platform sets after
  successful login (no URL change to look for).

Both flavors use the synchronous Playwright API. We deliberately
keep this synchronous (vs. async) because Playwright's
``sync_playwright`` context manager is the documented stable
entry point and the entire flow is one long blocking operation
that's trivially wrapped in ``asyncio.to_thread`` from async
callers.

Headless / headed:

* The default is **headed** (you can see the browser). The user
  needs to *see* the QR on the page so they can scan it. (Yes,
  the CLI also prints the QR to the terminal, but the browser
  view is the authoritative one — some platforms render
  differently in mobile emulation.)
* ``headless=True`` is supported but useless unless you have
  another way to display the QR. Some users may pipe the
  page's QR to a phone via screen-sharing, etc.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

logger = logging.getLogger("doubi.core.auth.browser_login")


# ---------------------------------------------------------------------------
# Playwright availability
# ---------------------------------------------------------------------------


try:
    from playwright.sync_api import (  # type: ignore
        TimeoutError as PlaywrightTimeoutError,
        sync_playwright,
    )
    HAS_PLAYWRIGHT = True
except ImportError:  # pragma: no cover
    HAS_PLAYWRIGHT = False
    PlaywrightTimeoutError = Exception  # type: ignore


class BrowserLoginError(RuntimeError):
    """Raised when the browser-based login can't complete."""


def require_playwright() -> None:
    """Raise a clear ``BrowserLoginError`` if Playwright is not installed."""
    if not HAS_PLAYWRIGHT:
        raise BrowserLoginError(install_playwright_instructions())


def install_playwright_instructions() -> str:
    return (
        "Playwright is not installed.\n"
        "Install it with:\n"
        "  pip install playwright\n"
        "  python -m playwright install chromium\n"
        "(or: pip install 'doubi[gui]' to get everything at once)"
    )


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass
class LoginResult:
    """Outcome of a browser-based login."""

    cookies: list[dict] = field(default_factory=list)
    final_url: str = ""
    elapsed_seconds: float = 0.0

    def has_cookies(self) -> bool:
        return any(c.get("value") for c in self.cookies)


# ---------------------------------------------------------------------------
# Common base
# ---------------------------------------------------------------------------


class _BaseBrowserLogin:
    """Shared browser lifecycle for both flavors."""

    def __init__(
        self,
        *,
        headless: bool = False,
        timeout: float = 180.0,
        wait_selector: Optional[str] = None,
        user_agent: Optional[str] = None,
        qr_callback: Optional[Callable[["object"], None]] = None,
    ):
        self.headless = headless
        self.timeout = timeout
        self.wait_selector = wait_selector
        self.user_agent = user_agent
        # M6.26: optional hook fired after ``on_page_ready`` but before
        # ``_wait_for_success``. The GUI passes a callable that takes
        # the Playwright ``Page`` and snapshots the QR element. The
        # default headed flow (no callback) is unchanged.
        self.qr_callback = qr_callback

    def _run_browser(self, on_page_ready=None) -> "LoginResult":
        """Open Chromium, navigate to a page set up by the subclass,
        and either wait for URL change or for cookies to appear.

        ``on_page_ready(page)`` is called once after the page is
        loaded — subclasses can use it to render the QR or click
        a "login" button. If a ``qr_callback`` was supplied it is
        called **once** right after ``on_page_ready`` with the same
        Page so the caller can take a screenshot of the QR element
        and surface it in the GUI.

        Returns a :class:`LoginResult`.
        """
        require_playwright()
        import time

        started = time.monotonic()
        with sync_playwright() as p:
            # channel="chromium" 必须和 core/sniffer.py 保持一致：发布版不打包
            # chrome-headless-shell.exe（270.7 MB），只带完整 Chromium。虽然
            # 扫码登录一律 headless=False，headed 模式也已实测确认 channel
            # 生效；显式写上是为了让「两处 launch 必须同参数」这条约束在代码
            # 里可见，避免以后有人给登录加 headless 选项时踩坑。
            browser = p.chromium.launch(
                channel="chromium",
                headless=self.headless,
            )
            try:
                context_opts: dict = {}
                if self.user_agent:
                    context_opts["user_agent"] = self.user_agent
                context = browser.new_context(**context_opts)
                page = context.new_page()
                if on_page_ready is not None:
                    on_page_ready(page)
                # M6.26: hand the Page to the QR snapshotter exactly
                # once, *after* the page is set up but *before* we
                # start polling for cookies — that way the QR is on
                # screen by the time the user reaches for their phone.
                if self.qr_callback is not None:
                    try:
                        self.qr_callback(page)
                    except Exception:  # noqa: BLE001
                        # QR snapshot is best-effort; if the selector
                        # is wrong or the page isn't loaded yet, the
                        # login should still proceed.
                        logger.exception("qr_callback raised (continuing)")
                self._wait_for_success(page, context)
                # Cookies are visible via context.cookies() the moment
                # _wait_for_success returns — the previous
                # ``wait_for_load_state("networkidle")`` was a bug:
                # post-login landing pages (Douyin feed, B-station home)
                # have *persistent* traffic (WebSocket, video feed,
                # heartbeats) and never reach networkidle within 10s,
                # throwing ``TimeoutError`` after the cookies are
                # already in hand. A short fixed settle is enough for
                # any final cookie writes that lag behind by a frame.
                page.wait_for_timeout(500)
                cookies = self._collect_cookies(context)
                final_url = page.url
            finally:
                browser.close()
        return LoginResult(
            cookies=cookies,
            final_url=final_url,
            elapsed_seconds=time.monotonic() - started,
        )

    # subclasses must implement
    def _wait_for_success(self, page, context) -> None: ...
    def _collect_cookies(self, context) -> list[dict]: ...

    def _filter_cookies(self, cookies: list[dict], domains: Sequence[str]) -> list[dict]:
        out: list[dict] = []
        for c in cookies:
            d = c.get("domain", "")
            if any(d == dom or d.endswith("." + dom.lstrip(".")) for dom in domains):
                # Normalize for write_netscape_cookies
                out.append({
                    "name": c["name"],
                    "value": c["value"],
                    "domain": c["domain"],
                    "path": c.get("path", "/"),
                    "secure": bool(c.get("secure", False)),
                    "expires": int(c.get("expires", 0) or 0),
                })
        return out


# ---------------------------------------------------------------------------
# URL-change login (B 站)
# ---------------------------------------------------------------------------


class URLChangeLogin(_BaseBrowserLogin):
    """Wait for the page URL to change to a "success" pattern.

    Used by B 站: after the user scans the QR with the B 站 app,
    the page redirects to ``https://www.bilibili.com/`` (or similar
    domain-bearing URL) with the session cookies now set.

    M6.31: 接受 ``qr_callback`` 钩子(对齐 M6.26 抖音 ``CookieSetLogin``),
    让 GUI 能在不弹浏览器窗口的前提下把 QR 元素截图扒下来。
    """

    def __init__(
        self,
        start_url: str,
        success_url_pattern: str,
        cookie_domains: Sequence[str],
        *,
        headless: bool = False,
        timeout: float = 180.0,
        user_agent: Optional[str] = None,
        qr_callback: Optional[Callable[["object"], None]] = None,
    ):
        super().__init__(
            headless=headless, timeout=timeout, user_agent=user_agent,
            qr_callback=qr_callback,
        )
        self.start_url = start_url
        self.success_url_pattern = success_url_pattern
        self.cookie_domains = list(cookie_domains)
        self._compiled = re.compile(success_url_pattern)

    def run(self) -> LoginResult:
        def _on_ready(page):
            page.goto(self.start_url, wait_until="domcontentloaded", timeout=30_000)
            if self.wait_selector:
                try:
                    page.wait_for_selector(self.wait_selector, timeout=10_000)
                except PlaywrightTimeoutError:
                    logger.debug("wait_selector %r timed out (continuing)", self.wait_selector)
        return self._run_browser(on_page_ready=_on_ready)

    def _wait_for_success(self, page, context) -> None:
        try:
            page.wait_for_url(self._compiled, timeout=int(self.timeout * 1000))
        except PlaywrightTimeoutError as e:
            raise BrowserLoginError(
                f"Login timed out after {self.timeout:.0f}s — "
                f"URL did not match {self.success_url_pattern!r}"
            ) from e

    def _collect_cookies(self, context) -> list[dict]:
        return self._filter_cookies(context.cookies(), self.cookie_domains)


# ---------------------------------------------------------------------------
# Cookie-set login (抖音)
# ---------------------------------------------------------------------------


class CookieSetLogin(_BaseBrowserLogin):
    """Wait for a specific set of cookies to appear.

    Used by 抖音: the landing page does not change URL on login,
    but a successful login sets a small set of identifying cookies
    (``ttwid``, ``msToken``, ``odin_tt``, ``passport_csrf_token``,
    ``sid_guard``). We poll the cookie list until at least N of
    them are present (default: all of them).
    """

    def __init__(
        self,
        start_url: str,
        required_cookies: Sequence[str],
        cookie_domains: Sequence[str],
        *,
        headless: bool = False,
        timeout: float = 180.0,
        min_present: Optional[int] = None,
        user_agent: Optional[str] = None,
        qr_callback: Optional[Callable[["object"], None]] = None,
        pre_login_hook: Optional[Callable[["object"], None]] = None,
    ):
        super().__init__(
            headless=headless, timeout=timeout, user_agent=user_agent,
            qr_callback=qr_callback,
        )
        self.start_url = start_url
        self.required_cookies = list(required_cookies)
        self.cookie_domains = list(cookie_domains)
        # By default, require ALL of the cookies
        self.min_present = min_present if min_present is not None else len(self.required_cookies)
        if self.min_present < 1:
            raise ValueError("min_present must be >= 1")
        if self.min_present > len(self.required_cookies):
            raise ValueError("min_present cannot exceed len(required_cookies)")
        # M6.37: optional hook fired after ``page.goto`` but before
        # ``qr_callback`` / ``_wait_for_success``. Douyin uses this to
        # click the "扫码登录" button on the homepage before the QR
        # modal appears (headed-only — headless always gets verify-
        # captcha'd by byte-dance, no QR to surface either way).
        self.pre_login_hook = pre_login_hook

    def run(self) -> LoginResult:
        def _on_ready(page):
            page.goto(self.start_url, wait_until="domcontentloaded", timeout=30_000)
            # M6.37: run the platform-specific pre-login hook (e.g.
            # click the "扫码登录" button to surface the QR modal).
            if self.pre_login_hook is not None:
                try:
                    self.pre_login_hook(page)
                except Exception:  # noqa: BLE001
                    # Pre-login is best-effort — if the click misses
                    # the page may still load the QR via a different
                    # selector, or fail outright via _wait_for_success.
                    logger.exception("pre_login_hook raised (continuing)")
        return self._run_browser(on_page_ready=_on_ready)

    def _wait_for_success(self, page, context) -> None:
        import time
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            present = {c["name"] for c in context.cookies()}
            hit = sum(1 for n in self.required_cookies if n in present)
            if hit >= self.min_present:
                logger.info("Cookie-set login succeeded: %d/%d cookies present",
                            hit, len(self.required_cookies))
                return
            # Politely check every second; if a wait_selector is set
            # we still respect it for early "log in" UI hints.
            if self.wait_selector:
                try:
                    page.wait_for_selector(self.wait_selector, timeout=1_000,
                                            state="visible")
                except PlaywrightTimeoutError:
                    pass
            else:
                page.wait_for_timeout(1_000)
        raise BrowserLoginError(
            f"Login timed out after {self.timeout:.0f}s — "
            f"cookies {self.required_cookies!r} never reached "
            f"{self.min_present}/{len(self.required_cookies)}"
        )

    def _collect_cookies(self, context) -> list[dict]:
        return self._filter_cookies(context.cookies(), self.cookie_domains)
