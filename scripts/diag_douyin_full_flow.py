"""M6.37 follow-up: full GUI flow replay.

Headed mode + click the "扫码登录" button + wait for the QR modal to
appear, then dump what's on the page. This tells us if M6.37's
pre_login_hook click actually works in a real Chromium headed session,
and if so what selector identifies the QR element.

Run::

    $env:PYTHONPATH = "src"
    py scripts/diag_douyin_full_flow.py

Prints to stdout; the goal is to find the QR element selector inside
the modal so we can update ``_qr_snapshot`` to find it.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from doubi.core.auth.browser_login import require_playwright  # noqa: E402

# Same selectors M6.37 uses — keep in sync with platforms/douyin/auth.py
SCAN_LOGIN_SELECTORS = (
    "xpath=//*[normalize-space(text())='扫码登录']",
    "xpath=//*[contains(text(),'扫码登录')]",
    "xpath=//span[contains(text(),'扫码')]",
    "xpath=//div[contains(text(),'扫码')]",
    "xpath=//a[contains(text(),'登录')]",
)

# After the click, look for ANY of these in the modal area.
# We try a wide net because the 2026 modal selector is unknown.
POST_CLICK_CANDIDATES = (
    # Common byte-dance / douyin patterns
    "[class*='QRCode']",
    "[class*='qrcode']",
    "[class*='qr-code']",
    "[class*='loginCode']",
    "[class*='login-code']",
    "[class*='LoginCode']",
    "[class*='login-qrcode']",
    "[data-e2e*='qrcode']",
    "[data-e2e*='qr-code']",
    "[data-e2e*='login']",
    "canvas",
    "img[alt*='QR']",
    "img[alt*='二维码']",
    "img[alt*='qrcode']",
    "img[src*='qrcode']",
    "img[src*='data:image/png;base64']",
    # Modal containers (the QR is usually inside a modal/portal)
    "[class*='modal']",
    "[class*='Modal']",
    "[class*='dialog']",
    "[class*='Dialog']",
    "[class*='portal']",
    "[class*='mask']",
    "[role='dialog']",
)


def main() -> None:
    require_playwright()
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        print("[diag] launching headed Chromium…")
        browser = p.chromium.launch(channel="chromium", headless=False)
        try:
            ctx = browser.new_context(
                viewport={"width": 1280, "height": 720},
            )
            page = ctx.new_page()

            print("[diag] navigating to https://www.douyin.com/ …")
            page.goto("https://www.douyin.com/", wait_until="load", timeout=30_000)
            try:
                page.wait_for_load_state("networkidle", timeout=10_000)
            except Exception:
                pass
            print(f"[diag] landed at {page.url}")
            print(f"[diag] title: {page.title()!r}")

            # ---- 1. Pre-click: confirm "扫码登录" button is found ----
            print()
            print("=" * 60)
            print("Pre-click probe — locate '扫码登录' button")
            print("=" * 60)
            clicked = False
            for sel in SCAN_LOGIN_SELECTORS:
                try:
                    el = page.locator(sel).first
                    if el.is_visible(timeout=2_000):
                        box = el.bounding_box()
                        text = (el.text_content() or "").strip()
                        print(f"  + visible: {sel!r} box={box} text={text!r}")
                        print(f"    -> clicking")
                        el.click(timeout=5_000)
                        clicked = True
                        break
                    else:
                        print(f"  - not visible: {sel!r}")
                except Exception as exc:  # noqa: BLE001
                    print(f"  - {sel!r}: {exc!r}")
            if not clicked:
                print("[diag] FAILED to find/click '扫码登录' button")
                print("[diag] page is what it is — login flow won't work")
                return

            # ---- 2. Wait for modal to render ----
            print()
            print("[diag] waiting 2s for modal animation…")
            page.wait_for_timeout(2_000)
            print(f"[diag] still at {page.url}")
            print(f"[diag] title: {page.title()!r}")

            # ---- 3. Post-click: probe for QR / modal elements ----
            print()
            print("=" * 60)
            print("Post-click probe — find QR / modal elements")
            print("=" * 60)
            hits = 0
            for sel in POST_CLICK_CANDIDATES:
                try:
                    loc = page.locator(sel)
                    count = loc.count()
                except Exception as exc:  # noqa: BLE001
                    continue
                if count == 0:
                    continue
                hits += 1
                print(f"  {sel!r}: {count} match(es)")
                for i in range(min(count, 3)):
                    el = loc.nth(i)
                    try:
                        box = el.bounding_box()
                        visible = el.is_visible()
                        text = (el.text_content() or "").strip()[:60]
                        outer = el.evaluate("e => e.outerHTML").strip()[:280]
                    except Exception as exc:  # noqa: BLE001
                        print(f"    [{i}] inspect failed: {exc!r}")
                        continue
                    print(f"    [{i}] visible={visible} box={box} text={text!r}")
                    print(f"        outerHTML: {outer}")
            if hits == 0:
                print("  [no candidates hit] — modal may not have appeared")

            # ---- 4. Dump full body for debugging ----
            try:
                body_html = page.locator("body").evaluate("e => e.outerHTML")
                dump = ROOT / "tmp_douyin_after_click.html"
                dump.write_text(body_html, encoding="utf-8")
                print()
                print(f"  [diag] body after click dumped to {dump} "
                      f"({len(body_html)} chars)")
            except Exception as exc:  # noqa: BLE001
                print(f"  body dump failed: {exc!r}")

        finally:
            browser.close()


if __name__ == "__main__":
    main()
