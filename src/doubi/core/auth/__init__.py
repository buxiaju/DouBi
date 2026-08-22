"""Cross-platform authentication helpers (browser-based auto-login).

This package is deliberately platform-agnostic: it knows how to
drive a Chromium browser, but knows nothing specific about 抖音
or B 站. The platform adapters wrap this with their own URLs /
indicators / cookie-domain filters.

Playwright is an *optional* dependency. Importing this package
never fails — :func:`require_playwright` raises a clear
``RuntimeError`` at *use* time if Playwright isn't installed.
"""

from __future__ import annotations

from .browser_login import (
    HAS_PLAYWRIGHT,
    BrowserLoginError,
    CookieSetLogin,
    URLChangeLogin,
    install_playwright_instructions,
    require_playwright,
)

__all__ = [
    "HAS_PLAYWRIGHT",
    "BrowserLoginError",
    "CookieSetLogin",
    "URLChangeLogin",
    "install_playwright_instructions",
    "require_playwright",
]
