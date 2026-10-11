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
    from PySide6.QtWidgets import (
        QHBoxLayout,
        QLabel,
        QVBoxLayout,
        QWidget,
    )
    from qfluentwidgets import StrongBodyLabel

    from .theme import (
        SPACE_LG,
        SPACE_SM,
        TYPE_H1,
        heading_qss,
        muted_qss,
        subscribe_theme,
        token,
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
    from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

    from .theme import (
        RADIUS_PILL,
        SPACE_MD,
        SPACE_SM,
        TYPE_CAPTION,
        TYPE_H2,
        subscribe_theme,
        token,
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
                f"font-size: {TYPE_H2}px; font-weight: 600; "
                f"color: {fg}; background: transparent; border: none;"
            )
            self._label.setStyleSheet(
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
        QHBoxLayout,
        QLabel,
        QSizePolicy,
        QVBoxLayout,
        QWidget,
    )
    from qfluentwidgets import PushButton

    from .theme import (
        FONT_FAMILY_PRIMARY,
        SPACE_LG,
        SPACE_MD,
        TYPE_BODY,
        TYPE_CAPTION,
        subscribe_theme,
        token,
    )

    class EmptyState(QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setObjectName("emptyState")
            self._title_text = ""
            self._subtitle_text = ""
            self._action_cb = None
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
            self._title_font = QFont(FONT_FAMILY_PRIMARY)
            self._title_font.setPixelSize(TYPE_BODY + 1)
            self._title_font.setWeight(QFont.Medium)
            self._title.setFont(self._title_font)
            self._subtitle = QLabel(self)
            self._subtitle.setAlignment(Qt.AlignCenter)
            self._subtitle.setWordWrap(True)
            self._subtitle.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            self._subtitle_font = QFont(FONT_FAMILY_PRIMARY)
            self._subtitle_font.setPixelSize(TYPE_CAPTION)
            self._subtitle.setFont(self._subtitle_font)

            # 0.3.7：可选 CTA 按钮（解析页用「试试示例链接」/ 其他页可复用）。
            # 默认隐藏，set_action() 启用。
            self._action = PushButton("", self)
            self._action.setVisible(False)
            self._action.clicked.connect(self._on_action_clicked)
            self._action_row = QHBoxLayout()
            self._action_row.setContentsMargins(0, 0, 0, 0)
            self._action_row.setSpacing(SPACE_MD)
            self._action_row.addStretch(1)
            self._action_row.addWidget(self._action)
            self._action_row.addStretch(1)

            layout.addWidget(self._title)
            layout.addWidget(self._subtitle)
            layout.addLayout(self._action_row)

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

        def set_action(self, label: str, callback) -> None:
            """Add an optional CTA button below the subtitle.

            Pass ``label=""`` (default) to hide. Used by parse page's
            "try a sample link" shortcut, and reusable by any page that
            wants a discoverable next action on its empty state.
            """
            if not label or callback is None:
                self._action.setVisible(False)
                self._action_cb = None
                return
            self._action.setText(label)
            self._action.setVisible(True)
            self._action_cb = callback

        def _on_action_clicked(self) -> None:
            cb = self._action_cb
            if cb is not None:
                cb()

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
        RADIUS_PILL,
        SPACE_MD,
        TYPE_TINY,
        _hex_to_rgba,
        current_theme,
        subscribe_theme,
        token,
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


# ---------------------------------------------------------------------------
# LoadingState — 数据加载中的占位（0.3.7 新增）
# ---------------------------------------------------------------------------
#
# 与 EmptyState 共享同一套布局约定（QVBoxLayout 居中、字号层级、上下
# 留白），但中间多一个 ProgressRing 在转。文案通常带「正在…」/「…稍候」。
#
# 用法：和 EmptyState 一样塞进 QStackedWidget——0.3.7 把 6 个页面的
# 「正在拉数据」过渡态都改成这个：
#
#     self._stack.addWidget(self._loading)
#     self._stack.addWidget(self._empty_state)
#     self._stack.addWidget(self.table)
#     # _on_refresh()
#     self._loading.set_message("正在搜索…")
#     self._stack.setCurrentWidget(self._loading)
#     …
#     self._stack.setCurrentWidget(self.table)   # 或 self._empty_state
#
# 内存 + CPU 占用
# --------------
# ProgressRing 构造出来就一直在转（qfluentwidgets 没暴露 ``start()``），
# 所以一旦不再可见要调 ``stop()``，否则隐藏在 stack 里的 spinner 还在
# 走 60 FPS 定时器，白白烧 CPU。Stack 切换是本组件唯一的退出路径，
# 调用方在 ``setCurrentWidget(非 self)`` 之后调一次 ``stop()`` 即可。
#
# 颜色
# ----
# ``ProgressRing`` 默认色跟 qfluentwidgets 主题走（亮 / 暗两套），**不要**
# 主动 ``setCustomBarColor`` —— 否则切主题时不变，会锁死在第一版调色上。
# 文字颜色用 ``text_primary``，主题切换通过 ``subscribe_theme`` 自动重刷。


def build_loading_state(parent=None):
    """``QStackedWidget`` 里使用的 loading 占位卡片。

    返回的 component 接口：
    set_message(text)  改文案
    start() / stop()  起停 spinner（不显示时停掉省 CPU）
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont as _QFont
    from PySide6.QtWidgets import (
        QLabel,
        QSizePolicy,
        QVBoxLayout,
        QWidget,
    )
    from qfluentwidgets import ProgressRing

    from .theme import (
        FONT_FAMILY_PRIMARY,
        SPACE_LG,
        TYPE_BODY,
        subscribe_theme,
        token,
    )

    class LoadingState(QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setObjectName("loadingState")
            self._message_text = ""

            layout = QVBoxLayout(self)
            layout.setContentsMargins(
                SPACE_LG * 2, SPACE_LG * 3, SPACE_LG * 2, SPACE_LG * 3,
            )
            layout.setSpacing(SPACE_LG)
            layout.setAlignment(Qt.AlignCenter)

            # ProgressRing 默认色跟随 qfluentthemes 主题走；不要
            # setCustomBarColor，否则切主题时不会跟随主题重画。
            self._ring = ProgressRing(self)
            self._ring.setFixedSize(40, 40)
            self._ring.setStrokeWidth(4)
            self._ring.setTextVisible(False)
            # qfluentwidgets 的 ProgressRing 没有 ``start()`` —— 构造出来就转。
            # 但 ``pause`` / ``resume`` 都有，所以这两个方法名对应
            # 用户语义上的「停/启」。

            self._message = QLabel(self)
            self._message.setAlignment(Qt.AlignCenter)
            self._message.setWordWrap(True)
            # 同 EmptyState：Expanding 才能让 label 在父容器宽度内一行装下，
            # 否则按"刚够装下文字"的 sizeHint 来一行一个字。
            self._message.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            msg_font = _QFont(FONT_FAMILY_PRIMARY)
            msg_font.setPixelSize(TYPE_BODY)
            self._message.setFont(msg_font)

            layout.addWidget(self._ring, 0, Qt.AlignHCenter)
            layout.addWidget(self._message)

            self.setMinimumHeight(168)
            self.set_message("正在加载…")
            self._refresh()
            subscribe_theme(self, self._refresh)

        def set_message(self, text: str) -> None:
            self._message_text = text
            self._message.setText(text)
            self._message.setVisible(bool(text))

        def start(self) -> None:
            """Resume animation. 构造完即默认在跑，此处只为 API 对称。"""
            self._ring.resume()

        def stop(self) -> None:
            """Pause animation. 从 stack 切走后调一次省 CPU。"""
            self._ring.pause()

        def _refresh(self) -> None:
            self.setStyleSheet("background: transparent; border: none;")
            self._message.setStyleSheet(
                f"color: {token('text_primary')}; "
                f"line-height: 1.6; padding: 6px 8px; "
                f"background: transparent; border: none;"
            )

    return LoadingState


# ---------------------------------------------------------------------------
# ErrorState — 区别于「空 / 加载中」的错误占位（0.3.7 新增）
# ---------------------------------------------------------------------------
#
# 和 EmptyState 同布局：标题 + 副标题。但副标题用 ``status_failed_fg``
# 颜色 + 「重试」按钮，提示用户「这不是没数据，是出错了」——避免空状态
# 文本被解读成「搜索词没结果」。
#
# 设计要点
# --------
# * 标题颜色保持 ``text_primary``（不染红）——一行大字全染红看起来像警报，
#   其实只是「没搜到」级别的失败。
# * 副标题颜色用 ``status_failed_fg``——温和地标出「这是错误」但不抢眼。
# * 「重试」按钮是 ``set_action`` 的副产物，需要外部传 callable 进来。
# * 继承 EmptyState 的布局是因为它已经经过 0.3.5 一轮关于留白/字号/
#   字重的打磨——重写一遍只会重新踩一遍同样的坑。
#
# 用法：
#     self._error = ErrorState(self)
#     self._error.set_text("加载失败", "网络中断，请稍后重试。")
#     self._error.set_action("重试", self._refresh)
#     self._stack.addWidget(self._error)
#     # 失败时
#     self._stack.setCurrentWidget(self._error)


def build_error_state(parent=None):
    """失败占位卡片（区别于 EmptyState 的「空」。）

    与 EmptyState 的差异：
    * 副标题用 ``status_failed_fg`` 染色。
    * 多一个 ``set_action(label, callback)`` 入口，加一个按钮（默认「重试」）。
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont as _QFont
    from PySide6.QtWidgets import (
        QHBoxLayout,
        QLabel,
        QSizePolicy,
        QVBoxLayout,
        QWidget,
    )
    from qfluentwidgets import PushButton

    from .theme import (
        FONT_FAMILY_PRIMARY,
        SPACE_LG,
        SPACE_MD,
        TYPE_BODY,
        TYPE_CAPTION,
        subscribe_theme,
        token,
    )

    class ErrorState(QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setObjectName("errorState")
            self._title_text = ""
            self._subtitle_text = ""

            layout = QVBoxLayout(self)
            layout.setContentsMargins(
                SPACE_LG * 2, SPACE_LG * 3, SPACE_LG * 2, SPACE_LG * 3,
            )
            layout.setSpacing(SPACE_LG)
            layout.setAlignment(Qt.AlignCenter)

            self._title = QLabel(self)
            self._title.setAlignment(Qt.AlignCenter)
            self._title.setWordWrap(True)
            self._title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            title_font = _QFont(FONT_FAMILY_PRIMARY)
            title_font.setPixelSize(TYPE_BODY + 1)
            title_font.setWeight(_QFont.Medium)
            self._title.setFont(title_font)

            self._subtitle = QLabel(self)
            self._subtitle.setAlignment(Qt.AlignCenter)
            self._subtitle.setWordWrap(True)
            self._subtitle.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            sub_font = _QFont(FONT_FAMILY_PRIMARY)
            sub_font.setPixelSize(TYPE_CAPTION)
            self._subtitle.setFont(sub_font)

            # 错误专属的「重试」按钮槽
            self._action_row = QHBoxLayout()
            self._action_row.setContentsMargins(0, 0, 0, 0)
            self._action_row.setSpacing(SPACE_MD)
            self._action = PushButton("重试", self)
            self._action.setVisible(False)
            self._action.clicked.connect(self._on_action_clicked)
            self._action_row.addStretch(1)
            self._action_row.addWidget(self._action)
            self._action_row.addStretch(1)

            layout.addWidget(self._title)
            layout.addWidget(self._subtitle)
            layout.addLayout(self._action_row)

            self.setMinimumHeight(168)
            self._action_cb = None
            self._refresh()
            subscribe_theme(self, self._refresh)

        def set_text(self, title: str, subtitle: str = "") -> None:
            self._title_text = title
            self._subtitle_text = subtitle
            self._title.setText(title)
            self._subtitle.setText(subtitle)
            self._subtitle.setVisible(bool(subtitle))

        def set_action(self, label: str, callback) -> None:
            """Configure the retry button.

            Pass ``label=""`` to hide the action entirely. Callback receives
            no arguments; it's typically ``self._refresh`` or similar.
            """
            if not label:
                self._action.setVisible(False)
                self._action_cb = None
                return
            self._action.setText(label)
            self._action.setVisible(True)
            self._action_cb = callback

        def _on_action_clicked(self) -> None:
            cb = self._action_cb
            if cb is not None:
                cb()

        def _refresh(self) -> None:
            self.setStyleSheet("background: transparent; border: none;")
            self._title.setStyleSheet(
                f"color: {token('text_primary')}; "
                f"line-height: 1.6; padding: 10px 8px; "
                f"background: transparent; border: none;"
            )
            # 副标题染色为 status_failed —— 用 fg 不染红底，温和地告知失败
            # 但不抢标题的注意力。
            self._subtitle.setStyleSheet(
                f"color: {token('status_failed_fg', token('text_muted'))}; "
                f"line-height: 1.6; padding: 6px 8px; "
                f"background: transparent; border: none;"
            )

    return ErrorState
