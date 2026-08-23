"""主题包（Theme Pack）—— GUI 的设计 token 中心。

每个主题是一张**完整的 token 表**并**自带明度**：选「深海」即固定为暗色，
没有独立的「亮/暗/自动」开关。这样做的代价是失去跟随系统明暗的能力，
换来的是「选了什么就是什么」的确定性。

设计约束：

* 本模块放在 ``ui/`` 而非 ``core/``。``core/`` 必须保持无 Qt 依赖，
  主题是纯呈现层概念——``core.config`` 只存一个字符串 ``theme``，不认识 token。
* token 表是纯数据，**导入本模块不需要 PySide6**。只有 :func:`set_theme`
  等真正操作 Qt 的函数才在函数体内延迟导入，与 ``ui/`` 其余模块一致。
* :attr:`ThemePack.name` 与 :attr:`ThemePack.label` 分离：写进 YAML 的是
  ``deep_sea`` 而不是「深海」。否则改文案或做 i18n 会让所有人的配置失效。

用法::

    from .theme import set_theme, current_theme, subscribe_theme

    set_theme("deep_sea")
    color = current_theme().tokens["text_muted"]
    subscribe_theme(widget, widget._refresh_colors)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger("doubi.ui.theme")

__all__ = [
    "ThemePack",
    "THEMES",
    "DEFAULT_THEME",
    "FONT_FAMILY",
    "FONT_FAMILY_MONO",
    "TYPE_H1",
    "TYPE_H2",
    "TYPE_H3",
    "TYPE_BODY",
    "TYPE_CAPTION",
    "TYPE_TINY",
    "SPACE_XS",
    "SPACE_SM",
    "SPACE_MD",
    "SPACE_LG",
    "SPACE_XL",
    "SPACE_XXL",
    "RADIUS_DEFAULT",
    "RADIUS_CARD",
    "RADIUS_PILL",
    "theme_names",
    "theme_labels",
    "resolve_theme",
    "get_theme",
    "current_theme",
    "current_theme_name",
    "set_theme",
    "subscribe_theme",
    "token",
    "muted_qss",
    "heading_qss",
    "body_qss",
    "card_qss",
    "header_qss",
    "app_qss",
]


@dataclass(frozen=True)
class ThemePack:
    """一套完整的界面配色。

    :param name: 持久化用的稳定 key（写入 YAML），如 ``deep_sea``
    :param label: 界面显示名，如「深海」
    :param dark: 自带明度，决定 ``setTheme(Theme.DARK / LIGHT)``
    :param accent: 主色，喂给 ``setThemeColor()``
    :param tokens: 语义化颜色 / 尺寸 / 排版 token 表，见模块内各主题定义
    """

    name: str
    label: str
    dark: bool
    accent: str
    accent_soft: str = ""           # 主色的 12% 透明变体，做 hover/选中背景
    accent_strong: str = ""         # 主色的更深变体，做按压/强调
    bg_elevated: str = ""           # 卡片/弹层上浮色（比 bg_layer 再亮一档）
    shadow: str = ""                # 主阴影色（rgba 字符串）
    gradient_header: tuple = ()     # 头部装饰渐变（起点, 终点），可空
    tokens: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------
# 内置主题
#
# 语义色必须随明度调整而非直接复用：#c02b2b 这类暗红在深色底上几乎不可读，
# 暗色主题一律提亮到 #ff6b6b 一档。这是旧 _apply_status_color() 的实际缺陷
# ——它用固定值，且主题切换时根本不刷新。
# --------------------------------------------------------------------------

DEFAULT_THEME = "default_light"


# --------------------------------------------------------------------------
# 排版 / 间距 / 圆角 常量
#
# 跨主题的尺寸规范集中在模块顶部，便于一眼看到「全应用统一的设计尺度」。
# 个别主题可以在 token 里覆盖 radius / row_height，但排版字号与间距是
# 写死的设计语言——所有主题共用，不在 token 里散落。
# --------------------------------------------------------------------------

# 字体优先级：优先中文 / 跨平台通用名，回退到系统默认无衬线。
# 不用"Microsoft YaHei"等带空格的本地化名：PySide6 在不同平台下
# 字体匹配算法略有差异，无空格名能保证每处渲染一致。
FONT_FAMILY = (
    "'PingFang SC', 'HarmonyOS Sans SC', 'Microsoft YaHei UI', "
    "'Source Han Sans SC', 'Noto Sans CJK SC', 'WenQuanYi Micro Hei', "
    "Segoe UI, sans-serif"
)
FONT_FAMILY_MONO = (
    "'JetBrains Mono', 'Cascadia Code', 'Fira Code', "
    "Consolas, 'Courier New', monospace"
)

# 排版尺度（所有主题共用）
TYPE_H1 = 22       # 页面大标题
TYPE_H2 = 16       # 卡片标题
TYPE_H3 = 14       # 分组标题
TYPE_BODY = 13     # 正文
TYPE_CAPTION = 12  # 次级说明
TYPE_TINY = 11     # 极小说明

# 间距尺度
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16
SPACE_XL = 24
SPACE_XXL = 32

# 圆角（默认；token 可覆盖）
RADIUS_DEFAULT = 6
RADIUS_CARD = 10
RADIUS_PILL = 999


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    """把 ``#rrggbb`` 形式的色值转成 ``rgba(r, g, b, a)``。

    主色需要做「12% 透明背景」时，qss 字符串里要 rgba 而不是 hex——直接
    把 ``#ff0000`` 拼到 ``rgba()`` 里会语法错误。本函数不解析简写
    (``#f00``) 也不解析 ``#rgb8``，因为主题包内统一用六位 hex 即可。
    """
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return f"rgba(128, 128, 128, {alpha})"
    try:
        r = int(h[0:2], 16)
        g = int(h[2:4], 16)
        b = int(h[4:6], 16)
    except ValueError:
        return f"rgba(128, 128, 128, {alpha})"
    return f"rgba({r}, {g}, {b}, {alpha})"


def _lighten(hex_color: str, amount: float = 0.06) -> str:
    """把 hex 颜色提亮 amount 比例（0~1），用于「elevated」层。"""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return hex_color
    try:
        r = int(h[0:2], 16)
        g = int(h[2:4], 16)
        b = int(h[4:6], 16)
    except ValueError:
        return hex_color
    nr = min(255, int(r + (255 - r) * amount))
    ng = min(255, int(g + (255 - g) * amount))
    nb = min(255, int(b + (255 - b) * amount))
    return f"#{nr:02x}{ng:02x}{nb:02x}"


def _darken(hex_color: str, amount: float = 0.12) -> str:
    """把 hex 颜色压暗 amount 比例（0~1），用于「strong」强调。"""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return hex_color
    try:
        r = int(h[0:2], 16)
        g = int(h[2:4], 16)
        b = int(h[4:6], 16)
    except ValueError:
        return hex_color
    nr = max(0, int(r * (1 - amount)))
    ng = max(0, int(g * (1 - amount)))
    nb = max(0, int(b * (1 - amount)))
    return f"#{nr:02x}{ng:02x}{nb:02x}"


def _light_tokens(
    *,
    bg_base: str,
    bg_layer: str,
    bg_hover: str,
    text_primary: str,
    text_muted: str,
) -> dict[str, Any]:
    """亮色主题的公共 token 骨架，只有背景/文字层需要各自指定。"""
    return {
        "bg_base": bg_base,
        "bg_layer": bg_layer,
        "bg_hover": bg_hover,
        "text_primary": text_primary,
        "text_muted": text_muted,
        "row_odd": "rgba(0, 0, 0, 0.028)",
        "row_even": "rgba(0, 0, 0, 0.055)",
        "status_running_fg": "#0a6cbf",
        "status_running_bg": "rgba(10, 108, 191, 0.10)",
        "status_paused_fg": "#a8690a",
        "status_paused_bg": "rgba(168, 105, 10, 0.12)",
        "status_completed_fg": "#127a1f",
        "status_completed_bg": "rgba(18, 122, 31, 0.10)",
        "status_failed_fg": "#c02b2b",
        "status_failed_bg": "rgba(192, 43, 43, 0.10)",
        "status_cancelled_fg": "#6b6b6b",
        "status_cancelled_bg": "rgba(107, 107, 107, 0.12)",
        "progress_normal": "#0a6cbf",
        "progress_success": "#2ea121",
        "progress_error": "#e64545",
        "progress_paused": "#e0a030",
        "radius": RADIUS_DEFAULT,
        "radius_card": RADIUS_CARD,
        "radius_pill": RADIUS_PILL,
        "row_height": 52,
        "shadow_sm": "0 1px 2px rgba(0, 0, 0, 0.06)",
        "shadow_md": "0 4px 12px rgba(0, 0, 0, 0.08)",
        "shadow_lg": "0 8px 24px rgba(0, 0, 0, 0.12)",
    }


def _dark_tokens(
    *,
    bg_base: str,
    bg_layer: str,
    bg_hover: str,
    text_primary: str,
    text_muted: str,
) -> dict[str, Any]:
    """暗色主题的公共 token 骨架。语义色整体提亮一档以保证可读性。"""
    return {
        "bg_base": bg_base,
        "bg_layer": bg_layer,
        "bg_hover": bg_hover,
        "text_primary": text_primary,
        "text_muted": text_muted,
        "row_odd": "rgba(255, 255, 255, 0.055)",
        "row_even": "rgba(255, 255, 255, 0.10)",
        "status_running_fg": "#4cc2ff",
        "status_running_bg": "rgba(76, 194, 255, 0.14)",
        "status_paused_fg": "#f0b25a",
        "status_paused_bg": "rgba(240, 178, 90, 0.16)",
        "status_completed_fg": "#5ed675",
        "status_completed_bg": "rgba(94, 214, 117, 0.14)",
        "status_failed_fg": "#ff6b6b",
        "status_failed_bg": "rgba(255, 107, 107, 0.16)",
        "status_cancelled_fg": "#9a9a9a",
        "status_cancelled_bg": "rgba(154, 154, 154, 0.16)",
        "progress_normal": "#4cc2ff",
        "progress_success": "#5ed675",
        "progress_error": "#ff6b6b",
        "progress_paused": "#f0b25a",
        "radius": RADIUS_DEFAULT,
        "radius_card": RADIUS_CARD,
        "radius_pill": RADIUS_PILL,
        "row_height": 52,
        "shadow_sm": "0 1px 2px rgba(0, 0, 0, 0.35)",
        "shadow_md": "0 4px 12px rgba(0, 0, 0, 0.45)",
        "shadow_lg": "0 8px 24px rgba(0, 0, 0, 0.55)",
    }


THEMES: dict[str, ThemePack] = {
    "default_light": ThemePack(
        name="default_light",
        label="默认亮",
        dark=False,
        accent="#0078d4",
        accent_soft="rgba(0, 120, 212, 0.10)",
        accent_strong="#005a9e",
        bg_elevated="#ffffff",
        shadow="rgba(0, 0, 0, 0.08)",
        tokens=_light_tokens(
            bg_base="#f3f3f3",
            bg_layer="#ffffff",
            bg_hover="#e6e6e6",
            text_primary="#1a1a1a",
            text_muted="#8a8a8a",
        ),
    ),
    "default_dark": ThemePack(
        name="default_dark",
        label="默认暗",
        dark=True,
        accent="#4cc2ff",
        accent_soft="rgba(76, 194, 255, 0.16)",
        accent_strong="#7fd6ff",
        bg_elevated="#2f2f2f",
        shadow="rgba(0, 0, 0, 0.45)",
        tokens=_dark_tokens(
            bg_base="#202020",
            bg_layer="#2b2b2b",
            bg_hover="#3a3a3a",
            text_primary="#f0f0f0",
            text_muted="#a0a0a0",
        ),
    ),
    # ----------------------------------------------------------------
    # 品牌主题——「豆比紫」
    #
    # 配色直接来自产品图标：深紫底色 + 琥珀/朱砂强调色。
    # 这是 DouBi 自家最有辨识度的视觉。
    # 排在两套「默认」主题之后，让下拉与导航栏循环先出现中性选项。
    # ----------------------------------------------------------------
    "doubi": ThemePack(
        name="doubi",
        label="豆比紫",
        dark=True,
        accent="#f59e6a",          # 琥珀橙，取自图标嘴/腮红色
        accent_soft="rgba(245, 158, 106, 0.16)",
        accent_strong="#d97a45",
        bg_elevated="#241a3d",     # 卡片/弹层上浮色
        shadow="rgba(0, 0, 0, 0.45)",
        gradient_header=("#2c1d4a", "#1a1230"),
        tokens={
            **_dark_tokens(
                bg_base="#1a1230",    # 图标主色：深邃紫
                bg_layer="#211842",
                bg_hover="#2d2160",
                text_primary="#f5ecff",
                text_muted="#a89dc4",
            ),
            # 主题专属覆写
            "row_odd": "rgba(255, 255, 255, 0.04)",
            "row_even": "rgba(255, 255, 255, 0.08)",
            "status_running_fg": "#f59e6a",
            "status_running_bg": "rgba(245, 158, 106, 0.18)",
            "status_paused_fg": "#f0c879",
            "status_paused_bg": "rgba(240, 200, 121, 0.18)",
            "status_completed_fg": "#7adfb0",
            "status_completed_bg": "rgba(122, 223, 176, 0.18)",
            "status_failed_fg": "#ff8a8a",
            "status_failed_bg": "rgba(255, 138, 138, 0.18)",
            "status_cancelled_fg": "#b0a8c8",
            "status_cancelled_bg": "rgba(176, 168, 200, 0.16)",
            "progress_normal": "#f59e6a",
            "progress_success": "#7adfb0",
            "progress_error": "#ff8a8a",
            "progress_paused": "#f0c879",
        },
    ),
    "deep_sea": ThemePack(
        name="deep_sea",
        label="深海",
        dark=True,
        accent="#2dd4bf",
        accent_soft="rgba(45, 212, 191, 0.16)",
        accent_strong="#5eead4",
        bg_elevated="#1d3a4a",
        shadow="rgba(0, 0, 0, 0.45)",
        tokens={
            **_dark_tokens(
                bg_base="#0f1c24",
                bg_layer="#162b36",
                bg_hover="#1f3b49",
                text_primary="#e3f2f5",
                text_muted="#7fa3ad",
            ),
            "status_running_fg": "#2dd4bf",
            "status_running_bg": "rgba(45, 212, 191, 0.14)",
            "progress_normal": "#2dd4bf",
        },
    ),
    "morandi": ThemePack(
        name="morandi",
        label="莫兰迪",
        dark=False,
        accent="#8c7b6b",
        accent_soft="rgba(140, 123, 107, 0.12)",
        accent_strong="#6b5a4a",
        bg_elevated="#fbfaf6",
        shadow="rgba(60, 50, 40, 0.10)",
        tokens={
            **_light_tokens(
                bg_base="#eceae5",
                bg_layer="#f7f5f1",
                bg_hover="#ded9d1",
                text_primary="#3b352f",
                text_muted="#948b80",
            ),
            "status_running_fg": "#7a6a58",
            "status_running_bg": "rgba(122, 106, 88, 0.12)",
            "status_completed_fg": "#6b7f5e",
            "status_completed_bg": "rgba(107, 127, 94, 0.12)",
            "progress_normal": "#8c7b6b",
            "progress_success": "#6b7f5e",
        },
    ),
    "eye_care": ThemePack(
        name="eye_care",
        label="护眼",
        dark=False,
        accent="#3f7d58",
        accent_soft="rgba(63, 125, 88, 0.12)",
        accent_strong="#2c5e3f",
        bg_elevated="#fdfaf2",
        shadow="rgba(80, 70, 40, 0.08)",
        tokens={
            **_light_tokens(
                bg_base="#f5f1e8",
                bg_layer="#fbf8f1",
                bg_hover="#e8e2d3",
                text_primary="#33372c",
                text_muted="#8b8874",
            ),
            "status_running_fg": "#3f7d58",
            "status_running_bg": "rgba(63, 125, 88, 0.12)",
            "progress_normal": "#3f7d58",
        },
    ),
    "high_contrast": ThemePack(
        name="high_contrast",
        label="高对比",
        dark=True,
        accent="#ffd60a",
        accent_soft="rgba(255, 214, 10, 0.22)",
        accent_strong="#ffe552",
        bg_elevated="#1a1a1a",
        shadow="rgba(0, 0, 0, 0.6)",
        tokens={
            **_dark_tokens(
                bg_base="#000000",
                bg_layer="#0d0d0d",
                bg_hover="#262626",
                text_primary="#ffffff",
                text_muted="#d0d0d0",
            ),
            "row_odd": "rgba(255, 255, 255, 0.10)",
            "row_even": "rgba(255, 255, 255, 0.18)",
            "status_running_fg": "#ffd60a",
            "status_running_bg": "rgba(255, 214, 10, 0.20)",
            "status_completed_fg": "#7cff7c",
            "status_completed_bg": "rgba(124, 255, 124, 0.20)",
            "status_failed_fg": "#ff8080",
            "status_failed_bg": "rgba(255, 128, 128, 0.20)",
            "status_cancelled_fg": "#cccccc",
            "status_cancelled_bg": "rgba(204, 204, 204, 0.20)",
            "progress_normal": "#ffd60a",
            "progress_success": "#7cff7c",
            "progress_error": "#ff8080",
        },
    ),
}


def theme_names() -> list[str]:
    """全部主题 key，顺序即界面展示顺序。"""
    return list(THEMES)


def theme_labels() -> list[str]:
    """全部主题显示名，与 :func:`theme_names` 同序。"""
    return [pack.label for pack in THEMES.values()]


def resolve_theme(value: Optional[str]) -> str:
    """把任意输入归一为合法主题 key。

    接受 key（``deep_sea``）、显示名（「深海」），以及为兼容旧配置保留的
    ``light`` / ``dark`` / ``auto``。无法识别时回退到 :data:`DEFAULT_THEME`
    并记一条 warning——绝不因为一个坏配置值让 GUI 起不来。
    """
    if not value:
        return DEFAULT_THEME
    text = str(value).strip()
    if text in THEMES:
        return text
    for pack in THEMES.values():
        if text == pack.label:
            return pack.name
    legacy = {
        "light": "default_light",
        "亮色": "default_light",
        "dark": "default_dark",
        "暗色": "default_dark",
        "auto": DEFAULT_THEME,
        "自动": DEFAULT_THEME,
    }
    if text.lower() in legacy:
        return legacy[text.lower()]
    if text in legacy:
        return legacy[text]
    logger.warning("未知主题 %r，回退到 %s", value, DEFAULT_THEME)
    return DEFAULT_THEME


def get_theme(name: Optional[str]) -> ThemePack:
    """按名取主题包，无法识别时返回默认主题。"""
    return THEMES[resolve_theme(name)]


# --------------------------------------------------------------------------
# 运行时状态
# --------------------------------------------------------------------------

_current: str = DEFAULT_THEME
_callbacks: list[Callable[[], None]] = []


def current_theme() -> ThemePack:
    """当前生效的主题包。"""
    return THEMES[_current]


def current_theme_name() -> str:
    """当前生效的主题 key（可直接写入配置）。"""
    return _current


def token(key: str, default: Any = None) -> Any:
    """取当前主题的一个 token，缺失时给 default。"""
    return current_theme().tokens.get(key, default)


def muted_qss(size: int = TYPE_CAPTION) -> str:
    """次级说明文字的 QSS。

    原来各页面散落着 ``setStyleSheet("color: gray;")``：字面量 gray 在暗色
    背景上对比度不足，而且换主题时不会刷新。统一走本函数后四处行为一致。
    """
    return f"font-family: {FONT_FAMILY}; font-size: {size}px; color: {token('text_muted')};"


def heading_qss(level: int = 1) -> str:
    """页面/卡片大标题的 QSS。

    等级映射字号：1 → 22, 2 → 16, 3 → 14。统一用主题主色加粗，让标题
    在所有主题里都「跳出来」——而不是用 text_primary 的死黑色块。
    """
    sizes = {1: TYPE_H1, 2: TYPE_H2, 3: TYPE_H3}
    size = sizes.get(level, TYPE_BODY)
    weight = "600" if level <= 2 else "500"
    color = token("text_primary")
    return (
        f"font-family: {FONT_FAMILY}; "
        f"font-size: {size}px; "
        f"font-weight: {weight}; "
        f"color: {color};"
    )


def body_qss(size: int = TYPE_BODY) -> str:
    """正文文字的 QSS。"""
    return (
        f"font-family: {FONT_FAMILY}; "
        f"font-size: {size}px; "
        f"color: {token('text_primary')};"
    )


def card_qss(elevated: bool = False) -> str:
    """卡片容器的 QSS。

    elevated=True 时用 ``bg_elevated``（比 layer 再亮一档，模拟上浮），
    主要给弹层/对话框使用。普通页面卡片用 False 即可。

    圆角 radius_card 单独维护：list/table 行希望圆角小，登录对话框希望
    圆角大，两件事不应当共用同一个 token。
    """
    pack = current_theme()
    bg = pack.bg_elevated if elevated and pack.bg_elevated else token("bg_layer")
    border = (
        "rgba(255, 255, 255, 0.10)" if pack.dark
        else "rgba(0, 0, 0, 0.08)"
    )
    radius = token("radius_card", RADIUS_CARD)
    return (
        f"background-color: {bg}; "
        f"border: 1px solid {border}; "
        f"border-radius: {radius}px;"
    )


def header_qss(level: int = 1) -> str:
    """页面顶部的「Hero」区 QSS：品牌渐变 + 标题 + 副标题。

    在 ``MainWindow`` 的「欢迎」位和登录对话框的标题区使用。level 控制
    标题字号与渐变强度。token ``gradient_header`` 缺省时退化为纯色底，
    不会因为新主题没填这个键而崩。
    """
    pack = current_theme()
    if pack.gradient_header:
        bg_start, bg_end = pack.gradient_header
        background = f"qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {bg_start}, stop:1 {bg_end})"
    else:
        background = pack.bg_elevated or token("bg_layer")
    sizes = {1: TYPE_H1, 2: TYPE_H2, 3: TYPE_H3}
    title_size = sizes.get(level, TYPE_H1)
    return f"""
        QWidget#brandHero {{
            background: {background};
            border: none;
            border-radius: {RADIUS_CARD}px;
        }}
        QLabel#brandHeroTitle {{
            font-family: {FONT_FAMILY};
            font-size: {title_size}px;
            font-weight: 600;
            color: {token('text_primary')};
            background: transparent;
            border: none;
        }}
        QLabel#brandHeroSubtitle {{
            font-family: {FONT_FAMILY};
            font-size: {TYPE_CAPTION}px;
            color: {token('text_muted')};
            background: transparent;
            border: none;
        }}
    """


def app_qss(pack: Optional[ThemePack] = None) -> str:
    """整套界面的全局 QSS（喂给 ``QApplication.setStyleSheet``）。

    **为什么必须有这个函数**：qfluentwidgets 内置只有「亮」「暗」两套调色板，
    ``setTheme()`` 只能在这两者间切，``setThemeColor()`` 只改强调色。也就是说
    「深海 / 莫兰迪 / 护眼 / 高对比」这四套主题里的 ``bg_base`` / ``bg_layer``
    以前从未真正生效——窗口和输入框始终是 fluent 自带的白底或深灰底，
    用户只能看到强调色在变。本函数把 token 表翻译成 QSS 铺到整个应用上，
    背景层才真正跟着主题走。

    覆盖范围刻意写全：窗口 / 页面容器 / 多行输入 / 单行输入 / 下拉 / 表格
    （含表头与选中态）/ 滚动区与滚动条 / 对话框 / 普通文字。少一处就会像
    之前的解析页那样留一块突兀的白。
    """
    pack = pack or current_theme()
    t = pack.tokens
    base = t["bg_base"]
    layer = t["bg_layer"]
    hover = t["bg_hover"]
    text = t["text_primary"]
    muted = t["text_muted"]
    accent = pack.accent
    accent_soft = pack.accent_soft or _hex_to_rgba(accent, 0.14)
    radius = t.get("radius", RADIUS_DEFAULT)
    radius_card = t.get("radius_card", RADIUS_CARD)
    # 边框色跟着明度走：暗色主题用提亮的白色叠加，亮色主题用压暗的黑色叠加，
    # 这样同一套规则在六个主题下都不会出现「边框比背景还亮」的割裂感。
    border = (
        "rgba(255, 255, 255, 0.10)" if pack.dark else "rgba(0, 0, 0, 0.10)"
    )
    return f"""
