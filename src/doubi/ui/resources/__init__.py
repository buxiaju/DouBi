"""应用品牌资源（图标、名称、版本、版权）。

设计目标：

* **不强制依赖 PIL**：图标加载走 ``PySide6.QtGui.QPixmap``，PySide6 已经是
  GUI 形态的可选依赖，进 ``ui/`` 时已经确认它可用。
* **路径解析用 ``__file__`` 锚定**：不要假设 ``os.getcwd()``，PyInstaller
  打包后 cwd 会变，但 ``__file__`` 始终指向包内的资源文件。
* **退化路径**：图标丢失时返回 ``None``，调用方决定是否回退到
  ``qfluentwidgets`` 自带图标。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

__all__ = [
    "APP_NAME",
    "APP_DISPLAY_NAME",
    "APP_VERSION",
    "APP_TAGLINE",
    "APP_COPYRIGHT",
    "RESOURCE_DIR",
    "icon_path",
    "splash_path",
    "load_app_icon",
    "load_splash_pixmap",
]


APP_NAME = "DouBi"
APP_DISPLAY_NAME = "豆比下载"
APP_TAGLINE = "一站式多平台视频下载"
APP_VERSION = "0.6.0"
APP_COPYRIGHT = "© 2026 DouBi Contributors · GPL-3.0"

RESOURCE_DIR = Path(__file__).resolve().parent


def icon_path() -> Path:
    """主图标路径（PNG）。"""
    return RESOURCE_DIR / "icon.png"


def splash_path() -> Path:
    """启动闪屏图路径。复用主图标，启动屏只是显示风格不同。"""
    return RESOURCE_DIR / "icon.png"


def load_app_icon(size: Optional[int] = None):
    """加载应用主图标为 :class:`QIcon`，缺失时返回 ``None``。

    :param size: 期望尺寸。``None`` 时保留原图；指定尺寸时构造一个
        ``QIcon`` 并 addPixmap 一个平滑缩放后的版本（DPI 自适应更好）。
    """
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QIcon, QPixmap
    except ImportError:  # pragma: no cover
        return None
    p = icon_path()
    if not p.is_file():
        return None
    pix = QPixmap(str(p))
    if pix.isNull():
        return None
    if size is not None:
        pix = pix.scaled(
            size, size,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
    icon = QIcon(pix)
    return icon if not icon.isNull() else None


def load_splash_pixmap(width: int = 240, height: int = 240):
    """加载启动闪屏用的 :class:`QPixmap`。

    图标本身是正方形的，所以只取一个尺寸即可居中显示。
    """
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QPixmap
    except ImportError:  # pragma: no cover
        return None
    p = splash_path()
    if not p.is_file():
        return None
    pix = QPixmap(str(p))
    if pix.isNull():
        return None
    return pix.scaled(
        width, height,
        Qt.KeepAspectRatio,
        Qt.SmoothTransformation,
    )
