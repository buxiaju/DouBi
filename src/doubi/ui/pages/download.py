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
        StrongBodyLabel, InfoBar, InfoBarPosition, TableWidget,
    )

    from ...core.models import MediaItem
    from ..task_manager import TaskInfo, TaskManager
    from ..theme import (
        FONT_FAMILY, SPACE_LG, SPACE_MD, SPACE_SM, SPACE_XL, SPACE_XS,
        TYPE_BODY, TYPE_CAPTION, TYPE_H2, RADIUS_CARD,
        heading_qss, muted_qss as _muted_qss, subscribe_theme, token,
    )
    from ..widgets import (
        build_empty_state, build_page_header, build_stat_chip,
    )

    # ------------------------------------------------------------------
    # Theme helpers
    # ------------------------------------------------------------------

    def _row_colors() -> tuple:
        """行背景（常态, 悬浮），取自当前主题包的 token。"""
        return token("row_odd"), token("row_even")

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

        # 行高的兜底值。真实高度优先取主题包的 row_height，
        # 保留类属性是为了 token 缺失时仍有确定行为。
        ROW_HEIGHT = 44

        @staticmethod
        def _status_style(status: str) -> tuple:
            """状态胶囊的（前景, 背景），随主题包变化。

            旧代码用类级常量 STATUS_STYLE 写死了浅色系的值，切到暗色
            主题后「失败」的深红在深底上几乎看不见。改成按需从 token 取。
            """
            fg = token(f"status_{status}_fg")
            bg = token(f"status_{status}_bg")
            if fg is None or bg is None:
                return token("text_primary"), token("bg_hover")
            return fg, bg

        def __init__(self, info: TaskInfo, parent: Optional[QWidget] = None):
            super().__init__(parent)
            self.info = info
            self._title_full = info.title or info.item.item_id
            self._message_full = ""
            self._build_ui()

        # ---- construction -------------------------------------------

        def _build_ui(self):
            self.setObjectName("taskRow")
            self.setFixedHeight(int(token("row_height", self.ROW_HEIGHT)))
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
            self._apply_progress_track()
            self._apply_progress_color()

            self.progress_percent = QLabel(
                self._percent_text(self.info.fraction), self.progress_wrap,
            )
            self.progress_percent.setStyleSheet(_muted_qss())
            self.progress_percent.setFixedWidth(38)
            self.progress_percent.setAlignment(Qt.AlignVCenter | Qt.AlignRight)

            progress_wrap_layout.addWidget(self.progress, 0)
            progress_wrap_layout.addWidget(self.progress_percent, 0)
            self.progress_wrap.setFixedWidth(196)

            self.message_label = QLabel(self)
            self.message_label.setStyleSheet(_muted_qss())
            self.message_label.setFixedWidth(150)
            self.message_label.setFixedHeight(20)
            self.message_label.setWordWrap(False)
            self.message_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)

            # Same fixed-width holder trick as the retry column: the
            # button swaps between 暂停 / 继续 and hides entirely once the
            # task is terminal, but the column must never change width.
            self.pause_slot = QWidget(self)
            self.pause_slot.setFixedWidth(52)
            pause_slot_layout = QHBoxLayout(self.pause_slot)
            pause_slot_layout.setContentsMargins(0, 0, 0, 0)
            pause_slot_layout.setSpacing(0)

            self.pause_btn = PushButton("暂停", self.pause_slot)
            self.pause_btn.setFixedHeight(28)
            self.pause_btn.setMinimumWidth(56)
            self.pause_btn.clicked.connect(self._on_pause)
            pause_slot_layout.addWidget(self.pause_btn)

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
            self.retry_btn.setFixedHeight(28)
            self.retry_btn.setMinimumWidth(56)
            self.retry_btn.clicked.connect(self._on_retry)
            self.retry_btn.hide()
            retry_slot_layout.addWidget(self.retry_btn)

            self.remove_btn = PushButton("移除", self)
            self.remove_btn.setFixedHeight(28)
            self.remove_btn.setMinimumWidth(56)
            self.remove_btn.clicked.connect(self._on_remove)

            layout.addWidget(self.status_label, 0)
            layout.addWidget(self.title_label, 1)
            layout.addWidget(self.progress_wrap, 0)
            layout.addWidget(self.message_label, 0)
            layout.addWidget(self.pause_slot, 0)
            layout.addWidget(self.retry_slot, 0)
            layout.addWidget(self.remove_btn, 0)

            self._apply_status_color()
            self._sync_pause_btn()
            self._refresh_texts()

        # ---- text helpers -------------------------------------------

        def _status_text(self) -> str:
            return {
                "running": "下载中",
                "paused": "已暂停",
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
            if info.status == "paused":
                # Keep the percentage meaningful: a paused row still shows
                # how far it got, so the message says why it stopped.
                return "已暂停"
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
            """给行画一块带圆角的主题底板。

            取代早期的下边框分割线：行间已有间距，边框会悬在半空；
            而一块淡色底板既像列表项，又能通过 :func:`_row_colors`
            和 radius token 跟着主题包变化。
            """
            idle, hover = _row_colors()
            radius = token("radius", 6)
            self.setStyleSheet(
                "#taskRow {"
                f" background-color: {idle};"
                " border: none;"
                f" border-radius: {radius}px;"
                "}"
                "#taskRow:hover {"
                f" background-color: {hover};"
                "}"
            )

        def _apply_status_color(self) -> None:
            color, background = self._status_style(self.info.status)
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
            # 终态用语义色（完成=绿 / 失败=红）让状态一眼可辨；
            # 颜色全部来自主题包，暗色主题下会自动换成提亮版本。
            status = self.info.status
            color = {
                "completed": token("progress_success"),
                "failed": token("progress_error"),
                "cancelled": token("text_muted"),
                "paused": token("progress_paused"),
            }.get(status) or token("progress_normal")
            # setCustomBarColor(亮, 暗) 需要两个颜色，但主题包自带明度，
            # 当前生效的只有一套值，所以同一个颜色传两遍即可。
            self.progress.setCustomBarColor(color, color)

        def _apply_progress_track(self) -> None:
            """进度条底槽：0% 时若无底槽会看起来像一条分割线。"""
            if not hasattr(self.progress, "setCustomBackgroundColor"):
                return
            track = token("bg_hover")
            try:
                self.progress.setCustomBackgroundColor(track, track)
            except (TypeError, ValueError):
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
            self._sync_pause_btn()

            tip = [self._title_full, "", info.item.source_url]
            if info.error:
                tip.append(f"\n错误详情:\n{info.error}")
            elif self._message_full:
                tip.append(f"\n{self._message_full}")
            self.setToolTip("\n".join(tip))
            self.title_label.setToolTip("\n".join(tip))
            self.message_label.setToolTip(info.error or self._message_full)

        def _sync_pause_btn(self) -> None:
            """Make the button describe the *next* action, not the state.

            A running row offers 暂停, a paused row offers 继续, and a
            terminal row offers nothing — but the holder keeps its width
            so hiding the button never shifts the 移除 column.
            """
            status = self.info.status
            self.pause_btn.setVisible(status in ("running", "paused"))
            self.pause_btn.setText("继续" if status == "paused" else "暂停")

        # ---- actions ------------------------------------------------

        def _on_remove(self) -> None:
            self._on_remove_requested(self)

        def _on_retry(self) -> None:
            if self._on_retry_requested is not None:
                self._on_retry_requested(self)

        def _on_pause(self) -> None:
            if self._on_pause_requested is not None:
                self._on_pause_requested(self)

        _on_remove_requested = None
        _on_retry_requested = None
        _on_pause_requested = None

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
            # 行底色、状态胶囊、进度条颜色都被烘进了 stylesheet，
            # 运行时换主题必须重刷一遍。统一走 subscribe_theme，
            # 它会在控件销毁时自动退订，不会留下野回调。
            subscribe_theme(self, self._on_theme_changed)

        def _on_theme_changed(self, *_args) -> None:
            """换主题后重新给已存在的行上色。"""
            height = int(token("row_height", TaskRow.ROW_HEIGHT))
            for row in self._rows.values():
                row.setFixedHeight(height)
                row._apply_row_background()
                row._apply_status_color()
                row._apply_progress_track()
                row._apply_progress_color()
                row.progress_percent.setStyleSheet(_muted_qss())
                row.message_label.setStyleSheet(_muted_qss())
            # 顶部 summary 走 heading_qss(3)，重新刷一次颜色
            self.active_summary.setStyleSheet(heading_qss(3))
            self.completed_summary.setStyleSheet(heading_qss(3))

        def set_task_manager(self, manager: TaskManager) -> None:
            # Disconnect previous manager if any (defensive)
            if self._manager is not None:
                self._disconnect_signals()
            self._manager = manager
            self._connect_signals()
            self._refresh_all()

        # ---- UI build ------------------------------------------------

        def _build_ui(self):
            PageHeader = build_page_header()
            EmptyState = build_empty_state()
            StatChip = build_stat_chip()

            outer = QVBoxLayout(self)
            outer.setContentsMargins(SPACE_XL, SPACE_LG, SPACE_XL, SPACE_LG)
            outer.setSpacing(SPACE_LG)

            # ---- 页头 ----
            self._header = PageHeader(self)
            self._header.set_title("下载")
            self._header.set_subtitle("实时查看下载进度、暂停与重试，所有状态在两侧标签页间切换。")
            self.open_output_btn = PushButton("打开下载目录", self)
            self.open_output_btn.clicked.connect(self._on_open_output_dir)
            self._header.add_action(self.open_output_btn)
            outer.addWidget(self._header)

            # ---- 统计条（4 个 stat chip） ----
            stats_row = QHBoxLayout()
            stats_row.setSpacing(SPACE_MD)
            self._stat_running = StatChip(self)
            self._stat_running.set_kind("running")
            self._stat_running.set_label("正在下载")
            self._stat_paused = StatChip(self)
            self._stat_paused.set_kind("paused")
            self._stat_paused.set_label("已暂停")
            self._stat_completed = StatChip(self)
            self._stat_completed.set_kind("completed")
            self._stat_completed.set_label("已完成")
            self._stat_failed = StatChip(self)
            self._stat_failed.set_kind("failed")
            self._stat_failed.set_label("失败")
            for w in (self._stat_running, self._stat_paused,
                      self._stat_completed, self._stat_failed):
                stats_row.addWidget(w, 1)
            outer.addLayout(stats_row)

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
            active_layout.setContentsMargins(SPACE_MD, SPACE_MD, SPACE_MD, SPACE_MD)
            active_layout.setSpacing(SPACE_MD)
            active_header = QHBoxLayout()
            active_header.setSpacing(SPACE_SM)
            self.active_summary = QLabel("暂无正在下载的任务。", self.active_card)
            self.active_summary.setStyleSheet(heading_qss(3))
            active_header.addWidget(self.active_summary, 1)
            self.pause_all_btn = PushButton("全部暂停", self.active_card)
            self.pause_all_btn.setEnabled(False)
            self.pause_all_btn.clicked.connect(self._on_pause_all)
            self.remove_all_btn = PushButton("全部删除", self.active_card)
            self.remove_all_btn.clicked.connect(self._remove_all_active)
            active_header.addWidget(self.pause_all_btn)
            active_header.addWidget(self.remove_all_btn)
            active_layout.addLayout(active_header)

            self.active_list = QWidget(self.active_card)
            self.active_list_layout = QVBoxLayout(self.active_list)
            self.active_list_layout.setContentsMargins(0, 0, 0, 0)
            self.active_list_layout.setSpacing(SPACE_SM)
            self.active_list_layout.addStretch(1)
            self.active_scroll = QScrollArea(self.active_card)
            self.active_list.setParent(self.active_scroll)
            self.active_scroll.setWidget(self.active_list)
            _make_transparent(self.active_scroll, self.active_list)
            active_layout.addWidget(self.active_scroll, 1)
            outer.addWidget(self.active_card, 1)

            # 活跃列表的空态：塞在同一个 scroll 区域里、跟着列表 0/非 0 切换
            self._active_empty = EmptyState(self.active_list)
            self._active_empty.set_text(
                "暂无正在下载的任务",
                "去「解析」粘贴链接，勾选后加入下载队列即可",
            )
            self.active_list_layout.insertWidget(0, self._active_empty)

            # Completed tasks card
            self.completed_card = CardWidget(self)
            completed_layout = QVBoxLayout(self.completed_card)
            completed_layout.setContentsMargins(SPACE_MD, SPACE_MD, SPACE_MD, SPACE_MD)
            completed_layout.setSpacing(SPACE_MD)
            completed_header = QHBoxLayout()
            completed_header.setSpacing(SPACE_SM)
            self.completed_summary = QLabel("暂无已完成的任务。", self.completed_card)
            self.completed_summary.setStyleSheet(heading_qss(3))
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
            self.completed_list_layout.setSpacing(SPACE_SM)
            self.completed_list_layout.addStretch(1)
            self.completed_scroll = QScrollArea(self.completed_card)
            self.completed_list.setParent(self.completed_scroll)
            self.completed_scroll.setWidget(self.completed_list)
            _make_transparent(self.completed_scroll, self.completed_list)
            completed_layout.addWidget(self.completed_scroll, 1)
            outer.addWidget(self.completed_card, 1)

            self._completed_empty = EmptyState(self.completed_list)
            self._completed_empty.set_text(
                "尚无已完成的任务",
                "下载完成后会自动归档到这里，支持重试与清理",
            )
            self.completed_list_layout.insertWidget(0, self._completed_empty)

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
            row._on_pause_requested = self._on_pause_row
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
                row._on_pause_requested = self._on_pause_row
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

        def _on_pause_row(self, row: TaskRow) -> None:
            """Toggle one task between running and paused.

            The row shows a single button whose meaning follows the task
            state, so the page decides the direction here rather than
            making the row track it.
            """
            if self._manager is None:
                return
            task_id = row.info.task_id
            if row.info.status == "paused":
                self._manager.resume(task_id)
            else:
                self._manager.pause(task_id)
            info = self._manager.get(task_id)
            if info is not None:
                row.update_from(info)
            self._update_summaries()

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

        def _on_pause_all(self) -> None:
            """One button for both directions, decided by what's running.

            Pausing wins when anything is still running; only once the
            active list is fully paused does the button become 全部继续.
            That keeps a single click from immediately undoing itself on
            a mixed list.
            """
            if self._manager is None:
                return
            if self._manager.running_count():
                changed = self._manager.pause_all()
            else:
                changed = self._manager.resume_all()
            if changed:
                self._refresh_active_rows()
            self._update_summaries()

        def _refresh_active_rows(self) -> None:
            """Re-render active rows after a bulk state change.

            Bulk pause/resume flips several TaskInfo objects without
            going through the per-row signal path, so the widgets need an
            explicit nudge to pick up the new status.
            """
            if self._manager is None:
                return
            for info in self._manager.active_tasks():
                row = self._rows.get(info.task_id)
                if row is not None:
                    row.update_from(info)

        def _on_clear_completed(self) -> None:
            if self._manager is None:
                return
            self._manager.clear_completed()

        def _update_summaries(self) -> None:
            if self._manager is None:
                self.active_summary.setText("暂无正在下载的任务。")
                self.completed_summary.setText("暂无已完成的任务。")
                self.retry_all_btn.setEnabled(False)
                self.pause_all_btn.setEnabled(False)
                self._update_stat_chips(0, 0, 0, 0)
                self._update_empty_visibility(0, 0)
                return
            active = self._manager.active_count()
            completed = self._manager.completed_count()
            failed = self._manager.failed_count()
            paused = self._manager.paused_count()
            running = self._manager.running_count()
            if not active:
                self.active_summary.setText("暂无正在下载的任务。")
            elif paused:
                # Spell out the split so a stalled-looking list is
                # explained by the summary rather than by the rows alone.
                self.active_summary.setText(
                    f"{running} 个任务正在下载，{paused} 个已暂停",
                )
            else:
                self.active_summary.setText(f"{active} 个任务正在下载")
            # The button mirrors _on_pause_all's own rule, so its label
            # always matches what a click would actually do.
            self.pause_all_btn.setEnabled(bool(active))
            self.pause_all_btn.setText("全部暂停" if running else "全部继续")
            if completed:
                text = f"已完成 {completed} 个任务"
                if failed:
                    text += f"（其中 {failed} 个失败）"
                self.completed_summary.setText(text)
            else:
                self.completed_summary.setText("暂无已完成的任务。")
            self.retry_all_btn.setEnabled(bool(failed))
            self._update_stat_chips(running, paused, completed, failed)
            self._update_empty_visibility(active, completed)

        def _update_stat_chips(
            self, running: int, paused: int, completed: int, failed: int,
        ) -> None:
            """把数字推到顶部的 4 个 chip——空时显示 0 而非隐藏。"""
            self._stat_running.set_value(running)
            self._stat_paused.set_value(paused)
            self._stat_completed.set_value(completed)
            self._stat_failed.set_value(failed)

        def _update_empty_visibility(self, active: int, completed: int) -> None:
            """列表为空时显示 EmptyState，否则隐藏。"""
            self._active_empty.setVisible(active == 0)
            self._completed_empty.setVisible(completed == 0)

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
