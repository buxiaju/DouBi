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

import asyncio
import logging

logger = logging.getLogger("doubi.ui.main_window")

#: 自绘标题栏里应用图标的边长。标题栏固定 48px 高，28px 图标上下各留 10px，
#: 视觉重量合适；qfluentwidgets 默认的 18px 在这个高度里明显偏小。
TITLEBAR_ICON_SIZE = 28

#: 关窗时等待落库写入的上限（毫秒）。这是 ``flush_pending_writes`` 自身超时
#: 之外的第二道保险，比它留得宽一点，好让正常路径由内层超时收尾、这一层只在
#: 内层也失灵时兜底。取值要够短，卡住的磁盘不该让用户以为程序死了。
CLOSE_FLUSH_TIMEOUT_MS = 5000


def build_main_window():
    """Return a factory that constructs the :class:`MainWindow` QWidget."""
    from PySide6.QtCore import QEventLoop as QtEventLoop
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication
    from qfluentwidgets import (
        FluentIcon,
        InfoBar,
        InfoBarPosition,
        MessageBox,
        MSFluentWindow,
        NavigationItemPosition,
        NavigationToolButton,
    )

    from ..core.engine_loader import build_default_pipeline
    from .i18n import tr
    from .pages import (
        build_download_widgets,
        build_history_widgets,
        build_parse_widgets,
        build_settings_widgets,
    )
    from .resources import APP_DISPLAY_NAME, APP_VERSION, load_app_icon
    from .task_manager import TaskManager
    from .theme import (
        current_theme_name,
        set_theme,
        subscribe_theme,
        theme_names,
    )

    ParsePage, _ = build_parse_widgets()
    DownloadPage, _ = build_download_widgets()
    HistoryPage, _ = build_history_widgets()
    SettingsPage, _ = build_settings_widgets()

    class MainWindow(MSFluentWindow):
        def __init__(self):
            super().__init__()
            # 窗口标题：应用名 · 版本 + 一个可读的副标题
            self.setWindowTitle(
                f"{APP_DISPLAY_NAME} {APP_VERSION}  ·  {tr('app.title_suffix')}"
            )
            self.resize(1100, 760)
            self.setMinimumSize(820, 580)
            # 居中到主屏幕（多屏时取屏幕 0 可用矩形的中心）。
            self._center_on_screen()

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
                tr("nav.parse"),
                position=NavigationItemPosition.TOP,
            )
            self.parse_interface.set_task_manager(self.task_manager)

            # ---- 下载 (task manager) --------------------------------
            self.download_interface = DownloadPage(self)
            self.download_interface.setObjectName("downloadInterface")
            self.addSubInterface(
                self.download_interface,
                FluentIcon.DOWNLOAD,
                tr("nav.download"),
                position=NavigationItemPosition.TOP,
            )
            self.download_interface.set_task_manager(self.task_manager)

            # ---- 历史 -----------------------------------------------
            self.history_interface = HistoryPage(self)
            self.history_interface.setObjectName("historyInterface")
            self.addSubInterface(
                self.history_interface,
                FluentIcon.HISTORY,
                tr("nav.history"),
                position=NavigationItemPosition.TOP,
            )
            # 历史页「重新解析」：把 URL 填入解析页输入框并跳转过去
            self.history_interface.set_reparse_callback(self._reparse_from_history)

            # ---- 设置 -----------------------------------------------
            self.settings_interface = SettingsPage(self)
            self.settings_interface.setObjectName("settingsInterface")
            self.addSubInterface(
                self.settings_interface,
                FluentIcon.SETTING,
                tr("nav.settings"),
                position=NavigationItemPosition.BOTTOM,
            )
            # 把 GUI 偏好推到解析页：启动时一次性下发，之后设置页切换会
            # 通过 promptBeforeDownloadChanged 信号再次下发，实时生效。
            self.parse_interface.set_prompt_before_download(
                self.settings_interface._cfg.prompt_before_download
            )
            self.settings_interface.promptBeforeDownloadChanged.connect(
                self.parse_interface.set_prompt_before_download
            )

            # 主题循环按钮固定在导航栏底部
            self.theme_toggle = NavigationToolButton(FluentIcon.BRUSH)
            self.theme_toggle.setToolTip(tr("nav.theme_tooltip"))
            self.navigationInterface.addWidget(
                routeKey="themeToggle",
                widget=self.theme_toggle,
                onClick=self._cycle_theme,
                position=NavigationItemPosition.BOTTOM,
            )

            # 关于按钮同样放底部——比「帮助」更准确
            self.about_btn = NavigationToolButton(FluentIcon.INFO)
            self.about_btn.setToolTip(tr("nav.about_tooltip"))
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

            # 上次退出时还没下完的任务：问一句要不要接着下。
            # 排在最后，因为它要用到 parse_interface 的配置和已经建好的
            # 下载页——单次射击的定时器把它推到事件循环的下一轮，让窗口
            # 先画出来，否则对话框会弹在一片空白上。
            QTimer.singleShot(0, self._offer_restore)

        # ---- 跨进程断点续传 -------------------------------------------

        def _offer_restore(self) -> None:
            """询问是否恢复上次未完成的任务。

            整个流程都是尽力而为：拿不到**正在运行的**事件循环（
            ``--no-event-loop`` 模式、以及直接构造窗口的 GUI 测试）就
            安静跳过。这里刻意不用 ``get_event_loop()``：那个函数在没有
            循环时会自己造一个（3.12 起还带弃用告警），而一个没人 run
            的循环上 ``create_task`` 出来的协程永远不会被执行——看着成功，
            实际什么都没发生。``get_running_loop()`` 问的正是我要的问题。

            启动路径上的任何异常都不该拦住用户打开应用——恢复是锦上添花，
            开不了窗才是故障。
            """
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return
            task = loop.create_task(self._restore_flow())
            # asyncio 只持弱引用，不留着会被中途回收。
            self._restore_task = task

        async def _restore_flow(self) -> None:
            options = self.parse_interface.current_options()
            db_path = options.database
            rows = await self.task_manager.list_restorable(db_path)
            if not rows:
                return

            titles = [
                (getattr(r, "title", "") or getattr(r, "item_id", "") or "?")
                for r in rows[:5]
            ]
            listing = "\n".join(f"  · {t}" for t in titles)
            if len(rows) > len(titles):
                listing += f"\n  … 另有 {len(rows) - len(titles)} 个"
            box = MessageBox(
                "恢复上次的下载？",
                f"上次退出时有 {len(rows)} 个任务没有下完：\n{listing}\n\n"
                "恢复后它们会以「已暂停」出现在下载页，"
                "点继续即可从断点接着下。\n"
                "选择「不恢复」会清掉这些记录，已下载的文件片段仍留在硬盘上。",
                self.window(),
            )
            box.yesButton.setText("恢复")
            box.cancelButton.setText("不恢复")
            if not box.exec():
                # 「不恢复」必须落库，否则下次启动还会问同一批任务。
                self.task_manager.discard_restorable(rows, db_path)
                return

            restored = self.task_manager.restore(rows, options)
            if not restored:
                return
            self.stackedWidget.setCurrentWidget(self.download_interface)
            self.navigationInterface.setCurrentItem(
                self.download_interface.objectName()
            )
            InfoBar.success(
                title="已恢复",
                content=f"{len(restored)} 个任务已暂停待续",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=4000,
            )

        def closeEvent(self, event) -> None:
            """关窗前把还在飞的落库写等回来。

            状态变更的写入是故意「发射后不管」的——运行期任何一次暂停都
            不该卡在磁盘 I/O 上。但关窗时这个取舍要反过来：循环一关，
            还排在队里的写就静静丢了，而丢掉的恰恰是用户临走前那几次
            操作，也正是下次启动要靠它来提供恢复的那批记录。

            这里**不能**用 ``run_until_complete``：``closeEvent`` 是同步的
            Qt 回调，而此刻 qasync 的循环正在跑，往运行中的循环上再调一次
            run 只会抛 ``RuntimeError``——被兜住之后 flush 就成了看不见的
            空操作。改成起一个嵌套的 Qt 事件循环来等：qasync 的 asyncio
            回调本来就是靠 Qt 事件派发的，spin 住 Qt 就等于让 flush 继续
            推进，同时又没有第二次「run 循环」。

            两道上限：``flush_pending_writes`` 自带超时，外面再挂一个
            定时器兜住嵌套循环，任何一边卡住都不会把窗口关不掉。
            """
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                # 没有跑着的循环，也就没有在飞的写。
                super().closeEvent(event)
                return

            task = loop.create_task(self.task_manager.flush_pending_writes())
            spin = QtEventLoop()
            task.add_done_callback(lambda _t: spin.quit())
            QTimer.singleShot(CLOSE_FLUSH_TIMEOUT_MS, spin.quit)
            # done_callback 是 call_soon 派发的，回到事件循环才会跑，理论上
            # 不会早于 exec()。仍然先查一次：quit() 落在 exec() 之前会被丢弃，
            # 那样这里就会永久挂住。
            if not task.done():
                spin.exec()
            if not task.done():
                logger.debug("退出前落库超时，剩余写入放弃")
                task.cancel()
            super().closeEvent(event)

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

        def _center_on_screen(self) -> None:
            """把窗口放到主屏幕（或默认屏幕）可用矩形的正中。

            先读 ``frameGeometry``（包含自绘标题栏），再用
            ``availableGeometry`` 减去任务栏偏移，避免一半被任务栏盖住。
            多屏环境：优先用 ``QApplication.primaryScreen()``，没有再退到
            ``screen()``。
            """
            from PySide6.QtGui import QGuiApplication

            app = QGuiApplication.instance()
            screen = None
            if app is not None:
                screen = app.primaryScreen()
            if screen is None:
                screen = self.screen()
            if screen is None:
                return
            available = screen.availableGeometry()
            fg = self.frameGeometry()
            fg.moveCenter(available.center())
            self.move(fg.topLeft())

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

        def _reparse_from_history(self, url: str) -> None:
            """历史页「重新解析」回调：填入 URL 并跳到解析页。"""
            current = self.parse_interface.url_input.toPlainText().strip()
            if current:
                self.parse_interface.url_input.setPlainText(current + "\n" + url)
            else:
                self.parse_interface.url_input.setPlainText(url)
            self.stackedWidget.setCurrentWidget(self.parse_interface)
            self.navigationInterface.setCurrentItem(
                self.parse_interface.objectName()
            )

        def _show_about(self) -> None:
            from .dialogs.about_dialog import build_about_dialog
            cls = build_about_dialog()
            dlg = cls(self.window())
            dlg.exec()

    return MainWindow
