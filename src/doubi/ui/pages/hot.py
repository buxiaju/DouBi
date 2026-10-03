"""Hot page (0.3.3 / P1-3) — GUI front for ``doubi hot``.

Shows the 抖音 4 boards (positive / entertainment / society /
challenge) in a single table. Mirrors :meth:`DouyinWebAPI.get_hot_list`
exactly so the GUI stays in sync with the CLI / MCP / REST siblings.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("doubi.ui.pages.hot")


#: Hot-board dropdown options, parallel to ``doubi hot --board``.
BOARD_OPTIONS = [
    ("all",          "全部榜单"),
    ("positive",     "热搜"),
    ("entertainment", "娱乐"),
    ("society",      "社会"),
    ("challenge",    "挑战"),
]


def build_hot_widgets():
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
    )
    from qfluentwidgets import (
        PushButton, ComboBox, TableWidget, InfoBar, InfoBarPosition,
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
                "抖音官方榜单（热搜 / 娱乐 / 社会 / 挑战），"
                "按 `--board` 选项过滤。数据来自 CLI `doubi hot` 同源。"
            )
            self.refresh_btn = PushButton("刷新", self)
            self.refresh_btn.clicked.connect(self._on_refresh)
            self._header.add_action(self.refresh_btn)
            outer.addWidget(self._header)

            row = QHBoxLayout()
            row.setSpacing(SPACE_MD)
            self._board = ComboBox(self)
            for value, label in BOARD_OPTIONS:
                self._board.addItem(label, userData=value)
            self._board.setCurrentIndex(0)
            self._board.currentIndexChanged.connect(self._on_refresh)
            row.addWidget(self._board, 1)
            row.addStretch(3)
            outer.addLayout(row)

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
                    message=str(exc),
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=5000,
                )

        async def _run_hot(self) -> None:
            from doubi.platforms.douyin.webapi import DouyinWebAPI

            board = self._board.currentData() or "all"
            cookies_file = (
                self._cfg.cookies_file if self._cfg.cookies_file else None
            )
            api = DouyinWebAPI(
                cookies_file=cookies_file,
                proxy=self._cfg.proxy,
                timeout=15.0,
            )
            rows = await api.get_hot_list(board=board, max_rows=50)
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
                # 抖音榜单里「榜单名」= ``board``，「标题」= ``title``，
                # 「热度」= ``hot_value``，「详情」= ``share_url``。
                # 任何字段缺失就用空串兜底，避免单元格显示 ``None``。
                self.table.setItem(
                    i, 0,
                    QTableWidgetItem(str(row.get("board") or "")),
                )
                self.table.setItem(
                    i, 1,
                    QTableWidgetItem(str(row.get("title") or "")),
                )
                self.table.setItem(
                    i, 2,
                    QTableWidgetItem(str(row.get("hot_value") or "")),
                )
                self.table.setItem(
                    i, 3,
                    QTableWidgetItem(str(row.get("share_url") or "")),
                )

    return HotPage, None