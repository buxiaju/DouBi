"""Hot page (0.3.3 / P1-3 + 0.3.4 / UI 完善) — GUI front for ``doubi hot``.

抖音 4 牌榜 + B 站热搜词 / 热门视频。所有数据共用同一个
``collect_hot_async(platform=...)``，CLI / MCP / REST 同步。

The ``platform`` segmented control at the top is the only switch
between 抖音 (4 boards aggregated) and B 站 (hot-word list + popular
videos together). ``board`` for 抖音 still maps to the original
``positive`` / ``entertainment`` / ``society`` / ``challenge`` keys.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("doubi.ui.pages.hot")


#: Platforms shown on the page. Order matters: first = default.
PLATFORM_OPTIONS = [
    ("douyin",   "抖音"),
    ("bilibili", "B 站"),
]

#: Board dropdown options per platform. B 站 has no board — its ``hotword``
#: + ``popular`` streams are aggregated inside :func:`collect_hot_async`,
#: so the GUI shows just an "all" sentinel.
PLATFORM_BOARDS: dict[str, list[tuple[str, str]]] = {
    "douyin": [
        ("all",           "全部榜单"),
        ("positive",      "热搜"),
        ("entertainment", "娱乐"),
        ("society",       "社会"),
        ("challenge",     "挑战"),
    ],
    "bilibili": [
        ("all", "热搜词 + 热门视频"),
    ],
}
DEFAULT_BOARD: dict[str, str] = {
    "douyin":   "all",
    "bilibili": "all",
}


def build_hot_widgets():
    from PySide6.QtCore import Qt, QUrl
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import (
        QApplication, QMenu, QMessageBox, QWidget, QVBoxLayout,
        QHBoxLayout, QStackedWidget,
    )
    from qfluentwidgets import (
        PushButton, ComboBox, SegmentedWidget, TableWidget,
        InfoBar, InfoBarPosition,
    )

    from ...core.config import load_config
    from ..theme import (
        SPACE_LG, SPACE_MD, SPACE_XL,
        subscribe_theme,
    )
    from ..widgets import build_empty_state, build_page_header, build_stat_chip

    class HotPage(QWidget):
        def __init__(self, parent: Optional[QWidget] = None):
            super().__init__(parent)
            self.setObjectName("hotPage")
            self._cfg = load_config(None)
            self._rows: list[dict] = []
            #: Set by ``main_window`` right after construction; ``None``
            #: keeps the page buildable stand-alone.
            self._task_manager = None
            self._platform = PLATFORM_OPTIONS[0][0]
            self._build_ui()
            subscribe_theme(self, lambda: None)

        # ---- public API ----------------------------------------------

        def set_task_manager(self, manager) -> None:
            """主窗口接线：右键「下载」需要它才能入队。"""
            self._task_manager = manager

        def _build_ui(self):
            PageHeader = build_page_header()
            EmptyState = build_empty_state()
            StatChip = build_stat_chip()

            outer = QVBoxLayout(self)
            outer.setContentsMargins(SPACE_XL, SPACE_LG, SPACE_XL, SPACE_LG)
            outer.setSpacing(SPACE_LG)

            self._header = PageHeader(self)
            self._header.set_title("热榜")
            self._header.set_subtitle(
                "抖音官方榜单（热搜 / 娱乐 / 社会 / 挑战）+ "
                "B 站热搜词 / 热门视频。数据来自 CLI `doubi hot` 同源。"
            )
            self.refresh_btn = PushButton("刷新", self)
            self.refresh_btn.clicked.connect(self._on_refresh)
            self._header.add_action(self.refresh_btn)
            outer.addWidget(self._header)

            # ---- 平台切换 ----
            self._platform_tabs = SegmentedWidget(self)
            for value, label in PLATFORM_OPTIONS:
                self._platform_tabs.addItem(routeKey=value, text=label)
            self._platform_tabs.setCurrentItem(PLATFORM_OPTIONS[0][0])
            self._platform_tabs.currentItemChanged.connect(self._on_platform_changed)
            outer.addWidget(self._platform_tabs)

            # ---- 牌 / 类型选择 ----
            row = QHBoxLayout()
            row.setSpacing(SPACE_MD)
            self._board = ComboBox(self)
            self._refresh_board_options(PLATFORM_OPTIONS[0][0])
            self._board.currentIndexChanged.connect(self._on_refresh)
            row.addWidget(self._board, 1)
            row.addStretch(3)
            outer.addLayout(row)

            # ---- 状态条 ----
            stats_row = QHBoxLayout()
            stats_row.setSpacing(SPACE_MD)
            self._stat_hits = StatChip(self)
            self._stat_hits.set_kind("running")
            self._stat_hits.set_label("本次榜单条目数")
            stats_row.addWidget(self._stat_hits, 1)
            stats_row.addStretch(3)
            outer.addLayout(stats_row)

            self._stack = QStackedWidget(self)
            self.table = TableWidget(self)
            self.table.setColumnCount(4)
            self.table.setHorizontalHeaderLabels(["榜单", "标题", "热度", "详情"])
            self.table.verticalHeader().hide()
            self.table.setWordWrap(False)
            self.table.setEditTriggers(TableWidget.NoEditTriggers)
            self.table.setSelectionBehavior(TableWidget.SelectRows)
            self.table.verticalHeader().setDefaultSectionSize(32)
            self.table.setContextMenuPolicy(Qt.CustomContextMenu)
            self.table.customContextMenuRequested.connect(
                self._on_table_context_menu,
            )
            self._stack.addWidget(self.table)

            self._empty_state = EmptyState(self)
            self._empty_state.set_text(
                "尚未加载",
                "点「刷新」拉取榜单数据。",
            )
            self._stack.addWidget(self._empty_state)
            outer.addWidget(self._stack, 1)

            self._stack.setCurrentWidget(self._empty_state)

        def _refresh_board_options(self, platform: str) -> None:
            self._board.blockSignals(True)
            self._board.clear()
            for value, label in PLATFORM_BOARDS.get(platform, []):
                self._board.addItem(label, userData=value)
            default = DEFAULT_BOARD.get(platform)
            if default is not None:
                for i in range(self._board.count()):
                    if self._board.itemData(i) == default:
                        self._board.setCurrentIndex(i)
                        break
            self._board.blockSignals(False)

        def _on_platform_changed(self, route_key: str) -> None:
            self._platform = route_key
            self._refresh_board_options(route_key)

        # ----------------------------------------------------------

        def _on_refresh(self) -> None:
            try:
                self._run_async(self._run_hot())
            except Exception as exc:
                logger.exception("hot list failed: %s", exc)
                InfoBar.error(
                    title="热榜失败",
                    content=str(exc),
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=5000,
                )

        async def _run_hot(self) -> None:
            from doubi.cli.main import collect_hot_async

            # qfluentwidgets 的 SegmentedWidget.currentItem() 返回的是
            # SegmentedItem **对象**，不是 routeKey 字符串；必须用
            # currentRouteKey()。用错会把对象当成平台名传给
            # collect_hot_async，抛 "unknown platform: <SegmentedItem...>"。
            platform_route = (
                self._platform_tabs.currentRouteKey()
                or PLATFORM_OPTIONS[0][0]
            )
            # 记住本次刷新用的平台：右键菜单的 URL 合成依赖它。
            self._platform = platform_route
            board = self._board.currentData() or DEFAULT_BOARD[platform_route]
            cookies_file = (
                self._cfg.cookies_file if self._cfg.cookies_file else None
            )
            try:
                rows = await collect_hot_async(
                    board=board,
                    platform=platform_route,
                    max_count=50,
                    cookies_file=cookies_file,
                    proxy=self._cfg.proxy,
                    timeout=15.0,
                )
            except Exception:
                raise

            self._rows = list(rows or [])
            self._stat_hits.set_value(len(self._rows))
            if self._rows:
                self._populate_table()
                self._stack.setCurrentWidget(self.table)
            else:
                self._empty_state.set_text(
                    "暂无榜单",
                    "平台可能临时下线了该榜或限流，请稍后重试。",
                )
                self._stack.setCurrentWidget(self._empty_state)

        def _populate_table(self) -> None:
            from PySide6.QtWidgets import QTableWidgetItem

            self.table.setRowCount(len(self._rows))
            for i, row in enumerate(self._rows):
                board_name = (
                    row.get("board_name")
                    or row.get("board")
                    or ""
                )
                title = row.get("title") or row.get("word") or ""
                hot_value = (
                    row.get("hot_value")
                    if row.get("hot_value") is not None
                    else row.get("score")
                    or ""
                )
                detail = row.get("share_url") or ""
                self.table.setItem(
                    i, 0, QTableWidgetItem(str(board_name)),
                )
                self.table.setItem(
                    i, 1, QTableWidgetItem(str(title)),
                )
                self.table.setItem(
                    i, 2, QTableWidgetItem(str(hot_value)),
                )
                self.table.setItem(
                    i, 3, QTableWidgetItem(str(detail)),
                )

        # ---- 右键菜单 (0.3.6) ----------------------------------------

        def _context_menu_entries(self, row: dict) -> list[tuple[str, bool]]:
            """纯函数：该行应该出现哪些菜单项、各自是否可用。

            热榜有两种行，菜单因此分叉：

            * **视频 / 用户行**（B 站热门视频、抖音热榜里带 ``aweme_id``
              的条目）—— 与搜索页一致：下载 / 复制链接 / 浏览器打开。
            * **热搜词行**（抖音 ``word``、B 站 ``hotword``）—— 词条本身
              不是可下载资源，没有直链可复制。唯一有意义的动作是
              「搜索该词条并把结果入队」，所以这里不出现「复制链接」。
              抖音搜索当前会被平台风控拦（0.3.6 已能识别并提示），
              但 B 站热搜词能正常拿到视频 —— 行为一致比按平台分叉更好。

            0.3.6 修正：词条行的动作名从「下载」改为
            :data:`~doubi.ui.row_confirm.HOT_WORD_ACTION`。用户实测反馈
            「点一条却下了 20 个」——语义没错（词条唯一有意义的就是全收），
            错的是标签让人以为是「下载这一条」。
            """
            from ..row_actions import is_hot_word_row, share_url_for
            from ..row_confirm import HOT_WORD_ACTION

            enabled_manager = self._task_manager is not None
            if is_hot_word_row(row):
                return [
                    (HOT_WORD_ACTION, enabled_manager),
                ]
            url = share_url_for(row, self._platform)
            has_url = bool(url)
            return [
                ("下载", has_url and enabled_manager),
                ("复制链接", has_url),
                ("在浏览器中打开", has_url),
            ]

        def _on_table_context_menu(self, pos) -> None:
            # 与搜索页同因：``QMenu`` 等必须来自工厂闭包，测试才能用
            # 非模态子类替换 ``exec``（见 ``parse.py`` 的同款注释）。
            row = self.table.rowAt(pos.y())
            if row < 0 or row >= len(self._rows):
                return
            self.table.setCurrentCell(row, self.table.currentColumn())
            record = self._rows[row]

            from ..row_actions import is_hot_word_row, share_url_for
            from ..row_confirm import HOT_WORD_ACTION

            is_word = is_hot_word_row(record)
            url = None if is_word else share_url_for(record, self._platform)
            enabled_manager = self._task_manager is not None

            menu = QMenu(self.table)
            if is_word:
                search_word = menu.addAction(HOT_WORD_ACTION)
                copy_link = browser = download = None
                search_word.setEnabled(enabled_manager)
            else:
                has_url = bool(url)
                download = menu.addAction("下载")
                copy_link = menu.addAction("复制链接")
                browser = menu.addAction("在浏览器中打开")
                search_word = None
                for action in (download, copy_link, browser):
                    action.setEnabled(has_url and (
                        enabled_manager if action is download else True
                    ))

            chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
            if chosen is None:
                return
            if is_word:
                if chosen is search_word:
                    self._search_word_and_enqueue(record)
                return
            if not url:
                return
            if chosen is copy_link:
                clipboard = QApplication.clipboard()
                if clipboard is not None:
                    clipboard.setText(url)
                    self._toast("已复制链接", url)
            elif chosen is browser:
                QDesktopServices.openUrl(QUrl(url))
            elif chosen is download:
                self._enqueue_row(record, url)

        # ---- 入队 -----------------------------------------------------

        def _enqueue_row(self, record: dict, url: str) -> None:
            """把一行热榜内容解析成 MediaItem 并入队。"""
            if self._task_manager is None:
                self._toast(
                    "未连接任务管理器", "请在主窗口中打开此页面。",
                    kind="error",
                )
                return

            async def _do():
                from ..row_actions import build_media_item, row_label

                item, children = await build_media_item(url)
                targets = children or ([item] if item is not None else [])
                if not targets:
                    self._toast(
                        "无法下载",
                        f"没能解析出行内容：{row_label(record) or url}",
                        kind="error",
                    )
                    return
                opts = self._build_options()
                for target in targets:
                    self._task_manager.add(target, opts)
                self._toast(
                    "已加入下载队列",
                    f"{row_label(record) or url}（{len(targets)} 项）",
                )

            self._run_async(_do())

        def _search_word_and_enqueue(self, record: dict) -> None:
            """热搜词行：先搜该词，**确认后**再把搜到的视频全部入队。

            词条本身不可下载（只有 ``word`` + ``sentence_id``），
            用户右键一个热搜词的真实意图就是「把这词下面的视频收了」。

            0.3.6 修正：搜索完成后先弹确认框再入队。此前是搜完直接入队，
            用户看到的结果是「点了一条，下了 20 个」，读起来像 bug。
            顺序上必须**先搜再问**——条数只有搜完才知道，预先估算会猜错。
            """
            if self._task_manager is None:
                self._toast(
                    "未连接任务管理器", "请在主窗口中打开此页面。",
                    kind="error",
                )
                return
            keyword = str(
                record.get("word") or record.get("sentence") or ""
            ).strip()
            if not keyword:
                self._toast("词条为空", "这一行没有可搜索的关键词。", kind="warning")
                return

            async def _do():
                from doubi.cli.main import collect_search_async

                from ..row_actions import build_media_item, share_url_for
                from ..row_confirm import confirm_plan

                platform = self._platform
                cookies_file = (
                    self._cfg.cookies_file if self._cfg.cookies_file else None
                )
                try:
                    hits = await collect_search_async(
                        keyword=keyword,
                        channel="video",
                        platform=platform,
                        max_count=20,
                        cookies_file=cookies_file,
                        proxy=self._cfg.proxy,
                        timeout=15.0,
                    )
                except Exception as exc:  # noqa: BLE001 - reported to user
                    logger.exception("hot word search failed: %s", exc)
                    self._toast("搜索失败", f"{keyword}：{exc}", kind="error")
                    return

                if not hits:
                    # 抖音搜索目前会被平台风控（``search_nil_type =
                    # verify_check``）拦成「HTTP 200 + 空结果」。这是
                    # 平台侧限制，客户端绕不过去——但绝不能像以前那样
                    # 静默显示空表，否则用户会以为软件坏了。
                    hint = (
                        "抖音当前会对关键词搜索做风控校验，可能需要先在"
                        "网页端完成一次验证；换 B 站热搜词一般可用。"
                        if platform == "douyin"
                        else "换个词条或稍后重试。"
                    )
                    self._toast(
                        "没有搜到视频", f"「{keyword}」：{hint}", kind="warning",
                    )
                    return

                # 先把命中解析成 MediaItem，再拿**真实条数**去确认。
                # 顺序不能反：解析失败的命中不该计入待下载数量，否则
                # 确认框上的数字和实际入队数对不上，等于又在骗人。
                opts = self._build_options()
                pending = []
                for hit in hits:
                    url = share_url_for(hit, platform)
                    if not url:
                        continue
                    item, _children = await build_media_item(url)
                    if item is None:
                        continue
                    pending.append(item)
                if not pending:
                    self._toast(
                        "没有可入队的视频",
                        f"「{keyword}」命中 {len(hits)} 条，但都没能解析出媒体项。",
                        kind="warning",
                    )
                    return

                plan = confirm_plan(
                    kind="hot_word", label=keyword, count=len(pending),
                )
                if not self._confirm(plan):
                    self._toast(
                        "已取消",
                        f"「{keyword}」的 {len(pending)} 个视频未加入队列。",
                        kind="info",
                    )
                    return

                for item in pending:
                    self._task_manager.add(item, opts)
                self._toast(
                    "已加入下载队列",
                    f"「{keyword}」共 {len(pending)} 个视频。",
                )

            self._run_async(_do())

        def _confirm(self, plan) -> bool:
            """把 :class:`ConfirmPlan` 渲染成模态框，返回用户是否确认。

            单独抽出来是为了让测试可以替换掉它——模态框在 offscreen /
            CI 下无法用真实点击驱动，而「批量动作必须先问一次」这条
            规则本身必须被测到。
            """
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Question)
            box.setWindowTitle(plan.title)
            box.setText(plan.body)
            yes = box.addButton(plan.confirmed_text, QMessageBox.AcceptRole)
            box.addButton(plan.cancelled_text, QMessageBox.RejectRole)
            box.setDefaultButton(box.buttons()[-1])
            box.exec()
            return box.clickedButton() is yes

        def _run_async(self, coro) -> None:
            import asyncio

            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop and loop.is_running():
                loop.create_task(coro)
            else:
                asyncio.run(coro)

        def _build_options(self):
            """``AppConfig -> DownloadOptions``（与解析页同源同字段）。"""
            from ...core.models import DownloadOptions

            cfg = self._cfg
            return DownloadOptions(
                output_root=cfg.output_root,
                output_dir_template=cfg.output_dir_template,
                filename_template=cfg.filename_template,
                container=cfg.container,
                max_quality=cfg.max_quality,
                write_thumbnail=cfg.write_thumbnail,
                write_metadata_json=cfg.write_metadata_json,
                write_nfo=cfg.write_nfo,
                write_danmaku=cfg.write_danmaku,
                write_subtitles=cfg.write_subtitles,
                resume=cfg.resume,
                duplicate_policy=cfg.duplicate_policy,
                database=cfg.database_path if cfg.database else None,
                manifest=cfg.manifest_path,
                proxy=cfg.proxy,
                rate_limit=cfg.rate_limit,
                cookies_file=cfg.cookies_file,
            )

        def _toast(self, title: str, content: str, kind: str = "success") -> None:
            fn = {
                "success": InfoBar.success,
                "warning": InfoBar.warning,
                "error": InfoBar.error,
                "info": InfoBar.info,
            }[kind]
            fn(
                title=title, content=content, parent=self,
                position=InfoBarPosition.TOP_RIGHT, duration=4000,
            )

    return HotPage, None
