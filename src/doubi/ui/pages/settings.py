"""Settings page — runtime config knobs (M5.1) + 账号 (M5.3).

Adds proxy / concurrency / theme over the M5 skeleton, and a 账号
card that surfaces the current login state of B 站 and 抖音 with
one-click entry points to the QR / browser login dialogs and to
cookie file import.

Save writes ``~/.doubi/config.yml`` (the same file the CLI reads),
so GUI-set values carry over to CLI / REST / MCP runs.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger("doubi.ui.pages.settings")


# ---------------------------------------------------------------------------
# Module-level helper used by login dialogs to refresh the parent page
# ---------------------------------------------------------------------------


def _refresh_account_status_external(host) -> None:
    """Best-effort: find a :class:`SettingsPage` somewhere in the tree
    and ask it to refresh its account status block."""
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            return
        if host is None:
            return
        page = _find_settings_page(host)
        if page is not None and hasattr(page, "_refresh_account_status"):
            page._refresh_account_status()
    except Exception:   # noqa: BLE001
        logger.debug("refresh account status failed", exc_info=True)


def _find_settings_page(widget):
    """从 ``widget`` 出发找到设置页。

    不能按 objectName 找：``SettingsPage.__init__`` 设的是 ``settingsPage``，
    但 ``main_window`` 加进导航时会覆写成 ``settingsInterface``，
    按名字找会永远返回 None，登录完账号状态就静默不刷新。
    这里改成按能力识别（有 ``_refresh_account_status`` 就是它），
    先沿父链上溯——登录对话框的 host 通常是设置页的子控件。
    """
    from PySide6.QtWidgets import QWidget

    def _is_page(candidate) -> bool:
        return callable(getattr(candidate, "_refresh_account_status", None))

    node = widget
    while node is not None:
        if _is_page(node):
            return node
        node = node.parent()

    if isinstance(widget, QWidget):
        for child in widget.findChildren(QWidget):
            if _is_page(child):
                return child
    return None


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------


def build_settings_widgets():
    from PySide6.QtCore import Qt, QTimer, Signal as pyqtSignal
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QFileDialog, QLabel,
        QScrollArea, QSizePolicy,
    )
    from qfluentwidgets import (
        LineEdit, ComboBox, SwitchButton, PushButton, StrongBodyLabel,
        InfoBar, InfoBarPosition, CardWidget,
    )

    from ...core.config import DEFAULT_CONFIG_PATH, load_config
    from ..theme import (
        FONT_FAMILY, SPACE_LG, SPACE_MD, SPACE_SM, SPACE_XL, SPACE_XS,
        TYPE_CAPTION, RADIUS_CARD,
        current_theme_name, heading_qss, muted_qss, resolve_theme, set_theme,
        subscribe_theme, theme_labels, theme_names, token, body_qss, card_qss,
    )
    from ..widgets import build_page_header, build_section_divider
    from ...ui.auth_actions import (
        LoginStatus,
        bilibili_status,
        douyin_status,
        import_bilibili_cookies,
        import_douyin_cookies,
        import_douyin_legacy_json,
    )

    class SettingsPage(QWidget):
        # 保存后通知主窗口把 prompt_before_download 推到 parse_page，
        # 这样不重启也能生效。仅这一个字段需要即时下发——其他字段的
        # 变更要么重启生效（database_path / theme），要么下一次下载
        # 入队时自然重新读（container / max_quality 等）。
        promptBeforeDownloadChanged = pyqtSignal(bool)
        # 保存后通知主窗口把嗅探配置推到 parse_page（解析按钮的
        # 「嗅探中… (Ns)」文案要用到 N），载荷是 ``(enabled, duration_sec)``。
        sniffConfigChanged = pyqtSignal(bool, int)

        def __init__(self, parent: Optional[QWidget] = None):
            super().__init__(parent)
            self.setObjectName("settingsPage")
            self._cfg = load_config(None)
            self._bili_status: Optional[LoginStatus] = None
            self._douyin_status: Optional[LoginStatus] = None
            # 反向同步时用来抑制信号回环：主题下拉被程序改动时
            # 不应该再触发一次 set_theme。
            self._syncing_theme = False
            self._build_ui()
            self._load_from_cfg()
            self.theme.currentIndexChanged.connect(self._on_theme_combo_changed)
            # SwitchButton 没有「用户主动切换」与「程序改值」的区分——直接
            # 连它自身的 checkedChanged 信号就够了，程序改值时不会跑
            # 回调（加载在构造时就完成，那时还没 connect）。
            self.prompt_before_download.checkedChanged.connect(
                self.promptBeforeDownloadChanged.emit
            )
            # 别处（导航栏主题按钮、CLI）切换主题时，下拉框跟着走。
            subscribe_theme(self, self._sync_theme_combo)
            # Populate the account block asynchronously
            # 包一层 try：测试/截屏脚本等没有运行中的 asyncio loop 时，
            # ``asyncio.ensure_future`` 会抛 RuntimeError——这种情况
            # 直接同步调一次即可，账号状态晚一点刷新不影响 UI 启动。
            def _kick_status_refresh() -> None:
                try:
                    asyncio.ensure_future(self._refresh_account_status_async())
                except RuntimeError:
                    import logging
                    logging.getLogger("doubi.ui.pages.settings").debug(
                        "no event loop, falling back to sync account refresh",
                    )
                    try:
                        # 同步跑一次：阻塞到完成
                        asyncio.run(self._refresh_account_status_async())
                    except Exception:   # noqa: BLE001
                        pass
            QTimer.singleShot(50, _kick_status_refresh)

        # ---------------------------------------------------------- UI

        def _build_ui(self):
            PageHeader = build_page_header()
            SectionDivider = build_section_divider()

            outer = QVBoxLayout(self)
            outer.setContentsMargins(SPACE_XL, SPACE_LG, SPACE_XL, SPACE_LG)
            outer.setSpacing(SPACE_LG)

            # ---- 页头 ----
            self._header = PageHeader(self)
            self._header.set_title("设置")
            self._header.set_subtitle(
                "账号 / 主题 / 性能 / 路径。所有改动点「保存设置」后才会写入配置文件。"
            )
            self.save_btn = PushButton("保存设置", self)
            self.save_btn.setFixedWidth(120)
            self.save_btn.clicked.connect(self._on_save)
            self._header.add_action(self.save_btn)
            outer.addWidget(self._header)

            # ---- 滚动区（容纳下面的多张卡） ----
            self._body_scroll = QScrollArea(self)
            self._body_scroll.setWidgetResizable(True)
            self._body_scroll.setFrameShape(QScrollArea.NoFrame)
            self._body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self._body_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self._body_scroll.setStyleSheet(
                "QScrollArea { background: transparent; border: none; }"
            )
            self._body_scroll.viewport().setStyleSheet(
                "background: transparent;"
            )

            body = QWidget(self._body_scroll)
            body.setStyleSheet("background: transparent;")
            body.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
            body_layout = QVBoxLayout(body)
            body_layout.setContentsMargins(0, 0, 0, 0)
            body_layout.setSpacing(SPACE_LG)

            # ---- 账号卡 ----
            self.account_card = self._build_account_card()
            body_layout.addWidget(self.account_card)

            # ---- 下载设置卡（输出 / 性能 / 画质） ----
            self._download_card = self._build_card(
                "下载设置",
                "输出位置、画质、并发等运行时配置",
            )
            download_form = QFormLayout(self._download_card["body"])
            download_form.setVerticalSpacing(SPACE_MD)
            download_form.setHorizontalSpacing(SPACE_LG)
            download_form.setContentsMargins(0, 0, 0, 0)

            self.output_root = LineEdit(self._download_card["body"])
            self.output_root.setPlaceholderText("./Downloaded")
            self.filename_template = LineEdit(self._download_card["body"])
            self.filename_template.setPlaceholderText("{title}_{item_id}")
            self.container = ComboBox(self._download_card["body"])
            self.container.addItems(["mp4", "mkv"])
            self.max_quality = ComboBox(self._download_card["body"])
            self.max_quality.addItems(["best", "8k", "4k", "1080p", "720p", "480p"])

            download_form.addRow("保存根目录", self.output_root)
            download_form.addRow("文件名模板", self.filename_template)
            download_form.addRow("容器格式", self.container)
            download_form.addRow("最高画质", self.max_quality)
            body_layout.addWidget(self._download_card["widget"])

            # ---- 性能 / 网络卡 ----
            self._network_card = self._build_card(
                "性能与网络",
                "代理、并发、限速、数据库等可选项",
            )
            net_form = QFormLayout(self._network_card["body"])
            net_form.setVerticalSpacing(SPACE_MD)
            net_form.setHorizontalSpacing(SPACE_LG)
            net_form.setContentsMargins(0, 0, 0, 0)

            self.proxy = LineEdit(self._network_card["body"])
            self.proxy.setPlaceholderText("http://127.0.0.1:7890（留空不使用）")
            self.concurrent = LineEdit(self._network_card["body"])
            self.concurrent.setPlaceholderText("3")
            self.rate_limit = LineEdit(self._network_card["body"])
            self.rate_limit.setPlaceholderText("如 5M（留空不限速）")
            self.database = SwitchButton(self._network_card["body"])

            net_form.addRow("代理", self.proxy)
            net_form.addRow("并发下载数", self.concurrent)
            net_form.addRow("限速", self.rate_limit)
            net_form.addRow("启用数据库", self.database)
            body_layout.addWidget(self._network_card["widget"])

            # ---- 通用嗅探 ----
            # 只有「未知站点」才会走这条路：registry 里 GenericAdapter 的
            # priority=-1，抖音 / B 站等具体平台永远先匹配，这些开关对它们无效。
            self._sniff_card = self._build_card(
                "通用嗅探",
                "未识别的网站会用无头浏览器嗅探视频地址；已支持的平台不受影响",
            )
            sniff_form = QFormLayout(self._sniff_card["body"])
            sniff_form.setVerticalSpacing(SPACE_MD)
            sniff_form.setHorizontalSpacing(SPACE_LG)
            sniff_form.setContentsMargins(0, 0, 0, 0)

            self.sniff_enabled = SwitchButton(self._sniff_card["body"])
            self.sniff_duration = LineEdit(self._sniff_card["body"])
            self.sniff_duration.setPlaceholderText("15（秒，建议 5–60）")
            self.sniff_headless = SwitchButton(self._sniff_card["body"])
            self.sniff_auto_play = SwitchButton(self._sniff_card["body"])
            self.sniff_user_agent = LineEdit(self._sniff_card["body"])
            self.sniff_user_agent.setPlaceholderText("留空用浏览器默认 UA")

            sniff_form.addRow("启用通用嗅探", self.sniff_enabled)
            sniff_form.addRow("嗅探时长（秒）", self.sniff_duration)
            sniff_form.addRow("无头模式", self.sniff_headless)
            sniff_form.addRow("自动播放触发", self.sniff_auto_play)
            sniff_form.addRow("User-Agent", self.sniff_user_agent)
            body_layout.addWidget(self._sniff_card["widget"])

            # ---- 主题与外观 ----
            self._appearance_card = self._build_card(
                "主题与外观",
                "切换主题包会立即生效；点「保存设置」才会写入配置文件",
            )
            appearance_form = QFormLayout(self._appearance_card["body"])
            appearance_form.setVerticalSpacing(SPACE_MD)
            appearance_form.setHorizontalSpacing(SPACE_LG)
            appearance_form.setContentsMargins(0, 0, 0, 0)

            self.theme = ComboBox(self._appearance_card["body"])
            self.theme.addItems(theme_labels())
            appearance_form.addRow("主题", self.theme)

            # 语言：切换后需重启生效（已渲染的控件不会自动重译），
            # 所以这里只写配置、不实时切——和 theme 的「实时预览」不同档。
            from ..i18n import (
                available_languages, current_language, language_labels, tr,
            )
            self.language = ComboBox(self._appearance_card["body"])
            self.language.addItems(language_labels())
            # 把当前生效语言反映到下拉框（不触发 set_language）。
            langs = available_languages()
            try:
                self.language.setCurrentIndex(langs.index(current_language()))
            except ValueError:
                pass
            appearance_form.addRow(tr("language.label"), self.language)

            # GUI 行为偏好：是否在解析页点下载时先弹选项对话框。
            # 默认 False——「点一下就走」是绝大多数用户的心智模型。
            self.prompt_before_download = SwitchButton(self._appearance_card["body"])
            appearance_form.addRow("下载前询问选项", self.prompt_before_download)
            body_layout.addWidget(self._appearance_card["widget"])

            # ---- Cookie 与存储 ----
            self._cookie_card = self._build_card(
                "Cookie 与存储",
                "登录状态会写入 ~/.doubi/cookies/ 目录",
            )
            cookie_form = QFormLayout(self._cookie_card["body"])
            cookie_form.setVerticalSpacing(SPACE_MD)
            cookie_form.setHorizontalSpacing(SPACE_LG)
            cookie_form.setContentsMargins(0, 0, 0, 0)

            self.cookies_dir_label = LineEdit(self._cookie_card["body"])
            self.cookies_dir_label.setReadOnly(True)
            self.open_cookies_btn = PushButton("打开目录", self._cookie_card["body"])
            self.open_cookies_btn.setFixedWidth(96)
            self.open_cookies_btn.clicked.connect(self._on_open_cookies_dir)
            cookies_row = QHBoxLayout()
            cookies_row.setContentsMargins(0, 0, 0, 0)
            cookies_row.setSpacing(SPACE_SM)
            cookies_row.addWidget(self.cookies_dir_label, 1)
            cookies_row.addWidget(self.open_cookies_btn)
            cookies_holder = QWidget()
            cookies_holder.setStyleSheet("background: transparent;")
            cookies_holder.setLayout(cookies_row)
            cookie_form.addRow("Cookie 目录", cookies_holder)
            body_layout.addWidget(self._cookie_card["widget"])

            body_layout.addStretch(1)

            self._body_scroll.setWidget(body)
            outer.addWidget(self._body_scroll, 1)

        def _build_card(self, title: str, subtitle: str) -> dict:
            """构造一张带「标题 / 副标题 / body 容器」的可复用卡片。

            返回值是 ``{"widget": QWidget, "body": QWidget}``——body 是
            放表单行的容器，widget 是外层整个 Card。
            """
            SectionDivider = build_section_divider()
            from qfluentwidgets import CardWidget, StrongBodyLabel

            card = CardWidget(self)
            card.setObjectName("settingsCard")
            layout = QVBoxLayout(card)
            layout.setContentsMargins(SPACE_LG, SPACE_MD, SPACE_LG, SPACE_LG)
            layout.setSpacing(SPACE_SM)

            # 标题 + 副标题
            header = QVBoxLayout()
            header.setContentsMargins(0, 0, 0, 0)
            header.setSpacing(2)
            title_label = StrongBodyLabel(card)
            title_label.setText(title)
            title_label.setStyleSheet(heading_qss(3))
            sub_label = QLabel(subtitle, card)
            sub_label.setStyleSheet(muted_qss())
            sub_label.setWordWrap(True)
            header.addWidget(title_label)
            header.addWidget(sub_label)
            layout.addLayout(header)

            # 分隔线
            divider = SectionDivider(card)
            layout.addWidget(divider)

            # body 容器
            body = QWidget(card)
            body.setStyleSheet("background: transparent;")
            layout.addWidget(body)

            return {"widget": card, "body": body, "title": title_label, "subtitle": sub_label}

        def _build_account_card(self) -> CardWidget:
            card = CardWidget(self)
            card.setObjectName("settingsCard")
            layout = QVBoxLayout(card)
            layout.setContentsMargins(SPACE_LG, SPACE_MD, SPACE_LG, SPACE_LG)
            layout.setSpacing(SPACE_MD)

            # 标题 + 副标题
            from qfluentwidgets import StrongBodyLabel
            header = QHBoxLayout()
            header.setContentsMargins(0, 0, 0, 0)
            text_col = QVBoxLayout()
            text_col.setContentsMargins(0, 0, 0, 0)
            text_col.setSpacing(2)
            header_title = StrongBodyLabel(card)
            header_title.setText("账号与登录")
            header_title.setStyleSheet(heading_qss(3))
            text_col.addWidget(header_title)
            sub = QLabel("管理 B 站 / 抖音的登录态", card)
            sub.setStyleSheet(muted_qss())
            text_col.addWidget(sub)
            header.addLayout(text_col, 1)
            self.refresh_status_btn = PushButton("刷新状态", card)
            self.refresh_status_btn.clicked.connect(
                lambda: asyncio.ensure_future(self._refresh_account_status_async())
            )
            header.addWidget(self.refresh_status_btn)
            layout.addLayout(header)

            # 分隔线
            SectionDivider = build_section_divider()
            layout.addWidget(SectionDivider(card))

            # ---- B 站 row -----------------------------------------
            bili_row = QHBoxLayout()
            bili_row.setSpacing(SPACE_SM)
            self.bili_status_label = StrongBodyLabel(card)
            self.bili_status_label.setText("B 站：正在检测…")
            bili_row.addWidget(self.bili_status_label, 1)
            self.bili_qr_btn = PushButton("扫码登录", card)
            self.bili_qr_btn.clicked.connect(self._on_bilibili_qr_login)
            self.bili_import_btn = PushButton("导入 Cookie 文件", card)
            self.bili_import_btn.clicked.connect(self._on_bilibili_import)
            bili_row.addWidget(self.bili_qr_btn)
            bili_row.addWidget(self.bili_import_btn)
            layout.addLayout(bili_row)

            bili_detail = QLabel(
                "扫码登录用 B 站 App 扫描二维码；导入 Cookie 用浏览器扩展 "
                "“Get cookies.txt LOCALLY” 导出后再选文件。",
                card,
            )
            bili_detail.setStyleSheet(muted_qss())
            bili_detail.setWordWrap(True)
            self._bili_detail = bili_detail
            layout.addWidget(bili_detail)

            # ---- 抖音 row -----------------------------------------
            dy_row = QHBoxLayout()
            dy_row.setSpacing(SPACE_SM)
            self.dy_status_label = StrongBodyLabel(card)
            self.dy_status_label.setText("抖音：正在检测…")
            dy_row.addWidget(self.dy_status_label, 1)
            self.dy_qr_btn = PushButton("扫码登录", card)
            self.dy_qr_btn.clicked.connect(self._on_douyin_browser_login)
            self.dy_import_btn = PushButton("导入 Cookie 文件", card)
            self.dy_import_btn.clicked.connect(self._on_douyin_import)
            self.dy_legacy_btn = PushButton("导入 douyin-downloader JSON", card)
            self.dy_legacy_btn.clicked.connect(self._on_douyin_legacy_import)
            dy_row.addWidget(self.dy_qr_btn)
            dy_row.addWidget(self.dy_import_btn)
            dy_row.addWidget(self.dy_legacy_btn)
            layout.addLayout(dy_row)

            dy_detail = QLabel(
                "扫码登录会打开 Chromium 窗口，请在窗口里完成登录；"
                "Cookie 抓取完成后会自动写入。",
                card,
            )
            dy_detail.setStyleSheet(muted_qss())
            dy_detail.setWordWrap(True)
            self._dy_detail = dy_detail
            layout.addWidget(dy_detail)

            return card

        def _load_from_cfg(self):
            self.output_root.setText(str(self._cfg.output_root))
            self.filename_template.setText(self._cfg.filename_template)
            self._set_combo(self.container, self._cfg.container)
            self._set_combo(self.max_quality, self._cfg.max_quality)
            self.proxy.setText(self._cfg.proxy or "")
            self.concurrent.setText(str(self._cfg.concurrent_jobs))
            self.rate_limit.setText(self._cfg.rate_limit or "")
            self.database.setChecked(self._cfg.database)
            self.prompt_before_download.setChecked(self._cfg.prompt_before_download)
            self.sniff_enabled.setChecked(self._cfg.sniff_enabled)
            self.sniff_duration.setText(str(self._cfg.sniff_duration_sec))
            self.sniff_headless.setChecked(self._cfg.sniff_headless)
            self.sniff_auto_play.setChecked(self._cfg.sniff_auto_play)
            self.sniff_user_agent.setText(self._cfg.sniff_user_agent or "")
            self._sync_theme_combo()
            self.cookies_dir_label.setText(
                str(Path.home() / ".doubi" / "cookies")
            )

        # ---------------------------------------------------- 主题

        def _sync_theme_combo(self) -> None:
            """把当前生效的主题反映到下拉框（不触发 set_theme）。"""
            name = resolve_theme(current_theme_name())
            names = theme_names()
            if name not in names:
                return
            idx = names.index(name)
            if self.theme.currentIndex() == idx:
                return
            self._syncing_theme = True
            try:
                self.theme.setCurrentIndex(idx)
            finally:
                self._syncing_theme = False
            # 同步刷新账号卡片的次级说明色，主题包里 text_muted 变了它也得变。
            self._refresh_muted_labels()

        def _refresh_muted_labels(self) -> None:
            for label in (getattr(self, "_bili_detail", None),
                          getattr(self, "_dy_detail", None)):
                if label is not None:
                    label.setStyleSheet(muted_qss())

        def _on_theme_combo_changed(self, _index: int) -> None:
            """选中即预览：立即生效，但只有点「保存设置」才写入配置。"""
            if self._syncing_theme:
                return
            set_theme(self._selected_theme_name())

        def _selected_theme_name(self) -> str:
            """把主题下拉的当前显示名转回稳定 key。"""
            idx = self.theme.currentIndex()
            names = theme_names()
            if 0 <= idx < len(names):
                return names[idx]
            return resolve_theme(self.theme.currentText())

        @staticmethod
        def _set_combo(combo: ComboBox, value: str) -> None:
            idx = combo.findText(value)
            if idx >= 0:
                combo.setCurrentIndex(idx)

        # ---------------------------------------------------- 账号

        async def _refresh_account_status_async(self) -> None:
            try:
                self._bili_status = await bilibili_status()
                self._douyin_status = await douyin_status()
            except Exception as exc:   # noqa: BLE001
                logger.warning("账号状态检测失败: %s", exc)
            self._refresh_account_status()

        def _refresh_account_status(self) -> None:
            if self._bili_status is not None:
                self.bili_status_label.setText(
                    f"B 站：{self._bili_status.short_label()}"
                )
            else:
                self.bili_status_label.setText("B 站：未知（点击右上角刷新）")
            if self._douyin_status is not None:
                self.dy_status_label.setText(
                    f"抖音：{self._douyin_status.short_label()}"
                )
            else:
                self.dy_status_label.setText("抖音：未知（点击右上角刷新）")

        def _on_bilibili_qr_login(self) -> None:
            from ...ui.dialogs.login_dialog import build_bilibili_qr_dialog
            cls = build_bilibili_qr_dialog()
            dlg = cls(self.window())
            dlg.exec()
            asyncio.ensure_future(self._refresh_account_status_async())

        def _on_bilibili_import(self) -> None:
            src, _ = QFileDialog.getOpenFileName(
                self, "选择 B 站 Cookie 文件",
                str(Path.home() / ".doubi" / "cookies"),
                "Cookie 文件 (*.txt *.json);;全部 (*)",
            )
            if not src:
                return
            try:
                ok, msg = import_bilibili_cookies(Path(src))
            except Exception as exc:   # noqa: BLE001
                self._toast(False, "导入失败", str(exc))
                return
            self._toast(ok, "B 站 Cookie" if ok else "B 站 Cookie 失败", msg)
            asyncio.ensure_future(self._refresh_account_status_async())

        def _on_douyin_browser_login(self) -> None:
            from ...ui.dialogs.login_dialog import build_douyin_browser_dialog
            cls = build_douyin_browser_dialog()
            dlg = cls(self.window())
            dlg.exec()
            asyncio.ensure_future(self._refresh_account_status_async())

        def _on_douyin_import(self) -> None:
            src, _ = QFileDialog.getOpenFileName(
                self, "选择抖音 Cookie 文件",
                str(Path.home() / ".doubi" / "cookies"),
                "Cookie 文件 (*.txt *.json);;全部 (*)",
            )
            if not src:
                return
            try:
                ok, msg = import_douyin_cookies(Path(src))
            except Exception as exc:   # noqa: BLE001
                self._toast(False, "导入失败", str(exc))
                return
            self._toast(ok, "抖音 Cookie" if ok else "抖音 Cookie 失败", msg)
            asyncio.ensure_future(self._refresh_account_status_async())

        def _on_douyin_legacy_import(self) -> None:
            src, _ = QFileDialog.getOpenFileName(
                self, "选择 douyin-downloader cookies.json",
                str(Path.home()),
                "JSON 文件 (*.json);;全部 (*)",
            )
            if not src:
                return
            try:
                ok, msg = import_douyin_legacy_json(Path(src))
            except Exception as exc:   # noqa: BLE001
                self._toast(False, "导入失败", str(exc))
                return
            self._toast(ok, "抖音 legacy" if ok else "抖音 legacy 失败", msg)
            asyncio.ensure_future(self._refresh_account_status_async())

        def _toast(self, ok: bool, title: str, msg: str) -> None:
            kind = InfoBar.success if ok else InfoBar.error
            kind(
                title=title, content=msg, parent=self,
                position=InfoBarPosition.TOP, duration=4000,
            )

        # ----------------------------------------------------- save

        def _on_save(self) -> None:
            try:
                import yaml
            except ImportError:
                InfoBar.error(
                    title="无法保存",
                    content="缺少 pyyaml 依赖。",
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=3000,
                )
                return

            # 必须用 to_dict() 而不是 asdict()：后者保留 Path 对象，
            # yaml.safe_dump 无法表示，会 RepresenterError。
            data = self._cfg.to_dict()
            data["output_root"] = self.output_root.text().strip() or "./Downloaded"
            data["filename_template"] = self.filename_template.text() or "{title}_{item_id}"
            data["container"] = self.container.currentText()
            data["max_quality"] = self.max_quality.currentText()
            data["proxy"] = self.proxy.text().strip() or None
            try:
                data["concurrent_jobs"] = max(1, int(self.concurrent.text() or 3))
            except ValueError:
                data["concurrent_jobs"] = 3
            data["rate_limit"] = self.rate_limit.text().strip() or None
            data["database"] = self.database.isChecked()
            data["prompt_before_download"] = self.prompt_before_download.isChecked()

            # 通用嗅探。时长夹到 5–60：低于 5 秒基本抓不到 m3u8（页面还没起播），
            # 高于 60 秒用户会以为程序卡死。非法输入回落到默认 15。
            data["sniff_enabled"] = self.sniff_enabled.isChecked()
            try:
                data["sniff_duration_sec"] = min(60, max(5, int(self.sniff_duration.text() or 15)))
            except ValueError:
                data["sniff_duration_sec"] = 15
            data["sniff_headless"] = self.sniff_headless.isChecked()
            data["sniff_auto_play"] = self.sniff_auto_play.isChecked()
            data["sniff_user_agent"] = self.sniff_user_agent.text().strip()

            theme_name = self._selected_theme_name()
            data["theme"] = theme_name
            set_theme(theme_name)

            # 语言：写入配置即可，下次启动时 app.py 读 config 调 set_language。
            # 这里不实时切语言——已渲染的控件不会重译，切了反而半中半英。
            from ..i18n import available_languages, language_labels
            lang_labels = language_labels()
            lang_idx = self.language.currentIndex()
            if 0 <= lang_idx < len(lang_labels):
                langs = available_languages()
                data["language"] = langs[lang_idx]

            cfg_path = DEFAULT_CONFIG_PATH
            try:
                # 先 dump 到内存再落盘：open(..., "w") 会立即截断文件，
                # 若 dump 在写入过程中失败，用户的旧配置就被清空了。
                text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
                cfg_path.parent.mkdir(parents=True, exist_ok=True)
                cfg_path.write_text(text, encoding="utf-8")
            except Exception as exc:   # noqa: BLE001
                logger.exception("settings save failed")
                InfoBar.error(
                    title="保存失败",
                    content=f"{exc}",
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=5000,
                )
                return

            # 嗅探配置要立即在本进程生效，否则用户改完时长还得重启才看得到
            # 变化。``self._cfg`` 是内存里那份，同步它 + 重新注入兜底适配器，
            # 就等于走了一遍启动时的 ``GenericAdapter.set_config``。
            self._cfg.sniff_enabled = data["sniff_enabled"]
            self._cfg.sniff_duration_sec = data["sniff_duration_sec"]
            self._cfg.sniff_headless = data["sniff_headless"]
            self._cfg.sniff_auto_play = data["sniff_auto_play"]
            self._cfg.sniff_user_agent = data["sniff_user_agent"]
            try:
                from ...platforms.generic import GenericAdapter
                GenericAdapter.set_config(self._cfg)
            except Exception:  # noqa: BLE001 - 注入失败不该阻断保存
                logger.exception("failed to push sniff config to GenericAdapter")
            self.sniffConfigChanged.emit(
                self._cfg.sniff_enabled, self._cfg.sniff_duration_sec
            )

            InfoBar.success(
                title="设置已保存",
                content=f"已写入 {cfg_path}。大部分设置下次下载时即生效；"
                        f"如遇异常请重启应用。",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=4000,
            )
            logger.info("settings saved to %s", cfg_path)

        def _on_open_cookies_dir(self) -> None:
            cookies_dir = Path(self.cookies_dir_label.text())
            cookies_dir.mkdir(parents=True, exist_ok=True)
            try:
                if sys.platform.startswith("win"):
                    os.startfile(str(cookies_dir))   # type: ignore[attr-defined]
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", str(cookies_dir)])
                else:
                    subprocess.Popen(["xdg-open", str(cookies_dir)])
            except Exception as exc:   # noqa: BLE001
                logger.warning("open cookies dir failed: %s", exc)
                InfoBar.error(
                    title="打开失败",
                    content=f"请手动前往 {cookies_dir}。",
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=3000,
                )

    return SettingsPage, SettingsPage
