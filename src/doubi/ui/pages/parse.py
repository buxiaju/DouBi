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


# ---------------------------------------------------------------------------
# Prompt options dialog (M6.11 下载前询问)
# ---------------------------------------------------------------------------
#
# 故意放在模块顶层、不嵌进 ``build_parse_widgets`` 工厂里：
# * 单元测试可以直接 ``from doubi.ui.pages.parse import PromptOptionsDialog``
#   拿到实例，不需要先把整个 ParsePage / qfluentwidgets 主题表跑一遍。
# * PySide6 / qfluentwidgets 都在 ``PromptOptionsDialog.__init__`` 内部延迟
#   import，模块顶层不引入任何 Qt 符号——没装 PySide6 的环境（CLI / 测试
#   收集阶段）不会因此报错。
#
# 这是个 ``MessageBoxBase`` 子类：两个按钮（"下载" / "取消"），点"下载"
# 时返回 1 + 用户在表单里改的值；点"取消"或 ESC 时返回 0，不修改配置。
# 控件挂在 ``viewLayout``（这是项目里这个版本的 qfluentwidgets 提供的
# 容器，**不是** 文档示例里的 ``view`` widget）。选项集合刻意复用设置
# 页已定的 ``["mp4","mkv"]`` / ``["best","8k",...]``，避免在两处维护。

_QUALITY_CHOICES = ("best", "8k", "4k", "1080p", "720p", "480p")
_CONTAINER_CHOICES = ("mp4", "mkv")


def _build_prompt_dialog_class():
    """Lazy-import Qt and return the dialog class.

    Done in a helper so the module can be imported on machines without
    PySide6 — the rest of ``parse.py`` is unrelated to the dialog.
    """
    from PySide6.QtWidgets import (
        QCheckBox, QComboBox, QFormLayout, QWidget,
    )
    from qfluentwidgets import MessageBoxBase

    class PromptOptionsDialog(MessageBoxBase):
        """'Download with what options?' dialog. Two buttons (下载 / 取消).

        Pre-fills from ``seed``: typically the current ``DownloadOptions``
        so the user only tweaks what they want to change.
        """

        def __init__(self, parent: QWidget, seed):
            super().__init__(parent)
            # 默认按钮文案是 'OK' / 'Cancel'——这个版本的 qfluentwidgets
            # 没有提供 label 自带的 setTitle 之外的文案入口，直接改。
            self.yesButton.setText("下载")
            self.cancelButton.setText("取消")

            self.quality = QComboBox(self)
            self.quality.addItems(_QUALITY_CHOICES)
            self.container = QComboBox(self)
            self.container.addItems(_CONTAINER_CHOICES)
            self.thumb = QCheckBox("生成缩略图 (.jpg)", self)
            self.metadata_json = QCheckBox("写入 metadata.json", self)

            # seed -> 控件当前值
            self.quality.setCurrentText(str(seed.max_quality))
            self.container.setCurrentText(str(seed.container))
            self.thumb.setChecked(bool(seed.write_thumbnail))
            self.metadata_json.setChecked(bool(seed.write_metadata_json))

            form = QFormLayout()
            form.setSpacing(8)
            form.addRow("最高画质", self.quality)
            form.addRow("容器格式", self.container)
            form.addRow("附加产物", self.thumb)
            form.addRow("", self.metadata_json)
            self.viewLayout.addLayout(form)

    return PromptOptionsDialog


def collect_prompt_overrides(dialog) -> dict:
    """Pure-function helper: read a PromptOptionsDialog's controls.

    Kept module-level so unit tests can verify field collection without
    ``exec()`` (which would block in offscreen tests). Returns a dict
    that can be passed straight into ``dataclasses.replace(options, **x)``.
    Only the four fields the dialog exposes are ever set — no spillover.
    """
    return {
        "max_quality": dialog.quality.currentText(),
        "container": dialog.container.currentText(),
        "write_thumbnail": dialog.thumb.isChecked(),
        "write_metadata_json": dialog.metadata_json.isChecked(),
    }


# 模块顶层的轻量引用，仅当 Qt 可用时才被解析；测试在没装 Qt 的环境下
# 仍可 ``import doubi.ui.pages.parse``。
try:  # pragma: no cover - import availability gate
    PromptOptionsDialog = _build_prompt_dialog_class()
except Exception:  # noqa: BLE001
    PromptOptionsDialog = None  # type: ignore[assignment]


