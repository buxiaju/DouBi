"""应用品牌资源（图标、名称、版本、版权）。

图标管线
========

设计源文件是 ``icon.svg``（画板 1124×1124，带投影/内高光滤镜），**不直接渲染**。
真正被渲染的是 ``icon_template.svg``——同一张图的 QtSvg 安全重写版，理由见该
文件头部注释（简言之：Qt 只实现 SVG Tiny 1.2，原文件的 ``feColorMatrix``
会被误画成实心黑块）。

三条设计取舍：

* **矢量优先，PNG 只是兜底**。QIcon 的每一档尺寸都由 SVG 独立渲染，而不是拿
  一张位图缩放——16px 的标题栏图标和 256px 的闪屏图标同样锐利。只有 QtSvg
  不可用（极老的 PySide6 发行版）时才退回 ``icon.png``。
* **配色跟着主题走**。``icon_template.svg`` 里的 7 个品牌色值同时充当替换锚点，
  换色就是一次正则替换（见 :data:`BRAND_PALETTE` / :func:`icon_palette`）。
  模板因此单独打开时仍是一张正常的品牌色图标，不引入模板语法。
* **不强制依赖 PIL**。渲染走 ``PySide6.QtSvg``，进 ``ui/`` 时 PySide6 已确认可用。

退化路径一律返回 ``None``，由调用方决定是否回退到 ``qfluentwidgets`` 自带图标。
"""

from __future__ import annotations

import colorsys
import logging
import re
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("doubi.ui.resources")

__all__ = [
    "APP_NAME",
    "APP_DISPLAY_NAME",
    "APP_VERSION",
    "APP_TAGLINE",
    "APP_COPYRIGHT",
    "RESOURCE_DIR",
    "BRAND_ACCENT",
    "BRAND_PALETTE",
    "ICON_SIZES",
    "icon_path",
    "icon_source_path",
    "icon_template_path",
    "splash_path",
    "icon_palette",
    "icon_svg",
    "render_icon_pixmap",
    "load_app_icon",
    "load_splash_pixmap",
    "clear_icon_cache",
]


APP_NAME = "DouBi"
APP_DISPLAY_NAME = "豆比下载"
APP_TAGLINE = "一站式多平台视频下载"
APP_VERSION = "0.1.0"
APP_COPYRIGHT = "© 2026 DouBi Contributors · GPL-3.0"

RESOURCE_DIR = Path(__file__).resolve().parent

#: 品牌主色（与 ``theme.THEMES["doubi"].accent`` 一致）。
BRAND_ACCENT = "#f59e6a"

#: 模板里的品牌色值 → 语义名。这七个 hex 同时是主题换色的替换锚点，
#: 因此 **必须与 icon_template.svg 中的字面量逐字一致**（含大小写）。
#: ``#FFFFFF``（眼睛高光、rim light）刻意不在此表内——它恒白。
BRAND_PALETTE: dict[str, str] = {
    "bg_from": "#FF8C42",   # 底板渐变起点
    "bg_to": "#FF5E7C",     # 底板渐变终点
    "tuft": "#E8552A",      # 呆毛
    "face": "#FFE4D1",      # 脸
    "ink": "#2A2A2A",       # 眼睛 / 嘴
    "blush": "#FF9AA2",     # 腮红
    "tongue": "#FF6B6B",    # 舌头
}

#: QIcon 预置的尺寸档位。覆盖标题栏(16) → 任务栏(32) → Alt+Tab(48)
#: → 对话框品牌区(96/128) → 闪屏(256)。每档独立渲染，不做位图缩放。
ICON_SIZES: tuple[int, ...] = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)

_HEX_TO_KEY = {v: k for k, v in BRAND_PALETTE.items()}
# 长的先匹配，避免短 hex 抢占（当前七色互不为前缀，但别把正确性寄托在巧合上）
_BRAND_RE = re.compile(
    "|".join(
        re.escape(h)
        for h in sorted(BRAND_PALETTE.values(), key=len, reverse=True)
    )
)

# --------------------------------------------------------------------------
# 路径
# --------------------------------------------------------------------------


def icon_path() -> Path:
    """位图兜底图标路径（PNG）。由 ``scripts/build_icons.py`` 从模板生成。"""
    return RESOURCE_DIR / "icon.png"


def icon_source_path() -> Path:
    """设计源 SVG。保留归档用，不参与渲染。"""
    return RESOURCE_DIR / "icon.svg"


def icon_template_path() -> Path:
    """渲染用 SVG 模板（QtSvg 安全子集 + 换色锚点）。"""
    return RESOURCE_DIR / "icon_template.svg"


