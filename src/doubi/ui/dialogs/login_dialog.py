"""Login dialogs — QR code + status for B 站, browser flow for 抖音.

Two factories:

* :func:`build_bilibili_qr_dialog` — opens a dialog that:
    1. Calls :func:`bilibili_generate_qr` to fetch a fresh QR.
    2. Renders the QR in a fixed-width text view.
    3. Polls for scan confirmation.
    4. If Playwright is available, runs a Chromium window that
       auto-extracts cookies and saves them.
    5. Otherwise points the user to the manual-import path.

* :func:`build_douyin_browser_dialog` — opens a dialog that launches
  Playwright (or fails gracefully if not installed), waits for the
  cookies, and saves them.

Both dialogs are :class:`QDialog` instances with a "关闭" button. M6.x
在标题区加了「品牌 hero」（小图标 + 应用名 + 平台标签），与主窗口和
关于对话框保持一致的视觉语言。
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("doubi.ui.dialogs.login")


# ---------------------------------------------------------------------------
# 共享：登录对话框顶部的品牌 hero（平台 logo + 平台名 + 应用名）
# ---------------------------------------------------------------------------


def _build_brand_hero(platform: str, accent: str) -> "QWidget":
    """登录对话框的顶部品牌区。

    不是直接用 main_window 的 :func:`header_qss`——主窗口的渐变配色
    不一定契合登录场景，单独给对话框做一份。配色跟随主色。
    """
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QFont
        from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel
    except ImportError:  # pragma: no cover
        return None

    from ..resources import APP_NAME, load_app_icon
    from ..theme import (
        FONT_FAMILY, SPACE_LG, SPACE_MD, RADIUS_CARD, TYPE_H1, TYPE_CAPTION,
        _hex_to_rgba, current_theme, token,
    )

    pack = current_theme()
    bg_color = pack.bg_elevated or token("bg_layer")
    text_color = token("text_primary")
    sub_color = token("text_muted")
    border = _hex_to_rgba(text_color, 0.08)

    hero = QWidget()
    hero.setObjectName("loginBrandHero")
    hero.setStyleSheet(
        f"QWidget#loginBrandHero {{"
        f" background-color: {bg_color};"
        f" border: 1px solid {border};"
        f" border-radius: {RADIUS_CARD}px;"
        f" }}"
    )

    h = QHBoxLayout(hero)
    h.setContentsMargins(SPACE_LG, SPACE_MD, SPACE_LG, SPACE_MD)
    h.setSpacing(SPACE_MD)

    # ---- 平台 badge：圆形背景 + 首字 ----
    badge = QLabel(platform[:1] if platform else "D")
    badge.setFixedSize(40, 40)
    badge.setAlignment(Qt.AlignCenter)
    badge_font = QFont()
    badge_font.setFamilies([s.strip("'") for s in FONT_FAMILY.split(",")])
    badge_font.setPointSize(16)
    badge_font.setBold(True)
    badge.setFont(badge_font)
    badge_color = accent or pack.accent
    badge.setStyleSheet(
        f"QLabel {{"
        f" color: #ffffff;"
        f" background-color: {badge_color};"
        f" border: none;"
        f" border-radius: 20px;"
        f" }}"
    )
    h.addWidget(badge, 0)

    # ---- 文字 ----
    text_col = QVBoxLayout()
    text_col.setContentsMargins(0, 0, 0, 0)
    text_col.setSpacing(2)

    title = QLabel(f"{platform} 登录")
    title.setStyleSheet(
        f"QLabel {{"
        f" font-family: {FONT_FAMILY};"
        f" font-size: {TYPE_H1 - 4}px;"
        f" font-weight: 600;"
        f" color: {text_color};"
        f" background: transparent;"
        f" border: none;"
        f" }}"
    )
    text_col.addWidget(title)

    sub = QLabel(f"{APP_NAME} · 一站式多平台视频下载")
    sub.setStyleSheet(
        f"QLabel {{"
        f" font-family: {FONT_FAMILY};"
        f" font-size: {TYPE_CAPTION}px;"
        f" color: {sub_color};"
        f" background: transparent;"
        f" border: none;"
        f" }}"
    )
    text_col.addWidget(sub)
    h.addLayout(text_col, 1)

    return hero


# ---------------------------------------------------------------------------
# B 站 QR
# ---------------------------------------------------------------------------


def build_bilibili_qr_dialog():
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPlainTextEdit,
        QPushButton, QProgressBar,
    )
    from qfluentwidgets import MessageBox

    from ...ui.auth_actions import (
        bilibili_extract_cookies_via_browser,
        bilibili_generate_qr,
        bilibili_save_cookies,
        bilibili_status,
        bilibili_wait_for_scan,
    )
    from ..theme import muted_qss, token

    class BilibiliQRDialog(QDialog):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setWindowTitle("B 站扫码登录")
            self.resize(500, 600)
            self._qr_session = None
            self._qr_code = None
            self._scan_task: Optional[asyncio.Task] = None
            self._cancelled = False
            self._build_ui()
            QTimer.singleShot(50, self._start)

        def _build_ui(self):
            layout = QVBoxLayout(self)
            layout.setContentsMargins(20, 20, 20, 20)
            layout.setSpacing(12)

            # 顶部品牌 hero —— 与主窗口、关于对话框保持一致的视觉
            hero = _build_brand_hero("B 站", "#00aeec")
            if hero is not None:
                layout.addWidget(hero)

            title = QLabel("用 B 站 App 扫描下方二维码", self)
            font = title.font()
            font.setBold(True)
            font.setPointSize(font.pointSize() + 1)
            title.setFont(font)
            layout.addWidget(title)

            hint = QLabel(
                "打开手机 B 站 App → 右上角扫一扫 → 对准此二维码\n"
                "若二维码看不清，可点 “在浏览器打开” 跳转后扫描",
                self,
            )
            hint.setStyleSheet(muted_qss())
            layout.addWidget(hint)

            self.qr_view = QPlainTextEdit(self)
            self.qr_view.setReadOnly(True)
            self.qr_view.setMinimumHeight(280)
            mono = QFont("Consolas")
            mono.setStyleHint(QFont.Monospace)
            mono.setPointSize(9)
            self.qr_view.setFont(mono)
            self.qr_view.setPlaceholderText("正在生成二维码…")
            layout.addWidget(self.qr_view)

            self.url_label = QLabel("", self)
            self.url_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.url_label.setWordWrap(True)
            self.url_label.setStyleSheet(muted_qss())
            layout.addWidget(self.url_label)

            self.progress = QProgressBar(self)
            self.progress.setRange(0, 0)   # indeterminate
            self.progress.setTextVisible(False)
            self.progress.setFixedHeight(4)
            layout.addWidget(self.progress)

            self.status_label = QLabel("正在准备二维码…", self)
            self.status_label.setStyleSheet(muted_qss())
            layout.addWidget(self.status_label)

            btn_row = QHBoxLayout()
            self.copy_btn = QPushButton("复制链接", self)
            self.copy_btn.clicked.connect(self._copy_url)
            self.close_btn = QPushButton("关闭", self)
            self.close_btn.clicked.connect(self._on_close)
            btn_row.addWidget(self.copy_btn)
            btn_row.addStretch(1)
            btn_row.addWidget(self.close_btn)
            layout.addLayout(btn_row)

        # -------------------------------------------------- async flow

        def _start(self) -> None:
            self._scan_task = asyncio.ensure_future(self._run())

        async def _run(self) -> None:
            try:
                self._qr_session, self._qr_code = await bilibili_generate_qr()
            except Exception as exc:   # noqa: BLE001
                logger.exception("B 站 QR 生成失败")
                self._set_status(f"二维码生成失败：{exc}", error=True)
                return

            self.qr_view.setPlainText(self._qr_code.render_ascii())
            self.url_label.setText(f"或浏览器打开：{self._qr_code.url}")
            self._set_status("等待扫码…（180 秒内有效）")

            try:
                result = await bilibili_wait_for_scan(
                    self._qr_session, self._qr_code.qrcode_key,
                    poll_interval=2.0, max_wait=180.0,
                )
            except asyncio.TimeoutError:
                self._set_status("扫码超时，请重试", error=True)
                await self._close_session()
                return
            except Exception as exc:   # noqa: BLE001
                logger.exception("B 站 QR 轮询失败")
                self._set_status(f"轮询失败：{exc}", error=True)
                await self._close_session()
                return

            from ...platforms.bilibili.qr_login import QRStatus
            if result.status is not QRStatus.SUCCESS:
                self._set_status(
                    f"扫码未成功：{result.status.value}（{result.message}）",
                    error=True,
                )
                await self._close_session()
                return

            self._set_status("扫码成功！正在尝试通过浏览器抓取 Cookie…")

            # Try Playwright extraction. The thread callback will call
            # _on_browser_done via the Qt main thread.
            self.progress.show()
            bilibili_extract_cookies_via_browser(
                headless=False, timeout=120.0,
                on_done=self._on_browser_done_threadsafe,
            )

        def _on_browser_done_threadsafe(
            self, cookies: Optional[list[dict]], error: Optional[Exception],
        ) -> None:
            # Called from worker thread; bounce to main thread.
            from PySide6.QtCore import QMetaObject, Qt
            from PySide6.QtWidgets import QApplication
            QApplication.instance().postEvent(
                self, _BrowserDoneEvent(cookies, error),
            )

        def event(self, ev) -> bool:
            if ev.type() == _BrowserDoneEvent.event_type:
                self._on_browser_done(ev.cookies, ev.error)
                return True
            return super().event(ev)

        def _on_browser_done(
            self, cookies: Optional[list[dict]], error: Optional[Exception],
        ) -> None:
            self.progress.hide()
            if cookies:
                ok, msg = bilibili_save_cookies(cookies)
                self._set_status(msg, error=not ok)
                if ok:
                    self._refresh_status()
                    QTimer.singleShot(800, self.accept)
                return
            err = str(error) if error else "未知错误"
            self._set_status(
                f"浏览器抓取失败：{err}\n请改用 “导入 Cookie 文件” 方式",
                error=True,
            )
            asyncio.ensure_future(self._close_session())

        async def _close_session(self) -> None:
            if self._qr_session is not None:
                try:
                    await self._qr_session.__aexit__(None, None, None)
                except Exception:   # noqa: BLE001
                    pass
                self._qr_session = None

        # -------------------------------------------------- helpers

        def _set_status(self, text: str, *, error: bool = False) -> None:
            color = token("progress_error") if error else token("text_muted")
            self.status_label.setStyleSheet(f"color: {color};")
            self.status_label.setText(text)

        def _copy_url(self) -> None:
            from PySide6.QtWidgets import QApplication
            if self._qr_code is None:
                return
            QApplication.clipboard().setText(self._qr_code.url)

        def _refresh_status(self) -> None:
            """Update the page-level status label after login."""
            try:
                from ...ui.pages.settings import _refresh_account_status_external
                _refresh_account_status_external(self.parent())
            except Exception:   # noqa: BLE001
                logger.debug("status refresh callback missing", exc_info=True)

        def _on_close(self) -> None:
            self._cancelled = True
            if self._scan_task and not self._scan_task.done():
                self._scan_task.cancel()
            if self._qr_session is not None:
                asyncio.ensure_future(self._close_session())
            self.reject()

        def closeEvent(self, ev) -> None:
            self._on_close()
            super().closeEvent(ev)

    # ----- custom event for thread-safe callback --------------------

    from PySide6.QtCore import QEvent

    class _BrowserDoneEvent(QEvent):
        event_type = QEvent.Type(QEvent.registerEventType())

        def __init__(self, cookies, error):
            super().__init__(self.event_type)
            self.cookies = cookies
            self.error = error

    # Inject the event class into the closure namespace.
    BilibiliQRDialog._BrowserDoneEvent = _BrowserDoneEvent

    return BilibiliQRDialog


# ---------------------------------------------------------------------------
# 抖音 browser login
# ---------------------------------------------------------------------------


def build_douyin_browser_dialog():
    from PySide6.QtCore import Qt, QEvent, QTimer
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
        QProgressBar, QPlainTextEdit,
    )

    from ...ui.auth_actions import douyin_login_via_browser, douyin_save_cookies
    from ..theme import muted_qss, token

    class _BrowserDoneEvent(QEvent):
        event_type = QEvent.Type(QEvent.registerEventType())

        def __init__(self, cookies, error):
            super().__init__(self.event_type)
            self.cookies = cookies
            self.error = error

    class DouyinBrowserDialog(QDialog):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setWindowTitle("抖音扫码登录")
            self.resize(500, 460)
            self._cancelled = False
            self._build_ui()
            QTimer.singleShot(50, self._start)

        def _build_ui(self):
            layout = QVBoxLayout(self)
            layout.setContentsMargins(20, 20, 20, 20)
            layout.setSpacing(12)

            # 顶部品牌 hero
            hero = _build_brand_hero("抖音", "#fe2c55")
            if hero is not None:
                layout.addWidget(hero)

            title = QLabel("请在弹出的浏览器窗口中登录抖音", self)
            font = title.font()
            font.setBold(True)
            font.setPointSize(font.pointSize() + 1)
            title.setFont(font)
            layout.addWidget(title)

            hint = QLabel(
                "1. 浏览器会打开抖音登录页\n"
                "2. 点击 “登录”，用抖音 App 扫码（或手机号验证）\n"
                "3. 登录成功后本窗口会自动关闭",
                self,
            )
            hint.setStyleSheet(muted_qss())
            layout.addWidget(hint)

            self.progress = QProgressBar(self)
            self.progress.setRange(0, 0)
            self.progress.setTextVisible(False)
            self.progress.setFixedHeight(4)
            layout.addWidget(self.progress)

            self.status_label = QLabel("正在启动浏览器…", self)
            self.status_label.setStyleSheet(muted_qss())
            self.status_label.setWordWrap(True)
            layout.addWidget(self.status_label)

            self.log_view = QPlainTextEdit(self)
            self.log_view.setReadOnly(True)
            self.log_view.setMaximumHeight(120)
            mono = QFont("Consolas")
            mono.setStyleHint(QFont.Monospace)
            self.log_view.setFont(mono)
            layout.addWidget(self.log_view)

            btn_row = QHBoxLayout()
            btn_row.addStretch(1)
            self.close_btn = QPushButton("关闭", self)
            self.close_btn.clicked.connect(self._on_close)
            btn_row.addWidget(self.close_btn)
            layout.addLayout(btn_row)

        def _start(self) -> None:
            self._set_status("正在启动 Chromium 浏览器…")
            douyin_login_via_browser(
                headless=False, timeout=180.0,
                on_done=self._on_browser_done_threadsafe,
            )

        def _on_browser_done_threadsafe(
            self, cookies: Optional[list[dict]], error: Optional[Exception],
        ) -> None:
            from PySide6.QtWidgets import QApplication
            QApplication.instance().postEvent(
                self, _BrowserDoneEvent(cookies, error),
            )

        def event(self, ev) -> bool:
            if ev.type() == _BrowserDoneEvent.event_type:
                self._on_browser_done(ev.cookies, ev.error)
                return True
            return super().event(ev)

        def _on_browser_done(
            self, cookies: Optional[list[dict]], error: Optional[Exception],
        ) -> None:
            self.progress.hide()
            if cookies:
                ok, msg = douyin_save_cookies(cookies)
                self._set_status(msg, error=not ok)
                if ok:
                    QTimer.singleShot(800, self.accept)
                return
            err = str(error) if error else "未知错误"
            self._set_status(
                f"浏览器登录失败：{err}\n请改用 “导入 Cookie 文件” 方式",
                error=True,
            )

        def _set_status(self, text: str, *, error: bool = False) -> None:
            color = token("progress_error") if error else token("text_muted")
            self.status_label.setStyleSheet(f"color: {color};")
            self.status_label.setText(text)
            self.log_view.appendPlainText(text)

        def _on_close(self) -> None:
            self._cancelled = True
            self.reject()

        def closeEvent(self, ev) -> None:
            self._cancelled = True
            super().closeEvent(ev)

    DouyinBrowserDialog._BrowserDoneEvent = _BrowserDoneEvent
    return DouyinBrowserDialog
