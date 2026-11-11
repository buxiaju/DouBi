"""Favorites page — GUI front for ``doubi favorites`` (抖音收藏全家族).

M6.51 的收藏 5 类（收藏夹 / 收藏夹视频 / 收藏合集 / 收藏音乐 / 收藏短剧）
此前只有 CLI 入口；本页与搜索 / 热榜页同模式，所有数据共用
``collect_favorites_async``，CLI / GUI 同源。

交互设计对应 API 的真实能力边界：

* **收藏夹**行可下钻 → ``iter_collects_videos(collects_id)``（可下载）；
* **收藏合集**行可下载整个合集 → ``iter_mix_awemes(mix_id)``（M6.56 的
  合集展开器，确认后整包入队）；
* **收藏音乐 / 收藏短剧**仅列表（与 CLI 对齐——M6.51 明确把这两类的
  展开划出范围，API 层没有对应端点）；
* 全家族 gate 在抖音登录态上：本机没有 cookie 文件时直接给「去设置页
  登录」的引导态，不发无效请求。
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("doubi.ui.pages.favorites")


#: 5 类收藏。value 与 CLI ``--kind`` / ``collect_favorites_async`` 对齐。
FAVORITE_KINDS = [
    ("favorites", "收藏夹"),
    ("videos",    "收藏夹视频"),
    ("mix",       "收藏合集"),
    ("music",     "收藏音乐"),
    ("series",    "收藏短剧"),
]

#: 每类行的展示字段（按顺序取第一个非空键——平台原始 dict 的键名
#: 各端点不一致，防御式取值与热榜页同策略）。
KIND_ROW_FIELDS: dict[str, dict[str, tuple[str, ...]]] = {
    "favorites": {"name": ("collect_name", "name", "title"), "id": ("collects_id",)},
    "videos":    {"name": ("desc", "title"), "id": ("aweme_id",)},
    "mix":       {"name": ("mix_name", "name", "title"), "id": ("mix_id",)},
    "music":     {"name": ("mc_name", "name", "title"), "id": ("mc_id",)},
    "series":    {"name": ("series_name", "name", "title"), "id": ("series_id",)},
}


def build_favorites_widgets():
    from PySide6.QtCore import Qt, QUrl
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import (
        QApplication,
        QHBoxLayout,
        QMenu,
        QMessageBox,
        QStackedWidget,
        QVBoxLayout,
        QWidget,
    )
    from qfluentwidgets import (
        LineEdit,
        PushButton,
        SegmentedWidget,
        TableWidget,
    )

    from ...core.config import load_config
    from ..feedback import (
        toast_error,
        toast_info,
        toast_success,
        toast_warning,
    )
    from ..theme import (
        SPACE_LG,
        SPACE_MD,
        SPACE_XL,
        subscribe_theme,
    )
    from ..widgets import (
        build_empty_state,
        build_error_state,
        build_loading_state,
        build_page_header,
        build_stat_chip,
    )

    class FavoritesPage(QWidget):
        def __init__(self, parent: Optional[QWidget] = None):
            super().__init__(parent)
            self.setObjectName("favoritesPage")
            self._cfg = load_config(None)
            self._rows: list[dict] = []
            self._kind = FAVORITE_KINDS[0][0]
            #: Set by ``main_window`` right after construction; ``None``
            #: keeps the page buildable stand-alone.
            self._task_manager = None
            #: Set by ``main_window``: 跳设置页登录用（可选）。
            self._open_settings = None
            self._build_ui()
            subscribe_theme(self, lambda: None)

        # ---- public API ----------------------------------------------

        def set_task_manager(self, manager) -> None:
            """主窗口接线：右键「下载」需要它才能入队。"""
            self._task_manager = manager

        def set_open_settings_callback(self, callback) -> None:
            """主窗口接线：未登录引导态的「去设置页登录」按钮。"""
            self._open_settings = callback

        def _build_ui(self):
            PageHeader = build_page_header()
            EmptyState = build_empty_state()
            ErrorState = build_error_state()
            LoadingState = build_loading_state()
            StatChip = build_stat_chip()

            outer = QVBoxLayout(self)
            outer.setContentsMargins(SPACE_XL, SPACE_LG, SPACE_XL, SPACE_LG)
            outer.setSpacing(SPACE_LG)

            self._header = PageHeader(self)
            self._header.set_title("收藏")
            self._header.set_subtitle(
                "抖音收藏全家族（收藏夹 / 视频 / 合集 / 音乐 / 短剧），"
                "需登录抖音。数据来自 CLI `doubi favorites` 同源。"
            )
            self.refresh_btn = PushButton("刷新", self)
            self.refresh_btn.clicked.connect(self._on_refresh)
            self._header.add_action(self.refresh_btn)
            outer.addWidget(self._header)

            # ---- 类型切换 ----
            self._kind_tabs = SegmentedWidget(self)
            for value, label in FAVORITE_KINDS:
                self._kind_tabs.addItem(routeKey=value, text=label)
            self._kind_tabs.setCurrentItem(FAVORITE_KINDS[0][0])
            self._kind_tabs.currentItemChanged.connect(self._on_kind_changed)
            outer.addWidget(self._kind_tabs)

            # ---- 收藏夹 ID（仅「收藏夹视频」类可见）----
            id_row = QHBoxLayout()
            id_row.setSpacing(SPACE_MD)
            self._collect_id_label = LineEdit(self)
            self._collect_id_label.setPlaceholderText("收藏夹 ID（collects_id）")
            self._collect_id_label.setFixedWidth(260)
            self._collect_id_input = LineEdit(self)
            self._collect_id_input.setPlaceholderText(
                "从「收藏夹」列表右键「查看收藏夹视频」自动填入，或手填 ID"
            )
            self._collect_id_input.returnPressed.connect(self._on_refresh)
            id_row.addWidget(self._collect_id_label)
            id_row.addWidget(self._collect_id_input, 1)
            outer.addLayout(id_row)
            self._id_row_widgets = (self._collect_id_label, self._collect_id_input)

            # ---- 状态条 ----
            stats_row = QHBoxLayout()
            stats_row.setSpacing(SPACE_MD)
            self._stat_hits = StatChip(self)
            self._stat_hits.set_kind("running")
            self._stat_hits.set_label("本次条目数")
            stats_row.addWidget(self._stat_hits, 1)
            stats_row.addStretch(3)
            outer.addLayout(stats_row)

            self._stack = QStackedWidget(self)
            self.table = TableWidget(self)
            self.table.setColumnCount(4)
            self.table.setHorizontalHeaderLabels(["名称", "标识 ID", "类型", "链接"])
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
                "尚未加载",
                "点「刷新」拉取收藏数据。",
            )
            self._stack.addWidget(self._empty_state)

            self._error_state = ErrorState(self)
            self._stack.addWidget(self._error_state)

            self._loading_state = LoadingState(self)
            self._loading_state.set_message("正在拉取收藏…")
            self._stack.addWidget(self._loading_state)

            outer.addWidget(self._stack, 1)

            self._stack.setCurrentWidget(self._empty_state)
            self._sync_collect_id_visibility()

        # ---- helpers ---------------------------------------------------

        def _current_kind(self) -> str:
            # qfluentwidgets 的 SegmentedWidget 要用 currentRouteKey()，
            # currentItem() 返回的是对象（与热榜页同坑）。
            return self._kind_tabs.currentRouteKey() or self._kind

        def _sync_collect_id_visibility(self) -> None:
            visible = self._current_kind() == "videos"
            for w in self._id_row_widgets:
                w.setVisible(visible)

        def _resolve_douyin_cookies(self):
            """GUI 侧抖音 cookie 解析：显式配置优先，回落默认登录路径。

            与 CLI 不同（CLI 要求显式 --cookies-file），GUI 用户在设置页
            登录后 cookie 落在 auth 模块的默认路径上——收藏全家族必须
            登录，这里替用户把两处接起来。
            """
            from pathlib import Path

            if self._cfg.cookies_file:
                p = Path(self._cfg.cookies_file)
                if p.is_file():
                    return p
            from ...platforms.douyin.auth import default_cookie_path

            p = default_cookie_path()
            return p if p.is_file() else None

        def _show_error_state(self, message: str, *, need_login: bool = False) -> None:
            self._loading_state.stop()
            self.refresh_btn.setEnabled(True)
            if need_login:
                self._error_state.set_text(
                    "需要登录抖音",
                    "收藏全家族的所有端点都要求登录态。请到「设置」页登录抖音后重试。",
                )
                if self._open_settings is not None:
                    self._error_state.set_action("去设置页登录", self._open_settings)
                else:
                    self._error_state.set_action("重试", self._on_refresh)
            else:
                self._error_state.set_text(
                    "收藏拉取失败",
                    f"{message or '未知错误'}\n请检查网络后重试。",
                )
                self._error_state.set_action("重试", self._on_refresh)
            self._stack.setCurrentWidget(self._error_state)

        # ---- 数据流 ----------------------------------------------------

        def _on_kind_changed(self, route_key: str) -> None:
            self._kind = route_key
            self._sync_collect_id_visibility()
            # 切类型即刷新：各类型的行结构完全不同，留着旧表只会误导。
            if self._rows:
                self._on_refresh()

        def _on_refresh(self) -> None:
            kind = self._current_kind()
            collect_id = self._collect_id_input.text().strip()
            if kind == "videos" and not collect_id:
                toast_warning(
                    self, "缺少收藏夹 ID",
                    "先在「收藏夹」列表里右键「查看收藏夹视频」，或手填收藏夹 ID。",
                )
                return
            if self._resolve_douyin_cookies() is None:
                self._show_error_state("", need_login=True)
                return
            self._loading_state.set_message("正在拉取收藏…")
            self._loading_state.start()
            self._stack.setCurrentWidget(self._loading_state)
            self.refresh_btn.setEnabled(False)
            try:
                self._run_async(self._run_favorites(kind, collect_id))
            except Exception as exc:
                logger.exception("favorites list failed: %s", exc)
                self._show_error_state(str(exc))

        async def _run_favorites(self, kind: str, collect_id: str) -> None:
            from doubi.cli.main import collect_favorites_async

            try:
                rows = await collect_favorites_async(
                    kind=kind,
                    collect_id=collect_id or None,
                    max_count=50,
                    cookies_file=self._resolve_douyin_cookies(),
                    proxy=self._cfg.proxy,
                    timeout=15.0,
                )
            except Exception as exc:  # noqa: BLE001 - reported to user
                self._show_error_state(str(exc))
                return

            self._loading_state.stop()
            self.refresh_btn.setEnabled(True)
            self._rows = list(rows or [])
            self._stat_hits.set_value(len(self._rows))
            if self._rows:
                self._populate_table()
                self._stack.setCurrentWidget(self.table)
            else:
                self._empty_state.set_text(
                    "暂无内容",
                    "这一类收藏是空的，或平台限流了。稍后重试，"
                    "或先到「设置」页确认抖音登录态。",
                )
                self._stack.setCurrentWidget(self._empty_state)

        def _populate_table(self) -> None:
            from PySide6.QtWidgets import QTableWidgetItem

            from doubi.cli.main import FAVORITES_KIND_NAMES

            kind = self._current_kind()
            fields = KIND_ROW_FIELDS.get(kind, {})
            kind_name = FAVORITES_KIND_NAMES.get(kind, kind)
            self.table.setRowCount(len(self._rows))
            for i, row in enumerate(self._rows):
                if not isinstance(row, dict):
                    row = {}

                def first(keys) -> str:
                    for key in keys:
                        value = row.get(key)
                        if value not in (None, ""):
                            return str(value)
                    return ""

                name = first(fields.get("name", ()))
                rid = first(fields.get("id", ()))
                if kind == "videos":
                    from ..row_actions import share_url_for

                    url = share_url_for(row, "douyin") or ""
                else:
                    url = ""
                self.table.setItem(i, 0, QTableWidgetItem(name))
                self.table.setItem(i, 1, QTableWidgetItem(rid))
                self.table.setItem(i, 2, QTableWidgetItem(kind_name))
                self.table.setItem(i, 3, QTableWidgetItem(url))

        # ---- 右键菜单 --------------------------------------------------

        def _menu_actions_for(self, record: dict, kind: str) -> list[tuple[str, bool]]:
            """纯函数：该类行应出现哪些菜单动作、各自是否可用。

            与热榜页 ``_context_menu_entries`` 同构——把「哪类行有哪些
            动作」的分叉从 QMenu 构造里剥出来，offscreen 测试才能不打
            断事件循环地 pin 死分叉表。
            """
            if kind == "favorites":
                return [("查看收藏夹视频", bool(record.get("collects_id")))]
            if kind == "mix":
                return [("下载整个合集", bool(record.get("mix_id")))]
            if kind == "videos":
                from ..row_actions import share_url_for

                has_url = bool(share_url_for(record, "douyin"))
                enabled_manager = self._task_manager is not None
                return [
                    ("下载", has_url and enabled_manager),
                    ("复制链接", has_url),
                    ("在浏览器中打开", has_url),
                ]
            # music / series：与 CLI 对齐，仅列表无动作。
            return []

        def _on_table_context_menu(self, pos) -> None:
            row = self.table.rowAt(pos.y())
            if row < 0 or row >= len(self._rows):
                return
            self.table.setCurrentCell(row, self.table.currentColumn())
            record = self._rows[row]
            kind = self._current_kind()

            entries = self._menu_actions_for(record, kind)
            if not entries:
                return

            menu = QMenu(self.table)
            actions = {label: menu.addAction(label) for label, _enabled in entries}
            for label, enabled in entries:
                actions[label].setEnabled(enabled)

            chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
            if chosen is None:
                return
            label = chosen.text()

            if kind == "videos":
                from ..row_actions import share_url_for

                url = share_url_for(record, "douyin")
                if not url:
                    return
                if label == "复制链接":
                    clipboard = QApplication.clipboard()
                    if clipboard is not None:
                        clipboard.setText(url)
                        toast_success(self, "已复制链接", url)
                elif label == "在浏览器中打开":
                    QDesktopServices.openUrl(QUrl(url))
                elif label == "下载":
                    self._enqueue_row(record, url)
                return
            if kind == "favorites" and label == "查看收藏夹视频":
                self._drill_into_videos(record)
            elif kind == "mix" and label == "下载整个合集":
                self._enqueue_whole_mix(record)

        def _drill_into_videos(self, record: dict) -> None:
            """收藏夹行 → 切到「收藏夹视频」并填入 collects_id 刷新。"""
            collects_id = str(record.get("collects_id") or "").strip()
            if not collects_id:
                toast_warning(self, "缺少收藏夹 ID", "这一行没有 collects_id 字段。")
                return
            self._collect_id_input.setText(collects_id)
            self._kind_tabs.setCurrentItem("videos")
            # setCurrentItem 会触发 currentItemChanged → _on_kind_changed
            # → 有行就刷新；但首次下钻时 _rows 可能还是空，保险起见直接刷。
            self._on_refresh()

        # ---- 入队 ------------------------------------------------------

        def _enqueue_row(self, record: dict, url: str) -> None:
            """把一行收藏视频解析成 MediaItem 并入队（与热榜页同构）。"""
            if self._task_manager is None:
                toast_error(self, "未连接任务管理器", "请在主窗口中打开此页面。")
                return

            async def _do():
                from ..row_actions import build_media_item, row_label

                item, children = await build_media_item(url)
                targets = children or ([item] if item is not None else [])
                if not targets:
                    toast_error(
                        self, "无法下载",
                        f"没能解析出行内容：{row_label(record) or url}",
                    )
                    return
                opts = self._build_options()
                for target in targets:
                    self._task_manager.add(target, opts)
                toast_success(
                    self, "已加入下载队列",
                    f"{row_label(record) or url}（{len(targets)} 项）",
                )

            self._run_async(_do())

        def _enqueue_whole_mix(self, record: dict) -> None:
            """收藏合集行：展开合集 → 确认 → 整包入队。

            与热榜页「搜索该词条并下载」同序：先展开、解析成**真实条数**，
            再拿这个数弹确认框——确认框上的数字必须和实际入队数一致。
            """
            if self._task_manager is None:
                toast_error(self, "未连接任务管理器", "请在主窗口中打开此页面。")
                return
            mix_id = str(record.get("mix_id") or "").strip()
            mix_name = str(
                record.get("mix_name") or record.get("name") or mix_id
            ).strip()
            if not mix_id:
                toast_warning(self, "缺少合集 ID", "这一行没有 mix_id 字段。")
                return

            async def _do():
                from ...platforms.douyin.webapi import DouyinWebAPI
                from ..row_actions import build_media_item, share_url_for
                from ..row_confirm import confirm_plan

                cookies = self._resolve_douyin_cookies()
                api = DouyinWebAPI(
                    cookies_file=cookies, proxy=self._cfg.proxy, timeout=15.0,
                )
                sink: dict = {}
                try:
                    awemes = await api.iter_mix_awemes(
                        mix_id, max_count=100, error_sink=sink,
                    )
                except Exception as exc:  # noqa: BLE001 - reported to user
                    logger.exception("mix expand failed: %s", exc)
                    toast_error(self, "合集展开失败", f"{mix_name}：{exc}")
                    return

                urls = []
                for aweme in awemes:
                    if isinstance(aweme, dict):
                        url = share_url_for(aweme, "douyin")
                        if url:
                            urls.append(url)
                if not urls:
                    hint = sink.get("hint")
                    if hint == "need_login":
                        self._show_error_state("", need_login=True)
                    else:
                        toast_warning(
                            self, "合集为空",
                            f"「{mix_name}」没有拿到可下载的视频。",
                        )
                    return

                opts = self._build_options()
                pending = []
                for url in urls:
                    item, _children = await build_media_item(url)
                    if item is None:
                        continue
                    pending.append(item)
                if not pending:
                    toast_warning(
                        self, "没有可入队的视频",
                        f"「{mix_name}」命中 {len(urls)} 条，但都没能解析出媒体项。",
                    )
                    return

                # 「container」分支即「展开合集 / 主页」语义，文案与本
                # 动作完全同构，不新增 confirm kind。
                plan = confirm_plan(
                    kind="container", label=mix_name, count=len(pending),
                )
                if not self._confirm(plan):
                    toast_info(
                        self, "已取消",
                        f"「{mix_name}」的 {len(pending)} 个视频未加入队列。",
                    )
                    return

                for item in pending:
                    self._task_manager.add(item, opts)
                toast_success(
                    self, "已加入下载队列",
                    f"「{mix_name}」共 {len(pending)} 个视频。",
                )

            self._run_async(_do())

        def _confirm(self, plan) -> bool:
            """把 :class:`ConfirmPlan` 渲染成模态框（与热榜页同构，便于测试替换）。"""
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Question)
            box.setWindowTitle(plan.title)
            box.setText(plan.body)
            yes = box.addButton(plan.confirmed_text, QMessageBox.AcceptRole)
            box.addButton(plan.cancelled_text, QMessageBox.RejectRole)
            box.setDefaultButton(box.buttons()[-1])
            box.exec()
            return box.clickedButton() is yes

        def _run_async(self, coro) -> None:
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
            """``AppConfig -> DownloadOptions``（与解析页同源同字段）。"""
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

    return FavoritesPage, None
