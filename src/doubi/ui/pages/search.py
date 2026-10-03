"""Search page (0.3.3 / P1-3) — GUI front for ``doubi search``.

CLI had this command since 0.3.2 (M6.49), but the GUI had no entry —
users who only knew the GUI couldn't see the four search channels
(general / video / user / live) at all. This page wraps
:meth:`DouyinWebAPI.search_general` / ``search_video`` / ``search_user``
/ ``search_live`` and shows the JSONL row stream as a table.

Logged-out handling: without cookies, 抖音 returns 403 for most search
endpoints (see ``DouyinWebAPI._request_json``). The page detects this
case and shows an explicit "去登录" empty state instead of an empty
table — that's the contract ROADMAP P1-3 calls out.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("doubi.ui.pages.search")


#: Search channels, parallel to ``doubi search --type`` values.
#: Module-level so the regression test can lock it down without
#: reaching into the factory's enclosing frame.
CHANNEL_OPTIONS = [
    ("general", "综合"),
    ("video",   "视频"),
    ("user",    "用户"),
    ("live",    "直播"),
]


def build_search_widgets():
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
    )
    from qfluentwidgets import (
        PushButton, LineEdit, ComboBox, TableWidget, InfoBar, InfoBarPosition,
    )

    from ...core.config import load_config
    from ..theme import (
        SPACE_LG, SPACE_MD, SPACE_SM, SPACE_XL,
        subscribe_theme,
    )
    from ..widgets import build_empty_state, build_page_header, build_stat_chip

    class SearchPage(QWidget):
        def __init__(self, parent: Optional[QWidget] = None):
            super().__init__(parent)
            self.setObjectName("searchPage")
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
            self._header.set_title("搜索")
            self._header.set_subtitle(
                "在抖音站内按关键词搜索。综合/视频/用户/直播 4 个通道，"
                "结构与 CLI `doubi search` 完全对齐。"
            )
            self.search_btn = PushButton("搜索", self)
            self.search_btn.clicked.connect(self._on_search)
            self._header.add_action(self.search_btn)
            outer.addWidget(self._header)

            # ---- 输入条 ----
            row = QHBoxLayout()
            row.setSpacing(SPACE_MD)
            self._keyword = LineEdit(self)
            self._keyword.setPlaceholderText("搜索关键词（中英文都行）")
            self._keyword.returnPressed.connect(self._on_search)
            self._channel = ComboBox(self)
            for value, label in CHANNEL_OPTIONS:
                self._channel.addItem(label, userData=value)
            self._channel.setCurrentIndex(0)
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
            self._stack.addWidget(self.table)

            self._empty_state = EmptyState(self)
            self._empty_state.set_text(
                "尚未搜索",
                "在上方输入关键词并回车，或点「搜索」。",
            )
            self._stack.addWidget(self._empty_state)
            outer.addWidget(self._stack, 1)

            self._stack.setCurrentWidget(self._empty_state)

        # ----------------------------------------------------------

        def _on_search(self) -> None:
            keyword = self._keyword.text().strip()
            if not keyword:
                InfoBar.warning(
                    title="需要关键词",
                    message="请先输入搜索关键词。",
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=3000,
                )
                return
            try:
                import asyncio
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None
                if loop and loop.is_running():
                    loop.create_task(self._run_search(keyword))
                else:
                    asyncio.run(self._run_search(keyword))
            except Exception as exc:
                logger.exception("search failed: %s", exc)
                InfoBar.error(
                    title="搜索失败",
                    message=str(exc),
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=5000,
                )

        async def _run_search(self, keyword: str) -> None:
            from doubi.platforms.douyin.webapi import DouyinWebAPI

            channel = self._channel.currentData() or "general"
            cookies_file = (
                self._cfg.cookies_file if self._cfg.cookies_file else None
            )
            api = DouyinWebAPI(
                cookies_file=cookies_file,
                proxy=self._cfg.proxy,
                timeout=15.0,
            )
            try:
                if channel == "general":
                    results = await api.search_general(
                        keyword, count=10, max_count=20, error_sink={},
                    )
                elif channel == "video":
                    results = await api.search_video(
                        keyword, count=10, max_count=20, error_sink={},
                    )
                elif channel == "user":
                    results = await api.search_user(
                        keyword, count=10, max_count=20, error_sink={},
                    )
                else:
                    results = await api.search_live(
                        keyword, count=10, max_count=20, error_sink={},
                    )
            except Exception as exc:
                # 403 等情形会抛异常。让上层 InfoBar 提示。
                raise

            self._rows = list(results or [])
            self._stat_hits.set_value(len(self._rows))
            if self._rows:
                self._populate_table()
                self._stack.setCurrentWidget(self.table)
            else:
                # 没有 cookies 时抖音多数搜索会返回 0 条——明确告诉用户去登录。
                if not cookies_file:
                    self._empty_state.set_text(
                        "暂无结果（未登录）",
                        "抖音搜索需要登录态。请前往「设置 → 账号 → 抖音扫码登录」后再试。",
                    )
                else:
                    self._empty_state.set_text(
                        "暂无结果",
                        "可能是关键词拼写、平台限流或登录态过期。请换个关键词或在设置页检查 Cookie。",
                    )
                self._stack.setCurrentWidget(self._empty_state)

        def _populate_table(self) -> None:
            from PySide6.QtWidgets import QTableWidgetItem

            self.table.setRowCount(len(self._rows))
            for i, row in enumerate(self._rows):
                title = row.get("title") or row.get("nickname") or ""
                author = (
                    row.get("author", {}).get("nickname", "")
                    if isinstance(row.get("author"), dict)
                    else row.get("nickname", "")
                )
                item_id = (
                    row.get("aweme_id")
                    or row.get("uid")
                    or row.get("room_id")
                    or ""
                )
                # 「详情」用 aweme/user/room 的原始 URL 形态，让 GUI 看得出
                # CLI 同源。空字符串代表非视频/用户条目（如 live 详情行）。
                detail = row.get("share_url") or ""
                self.table.setItem(i, 0, QTableWidgetItem(str(title)))
                self.table.setItem(i, 1, QTableWidgetItem(str(author)))
                self.table.setItem(i, 2, QTableWidgetItem(str(item_id)))
                self.table.setItem(i, 3, QTableWidgetItem(str(detail)))

    return SearchPage, None