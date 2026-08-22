"""Download page — the Bili23-style "下载中 / 已完成" task manager.

The page is a passive observer of a :class:`TaskManager` (owned by
:mod:`doubi.ui.main_window`). It listens to its signals and renders
the tasks in two tabs:

* **下载中** — list of in-flight tasks with live progress bars
* **已完成** — list of finished / failed / cancelled tasks

Both lists support:

* sort by time / title / size / progress
* batch operations: 全部暂停 / 全部删除 / 清空已完成
* right-click on a task: 重新下载 / 删除 / 重新解析来源链接

The page is intentionally NOT responsible for parsing URLs; the
:class:`ParsePage` (in ``parse.py``) handles that and adds tasks
through the manager.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger("doubi.ui.pages.download")


def build_download_widgets():
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFontMetrics
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel, QHeaderView, QMenu,
        QAbstractItemView, QSizePolicy, QScrollArea,
    )
    from qfluentwidgets import (
        PushButton, ProgressBar, CardWidget, SegmentedWidget,
        StrongBodyLabel, InfoBar, InfoBarPosition, TableWidget, isDarkTheme,
    )

    from ...core.models import MediaItem
    from ..task_manager import TaskInfo, TaskManager

    # ------------------------------------------------------------------
    # Theme helpers
    # ------------------------------------------------------------------

    def _row_colors() -> tuple:
        """Row background (idle, hover) that follows the active theme."""
        if isDarkTheme():
            return "rgba(255, 255, 255, 0.055)", "rgba(255, 255, 255, 0.10)"
        return "rgba(0, 0, 0, 0.028)", "rgba(0, 0, 0, 0.055)"

    def _muted_color() -> str:
        """Secondary text color that stays readable in both themes."""
        return "#a0a0a0" if isDarkTheme() else "#8a8a8a"

    def _make_transparent(scroll, inner) -> None:
        """Strip a QScrollArea's own background and hide its scrollbar.

        A QScrollArea paints its viewport with the palette *base* color,
        which is near-white regardless of theme. Left alone it punches a
        bright rectangle into the CardWidget. Making the area, its
        viewport and the inner container all transparent lets the card's
        themed background show through instead.

        The vertical scrollbar is turned off but wheel scrolling keeps
        working, which is exactly what "隐藏滚动条" asks for.
        """
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
        )
        scroll.viewport().setStyleSheet("background: transparent;")
        if inner is not None:
            inner.setStyleSheet("background: transparent;")

    # ------------------------------------------------------------------
    # Task row widget
    # ------------------------------------------------------------------

    class TaskRow(QWidget):
        """One fixed-height row — status pill + title + progress + actions.

        Every row has the *same* height and the same column widths so the
        list reads as a table instead of a ragged pile of widgets. Long
        titles / messages are elided with "…" (never wrapped), and the
        full text always lives in the tooltip.
        """

        ROW_HEIGHT = 44

        STATUS_STYLE = {
            "running":   ("#0a6cbf", "rgba(10, 108, 191, 0.10)"),
            "completed": ("#127a1f", "rgba(18, 122, 31, 0.10)"),
            "failed":    ("#c02b2b", "rgba(192, 43, 43, 0.10)"),
            "cancelled": ("#6b6b6b", "rgba(107, 107, 107, 0.12)"),
        }

        def __init__(self, info: TaskInfo, parent: Optional[QWidget] = None):
            super().__init__(parent)
            self.info = info
            self._title_full = info.title or info.item.item_id
            self._message_full = ""
            self._build_ui()

        # ---- construction -------------------------------------------

        def _build_ui(self):
            self.setObjectName("taskRow")
            self.setFixedHeight(self.ROW_HEIGHT)
            self._apply_row_background()

            layout = QHBoxLayout(self)
            layout.setContentsMargins(12, 0, 12, 0)
            layout.setSpacing(12)

            self.status_label = QLabel(self._status_text(), self)
            self.status_label.setFixedWidth(56)
            self.status_label.setFixedHeight(20)
            self.status_label.setAlignment(Qt.AlignCenter)

            self.title_label = QLabel(self._title_full, self)
            self.title_label.setWordWrap(False)
            self.title_label.setStyleSheet("font-size: 13px;")
            self.title_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            self.title_label.setFixedHeight(20)
            self.title_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)

            # progress bar + percent stay glued together in a wrapper so
            # the number never drifts away from its bar.
            self.progress_wrap = QWidget(self)
            progress_wrap_layout = QHBoxLayout(self.progress_wrap)
            progress_wrap_layout.setContentsMargins(0, 0, 0, 0)
            progress_wrap_layout.setSpacing(8)

            self.progress = ProgressBar(self.progress_wrap)
            self.progress.setRange(0, 100)
            self.progress.setFixedWidth(150)
            self.progress.setFixedHeight(6)
            # A visible track keeps a 0% bar from reading as a hairline
            # divider (which is exactly how it looked before).
            if hasattr(self.progress, "setCustomBackgroundColor"):
                try:
                    self.progress.setCustomBackgroundColor("#e6e6e6", "#3a3a3a")
                except (TypeError, ValueError):
                    pass
            self._apply_progress_color()

            self.progress_percent = QLabel(
                self._percent_text(self.info.fraction), self.progress_wrap,
            )
            self.progress_percent.setStyleSheet(
                f"font-size: 12px; color: {_muted_color()};"
            )
            self.progress_percent.setFixedWidth(38)
            self.progress_percent.setAlignment(Qt.AlignVCenter | Qt.AlignRight)

            progress_wrap_layout.addWidget(self.progress, 0)
            progress_wrap_layout.addWidget(self.progress_percent, 0)
            self.progress_wrap.setFixedWidth(196)

            self.message_label = QLabel(self)
            self.message_label.setStyleSheet(
                f"font-size: 12px; color: {_muted_color()};"
            )
            self.message_label.setFixedWidth(150)
            self.message_label.setFixedHeight(20)
            self.message_label.setWordWrap(False)
            self.message_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)

            # The retry button lives inside a fixed-width holder so the
            # column keeps its space even while the button is hidden.
            # Without the holder a running row would pull "移除" 62px to
            # the left and break alignment with the failed rows.
            self.retry_slot = QWidget(self)
            self.retry_slot.setFixedWidth(52)
            retry_slot_layout = QHBoxLayout(self.retry_slot)
            retry_slot_layout.setContentsMargins(0, 0, 0, 0)
            retry_slot_layout.setSpacing(0)

            self.retry_btn = PushButton("重试", self.retry_slot)
            self.retry_btn.setFixedSize(52, 24)
            self.retry_btn.clicked.connect(self._on_retry)
            self.retry_btn.hide()
            retry_slot_layout.addWidget(self.retry_btn)

            self.remove_btn = PushButton("移除", self)
            self.remove_btn.setFixedSize(52, 24)
            self.remove_btn.clicked.connect(self._on_remove)

            layout.addWidget(self.status_label, 0)
            layout.addWidget(self.title_label, 1)
            layout.addWidget(self.progress_wrap, 0)
            layout.addWidget(self.message_label, 0)
            layout.addWidget(self.retry_slot, 0)
            layout.addWidget(self.remove_btn, 0)

            self._apply_status_color()
            self._refresh_texts()

        # ---- text helpers -------------------------------------------

        def _status_text(self) -> str:
            return {
                "running": "下载中",
                "completed": "完成",
                "failed": "失败",
                "cancelled": "已取消",
            }.get(self.info.status, self.info.status)

        def _percent_text(self, fraction: float) -> str:
            try:
                value = float(fraction)
            except (TypeError, ValueError):
                return "0%"
            if value <= 0:
                return "0%"
            if value >= 1:
                return "100%"
            return f"{value * 100:.0f}%"

        def _status_message(self) -> str:
            """A short, human-readable phase label (never a raw URL)."""
            info = self.info
            if info.status == "completed":
                return "已保存" if info.save_path else "下载完成"
            if info.status == "failed":
                return "下载失败"
            if info.status == "cancelled":
                return "已取消"
            return self._friendly_phase(info.message)

        @staticmethod
        def _friendly_phase(message: str) -> str:
            """Translate raw engine chatter into a compact Chinese phase.

            yt-dlp emits things like ``Starting https://...`` or
            ``download finished, post-processing`` — dumping those into a
            narrow column looked noisy, so we map them to short labels
            and keep the original text in the tooltip.
            """
            if not message:
                return "排队中"
            low = message.lower()
            if low.startswith("starting"):
                return "准备中"
            if "post-processing" in low or "merging" in low:
                return "合并音视频"
            if "downloading" in low:
                return "下载中"
            if "extracting" in low or "metadata" in low:
                return "读取信息"
            if "writing" in low or "thumbnail" in low or "subtitle" in low:
                return "写入附件"
            if len(message) <= 12:
                return message
            return message[:11] + "…"

        def _elide(self, label: QLabel, text: str) -> None:
            metrics = QFontMetrics(label.font())
            width = max(label.width() - 2, 40)
            label.setText(metrics.elidedText(text, Qt.ElideRight, width))

        def _refresh_texts(self) -> None:
            self._elide(self.title_label, self._title_full)
            self._message_full = self.info.message or self.info.error or ""
            self._elide(self.message_label, self._status_message())

        def resizeEvent(self, event) -> None:      # noqa: N802 (Qt naming)
            super().resizeEvent(event)
            self._refresh_texts()

        # ---- colouring ----------------------------------------------

        def _apply_row_background(self) -> None:
            """Give the row a themed, rounded background plate.

            Replaces the old bottom-border separator: with real spacing
            between rows a border would float in mid-air, while a subtle
            tinted plate reads as a proper list item and inherits the
            light/dark theme via :func:`_row_colors`.
            """
            idle, hover = _row_colors()
            self.setStyleSheet(
                "#taskRow {"
                f" background-color: {idle};"
                " border: none;"
                " border-radius: 6px;"
                "}"
                "#taskRow:hover {"
                f" background-color: {hover};"
                "}"
            )

        def _apply_status_color(self) -> None:
            color, background = self.STATUS_STYLE.get(
                self.info.status, ("#333333", "rgba(0, 0, 0, 0.06)"),
            )
            self.status_label.setStyleSheet(
                "QLabel {"
                f" color: {color};"
                f" background-color: {background};"
                " border-radius: 10px;"
                " font-size: 12px;"
                " font-weight: 600;"
                "}"
            )

        def _apply_progress_color(self) -> None:
            # Override fluent-widget's default bar accent only when the
            # task is in a terminal state so "completed = green" and
            # "failed = red" are visually obvious at a glance.
            status = self.info.status
            if status == "completed":
                self.progress.setCustomBarColor("#2ea121", "#2ea121")
            elif status == "failed":
                self.progress.setCustomBarColor("#e64545", "#e64545")
            elif status == "cancelled":
                self.progress.setCustomBarColor("#999", "#999")
            else:
                # running → default fluent blue
                try:
                    self.progress.setCustomBarColor()
                except TypeError:
                    # Newer QFluentWidget builds require explicit args
                    pass

        # ---- state sync ---------------------------------------------

        def update_from(self, info: TaskInfo) -> None:
            self.info = info
            if info.title:
                self._title_full = info.title
            self.status_label.setText(self._status_text())
            self._apply_status_color()

            fraction = info.fraction
            if info.status == "completed" and (fraction is None or fraction < 1):
                # Defensive: TaskManager already sets fraction=1 on the
                # info object before emitting finished, but we force it
                # here so the bar is always visually full for done tasks.
                fraction = 1.0
            try:
                self.progress.setValue(int(float(fraction) * 100))
            except (TypeError, ValueError):
                self.progress.setValue(0)
            self.progress_percent.setText(self._percent_text(fraction))
            self._apply_progress_color()
            self._refresh_texts()

            # Retryable states get an extra button; running/completed
            # rows keep the column empty so widths stay aligned.
            self.retry_btn.setVisible(info.status in ("failed", "cancelled"))

            tip = [self._title_full, "", info.item.source_url]
            if info.error:
                tip.append(f"\n错误详情:\n{info.error}")
            elif self._message_full:
                tip.append(f"\n{self._message_full}")
            self.setToolTip("\n".join(tip))
            self.title_label.setToolTip("\n".join(tip))
            self.message_label.setToolTip(info.error or self._message_full)

        # ---- actions ------------------------------------------------

        def _on_remove(self) -> None:
            self._on_remove_requested(self)

        def _on_retry(self) -> None:
            if self._on_retry_requested is not None:
                self._on_retry_requested(self)

        _on_remove_requested = None
        _on_retry_requested = None

    # ------------------------------------------------------------------
    # Page
    # ------------------------------------------------------------------

    class DownloadPage(QWidget):
        def __init__(self, parent: Optional[QWidget] = None):
            super().__init__(parent)
            self.setObjectName("downloadPage")
            self._manager: Optional[TaskManager] = None
            # task_id -> row widget
            self._rows: dict[str, TaskRow] = {}
            self._build_ui()
            # Row tints are baked into stylesheets, so they must be
            # repainted when the user flips light/dark at runtime.
            try:
                from qfluentwidgets import qconfig
                qconfig.themeChanged.connect(self._on_theme_changed)
            except (ImportError, AttributeError):
                pass

        def _on_theme_changed(self, *_args) -> None:
            """Re-tint every existing row after a light/dark switch."""
            muted = _muted_color()
            for row in self._rows.values():
                row._apply_row_background()
                row.progress_percent.setStyleSheet(
                    f"font-size: 12px; color: {muted};"
                )
                row.message_label.setStyleSheet(
                    f"font-size: 12px; color: {muted};"
                )

        def set_task_manager(self, manager: TaskManager) -> None:
            # Disconnect previous manager if any (defensive)
            if self._manager is not None:
                self._disconnect_signals()
            self._manager = manager
            self._connect_signals()
            self._refresh_all()

        # ---- UI build ------------------------------------------------

        def _build_ui(self):
            outer = QVBoxLayout(self)
            outer.setContentsMargins(24, 24, 24, 24)
            outer.setSpacing(12)

            header = QHBoxLayout()
            title = StrongBodyLabel(self)
            title.setText("下载")
            header.addWidget(title)
            header.addStretch(1)
            self.open_output_btn = PushButton("打开下载目录", self)
            self.open_output_btn.clicked.connect(self._on_open_output_dir)
            header.addWidget(self.open_output_btn)
            outer.addLayout(header)

            # Tab switcher: 下载中 / 已完成
            self.tabs = SegmentedWidget(self)
            self.active_tab = self.tabs.addItem(
                "active", "下载中", onClick=lambda: self._show_view("active"),
            )
            self.completed_tab = self.tabs.addItem(
                "completed", "已完成", onClick=lambda: self._show_view("completed"),
            )
            self.tabs.setCurrentItem("active")
            outer.addWidget(self.tabs)

            # Active tasks card
            self.active_card = CardWidget(self)
            active_layout = QVBoxLayout(self.active_card)
            active_layout.setContentsMargins(12, 12, 12, 12)
            active_layout.setSpacing(8)
            active_header = QHBoxLayout()
            self.active_summary = QLabel("暂无正在下载的任务。", self.active_card)
            active_header.addWidget(self.active_summary, 1)
            self.pause_all_btn = PushButton("全部暂停", self.active_card)
            self.pause_all_btn.setEnabled(False)   # pause-all is TODO
            self.remove_all_btn = PushButton("全部删除", self.active_card)
            self.remove_all_btn.clicked.connect(self._remove_all_active)
            active_header.addWidget(self.pause_all_btn)
            active_header.addWidget(self.remove_all_btn)
            active_layout.addLayout(active_header)

            self.active_list = QWidget(self.active_card)
            self.active_list_layout = QVBoxLayout(self.active_list)
            self.active_list_layout.setContentsMargins(0, 0, 0, 0)
            self.active_list_layout.setSpacing(6)
            self.active_list_layout.addStretch(1)
            self.active_scroll = QScrollArea(self.active_card)
            self.active_list.setParent(self.active_scroll)
            self.active_scroll.setWidget(self.active_list)
            _make_transparent(self.active_scroll, self.active_list)
            active_layout.addWidget(self.active_scroll, 1)
            outer.addWidget(self.active_card, 1)

            # Completed tasks card
            self.completed_card = CardWidget(self)
            completed_layout = QVBoxLayout(self.completed_card)
            completed_layout.setContentsMargins(12, 12, 12, 12)
            completed_layout.setSpacing(8)
            completed_header = QHBoxLayout()
            self.completed_summary = QLabel("暂无已完成的任务。", self.completed_card)
            completed_header.addWidget(self.completed_summary, 1)
            self.retry_all_btn = PushButton("重试全部失败", self.completed_card)
            self.retry_all_btn.setEnabled(False)
            self.retry_all_btn.clicked.connect(self._on_retry_all_failed)
            completed_header.addWidget(self.retry_all_btn)
            self.clear_completed_btn = PushButton("清空", self.completed_card)
            self.clear_completed_btn.clicked.connect(self._on_clear_completed)
            completed_header.addWidget(self.clear_completed_btn)
            completed_layout.addLayout(completed_header)

            self.completed_list = QWidget(self.completed_card)
            self.completed_list_layout = QVBoxLayout(self.completed_list)
            self.completed_list_layout.setContentsMargins(0, 0, 0, 0)
            self.completed_list_layout.setSpacing(6)
            self.completed_list_layout.addStretch(1)
            self.completed_scroll = QScrollArea(self.completed_card)
            self.completed_list.setParent(self.completed_scroll)
            self.completed_scroll.setWidget(self.completed_list)
            _make_transparent(self.completed_scroll, self.completed_list)
            completed_layout.addWidget(self.completed_scroll, 1)
            outer.addWidget(self.completed_card, 1)

            self._show_view("active")

        def _show_view(self, which: str) -> None:
            if which == "active":
                self.active_card.show()
                self.completed_card.hide()
            else:
                self.active_card.hide()
                self.completed_card.show()

        # ---- manager wiring -----------------------------------------

        def _connect_signals(self) -> None:
            if self._manager is None:
                return
            m = self._manager
            m.task_added.connect(self._on_task_added)
            m.task_progress.connect(self._on_task_progress)
            m.task_finished.connect(self._on_task_finished)
            m.task_failed.connect(self._on_task_failed)
            m.task_removed.connect(self._on_task_removed)

        def _disconnect_signals(self) -> None:
            if self._manager is None:
                return
            m = self._manager
            try:
                m.task_added.disconnect(self._on_task_added)
                m.task_progress.disconnect(self._on_task_progress)
                m.task_finished.disconnect(self._on_task_finished)
                m.task_failed.disconnect(self._on_task_failed)
                m.task_removed.disconnect(self._on_task_removed)
            except (RuntimeError, TypeError):
                pass

        # ---- rendering -----------------------------------------------

        def _refresh_all(self) -> None:
            """Render the current state of the manager."""
            if self._manager is None:
                return
            for info in self._manager.active_tasks():
                self._render_active_row(info)
            for info in self._manager.completed_tasks():
                self._render_completed_row(info)
            self._update_summaries()

        def _render_active_row(self, info: TaskInfo) -> None:
            row = self._rows.get(info.task_id)
            if row is not None:
                # Already rendered — this is a retry, so pull the row back
                # out of the completed list into the active one.
                self.completed_list_layout.removeWidget(row)
                row.setParent(self.active_list)
                idx = self.active_list_layout.count() - 1
                self.active_list_layout.insertWidget(idx, row)
                row.show()
                row.update_from(info)
                return
            row = TaskRow(info, self.active_list)
            row._on_remove_requested = self._on_remove_row
            row._on_retry_requested = self._on_retry_row
            # Insert before the trailing stretch
            idx = self.active_list_layout.count() - 1
            self.active_list_layout.insertWidget(idx, row)
            self._rows[info.task_id] = row

        def _render_completed_row(self, info: TaskInfo) -> None:
            """Move a task's row from the active list to the completed list.

            We *reuse* the existing row widget rather than destroy +
            recreate it: that avoids flicker and keeps stable widget
            references (which the UI signals rely on).
            """
            row = self._rows.get(info.task_id)
            if row is None:
                # The page was created after the task finished
                row = TaskRow(info, self.completed_list)
                row._on_remove_requested = self._on_remove_row
                row._on_retry_requested = self._on_retry_row
                idx = self.completed_list_layout.count() - 1
                self.completed_list_layout.insertWidget(idx, row)
                self._rows[info.task_id] = row
                row.update_from(info)
                return

            # Detach from the active layout, attach to the completed one.
            self.active_list_layout.removeWidget(row)
            row.setParent(self.completed_list)
            idx = self.completed_list_layout.count() - 1
            self.completed_list_layout.insertWidget(idx, row)
            row.show()
            row.update_from(info)

        def _on_remove_row(self, row: TaskRow) -> None:
            if self._manager is None:
                return
            self._manager.remove(row.info.task_id)

        def _on_retry_row(self, row: TaskRow) -> None:
            if self._manager is None:
                return
            task_id = row.info.task_id
            if self._manager.retry(task_id):
                self.tabs.setCurrentItem("active")
                self._show_view("active")
            else:
                self._toast(InfoBar.warning, "无法重试", "该任务已在下载队列中")

        def _on_retry_all_failed(self) -> None:
            if self._manager is None:
                return
            started = self._manager.retry_all_failed()
            if started:
                self.tabs.setCurrentItem("active")
                self._show_view("active")
                self._toast(InfoBar.success, "已重新下载", f"共 {started} 个失败任务")
            else:
                self._toast(InfoBar.warning, "没有可重试的任务", "已完成列表中没有失败记录")

        def _on_task_added(self, task_id: str) -> None:
            if self._manager is None:
                return
            info = self._manager.get(task_id)
            if info is None:
                return
            self._render_active_row(info)
            self._update_summaries()

        def _on_task_progress(self, task_id: str, fraction: float, message: str) -> None:
            row = self._rows.get(task_id)
            if row is None:
                return
            info = self._manager.get(task_id) if self._manager else None
            if info is not None:
                row.update_from(info)
            self._update_summaries()

        def _on_task_finished(self, task_id: str, title: str) -> None:
            self._move_to_completed(task_id)
            self._toast(InfoBar.success, "下载完成", title or task_id)

        def _on_task_failed(self, task_id: str, message: str) -> None:
            self._move_to_completed(task_id)
            self._toast(InfoBar.error, "下载失败", message or task_id)

        def _on_task_removed(self, task_id: str) -> None:
            row = self._rows.pop(task_id, None)
            if row is not None:
                self._remove_row_widget(row)
            self._update_summaries()

        def _move_to_completed(self, task_id: str) -> None:
            if self._manager is None:
                return
            info = self._manager.get(task_id)
            if info is None:
                return
            self._render_completed_row(info)
            self._update_summaries()

        def _remove_row_widget(self, row: TaskRow) -> None:
            self.active_list_layout.removeWidget(row)
            self.completed_list_layout.removeWidget(row)
            row.setParent(None)
            row.deleteLater()

        def _remove_all_active(self) -> None:
            if self._manager is None:
                return
            for info in list(self._manager.active_tasks()):
                self._manager.remove(info.task_id)

        def _on_clear_completed(self) -> None:
            if self._manager is None:
                return
            self._manager.clear_completed()

        def _update_summaries(self) -> None:
            if self._manager is None:
                self.active_summary.setText("暂无正在下载的任务。")
                self.completed_summary.setText("暂无已完成的任务。")
                self.retry_all_btn.setEnabled(False)
                return
            active = self._manager.active_count()
            completed = self._manager.completed_count()
            failed = self._manager.failed_count()
            self.active_summary.setText(
                f"{active} 个任务正在下载" if active else "暂无正在下载的任务。",
            )
            if completed:
                text = f"已完成 {completed} 个任务"
                if failed:
                    text += f"（其中 {failed} 个失败）"
                self.completed_summary.setText(text)
            else:
                self.completed_summary.setText("暂无已完成的任务。")
            self.retry_all_btn.setEnabled(bool(failed))

        def _on_open_output_dir(self) -> None:
            from ...core.config import load_config
            cfg = load_config(None)
            out = Path(cfg.output_root)
            out.mkdir(parents=True, exist_ok=True)
            try:
                if sys.platform.startswith("win"):
                    os.startfile(str(out))   # type: ignore[attr-defined]
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", str(out)])
                else:
                    subprocess.Popen(["xdg-open", str(out)])
            except Exception as exc:   # noqa: BLE001
                logger.warning("open output dir failed: %s", exc)
                self._toast(InfoBar.error, "打开失败", f"请手动前往 {out}。")

        def _toast(self, kind, title: str, content: str) -> None:
            kind(
                title=title, content=content, parent=self,
                position=InfoBarPosition.TOP_RIGHT, duration=4000,
            )

    return DownloadPage, DownloadPage
