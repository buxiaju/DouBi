"""Main window — the qfluentwidgets FluentWindow shell.

M5.1 adds a theme toggle button in the navigation bar, plus proper
page titles. The toggle cycles through the built-in theme packs
(see :mod:`doubi.ui.theme`).

M5.4 splits the previous single "下载" page into two: **解析** (the
default landing page) and **下载** (the task manager). Both share a
single :class:`TaskManager` instance owned by the main window.

M6.x 重做品牌与窗体：标题、图标、底栏「关于」按钮，所有页面共享一套
页头 / 空态组件（见 :mod:`doubi.ui.widgets`）。
"""

from __future__ import annotations

import logging

logger = logging.getLogger("doubi.ui.main_window")

#: 自绘标题栏里应用图标的边长。标题栏固定 48px 高，28px 图标上下各留 10px，
#: 视觉重量合适；qfluentwidgets 默认的 18px 在这个高度里明显偏小。
TITLEBAR_ICON_SIZE = 28


def build_main_window():
    """Return a factory that constructs the :class:`MainWindow` QWidget."""
    from PySide6.QtCore import Qt, QSize
    from PySide6.QtGui import QAction, QIcon
    from PySide6.QtWidgets import QApplication
    from qfluentwidgets import (
        MSFluentWindow, NavigationItemPosition, FluentIcon,
        NavigationToolButton, InfoBar, InfoBarPosition,
    )

    from .pages import (
        build_download_widgets, build_history_widgets,
        build_parse_widgets, build_settings_widgets,
    )
    from .resources import APP_DISPLAY_NAME, APP_NAME, APP_VERSION, load_app_icon
    from .theme import (
        FONT_FAMILY, TYPE_BODY, current_theme_name, set_theme, subscribe_theme,
        theme_names, muted_qss,
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
            # 窗口标题：应用名 · 版本 + 一个可读的副标题
            self.setWindowTitle(
                f"{APP_DISPLAY_NAME} {APP_VERSION}  ·  多平台视频下载器"
            )
            self.resize(1100, 760)
            self.setMinimumSize(820, 580)

            # 应用图标：主窗口的窗口图标、任务栏图标都跟 app.setWindowIcon 走
            self._refresh_app_icon()
            # qfluentwidgets 把标题栏图标写死成 18px，太小，先放大
            self._enlarge_titlebar_icon(TITLEBAR_ICON_SIZE)
            # 图标底板配色取自主题主色，切主题时要重新渲染
            subscribe_theme(self, self._refresh_app_icon)

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

            # 主题循环按钮固定在导航栏底部
            self.theme_toggle = NavigationToolButton(FluentIcon.BRUSH)
            self.theme_toggle.setToolTip("切换主题（在内置主题包之间循环）")
            self.navigationInterface.addWidget(
                routeKey="themeToggle",
                widget=self.theme_toggle,
                onClick=self._cycle_theme,
                position=NavigationItemPosition.BOTTOM,
            )

            # 关于按钮同样放底部——比「帮助」更准确
            self.about_btn = NavigationToolButton(FluentIcon.INFO)
            self.about_btn.setToolTip("关于")
            self.navigationInterface.addWidget(
                routeKey="about",
                widget=self.about_btn,
                onClick=self._show_about,
                position=NavigationItemPosition.BOTTOM,
            )

            # Default to the parse page (Bili23 style)
            self.stackedWidget.setCurrentWidget(self.parse_interface)
            self.navigationInterface.setCurrentItem(
                self.parse_interface.objectName()
            )

        def _enlarge_titlebar_icon(self, size: int = TITLEBAR_ICON_SIZE) -> None:
            """放大自绘标题栏里的应用图标。

            ``qfluentwidgets.FluentTitleBar`` 把图标写死成 18×18
            （``iconLabel.setFixedSize(18, 18)`` + ``setIcon`` 里
            ``pixmap(18, 18)``），在 48px 高的标题栏里明显偏小。

            光改 ``iconLabel`` 尺寸不够：``__init__`` 里已经把
            ``windowIconChanged`` 连到了原始 ``setIcon`` 上，下一次换主题
            触发信号就会把放大后的 pixmap 覆盖回 18px。所以要先断开旧连接、
            按实例覆写 ``setIcon``、再接上新的。

            整个过程对 qfluentwidgets 的内部结构有依赖，因此全程防御性处理：
            拿不到 ``iconLabel`` 就直接放弃，不影响窗口正常工作。
            """
            title_bar = getattr(self, "titleBar", None)
            label = getattr(title_bar, "iconLabel", None)
            if title_bar is None or label is None:
                return

            label.setFixedSize(size, size)

            def set_icon(icon, _label=label, _size=size) -> None:
                _label.setPixmap(QIcon(icon).pixmap(_size, _size))

            try:
                self.windowIconChanged.disconnect(title_bar.setIcon)
            except (TypeError, RuntimeError):
                # 未连接 / 已析构：忽略，后面照样接上新的
                pass
            title_bar.setIcon = set_icon
            self.windowIconChanged.connect(set_icon)
            set_icon(self.windowIcon())

        def _refresh_app_icon(self) -> None:
            """按当前主题重新渲染并挂上应用图标。

            两处都要设：``QApplication`` 级图标决定任务栏 / Alt+Tab 的表现，
            窗口级图标决定标题栏。只改后者的话任务栏会残留旧配色。
            """
            icon = load_app_icon()
            if icon is None:
                return
            self.setWindowIcon(icon)
            app = QApplication.instance()
            if app is not None:
                app.setWindowIcon(icon)

        def _cycle_theme(self) -> None:
            """在内置主题包之间循环切换。

            只调用 :func:`set_theme`，设置页的下拉框通过订阅主题信号
            自行同步——主窗口不再伸手进别的页面调私有方法。
            """
            names = theme_names()
            if not names:
                return
            try:
                idx = names.index(current_theme_name())
            except ValueError:
                idx = -1
            pack = set_theme(names[(idx + 1) % len(names)])
            InfoBar.success(
                title="已切换主题",
                content=f"{pack.label}",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=1500,
            )

        def _show_about(self) -> None:
            from .dialogs.about_dialog import build_about_dialog
            cls = build_about_dialog()
            dlg = cls(self.window())
            dlg.exec()

    return MainWindow
