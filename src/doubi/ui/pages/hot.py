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
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
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
            self._build_ui()
            subscribe_theme(self, lambda: None)

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
            self._refresh_board_options(route_key)

        # ----------------------------------------------------------

        def _on_refresh(self) -> None:
            try:
                import asyncio
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None
                if loop and loop.is_running():
                    loop.create_task(self._run_hot())
                else:
                    asyncio.run(self._run_hot())
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
            except Exception as exc:
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

    return HotPage, None