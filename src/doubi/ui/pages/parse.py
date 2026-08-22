"""Parse page — the Bili23-style "parse → pick → send to download" page.

This is the default landing page of the GUI. The user pastes one or
more URLs (one per line) and clicks **解析**. Each URL is sent through
``pipeline.parse_and_expand``; the resulting ``MediaItem`` list is
shown in a table where the user can:

* search by keyword (实时过滤)
* 全选 / 全不选 / 行号范围选择
* 右键：解析此项 / 在浏览器中打开 / 作为单视频下载 / 查看元数据 / 查看封面
* 点击 **下载选中** to send the checked rows to the :class:`TaskManager`,
  which is shared with the :class:`DownloadPage` (rendered in a
  separate tab).

The "快速下载" path (**开始下载**) is kept for one-shot single URLs
that don't need a picker.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("doubi.ui.pages.parse")


def build_parse_widgets():
    from PySide6.QtCore import QObject, Qt, QUrl, Signal
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPlainTextEdit,
        QAbstractItemView, QHeaderView, QMenu,
    )
    from qfluentwidgets import (
        ComboBox, PushButton, CardWidget, SearchLineEdit,
        StrongBodyLabel, InfoBar, InfoBarPosition, TableWidget,
    )

    from ...core.config import AppConfig, load_config
    from ...core.engine_loader import build_default_pipeline
    from ...core.models import DownloadOptions, MediaItem
    from ...core.pipeline import DownloadPipeline

    class ParsePage(QWidget):
        """The "解析" tab of the main window."""

        def __init__(self, parent: Optional[QWidget] = None):
            super().__init__(parent)
            self.setObjectName("parsePage")
            self._cfg: AppConfig = load_config(None)
            self._pipeline: DownloadPipeline = build_default_pipeline()
            self._parsed_items: list[MediaItem] = []
            # Set later via set_task_manager(...) from MainWindow.
            self._task_manager = None
            self._build_ui()

        # ---- public API ----------------------------------------------

        def set_task_manager(self, manager) -> None:
            self._task_manager = manager

        # ---- UI build ------------------------------------------------

        def _build_ui(self):
            layout = QVBoxLayout(self)
            layout.setContentsMargins(24, 24, 24, 24)
            layout.setSpacing(12)

            title = StrongBodyLabel(self)
            title.setText("解析")
            layout.addWidget(title)

            hint = QLabel(
                "粘贴链接（每行一个），支持抖音 / B 站 / 合集 / 用户主页 / 短链接。",
                self,
            )
            hint.setStyleSheet("color: gray;")
            layout.addWidget(hint)

            # URL input
            self.url_input = QPlainTextEdit(self)
            self.url_input.setPlaceholderText(
                "https://www.bilibili.com/video/BV1GJ411x7h7\n"
                "https://space.bilibili.com/486906719\n"
                "https://www.bilibili.com/list/ml12345\n"
                "https://www.douyin.com/video/7123456789012345678"
            )
            self.url_input.setFixedHeight(100)
            layout.addWidget(self.url_input)

            # Buttons row: parse / quick download on the right
            btn_row = QHBoxLayout()
            btn_row.addStretch(1)
            self.parse_btn = PushButton("解析", self)
            self.parse_btn.clicked.connect(self._on_parse_clicked)
            self.quick_download_btn = PushButton("快速下载", self)
            self.quick_download_btn.setToolTip("解析第一个 URL 并直接加入下载队列")
            self.quick_download_btn.clicked.connect(self._on_quick_download_clicked)
            btn_row.addWidget(self.parse_btn)
            btn_row.addWidget(self.quick_download_btn)
            btn_row.addSpacing(12)
            btn_row.addWidget(QLabel("平台：", self))
            self.platform_combo = ComboBox(self)
            self.platform_combo.addItems(["自动识别", "抖音", "B 站"])
            self.platform_combo.setCurrentIndex(0)
            btn_row.addWidget(self.platform_combo)
            layout.addLayout(btn_row)

            # Result card: search + summary + table
            self.result_card = CardWidget(self)
            self.result_layout = QVBoxLayout(self.result_card)
            self.result_layout.setContentsMargins(12, 12, 12, 12)
            self.result_layout.setSpacing(8)

            top_row = QHBoxLayout()
            self.result_summary = QLabel("尚未解析。", self.result_card)
            top_row.addWidget(self.result_summary, 1)
            self.search_box = SearchLineEdit(self.result_card)
            self.search_box.setPlaceholderText("搜索标题 / 作者…")
            self.search_box.setFixedWidth(220)
            self.search_box.textChanged.connect(self._on_search_changed)
            top_row.addWidget(self.search_box)
            self.result_layout.addLayout(top_row)

            actions_row = QHBoxLayout()
            self.select_all_btn = PushButton("全选", self.result_card)
            self.select_all_btn.clicked.connect(self._select_all)
            self.select_none_btn = PushButton("全不选", self.result_card)
            self.select_none_btn.clicked.connect(self._select_none)
            self.select_range_btn = PushButton("按行号选择…", self.result_card)
            self.select_range_btn.clicked.connect(self._on_select_range)
            self.download_selected_btn = PushButton("下载选中 (0)", self.result_card)
            self.download_selected_btn.clicked.connect(self._download_selected)
            actions_row.addWidget(self.select_all_btn)
            actions_row.addWidget(self.select_none_btn)
            actions_row.addWidget(self.select_range_btn)
            actions_row.addStretch(1)
            actions_row.addWidget(self.download_selected_btn)
            self.result_layout.addLayout(actions_row)

            self.result_table = TableWidget(self.result_card)
            self.result_table.setColumnCount(7)
            self.result_table.setHorizontalHeaderLabels([
                "✓", "#", "标题", "作者", "时长", "类型", "平台",
            ])
            self.result_table.verticalHeader().hide()
            self.result_table.setWordWrap(False)
            self.result_table.setEditTriggers(TableWidget.NoEditTriggers)
            self.result_table.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.result_table.setContextMenuPolicy(Qt.CustomContextMenu)
            self.result_table.customContextMenuRequested.connect(
                self._on_table_context_menu,
            )
            header = self.result_table.horizontalHeader()
            header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
            header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
            header.setSectionResizeMode(2, QHeaderView.Stretch)
            header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
            header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
            header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
            header.setSectionResizeMode(6, QHeaderView.ResizeToContents)
            self.result_table.itemChanged.connect(self._on_table_changed)
            self.result_layout.addWidget(self.result_table, 1)
            layout.addWidget(self.result_card, 1)

        # ---- parsing --------------------------------------------------

        def _on_parse_clicked(self):
            urls = self._parse_urls()
            if not urls:
                self._toast(InfoBar.warning, "没有有效链接", "请至少粘贴一个 URL（每行一个）。")
                return
            self.parse_btn.setEnabled(False)
            self.parse_btn.setText("解析中…")

            async def _do():
                try:
                    items: list[MediaItem] = []
                    per_url: list[tuple[str, list[MediaItem]]] = []
                    for url in urls:
                        item, children = await self._pipeline.parse_and_expand(url)
                        if not children and item is not None:
                            children = [item]
                        per_url.append((url, list(children)))
                        items.extend(children)
                finally:
                    self.parse_btn.setEnabled(True)
                    self.parse_btn.setText("解析")

                if not items:
                    title, content = self._empty_parse_message(per_url)
                    self._toast(InfoBar.warning, title, content)
                    return
                self._fill_result_table(items)
                self._toast(InfoBar.success, "解析完成",
                            f"共 {len(items)} 项可下载。")

            asyncio.create_task(_do())

        def _on_quick_download_clicked(self):
            urls = self._parse_urls()
            if not urls:
                self._toast(InfoBar.warning, "没有有效链接", "请至少粘贴一个 URL。")
                return
            url = urls[0]
            if self._task_manager is None:
                self._toast(InfoBar.error, "未连接任务管理器",
                            "请在主窗口中打开此页面。")
                return

            async def _do():
                item, children = await self._pipeline.parse_and_expand(url)
                if item is None:
                    self._toast(InfoBar.error, "解析失败", f"无法解析：{url}")
                    return
                targets = children if children else [item]
                if not targets:
                    self._toast(InfoBar.warning, "无可下载内容",
                                "该链接没有可下载的子项。")
                    return
                opts = self._build_options()
                for it in targets:
                    self._task_manager.add(it, opts)
                self._toast(InfoBar.success, "已加入下载队列",
                            f"共 {len(targets)} 项。")

            asyncio.create_task(_do())

        def _on_search_changed(self, text: str):
            """Hide rows whose title / author doesn't contain *text*."""
            needle = text.strip().lower()
            self.result_table.blockSignals(True)
            try:
                for row in range(self.result_table.rowCount()):
                    if not needle:
                        self.result_table.setRowHidden(row, False)
                        continue
                    title = (self.result_table.item(row, 2).text()
                             if self.result_table.item(row, 2) else "").lower()
                    author = (self.result_table.item(row, 3).text()
                              if self.result_table.item(row, 3) else "").lower()
                    self.result_table.setRowHidden(
                        row, needle not in title and needle not in author,
                    )
            finally:
                self.result_table.blockSignals(False)
            self._update_summary()

        def _on_table_context_menu(self, pos):
            row = self.result_table.rowAt(pos.y())
            if row < 0:
                return
            # Make the row under the cursor the "current" row so the
            # user immediately sees which row the menu applies to.
            self.result_table.setCurrentCell(row, self.result_table.currentColumn())

            # Resolve the underlying top-level item, the episode item (if
            # the row is inside an expanded section), and the page item
            # (if the row is inside an expanded episode). All three can
            # be acted on independently from the same context menu.
            top_item = self._resolve_top_item_for_row(row)
            episode_item = self._resolve_episode_for_row(row)

            menu = QMenu(self.result_table)

            # ---- expand / collapse actions (right-click is the trigger)
            expand_section_action: Optional[object] = None
            collapse_section_action: Optional[object] = None
            expand_episode_action: Optional[object] = None
            collapse_episode_action: Optional[object] = None

            # ``_resolve_top_item_for_row`` intentionally maps child rows
            # (episodes, pages) back to their owning section — that is
            # what ``_row_to_top_idx`` means. So "is this a section row"
            # must be decided by row identity, NOT by whether the
            # resolved item happens to be a section. Otherwise
            # right-clicking an episode offers 「折叠分类」 and collapses
            # all of its siblings along with it.
            top_idx = self._row_to_top_idx.get(row)
            is_top_row = (
                top_idx is not None and row == self._top_to_row.get(top_idx)
            )

            if (
                is_top_row
                and top_item is not None
                and top_item.extra.get("_from_ugc_season_section")
            ):
                if top_item.children:
                    collapse_section_action = menu.addAction("折叠分类")
                else:
                    expand_section_action = menu.addAction("展开分类")

            if episode_item is not None and episode_item.extra.get(
                "_from_ugc_season",
            ):
                ep_key = self._episode_key_for_row(row)
                if ep_key is not None and ep_key in self._expanded_episode_rows:
                    collapse_episode_action = menu.addAction("折叠分P")
                else:
                    expand_episode_action = menu.addAction("展开分P")

            if any([
                expand_section_action, collapse_section_action,
                expand_episode_action, collapse_episode_action,
            ]):
                menu.addSeparator()

            reparse = menu.addAction("解析此项")
            browser = menu.addAction("在浏览器中打开")
            single = menu.addAction("作为单个视频下载")
            menu.addSeparator()
            meta = menu.addAction("查看元数据")
            cover = menu.addAction("查看封面")

            # ``item`` is what the legacy actions operate on — fall back
            # to the deepest item we have so reparse / open / single still
            # work when the user right-clicks an inserted episode/page row.
            item = episode_item or top_item
            if item is None:
                for a in (reparse, browser, single, meta, cover):
                    a.setEnabled(False)
            elif item.is_container():
                # Containers (ugc_season section rows, season containers)
                # can't be handed to the engine directly — the pipeline
                # would refuse with a "Refusing to download container"
                # error. Disable the per-row "single video download"
                # entry; users who want a section's episodes should use
                # the main 「下载选中」 button instead.
                single.setEnabled(False)
                single.setText("作为单个视频下载（不可用，先展开）")
            chosen = menu.exec(self.result_table.viewport().mapToGlobal(pos))
            if chosen is None:
                return
            if chosen is expand_section_action:
                asyncio.create_task(
                    self._expand_section_row(row, top_item),
                )
                return
            if chosen is collapse_section_action:
                self._collapse_section(row)
                return
            if chosen is expand_episode_action:
                asyncio.create_task(
                    self._expand_episode_row(row, episode_item),
                )
                return
            if chosen is collapse_episode_action:
                self._collapse_episode(row)
                return
            if item is None:
                return
            if chosen is reparse:
                self.url_input.setPlainText(item.source_url)
                self._on_parse_clicked()
            elif chosen is browser:
                QDesktopServices.openUrl(QUrl(item.source_url))
            elif chosen is single:
                if self._task_manager is not None:
                    self._task_manager.add(item, self._build_options())
                    self._toast(InfoBar.success, "已加入下载队列", item.title or item.item_id)
            elif chosen is meta:
                self._show_metadata_dialog(item)
            elif chosen is cover:
                if item.cover_url:
                    QDesktopServices.openUrl(QUrl(item.cover_url))

        def _show_metadata_dialog(self, item: MediaItem) -> None:
            from qfluentwidgets import MessageBox
            lines = [
                f"标题：{item.title or '(无)'}",
                f"平台：{item.platform.value if item.platform else '?'}",
                f"类型：{item.media_type.value if item.media_type else '?'}",
                f"作者：{item.author.name if item.author else '(无)'}",
                f"时长：{_fmt_duration(item.duration)}",
                f"发布时间：{item.publish_time.isoformat() if item.publish_time else '(无)'}",
                f"原链接：{item.source_url}",
            ]
            extra = item.extra or {}
            for k, v in extra.items():
                if k.startswith("_"):
                    continue
                lines.append(f"{k}：{v}")
            box = MessageBox("元数据", "\n".join(lines), self.window())
            box.exec()

        def _on_select_range(self):
            from qfluentwidgets import MessageBox
            box = MessageBox(
                "按行号选择",
                "输入行号范围，如：\n"
                "  1-5,7,9-12\n"
                "支持：单行 (3)、区间 (1-5)、组合 (1-3,7,10-12)",
                self.window(),
            )
            box.textLayout.addWidget(_make_input_widget := _RowInput())
            if box.exec():
                text = _make_input_widget.text().strip()
                self._apply_range_selection(text)

        def _apply_range_selection(self, text: str):
            """Parse a row-range string (1-indexed) and check those rows."""
            indices = _parse_range(text, self.result_table.rowCount())
            if not indices:
                self._toast(InfoBar.warning, "无效行号", f"未解析到有效行号：{text}")
                return
            self.result_table.blockSignals(True)
            try:
                for i in range(self.result_table.rowCount()):
                    chk = self.result_table.item(i, 0)
                    if chk is not None:
                        chk.setCheckState(
                            Qt.Checked if i in indices else Qt.Unchecked,
                        )
            finally:
                self.result_table.blockSignals(False)
            self._update_summary()

        # ---- result table helpers -------------------------------------

        def _fill_result_table(self, items: list[MediaItem]) -> None:
            self._parsed_items = list(items)
            # Expansion state keyed by **stable identifiers** rather
            # than by table row number — table rows shift whenever a
            # sibling section is expanded/collapsed, so a row-based
            # key goes stale silently. We use ``(top_idx,)`` for
            # section rows and ``(top_idx, child_idx)`` for episode
            # rows so re-expanding a collapsed section restores the
            # exact same children list.
            self._expanded_rows: dict[tuple[int, ...], list[MediaItem]] = {}
            self._expanded_episode_rows: dict[
                tuple[int, ...], list[MediaItem],
            ] = {}
            # row -> top_index (the index into self._parsed_items that
            # owns that table row). Top rows point at themselves; child
            # rows (episodes of a section, pages of an episode) point at
            # the ancestor section/episode. Built/maintained in
            # ``_refresh_row_mapping``.
            self._row_to_top_idx: dict[int, int] = {}
            self._top_to_row: dict[int, int] = {}
            self._top_id_to_row: dict[str, int] = {}
            # Page rows are inserted directly beneath their episode row,
            # so sibling episodes are NOT contiguous. These two caches
            # record row ownership explicitly instead of re-deriving it
            # with offset arithmetic (which silently breaks as soon as
            # one episode is expanded).
            self._row_to_episode_key: dict[int, tuple[int, int]] = {}
            self._row_to_page_key: dict[int, tuple[int, int, int]] = {}
            self.result_table.blockSignals(True)
            try:
                self.result_table.setRowCount(len(items))
                for i, item in enumerate(items):
                    chk = _check_item()
                    is_section_row = bool(
                        item.extra.get("_from_ugc_season_section"),
                    )
                    if is_section_row:
                        # Section rows are containers; checking them
                        # directly is misleading (download count would
                        # already be inflated by their episodes). Force
                        # tristate and disable user clicks — episodes
                        # beneath them stay individually selectable.
                        chk.setCheckState(Qt.PartiallyChecked)
                        chk.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                        chk.setToolTip(
                            "分类容器不可直接下载 — 展开后勾选下面的分集")
                    else:
                        chk.setCheckState(Qt.Checked)
                    self.result_table.setItem(i, 0, chk)
                    self.result_table.setItem(i, 1, _cell(str(i + 1)))
                    title_text = item.title or item.item_id
                    if is_section_row:
                        title_text = f"▸ {title_text}  ({item.extra.get('episode_count', 0)} 分集)"
                    self.result_table.setItem(i, 2, _cell(title_text))
                    self.result_table.setItem(i, 3, _cell(
                        item.author.name if item.author else ""))
                    self.result_table.setItem(i, 4, _cell(
                        _fmt_duration(item.duration)))
                    self.result_table.setItem(i, 5, _cell(
                        item.media_type.value if item.media_type else ""))
                    self.result_table.setItem(i, 6, _cell(
                        item.platform.value if item.platform else ""))
            finally:
                self.result_table.blockSignals(False)
            self._refresh_row_mapping()
            self._update_summary()
            # Apply any active filter
            if self.search_box.text():
                self._on_search_changed(self.search_box.text())

        # ---- section expansion (ugc_season) ----------------------------

        def _refresh_row_mapping(self) -> None:
            """(Re)build the row-mapping caches.

            Five dicts are maintained:

            * ``_row_to_top_idx`` — table row → top-level parsed index.
              Child rows (episodes, pages) point at their owning section.
            * ``_top_to_row`` — top-level parsed index → table row.
            * ``_top_id_to_row`` — top-level ``item_id`` → table row.
              Stable across expand/collapse, used by
              ``_find_row_for_top_item`` for O(1) lookups that survive
              row shifts.
            * ``_row_to_episode_key`` — table row → ``(top_idx,
              child_idx)``, present **only** for genuine episode rows.
            * ``_row_to_page_key`` — table row → ``(top_idx, child_idx,
              page_idx)``, present **only** for genuine page rows.

            The last two exist because page rows are inserted directly
            beneath their episode row, so the layout is *interleaved*
            (``sec, ep0, pg0..pgN, ep1, ep2``). Any attempt to recover
            "which episode owns row N" with ``row - section_row - 1``
            arithmetic breaks the moment one episode is expanded. This
            walk is the single source of truth; everything else looks
            the answer up instead of recomputing it.
            """
            row_to_top: dict[int, int] = {}
            top_to_row: dict[int, int] = {}
            top_id_to_row: dict[str, int] = {}
            row_to_episode_key: dict[int, tuple[int, int]] = {}
            row_to_page_key: dict[int, tuple[int, int, int]] = {}
            row = 0
            for top_idx in range(len(self._parsed_items)):
                top_to_row[top_idx] = row
                row_to_top[row] = top_idx
                item_id = getattr(
                    self._parsed_items[top_idx], "item_id", None,
                )
                if item_id is not None:
                    top_id_to_row[item_id] = row
                row += 1
                episodes = self._expanded_rows.get((top_idx,)) or []
                for child_idx, _ in enumerate(episodes):
                    row_to_top[row] = top_idx
                    row_to_episode_key[row] = (top_idx, child_idx)
                    row += 1
                    pages = (
                        self._expanded_episode_rows.get((top_idx, child_idx))
                        or []
                    )
                    for page_idx, _ in enumerate(pages):
                        row_to_top[row] = top_idx
                        row_to_page_key[row] = (top_idx, child_idx, page_idx)
                        row += 1
            self._row_to_top_idx = row_to_top
            self._top_to_row = top_to_row
            self._top_id_to_row = top_id_to_row
            self._row_to_episode_key = row_to_episode_key
            self._row_to_page_key = row_to_page_key

        def _episode_key_for_row(self, row: int) -> Optional[tuple[int, ...]]:
            """Map an episode row to its stable expansion key.

            Returns ``(top_idx, child_idx)`` where ``child_idx`` is the
            position of the episode within the section's expanded
            children list — the key used by
            ``_expanded_episode_rows``. Returns ``None`` for section
            rows, page rows and unknown rows alike.
            """
            return self._row_to_episode_key.get(row)

        def _resolve_top_item_for_row(self, row: int) -> Optional[MediaItem]:
            """Map a table row back to its top-level ``_parsed_items`` entry.

            Backed by the ``_row_to_top_idx`` cache that is rebuilt by
            ``_refresh_row_mapping`` whenever the table composition
            changes — so this is O(1) instead of an O(N) table walk.
            """
            top_idx = self._row_to_top_idx.get(row)
            if top_idx is None:
                return None
            if 0 <= top_idx < len(self._parsed_items):
                return self._parsed_items[top_idx]
            return None

        def _resolve_episode_for_row(self, row: int) -> Optional[MediaItem]:
            """Return the episode MediaItem that owns *row*, if any.

            Works for both an episode row itself and any of its page
            rows. Section rows return ``None``.
            """
            key = self._row_to_episode_key.get(row)
            if key is None:
                page_key = self._row_to_page_key.get(row)
                if page_key is None:
                    return None
                key = (page_key[0], page_key[1])
            top_idx, child_idx = key
            episodes = self._expanded_rows.get((top_idx,)) or []
            if 0 <= child_idx < len(episodes):
                return episodes[child_idx]
            return None

        def _resolve_page_for_row(self, row: int) -> Optional[MediaItem]:
            """Return the page (分P) MediaItem *row* represents, if any.

            ``None`` unless *row* is a page row inside an expanded
            episode.
            """
            page_key = self._row_to_page_key.get(row)
            if page_key is None:
                return None
            top_idx, child_idx, page_idx = page_key
            pages = self._expanded_episode_rows.get((top_idx, child_idx)) or []
            if 0 <= page_idx < len(pages):
                return pages[page_idx]
            return None

        def _is_section_row(self, row: int) -> bool:
            """True only when *row* is a section's own top-level row.

            Note the row-identity check: ``_resolve_top_item_for_row``
            maps child rows to their owning section too, so testing the
            resolved item alone would report episode/page rows as
            sections.
            """
            top_idx = self._row_to_top_idx.get(row)
            if top_idx is None or row != self._top_to_row.get(top_idx):
                return False
            item = self._resolve_top_item_for_row(row)
            return bool(item and item.extra.get("_from_ugc_season_section"))

        async def _expand_episode_row(self, row: int, episode_item: MediaItem) -> None:
            from ...core.models import Platform
            from ...core.registry import PlatformRegistry
            adapter = PlatformRegistry.get(Platform.BILIBILI)
            if adapter is None:
                self._toast(InfoBar.error, "展开分集失败",
                            "未找到 B 站适配器，请重启软件。")
                return
            try:
                pages = await adapter.expand_episode_pages(episode_item)
            except Exception as exc:  # noqa: BLE001
                logger.exception("expand_episode_pages failed")
                self._toast(InfoBar.error, "展开分集失败",
                            f"{episode_item.title}: {exc}")
                return
            if len(pages) <= 1:
                # Single-page or fetch failed — the row IS the video.
                self._toast(InfoBar.info, "没有分集",
                            f"{episode_item.title} 没有分P。")
                return
            key = self._episode_key_for_row(row)
            if key is None:
                logger.warning("expand_episode_row: row %d not in mapping", row)
                return
            self._expanded_episode_rows[key] = list(pages)
            insert_at = row + 1
            self.result_table.blockSignals(True)
            try:
                for k, page in enumerate(pages):
                    self.result_table.insertRow(insert_at + k)
                    self._write_section_child_row(
                        insert_at + k, page, indent=True,
                        marker="··",
                    )
            finally:
                self.result_table.blockSignals(False)
            self._refresh_row_mapping()
            self._update_summary()

        def _collapse_episode(self, row: int) -> None:
            key = self._episode_key_for_row(row)
            if key is None:
                return
            pages = self._expanded_episode_rows.pop(key, None)
            if not pages:
                return
            count = len(pages)
            self.result_table.blockSignals(True)
            try:
                for _ in range(count):
                    self.result_table.removeRow(row + 1)
            finally:
                self.result_table.blockSignals(False)
            self._refresh_row_mapping()
            self._update_summary()

        async def _expand_section_row(self, row: int, section_item: MediaItem) -> None:
            from ...core.models import Platform
            from ...core.registry import PlatformRegistry
            adapter = PlatformRegistry.get(Platform.BILIBILI)
            if adapter is None:
                self._toast(InfoBar.error, "展开分类失败",
                            "未找到 B 站适配器，请重启软件。")
                return
            try:
                episodes = await adapter.expand_section(section_item)
            except Exception as exc:  # noqa: BLE001
                logger.exception("expand_section failed")
                self._toast(InfoBar.error, "展开分类失败",
                            f"{section_item.title}: {exc}")
                return

            top_idx = self._row_to_top_idx.get(row)
            if top_idx is None:
                logger.warning("expand_section_row: row %d not in mapping", row)
                return
            # Same guard as ``_collapse_section``: inserting episodes
            # beneath a child row would interleave them into the wrong
            # parent and desync every downstream cache.
            if row != self._top_to_row.get(top_idx):
                logger.warning(
                    "expand_section_row: row %d is not a top-level row "
                    "— ignoring", row,
                )
                return
            self._expanded_rows[(top_idx,)] = list(episodes)
            insert_at = row + 1
            self.result_table.blockSignals(True)
            try:
                self.result_table.insertRow(insert_at)
                self._write_section_child_row(insert_at, episodes[0], indent=True)
                for k, ep in enumerate(episodes[1:], start=1):
                    self.result_table.insertRow(insert_at + k)
                    self._write_section_child_row(insert_at + k, ep, indent=True)
            finally:
                self.result_table.blockSignals(False)
            self._refresh_row_mapping()
            self._update_summary()

        def _collapse_section(self, row: int) -> None:
            top_idx = self._row_to_top_idx.get(row)
            if top_idx is None:
                return
            # Hard guard: *row* must be the section's own row. Child rows
            # map to the same ``top_idx``, so a stray call from an
            # episode row would otherwise wipe out that episode's
            # siblings and delete the wrong table rows.
            if row != self._top_to_row.get(top_idx):
                logger.warning(
                    "_collapse_section: row %d is not a top-level row "
                    "(owning section sits at %s) — ignoring",
                    row, self._top_to_row.get(top_idx),
                )
                return
            key = (top_idx,)
            episodes = self._expanded_rows.pop(key, None)
            if not episodes:
                return
            # Build the list of rows to remove (episode rows + any
            # page rows underneath them), then delete them bottom-up
            # so the table indices don't shift during removal.
            #
            # Episode rows are NOT contiguous: an expanded episode has
            # its page rows wedged in right below it, pushing the next
            # sibling episode down. So walk a running cursor instead of
            # computing ``row + 1 + child_idx``.
            rows_to_remove: list[int] = []
            ep_row = row + 1
            for child_idx in range(len(episodes)):
                pages_key = (top_idx, child_idx)
                pages = self._expanded_episode_rows.pop(pages_key, None)
                rows_to_remove.append(ep_row)
                page_count = len(pages) if pages else 0
                for off in range(1, page_count + 1):
                    rows_to_remove.append(ep_row + off)
                ep_row += 1 + page_count
            self.result_table.blockSignals(True)
            try:
                for r in sorted(rows_to_remove, reverse=True):
                    self.result_table.removeRow(r)
                # Reset the underlying section item so a re-click re-runs
                # ``adapter.expand_section``; otherwise the toggle in
                # ``_on_row_activated`` short-circuits on
                # ``section_item.children`` being non-empty and ignores
                # the new click entirely.
                section_item = self._resolve_top_item_for_row(row)
                if section_item is not None:
                    section_item.children = []
                    section_item.extra.pop("_expanded", None)
            finally:
                self.result_table.blockSignals(False)
            self._refresh_row_mapping()
            self._update_summary()

        def _write_section_child_row(self, row: int, item: MediaItem, *, indent: bool, marker: str = "·") -> None:
            chk = _check_item()
            chk.setCheckState(Qt.Checked)
            self.result_table.setItem(row, 0, chk)
            self.result_table.setItem(row, 1, _cell(marker))
            prefix = "    " if indent else ""
            self.result_table.setItem(row, 2, _cell(prefix + (item.title or item.item_id)))
            self.result_table.setItem(row, 3, _cell(
                item.author.name if item.author else ""))
            self.result_table.setItem(row, 4, _cell(_fmt_duration(item.duration)))
            self.result_table.setItem(row, 5, _cell(
                item.media_type.value if item.media_type else ""))
            self.result_table.setItem(row, 6, _cell(
                item.platform.value if item.platform else ""))

        def _selected_items(self) -> list[MediaItem]:
            """Return the items currently checked in the table.

            Rows that have been expanded from a section are flattened into
            the list using the in-memory expanded-rows cache.
            """
            sel: list[MediaItem] = []
            for i in range(self.result_table.rowCount()):
                if self.result_table.isRowHidden(i):
                    continue
                chk = self.result_table.item(i, 0)
                if chk is None or chk.checkState() != Qt.Checked:
                    continue
                top_idx = self._row_to_top_idx.get(i)
                if top_idx is None:
                    continue
                episodes_here = self._expanded_rows.get((top_idx,)) or []
                if i == self._top_to_row.get(top_idx) and episodes_here:
                    # Top-level section row: emit each expanded episode
                    # individually so the engine can persist them as
                    # separate files. Child rows (episodes, pages)
                    # are emitted on their own pass below.
                    for ep in episodes_here:
                        if not _is_duplicate(ep, sel):
                            sel.append(ep)
                elif i == self._top_to_row.get(top_idx):
                    top = self._parsed_items[top_idx]
                    if not _is_duplicate(top, sel):
                        sel.append(top)
                else:
                    # A child row that is itself checked. Resolve the
                    # most specific item it stands for: a page row means
                    # that page, an episode row means that episode.
                    owner = (
                        self._resolve_page_for_row(i)
                        or self._resolve_episode_for_row(i)
                        or self._resolve_top_item_for_row(i)
                    )
                    if owner is not None and not _is_duplicate(owner, sel):
                        sel.append(owner)
            return sel

        def _on_table_changed(self, item):
            if item.column() == 0:
                self._update_summary()

        def _update_summary(self) -> None:
            checked = self._checked_count()
            total = len(self._parsed_items)
            visible = self._visible_count()
            if total == 0:
                self.result_summary.setText("尚未解析。")
            elif visible < total:
                self.result_summary.setText(
                    f"已解析 {total} 项（显示 {visible}），已勾选 {checked} 项",
                )
            else:
                self.result_summary.setText(
                    f"已解析 {total} 项，已勾选 {checked} 项",
                )
            self.download_selected_btn.setText(f"下载选中 ({checked})")

        def _visible_count(self) -> int:
            n = 0
            for i in range(self.result_table.rowCount()):
                if not self.result_table.isRowHidden(i):
                    n += 1
            return n

        def _checked_count(self) -> int:
            n = 0
            for i in range(self.result_table.rowCount()):
                if self.result_table.isRowHidden(i):
                    continue
                chk = self.result_table.item(i, 0)
                if chk is not None and chk.checkState() == Qt.Checked:
                    n += 1
            return n

        def _select_all(self) -> None:
            self.result_table.blockSignals(True)
            try:
                for i in range(self.result_table.rowCount()):
                    if self.result_table.isRowHidden(i):
                        continue
                    chk = self.result_table.item(i, 0)
                    if chk is None:
                        continue
                    # Section rows are tristate containers; users select
                    # them by selecting their children. Leave them as-is.
                    if chk.flags() & Qt.ItemIsUserCheckable == 0:
                        continue
                    chk.setCheckState(Qt.Checked)
            finally:
                self.result_table.blockSignals(False)
            self._update_summary()

        def _select_none(self) -> None:
            self.result_table.blockSignals(True)
            try:
                for i in range(self.result_table.rowCount()):
                    chk = self.result_table.item(i, 0)
                    if chk is not None:
                        chk.setCheckState(Qt.Unchecked)
            finally:
                self.result_table.blockSignals(False)
            self._update_summary()

        def _download_selected(self) -> None:
            rows = self._checked_rows()
            if not rows:
                self._toast(InfoBar.warning, "未选择项目", "请先勾选要下载的条目。")
                return
            if self._task_manager is None:
                self._toast(InfoBar.error, "未连接任务管理器",
                            "请在主窗口中打开此页面。")
                return

            async def _do():
                targets = await self._resolve_download_targets(rows)
                if not targets:
                    self._toast(InfoBar.warning, "无可下载内容",
                                "勾选项展开后没有分集。")
                    return
                opts = self._build_options()
                for it in targets:
                    self._task_manager.add(it, opts)
                self._toast(InfoBar.success, "已加入下载队列", f"共 {len(targets)} 项。")

            asyncio.create_task(_do())

        def _checked_rows(self) -> list[int]:
            """Return table rows whose checkbox is currently Checked."""
            out: list[int] = []
            for r in range(self.result_table.rowCount()):
                if self.result_table.isRowHidden(r):
                    continue
                chk = self.result_table.item(r, 0)
                if chk is not None and chk.checkState() == Qt.Checked:
                    out.append(r)
            return out

        async def _resolve_download_targets(self, rows: list[int]) -> list[MediaItem]:
            """Flatten checked table rows into concrete download items.

            Handles three levels of ugc_season nesting:

            * a plain VIDEO row → itself
            * an episode row inside an expanded section → the episode
              (or its expanded pages if the user expanded them too)
            * a section row → all episodes inside (hydrating on the fly
              if the user hadn't clicked it open)
            * a page row inside an expanded episode → just that page
            """
            from ...core.models import Platform
            from ...core.registry import PlatformRegistry
            adapter = PlatformRegistry.get(Platform.BILIBILI)
            targets: list[MediaItem] = []

            for row in rows:
                # A page row represents exactly one 分P — emit just it.
                # Emitting the whole owning episode here would duplicate
                # the download (the episode's other page rows are
                # separate checkboxes the user may have unticked).
                page = self._resolve_page_for_row(row)
                if page is not None:
                    if not _is_duplicate(page, targets):
                        targets.append(page)
                    continue

                # Episode row. If its pages are expanded, they are their
                # own checkable rows and handled above, so skip the
                # episode to avoid enqueueing it twice.
                ep_key = self._episode_key_for_row(row)
                if ep_key is not None:
                    if ep_key in self._expanded_episode_rows:
                        continue
                    episode = self._resolve_episode_for_row(row)
                    if episode is not None:
                        if not _is_duplicate(episode, targets):
                            targets.append(episode)
                        continue

                # Top-level row: either section or standalone video
                item = self._resolve_top_item_for_row(row)
                if item is None:
                    continue
                if item.extra.get("_from_ugc_season_section"):
                    if not item.children and adapter is not None:
                        try:
                            await adapter.expand_section(item)
                        except Exception:
                            logger.exception("auto expand_section failed")
                            continue
                    top_idx = self._row_to_top_idx.get(row)
                    if top_idx is not None:
                        self._expanded_rows.setdefault(
                            (top_idx,), list(item.children),
                        )
                    for ep in item.children:
                        if not _is_duplicate(ep, targets):
                            targets.append(ep)
                    # Hard guard: never enqueue the section itself.
                    # task_manager dedupes by item_id so duplicates
                    # would otherwise be silently swallowed, but a
                    # COLLECTION item slipping through would show up
                    # in the download center as the section title.
                    continue
                else:
                    if not _is_duplicate(item, targets):
                        targets.append(item)
            return targets

        def _find_row_for_top_item(self, top_item: MediaItem) -> Optional[int]:
            """Return the table row that currently hosts *top_item*.

            Uses the ``_top_id_to_row`` cache (stable ``item_id`` → row)
            populated by ``_refresh_row_mapping`` — O(1) and immune to
            row shifts when sibling sections are expanded/collapsed.
            """
            target_id = getattr(top_item, "item_id", None)
            if target_id is None:
                return None
            return self._top_id_to_row.get(target_id)

        # ---- empty-parse message (Bili23-style hints) -----------------

        def _empty_parse_message(
            self, per_url: list[tuple[str, list[MediaItem]]]
        ) -> tuple[str, str]:
            needs_login: list[str] = []
            other: list[str] = []
            for url, items in per_url:
                if items:
                    continue
                kind = self._classify_login_required(url)
                if kind:
                    needs_login.append(f"{kind}（{url}）")
                else:
                    other.append(url)

            cookie_path = str(Path.home() / ".doubi" / "cookies" / "bilibili.txt")
            if needs_login and not other:
                return (
                    "解析结果为空 · B 站需要登录",
                    "以下链接需要先登录 B 站：\n  • "
                    + "\n  • ".join(needs_login)
                    + "\n请到 设置 页填入 Cookie 文件路径（通常为\n  "
                    + cookie_path
                    + "\n），或在 CLI 跑 `doubi auth bilibili` 导入。",
                )
            if needs_login and other:
                return (
                    "解析结果为空 · 部分链接需要登录",
                    "需要登录：\n  • " + "\n  • ".join(needs_login)
                    + "\n\n其他链接：\n  • " + "\n  • ".join(other)
                    + "\n\n请检查链接是否可访问，或到 设置 页导入 B 站 Cookie。",
                )
            return (
                "解析结果为空",
                "没有可下载的内容，请检查链接或确认该链接可访问。",
            )

        def _classify_login_required(self, url: str) -> Optional[str]:
            try:
                from ...platforms.bilibili.url import (
                    BilibiliURLType,
                    classify_bilibili_url,
                )
            except Exception:
                return None
            c = classify_bilibili_url(url)
            if c.type is BilibiliURLType.FAVLIST:
                return "收藏夹"
            if c.type is BilibiliURLType.WATCH_LATER:
                return "稍后再看"
            if c.type is BilibiliURLType.SPACE:
                return "UP 主空间"
            if c.type is BilibiliURLType.LIST:
                return "合集"
            return None

        # ---- shared helpers -------------------------------------------

        def _parse_urls(self) -> list[str]:
            out: list[str] = []
            for raw in self.url_input.toPlainText().splitlines():
                s = raw.strip()
                if not s or s.startswith("#"):
                    continue
                out.append(s)
            return out

        def _build_options(self) -> DownloadOptions:
            return DownloadOptions(
                output_root=self._cfg.output_root,
                filename_template=self._cfg.filename_template,
                container=self._cfg.container,
                max_quality=self._cfg.max_quality,
                write_thumbnail=self._cfg.write_thumbnail,
                write_metadata_json=self._cfg.write_metadata_json,
                database=self._cfg.database_path if self._cfg.database else None,
                manifest=self._cfg.manifest_path,
                proxy=self._cfg.proxy,
                rate_limit=self._cfg.rate_limit,
            )

        def _toast(self, kind, title: str, content: str) -> None:
            kind(
                title=title, content=content, parent=self,
                position=InfoBarPosition.TOP_RIGHT, duration=4000,
            )

    # ------------------------------------------------------------------
    # helpers (module-level so they don't close over Page state)
    # ------------------------------------------------------------------

    def _cell(text: str):
        from PySide6.QtWidgets import QTableWidgetItem
        return QTableWidgetItem(text)

    def _check_item():
        from PySide6.QtWidgets import QTableWidgetItem
        return QTableWidgetItem()

    def _fmt_duration(seconds) -> str:
        if not seconds:
            return ""
        try:
            s = int(seconds)
            h, rem = divmod(s, 3600)
            m, sec = divmod(rem, 60)
            if h:
                return f"{h}:{m:02d}:{sec:02d}"
            return f"{m}:{sec:02d}"
        except (TypeError, ValueError):
            return str(seconds)

    def _RowInput():
        from PySide6.QtWidgets import QLineEdit
        w = QLineEdit()
        w.setPlaceholderText("如 1-5,7,9-12")
        w.setClearButtonEnabled(True)
        return w

    def _parse_range(text: str, n_rows: int) -> set[int]:
        """Parse '1-5,7,9-12' into a set of 0-indexed row numbers."""
        out: set[int] = set()
        for chunk in text.replace(" ", "").split(","):
            if not chunk:
                continue
            if "-" in chunk:
                a, b = chunk.split("-", 1)
                try:
                    lo, hi = int(a), int(b)
                except ValueError:
                    continue
                if lo > hi:
                    lo, hi = hi, lo
                for i in range(max(1, lo), min(n_rows, hi) + 1):
                    out.add(i - 1)
            else:
                try:
                    i = int(chunk)
                except ValueError:
                    continue
                if 1 <= i <= n_rows:
                    out.add(i - 1)
        return out

    def _is_duplicate(item, existing: list) -> bool:
        """True if *item* shares an item_id with any item in *existing*.

        Used by the parse picker to avoid handing the same BV to the
        download queue twice when a section is selected and then its
        episodes are also ticked individually. ``TaskManager.add`` itself
        dedupes by ``item_id`` but skipping early keeps the user-visible
        counter honest.
        """
        target = getattr(item, "item_id", None)
        if target is None:
            return False
        for other in existing:
            if getattr(other, "item_id", None) == target:
                return True
        return False

    return ParsePage, ParsePage