/* ---- 全局字体 ----
   把默认字体写进 QSS，让所有没显式指定字体的控件都按这套字渲染。 */
* {{
    font-family: {FONT_FAMILY};
    font-size: {TYPE_BODY}px;
}}

/* ---- 窗口与页面容器 ---- */
QWidget#parseInterface,
QWidget#downloadInterface,
QWidget#historyInterface,
QWidget#settingsInterface {{
    background-color: {base};
}}
QMainWindow {{
    background-color: {base};
}}
QDialog {{
    background-color: {base};
}}

/* ---- 文字 ---- */
QLabel {{
    color: {text};
    background-color: transparent;
    font-family: {FONT_FAMILY};
}}

/* ---- 多行输入（解析页 URL 框、登录框二维码/日志） ---- */
QPlainTextEdit, QTextEdit {{
    background-color: {layer};
    color: {text};
    border: 1px solid {border};
    border-radius: {radius}px;
    padding: 6px;
    selection-background-color: {accent};
    selection-color: #ffffff;
}}

/* ---- 单行输入与下拉 ---- */
QLineEdit, LineEdit, SearchLineEdit {{
    background-color: {layer};
    color: {text};
    border: 1px solid {border};
    border-radius: {radius}px;
    padding: 4px 8px;
    selection-background-color: {accent};
    selection-color: #ffffff;
}}
ComboBox, QComboBox {{
    background-color: {layer};
    color: {text};
    border: 1px solid {border};
    border-radius: {radius}px;
    padding: 4px 8px;
}}

