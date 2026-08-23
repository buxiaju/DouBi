"""跨页面共享的小组件（页头 / 空态 / 统计条 / 分隔）。

把以前散落在各页面里重复造的轮子（卡片大标题 + 副标题、占位插画、统计
chip）抽到一个模块，让所有页面有同一种「讲法」。

设计要点：

* 全部 widget 都是「哑」的——不持有业务状态，纯展示。状态由调用方提供，
  ``setText`` / ``setCount`` 时自动重画。
* 颜色全部走 :mod:`doubi.ui.theme` 的 token，主题切换时通过订阅自动重
  刷样式——不需要每个 widget 自己挂 subscribe。
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("doubi.ui.widgets")


# ---------------------------------------------------------------------------
# PageHeader — 页面顶部的大标题区
# ---------------------------------------------------------------------------


def build_page_header(parent=None):
    """创建一个页头：主标题 + 副标题 + 右侧动作槽。

    返回的类有以下方法：

    * ``set_title(text)`` / ``set_subtitle(text)`` — 改文案
    * ``add_action(widget)`` — 右侧加一个按钮（推送用 addStretch 思路）
    * ``set_accent(bool)`` — 切换「品牌渐变」皮肤（默认关闭）

    不用 :class:`QStackedWidget` 切两套 header，直接控制 QSS 与子组件可见性。
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    )
    from qfluentwidgets import StrongBodyLabel

    from .theme import (
        FONT_FAMILY, SPACE_SM, SPACE_LG, TYPE_H1, TYPE_H2, TYPE_CAPTION,
        heading_qss, body_qss, muted_qss, current_theme, token, subscribe_theme,
    )

    class PageHeader(QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setObjectName("pageHeader")
            self._accent = False

            outer = QVBoxLayout(self)
            outer.setContentsMargins(0, 0, 0, 0)
            outer.setSpacing(SPACE_SM)

            # ---- title row: title + actions on the right ----
            self._row = QHBoxLayout()
            self._row.setContentsMargins(0, 0, 0, 0)
            self._row.setSpacing(SPACE_LG)

            # 标题 + 副标题用垂直布局
            text_col = QVBoxLayout()
            text_col.setContentsMargins(0, 0, 0, 0)
            text_col.setSpacing(2)

            self._title = StrongBodyLabel(self)
            self._subtitle = QLabel(self)
            self._subtitle.setStyleSheet(muted_qss())
            self._subtitle.setWordWrap(True)

            text_col.addWidget(self._title)
            text_col.addWidget(self._subtitle)
            self._row.addLayout(text_col, 1)

            self._actions_layout = QHBoxLayout()
            self._actions_layout.setContentsMargins(0, 0, 0, 0)
            self._actions_layout.setSpacing(SPACE_SM)
            self._row.addLayout(self._actions_layout, 0)

            outer.addLayout(self._row)
            self._refresh_styles()
            subscribe_theme(self, self._refresh_styles)

        def set_title(self, text: str) -> None:
            self._title.setText(text)
            self._apply_title_style()

        def set_subtitle(self, text: str) -> None:
            self._subtitle.setText(text)
            self._subtitle.setVisible(bool(text))

        def add_action(self, widget) -> None:
            """把右侧按钮 / 工具按钮追加到 action 槽。"""
            self._actions_layout.addWidget(widget)

        def add_stretch(self) -> None:
            self._actions_layout.addStretch(1)

        def set_accent(self, on: bool) -> None:
            """切换「Hero 品牌渐变」皮肤——用于启动后的欢迎页。"""
            self._accent = bool(on)
            self._refresh_styles()

        # ---- 主题刷新 ----

        def _apply_title_style(self) -> None:
            # 大标题固定走 22px / weight 600，颜色随主题
            self._title.setStyleSheet(heading_qss(1))

        def _refresh_styles(self) -> None:
            self._apply_title_style()
            self._subtitle.setStyleSheet(muted_qss())
            if self._accent:
                # 应用品牌渐变背景（深紫 → 更深紫），与「豆比」主题天然契合。
                from .theme import header_qss
                self.setStyleSheet(header_qss(1))
                # accent 模式下，标题用更亮的字
                self._title.setStyleSheet(
                    f"font-family: {FONT_FAMILY}; "
                    f"font-size: {TYPE_H1}px; "
                    f"font-weight: 600; "
                    f"color: {token('text_primary')}; "
                    f"background: transparent; border: none;"
                )
            else:
                self.setStyleSheet("background: transparent; border: none;")

    return PageHeader


# ---------------------------------------------------------------------------
# StatChip — 单条数字 + 标签
# ---------------------------------------------------------------------------


def build_stat_chip(parent=None):
    """一个「数字 + 小标签」的 chip，用于历史页 / 下载页顶部的统计条。

    配色与状态胶囊一致：背景用 status_xxx_bg，数字用 status_xxx_fg。
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel

    from .theme import (
        SPACE_SM, SPACE_MD, FONT_FAMILY, TYPE_H2, TYPE_CAPTION,
        token, current_theme, subscribe_theme, RADIUS_PILL,
    )

    class StatChip(QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setObjectName("statChip")
            self._kind = "muted"   # running/paused/completed/failed/muted

            self._layout = QHBoxLayout(self)
            self._layout.setContentsMargins(SPACE_MD, 6, SPACE_MD, 6)
            self._layout.setSpacing(SPACE_SM)

            self._value = QLabel("0", self)
            self._value.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)

            self._label = QLabel("", self)
            self._label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)

            self._layout.addWidget(self._value)
            self._layout.addWidget(self._label)
            self._layout.addStretch(1)

            self.set_kind("muted")
            subscribe_theme(self, self._refresh)

        def set_value(self, value) -> None:
            self._value.setText(str(value))

        def set_label(self, text: str) -> None:
            self._label.setText(text)

        def set_kind(self, kind: str) -> None:
            """切换配色：running/paused/completed/failed/cancelled/muted"""
            self._kind = kind
            self._refresh()

        def _refresh(self) -> None:
            kind = self._kind
            if kind == "muted":
                fg = token("text_muted")
                bg = "transparent"
                border = "rgba(128, 128, 128, 0.18)"
            else:
                fg = token(f"status_{kind}_fg", token("text_primary"))
                bg = token(f"status_{kind}_bg", token("bg_hover"))
                border = fg
            self._value.setStyleSheet(
                f"font-family: {FONT_FAMILY}; "
                f"font-size: {TYPE_H2}px; font-weight: 600; "
                f"color: {fg}; background: transparent; border: none;"
            )
            self._label.setStyleSheet(
                f"font-family: {FONT_FAMILY}; "
                f"font-size: {TYPE_CAPTION}px; "
                f"color: {fg}; background: transparent; border: none;"
            )
            self.setStyleSheet(
                f"QWidget#statChip {{"
                f"background: {bg}; "
                f"border: 1px solid {border}; "
                f"border-radius: {RADIUS_PILL}px;"
                f"}}"
            )

    return StatChip


# ---------------------------------------------------------------------------
# EmptyState — 空态插画 + 主文案 + 副文案
# ---------------------------------------------------------------------------


def build_empty_state(parent=None):
    """无图标 / 解析结果 / 历史记录时显示的占位卡片。

    只有文字与一条横向分隔线：图标在 QSS 里画会跨主题不一致，干脆让主题
    自身去承载视觉。这里只负责把「尚未 X」这件事说清楚。
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QLabel, QSizePolicy,
    )

    from .theme import (
        SPACE_LG, SPACE_MD, FONT_FAMILY, TYPE_BODY, TYPE_CAPTION,
        token, card_qss, current_theme, subscribe_theme,
    )

    class EmptyState(QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setObjectName("emptyState")
            self._title_text = ""
            self._subtitle_text = ""
            layout = QVBoxLayout(self)
            layout.setContentsMargins(SPACE_LG * 2, SPACE_LG * 3, SPACE_LG * 2, SPACE_LG * 3)
            # SPACE_LG = 16px — 给标题/副标题之间留出明确空气。
            # SPACE_MD (12px) 贴 12/14px 字号会让两行文字视觉重叠，
            # 是历史上这个组件看起来被"压扁"过的根因。
            layout.setSpacing(SPACE_LG)
            layout.setAlignment(Qt.AlignCenter)

            # 用普通 QLabel + setFont（而非 qfluentwidgets.StrongBodyLabel）：
            # StrongBodyLabel 内部走 qss 优先级链，widget 级 setStyleSheet
            # 改不掉它的 font-size，导致标题字号被默认的 18px+ 样式覆盖，
            # 把整张卡片撑爆，看起来"被压扁"。setFont 优先级最高，绝对生效。
            self._title = QLabel(self)
            self._title.setAlignment(Qt.AlignCenter)
            self._title.setWordWrap(True)
            # label 水平 Expanding：否则 QVBoxLayout 给它们 sizeHint.width()
            # （"刚好装下文字" 的最小宽度，如 244px），副标题 252px 文字被
            # 强制换行、最后一个字孤立到第二行居中。Expanding 让 label fill
            # 父容器（如 700px），一行就能装下整段副标题。
            self._title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            self._title_font = QFont(FONT_FAMILY)
            self._title_font.setPixelSize(TYPE_BODY + 1)
            self._title_font.setWeight(QFont.Medium)
            self._title.setFont(self._title_font)
            self._subtitle = QLabel(self)
            self._subtitle.setAlignment(Qt.AlignCenter)
            self._subtitle.setWordWrap(True)
            self._subtitle.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            self._subtitle_font = QFont(FONT_FAMILY)
            self._subtitle_font.setPixelSize(TYPE_CAPTION)
            self._subtitle.setFont(self._subtitle_font)

            layout.addWidget(self._title)
            layout.addWidget(self._subtitle)

            # 防止父布局（QScrollArea + addStretch）把整张卡片压成一条缝
            self.setMinimumHeight(168)

            self._refresh()
            subscribe_theme(self, self._refresh)

        def set_text(self, title: str, subtitle: str = "") -> None:
            self._title_text = title
            self._subtitle_text = subtitle
            self._title.setText(title)
            self._subtitle.setText(subtitle)
            self._subtitle.setVisible(bool(subtitle))

        def refresh_text(self) -> None:
            """主题切换时只重画样式，不动文案——但调用方要重读也可以走本方法。"""
            self._title.setText(self._title_text)
            self._subtitle.setText(self._subtitle_text)
            self._subtitle.setVisible(bool(self._subtitle_text))

        def _refresh(self) -> None:
            # 透明底：EmptyState 一般嵌在 CardWidget 里
            self.setStyleSheet("background: transparent; border: none;")
            # 字号/字重由 setFont 设定（优先级高于 stylesheet，绝对生效）。
            # 这里只设行高/颜色/padding/透明底——这些 setFont 改不掉的属性。
            # line-height 1.6 是空态呼吸感的关键，少了就被父布局压扁。
            self._title.setStyleSheet(
                f"color: {token('text_primary')}; "
                f"line-height: 1.6; "
                f"padding: 10px 8px; "
                f"background: transparent; border: none;"
            )
            self._subtitle.setStyleSheet(
                f"color: {token('text_muted')}; "
                f"line-height: 1.6; "
                f"padding: 6px 8px; "
                f"background: transparent; border: none;"
            )

    return EmptyState


# ---------------------------------------------------------------------------
# PlatformBadge — 平台徽章（解析结果表头 / 详情行）
# ---------------------------------------------------------------------------


def build_platform_badge(parent=None):
    """一个胶囊形状的平台徽章。

    不用 QSS 自绘：qfluentwidgets 的 Pivot 控件在长列表里太重，胶囊更轻
    更适合「单条结果的元信息」位。颜色用 accent_soft + accent，永远跟
    主题走。
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel

    from .theme import (
        FONT_FAMILY, RADIUS_PILL, SPACE_SM, SPACE_MD, TYPE_TINY,
        token, current_theme, subscribe_theme, _hex_to_rgba,
    )

    class PlatformBadge(QLabel):
        # 平台显示名 → 颜色 hint 映射
        _PLATFORM_COLORS = {
            "抖音": "#fe2c55",
            "douyin": "#fe2c55",
            "B 站": "#00aeec",
            "哔哩哔哩": "#00aeec",
            "bilibili": "#00aeec",
            "youtube": "#ff0000",
            "YouTube": "#ff0000",
            "tiktok": "#000000",
            "TikTok": "#000000",
            "小红书": "#ff2442",
            "微博": "#e6162d",
        }

        def __init__(self, text: str = "", parent=None):
            super().__init__(text or "", parent)
            self.setObjectName("platformBadge")
            self.setAlignment(Qt.AlignCenter)
            self._platform = text or ""
            self._refresh()
            subscribe_theme(self, self._refresh)

        def set_platform(self, name: str) -> None:
            self._platform = name
            self.setText(name)
            self._refresh()

        def _refresh(self) -> None:
            color = self._PLATFORM_COLORS.get(self._platform, token("progress_normal"))
            pack = current_theme()
            if pack.dark:
                # 暗色主题下用饱和度稍低的同色，避免辣眼睛
                text_color = color
                bg = _hex_to_rgba(color, 0.18)
            else:
                text_color = color
                bg = _hex_to_rgba(color, 0.10)
            self.setStyleSheet(
                f"QLabel#platformBadge {{"
                f"font-family: {FONT_FAMILY}; "
                f"font-size: {TYPE_TINY}px; font-weight: 600; "
                f"color: {text_color}; "
                f"background-color: {bg}; "
                f"border: 1px solid {_hex_to_rgba(color, 0.30)}; "
                f"border-radius: {RADIUS_PILL}px; "
                f"padding: 2px {SPACE_MD - 2}px;"
                f"}}"
            )

    return PlatformBadge


# ---------------------------------------------------------------------------
# SectionDivider — 区块之间的细分隔线
# ---------------------------------------------------------------------------


def build_section_divider(parent=None):
    """区块之间的一条细分隔线，颜色比 border 再淡一档。"""
    from PySide6.QtWidgets import QFrame

    class SectionDivider(QFrame):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setObjectName("sectionDivider")
            self.setFrameShape(QFrame.HLine)
            self.setFixedHeight(1)
            self.setStyleSheet(
                "QFrame#sectionDivider {"
                "background-color: rgba(128, 128, 128, 0.18);"
                "border: none;"
                "}"
            )

    return SectionDivider
