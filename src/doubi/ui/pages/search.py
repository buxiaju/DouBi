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
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
    )
    from qfluentwidgets import (
        PushButton, LineEdit, ComboBox, SegmentedWidget,
        TableWidget, InfoBar, InfoBarPosition,
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
            self._refresh_channel_options(route_key)

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
            platform_route = (
                self._platform_tabs.currentItem()
                or PLATFORM_OPTIONS[0][0]
            )
            try:
                import asyncio
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None
                if loop and loop.is_running():
                    loop.create_task(
                        self._run_search(platform_route, keyword),
                    )
                else:
                    asyncio.run(self._run_search(platform_route, keyword))
            except Exception as exc:
                logger.exception("search failed: %s", exc)
                InfoBar.error(
                    title="搜索失败",
                    message=str(exc),
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
            except Exception as exc:
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

    return SearchPage, None