/* ---- 工具提示（悬浮提示）---- */
QToolTip {{
    background-color: {layer};
    color: {text};
    border: 1px solid {border};
    border-radius: {radius}px;
    padding: 6px 8px;
    font-family: {FONT_FAMILY};
    font-size: {TYPE_CAPTION}px;
}}

/* ---- 表格（解析结果、历史记录） ---- */
QTableView, TableWidget, QTableWidget {{
    background-color: {layer};
    alternate-background-color: {hover};
    color: {text};
    border: 1px solid {border};
    border-radius: {radius_card}px;
    gridline-color: {border};
    selection-background-color: {accent_soft};
    selection-color: {text};
}}
QTableView::item {{
    color: {text};
    background-color: transparent;
    padding: 4px 8px;
    border: none;
}}
QTableView::item:selected {{
    background-color: {accent_soft};
    color: {text};
}}
QHeaderView {{
    background-color: transparent;
}}
QHeaderView::section {{
    background-color: transparent;
    color: {muted};
    border: none;
    border-bottom: 1px solid {border};
    padding: 8px 8px;
    font-weight: 500;
    font-size: {TYPE_CAPTION}px;
}}
QTableCornerButton::section {{
    background-color: transparent;
    border: none;
}}

/* ---- 滚动区与滚动条 ----
   页面里的 QScrollArea 已手工透明化，这里再兜一层，避免 viewport
   在某些样式下露出 fluent 的默认底色。 */
