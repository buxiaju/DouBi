"""Settings page — runtime config knobs (M5.1) + 账号 (M5.3).

Adds proxy / concurrency / theme over the M5 skeleton, and a 账号
card that surfaces the current login state of B 站 and 抖音 with
one-click entry points to the QR / browser login dialogs and to
cookie file import.

Save writes ``~/.doubi/config.yml`` (the same file the CLI reads),
so GUI-set values carry over to CLI / REST / MCP runs.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger("doubi.ui.pages.settings")


# ---------------------------------------------------------------------------
# Module-level helper used by login dialogs to refresh the parent page
# ---------------------------------------------------------------------------


def _refresh_account_status_external(host) -> None:
    """Best-effort: find a :class:`SettingsPage` somewhere in the tree
    and ask it to refresh its account status block."""
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            return
        if host is None:
            return
        page = _find_settings_page(host)
        if page is not None and hasattr(page, "_refresh_account_status"):
            page._refresh_account_status()
    except Exception:   # noqa: BLE001
        logger.debug("refresh account status failed", exc_info=True)


def _find_settings_page(widget):
    from PySide6.QtWidgets import QWidget
    if widget is None:
        return None
    if widget.objectName() == "settingsPage":
        return widget
    if isinstance(widget, QWidget):
        for child in widget.findChildren(QWidget, "settingsPage"):
            return child
    return None


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------


def build_settings_widgets():
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QFileDialog, QLabel,
        QScrollArea, QSizePolicy,
    )
    from qfluentwidgets import (
        LineEdit, ComboBox, SwitchButton, PushButton, StrongBodyLabel,
        InfoBar, InfoBarPosition, setTheme, Theme, CardWidget,
    )

    from ...core.config import load_config
    from ...ui.auth_actions import (
        LoginStatus,
        bilibili_status,
        douyin_status,
        import_bilibili_cookies,
        import_douyin_cookies,
        import_douyin_legacy_json,
    )

    class SettingsPage(QWidget):
        def __init__(self, parent: Optional[QWidget] = None):
            super().__init__(parent)
            self.setObjectName("settingsPage")
            self._cfg = load_config(None)
            self._bili_status: Optional[LoginStatus] = None
            self._douyin_status: Optional[LoginStatus] = None
            self._build_ui()
            self._load_from_cfg()
            # Populate the account block asynchronously
            QTimer.singleShot(50, lambda: asyncio.ensure_future(self._refresh_account_status_async()))

        # ---------------------------------------------------------- UI

        def _build_ui(self):
            outer = QVBoxLayout(self)
            outer.setContentsMargins(20, 16, 20, 16)
            outer.setSpacing(10)

            title = StrongBodyLabel(self)
            title.setText("设置")
            outer.addWidget(title)

            # ---- wrap everything below the title in a scroll area so it
            # still fits on small screens (low-res / windowed). ---------
            # The area, its viewport and the body container are all made
            # transparent: a QScrollArea otherwise paints its viewport
            # with the near-white palette base color, which clashes with
            # the themed page background (very obvious in dark mode).
            # The vertical scrollbar is hidden too — wheel scrolling and
            # keyboard navigation keep working.
            self._body_scroll = QScrollArea(self)
            self._body_scroll.setWidgetResizable(True)
            self._body_scroll.setFrameShape(QScrollArea.NoFrame)
            self._body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self._body_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self._body_scroll.setStyleSheet(
                "QScrollArea { background: transparent; border: none; }"
            )
            self._body_scroll.viewport().setStyleSheet(
                "background: transparent;"
            )

            body = QWidget(self._body_scroll)
            body.setStyleSheet("background: transparent;")
            body.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
            body_layout = QVBoxLayout(body)
            body_layout.setContentsMargins(0, 0, 0, 0)
            body_layout.setSpacing(16)

            # ---- 账号 card ----------------------------------------
            self.account_card = self._build_account_card()
            body_layout.addWidget(self.account_card)

            # ---- runtime config form ------------------------------
            form = QFormLayout()
            form.setVerticalSpacing(14)
            form.setHorizontalSpacing(16)
            form.setContentsMargins(4, 4, 4, 4)

            self.output_root = LineEdit(self)
            self.filename_template = LineEdit(self)
            self.container = ComboBox(self)
            self.container.addItems(["mp4", "mkv"])
            self.max_quality = ComboBox(self)
            self.max_quality.addItems(["best", "8k", "4k", "1080p", "720p", "480p"])
            self.proxy = LineEdit(self)
            self.proxy.setPlaceholderText("http://127.0.0.1:7890（留空不使用）")
            self.concurrent = LineEdit(self)
            self.rate_limit = LineEdit(self)
            self.rate_limit.setPlaceholderText("如 5M（留空不限速）")
            self.database = SwitchButton(self)
            self.theme = ComboBox(self)
            self.theme.addItems(["自动", "亮色", "暗色"])
            self.cookies_dir_label = LineEdit(self)
            self.cookies_dir_label.setReadOnly(True)
            self.open_cookies_btn = PushButton("打开目录", self)
            self.open_cookies_btn.setFixedWidth(96)
            self.open_cookies_btn.clicked.connect(self._on_open_cookies_dir)
            cookies_row = QHBoxLayout()
            cookies_row.setContentsMargins(0, 0, 0, 0)
            cookies_row.setSpacing(8)
            cookies_row.addWidget(self.cookies_dir_label, 1)
            cookies_row.addWidget(self.open_cookies_btn)

            form.addRow("保存根目录：", self.output_root)
            form.addRow("文件名模板：", self.filename_template)
            form.addRow("容器：", self.container)
            form.addRow("最高画质：", self.max_quality)
            form.addRow("代理：", self.proxy)
            form.addRow("并发下载数：", self.concurrent)
            form.addRow("限速：", self.rate_limit)
            form.addRow("启用数据库：", self.database)
            form.addRow("主题：", self.theme)
            form.addRow("Cookie 目录：", cookies_row)
            body_layout.addLayout(form)

            btn_row = QVBoxLayout()
            self.save_btn = PushButton("保存设置", self)
            self.save_btn.clicked.connect(self._on_save)
            btn_row.addWidget(self.save_btn)
            body_layout.addLayout(btn_row)

            body_layout.addStretch(1)

            self._body_scroll.setWidget(body)
            outer.addWidget(self._body_scroll, 1)

        def _build_account_card(self) -> CardWidget:
            card = CardWidget(self)
            layout = QVBoxLayout(card)
            layout.setContentsMargins(16, 16, 16, 16)
            layout.setSpacing(12)

            header = QHBoxLayout()
            header_title = StrongBodyLabel(card)
            header_title.setText("账号与登录")
            header.addWidget(header_title)
            header.addStretch(1)
            self.refresh_status_btn = PushButton("刷新状态", card)
            self.refresh_status_btn.clicked.connect(
                lambda: asyncio.ensure_future(self._refresh_account_status_async())
            )
            header.addWidget(self.refresh_status_btn)
            layout.addLayout(header)

            # ---- B 站 row -----------------------------------------
            bili_row = QHBoxLayout()
            self.bili_status_label = StrongBodyLabel(card)
            self.bili_status_label.setText("B 站：正在检测…")
            bili_row.addWidget(self.bili_status_label, 1)
            self.bili_qr_btn = PushButton("扫码登录", card)
            self.bili_qr_btn.clicked.connect(self._on_bilibili_qr_login)
            self.bili_import_btn = PushButton("导入 Cookie 文件", card)
            self.bili_import_btn.clicked.connect(self._on_bilibili_import)
            bili_row.addWidget(self.bili_qr_btn)
            bili_row.addWidget(self.bili_import_btn)
            layout.addLayout(bili_row)

            bili_detail = QLabel(
                "扫码登录用 B 站 App 扫描二维码；导入 Cookie 用浏览器扩展 "
                "“Get cookies.txt LOCALLY” 导出后再选文件。",
                card,
            )
            bili_detail.setStyleSheet("color: gray;")
            bili_detail.setWordWrap(True)
            layout.addWidget(bili_detail)

            # ---- 抖音 row -----------------------------------------
            dy_row = QHBoxLayout()
            self.dy_status_label = StrongBodyLabel(card)
            self.dy_status_label.setText("抖音：正在检测…")
            dy_row.addWidget(self.dy_status_label, 1)
            self.dy_qr_btn = PushButton("扫码登录", card)
            self.dy_qr_btn.clicked.connect(self._on_douyin_browser_login)
            self.dy_import_btn = PushButton("导入 Cookie 文件", card)
            self.dy_import_btn.clicked.connect(self._on_douyin_import)
            self.dy_legacy_btn = PushButton("导入 douyin-downloader JSON", card)
            self.dy_legacy_btn.clicked.connect(self._on_douyin_legacy_import)
            dy_row.addWidget(self.dy_qr_btn)
            dy_row.addWidget(self.dy_import_btn)
            dy_row.addWidget(self.dy_legacy_btn)
            layout.addLayout(dy_row)

            dy_detail = QLabel(
                "扫码登录会打开 Chromium 窗口，请在窗口里完成登录；"
                "Cookie 抓取完成后会自动写入。",
                card,
            )
            dy_detail.setStyleSheet("color: gray;")
            dy_detail.setWordWrap(True)
            layout.addWidget(dy_detail)

            return card

        def _load_from_cfg(self):
            self.output_root.setText(str(self._cfg.output_root))
            self.filename_template.setText(self._cfg.filename_template)
            self._set_combo(self.container, self._cfg.container)
            self._set_combo(self.max_quality, self._cfg.max_quality)
            self.proxy.setText(self._cfg.proxy or "")
            self.concurrent.setText(str(self._cfg.concurrent_jobs))
            self.rate_limit.setText(self._cfg.rate_limit or "")
            self.database.setChecked(self._cfg.database)
            self.cookies_dir_label.setText(
                str(Path.home() / ".doubi" / "cookies")
            )

        @staticmethod
        def _set_combo(combo: ComboBox, value: str) -> None:
            idx = combo.findText(value)
            if idx >= 0:
                combo.setCurrentIndex(idx)

        # ---------------------------------------------------- 账号

        async def _refresh_account_status_async(self) -> None:
            try:
                self._bili_status = await bilibili_status()
                self._douyin_status = await douyin_status()
            except Exception as exc:   # noqa: BLE001
                logger.warning("账号状态检测失败: %s", exc)
            self._refresh_account_status()

        def _refresh_account_status(self) -> None:
            if self._bili_status is not None:
                self.bili_status_label.setText(
                    f"B 站：{self._bili_status.short_label()}"
                )
            else:
                self.bili_status_label.setText("B 站：未知（点击右上角刷新）")
            if self._douyin_status is not None:
                self.dy_status_label.setText(
                    f"抖音：{self._douyin_status.short_label()}"
                )
            else:
                self.dy_status_label.setText("抖音：未知（点击右上角刷新）")

        def _on_bilibili_qr_login(self) -> None:
            from ...ui.dialogs.login_dialog import build_bilibili_qr_dialog
            cls = build_bilibili_qr_dialog()
            dlg = cls(self.window())
            dlg.exec()
            asyncio.ensure_future(self._refresh_account_status_async())

        def _on_bilibili_import(self) -> None:
            src, _ = QFileDialog.getOpenFileName(
                self, "选择 B 站 Cookie 文件",
                str(Path.home() / ".doubi" / "cookies"),
                "Cookie 文件 (*.txt *.json);;全部 (*)",
            )
            if not src:
                return
            try:
                ok, msg = import_bilibili_cookies(Path(src))
            except Exception as exc:   # noqa: BLE001
                self._toast(False, "导入失败", str(exc))
                return
            self._toast(ok, "B 站 Cookie" if ok else "B 站 Cookie 失败", msg)
            asyncio.ensure_future(self._refresh_account_status_async())

        def _on_douyin_browser_login(self) -> None:
            from ...ui.dialogs.login_dialog import build_douyin_browser_dialog
            cls = build_douyin_browser_dialog()
            dlg = cls(self.window())
            dlg.exec()
            asyncio.ensure_future(self._refresh_account_status_async())

        def _on_douyin_import(self) -> None:
            src, _ = QFileDialog.getOpenFileName(
                self, "选择抖音 Cookie 文件",
                str(Path.home() / ".doubi" / "cookies"),
                "Cookie 文件 (*.txt *.json);;全部 (*)",
            )
            if not src:
                return
            try:
                ok, msg = import_douyin_cookies(Path(src))
            except Exception as exc:   # noqa: BLE001
                self._toast(False, "导入失败", str(exc))
                return
            self._toast(ok, "抖音 Cookie" if ok else "抖音 Cookie 失败", msg)
            asyncio.ensure_future(self._refresh_account_status_async())

        def _on_douyin_legacy_import(self) -> None:
            src, _ = QFileDialog.getOpenFileName(
                self, "选择 douyin-downloader cookies.json",
                str(Path.home()),
                "JSON 文件 (*.json);;全部 (*)",
            )
            if not src:
                return
            try:
                ok, msg = import_douyin_legacy_json(Path(src))
            except Exception as exc:   # noqa: BLE001
                self._toast(False, "导入失败", str(exc))
                return
            self._toast(ok, "抖音 legacy" if ok else "抖音 legacy 失败", msg)
            asyncio.ensure_future(self._refresh_account_status_async())

        def _toast(self, ok: bool, title: str, msg: str) -> None:
            kind = InfoBar.success if ok else InfoBar.error
            kind(
                title=title, content=msg, parent=self,
                position=InfoBarPosition.TOP, duration=4000,
            )

        # ----------------------------------------------------- save

        def _on_save(self) -> None:
            try:
                import yaml
            except ImportError:
                InfoBar.error(
                    title="无法保存",
                    content="缺少 pyyaml 依赖。",
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=3000,
                )
                return

            from dataclasses import asdict
            data = asdict(self._cfg)
            data["output_root"] = self.output_root.text().strip() or "./Downloaded"
            data["filename_template"] = self.filename_template.text() or "{title}_{item_id}"
            data["container"] = self.container.currentText()
            data["max_quality"] = self.max_quality.currentText()
            data["proxy"] = self.proxy.text().strip() or None
            try:
                data["concurrent_jobs"] = max(1, int(self.concurrent.text() or 3))
            except ValueError:
                data["concurrent_jobs"] = 3
            data["rate_limit"] = self.rate_limit.text().strip() or None
            data["database"] = self.database.isChecked()

            theme_text = self.theme.currentText()
            self._apply_theme(theme_text)

            cfg_path = Path.home() / ".doubi" / "config.yml"
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            with cfg_path.open("w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)

            InfoBar.success(
                title="设置已保存",
                content=f"已写入 {cfg_path}",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=3000,
            )
            logger.info("settings saved to %s", cfg_path)

        @staticmethod
        def _apply_theme(text: str) -> None:
            if text == "亮色":
                setTheme(Theme.LIGHT)
            elif text == "暗色":
                setTheme(Theme.DARK)
            # "自动" → leave to qfluentwidgets' system listener

        def _on_open_cookies_dir(self) -> None:
            cookies_dir = Path(self.cookies_dir_label.text())
            cookies_dir.mkdir(parents=True, exist_ok=True)
            try:
                if sys.platform.startswith("win"):
                    os.startfile(str(cookies_dir))   # type: ignore[attr-defined]
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", str(cookies_dir)])
                else:
                    subprocess.Popen(["xdg-open", str(cookies_dir)])
            except Exception as exc:   # noqa: BLE001
                logger.warning("open cookies dir failed: %s", exc)
                InfoBar.error(
                    title="打开失败",
                    content=f"请手动前往 {cookies_dir}。",
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=3000,
                )

    return SettingsPage, SettingsPage
