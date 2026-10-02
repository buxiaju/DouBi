"""Login dialogs — M6.25/M6.26 in-window login for B 站 and 抖音.

Two factories:

* :func:`build_bilibili_login_dialog` — opens a 2-tab dialog (M6.25) that:
    1. **Tab 1: 二维码** — pure-httpx QR login via
       :func:`bilibili_qr_login_image`. Renders a real ``QPixmap`` of
       the QR (not ASCII), polls for the user's app scan, and persists
       the cookies that B 站 issues in the same poll response.
       **No browser window is ever opened.**
    2. **Tab 2: 导入 Cookie** — read a Netscape-format cookies file
       exported by "Get cookies.txt LOCALLY" or any equivalent. Same
       escape hatch as M3.1.

* :func:`build_douyin_browser_dialog` — M6.26 reworked: launches
  Playwright with ``headless=True`` (default), takes a PNG screenshot
  of the QR element from the web login modal, and surfaces it in the
  dialog. The user never sees a Chromium window. A "显示浏览器"
  checkbox is provided as a one-click fallback to ``headless=False``
  if 抖音's web anti-bot rejects the headless session.

Why no "Account / SMS" tabs for B 站
------------------------------------
B 站's web login is gated by GeeTest (极验滑块) and the ``b_ret`` /
``b_wet`` device-fingerprint WASM. Neither can be synthesised from a
pure-httpx client. Earlier drafts proposed routing those flows through
``QWebEngineView`` but that would have re-added ~200 MB to the
PyInstaller onedir bundle (the same cost that justified removing
``QtWebEngine`` in 0.3.0; see ``docs/BUILD.md`` §4.5). QR + cookie
import covers >99 % of the real-world login cases for a desktop
download tool, so we ship those two tabs and document the gap here
rather than carrying ~200 MB for the long tail.

Both dialogs are :class:`QDialog` instances with a "关闭" button. The
顶部品牌 hero（小图标 + 应用名 + 平台标签）is shared between them via
``_build_brand_hero``.
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


# 注意：本模块顶层刻意不 import Qt（见文件头 docstring 的懒加载约定），
# 所有 QtWidgets 都在函数体内导入。因此下面这个返回值注解里的 ``QWidget``
# 在运行期不可解析——``ruff`` 会报 F821，但**不要**为此加顶层 Qt 导入：
# 那会破坏「无 Qt 环境也能 import 本模块」这一前提。
# 注解本身是字符串（``from __future__ import annotations``），永不求值，
# 只有显式 ``typing.get_type_hints()`` 才会碰到它，而本项目的调用方不做这件事。
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

    # ---- 应用图标：次级品牌标 ----
    app_icon = load_app_icon(32)
    if app_icon is not None and not app_icon.isNull():
        mark = QLabel()
        mark.setPixmap(app_icon.pixmap(32, 32))
        mark.setStyleSheet("QLabel { background: transparent; border: none; }")
        h.addWidget(mark, 0, Qt.AlignVCenter)

    return hero


# ---------------------------------------------------------------------------
# B 站登录（M6.25：2 Tab 统一对话框，QR 走纯 web API + 真实图片，备选「导入 Cookie」）
# ---------------------------------------------------------------------------


def build_bilibili_login_dialog():
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QFont, QImage, QPixmap
    from PySide6.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
        QFileDialog, QFrame, QSizePolicy,
    )

    from ...ui.auth_actions import (
        bilibili_qr_login_image,
        import_bilibili_cookies,
    )
    from ..i18n import tr
    from ..resources import load_app_icon
    from ..theme import muted_qss, token

    class BilibiliLoginDialog(QDialog):
        """M6.25 统一登录对话框（QR + 导入 Cookie）。

        QR tab 是主路径：纯 web API、零浏览器、QR 码渲染成真正的位图。
        导入 Cookie tab 是兜底，跟 M3.1 等价。
        """

        QR_PIXMAP_SIZE = 260   # 对话框内 QR 图标的最大边长

        def __init__(self, parent=None):
            super().__init__(parent)
            self.setWindowTitle(tr("login.bili.window_title"))
            icon = load_app_icon()
            if icon is not None and not icon.isNull():
                self.setWindowIcon(icon)
            self.resize(520, 600)
            self._qr_thread = None
            self._cancelled = False
            self._build_ui()
            # 打开后立即拉一张 QR；让用户几乎不感知等待
            QTimer.singleShot(60, self._start_qr_login)

        # ----------------------------------------------------- UI

        def _build_ui(self):
            outer = QVBoxLayout(self)
            outer.setContentsMargins(20, 20, 20, 20)
            outer.setSpacing(12)

            hero = _build_brand_hero("B 站", "#00aeec")
            if hero is not None:
                outer.addWidget(hero)

            # ---- 两个 Tab：二维码 / 导入 Cookie ----
            #
            # 用 ``SegmentedWidget``（顶栏导航）+ ``QStackedWidget``（内容
            # 区）联动，**不要**把 QFrame 传给 ``SegmentedWidget.addItem``
            # —— 它的签名是 ``addItem(routeKey: str, text: str, ...)``，
            # 传 QFrame 会被 Shiboken 拒绝并刷一排 "Cannot copy-convert
            # QFrame to C++"，实际效果是 Tab 1 内容(QR 标签所在的 QFrame)
            # 没被装进 widget tree，QR 图看不见。M6.29 fix。
            from PySide6.QtWidgets import QStackedWidget
            from qfluentwidgets import SegmentedWidget

            self.tabs = SegmentedWidget(self)
            self.tabs.addItem("qr", tr("login.bili.tab.qr"))
            self.tabs.addItem("import_cookie", tr("login.bili.tab.import_cookie"))
            self.tabs.setCurrentItem("qr")
            self.tabs.currentItemChanged.connect(self._on_tab_changed)
            outer.addWidget(self.tabs)

            self.qr_stack = QStackedWidget(self)
            outer.addWidget(self.qr_stack, 1)

            self.tab_qr = QFrame(self)
            self.tab_qr.setObjectName("biliTabQR")
            self.tab_import = QFrame(self)
            self.tab_import.setObjectName("biliTabImport")
            self.qr_stack.addWidget(self.tab_qr)   # index 0
            self.qr_stack.addWidget(self.tab_import)  # index 1

            # ---- 关闭按钮（两个 Tab 共用底部一行）----
            btn_row = QHBoxLayout()
            btn_row.addStretch(1)
            self.close_btn = QPushButton(tr("common.close"), self)
            self.close_btn.clicked.connect(self._on_close)
            btn_row.addWidget(self.close_btn)
            outer.addLayout(btn_row)

            self._build_qr_tab()
            self._build_import_tab()

        def _build_qr_tab(self):
            from PySide6.QtWidgets import QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QProgressBar

            page = QVBoxLayout(self.tab_qr)
            page.setContentsMargins(4, 8, 4, 4)
            page.setSpacing(8)

            hint = QLabel(
                tr("login.bili.qr.hint"),
                self,
            )
            hint.setStyleSheet(muted_qss())
            hint.setWordWrap(True)
            page.addWidget(hint)

            # QR image holder — 用 QLabel 配 QPixmap,自适应主题
            self.qr_image = QLabel(tr("login.bili.qr.generating"), self)
            self.qr_image.setAlignment(Qt.AlignCenter)
            self.qr_image.setMinimumHeight(self.QR_PIXMAP_SIZE + 24)
            self.qr_image.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.qr_image.setStyleSheet(
                f"QLabel {{"
                f" background: #ffffff;"
                f" border: 1px solid {token('divider')};"
                f" border-radius: 8px;"
                f" color: {token('text_muted')};"
                f" }}"
            )
            page.addWidget(self.qr_image, 0, Qt.AlignHCenter)

            self.qr_url = QLabel("", self)
            self.qr_url.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.qr_url.setWordWrap(True)
            self.qr_url.setStyleSheet(muted_qss())
            page.addWidget(self.qr_url)

            self.qr_progress = QProgressBar(self)
            self.qr_progress.setRange(0, 0)
            self.qr_progress.setTextVisible(False)
            self.qr_progress.setFixedHeight(4)
            page.addWidget(self.qr_progress)

            self.qr_status = QLabel(tr("login.bili.qr.preparing"), self)
            self.qr_status.setStyleSheet(muted_qss())
            self.qr_status.setWordWrap(True)
            page.addWidget(self.qr_status)

            row = QHBoxLayout()
            self.qr_refresh_btn = QPushButton(tr("login.bili.qr.refresh_button"), self)
            self.qr_refresh_btn.clicked.connect(self._start_qr_login)
            self.qr_copy_btn = QPushButton(tr("login.bili.qr.copy_button"), self)
            self.qr_copy_btn.clicked.connect(self._copy_qr_url)
            row.addWidget(self.qr_refresh_btn)
            row.addWidget(self.qr_copy_btn)
            row.addStretch(1)
            page.addLayout(row)

        def _build_import_tab(self):
            from PySide6.QtWidgets import QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QFileDialog

            page = QVBoxLayout(self.tab_import)
            page.setContentsMargins(4, 8, 4, 4)
            page.setSpacing(8)

            title = QLabel(tr("login.bili.import.title"), self)
            f = title.font()
            f.setBold(True)
            title.setFont(f)
            page.addWidget(title)

            hint = QLabel(
                tr("login.bili.import.hint"),
                self,
            )
            hint.setStyleSheet(muted_qss())
            hint.setWordWrap(True)
            page.addWidget(hint)

            row = QHBoxLayout()
            self.import_pick_btn = QPushButton(tr("login.bili.import.pick_button"), self)
            self.import_pick_btn.clicked.connect(self._pick_cookie_file)
            self.import_path_label = QLabel(tr("login.bili.import.placeholder"), self)
            self.import_path_label.setStyleSheet(muted_qss())
            self.import_path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            row.addWidget(self.import_pick_btn)
            row.addWidget(self.import_path_label, 1)
            page.addLayout(row)

            self.import_btn = QPushButton(tr("login.bili.import.confirm_button"), self)
            self.import_btn.setEnabled(False)
            self.import_btn.clicked.connect(self._do_import)
            page.addWidget(self.import_btn, 0, Qt.AlignRight)

            self.import_status = QLabel("", self)
            self.import_status.setStyleSheet(muted_qss())
            self.import_status.setWordWrap(True)
            page.addWidget(self.import_status, 1)

        # ----------------------------------------------------- 事件

        def _on_tab_changed(self, key: str) -> None:
            # M6.29: 真正驱动 QStackedWidget 切到对应 tab 页面。
            # 之前是空钩子 → SegmentedWidget 切了但 stacked 没动,用户
            # 只看到默认显示的 Tab 1,切 Tab 2 无反应。
            index_map = {"qr": 0, "import_cookie": 1}
            idx = index_map.get(key, 0)
            if self.qr_stack.currentIndex() != idx:
                self.qr_stack.setCurrentIndex(idx)

        def _on_close(self) -> None:
            self._cancelled = True
            # 子线程是 daemon=True 跟着主进程退出，不必显式 join
            self.reject()

        def closeEvent(self, ev) -> None:
            self._cancelled = True
            super().closeEvent(ev)

        # ----------------------------------------------------- QR 流程

        def _start_qr_login(self) -> None:
            if self._cancelled:
                return
            self.qr_refresh_btn.setEnabled(False)
            self.qr_image.setText(tr("login.bili.qr.generating"))
            self.qr_image.setPixmap(QPixmap())
            self.qr_url.setText("")
            self.qr_status.setText(tr("login.bili.qr.preparing"))
            self.qr_status.setStyleSheet(muted_qss())
            self.qr_progress.show()

            # M6.31: on_qr_ready 接 PNG bytes(跟抖音 dialog 一致)。
            # Playwright headless 跑 URLChangeLogin,登录页加载
            # 之后 _qr_snapshot 截 QR 元素 → bytes → on_qr_ready。
            def _on_qr_ready(png_bytes: bytes) -> None:
                if self._cancelled or not self.isVisible():
                    return
                try:
                    qimg = QImage.fromData(png_bytes, "PNG")
                    if qimg.isNull():
                        raise RuntimeError("QImage.fromData returned null")
                    pix = QPixmap.fromImage(qimg)
                except Exception as exc:   # noqa: BLE001
                    logger.exception("渲染 B 站二维码失败")
                    self.qr_image.setText(tr("login.bili.qr.render_fail", error=exc))
                    return
                scaled = pix.scaled(
                    self.QR_PIXMAP_SIZE, self.QR_PIXMAP_SIZE,
                    Qt.KeepAspectRatio, Qt.SmoothTransformation,
                )
                self.qr_image.setPixmap(scaled)
                self.qr_status.setText(tr("login.bili.qr.waiting_scan"))

            # M6.31: status 现在是字符串而不是 PollResult。
            # Playwright 路径能给的信号是:
            #   "starting_browser" / "timeout" / "failed" / "done" / "unknown"
            def _on_status(status: str) -> None:
                if self._cancelled or not self.isVisible():
                    return
                if status == "starting_browser":
                    self.qr_status.setText(tr("login.bili.qr.starting_browser"))
                else:
                    # "timeout" / "failed" / "done" / "unknown" 都不需要更新
                    # QR 区域(它已经在那里了),直接 pass。
                    pass

            def _on_done(path, error) -> None:
                self.qr_progress.hide()
                self.qr_refresh_btn.setEnabled(True)
                if error is not None:
                    self._set_qr_status(tr("login.bili.qr.fail_prefix", error=error), error=True)
                    return
                self._set_qr_status(tr("login.bili.qr.success_path", path=path))
                self._refresh_parent_status()
                # 让用户看到成功提示再自动关
                QTimer.singleShot(900, self.accept)

            self._qr_thread = bilibili_qr_login_image(
                max_wait=180.0,
                on_qr_ready=_on_qr_ready,
                on_status=_on_status,
                on_done=_on_done,
            )

        def _set_qr_status(self, text: str, *, error: bool = False) -> None:
            color = token("progress_error") if error else token("text_muted")
            self.qr_status.setStyleSheet(f"color: {color};")
            self.qr_status.setText(text)

        def _copy_qr_url(self) -> None:
            from PySide6.QtWidgets import QApplication
            text = self.qr_url.text()
            if text:
                # 取第一行（"或浏览器打开:xxx"）的真实 URL
                for line in text.splitlines():
                    if line.startswith("或浏览器打开:"):
                        QApplication.clipboard().setText(line.split(":", 1)[1].strip())
                        return

        # ----------------------------------------------------- 导入 Cookie 流程

        def _pick_cookie_file(self) -> None:
            path, _ = QFileDialog.getOpenFileName(
                self,
                "选择 Cookie 文件",
                "",
                "Cookie 文件 (*.txt *.json);;所有文件 (*.*)",
            )
            if not path:
                return
            self._import_path = Path(path)
            self.import_path_label.setText(str(self._import_path))
            self.import_btn.setEnabled(True)

        def _do_import(self) -> None:
            if not getattr(self, "_import_path", None):
                return
            ok, msg = import_bilibili_cookies(self._import_path)
            color = token("progress_error") if not ok else token("text_muted")
            self.import_status.setStyleSheet(f"color: {color};")
            self.import_status.setText(msg)
            if ok:
                self._refresh_parent_status()
                QTimer.singleShot(900, self.accept)

        # ----------------------------------------------------- 通用

        def _refresh_parent_status(self) -> None:
            """登录成功时,刷新设置页的「当前账号」标签。"""
            try:
                from ...ui.pages.settings import _refresh_account_status_external
                _refresh_account_status_external(self.parent())
            except Exception:   # noqa: BLE001
                logger.debug("status refresh callback missing", exc_info=True)

    return BilibiliLoginDialog


# ---------------------------------------------------------------------------
# 抖音 — M6.26 Playwright headless + 扒图
# ---------------------------------------------------------------------------


def build_douyin_browser_dialog():
    """M6.26 抖音扫码登录对话框 —— Playwright 跑在后台，**用户只看到窗口内的二维码图**。

    实现要点：

    1. ``douyin_login_via_browser(headless=True, on_qr_image=...)`` 启动
       无头 Chromium，登录页加载后 ``_qr_snapshot`` 通过几组候选
       选择器把 QR 元素截成 PNG bytes。
    2. bytes 推回主线程 → ``QImage`` → ``QPixmap`` → 居中显示。
    3. 后台 Playwright 继续等 ``sessionid / sessionid_ss / sid_guard``
       出现，捕获到即写 cookie 文件。
    4. 「**显示浏览器**」复选框:抖音 web 端在 headless 模式下**有
       概率被反爬**(canvas / webdriver 检测,我们的嗅探链路已经踩过
       类似的坑)。勾选后会以 ``headless=False`` 重启,会弹独立
       Chromium 窗口。**默认未勾选**(用户看不到浏览器)。
    5. 抖音 web 端对 a_bogus 设备指纹和 GeeTest 滑块非常严,本流程
       不在内部解决这些——我们把"扫码"这一步替到我们的窗口里,但
       登录态仍然由抖音自己的 web 端处理。
    """
    from PySide6.QtCore import Qt, QEvent, QTimer, QSettings
    from PySide6.QtGui import QImage, QPixmap
    from PySide6.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
        QProgressBar, QCheckBox,
    )

    from ...ui.auth_actions import douyin_login_via_browser
    from ...platforms.douyin import auth as dy_auth
    from ..i18n import tr
    from ..resources import load_app_icon
    from ..theme import muted_qss, token

    class _DyQRImageEvent(QEvent):
        event_type = QEvent.Type(QEvent.registerEventType())

        def __init__(self, png_bytes: bytes):
            super().__init__(self.event_type)
            self.png_bytes = png_bytes

    class _DyDoneEvent(QEvent):
        event_type = QEvent.Type(QEvent.registerEventType())

        def __init__(self, cookies, error):
            super().__init__(self.event_type)
            self.cookies = cookies
            self.error = error

    class DouyinBrowserDialog(QDialog):
        QR_PIXMAP_SIZE = 260

        def __init__(self, parent=None):
            super().__init__(parent)
            self.setWindowTitle(tr("login.dy.window_title"))
            icon = load_app_icon()
            if icon is not None and not icon.isNull():
                self.setWindowIcon(icon)
            self.resize(560, 600)
            self._thread = None
            self._cancelled = False
            self._build_ui()
            QTimer.singleShot(60, self._start)

        def _build_ui(self):
            outer = QVBoxLayout(self)
            outer.setContentsMargins(20, 20, 20, 20)
            outer.setSpacing(10)

            hero = _build_brand_hero("抖音", "#fe2c55")
            if hero is not None:
                outer.addWidget(hero)

            hint = QLabel(
                tr("login.dy.hint"),
                self,
            )
            hint.setStyleSheet(muted_qss())
            hint.setWordWrap(True)
            outer.addWidget(hint)

            # QR image holder — same style as B 站 dialog
            self.qr_image = QLabel(tr("login.dy.qr.loading"), self)
            self.qr_image.setAlignment(Qt.AlignCenter)
            self.qr_image.setMinimumHeight(self.QR_PIXMAP_SIZE + 24)
            self.qr_image.setStyleSheet(
                f"QLabel {{"
                f" background: #ffffff;"
                f" border: 1px solid {token('divider')};"
                f" border-radius: 8px;"
                f" color: {token('text_muted')};"
                f" }}"
            )
            outer.addWidget(self.qr_image, 0, Qt.AlignHCenter)

            self.progress = QProgressBar(self)
            self.progress.setRange(0, 0)
            self.progress.setTextVisible(False)
            self.progress.setFixedHeight(4)
            outer.addWidget(self.progress)

            self.status_label = QLabel(tr("login.dy.status.starting"), self)
            self.status_label.setStyleSheet(muted_qss())
            self.status_label.setWordWrap(True)
            outer.addWidget(self.status_label)

            # 「显示浏览器」降级开关
            # M6.37: 抖音 web 端 2026 反爬升级,headless 模式必被
            # 字节系 verify captcha 弹到中继页,无 QR 可截。**抖音
            # 必须 headed** —— 默认勾上 headed_checkbox,开 dialog
            # 就直接 headed + 自动 click "扫码登录" 按钮(M6.37
            # pre_login_hook)。B 站保持 headless 默认 unchecked。
            # M6.41: 持久化 headed 状态到 QSettings(用 setApplicationName
            # + setOrganizationName 落 Windows 注册表 / 其他平台对应位置),
            # 关 dialog 后下次打开还是勾选/未勾选,不用每次重设。
            self.headed_checkbox = QCheckBox(tr("login.dy.checkbox.headed"), self)
            # 读 QSettings,没存过则默认 True(M6.37 决定)
            _settings = QSettings()
            _initial_headed = _settings.value(
                "login.dy.headed_checkbox", True, type=bool,
            )
            self.headed_checkbox.setChecked(_initial_headed)
            self.headed_checkbox.setToolTip(tr("login.dy.checkbox.headed_tooltip"))
            outer.addWidget(self.headed_checkbox)

            btn_row = QHBoxLayout()
            btn_row.addStretch(1)
            self.close_btn = QPushButton(tr("common.close"), self)
            self.close_btn.clicked.connect(self._on_close)
            btn_row.addWidget(self.close_btn)
            outer.addLayout(btn_row)
            # M6.42: keep a reference so ``_offer_sms_verify`` can
            # insert the "continue verification" button before the
            # close button.
            self._btn_row = btn_row

        def _start(self) -> None:
            if self._cancelled:
                return
            self.qr_image.setText(tr("login.dy.qr.loading"))
            self.qr_image.setPixmap(QPixmap())
            self._set_status(tr("login.dy.status.starting_headless"))
            self.progress.show()

            def _on_qr_image(png_bytes: bytes) -> None:
                from PySide6.QtWidgets import QApplication
                QApplication.instance().postEvent(
                    self, _DyQRImageEvent(png_bytes),
                )

            def _on_done(cookies, error) -> None:
                from PySide6.QtWidgets import QApplication
                QApplication.instance().postEvent(
                    self, _DyDoneEvent(cookies, error),
                )

            self._thread = douyin_login_via_browser(
                headless=not self.headed_checkbox.isChecked(),
                timeout=180.0,
                on_qr_image=_on_qr_image,
                on_done=_on_done,
            )

        def event(self, ev) -> bool:
            if ev.type() == _DyQRImageEvent.event_type:
                self._on_qr_image(ev.png_bytes)
                return True
            if ev.type() == _DyDoneEvent.event_type:
                self._on_done(ev.cookies, ev.error)
                return True
            return super().event(ev)

        def _on_qr_image(self, png_bytes: bytes) -> None:
            qimg = QImage.fromData(png_bytes, "PNG")
            if qimg.isNull():
                # Should not normally happen — ``_qr_snapshot`` already
                # takes a viewport screenshot if no selector matches.
                self.qr_image.setText(tr("login.dy.qr.screenshot_decode_fail"))
                return
            pix = QPixmap.fromImage(qimg)
            scaled = pix.scaled(
                self.QR_PIXMAP_SIZE, self.QR_PIXMAP_SIZE,
                Qt.KeepAspectRatio, Qt.SmoothTransformation,
            )
            self.qr_image.setPixmap(scaled)
            self._set_status(tr("login.dy.status.qr_ready"))
            # 取消 indeterminate progress bar — 扫码阶段是「等用户操作」,不再是「正在加载」
            self.progress.setRange(0, 1)
            self.progress.setValue(0)

        def _on_done(
            self, cookies: Optional[list[dict]], error: Optional[Exception],
        ) -> None:
            self.progress.hide()
            if error is not None:
                self._set_status(
                    tr("login.dy.fail_with_hint", error=error),
                    error=True,
                )
                return
            # M6.35: write_netscape_cookies 签名是 (cookies, path=None) -> Path,
            # 不返回 (ok, msg) tuple。失败时直接 raise,所以 try/except 包一层。
            try:
                dy_auth.write_netscape_cookies(
                    cookies or [], path=dy_auth.default_cookie_path()
                )
            except Exception as exc:   # noqa: BLE001
                self._set_status(
                    tr("login.dy.fail_with_hint", error=exc), error=True,
                )
                return
            self._set_status(tr("login.dy.success"))
            # M6.42: re-validate cookies to surface ``need_sms_verify``
            # — if the user has scanned the QR but the platform
            # demands phone second-factor, we offer the SMS dialog
            # before closing the login dialog. Without this, the
            # session is half-broken and downloads will fail.
            try:
                info = dy_auth.login_info_from_cookies_sync(
                    dy_auth.default_cookie_path(),
                )
            except Exception:  # noqa: BLE001
                info = None
            if info is not None and info.need_sms_verify:
                self._offer_sms_verify()
                return
            self._refresh_parent_status()
            QTimer.singleShot(800, self.accept)

        def _offer_sms_verify(self) -> None:
            """M6.42: user has scanned QR but Douyin wants phone SMS.

            We show the hint + a "继续验证" button that opens the
            :class:`SmsVerifyDialog`. If verification succeeds, we
            close the login dialog (cookies are refreshed). If it
            fails, the user can retry from inside the SMS dialog
            without re-doing the QR scan.
            """
            from .sms_verify_dialog import SmsVerifyDialog

            self._set_status(tr("login.dy.need_sms_verify"))
            self._sms_btn = QPushButton(
                tr("login.dy.need_sms_verify_btn"), self,
            )
            self._sms_btn.clicked.connect(self._launch_sms_dialog)
            # Insert before the existing close button so the user
            # sees the "continue" call-to-action.
            self._btn_row.insertWidget(0, self._sms_btn)

        def _launch_sms_dialog(self) -> None:
            from .sms_verify_dialog import SmsVerifyDialog

            dlg = SmsVerifyDialog(
                cookies_file=dy_auth.default_cookie_path(),
                parent=self,
            )
            if dlg.exec() == QDialog.Accepted:
                # SMS verify succeeded — close the login dialog.
                self._refresh_parent_status()
                self.accept()

        def _set_status(self, text: str, *, error: bool = False) -> None:
            color = token("progress_error") if error else token("text_muted")
            self.status_label.setStyleSheet(f"color: {color};")
            self.status_label.setText(text)

        def _on_close(self) -> None:
            self._cancelled = True
            self.reject()

        def closeEvent(self, ev) -> None:
            # M6.41: persist headed_checkbox state to QSettings so the
            # next dialog open inherits the user's last choice. Don't
            # fail the close if QSettings write fails (e.g. read-only
            # filesystem in portable mode) — silently log + continue.
            try:
                _settings = QSettings()
                _settings.setValue(
                    "login.dy.headed_checkbox",
                    self.headed_checkbox.isChecked(),
                )
                _settings.sync()  # force-write so subsequent reads see it
            except Exception:  # noqa: BLE001
                logger.exception("M6.41: failed to persist headed_checkbox state")
            self._cancelled = True
            super().closeEvent(ev)

        def _refresh_parent_status(self) -> None:
            try:
                from ...ui.pages.settings import _refresh_account_status_external
                _refresh_account_status_external(self.parent())
            except Exception:   # noqa: BLE001
                logger.debug("status refresh callback missing", exc_info=True)

    return DouyinBrowserDialog