QScrollArea {{
    background-color: transparent;
    border: none;
}}
QScrollBar:vertical, QScrollBar:horizontal {{
    background-color: transparent;
    border: none;
    width: 8px;
    height: 8px;
}}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background-color: {border};
    border-radius: 4px;
    min-height: 24px;
    min-width: 24px;
}}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{
    background-color: {accent_soft};
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    background-color: transparent;
    border: none;
    height: 0;
    width: 0;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background-color: transparent;
}}

/* ---- 复选框 / 单选框 ----
   解析结果表头的全选框和下拉框的勾选项都用 QSS 着色，跟主题走。 */
QCheckBox, QRadioButton {{
    color: {text};
    spacing: 8px;
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {border};
    border-radius: 3px;
    background-color: {layer};
}}
QCheckBox::indicator:checked {{
    background-color: {accent};
    border-color: {accent};
}}
QRadioButton::indicator {{
    border-radius: 8px;
}}
QRadioButton::indicator:checked {{
    background-color: {accent};
    border-color: {accent};
}}

/* ---- 进度条 ----
   进度条走 qfluentwidgets 自绘，但兜底一份给原生 QProgressBar。 */
QProgressBar {{
    background-color: {hover};
    border: none;
    border-radius: 3px;
    text-align: center;
    color: {text};
    height: 6px;
}}
QProgressBar::chunk {{
    background-color: {accent};
    border-radius: 3px;
}}

