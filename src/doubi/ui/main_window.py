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

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

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
        MessageBox,
        MSFluentWindow,
        NavigationItemPosition,
        NavigationToolButton,
    )

    from ..core.engine_loader import build_default_pipeline
    from .feedback import toast_info, toast_success
    from .i18n import tr
    from .pages import (
        build_download_widgets,
        build_history_widgets,
        build_hot_widgets,
        build_parse_widgets,
        build_search_widgets,
        build_settings_widgets,
    )
    from .resources import APP_DISPLAY_NAME, APP_VERSION, load_app_icon
    from .shortcuts import ShortcutManager
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
    SearchPage, _ = build_search_widgets()
    HotPage, _ = build_hot_widgets()
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

            # 右下角加一个可视化的 resize 把手（0.3.9 修）。
            #
            # qfluentwidgets 用 qframelesswindow 自绘标题栏；它的原生
            # ``WS_THICKFRAME`` resize 边框只有 6–7 px（实测
            # ``GetWindowRect`` - ``GetClientRect`` delta = 6,6）——用户根本
            # 看不到也抓不到，体感就是「窗口不能调大小」。
            #
            # ``QSizeGrip`` 自带 16×16 三角点阵，但点阵颜色 (223,223,223)
            # 在浅色主题下几乎隐形。我们自绘一个明显一点的 18×18 三角拖拽
            # 把手——三道从右下角向左上方向的对角短线，颜色取自主题
            # ``progress_normal`` token（与「正在运行」色一致），暗主题里
            # 反过来用 ``progress_normal_dark``。
            self._size_grip = _ResizeGrip(self)
            self._size_grip.setToolTip("拖拽调整窗口大小")
            self._size_grip.lower()                  # 保持不抢其他控件焦点
            self._place_size_grip()                  # 初始化定位

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

            # ---- 搜索 / 热榜 (0.3.3 P1-3) ---------------------------
            self.search_interface = SearchPage(self)
            self.search_interface.setObjectName("searchInterface")
            self.addSubInterface(
                self.search_interface,
                FluentIcon.SEARCH,
                tr("nav.search"),
                position=NavigationItemPosition.TOP,
            )
            # 0.3.6：搜索页右键「下载」需要任务管理器才能入队。
            self.search_interface.set_task_manager(self.task_manager)

            self.hot_interface = HotPage(self)
            self.hot_interface.setObjectName("hotInterface")
            self.addSubInterface(
                self.hot_interface,
                FluentIcon.HEART,
                tr("nav.hot"),
                position=NavigationItemPosition.TOP,
            )
            # 0.3.6：热榜页右键「下载」/「搜索该词条并下载」同理。
            self.hot_interface.set_task_manager(self.task_manager)

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
            # 通用嗅探（M6.16）同理：设置页保存后把开关与时长推给解析页，
            # 解析按钮的「嗅探中… (Ns)」文案才不会停留在旧值。
            self.parse_interface.set_sniff_config(
                self.settings_interface._cfg.sniff_enabled,
                self.settings_interface._cfg.sniff_duration_sec,
            )
            self.settings_interface.sniffConfigChanged.connect(
                self.parse_interface.set_sniff_config
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

            # 关掉导航栏的指示条滑动动画（0.3.7 修）。
            #
            # 这里要分清 qfluentwidgets 里**两个不同的**蓝色指示条：
            #
            # 1. ``NavigationBar.indicator`` —— 一个独立的 4×24 圆角子控件，
            #    只在 ``setCurrentItem`` 的滑动动画期间可见，动画结束由
            #    ``_onIndicatorAniFinished`` ``hide()`` 掉。
            # 2. ``NavigationBarPushButton._drawBackground`` 里**按选中态画的**
            #    那条 ``drawRoundedRect(0, 16, 4, 24)``——它跟动画无关，只要
            #    该项 ``isSelected`` 就一定会画。
            #
            # 第 1 条在实测里会「卡住不消失」：从解析页依次切到设置页再切回
            # 解析页后，它停在「设置」旁边（灌 200 次事件循环也不退），
            # 视觉上等于两个页面同时被选中。关掉滑动动画就能消除它。
            # 第 2 条是 qfluentwidgets 的既定设计，保留。
            self.navigationInterface.setIndicatorAnimationEnabled(False)

            # 上次退出时还没下完的任务：问一句要不要接着下。
            # 排在最后，因为它要用到 parse_interface 的配置和已经建好的
            # 下载页——单次射击的定时器把它推到事件循环的下一轮，让窗口
            # 先画出来，否则对话框会弹在一片空白上。
            QTimer.singleShot(0, self._offer_restore)

            # ---- 系统托盘（关窗最小化到这里） ------------------------
            # 用户关窗不再等于退出进程：下载在跑的话，让他们最小化到托盘，
            # 任务完成时再弹 Windows toast 通知。``_install_tray`` 是单独
            # 方法因为它需要 ``self.setWindowIcon`` 已就位（构造里其他代
            # 码会 setWindowIcon），并且要分发给 download_interface。
            self._install_tray()

            # 任务状态变化时同步托盘菜单的可用性（暂停/继续按钮）。
            # ``task_added`` / ``task_progress`` / ``task_removed`` / 等
            # 都可能影响 running/paused 计数，这里用一个统一入口
            # ``_on_task_state_changed`` 收口，避免 N 个信号接 N 个槽。
            self.task_manager.task_added.connect(self._on_task_state_changed)
            self.task_manager.task_finished.connect(self._on_task_state_changed)
            self.task_manager.task_failed.connect(self._on_task_state_changed)
            self.task_manager.task_removed.connect(self._on_task_state_changed)

            # 全局快捷键（0.3.7 新增）—— 必须在 6 个子页面与 task_manager
            # 都就位后再注册，callbacks 才能拿到正确的 self.xxx_interface。
            self.shortcuts = ShortcutManager(self)
            self._register_shortcuts()
            # 把 ShortcutManager 注入设置页，让「快捷键速查」卡片显示出来。
            # 必须在 register 之后，否则 set_shortcuts 收到的 cheat_sheet 是空表。
            self.settings_interface.set_shortcuts(self.shortcuts)

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
            toast_success(self, "已恢复", f"{len(restored)} 个任务已暂停待续")

        def closeEvent(self, event) -> None:
            """关窗行为取决于 ``_truly_quit`` 标志。

            0.3.0 起的语义：点 X **不退出**进程，只把窗口藏到托盘。
            任务还在跑、用户想走开，关窗是放后台——他们从托盘可以再
            把窗口调出来。真正的退出走托盘菜单的「退出」。

            真正的退出（``_truly_quit`` 置 True）才走原本的落库清理路径：
            关窗前把还在飞的落库写等回来。状态变更的写入是故意「发射后
            不管」的——运行期任何一次暂停都不该卡在磁盘 I/O 上。但关窗
            时这个取舍要反过来：循环一关，还排在队里的写就静静丢了，
            而丢掉的恰恰是用户临走前那几次操作，也正是下次启动要靠
            它来提供恢复的那批记录。

            ``closeEvent`` 不能用 ``run_until_complete``：它是同步的 Qt
            回调，而此刻 qasync 的循环正在跑，往运行中的循环上再调一次
            run 只会抛 ``RuntimeError``——被兜住之后 flush 就成了看不见
            的空操作。改成起一个嵌套的 Qt 事件循环来等：qasync 的 asyncio
            回调本来就是靠 Qt 事件派发的，spin 住 Qt 就等于让 flush 继续
            推进，同时又没有第二次「run 循环」。

            两道上限：``flush_pending_writes`` 自带超时，外面再挂一个
            定时器兜住嵌套循环，任何一边卡住都不会让窗口关不掉。
            """
            # 走「真退出」路径：托盘「退出」/ 任务管理器「结束进程」/
            # 其他非用户-X 触发的关窗。
            if getattr(self, "_truly_quit", False):
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
                # done_callback 是 call_soon 派发的，回到事件循环才会跑，
                # 理论上不会早于 exec()。仍然先查一次：quit() 落在
                # exec() 之前会被丢弃，那样这里就会永久挂住。
                if not task.done():
                    spin.exec()
                if not task.done():
                    logger.debug("退出前落库超时，剩余写入放弃")
                    task.cancel()
                # 真退出时把托盘图标也收掉，否则 Windows 通知区会留
                # 一个不响应的孤儿图标直到用户手动清理。
                if getattr(self, "tray", None) is not None:
                    self.tray.shutdown()
                super().closeEvent(event)
                return

            # 用户点 X：把窗口藏到托盘，不退出。第一次藏的时候弹一个
            # 一次性通知，告诉用户「程序还在跑」。后续关窗就只藏不
            # 通知了——再弹就刷屏了。
            event.ignore()
            self.hide()
            if getattr(self, "tray", None) is not None:
                # 用一个内存型标志而不是 config 字段——这是「这次会话
                # 是否已经通知过」的临时状态，不该跨进程持续。
                if not getattr(self, "_tray_hide_announced", False):
                    self._tray_hide_announced = True
                    self.tray.show_message(
                        "DouBi 在后台运行",
                        "下载完成后会从这里弹出通知。"
                        "右键托盘图标可以显示主窗口或退出。",
                        icon_kind="info",
                        msec=4000,
                    )
                # 注意：这里**不能**动 ``show_window_requested`` 的连接。
                # 曾经有一行 ``disconnect()`` 号称「防止重复连」，但连接
                # 只在 ``_install_tray`` 里做一次，本来就没有重复。它的
                # 实际效果是：用户第一次点 X（正好就是进托盘的那一刻）
                # 把所有槽全断掉，之后托盘菜单「显示主窗口」emit 出去
                # 没人接，窗口再也唤不回来。M6.18.2 修复。
            else:
                # 兜底：没托盘（headless 测试 / 平台不支持）就老老实实退出。
                # 没有托盘的「后台」对用户毫无意义——他们会以为程序崩了。
                self._truly_quit = True
                super().closeEvent(event)

        def quit(self) -> None:
            """公共退出入口，供托盘「退出」菜单触发。

            不会真的关窗口——只翻标志，让 ``closeEvent`` 走「真退出」分支。
            """
            self._truly_quit = True
            self.close()

        # ---- 托盘集成 --------------------------------------------

        # ---- 窗口尺寸（右下角 resize 把手） ---------------------------------

        def _place_size_grip(self) -> None:
            """把 ``_size_grip`` 钉在右下角。

            不放进任何 layout（避免被标题栏 / 导航接口排挤），
            手动按 ``self.width() - 16`` / ``self.height() - 16`` 算坐标。
            """
            if getattr(self, "_size_grip", None) is None:
                return
            self._size_grip.move(
                max(0, self.width() - self._size_grip.width()),
                max(0, self.height() - self._size_grip.height()),
            )

        def resizeEvent(self, event) -> None:
            """窗口尺寸变化时同步 grip 的位置（保持钉在右下角）。"""
            super().resizeEvent(event)
            self._place_size_grip()

        def _install_tray(self) -> None:
            """构造 :class:`TrayController` 并把它的信号接进应用。

            三件事：
            1. 托盘双击 / 菜单「显示主窗口」→ 唤出主窗口。
            2. 托盘菜单「退出」→ ``quit()`` 走真退出路径。
            3. 托盘菜单「全部暂停 / 全部继续」→ 转给 task_manager。

            通知弹窗（``task_finished`` / ``task_failed``）不在这里接，
            而是在 ``DownloadPage`` 里接——它已经监听这些信号，附加
            一个 ``tray.notify_completion`` 转发即可，不必让 main_window
            再订阅一次。
            """
            from .tray import TrayController

            self.tray = TrayController(parent=self)
            self.tray.show_window_requested.connect(self._show_from_tray)
            self.tray.quit_requested.connect(self.quit)
            self.tray.pause_all_requested.connect(self.task_manager.pause_all)
            self.tray.resume_all_requested.connect(self.task_manager.resume_all)
            logger.debug("托盘已安装，信号已接线")
            # 初始可用性
            self._on_task_state_changed()

        def _show_from_tray(self) -> None:
            """托盘「显示主窗口」/ 双击托盘：把窗口呼回来。

            几个细节是**必要的**，缺一个都不行：
            1. ``setVisible(True)`` 而非 ``show()``：qfluentwidgets 的
               ``MSFluentWindow`` 重写了 ``hideEvent`` 关掉 Mica 等原生
               效果后，单纯 ``show()`` 不会把 HWND 重新挂回屏幕——
               ``setVisible(True)`` 走的是更底层的 ``setVisible`` 路径，
               能让 Qt 把 native window 重新 map。
            2. ``showNormal()`` 而非 ``showMaximized()``：用户关窗时是
               普通窗口，再开也应该是普通窗口。如果最大化关又最大化开，
               第二次的位置会漂到「记住的最大化位置」和「原始位置」之间。
            3. ``raise_() + activateWindow()``：从托盘唤回时 Windows 默认
               不会自动把焦点交给后台窗口，必须显式拉。
            4. 延迟 50ms 再 ``activateWindow``：HWND 刚 setVisible 时，Windows
               还在做 Z-order 计算，立刻 activate 会丢。``QTimer.singleShot``
               把 activate 推到下一轮事件循环，焦点就稳了。
            """
            logger.debug(
                "托盘唤出主窗口；当前 visible=%s minimized=%s",
                self.isVisible(),
                self.isMinimized(),
            )
            self.setVisible(True)
            self.showNormal()
            self.raise_()
            QTimer.singleShot(
                50,
                lambda: self.activateWindow() if not self.isMinimized() else None,
            )

        def _on_task_state_changed(self, *_args) -> None:
            """任务状态变化 → 同步托盘菜单「全部暂停 / 全部继续」可用性。

            接了 ``task_added`` / ``task_finished`` / ``task_failed`` /
            ``task_removed`` 四个信号，全部走这里，避免 N 个槽重复
            计算。``*_args`` 是为了吞下信号带的 task_id 等参数——
            我们要的是「刷新当前快照」，不关心具体是哪个任务变了。

            0.3.5：顺带把历史页标脏。历史页现在首刷懒加载 + 结果缓存，
            下载落库后不清标记，用户下完切过去看到的还是旧列表。
            """
            if hasattr(self, "history_interface"):
                self.history_interface.mark_dirty()
            if not hasattr(self, "tray") or self.tray is None:
                return
            self.tray.update_running_state(
                running=self.task_manager.running_count(),
                paused=self.task_manager.paused_count(),
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
            toast_success(self, "已切换主题", pack.label)

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

        # ---- 全局快捷键（0.3.7 新增） -------------------------------

        def _register_shortcuts(self) -> None:
            """把所有全局快捷键集中注册到 ``self.shortcuts``.

            设计要点：
            * 跳转类（Ctrl+1..5、Ctrl+,）走 ``_switch_to``：在切换前确认
              当前 stackedWidget 已经建好，缺一个就静默不切——避免快捷键
              在未初始化时抛 AttributeError。
            * ``F5`` 按当前页分发（解析/历史/搜索/热榜各自定义了 ``_refresh``
              或类似入口；下载页没有「刷新」语义，没注册）。
            * ``Ctrl+Enter`` 在解析页才生效——它通过 ``_on_parse_clicked``
              走，但 callback 里先查 ``self.stackedWidget.currentWidget()``
              是不是 ``parse_interface``，不是就 swallow。
            * ``Ctrl+Q`` 走 ``self.quit()`` 而不是 ``QApplication.quit()``：
              托盘程序的「退出」语义需要走 ``_truly_quit`` 路径，关窗前
              要落库，普通 QApplication.quit 不会触发我们写的 ``closeEvent``。
            """
            sc = self.shortcuts

            # ---- 页面跳转 ----
            sc.register(
                name="跳到解析页", key="Ctrl+1",
                callback=lambda: self._switch_to(self.parse_interface),
                description="跳转到「解析」页", category="导航",
            )
            sc.register(
                name="跳到下载页", key="Ctrl+2",
                callback=lambda: self._switch_to(self.download_interface),
                description="跳转到「下载」页（任务管理器）", category="导航",
            )
            sc.register(
                name="跳到历史页", key="Ctrl+3",
                callback=lambda: self._switch_to(self.history_interface),
                description="跳转到「历史」页", category="导航",
            )
            sc.register(
                name="跳到搜索页", key="Ctrl+4",
                callback=lambda: self._switch_to(self.search_interface),
                description="跳转到「搜索」页", category="导航",
            )
            sc.register(
                name="跳到热榜页", key="Ctrl+5",
                callback=lambda: self._switch_to(self.hot_interface),
                description="跳转到「热榜」页", category="导航",
            )
            sc.register(
                name="打开设置", key="Ctrl+,",
                callback=lambda: self._switch_to(self.settings_interface),
                description="跳转到「设置」页", category="导航",
            )

            # ---- 刷新 ----
            sc.register(
                name="刷新当前页面", key="F5",
                callback=self._refresh_current_page,
                description="按当前页面分发：搜索页重新搜、历史页重新查",
                category="刷新",
            )

            # ---- 解析页专属：Ctrl+Enter 解析当前输入 ----
            # 只在解析页是当前页时回调，其它页 swallow 不报错。
            sc.register(
                name="解析当前链接", key="Ctrl+Return",
                callback=self._trigger_parse_if_active,
                description="解析输入框里的所有链接（仅在「解析」页生效）",
                category="解析",
            )

            # ---- 系统 ----
            sc.register(
                name="切换主题", key="Ctrl+T",
                callback=self._cycle_theme,
                description="在内置主题包之间循环", category="外观",
            )
            sc.register(
                name="退出豆比", key="Ctrl+Q",
                callback=self.quit,
                description="走「真退出」路径（关窗前落库）", category="系统",
            )
            sc.register(
                name="关于豆比", key="F1",
                callback=self._show_about,
                description="弹出「关于」对话框", category="系统",
            )

        def _switch_to(self, widget) -> None:
            """切到指定子页（如果它已建好）。

            qfluentwidgets 的 ``MSFluentWindow`` 提供了 ``switchTo(widget)``
            ——这是官方切换接口，内部把 ``setCurrentItem`` + ``setCurrentWidget``
            的顺序正确串起来。手工组合两个调用在某些边界路径下会让
            ``setCurrentItem`` 把 widget 拽回原 page（实测过两次错过一拍）。

            先确认 widget 确实在 ``stackedWidget`` 里：``switchTo`` 内部直接
            调 ``setCurrentIndex(indexOf(widget))``，传一个不在栈里的 widget
            会抛 ``Exception: The index '-1' is illegal``（0.3.7 实测）。
            快捷键在极端时序下可能撞上「页面还没 addWidget」的瞬间，这个
            守卫把那种情况变成静默不切，而不是让异常冒到 Qt 事件循环里。
            """
            if widget is None:
                return
            try:
                if self.stackedWidget.indexOf(widget) < 0:
                    logger.debug(
                        "跳过 switchTo：%s 尚未加入 stackedWidget",
                        type(widget).__name__,
                    )
                    return
                self.switchTo(widget)
            except Exception:   # noqa: BLE001
                logger.debug("switchTo 失败（widget=%s）", type(widget).__name__)

        def _refresh_current_page(self) -> None:
            """按当前页面的语义跑「刷新」动作。

            解析页：直接弹 toast 提醒「解析页用「解析」按钮触发」。
            下载页：没有「刷新」语义，跳过。
            历史页：调 ``_refresh``（已有）。
            搜索页：调 ``search_btn.click()`` 复用用户行为，避免重复实现。
            热榜页：调 ``refresh_btn.click()``。
            设置页：跳过去（设置页没有「刷新」动作，但打开即用）。
            """
            current = self.stackedWidget.currentWidget()
            if current is self.parse_interface:
                toast_info(self, "解析页", "点「解析」按钮触发；Ctrl+Enter 同样有效。")
                return
            if current is self.download_interface:
                toast_info(self, "下载页", "下载页自动刷新，无需手动操作。")
                return
            if current is self.history_interface:
                if hasattr(self.history_interface, "_refresh"):
                    self.history_interface._refresh()
                return
            if current is self.search_interface:
                if hasattr(self.search_interface, "search_btn"):
                    self.search_interface.search_btn.click()
                return
            if current is self.hot_interface:
                if hasattr(self.hot_interface, "refresh_btn"):
                    self.hot_interface.refresh_btn.click()
                return
            if current is self.settings_interface:
                toast_info(self, "设置页", "设置即时生效。")
                return

        def _trigger_parse_if_active(self) -> None:
            """Ctrl+Enter 触发的解析——只在解析页生效，其它页 swallow。"""
            current = self.stackedWidget.currentWidget()
            if current is not self.parse_interface:
                return
            # 直接调 _on_parse_clicked 而不是 button.click()：后者还要先
            # 找焦点，解析页是默认页基本一定可见。
            self.parse_interface._on_parse_clicked()

    return MainWindow


# ---------------------------------------------------------------------------
# 自绘 resize 把手
# ---------------------------------------------------------------------------


class _ResizeGrip(QWidget):
    """右下角可视化的 resize 把手（0.3.9）。

    ``QSizeGrip`` 的点阵 (223,223,223) 在浅色主题下几乎隐形，
    用户根本看不出「这里能拖」。我们自绘一个 18×18 的小三角：
    三道从右下角向左上方向的对角短线，颜色取自主题
    ``progress_normal`` token。鼠标按下 / 移动直接调
    ``self.window().resize()``，与 ``QSizeGrip`` 同款语义。
    """

    SIZE = 18

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        from .theme import current_theme, token

        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.SizeFDiagCursor)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        # 主题主色（亮 / 暗各一对）：跟随主题切换
        # ``progress_normal`` 在默认 / 亮主题下是 ``#0a6cbf`` 这种深蓝，
        # 在暗主题下 ``progress_normal_dark`` 是 ``None``——会触发我们
        # 的 fallback 到中性灰，避免「暗主题里一个亮蓝三角」。
        self._light_color = token("progress_normal")
        self._dark_color = (
            current_theme().tokens.get("progress_normal_dark") or "#a8a8a8"
        )
        # 鼠标交互：记录按下起点 + 起始窗口几何
        self._press_pos: QPointF | None = None
        self._press_geo: tuple[int, int, int, int] | None = None

    def _color(self) -> str:
        from qfluentwidgets import isDarkTheme

        return self._dark_color if isDarkTheme() else self._light_color

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._press_pos = event.position()
            win = self.window()
            self._press_geo = (win.x(), win.y(), win.width(), win.height())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._press_pos is None or self._press_geo is None:
            super().mouseMoveEvent(event)
            return
        win = self.window()
        delta = event.position() - self._press_pos
        x, y, w0, h0 = self._press_geo
        # 增量为正，向右下拉；不让窗口小于它的 minimumSize
        new_w = max(win.minimumSize().width(), w0 + int(delta.x()))
        new_h = max(win.minimumSize().height(), h0 + int(delta.y()))
        win.resize(new_w, new_h)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._press_pos = None
            self._press_geo = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        color = QColor(self._color())
        pen = QPen(color)
        pen.setWidth(2)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        # 三道对角短线（右下角起点，向左上延伸）
        for off in (4, 9, 14):
            x0 = self.SIZE - 1
            y0 = self.SIZE - 1 - off
            x1 = self.SIZE - 1 - off
            y1 = self.SIZE - 1
            painter.drawLine(int(x0), int(y0), int(x1), int(y1))
