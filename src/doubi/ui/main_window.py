"""Main window — the qfluentwidgets FluentWindow shell.

M5.1 adds a theme toggle button (light / dark / auto cycle) in the
navigation bar, plus proper page titles.

M5.4 splits the previous single "下载" page into two: **解析** (the
default landing page) and **下载** (the task manager). Both share a
single :class:`TaskManager` instance owned by the main window.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("doubi.ui.main_window")


def build_main_window():
    """Return a factory that constructs the :class:`MainWindow` QWidget."""
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QIcon, QAction
    from PySide6.QtWidgets import QApplication
    from qfluentwidgets import (
        MSFluentWindow, NavigationItemPosition, FluentIcon, setTheme, Theme,
        isDarkTheme, NavigationToolButton, InfoBar, InfoBarPosition,
    )

    from .pages import (
        build_download_widgets, build_history_widgets,
        build_parse_widgets, build_settings_widgets,
    )
    from .task_manager import TaskManager
    from ..core.engine_loader import build_default_pipeline

    ParsePage, _ = build_parse_widgets()
    DownloadPage, _ = build_download_widgets()
    HistoryPage, _ = build_history_widgets()
    SettingsPage, _ = build_settings_widgets()

    class MainWindow(MSFluentWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("DouBi")
            self.resize(1024, 720)
            self.setMinimumSize(760, 540)

            # The shared task manager. Both ParsePage and DownloadPage
            # depend on this — it must be created first.
            self.task_manager = TaskManager(build_default_pipeline(), parent=self)

            # ---- 解析 (default landing) -----------------------------
            self.parse_interface = ParsePage(self)
            self.parse_interface.setObjectName("parseInterface")
            self.addSubInterface(
                self.parse_interface,
                FluentIcon.SEARCH,
                "解析",
                position=NavigationItemPosition.TOP,
            )
            self.parse_interface.set_task_manager(self.task_manager)

            # ---- 下载 (task manager) --------------------------------
            self.download_interface = DownloadPage(self)
            self.download_interface.setObjectName("downloadInterface")
            self.addSubInterface(
                self.download_interface,
                FluentIcon.DOWNLOAD,
                "下载",
                position=NavigationItemPosition.TOP,
            )
            self.download_interface.set_task_manager(self.task_manager)

            # ---- 历史 -----------------------------------------------
            self.history_interface = HistoryPage(self)
            self.history_interface.setObjectName("historyInterface")
            self.addSubInterface(
                self.history_interface,
                FluentIcon.HISTORY,
                "历史",
                position=NavigationItemPosition.TOP,
            )

            # ---- 设置 -----------------------------------------------
            self.settings_interface = SettingsPage(self)
            self.settings_interface.setObjectName("settingsInterface")
            self.addSubInterface(
                self.settings_interface,
                FluentIcon.SETTING,
                "设置",
                position=NavigationItemPosition.BOTTOM,
            )

            # Theme toggle button pinned to the bottom of the nav bar
            self.theme_toggle = NavigationToolButton(FluentIcon.BRUSH)
            self.theme_toggle.setToolTip("切换主题（亮 / 暗 / 自动）")
            self.theme_toggle.clicked.connect(self._cycle_theme)
            self.navigationInterface.addWidget(
                routeKey="themeToggle",
                widget=self.theme_toggle,
                onClick=self._cycle_theme,
                position=NavigationItemPosition.BOTTOM,
            )

            # Default to the parse page (Bili23 style)
            self.stackedWidget.setCurrentWidget(self.parse_interface)
            self.navigationInterface.setCurrentItem(
                self.parse_interface.objectName()
            )

        def _cycle_theme(self) -> None:
            """Cycle: dark → light → auto (→ dark …)."""
            from qfluentwidgets import setThemeColor
            current = Theme.DARK if isDarkTheme() else Theme.LIGHT
            if hasattr(self.settings_interface, "theme"):
                combo = self.settings_interface.theme
                text = combo.currentText()
                if text == "自动":
                    next_text = "暗色"
                elif text == "暗色":
                    next_text = "亮色"
                else:
                    next_text = "自动"
                combo.setCurrentText(next_text)
                self.settings_interface._apply_theme(next_text)
                return
            if current is Theme.DARK:
                setTheme(Theme.LIGHT)
            else:
                setTheme(Theme.DARK)

    return MainWindow