/* ---- 提示条 InfoBar ----
   qfluentwidgets 的 InfoBar 是自绘的，QSS 不一定管用，但兜底一层总没坏处。 */
InfoBar, InfoBarView {{
    background-color: {layer};
    color: {text};
    border-radius: {radius}px;
}}
"""


def _apply_app_qss(pack: ThemePack) -> None:
    """把 :func:`app_qss` 铺到 QApplication 上。

    走 ``QApplication`` 而不是逐控件 ``setStyleSheet``：QSS 会向下继承，
    一次调用就覆盖所有页面、对话框和未来新增的控件，不必每加一个控件
    就回来补一行。没有 QApplication 实例时（测试环境）静默跳过。
    """
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:  # pragma: no cover - 无 GUI 环境
        return
    app = QApplication.instance()
    if app is None:
        return
    app.setStyleSheet(app_qss(pack))


def _apply_window_background(pack: ThemePack) -> None:
    """给 MSFluentWindow 本体刷底色。

    主窗口是自绘的（``paintEvent`` 里直接填 ``backgroundColor``），QSS 管不到，
    必须调它自己的 ``setCustomBackgroundColor``。另外 Win11 上 fluent 默认开
    Mica 毛玻璃，开启时 ``_normalBackgroundColor()`` 会返回全透明，自定义底色
    根本画不出来——所以这里先把 Mica 关掉。这正是「整体背景没变」的直接原因。
    """
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:  # pragma: no cover - 无 GUI 环境
        return
    app = QApplication.instance()
    if app is None:
        return
    base = pack.tokens["bg_base"]
    for widget in app.topLevelWidgets():
        setter = getattr(widget, "setCustomBackgroundColor", None)
        if setter is None:
            continue
        disable_mica = getattr(widget, "setMicaEffectEnabled", None)
        if disable_mica is not None:
            try:
                disable_mica(False)
            except Exception:  # pragma: no cover - 非 Win11 直接 return
                pass
        try:
            setter(base, base)
        except (TypeError, ValueError):  # pragma: no cover - 防御性
            continue


_cards_patched = False


def _patch_fluent_card_background() -> None:
    """让 fluent 卡片的自绘底色改读主题 token（只需打一次）。

    ``CardWidget`` 的背景不是 QSS 画的，而是 ``paintEvent`` 里
    ``painter.setBrush(self.backgroundColor)``，取值来自
    ``_normalBackgroundColor()``——库里硬编码成 ``QColor(255, 255, 255, 170)``，
    也就是一层半透明**白**。所以无论怎么写样式表，解析页那张结果卡片永远
    发白，这正是用户看到「解析口一直是白色」的直接原因。

    这里把这三个取色方法换成读 token 的版本。因为是「调用时才取色」，
    打完补丁后卡片会自动跟着每次换主题走，不必为每张卡片单独登记。
    """
    global _cards_patched
    if _cards_patched:
        return
    try:
        from PySide6.QtGui import QColor
        from qfluentwidgets import CardWidget, SimpleCardWidget
    except ImportError:  # pragma: no cover - 无 GUI 环境
        return

    def _normal(self):  # noqa: ANN001, ANN202 - 需匹配库的方法签名
        return QColor(token("bg_layer"))

    def _hover(self):  # noqa: ANN001, ANN202
        return QColor(token("bg_hover"))

    # 两个类都要显式覆盖：SimpleCardWidget 自己重写过这三个方法，
    # 只改父类 CardWidget 的话它不会生效。
    for cls in (CardWidget, SimpleCardWidget):
        cls._normalBackgroundColor = _normal
        cls._hoverBackgroundColor = _hover
        cls._pressedBackgroundColor = _hover

    _cards_patched = True


def _fluent_override_qss(pack: ThemePack) -> str:
    """生成覆盖 fluent 自带硬编码颜色的那一份 QSS。

    库里每个控件的 qss 都把颜色写死了亮色值，实测（读编译进 rcc 的资源）：

    * ``button.qss``  → ``background: rgba(255,255,255,0.7); color: black``
    * ``combo_box.qss`` → 同上
    * ``line_edit.qss`` → 同上，``:focus`` 更是纯 ``white``
    * ``label.qss``   → ``FluentLabelBase { color: black }``
    * ``pivot.qss``   → 分段控件底色 + 文字写死黑
    * ``table_view.qss`` → 背景是 transparent（会跟卡片走），但表头文字写死灰

    所以这里只针对「写死了的」下手；已经是 transparent 的（表格背景、
    导航栏）不碰，让它们自然继承下层颜色。
    """
    t = pack.tokens
    layer = t["bg_layer"]
    hover = t["bg_hover"]
    text = t["text_primary"]
    muted = t["text_muted"]
    border = (
        "rgba(255, 255, 255, 0.10)" if pack.dark else "rgba(0, 0, 0, 0.10)"
    )
    radius = t.get("radius", 6)
    return f"""
