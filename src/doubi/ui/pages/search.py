"""Search page (0.3.3 / P1-3 + 0.3.4 / UI 完善) — GUI front for ``doubi search``.

CLI had this command since 0.3.2 (M6.49), but the GUI had no entry —
users who only knew the GUI couldn't see the four search channels
(general / video / user / live) at all. 0.3.4 adds a platform tab so
B 站 search (video / user) is reachable from the same page.

Logged-out handling: without cookies, 抖音 returns 403 for most search
endpoints, and B 站 search returns -412 (request intercepted) without
a ``buvid3`` cookie. The page detects these and shows an explicit "去登录"
empty state instead of an empty table.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("doubi.ui.pages.search")


#: Search platforms surfaced on the page. Order matters: first = default.
#: Module-level so the regression test can lock it down without reaching
#: into the factory's enclosing frame.
PLATFORM_OPTIONS = [
    ("douyin",   "抖音"),
    ("bilibili", "B 站"),
]

#: Search channels per platform. The default channel for a brand-less call
#: lives in :data:`DEFAULT_CHANNEL` keyed by the same platform id.
PLATFORM_CHANNELS: dict[str, list[tuple[str, str]]] = {
    "douyin": [
        ("general", "综合"),
        ("video",   "视频"),
        ("user",    "用户"),
        ("live",    "直播"),
    ],
    "bilibili": [
        ("video",   "视频"),
        ("user",    "用户"),
    ],
}

DEFAULT_CHANNEL: dict[str, str] = {
    "douyin":   "general",
    "bilibili": "video",
}


def build_search_widgets():
    from PySide6.QtCore import Qt, QUrl
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import (
        QApplication, QMenu, QWidget, QVBoxLayout, QHBoxLayout,
        QStackedWidget,
    )
    from qfluentwidgets import (
        PushButton, LineEdit, ComboBox, SegmentedWidget,
        TableWidget, InfoBar, InfoBarPosition,
    )

    from ...core.config import load_config
    from ..theme import (
        SPACE_LG, SPACE_MD, SPACE_XL,
        subscribe_theme,
    )
    from ..widgets import build_empty_state, build_page_header, build_stat_chip

    class SearchPage(QWidget):
        def __init__(self, parent: Optional[QWidget] = None):
            super().__init__(parent)
            self.setObjectName("searchPage")
            self._cfg = load_config(None)
            self._rows: list[dict] = []
            #: Set by ``main_window`` right after construction. Kept
            #: ``None`` so the page still builds stand-alone (and so the
            #: existing factory-only tests keep working).
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
            self._header.set_title("搜索")
            self._header.set_subtitle(
                "在 抖音 / B 站站内按关键词搜索。通道结构与 CLI "
                "`doubi search` 完全对齐。"
            )
            self.search_btn = PushButton("搜索", self)
            self.search_btn.clicked.connect(self._on_search)
            self._header.add_action(self.search_btn)
            outer.addWidget(self._header)

            # ---- 平台切换 + 通道 ----
            self._platform_tabs = SegmentedWidget(self)
            for value, label in PLATFORM_OPTIONS:
                self._platform_tabs.addItem(routeKey=value, text=label)
            self._platform_tabs.setCurrentItem(PLATFORM_OPTIONS[0][0])
            self._platform_tabs.currentItemChanged.connect(self._on_platform_changed)
            outer.addWidget(self._platform_tabs)

            # ---- 输入条 ----
            row = QHBoxLayout()
            row.setSpacing(SPACE_MD)
            self._keyword = LineEdit(self)
            self._keyword.setPlaceholderText("搜索关键词（中英文都行）")
            self._keyword.returnPressed.connect(self._on_search)
            self._channel = ComboBox(self)
            self._refresh_channel_options(PLATFORM_OPTIONS[0][0])
            row.addWidget(self._keyword, 4)
            row.addWidget(self._channel, 1)
            outer.addLayout(row)

            # ---- 状态条 ----
            stats_row = QHBoxLayout()
            stats_row.setSpacing(SPACE_MD)
            self._stat_hits = StatChip(self)
            self._stat_hits.set_kind("running")
            self._stat_hits.set_label("本次命中")
            stats_row.addWidget(self._stat_hits, 1)
            stats_row.addStretch(3)
            outer.addLayout(stats_row)

            # ---- 主体：表格 ↔ 空态 ----
            self._stack = QStackedWidget(self)
            self.table = TableWidget(self)
            self.table.setColumnCount(4)
            self.table.setHorizontalHeaderLabels(["标题/昵称", "作者", "ID", "详情"])
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
                "尚未搜索",
                "在上方输入关键词并回车，或点「搜索」。",
            )
            self._stack.addWidget(self._empty_state)
            outer.addWidget(self._stack, 1)

            self._stack.setCurrentWidget(self._empty_state)

        def _refresh_channel_options(self, platform: str) -> None:
            """按当前平台刷新通道下拉。"""
            self._channel.blockSignals(True)
            self._channel.clear()
            for value, label in PLATFORM_CHANNELS.get(platform, []):
                self._channel.addItem(label, userData=value)
            default = DEFAULT_CHANNEL.get(platform)
            if default is not None:
                for i in range(self._channel.count()):
                    if self._channel.itemData(i) == default:
                        self._channel.setCurrentIndex(i)
                        break
            self._channel.blockSignals(False)

        def _on_platform_changed(self, route_key: str) -> None:
            self._platform = route_key
            self._refresh_channel_options(route_key)

        # ----------------------------------------------------------

        def _on_search(self) -> None:
            keyword = self._keyword.text().strip()
            if not keyword:
                InfoBar.warning(
                    title="需要关键词",
                    content="请先输入搜索关键词。",
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=3000,
                )
                return
            # qfluentwidgets 的 SegmentedWidget.currentItem() 返回
            # SegmentedItem **对象**而非 routeKey 字符串；必须用
            # currentRouteKey()，否则会把对象当平台名传下去。
            platform_route = (
                self._platform_tabs.currentRouteKey()
                or PLATFORM_OPTIONS[0][0]
            )
            # 记住本次实际搜索的平台：右键菜单的 URL 合成依赖它，
            # 而用户完全可能在拿到结果后再切 Tab（切换只刷新通道
            # 下拉，不会重搜）。用「发起搜索时」的平台才不会串台。
            self._platform = platform_route
            try:
                self._run_async(self._run_search(platform_route, keyword))
            except Exception as exc:
                logger.exception("search failed: %s", exc)
                InfoBar.error(
                    title="搜索失败",
                    content=str(exc),
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=5000,
                )

        async def _run_search(self, platform: str, keyword: str) -> None:
            from doubi.cli.main import collect_search_async

            channel = self._channel.currentData() or DEFAULT_CHANNEL[platform]
            cookies_file = (
                self._cfg.cookies_file if self._cfg.cookies_file else None
            )
            try:
                rows = await collect_search_async(
                    keyword=keyword,
                    channel=channel,
                    platform=platform,
                    max_count=20,
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
                if not cookies_file:
                    self._empty_state.set_text(
                        "暂无结果（未登录）",
                        (
                            "抖音搜索需要登录态；B 站搜索需要至少 wbi keys。"
                            "请前往「设置 → 账号」登录对应平台后再试。"
                        ),
                    )
                else:
                    self._empty_state.set_text(
                        "暂无结果",
                        "可能是关键词拼写、平台限流或登录态过期。"
                        "请换个关键词或在设置页检查 Cookie。",
                    )
                self._stack.setCurrentWidget(self._empty_state)

        def _populate_table(self) -> None:
            from PySide6.QtWidgets import QTableWidgetItem

            self.table.setRowCount(len(self._rows))
            for i, row in enumerate(self._rows):
                # 新 schema (0.3.4): ``title`` 直接是字符串；作者在
                # ``row["author"]["name"]`` 或顶层 ``nickname``。
                title = row.get("title") or row.get("nickname") or row.get("word") or ""
                if isinstance(row.get("author"), dict):
                    author = row["author"].get("name") or row["author"].get("mid") or ""
                else:
                    author = row.get("nickname") or row.get("author") or ""
                item_id = (
                    row.get("item_id")
                    or row.get("aweme_id")
                    or row.get("uid")
                    or row.get("room_id")
                    or row.get("mid")
                    or ""
                )
                detail = row.get("share_url") or ""
                self.table.setItem(i, 0, QTableWidgetItem(str(title)))
                self.table.setItem(i, 1, QTableWidgetItem(str(author)))
                self.table.setItem(i, 2, QTableWidgetItem(str(item_id)))
                self.table.setItem(i, 3, QTableWidgetItem(str(detail)))

        # ---- 右键菜单 (0.3.6) ----------------------------------------

        def _context_menu_entries(self, row: dict) -> list[tuple[str, bool]]:
            """纯函数：该行应该出现哪些菜单项、各自是否可用。

            拆出来是为了让「菜单项可用性」可以被单测直接断言——
            不必驱动 Qt 菜单。Qt 侧只负责把结果变成 QAction。
            """
            from ..row_actions import share_url_for

            url = share_url_for(row, self._platform)
            has_url = bool(url)
            return [
                ("下载", has_url and self._task_manager is not None),
                ("复制链接", has_url),
                ("在浏览器中打开", has_url),
            ]

        def _on_table_context_menu(self, pos) -> None:
            # ``QMenu`` / ``QDesktopServices`` / ``QApplication`` 刻意来自
            # 工厂闭包（不是函数内 import）：测试需要一个非模态的 QMenu
            # 子类替换掉 ``exec``，而 shiboken 会绕过 Python 层的
            # ``QMenu.exec = ...`` 直接派发到 C++。唯一可靠的注入点是
            # 闭包 cell —— 与 ``parse.py`` 的右键菜单保持一致。
            row = self.table.rowAt(pos.y())
            if row < 0 or row >= len(self._rows):
                return
            self.table.setCurrentCell(row, self.table.currentColumn())
            record = self._rows[row]
            labels = self._context_menu_entries(record)
            by_label = {label: enabled for label, enabled in labels}

            menu = QMenu(self.table)
            download = menu.addAction("下载")
            copy_link = menu.addAction("复制链接")
            browser = menu.addAction("在浏览器中打开")
            for action in (download, copy_link, browser):
                action.setEnabled(by_label.get(action.text(), False))

            chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
            if chosen is None:
                return

            from ..row_actions import share_url_for

            url = share_url_for(record, self._platform)
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

        def _enqueue_row(self, record: dict, url: str) -> None:
            """把一行搜索结果解析成 MediaItem 并入队。"""
            if self._task_manager is None:
                self._toast(
                    "未连接任务管理器",
                    "请在主窗口中打开此页面。",
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

        def _run_async(self, coro) -> None:
            """在本页既有的「有 loop 就 create_task，没有就 asyncio.run」
            约定下跑一个协程。抽出来是因为右键动作与搜索按钮走的是
            同一套调度规则。
            """
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
            """``AppConfig -> DownloadOptions``。

            与解析页同源：解析页的 ``_build_options`` 是唯一出口，
            但它在 ``build_parse_widgets`` 的闭包里拿不到。这里只做
            同一个搬运，字段与解析页保持一致（见
            ``test_build_options_covers_every_shared_config_field``）。
            """
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

    return SearchPage, None