def splash_path() -> Path:
    """启动闪屏图路径。复用主图标，闪屏只是显示尺寸不同。"""
    return icon_path()


# --------------------------------------------------------------------------
# 配色推导
# --------------------------------------------------------------------------


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _parse_hex(value: str) -> Optional[tuple[int, int, int]]:
    h = value.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    if len(h) != 6:
        return None
    try:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return None


def _to_hls(value: str) -> Optional[tuple[float, float, float]]:
    """``#rrggbb`` → ``(hue_deg, lightness, saturation)``。"""
    rgb = _parse_hex(value)
    if rgb is None:
        return None
    r, g, b = (c / 255.0 for c in rgb)
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return h * 360.0, l, s


def _from_hls(hue_deg: float, lightness: float, saturation: float) -> str:
    r, g, b = colorsys.hls_to_rgb(
        (hue_deg % 360.0) / 360.0, _clamp(lightness), _clamp(saturation)
    )
    return "#{:02X}{:02X}{:02X}".format(
        round(r * 255), round(g * 255), round(b * 255)
    )


def icon_palette(accent: Optional[str] = None) -> dict[str, str]:
    """按主题主色推导整套图标配色。

    :param accent: 主题主色（``#rrggbb``）。``None`` 或无法解析时返回品牌原色。

    推导规则（数值反推自品牌原图，保证 doubi 主题外的主题也是同一套「性格」）：

    * 底板渐变 = 主色色相 ±20°，亮度 0.63 → 0.68，形成同色系斜向双色调。
    * 呆毛比底板更深更沉（亮度 0.52），维持原图的层次。
    * 脸是主色色相的极浅色（亮度 0.90），冷色主题下自然变成薄荷/淡蓝奶油色。
    * **腮红、舌头、眼睛保持原色不动**。这三处是角色的「生物特征」，粉腮红 +
      红舌头是吉祥物辨识度的核心；跟着主题变绿变蓝会丢掉可爱感。主题识别度
      由占比 70% 以上的底板承担，已经足够。

    饱和度不是照抄主色而是压缩到 ``0.42 + 0.55 * s``：莫兰迪这类低饱和主题
    如果强行拉满会变成刺眼的橙色，与主题气质相悖。
    """
    if not accent:
        return dict(BRAND_PALETTE)
    hls = _to_hls(accent)
    if hls is None:
        logger.debug("无法解析主色 %r，回退品牌配色", accent)
        return dict(BRAND_PALETTE)

    hue, _lightness, sat = hls
    sat_bg = _clamp(0.42 + 0.55 * sat, 0.42, 0.97)
    return {
        "bg_from": _from_hls(hue + 20.0, 0.63, sat_bg),
        "bg_to": _from_hls(hue - 20.0, 0.68, sat_bg),
        "tuft": _from_hls(hue - 15.0, 0.52, _clamp(0.35 + 0.40 * sat, 0.35, 0.85)),
        "face": _from_hls(hue - 6.0, 0.90, _clamp(0.55 + 0.45 * sat, 0.50, 1.0)),
        "ink": BRAND_PALETTE["ink"],
        "blush": BRAND_PALETTE["blush"],
        "tongue": BRAND_PALETTE["tongue"],
    }


_template_cache: Optional[str] = None


def _template_text() -> Optional[str]:
    global _template_cache
    if _template_cache is not None:
        return _template_cache
    p = icon_template_path()
    if not p.is_file():
        logger.warning("图标模板缺失：%s", p)
        return None
    try:
        _template_cache = p.read_text(encoding="utf-8")
    except OSError:
        logger.warning("图标模板读取失败：%s", p, exc_info=True)
        return None
    return _template_cache


def icon_svg(accent: Optional[str] = None) -> Optional[str]:
    """返回按 ``accent`` 换色后的 SVG 文本；模板缺失时返回 ``None``。

    七个锚点用**一次**正则替换完成，而不是逐色 ``str.replace``：后者在
    「新色恰好等于另一个锚点」时会被下一轮替换二次命中，产出错色。
    """
    tpl = _template_text()
    if tpl is None:
        return None
    palette = icon_palette(accent)
    return _BRAND_RE.sub(
        lambda m: palette[_HEX_TO_KEY[m.group(0)]], tpl
    )


# --------------------------------------------------------------------------
# 主题解析（懒加载，避免 resources ←→ theme 循环导入）
# --------------------------------------------------------------------------


def _active_accent() -> Optional[str]:
    """当前主题的图标主色。

    返回 ``None`` 表示「用品牌原色」——豆比紫主题本身就是从图标反推出来的，
    再按主色二次推导只会偏离原图。
    """
    try:
        from ..theme import current_theme
    except Exception:  # pragma: no cover - 无 GUI / 导入期
        return None
    try:
        pack = current_theme()
    except Exception:  # pragma: no cover - 防御性
        return None
    if pack is None or getattr(pack, "name", None) == "doubi":
        return None
    return getattr(pack, "accent", None)