PushButton, ToolButton, ToggleButton, ToggleToolButton,
DropDownPushButton, DropDownToolButton, SplitPushButton {{
    background: {layer};
    color: {text};
    border: 1px solid {border};
    border-bottom: 1px solid {border};
}}
PushButton:hover, ToolButton:hover, ToggleButton:hover,
ToggleToolButton:hover, DropDownPushButton:hover,
DropDownToolButton:hover, SplitPushButton:hover {{
    background: {hover};
    color: {text};
}}
PushButton:pressed, ToolButton:pressed, ToggleButton:pressed,
ToggleToolButton:pressed, DropDownPushButton:pressed,
DropDownToolButton:pressed, SplitPushButton:pressed {{
    background: {hover};
    color: {muted};
}}
TransparentToolButton, TransparentPushButton,
TransparentDropDownToolButton, TransparentDropDownPushButton,
TransparentTogglePushButton, TransparentToggleToolButton {{
    background-color: transparent;
    color: {text};
}}
ComboBox, ModelComboBox {{
    background-color: {layer};
    color: {text};
    border: 1px solid {border};
    border-bottom: 1px solid {border};
}}
ComboBox:hover, ModelComboBox:hover {{
    background-color: {hover};
}}
ComboBox:pressed, ModelComboBox:pressed {{
    background-color: {hover};
    color: {muted};
}}
LineEdit, TextEdit, PlainTextEdit, TextBrowser, SearchLineEdit {{
    background-color: {layer};
    color: {text};
    border: 1px solid {border};
    border-bottom: 1px solid {border};
    border-radius: {radius}px;
}}
LineEdit:hover, TextEdit:hover, PlainTextEdit:hover,
TextBrowser:hover, SearchLineEdit:hover {{
    background-color: {hover};
}}
LineEdit:focus, TextEdit:focus, PlainTextEdit:focus,
TextBrowser:focus, SearchLineEdit:focus {{
    background-color: {layer};
    border-bottom: 1px solid {pack.accent};
}}
FluentLabelBase {{
    color: {text};
    background-color: transparent;
}}
SegmentedWidget, SegmentedToolWidget {{
    background-color: {hover};
    border: 1px solid {border};
}}
SegmentedItem, SegmentedToolItem, PivotItem {{
    color: {muted};
    background-color: transparent;
}}
SegmentedItem[isSelected=true], SegmentedToolItem[isSelected=true],
PivotItem[isSelected=true] {{
    color: {text};
}}
SwitchButton > QLabel {{
    color: {text};
    background-color: transparent;
}}
QHeaderView::section {{
    background-color: transparent;
    color: {muted};
    border: 1px solid {border};
}}
QTableView::item {{
    color: {text};
}}
QTableCornerButton::section {{
    background-color: transparent;
    border: 1px solid {border};
}}
"""


def _refresh_fluent_widgets(pack: ThemePack) -> None:
    """逐个刷新 fluent 控件——它们压不住全局 QSS。

    Qt 里「控件自己的样式表」优先级高于 ``QApplication`` 的全局样式表，
    而 qfluentwidgets 会给每个控件单独 ``setStyleSheet``，所以
    :func:`app_qss` 对 fluent 控件基本无效（只对原生控件有效）。

    官方留的覆盖口是 ``setCustomStyleSheet``：它把我们的 QSS 拼在库自带
    QSS **之后**（``StyleSheetCompose`` 里 ``CustomStyleSheet`` 排最后），
    同选择器后者胜，于是能干净地改掉颜色而不用去改库文件。

    遍历对象选 ``styleSheetManager.items()`` 而不是 ``app.allWidgets()``：
    前者正好是「被库设过样式表、因而压住了全局 QSS」的那批控件，一个不多
    一个不少；后者会把成百上千个原生子控件也刷一遍，纯属浪费。
    卡片另走一条路——它的底色是自绘的，重算一次即可。
    """
    try:
        from qfluentwidgets import setCustomStyleSheet
        from qfluentwidgets.common.style_sheet import styleSheetManager
    except ImportError:  # pragma: no cover - 无 GUI 环境
        return

    qss = _fluent_override_qss(pack)
    for widget in list(styleSheetManager.widgets.keys()):
        try:
            setCustomStyleSheet(widget, qss, qss)
        except RuntimeError:  # pragma: no cover - 控件已被销毁
            continue

    for widget in _iter_cards():
        # 底色方法已被替换，触发一次重算就会取到新 token。
        widget._updateBackgroundColor()


def _iter_cards() -> list[Any]:
    """收集当前所有 fluent 卡片。

    卡片没有登记在 ``styleSheetManager`` 的必然性（它的颜色是自绘的），
    所以这里老老实实走 ``allWidgets()``。
    """
    try:
        from PySide6.QtWidgets import QApplication
        from qfluentwidgets import CardWidget
    except ImportError:  # pragma: no cover - 无 GUI 环境
        return []
    app = QApplication.instance()
    if app is None:
        return []
    return [w for w in app.allWidgets() if isinstance(w, CardWidget)]


_register_patched = False


def _patch_style_sheet_register() -> None:
    """让「换主题之后才创建的」fluent 控件也自动带上覆盖 QSS（只需打一次）。

    :func:`_refresh_fluent_widgets` 只能刷到调用那一刻已经存在的控件。
    可抖音登录对话框、右键菜单、下拉弹窗都是**用到才创建**的——它们在
    ``__init__`` 里调 ``styleSheetManager.register`` 拿库自带的亮色 QSS，
    错过了我们的刷新时机，于是又白回去。

    所以这里包一层 ``register``：任何控件一登记，立刻补上当前主题的覆盖 QSS。
    """
    global _register_patched
    if _register_patched:
        return
    try:
        from qfluentwidgets import setCustomStyleSheet
        from qfluentwidgets.common.style_sheet import styleSheetManager
    except ImportError:  # pragma: no cover - 无 GUI 环境
        return

    original = styleSheetManager.register

    def register(source: Any, widget: Any, reset: bool = True) -> None:
        original(source, widget, reset)
        try:
            qss = _fluent_override_qss(current_theme())
            setCustomStyleSheet(widget, qss, qss)
        except Exception:  # pragma: no cover - 不能让上色失败拖垮控件构造
            logger.debug("为新控件补主题 QSS 失败", exc_info=True)

    styleSheetManager.register = register
    _register_patched = True


def set_theme(name: Optional[str]) -> ThemePack:
    """切换主题并广播。

    六步：按主题自带的明度调 ``setTheme`` → 用主题主色调 ``setThemeColor``
    → 把卡片自绘取色和新控件的登记入口都接到 token 上 → 铺全局 QSS 覆盖
    原生控件 → 刷主窗口自绘底色与现存 fluent 控件 → 通知订阅者刷新那些把
    颜色烘进了 stylesheet 的控件。

    第三步往后都不能省：``setTheme`` 只在 fluent 内置的亮/暗两套色板间切，
    六套主题的 ``bg_base`` / ``bg_layer`` 得靠这些步骤才能真正落地。

    无 PySide6 时只更新内部状态（便于无 Qt 环境下测试解析逻辑）。
    """
    global _current
    pack = get_theme(name)
    _current = pack.name

    try:
        from qfluentwidgets import Theme, setTheme, setThemeColor
    except ImportError:  # pragma: no cover - 无 GUI 环境
        logger.debug("qfluentwidgets 不可用，仅更新主题状态为 %s", pack.name)
        return pack

    setTheme(Theme.DARK if pack.dark else Theme.LIGHT)
    setThemeColor(pack.accent)
    # 两个补丁都得在刷控件之前打好：卡片重算底色时取色方法必须已被替换，
    # 而 register 钩子要赶在后续控件创建之前就位。
    _patch_fluent_card_background()
    _patch_style_sheet_register()
    _apply_app_qss(pack)
    _apply_window_background(pack)
    _refresh_fluent_widgets(pack)
    _notify()
    return pack


def _notify() -> None:
    """逐个调用订阅者，任何一个抛异常都不许影响其余订阅者。"""
    for cb in list(_callbacks):
        try:
            cb()
        except Exception:  # pragma: no cover - 防御性
            logger.exception("主题回调执行失败")


def subscribe_theme(widget: Any, callback: Callable[[], None]) -> None:
    """订阅主题变化，随 ``widget`` 销毁自动解绑。

    同时挂到 qfluentwidgets 自身的 ``themeChanged`` 上，这样系统或第三方
    直接调 ``setTheme()`` 时自绘颜色也能跟上。

    旧代码只有 download.py 订阅了 ``themeChanged``，其余三个带色文件切主题后
    残留旧色；统一走本函数后四处行为一致。
    """
    _callbacks.append(callback)

    def _unsubscribe() -> None:
        try:
            _callbacks.remove(callback)
        except ValueError:  # pragma: no cover
            pass

    destroyed = getattr(widget, "destroyed", None)
    if destroyed is not None:
        destroyed.connect(_unsubscribe)

    try:
        from qfluentwidgets import qconfig
    except ImportError:  # pragma: no cover - 无 GUI 环境
        return
    qconfig.themeChanged.connect(lambda *_: callback())
