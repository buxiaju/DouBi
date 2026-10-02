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

# PySide6 imports are kept lazy (inside each wrapper) to keep this
# module importable in headless smoke tests, but M6.28 needs three names
# at module level so the cross-thread dispatcher in
# :func:`bilibili_qr_login_image` can ``postEvent`` typed events to a
# ``QObject`` parented to ``QApplication.instance()``. Lazy import of
# these inside the function is fine — the function is only called from
# the GUI anyway.

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


def bilibili_qr_login_image(
    *,
    cookie_path: Optional[Path] = None,
    max_wait: float = 180.0,
    on_qr_ready: Callable[[bytes], None],
    on_status: Callable[[str], None],
    on_done: Callable[[Optional[Path], Optional[Exception]], None],
    headless: bool = True,
) -> threading.Thread:
    """Run the M6.31 Playwright-headless B 站 login in a background thread.

    M6.31: 撤掉 M6.25 + M6.30 的 pure-httpx 路径 — 2026-09 实测
    发现 B 站 web 端针对纯 API 路径反爬,``data.url`` 跳转不通过
    Set-Cookie 下发 cookies,纯 httpx 拿不到。改走跟 M6.26 抖音
    一样的路径:``URLChangeLogin`` 在后台跑 Playwright,
    ``headless=True``(默认)让用户**看不到**浏览器窗口;
    ``qr_callback`` 钩子在登录页加载之后截 QR 元素 → PNG bytes
    → 通过 ``on_qr_ready`` 推回 GUI。

    ``on_qr_ready`` receives **PNG bytes** (跟抖音 dialog 一致) —
    GUI 端用 ``QImage.fromData(bytes, "PNG")`` 转 ``QPixmap`` 居中
    显示。``on_status`` receives a human-readable string status —
    Playwright 路径能给出的信号比较粗(``starting_browser`` /
    ``timeout`` / ``failed`` / ``done`` / ``unknown``),精细的
    "已扫码 / 请确认" 在 B 站 URL 变化前看不到,留给 GUI 显示
    "二维码已就绪 — 等待扫码"。

    **Threading contract (M6.28)**: 跟原来一致,callback 通过
    ``QApplication.postEvent`` 切回主线程,GUI 端零改动。
    """
    from ..platforms.bilibili import auth as bili_auth  # noqa: F811 — also module-level for testability
    from PySide6.QtCore import QEvent, QObject
    from PySide6.QtWidgets import QApplication

    target = cookie_path or bili_auth.default_cookie_path()
    box: dict = {}

    # ---- Cross-thread callback dispatching (M6.28) ----

    class _BiliQRReadyEvent(QEvent):
        event_type = QEvent.Type(QEvent.registerEventType())

        def __init__(self, png_bytes):
            super().__init__(self.event_type)
            self.png_bytes = png_bytes

    class _BiliStatusEvent(QEvent):
        event_type = QEvent.Type(QEvent.registerEventType())

        def __init__(self, status):
            super().__init__(self.event_type)
            self.status = status

    class _BiliDoneEvent(QEvent):
        event_type = QEvent.Type(QEvent.registerEventType())

        def __init__(self, path, error):
            super().__init__(self.event_type)
            self.path = path
            self.error = error

    app = QApplication.instance()
    if app is not None:
        class _Dispatcher(QObject):
            def event(self, ev):  # type: ignore[override]
                if ev.type() == _BiliQRReadyEvent.event_type:
                    if on_qr_ready is not None:
                        on_qr_ready(ev.png_bytes)
                    return True
                if ev.type() == _BiliStatusEvent.event_type:
                    if on_status is not None:
                        on_status(ev.status)
                    return True
                if ev.type() == _BiliDoneEvent.event_type:
                    if on_done is not None:
                        on_done(ev.path, ev.error)
                    return True
                return super().event(ev)

        _dispatcher = _Dispatcher(app)  # noqa: F841 — kept alive via parent

        def _on_qr(png_bytes) -> None:
            QApplication.postEvent(_dispatcher, _BiliQRReadyEvent(png_bytes))

        def _on_st(status) -> None:
            QApplication.postEvent(_dispatcher, _BiliStatusEvent(status))

        def _on_dn(path, error) -> None:
            QApplication.postEvent(_dispatcher, _BiliDoneEvent(path, error))
    else:
        # No QApplication yet (CLI / smoke tests). Call inline.
        _on_qr = on_qr_ready
        _on_st = on_status
        _on_dn = on_done

    def _qr_snapshot(page) -> None:
        """截 B 站 passport 登录页的 QR 元素。

        跟抖音 ``_qr_snapshot`` 同模式:候选选择器 + viewport 兜底。
        M6.32: B 站 passport.bilibili.com 登录页的 QR 元素实际是
        ``<div class="login-scan__qrcode">`` 嵌 ``<img alt="Scan me!"
        src="data:image/png;base64,...">``。M6.33: 必须先
        ``wait_for_selector`` 等 JS 渲染完再截——``domcontentloaded``
        不等 JS,B 站 QR 是 JS 异步生成的。M6.34: 截**父 div**
        而不是 img——img 元素 140x140 但内部 QR 矩阵被 padding
        挤到中央,截 img 会切掉左右两边的 finder pattern;div
        158x158 包含完整 QR + 留白 padding,scale 到 dialog 260
        居中显示后三个 finder pattern 都在。
        """
        # 等 JS 异步生成 QR 元素(最多 10s;若 10s 还没出来就走兜底)
        try:
            page.wait_for_selector(
                "div.login-scan__qrcode img, img[alt='Scan me!']",
                timeout=10_000,
                state="visible",
            )
        except Exception:   # noqa: BLE001
            # 走候选 selector + viewport 兜底
            pass

        # 优先截父 div(包含完整 QR + padding,scale 后三个 finder
        # pattern 都在);回退到 img(可能裁切,但聊胜于无);最后 viewport
        selectors = (
            "div.login-scan__qrcode",  # M6.34: 最稳,158x158 含完整 QR
            "div[class*='qrcode']",
            "div[class*='qrcode'] img",
            "img[alt='Scan me!']",
            "img[alt*='QR']",
        )
        png_bytes = None
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if el.is_visible():
                    png_bytes = el.screenshot(type="png")
                    break
            except Exception:   # noqa: BLE001
                continue
        if png_bytes is None:
            try:
                png_bytes = page.screenshot(type="png", full_page=False)
            except Exception:   # noqa: BLE001
                return
        _on_qr(png_bytes)

    def _runner():
        try:
            cookies = bili_auth.browser_login(
                headless=headless,
                timeout=max_wait,
                qr_callback=_qr_snapshot,
            )
        except Exception as exc:   # noqa: BLE001
            box["error"] = exc
            return
        # M6.35: write_netscape_cookies 签名是 (cookies, path=None) -> Path,
        # 不返回 (ok, msg) tuple;失败时直接 raise。先 try/except 包一层
        # 而不是错误地解包 Path 对象。
        try:
            bili_auth.write_netscape_cookies(cookies, path=target)
        except Exception as exc:   # noqa: BLE001
            box["error"] = RuntimeError(f"B 站 cookies 写入失败:{exc}")
            return
        box["path"] = target

    def _wrap():
        # 在 _runner 之前先发个 "启动无头浏览器" 状态 — GUI 立刻有反馈
        _on_st("starting_browser")

        t = threading.Thread(target=_runner, daemon=True)
        t.start()
        t.join(timeout=max_wait + 30)
        if t.is_alive():
            _on_st("timeout")
            _on_dn(None, TimeoutError("B 站 QR 登录超时"))
        elif "error" in box:
            _on_st("failed")
            _on_dn(None, box["error"])
        elif "path" in box:
            _on_st("done")
            _on_dn(box["path"], None)
        else:
            _on_st("unknown")
            _on_dn(None, RuntimeError("B 站 QR 登录未取到结果"))

    t = threading.Thread(target=_wrap, daemon=True)
    t.start()
    return t

    def _wrap():
        t = threading.Thread(target=_runner, daemon=True)
        t.start()
        # Generous outer bound: cookie persistence + UI ack.
        t.join(timeout=max_wait + 30)
        if t.is_alive():
            _on_dn(None, TimeoutError("B 站 QR 登录超时"))
        elif "error" in box:
            _on_dn(None, box["error"])
        elif "path" in box:
            _on_dn(box["path"], None)
        else:
            _on_dn(None, RuntimeError("B 站 QR 登录未取到结果"))

    t = threading.Thread(target=_wrap, daemon=True)
    t.start()
    return t


