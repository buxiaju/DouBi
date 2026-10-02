"""M6.36 diagnostic: open the douyin web login page in headless
Chromium, wait for it to settle, and dump every candidate QR
selector's hit count + first-match outerHTML + bounding box.

Run from project root::

    $env:PYTHONPATH = "src"
    py scripts/diag_douyin_qr_selector.py [URL ...]

If no URL is given we probe ``https://www.douyin.com/`` (production
default). Pass other URLs to compare, e.g.::

    py scripts/diag_douyin_qr_selector.py https://www.douyin.com/login

The script will print to stdout; the goal is to find which selector
actually targets the real login QR element. This is a one-shot
diagnostic — once we know the right selector, delete this file.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from doubi.core.auth.browser_login import require_playwright  # noqa: E402

CANDIDATE_SELECTORS = [
    "div[data-e2e='login-qrcode']",
    "div.login-QRcode",
    "div[data-e2e='login-qrcode'] img",
    "div.login-QRcode img",
    "img[class*='qrcode']",
    "div[class*='qrcode'] img",
    "div[data-e2e*='login'] img",
    "[class*='QRCode']",
    "[class*='QRcode']",
    "[class*='login-qrcode']",
    "img[alt*='QR']",
    "img[alt*='二维码']",
    "img[src*='qrcode']",
    "canvas",
    # 字节系抖音/抖音 web 端 2026 改版后常出现的新 class
    "[class*='web-login']",
    "[class*='loginCode']",
    "[class*='LoginCode']",
    "[class*='webLogin']",
    "[data-e2e*='qrcode']",
    "[data-e2e*='qr-code']",
    "[class*='qrCode']",
    "[class*='qr-code']",
    # 通用:任何有 "扫码" 文本的祖先
    "xpath=//*[contains(text(),'扫码')]",
    "xpath=//*[contains(text(),'扫一扫')]",
    "xpath=//*[contains(text(),'二维码')]",
]


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--headed", action="store_true",
                        help="Run Chromium in headed mode (default: headless)")
    parser.add_argument("urls", nargs="*", default=["https://www.douyin.com/"])
    args = parser.parse_args()
    urls = args.urls
    headless_flag = not args.headed
    if args.headed:
        print("[diag] launching headed Chromium…")
    require_playwright()
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chromium", headless=headless_flag)
        try:
            for url in urls:
                ctx = browser.new_context()
                page = ctx.new_page()
                try:
                    page.goto(url, wait_until="load", timeout=30_000)
                    # Give verify iframe / async JS time to render.
                    try:
                        page.wait_for_load_state("networkidle", timeout=10_000)
                    except Exception:  # noqa: BLE001
                        # Headed mode often never reaches networkidle
                        # (the verify iframe keeps polling). That's
                        # fine — the page is loaded, just busy.
                        pass
                except Exception as exc:  # noqa: BLE001
                    print(f"[diag] navigation failed: {exc!r}", file=sys.stderr)
                    ctx.close()
                    continue

                print("=" * 70)
                print(f"URL: {page.url}")
                print(f"Title: {page.title()!r}")
                print("=" * 70)

                for sel in CANDIDATE_SELECTORS:
                    try:
                        loc = page.locator(sel)
                        count = loc.count()
                    except Exception as exc:  # noqa: BLE001
                        print(f"  {sel!r}: locator() raised {exc!r}")
                        continue
                    if count == 0:
                        continue
                    print(f"  {sel!r}: {count} match(es)")
                    for i in range(min(count, 3)):
                        el = loc.nth(i)
                        try:
                            box = el.bounding_box()
                            visible = el.is_visible()
                            text = (el.text_content() or "").strip()[:80]
                            outer = el.evaluate("e => e.outerHTML").strip()[:280]
                        except Exception as exc:  # noqa: BLE001
                            print(f"    [{i}] inspect failed: {exc!r}")
                            continue
                        print(f"    [{i}] visible={visible} box={box} text={text!r}")
                        print(f"        outerHTML: {outer}")
                    print()

                # Also dump the full body if no selector hit.
                hits = sum(1 for sel in CANDIDATE_SELECTORS
                           if not sel.startswith("xpath=")
                           and page.locator(sel).count() > 0)
                if hits == 0:
                    try:
                        body_html = page.locator("body").evaluate("e => e.outerHTML")
                        dump_path = ROOT / f"tmp_douyin_body_{abs(hash(url)) % 10**6}.html"
                        dump_path.write_text(body_html, encoding="utf-8")
                        print(f"  [no selectors hit] full body dumped to {dump_path}")
                    except Exception as exc:  # noqa: BLE001
                        print(f"  body dump failed: {exc!r}")
                print()
                ctx.close()
        finally:
            browser.close()


if __name__ == "__main__":
    main()
