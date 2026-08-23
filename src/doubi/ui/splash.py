"""启动闪屏（Splash Screen）。

PySide6 自带 :class:`QSplashScreen`，给静态图加一个居中遮罩，适合「加载主
窗口之前先亮出品牌」的几十毫秒场景。这里不试图展示真实进度——闪屏关闭
时主窗口已经准备好了，进度条会立刻满格反而显得假。

设计：

* 图标复用 :func:`doubi.ui.resources.load_splash_pixmap`，不增加资源。
* ``finish()`` 接受任意主窗口，调用方控制关闭时机。
* 资源缺失或无 PySide6 时静默退化，不阻塞主流程。
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("doubi.ui.splash")


def show_splash(app) -> Optional[object]:
    """创建并显示启动闪屏。

    :param app: :class:`QApplication` 实例，用于居中计算。
    :return: :class:`QSplashScreen` 实例。无 PySide6 或图标缺失时返回 ``None``。
    """
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtWidgets import QSplashScreen
    except ImportError:  # pragma: no cover - 无 GUI 环境
        return None

    from .resources import load_splash_pixmap

    # 256px：图标现在是矢量渲染，放大不糊，闪屏可以给足品牌存在感
    pix = load_splash_pixmap(256, 256)
    if pix is None:
        return None

    splash = QSplashScreen(pix, Qt.WindowStaysOnTopHint)
    # 居中显示
    screen = QGuiApplication.primaryScreen()
    if screen is not None:
        geo = screen.availableGeometry()
        x = (geo.width() - splash.width()) // 2
        y = (geo.height() - splash.height()) // 2
        splash.move(x, y)
    splash.show()
    app.processEvents()
    return splash


def finish_splash(splash) -> None:
    """关闭闪屏。无实例或非 QSplashScreen 时静默忽略。"""
    if splash is None:
        return
    try:
        splash.finish(None)
        splash.deleteLater()
    except Exception:  # pragma: no cover - 防御性
        logger.debug("关闭闪屏失败", exc_info=True)
