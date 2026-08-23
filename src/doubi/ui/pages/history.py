"""History page — real query over the SQLite database.

M5.1 adds the full table: platform / item_id / title / author /
download time / save dir, backed by :meth:`Database.list_recent`.
A refresh button + auto-refresh on page show keep it current.

M6.x 重做：与其它页面共享 PageHeader / EmptyState，数据库未启用时
给出清晰的「去设置页打开」提示。
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Optional

logger = logging.getLogger("doubi.ui.pages.history")


def build_history_widgets():
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFileDialog,
        QStackedWidget,
    )
    from qfluentwidgets import (
        PushButton, TableWidget, StrongBodyLabel, InfoBar, InfoBarPosition,
    )

    from ...core.config import load_config
    from ...core.storage.database import Database
    from ..theme import (
        SPACE_LG, SPACE_MD, SPACE_SM, SPACE_XL,
        heading_qss, muted_qss, subscribe_theme, token,
    )
    from ..widgets import build_empty_state, build_page_header, build_stat_chip

    class HistoryPage(QWidget):
        def __init__(self, parent: Optional[QWidget] = None):
            super().__init__(parent)
            self.setObjectName("historyPage")
            self._cfg = load_config(None)
            self._rows: list = []       # MediaItemRow, for open-dir lookup
            self._build_ui()
            self._refresh()
            subscribe_theme(self, self._on_theme_changed)

        def _on_theme_changed(self) -> None:
            """换主题后刷新自绘颜色的控件。"""
            self.count_label.setStyleSheet(heading_qss(3))
            if hasattr(self, "_empty_state"):
                self._empty_state.refresh_text()

        def _build_ui(self):
            PageHeader = build_page_header()
            EmptyState = build_empty_state()
            StatChip = build_stat_chip()

            outer = QVBoxLayout(self)
            outer.setContentsMargins(SPACE_XL, SPACE_LG, SPACE_XL, SPACE_LG)
            outer.setSpacing(SPACE_LG)

            # ---- 页头 ----
            self._header = PageHeader(self)
            self._header.set_title("历史记录")
            self._header.set_subtitle(
                "查询最近 500 条下载记录。开启数据库后此页才有效。"
            )
            self.refresh_btn = PushButton("刷新", self)
            self.refresh_btn.clicked.connect(self._refresh)
            self.open_dir_btn = PushButton("打开保存目录", self)
            self.open_dir_btn.clicked.connect(self._open_selected_dir)
            self._header.add_action(self.open_dir_btn)
            self._header.add_action(self.refresh_btn)
            outer.addWidget(self._header)

            # ---- 统计条 ----
            stats_row = QHBoxLayout()
            stats_row.setSpacing(SPACE_MD)
            self._stat_total = StatChip(self)
            self._stat_total.set_kind("muted")
            self._stat_total.set_label("数据库中总数")
            self._stat_showing = StatChip(self)
            self._stat_showing.set_kind("running")
            self._stat_showing.set_label("本次显示")
            stats_row.addWidget(self._stat_total, 1)
            stats_row.addWidget(self._stat_showing, 1)
            stats_row.addStretch(2)
            outer.addLayout(stats_row)

            # ---- 主内容：表格 ↔ 空态 ----
            self._stack = QStackedWidget(self)
            self.table = TableWidget(self)
            self.table.setColumnCount(6)
            self.table.setHorizontalHeaderLabels([
                "平台", "ID", "标题", "作者", "下载时间", "保存目录",
            ])
            self.table.verticalHeader().hide()
            self.table.setWordWrap(False)
            self.table.setEditTriggers(TableWidget.NoEditTriggers)
            self.table.setSelectionBehavior(TableWidget.SelectRows)
            self.table.verticalHeader().setDefaultSectionSize(36)
            self._stack.addWidget(self.table)

            self._empty_state = EmptyState(self)
            self._stack.addWidget(self._empty_state)
            outer.addWidget(self._stack, 1)

            self.count_label = QLabel("", self)
            self.count_label.setStyleSheet(heading_qss(3))

        # ----------------------------------------------------------

        def _refresh(self) -> None:
            if not self._cfg.database:
                self._stat_total.set_value("—")
                self._stat_showing.set_value(0)
                self._empty_state.set_text(
                    "数据库未启用",
                    "请前往「设置」打开「启用数据库」开关，启用后此页会自动出现下载历史。",
                )
                self._stack.setCurrentWidget(self._empty_state)
                return
            try:
                import asyncio
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None
                if loop and loop.is_running():
                    loop.create_task(self._populate())
                else:
                    asyncio.run(self._populate())
            except Exception as exc:
                logger.exception("history refresh failed: %s", exc)

        async def _populate(self) -> None:
            db = Database(self._cfg.database_path)
            await db.initialize()
            try:
                rows = await db.list_recent(limit=500)
                total = await db.count()
            finally:
                await db.close()

            self._rows = rows
            self._stat_total.set_value(str(total))
            self._stat_showing.set_value(len(rows))
            if rows:
                self._stack.setCurrentWidget(self.table)
            else:
                self._empty_state.set_text(
                    "还没有下载记录",
                    "完成一次下载后，记录会自动出现在这里。",
                )
                self._stack.setCurrentWidget(self._empty_state)
            self.table.setRowCount(len(rows))
            for i, r in enumerate(rows):
                dl_time = ""
                if r.last_download_time:
                    try:
                        dl_time = datetime.fromtimestamp(r.last_download_time).strftime(
                            "%Y-%m-%d %H:%M"
                        )
                    except (OverflowError, OSError, ValueError):
                        dl_time = str(r.last_download_time)
                self.table.setItem(i, 0, _cell(r.platform or ""))
                self.table.setItem(i, 1, _cell(r.item_id or ""))
                self.table.setItem(i, 2, _cell(r.title or ""))
                self.table.setItem(i, 3, _cell(r.author_name or ""))
                self.table.setItem(i, 4, _cell(dl_time))
                self.table.setItem(i, 5, _cell(r.last_save_dir or ""))

        def _open_selected_dir(self) -> None:
            sel = self.table.selectedItems()
            if not sel:
                InfoBar.warning(
                    title="未选择记录",
                    content="请先在表格中选择一行。",
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=3000,
                )
                return
            row_idx = sel[0].row()
            if not (0 <= row_idx < len(self._rows)):
                return
            save_dir = self._rows[row_idx].last_save_dir or ""
            if not save_dir:
                InfoBar.warning(
                    title="无保存目录",
                    content="这条记录没有保存路径。",
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=3000,
                )
                return
            import os
            os.startfile(save_dir)   # Windows only; GUI is desktop-first

    def _cell(text: str):
        from PySide6.QtWidgets import QTableWidgetItem
        item = QTableWidgetItem(text)
        return item

    return HistoryPage, HistoryPage