def douyin_login_via_browser(
    *, headless: bool, timeout: float,
    on_done: Callable[[Optional[list[dict]], Optional[Exception]], None],
    on_qr_image: Optional[Callable[[bytes], None]] = None,
) -> threading.Thread:
    """Run Playwright in a background thread; call ``on_done`` on finish.

    ``on_done(cookies, error)`` — exactly one of the two is non-None.
    The caller is responsible for the UI (showing a window, asking
    the user to scan, etc).

    If ``on_qr_image`` is provided the M6.26 hook fires inside the
    Playwright thread right after the page is loaded: it takes a PNG
    screenshot of the QR element and hands the raw bytes to the
    callback. The GUI then converts those bytes to a ``QPixmap`` and
    shows them in a label. Best-effort: a selector miss logs and
    continues, the login still proceeds (and ``on_qr_image`` is **not**
    re-invoked).
    """
    from ..platforms.douyin import auth as dy_auth

    box: dict = {}

    def _qr_snapshot(page) -> None:
        """Snapshot the QR element on the douyin web login modal.

        M6.36: 跟 B 站 (M6.33) 对齐 — 抖音 QR 也是 JS 异步渲染的,
        ``CookieSetLogin`` 用 ``wait_until="domcontentloaded"`` 不等
        JS,callback 进来时所有 selector 都找不到。改前: dialog 显示
        白板。修复: 先 ``wait_for_selector`` 等最可能的 QR 元素
        (10s 上限)再走候选 selector;再找不到才 viewport fallback。

        M6.38: ``scripts/diag_douyin_full_flow.py --headed`` click
        "扫码登录" 按钮之后实证:抖音 2026 modal 里的 QR 元素是
        ``<img class="UoVu4M7K" src="data:image/png;base64,...">``,
        178x178,位于 (370, 275)。这是字节系前端用 React/Semi
        渲染的登录 modal,真 QR 是 data-URI base64 PNG,前面有
        ``class*='qrcode'``/``data-e2e='login-qrcode'`` 的元素都不
        存在了。所以走 **base64 PNG img 选 178x178 那个** 最稳。
        不过这种 class 是 hash 命名的,稳定 selector 还是
        ``img[src^='data:image/png;base64']`` + size filter。

        M6.39: **轮询等 QR 出现**(最长 60s)。抖音 2026 真实 headed
        流程(用户 IP/cookie 被字节标记过)经常先弹 verify 中继页,
        pre_login_hook click 按钮失败后用户**手动通过 verify** 滑块
        + 必要时手动点 "扫码登录" 按钮,之后真 QR 才会出来。
        单次截图 + viewport fallback 会截到 verify UI 而不是 QR。
        改为: 每 2s 轮询一次找 178x178 base64 PNG;一旦找到立刻
        截图;超时 60s 后才走 viewport fallback 兜底(让 dialog 至少
        有个东西显示)。
        """
        import time
        deadline = time.monotonic() + 60.0
        qr_bytes: Optional[bytes] = None

        # M6.36 一次性 wait:等 JS 异步生成 modal + 第一个 base64 PNG
        try:
            page.wait_for_selector(
                "img[src^='data:image/png;base64'], "
                "div[data-e2e='login-qrcode'] img, "
                "div[class*='qrcode'] img, "
                "img[class*='qrcode']",
                timeout=10_000,
                state="visible",
            )
        except Exception:   # noqa: BLE001
            # 即使没等到,继续轮询 — 抖音 verify 中继页可能
            # 临时挡住 base64 PNG,verify 通过后才会出现
            pass

        while time.monotonic() < deadline:
            # 1) 找 178x178 base64 PNG(M6.38 实证的真 QR selector)
            try:
                base64_imgs = page.locator("img[src^='data:image/png;base64']")
                n = base64_imgs.count()
                for i in range(n):
                    el = base64_imgs.nth(i)
                    try:
                        if not el.is_visible():
                            continue
                        box = el.bounding_box()
                        if box is None:
                            continue
                        # QR 真实尺寸 140-220px;头像/缩略图 16-64px
                        if (140 <= box["width"] <= 220
                                and 140 <= box["height"] <= 220):
                            qr_bytes = el.screenshot(type="png")
                            break
                    except Exception:   # noqa: BLE001
                        continue
                if qr_bytes is not None:
                    break
            except Exception:   # noqa: BLE001
                pass

            # 2) 兜底:经典 selector 链(以防抖音改回旧 class)
            if qr_bytes is None:
                fallback_selectors = (
                    "div[data-e2e='login-qrcode']",
                    "div.login-QRcode",
                    "div[data-e2e='login-qrcode'] img",
                    "div.login-QRcode img",
                    "img[class*='qrcode']",
                    "div[class*='qrcode'] img",
                )
                for sel in fallback_selectors:
                    try:
                        el = page.locator(sel).first
                        if el.is_visible():
                            qr_bytes = el.screenshot(type="png")
                            break
                    except Exception:   # noqa: BLE001
                        continue
                if qr_bytes is not None:
                    break

            # 还没找到,等 2s 再试
            try:
                page.wait_for_timeout(2_000)
            except Exception:   # noqa: BLE001
                break

        if qr_bytes is None:
            # 60s 轮询超时,viewport fallback 兜底(让 dialog 至少
            # 显示 verify UI / 当前页面状态,而不是白板)
            try:
                qr_bytes = page.screenshot(type="png", full_page=False)
            except Exception:   # noqa: BLE001
                return
        if on_qr_image is not None:
            on_qr_image(qr_bytes)

    def _runner():
        try:
            box["cookies"] = dy_auth.browser_login(
                headless=headless, timeout=timeout,
                qr_callback=_qr_snapshot if on_qr_image is not None else None,
            )
        except Exception as exc:   # noqa: BLE001
            box["error"] = exc

    def _wrap():
        t = threading.Thread(target=_runner, daemon=True)
        t.start()
        # Generous outer bound: cookie persistence + UI ack.
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
    # The online validator calls a risk-controlled endpoint that often
    # rejects plain httpx requests. But if we harvested a login-state
    # cookie (sessionid family), the login itself *did* succeed —
    # don't report failure just because the probe was blocked.
    names = {c.get("name") for c in cookies}
    if names & {"sessionid", "sessionid_ss", "sid_guard"}:
        return True, "登录成功，Cookie 已保存（在线校验被风控拦截，不影响下载）"
    return False, "Cookie 已保存但抖音仍报未登录"
