"""History page — real query over the SQLite database.

M5.1 adds the full table: platform / item_id / title / author /
download time / save dir, backed by :meth:`Database.list_recent`.
A refresh button + auto-refresh on page show keep it current.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Optional

logger = logging.getLogger("doubi.ui.pages.history")


def build_history_widgets():
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFileDialog
    from qfluentwidgets import (
        PushButton, TableWidget, StrongBodyLabel, InfoBar, InfoBarPosition,
    )

    from ...core.config import load_config
    from ...core.storage.database import Database

    class HistoryPage(QWidget):
        def __init__(self, parent: Optional[QWidget] = None):
            super().__init__(parent)
            self.setObjectName("historyPage")
            self._cfg = load_config(None)
            self._rows: list = []       # MediaItemRow, for open-dir lookup
            self._build_ui()
            self._refresh()

        def _build_ui(self):
            layout = QVBoxLayout(self)
            layout.setContentsMargins(24, 24, 24, 24)
            layout.setSpacing(12)

            title = StrongBodyLabel(self)
            title.setText("历史记录")
            layout.addWidget(title)

            row = QHBoxLayout()
            self.refresh_btn = PushButton("刷新", self)
            self.refresh_btn.clicked.connect(self._refresh)
            row.addWidget(self.refresh_btn)
            self.open_dir_btn = PushButton("打开保存目录", self)
            self.open_dir_btn.clicked.connect(self._open_selected_dir)
            row.addWidget(self.open_dir_btn)
            row.addStretch(1)
            self.count_label = QLabel("", self)
            row.addWidget(self.count_label)
            layout.addLayout(row)

            self.table = TableWidget(self)
            self.table.setColumnCount(6)
            self.table.setHorizontalHeaderLabels([
                "平台", "ID", "标题", "作者", "下载时间", "保存目录",
            ])
            self.table.verticalHeader().hide()
            self.table.setWordWrap(False)
            self.table.setEditTriggers(TableWidget.NoEditTriggers)
            self.table.setSelectionBehavior(TableWidget.SelectRows)
            layout.addWidget(self.table, 1)

        # ----------------------------------------------------------

        def _refresh(self) -> None:
            if not self._cfg.database:
                self.count_label.setText("数据库未启用（设置页可打开）")
                self.table.setRowCount(0)
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
            self.count_label.setText(f"共 {total} 条，显示最近 {len(rows)} 条")
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