def build_parse_widgets():
    from PySide6.QtCore import QObject, Qt, QUrl, Signal, QTimer
    from PySide6.QtGui import QDesktopServices, QGuiApplication
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
    from ..theme import (
        SPACE_LG, SPACE_MD, SPACE_SM, SPACE_XL, SPACE_XS,
        TYPE_BODY, TYPE_CAPTION, FONT_FAMILY, RADIUS_CARD,
        heading_qss, muted_qss, subscribe_theme,
    )
    from ..widgets import (
        build_page_header, build_empty_state, build_platform_badge,
    )

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
            # 提示文字的颜色写在 stylesheet 里，换主题时得重刷。
            subscribe_theme(self, self._on_theme_changed)
            # 剪贴板监听：用户在浏览器 / APP 里复制链接后，不用切回豆比
            # 再粘贴——直接弹 InfoBar 提示「检测到链接，已填入」。1.5s
            # 轮询足够即时，又不至于在打字时抢焦点。对比上次内容，只在
            # 新链接出现时弹，避免每次 focus 都弹一遍。
            self._last_clipboard_text: str = ""
            self._clipboard_timer = QTimer(self)
            self._clipboard_timer.setInterval(1500)
            self._clipboard_timer.timeout.connect(self._poll_clipboard)
            self._clipboard_timer.start()

        def _on_theme_changed(self) -> None:
            """换主题后刷新自绘颜色的控件。"""
            # hint 文案由 PageHeader 的副标题承载——但有些旧调用点（解析按钮
            # loading 文本）仍会读 hint，这里留空实现保持 ABI 兼容。
            pass

        # ---- 剪贴板监听 ----------------------------------------------

        def _poll_clipboard(self) -> None:
            """1.5s 轮询剪贴板，检测到新链接时填入输入框并提示。

            用 ``PlatformRegistry.detect()`` 判断剪贴板文本是否是已知
            链接（含裸编号），而不是用字符串匹配——这样新增平台自动覆盖，
            不用每次在这里加 URL pattern。只在文本变化时触发，避免重复
            弹窗。如果用户正在输入框里打字（光标在 url_input 里），
            不自动填入——避免打断输入。
            """
            try:
                clip = QGuiApplication.clipboard()
                text = (clip.text() or "").strip()
            except Exception:
                return
            if not text or text == self._last_clipboard_text:
                return
            self._last_clipboard_text = text

            # 用 registry 判断是否是已知链接
            from ...core.registry import PlatformRegistry
            adapter = PlatformRegistry.detect(text)
            if adapter is None:
                return
            # M6.16 起 GenericAdapter 兜底匹配**任意** http(s) URL，于是
            # ``detect()`` 对「复制了一条文档链接」也会返回非 None，剪贴板
            # 就会疯狂抢粘贴。这里只认具体平台（priority >= 0）：兜底嗅探
            # 仍然可以手动粘贴触发，但不该由剪贴板自动代劳。
            if getattr(adapter, "priority", 0) < 0:
                return

            # 用户正在输入框里打字时不自动覆盖
            if self.url_input.hasFocus():
                return

            # 填入并提示
            current = self.url_input.toPlainText().strip()
            if text in (current or ""):
                return
            if current:
                self.url_input.setPlainText(current + "\n" + text)
            else:
                self.url_input.setPlainText(text)
            self._toast(InfoBar.information, "检测到链接",
                        f"已从剪贴板填入：{text[:60]}")

        # ---- public API ----------------------------------------------

        def set_task_manager(self, manager) -> None:
            self._task_manager = manager

        def set_prompt_before_download(self, enabled: bool) -> None:
            """设置页保存后由主窗口转发下来：是否下载前先弹选项框。"""
            self._prompt_before_download = enabled

        def set_sniff_config(self, enabled: bool, duration_sec: int) -> None:
            """设置页保存后由主窗口转发下来：通用嗅探开关与时长。

            ``self._cfg`` 是构造时读的快照，不同步的话用户改完嗅探时长，
            解析按钮还会显示旧的 ``嗅探中… (15s)``。真正的注入
            （``GenericAdapter.set_config``）由设置页自己做，这里只更新
            本页要用到的两个显示字段。
            """
            self._cfg.sniff_enabled = enabled
            self._cfg.sniff_duration_sec = duration_sec

        def _ask_prompt_overrides(self) -> Optional[dict]:
            """弹「下载选项」对话框。返回 None 表示用户取消。

            默认行为是「点一下就走」：``self._prompt_before_download`` 未
            开启时直接返回空 dict，让 ``_options_for_overrides`` 走默认
            配置——这条路径在测试里也大量存在，不能被破坏。
            """
            if not getattr(self, "_prompt_before_download", False):
                return {}
            # 模块顶层可能在没装 Qt 的环境下把 ``PromptOptionsDialog`` 置
            # 成 None——这是理论兜底，正常 GUI 环境总是可用。
            if PromptOptionsDialog is None:
                return {}
            dlg = PromptOptionsDialog(self, self._build_options())
            if not dlg.exec():
                return None
            return collect_prompt_overrides(dlg)

        def current_options(self) -> DownloadOptions:
            """今天的配置对应的下载选项，供窗口级调用方复用。

            断点续传恢复需要一份 ``DownloadOptions``：数据库路径在里面，
            而快照缺失的字段也要拿它来补默认值。开这个公开出口，是为了
            让主窗口不必自己再拼一遍 ``AppConfig -> DownloadOptions``——
            那个搬运只允许存在一处（见 ``_build_options`` 与四端同名的
            ``test_build_options_covers_every_shared_config_field``）。
            """
            return self._build_options()

        # ---- UI build ------------------------------------------------

        def _build_ui(self):
            PageHeader = build_page_header()
            EmptyState = build_empty_state()

            outer = QVBoxLayout(self)
            outer.setContentsMargins(SPACE_XL, SPACE_LG, SPACE_XL, SPACE_LG)
            outer.setSpacing(SPACE_LG)

            # ---- 页头 ----
            self._header = PageHeader(self)
            self._header.set_title("解析")
            self._header.set_subtitle(
                "粘贴链接（每行一个），支持抖音 / B 站 / 合集 / 用户主页 / 短链接。"
            )
            outer.addWidget(self._header)

            # ---- 输入区（多行输入 + 平台 + 按钮 同一行） ----
            input_card = CardWidget(self)
            input_layout = QVBoxLayout(input_card)
            input_layout.setContentsMargins(SPACE_MD, SPACE_MD, SPACE_MD, SPACE_MD)
            input_layout.setSpacing(SPACE_MD)

            self.url_input = QPlainTextEdit(input_card)
            self.url_input.setPlaceholderText(
                "https://www.bilibili.com/video/BV1GJ411x7h7\n"
                "https://space.bilibili.com/486906719\n"
                "https://www.bilibili.com/list/ml12345\n"
                "https://www.douyin.com/video/7123456789012345678"
            )
            self.url_input.setFixedHeight(110)
            input_layout.addWidget(self.url_input)

            btn_row = QHBoxLayout()
            btn_row.setSpacing(SPACE_SM)
            btn_row.addStretch(1)
            self.parse_btn = PushButton("解析", input_card)
            self.parse_btn.clicked.connect(self._on_parse_clicked)
            self.quick_download_btn = PushButton("快速下载", input_card)
            self.quick_download_btn.setToolTip("解析第一个 URL 并直接加入下载队列")
            self.quick_download_btn.clicked.connect(self._on_quick_download_clicked)
            btn_row.addWidget(self.parse_btn)
            btn_row.addWidget(self.quick_download_btn)
            btn_row.addSpacing(SPACE_LG)
            platform_label = QLabel("平台：", input_card)
            platform_label.setStyleSheet(muted_qss())
            btn_row.addWidget(platform_label)
            self.platform_combo = ComboBox(input_card)
            self.platform_combo.addItems(["自动识别", "抖音", "B 站"])
            self.platform_combo.setCurrentIndex(0)
            btn_row.addWidget(self.platform_combo)
            input_layout.addLayout(btn_row)
            outer.addWidget(input_card)

            # ---- 结果区 ----
            self.result_card = CardWidget(self)
            self.result_layout = QVBoxLayout(self.result_card)
            self.result_layout.setContentsMargins(SPACE_MD, SPACE_MD, SPACE_MD, SPACE_MD)
            self.result_layout.setSpacing(SPACE_MD)

            top_row = QHBoxLayout()
            top_row.setSpacing(SPACE_MD)
            self.result_summary = QLabel("尚未解析。", self.result_card)
            self.result_summary.setStyleSheet(heading_qss(3))
            top_row.addWidget(self.result_summary, 1)
            self.search_box = SearchLineEdit(self.result_card)
            self.search_box.setPlaceholderText("搜索标题 / 作者…")
            self.search_box.setFixedWidth(220)
            self.search_box.textChanged.connect(self._on_search_changed)
            top_row.addWidget(self.search_box)
            self.result_layout.addLayout(top_row)

            actions_row = QHBoxLayout()
            actions_row.setSpacing(SPACE_SM)
            self.select_all_btn = PushButton("全选", self.result_card)
            self.select_all_btn.clicked.connect(self._select_all)
            self.select_none_btn = PushButton("全不选", self.result_card)
            self.select_none_btn.clicked.connect(self._select_none)
            self.select_range_btn = PushButton("按行号选择…", self.result_card)
            self.select_range_btn.clicked.connect(self._on_select_range)
            actions_row.addWidget(self.select_all_btn)
            actions_row.addWidget(self.select_none_btn)
            actions_row.addWidget(self.select_range_btn)
            actions_row.addStretch(1)
            self.download_selected_btn = PushButton("下载选中 (0)", self.result_card)
            self.download_selected_btn.clicked.connect(self._download_selected)
            actions_row.addWidget(self.download_selected_btn)
            self.result_layout.addLayout(actions_row)

            # 用一个 stack 切换「表格」与「空态」两套占位：解析前显示空态，
            # 解析后切换到表格。空态是 EmptyState 控件（透明 + 居中文案）。
            from PySide6.QtWidgets import QStackedWidget
            self._result_stack = QStackedWidget(self.result_card)
            self.result_layout.addWidget(self._result_stack, 1)

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
            # 行高拉大一点——之前 22 看起来太挤，改为更宽松的默认
            self.result_table.verticalHeader().setDefaultSectionSize(36)
            header = self.result_table.horizontalHeader()
            header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
            header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
            header.setSectionResizeMode(2, QHeaderView.Stretch)
            header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
            header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
            header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
            header.setSectionResizeMode(6, QHeaderView.ResizeToContents)
            self.result_table.itemChanged.connect(self._on_table_changed)
            self._result_stack.addWidget(self.result_table)

            self._empty = EmptyState(self.result_card)
            self._empty.set_text(
                "等待你粘贴链接",
                "支持视频 / 图集 / 直播 / 用户主页 / 收藏夹 / 合集 / 短链接\n"
                "粘贴后点击「解析」",
            )
            self._result_stack.addWidget(self._empty)
            self._result_stack.setCurrentWidget(self._empty)

            outer.addWidget(self.result_card, 1)

        # ---- parsing --------------------------------------------------

        def _sniff_seconds_for(self, urls: list[str]) -> int:
            """待解析 URL 里若有走 generic 兜底的，返回预计嗅探秒数，否则 0。

            解析按钮文案要区分「解析中…」和「嗅探中… (15s)」：兜底嗅探要真
            起一个无头浏览器等满 ``sniff_duration_sec`` 秒，不给预期用户会以为
            卡死。判据是 ``detect()`` 返回的适配器 ``priority < 0``（只有
            GenericAdapter 是负优先级）。
            """
            from ...core.registry import PlatformRegistry

            if not getattr(self._cfg, "sniff_enabled", True):
                return 0
            for url in urls:
                adapter = PlatformRegistry.detect(url)
                if adapter is not None and getattr(adapter, "priority", 0) < 0:
                    return int(getattr(self._cfg, "sniff_duration_sec", 15))
            return 0

        def _on_parse_clicked(self):
            urls = self._parse_urls()
            if not urls:
                self._toast(InfoBar.warning, "没有有效链接", "请至少粘贴一个 URL（每行一个）。")
                return
            self.parse_btn.setEnabled(False)
            sniff_sec = self._sniff_seconds_for(urls)
            self.parse_btn.setText(f"嗅探中… ({sniff_sec}s)" if sniff_sec else "解析中…")

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
                # 弹「下载选项」对话框：用户取消 = 整批不入队；用户确认 = 用
                # 弹窗里的覆盖项拼出 options。没启用提示时直接走默认配置。
                overrides = self._ask_prompt_overrides()
                if overrides is None:
                    return
                opts = self._options_for_overrides(overrides)
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

            # ``item`` is what the legacy actions operate on — fall back
            # to the deepest item we have so reparse / open / single still
            # work when the user right-clicks an inserted episode/page row.
            #
            # 这个赋值必须在任何读 ``item`` 的分支**之前**：它是本闭包的局部
            # 变量，编译期就被判定为 local，先读会直接 UnboundLocalError，
            # 不会回落到外层作用域。
            item = episode_item or top_item

            # 抖音：用户从合集 tab 复制的往往只是单条视频链接 —
            # 提供一个入口反查它所属的合集并整体展开。
            download_collection: Optional[object] = None
            if (
                item is not None
                and not item.is_container()
                and getattr(item.platform, "value", "") == "douyin"
            ):
                download_collection = menu.addAction("下载整个合集")

            menu.addSeparator()
            meta = menu.addAction("查看元数据")
            cover = menu.addAction("查看封面")

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
            if chosen is download_collection and item is not None:
                asyncio.create_task(
                    self._download_whole_collection(item),
                )
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
                    self._task_manager.add(item, self._options_for_overrides())
                    self._toast(InfoBar.success, "已加入下载队列", item.title or item.item_id)
            elif chosen is meta:
                self._show_metadata_dialog(item)
            elif chosen is cover:
                if item.cover_url:
                    QDesktopServices.openUrl(QUrl(item.cover_url))

        async def _download_whole_collection(self, item: MediaItem) -> None:
            """反查抖音视频所属合集，展开整个合集并刷新结果表格。"""
            from ...core.models import Platform
            from ...core.registry import PlatformRegistry
            adapter = PlatformRegistry.get(Platform.DOUYIN)
            if adapter is None or not hasattr(adapter, "collection_of"):
                self._toast(InfoBar.error, "获取合集失败",
                            "未找到抖音适配器，请重启软件。")
                return
            try:
                container = await adapter.collection_of(item.item_id)
            except Exception as exc:  # noqa: BLE001
                logger.exception("collection_of failed")
                self._toast(InfoBar.error, "获取合集失败",
                            f"{item.title or item.item_id}: {exc}")
                return
            if container is None:
                self._toast(InfoBar.info, "不属于合集",
                            f"{item.title or item.item_id} 不在任何合集中。")
                return
            try:
                children = await adapter.expand(container)
            except Exception as exc:  # noqa: BLE001
                logger.exception("expand collection failed")
                self._toast(InfoBar.error, "展开合集失败",
                            f"{container.title}: {exc}")
                return
            if not children:
                self._toast(InfoBar.warning, "合集为空",
                            f"{container.title}：未获取到任何视频。")
                return
            self._fill_result_table(children)
            self._toast(InfoBar.success, "合集已展开",
                        f"{container.title}（{len(children)} 个视频），"
                        f"请勾选后点击「下载选中」。")

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
            # 解析到内容后切换到「表格」视图
            self._result_stack.setCurrentWidget(self.result_table)
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
                # 弹「下载选项」对话框：用户取消 = 整批不入队；用户确认 = 用
                # 弹窗里的覆盖项拼出 options。没启用提示时直接走默认配置。
                overrides = self._ask_prompt_overrides()
                if overrides is None:
                    return
                opts = self._options_for_overrides(overrides)
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

        def _options_for_overrides(self, overrides: Optional[dict] = None) -> DownloadOptions:
            """所有「准备入队一条下载」的地方都走这个出口。

            ``_build_options`` 是唯一负责 ``AppConfig -> DownloadOptions``
            搬运的函数，弹窗里改的字段只能在这条流水线**之后**叠加，绝
            不能直接拼进 ``_build_options``（否则 ``test_build_options_covers_every_shared_config_field``
            会拒绝任何「只在弹窗里有意义」的字段）。``overrides`` 是来自
            弹窗的覆盖项，以 dataclasses.replace 形式叠加，None 表示无覆盖。
            """
            opts = self._build_options()
            if not overrides:
                return opts
            import dataclasses
            valid = {f.name for f in dataclasses.fields(DownloadOptions)}
            clean = {k: v for k, v in overrides.items() if k in valid}
            if not clean:
                return opts
            return dataclasses.replace(opts, **clean)

        def _build_options(self) -> DownloadOptions:
            return DownloadOptions(
                output_root=self._cfg.output_root,
                # Without this the GUI silently ignores a customised directory
                # layout: file_layout.resolve_item_dir() reads the template off
                # DownloadOptions, so an un-forwarded one falls back to the
                # dataclass default instead of the user's setting.
                output_dir_template=self._cfg.output_dir_template,
                filename_template=self._cfg.filename_template,
                container=self._cfg.container,
                max_quality=self._cfg.max_quality,
                write_thumbnail=self._cfg.write_thumbnail,
                write_metadata_json=self._cfg.write_metadata_json,
                # Sidecars and resume must be forwarded here too, or the GUI
                # would be the one surface that silently ignores them: the
                # engine reads them off DownloadOptions, not off AppConfig.
                write_nfo=self._cfg.write_nfo,
                write_danmaku=self._cfg.write_danmaku,
                write_subtitles=self._cfg.write_subtitles,
                resume=self._cfg.resume,
                duplicate_policy=self._cfg.duplicate_policy,
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
