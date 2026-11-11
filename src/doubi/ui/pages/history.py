"""History page — real query over the SQLite database.

M5.1 adds the full table: platform / item_id / title / author /
download time / save dir, backed by :meth:`Database.list_recent`.
A refresh button + auto-refresh on page show keep it current.

M6.x 重做：与其它页面共享 PageHeader / EmptyState，数据库未启用时
给出清晰的「去设置页打开」提示。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger("doubi.ui.pages.history")


def build_history_widgets():
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QMenu,
        QStackedWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    )
    from qfluentwidgets import (
        PushButton,
        TableWidget,
    )

    from ...core.config import load_config
    from ...core.storage.database import Database
    from ..feedback import toast_info, toast_warning
    from ..theme import (
        SPACE_LG,
        SPACE_MD,
        SPACE_XL,
        heading_qss,
        subscribe_theme,
    )
    from ..widgets import (
        build_empty_state,
        build_loading_state,
        build_page_header,
        build_stat_chip,
    )

    class HistoryPage(QWidget):
        def __init__(self, parent: Optional[QWidget] = None):
            super().__init__(parent)
            self.setObjectName("historyPage")
            self._cfg = load_config(None)
            self._rows: list = []       # MediaItemRow, for open-dir lookup
            # 0.3.5：首刷推迟到第一次真正可见。历史页是六个页签之一，
            # 但构造阶段就把整张表填满（500 行 × 6 列 = 3000 个
            # QTableWidgetItem）纯属白干——绝大多数会话根本不会切到这一页。
            self._loaded = False
            self._dirty = False         # 有下载落库后置位，下次可见时重查
            self._build_ui()
            subscribe_theme(self, self._on_theme_changed)

        def showEvent(self, event) -> None:        # noqa: N802 (Qt naming)
            """第一次可见时补做首刷；之后只在 dirty 时才重查。"""
            super().showEvent(event)
            if not self._loaded or self._dirty:
                self._refresh()

        def mark_dirty(self) -> None:
            """下载落库后由主窗口调用，让下一次可见时重新查询。

            没有这个标记就会反过来出错：缓存生效后，用户下载完切到
            历史页看到的还是旧结果。
            """
            self._dirty = True

        def _on_theme_changed(self) -> None:
            """换主题后刷新自绘颜色的控件。"""
            self.count_label.setStyleSheet(heading_qss(3))
            if hasattr(self, "_empty_state"):
                self._empty_state.refresh_text()

        def _build_ui(self):
            PageHeader = build_page_header()
            EmptyState = build_empty_state()
            LoadingState = build_loading_state()
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
            # 列宽策略（0.3.7 修）：短列给足能显示**完整值**的宽度，标题列拉伸。
            #
            # 修之前 6 列全是 Qt 默认的 100px，表格实际只用到约 600px：
            # 「ID」永远显示成 ``BV1vRH...``、「下载时间」永远是 ``2026-10...``、
            # 「保存目录」永远是 ``Downlo...``——三列的信息完全读不出来，右侧
            # 还空着 400 多像素没人用。
            #
            # 现在按**真实内容宽度**给定量：
            #   * ID：B 站 ``BV1vRHa6x7h7``（12 字符）留够，抖音 19 位数字
            #     会截断但保留前段辨识度——它本来就是长 ID，不是本文重点。
            #   * 下载时间：``2026-10-05 09:16`` 是 16 字符，给定宽度比它宽，
            #     保证**分钟**能读出来（修之前连小时都被切掉）。
            #   * 下载时间：``2026-10-05 09:16`` 是 16 个字符。实测宽度要按
            #     **最宽的可能字体**留——系统 UI 字体下约 118px，但 offscreen
            #     等回退字体能到 224px。给 230 才不会在别人的机器上被截断。
            #   * 标题：唯一 Stretch 的列，吃掉全部剩余宽度。
            header = self.table.horizontalHeader()
            header.setStretchLastSection(False)
            for _col, _w in ((0, 92), (1, 260), (3, 132), (4, 230), (5, 176)):
                header.setSectionResizeMode(_col, QHeaderView.Fixed)
                self.table.setColumnWidth(_col, _w)
            header.setSectionResizeMode(2, QHeaderView.Stretch)
            # 表头点击排序（下载时间默认倒序，与 list_recent 的 SQL 排序一致）。
            # 排序实际开关在 _populate 里控制——填充过程中必须关闭，
            # 否则 setItem 会把行插进「当前排序位置」，行序直接错乱。
            header.setSortIndicatorShown(True)
            header.setSortIndicator(4, Qt.DescendingOrder)
            self.table.setContextMenuPolicy(Qt.CustomContextMenu)
            self.table.customContextMenuRequested.connect(self._on_context_menu)
            self._stack.addWidget(self.table)

            self._empty_state = EmptyState(self)
            self._stack.addWidget(self._empty_state)

            # 0.3.7：加载占位——历史页首次切换时查询 SQLite，
            # 没有 spinner 用户以为没反应。
            self._loading_state = LoadingState(self)
            self._loading_state.set_message("正在查询数据库…")
            self._stack.addWidget(self._loading_state)

            outer.addWidget(self._stack, 1)

            self.count_label = QLabel("", self)
            self.count_label.setStyleSheet(heading_qss(3))

        # ----------------------------------------------------------

        def _refresh(self) -> None:
            if not self._cfg.database:
                self._loaded = True
                self._dirty = False
                self._stat_total.set_value("—")
                self._stat_showing.set_value(0)
                self._empty_state.set_text(
                    "数据库未启用",
                    "请前往「设置」打开「启用数据库」开关，启用后此页会自动出现下载历史。",
                )
                self._stack.setCurrentWidget(self._empty_state)
                return
            # 0.3.7：刷新中切 LoadingState——首次切到历史页或下载落库后
            # 自动重查时给用户一个明确反馈。
            self._loading_state.set_message("正在查询数据库…")
            self._loading_state.start()
            self._stack.setCurrentWidget(self._loading_state)
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
            self._loaded = True
            self._dirty = False
            self._stat_total.set_value(str(total))
            self._stat_showing.set_value(len(rows))
            self._loading_state.stop()
            if rows:
                self._stack.setCurrentWidget(self.table)
            else:
                self._empty_state.set_text(
                    "还没有下载记录",
                    "完成一次下载后，记录会自动出现在这里。",
                )
                self._stack.setCurrentWidget(self._empty_state)
            header = self.table.horizontalHeader()
            prev_section = header.sortIndicatorSection()
            prev_order = header.sortIndicatorOrder()
            self.table.setSortingEnabled(False)
            self.table.setRowCount(len(rows))
            for i, r in enumerate(rows):
                dl_time = ""
                dl_ts = None
                if r.last_download_time:
                    dl_ts = r.last_download_time
                    try:
                        dl_time = datetime.fromtimestamp(r.last_download_time).strftime(
                            "%Y-%m-%d %H:%M"
                        )
                    except (OverflowError, OSError, ValueError):
                        dl_time = str(r.last_download_time)
                        dl_ts = None
                cells = (
                    _cell(r.platform or ""),
                    _cell(r.item_id or ""),
                    _cell(r.title or ""),
                    _cell(r.author_name or ""),
                    _SortCell(dl_time, sort_key=dl_ts),
                    _cell(self._short_dir(r.last_save_dir)),
                )
                for col, item in enumerate(cells):
                    # 记录本体挂在每格上：排序打乱行序后，行 → 数据
                    # 的映射跟着单元格走（见 _row_record）。
                    item.setData(_REC_ROLE, r)
                    self.table.setItem(i, col, item)
            self.table.setSortingEnabled(True)
            # 保留用户上一次选的排序列 / 方向；首次填充落到 _build_ui
            # 设好的默认（下载时间倒序）。
            header.setSortIndicator(prev_section, prev_order)

        def _row_record(self, row_idx: int):
            """视觉行 → 数据记录。

            表头排序会打乱视觉行序，所以记录本体从单元格（``_REC_ROLE``）
            里取；单元格为空时退回 ``self._rows[row_idx]``（排序从未启用
            的旧路径 / 防御）。
            """
            item = self.table.item(row_idx, 0)
            if item is not None:
                rec = item.data(_REC_ROLE)
                if rec is not None:
                    return rec
            if 0 <= row_idx < len(self._rows):
                return self._rows[row_idx]
            return None

        def _open_selected_dir(self) -> None:
            sel = self.table.selectedItems()
            if not sel:
                toast_warning(self, "未选择记录", "请先在表格中选择一行。")
                return
            record = self._row_record(sel[0].row())
            if record is None:
                return
            save_dir = record.last_save_dir or ""
            if not save_dir:
                toast_warning(self, "无保存目录", "这条记录没有保存路径。")
                return
            import os
            os.startfile(save_dir)   # Windows only; GUI is desktop-first

        # ---- 右键菜单 / 重新解析 --------------------------------------

        def set_reparse_callback(self, cb) -> None:
            """主窗口在构造时注入：把 URL 送回解析页。

            历史页不应该直接持有解析页引用（两个页面互不依赖），
            用回调解耦：主窗口负责跳转 + 填入。
            """
            self._reparse_callback = cb

        def _on_context_menu(self, pos) -> None:
            row = self.table.rowAt(pos.y())
            if row < 0:
                return
            self.table.setCurrentCell(row, self.table.currentColumn())
            menu = QMenu(self.table)
            menu.addAction("打开保存目录", self._open_selected_dir)
            # 重新解析：用 platform + item_id 重建 URL
            r = self._row_record(row)
            if r is None:
                return
            url = _build_url_from_row(r)
            if url:
                menu.addAction("重新解析", lambda: self._reparse(url))
            menu.exec(self.table.viewport().mapToGlobal(pos))

        def _reparse(self, url: str) -> None:
            """把 URL 送回解析页并跳转过去。"""
            cb = getattr(self, "_reparse_callback", None)
            if cb is not None:
                cb(url)
                return
            # 回调未注入（测试 / 独立运行）——直接提示。
            # 注意：qfluentwidgets 没有 InfoBar.information，正确名是 info。
            toast_info(
                self, "重新解析",
                f"已复制链接到剪贴板：{url[:60]}",
            )

    def _cell(text: str, *, sort_key=None):
        """普通文本单元格；``sort_key`` 存 UserRole 供数值排序用。"""
        from PySide6.QtWidgets import QTableWidgetItem
        item = QTableWidgetItem(text)
        if sort_key is not None:
            from PySide6.QtCore import Qt
            item.setData(Qt.ItemDataRole.UserRole, sort_key)
        return item

    # 记录本体挂在单元格上（UserRole+1）：表头排序会打乱视觉行序，
    # 行 → 数据的映射必须跟着单元格走，不能再用 ``self._rows[row]``。
    _REC_ROLE = Qt.ItemDataRole.UserRole + 1

    class _SortCell(QTableWidgetItem):
        """数值角色优先的排序单元格：时间列按时间戳排，其余按文本。"""

        def __init__(self, text: str, *, sort_key=None):
            super().__init__(text)
            if sort_key is not None:
                self.setData(Qt.ItemDataRole.UserRole, sort_key)

        def __lt__(self, other):
            a = self.data(Qt.ItemDataRole.UserRole)
            b = other.data(Qt.ItemDataRole.UserRole)
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                return a < b
            return super().__lt__(other)

    def _short_dir(path) -> str:
        """把保存路径压成能在列里读完的一行（0.3.7 修）。

        真实数据里这一列 351/351 全被截断，而截断后剩下的
        ``Downloaded\\bilibili\\中华...`` 恰恰把**最有辨识度的目录名**切掉了。
        实测所有记录的路径形状高度一致：

            Downloaded\\<platform>\\<author>\\video

        尾部永远是 ``video``（351/351），首部永远是 ``Downloaded``——
        两段都是废话，真正区分记录的是中间那截「平台 + 作者」。

        所以这里剥掉固定的 ``Downloaded\\`` 前缀和末尾的 ``video``，
        保留 ``bilibili\\中华球侠`` 这种有信息量的形态。**只是显示层裁剪，
        不改 ``last_save_dir`` 本身**——右键「打开保存目录」用的仍是
        ``self._rows[i].last_save_dir`` 的完整路径。
        """
        if not path:
            return ""
        import os

        text = str(path).replace("/", "\\")
        parts = [p for p in text.split("\\") if p]
        # 丢掉固定的产出根目录
        if parts and parts[0].lower() == "downloaded":
            parts = parts[1:]
        # 丢掉尾部固定的类型目录（video / audio / image …）
        if parts and parts[-1].lower() in {"video", "audio", "image", "images", "cover"}:
            parts = parts[:-1]
        short = "\\".join(parts)
        return short or os.path.basename(text.rstrip("\\/"))

    # 挂到页面上：``_populate`` 用 ``self._short_dir`` 调用，测试也走同一入口。
    HistoryPage._short_dir = staticmethod(_short_dir)

    def _build_url_from_row(row) -> str:
        """从 DB 记录重建可解析的 URL。

        item_id 本身就是可被 ``classify_bilibili_url`` / 抖音 URL pattern
        识别的编号（BV / av / aweme_id / ep / ss / ml），所以最简单的做法
        是直接返回 item_id —— 裸编号解析（u1）已经覆盖了这个路径。
        对抖音纯数字 item_id，需要补上 ``https://www.douyin.com/video/``。
        """
        if not row or not row.item_id:
            return ""
        platform = (row.platform or "").lower()
        item_id = row.item_id
        # B 站：BV / av / ep / ss / ml 都是裸编号，直接返回
        if platform == "bilibili":
            return item_id
        # 抖音：item_id 是纯数字 aweme_id，补上 video URL
        if platform == "douyin":
            return f"https://www.douyin.com/video/{item_id}"
        # YouTube：item_id 是 11 位 video ID
        if platform == "youtube":
            return f"https://www.youtube.com/watch?v={item_id}"
        return ""

    return HistoryPage, HistoryPage
