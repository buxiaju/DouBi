"""M6.42: 抖音扫码登录后的 SMS 二次验证 dialog。

背景:抖音 web 端 2026 起,扫码登录后如果平台风控认为设备/IP
异常,会再要求**手机号 + 短信验证码**二次验证。`LoginInfo.
need_sms_verify=True` 是触发信号 — 走 ``DouyinWebAPI.send_
sms_code`` + ``verify_sms_code`` 两条 API 完成验证。

UI 结构:
- 手机号输入(默认 11 位中国大陆手机号格式)
- "获取验证码"按钮(发短信,触发 send_sms_code)
- 60s 倒计时(防止重复点击,触发 2001 频控)
- 验证码输入(6 位数字)
- "确认提交"按钮(触发 verify_sms_code)
- 失败提示(根据 error_code 走 i18n)

不依赖 headed 浏览器 — 纯 API 路径(headless / headed 都可用)。
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QProgressBar, QMessageBox,
)

from ..i18n import tr

logger = logging.getLogger("doubi.ui.dialogs.sms_verify")

# China mobile number: 11 digits starting with 1[3-9]. We do not
# support international numbers here — 抖音 web SMS flow is CN-only
# in the public API docs.
_PHONE_RE = re.compile(r"^1[3-9]\d{9}$")
_SMS_CODE_RE = re.compile(r"^\d{4,8}$")
_RESEND_COOLDOWN = 60  # seconds between SMS sends


class SmsVerifyDialog(QDialog):
    """Async SMS second-factor dialog for 抖音.

    The dialog drives ``DouyinWebAPI.send_sms_code`` /
    ``verify_sms_code`` directly (no Playwright). It uses ``QTimer`` to
    enforce the 60s resend cooldown and ``asyncio`` to fire the API
    calls off the GUI thread (the WebAPI client is async).
    """

    def __init__(
        self,
        *,
        cookies_file,  # Path — passed to DouyinWebAPI
        initial_phone: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(tr("login.dy.sms.window_title"))
        self.setModal(True)
        self.setMinimumWidth(420)

        self._cookies_file = cookies_file
        self._initial_phone = initial_phone
        self._busy = False
        self._cooldown_left = 0
        self._resend_timer: Optional[QTimer] = None
        self._last_error: Optional[str] = None

        outer = QVBoxLayout(self)

        # ---- header ----
        hint = QLabel(tr("login.dy.sms.hint"), self)
        hint.setWordWrap(True)
        outer.addWidget(hint)

        # ---- phone input + send button ----
        phone_row = QHBoxLayout()
        phone_row.addWidget(QLabel(tr("login.dy.sms.phone_label"), self))
        self.phone_edit = QLineEdit(self)
        self.phone_edit.setPlaceholderText("13800000000")
        self.phone_edit.setText(initial_phone)
        self.phone_edit.setMaxLength(11)
        phone_row.addWidget(self.phone_edit, 1)
        self.send_btn = QPushButton(tr("login.dy.sms.send_btn"), self)
        self.send_btn.clicked.connect(self._on_send_clicked)
        phone_row.addWidget(self.send_btn)
        outer.addLayout(phone_row)

        # ---- SMS code input + verify button ----
        code_row = QHBoxLayout()
        code_row.addWidget(QLabel(tr("login.dy.sms.code_label"), self))
        self.code_edit = QLineEdit(self)
        self.code_edit.setPlaceholderText("6 位数字")
        self.code_edit.setMaxLength(8)
        code_row.addWidget(self.code_edit, 1)
        outer.addLayout(code_row)

        # ---- status + progress ----
        self.status_label = QLabel("", self)
        self.status_label.setWordWrap(True)
        outer.addWidget(self.status_label)
        self.progress = QProgressBar(self)
        self.progress.setRange(0, 0)  # indeterminate
        self.progress.setVisible(False)
        outer.addWidget(self.progress)

        # ---- action buttons ----
        btn_row = QHBoxLayout()
        self.verify_btn = QPushButton(tr("login.dy.sms.verify_btn"), self)
        self.verify_btn.setDefault(True)
        self.verify_btn.clicked.connect(self._on_verify_clicked)
        cancel_btn = QPushButton(tr("common.cancel"), self)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch(1)
        btn_row.addWidget(self.verify_btn)
        btn_row.addWidget(cancel_btn)
        outer.addLayout(btn_row)

    # ------------------------------------------------------------------
    # QDialog lifecycle
    # ------------------------------------------------------------------

    def closeEvent(self, ev: QCloseEvent) -> None:
        # Stop the resend timer so we don't leak QTimer objects past
        # dialog destruction.
        if self._resend_timer is not None:
            self._resend_timer.stop()
            self._resend_timer = None
        super().closeEvent(ev)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _set_status(self, text: str, *, error: bool = False) -> None:
        self.status_label.setText(text)
        # Don't bundle a style sheet — QFluentWidgets theme covers it.
        self._last_error = text if error else None

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.progress.setVisible(busy)
        self.send_btn.setEnabled(not busy)
        self.verify_btn.setEnabled(not busy)
        self.phone_edit.setEnabled(not busy)
        self.code_edit.setEnabled(not busy)

    def _start_resend_cooldown(self) -> None:
        self._cooldown_left = _RESEND_COOLDOWN
        if self._resend_timer is None:
            self._resend_timer = QTimer(self)
            self._resend_timer.setInterval(1000)
            self._resend_timer.timeout.connect(self._tick_cooldown)
        self._resend_timer.start()
        self._tick_cooldown()

    def _tick_cooldown(self) -> None:
        if self._cooldown_left <= 0:
            if self._resend_timer is not None:
                self._resend_timer.stop()
            self.send_btn.setText(tr("login.dy.sms.send_btn"))
            self.send_btn.setEnabled(True and not self._busy)
            return
        self.send_btn.setText(
            tr("login.dy.sms.resend_in", seconds=self._cooldown_left)
        )
        self.send_btn.setEnabled(False)
        self._cooldown_left -= 1

    @staticmethod
    def _is_phone(s: str) -> bool:
        return bool(_PHONE_RE.match(s.strip()))

    @staticmethod
    def _is_code(s: str) -> bool:
        return bool(_SMS_CODE_RE.match(s.strip()))

    # ------------------------------------------------------------------
    # Click handlers
    # ------------------------------------------------------------------

    def _on_send_clicked(self) -> None:
        phone = self.phone_edit.text().strip()
        if not self._is_phone(phone):
            self._set_status(
                tr("login.dy.sms.error_invalid_phone"), error=True,
            )
            return
        if self._busy:
            return
        self._set_busy(True)
        self._set_status(tr("login.dy.sms.status_sending"))
        # Fire the async API off the GUI thread. We use a fresh event
        # loop because we're inside a Qt signal callback — using
        # ``asyncio.run`` would conflict with qasync.
        try:
            loop = asyncio.new_event_loop()
            try:
                resp = loop.run_until_complete(self._do_send(phone))
            finally:
                loop.close()
        except Exception as exc:  # noqa: BLE001
            logger.exception("M6.42: send_sms_code failed")
            self._set_busy(False)
            self._set_status(
                tr("login.dy.sms.error_network", error=str(exc)), error=True,
            )
            return
        self._set_busy(False)
        self._interpret_send_result(resp)

    def _on_verify_clicked(self) -> None:
        phone = self.phone_edit.text().strip()
        code = self.code_edit.text().strip()
        if not self._is_phone(phone):
            self._set_status(
                tr("login.dy.sms.error_invalid_phone"), error=True,
            )
            return
        if not self._is_code(code):
            self._set_status(
                tr("login.dy.sms.error_invalid_code"), error=True,
            )
            return
        if self._busy:
            return
        self._set_busy(True)
        self._set_status(tr("login.dy.sms.status_verifying"))
        try:
            loop = asyncio.new_event_loop()
            try:
                resp = loop.run_until_complete(self._do_verify(phone, code))
            finally:
                loop.close()
        except Exception as exc:  # noqa: BLE001
            logger.exception("M6.42: verify_sms_code failed")
            self._set_busy(False)
            self._set_status(
                tr("login.dy.sms.error_network", error=str(exc)), error=True,
            )
            return
        self._set_busy(False)
        ok = self._interpret_verify_result(resp)
        if ok:
            # Successful — close the dialog, signal success to caller.
            self.accept()

    # ------------------------------------------------------------------
    # Async API calls
    # ------------------------------------------------------------------

    async def _do_send(self, phone: str) -> dict:
        from ...platforms.douyin.webapi import DouyinWebAPI
        api = DouyinWebAPI(cookies_file=self._cookies_file)
        return await api.send_sms_code(phone)

    async def _do_verify(self, phone: str, code: str) -> dict:
        from ...platforms.douyin.webapi import DouyinWebAPI
        api = DouyinWebAPI(cookies_file=self._cookies_file)
        return await api.verify_sms_code(phone, code)

    # ------------------------------------------------------------------
    # Result interpretation
    # ------------------------------------------------------------------

    def _interpret_send_result(self, resp: dict) -> None:
        """Translate 抖音's send-SMS response into UI status.

        抖音 web API 的 send 端点正常情况返回 ``{"status_code": 0, ...}``。
        其他 status_code 走 i18n 失败提示。
        """
        if not resp:
            self._set_status(
                tr("login.dy.sms.error_empty_response"), error=True,
            )
            return
        status_code = resp.get("status_code")
        if status_code == 0:
            self._set_status(tr("login.dy.sms.status_sent"))
            self._start_resend_cooldown()
        elif status_code in (2001, 2002, 2003):
            # 2001 = "操作频繁,请稍后再试" (频控), 2002/2003 类似的
            self._set_status(
                tr("login.dy.sms.error_rate_limited"), error=True,
            )
        else:
            desc = resp.get("description") or resp.get("message") or ""
            self._set_status(
                tr("login.dy.sms.error_send_failed",
                   code=status_code, desc=desc),
                error=True,
            )

    def _interpret_verify_result(self, resp: dict) -> bool:
        """Return True if SMS verification succeeded."""
        if not resp:
            self._set_status(
                tr("login.dy.sms.error_empty_response"), error=True,
            )
            return False
        status_code = resp.get("status_code")
        if status_code == 0:
            self._set_status(tr("login.dy.sms.status_verified"))
            return True
        # Map common failure codes to user-friendly messages.
        if status_code in (1003, 1004, 1005, 2002):
            self._set_status(
                tr("login.dy.sms.error_wrong_code"), error=True,
            )
        else:
            desc = resp.get("description") or resp.get("message") or ""
            self._set_status(
                tr("login.dy.sms.error_verify_failed",
                   code=status_code, desc=desc),
                error=True,
            )
        return False