def _resolve_accent(accent: Optional[str], themed: bool) -> Optional[str]:
    if accent is not None:
        return accent
    return _active_accent() if themed else None


# --------------------------------------------------------------------------
# 渲染
# --------------------------------------------------------------------------

_pixmap_cache: dict[tuple[int, Optional[str]], Any] = {}
_icon_cache: dict[Optional[str], Any] = {}


def clear_icon_cache() -> None:
    """清空图标缓存。主要给测试与资源热替换用。"""
    _pixmap_cache.clear()
    _icon_cache.clear()


def _render_svg(size: int, accent: Optional[str]):
    """用 QtSvg 把模板渲染成 ``size × size`` 的 QPixmap。失败返回 ``None``。"""
    try:
        from PySide6.QtCore import QByteArray, Qt
        from PySide6.QtGui import QImage, QPainter, QPixmap
        from PySide6.QtSvg import QSvgRenderer
    except ImportError:  # pragma: no cover - 无 QtSvg 的老发行版
        return None
    markup = icon_svg(accent)
    if not markup:
        return None
    renderer = QSvgRenderer(QByteArray(markup.encode("utf-8")))
    if not renderer.isValid():  # pragma: no cover - 模板被改坏才会发生
        logger.warning("图标 SVG 解析失败")
        return None
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    try:
        renderer.render(painter)
    finally:
        painter.end()
    pix = QPixmap.fromImage(img)
    return None if pix.isNull() else pix


def _render_png(size: Optional[int]):
    """PNG 兜底。仅在 QtSvg 不可用或模板缺失时走到。"""
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QPixmap
    except ImportError:  # pragma: no cover
        return None
    p = icon_path()
    if not p.is_file():
        return None
    pix = QPixmap(str(p))
    if pix.isNull():
        return None
    if size is None:
        return pix
    return pix.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)


def render_icon_pixmap(
    size: int = 256,
    accent: Optional[str] = None,
    *,
    themed: bool = True,
):
    """渲染单张图标 :class:`QPixmap`。

    :param size: 边长（像素）。图标是正方形，宽高一致。
    :param accent: 强制指定主色。``None`` 时按 ``themed`` 决定。
    :param themed: ``True`` 跟随当前主题，``False`` 固定品牌原色。
    """
    if size <= 0:
        return None
    key = (size, _resolve_accent(accent, themed))
    cached = _pixmap_cache.get(key)
    if cached is not None:
        return cached
    pix = _render_svg(size, key[1]) or _render_png(size)
    if pix is not None:
        _pixmap_cache[key] = pix
    return pix


def load_app_icon(
    size: Optional[int] = None,
    accent: Optional[str] = None,
    *,
    themed: bool = True,
):
    """加载应用主图标为 :class:`QIcon`，缺失时返回 ``None``。

    :param size: 只需要单一尺寸时传入；``None`` 则填入 :data:`ICON_SIZES`
        全部档位，让 Qt 在标题栏 / 任务栏 / Alt+Tab 各挑最合适的一档，
        避免系统强制缩放产生锯齿与白边。
    :param accent: 强制指定主色，一般不用传。
    :param themed: 是否跟随当前主题配色。
    """
    try:
        from PySide6.QtGui import QIcon
    except ImportError:  # pragma: no cover - 无 GUI 环境
        return None

    resolved = _resolve_accent(accent, themed)

    if size is not None:
        pix = render_icon_pixmap(size, resolved, themed=False)
        if pix is None:
            return None
        icon = QIcon()
        icon.addPixmap(pix)
        return icon if not icon.isNull() else None

    cached = _icon_cache.get(resolved)
    if cached is not None:
        return cached

    icon = QIcon()
    added = False
    for s in ICON_SIZES:
        pix = render_icon_pixmap(s, resolved, themed=False)
        if pix is not None:
            icon.addPixmap(pix)
            added = True
    if not added:
        return None
    _icon_cache[resolved] = icon
    return icon


def load_splash_pixmap(
    width: int = 256,
    height: int = 256,
    accent: Optional[str] = None,
    *,
    themed: bool = True,
):
    """加载启动闪屏用的 :class:`QPixmap`。

    图标是正方形，取 ``min(width, height)`` 直接矢量渲染到目标边长——
    比「渲染大图再缩放」少一次重采样。
    """
    side = min(int(width), int(height))
    if side <= 0:
        return None
    return render_icon_pixmap(side, accent, themed=themed)
