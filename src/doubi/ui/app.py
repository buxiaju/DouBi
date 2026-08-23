"""DouBi GUI entry point.

The async event loop is run on the main thread via
:class:`qasync.QEventLoop`, which is the canonical way to combine
PySide6 (Qt's event loop) with asyncio. :class:`doubi.core.pipeline`
runs on this shared loop, and Qt widgets can schedule coroutines
with plain :func:`asyncio.create_task` because they share the
same loop.

Usage::

    doubi-gui                  # full GUI
    python -m doubi.ui.app     # same thing
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from . import GUIUnavailableError, is_gui_available

logger = logging.getLogger("doubi.ui.app")


def _ensure_gui_available():
    if not is_gui_available():
        raise GUIUnavailableError(
            "PySide6 + qfluentwidgets are not installed.\n"
            "Install with: pip install 'doubi[gui]'\n"
            "(includes PySide6, qfluentwidgets, qasync, and playwright)"
        )


def _apply_app_branding(app) -> None:
    """设置应用名 / 组织名 / 任务栏图标。

    这些字段在 QApplication 构造之后立即设置，原因：
    * ``setApplicationName`` 影响 QSettings 落盘位置（Windows 注册表路径）
    * ``setApplicationDisplayName`` 是 macOS 任务栏显示的名字
    * 任务栏图标在 Windows 上必须在 QApplication 创建后立刻设置，
      早于任何窗口创建，否则第一次显示窗口时图标不一致。
    """
    from .resources import APP_NAME, load_app_icon

    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName("DouBi")
    app.setDesktopFileName(APP_NAME)

    icon = load_app_icon()
    if icon is not None:
        app.setWindowIcon(icon)


def main(argv: list[str] | None = None) -> int:
    # 主题名列表来自 ui/theme.py，它不 import Qt，所以这里可以
    # 在 GUI 可用性检查之前安全导入，让 --help 也能列出主题。
    from .theme import DEFAULT_THEME, theme_names

    parser = argparse.ArgumentParser(
        prog="doubi-gui",
        description=f"DouBi desktop GUI.",
    )
    # default=None 而不是某个具体主题：只有显式传 --theme 才覆盖
    # 配置文件，与项目「环境变量 > 配置文件 > 默认值」的分层一致。
    parser.add_argument(
        "--theme", choices=theme_names(), default=None,
        help=f"界面主题（默认读取配置文件，回退 {DEFAULT_THEME}）",
    )
    parser.add_argument("--no-event-loop", action="store_true",
                        help="(dev) use Qt's default loop instead of qasync")
    parser.add_argument("--no-splash", action="store_true",
                        help="跳过启动闪屏")
    parser.add_argument("--log-level", default="INFO",
                        help="logging level (default: INFO)")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )

    _ensure_gui_available()

    from PySide6.QtWidgets import QApplication
    from qasync import QEventLoop

    from ..core.config import load_config
    from .splash import finish_splash, show_splash
    from .theme import set_theme

    app = QApplication(sys.argv)
    _apply_app_branding(app)

    # 显示启动闪屏——主窗口构建 + qasync loop 启动期间是几十毫秒
    # 的黑屏期，挂一张品牌图让用户先认得「打开的是豆比」。
    splash = None if args.no_splash else show_splash(app)

    # 必须在建窗口之前定主题：各页面构造时会按当前 token 取色。
    # load_config 内部已处理 DOUBI_THEME 环境变量与配置文件。
    theme_name = args.theme or load_config(None).theme
    set_theme(theme_name)

    if not args.no_event_loop:
        loop = QEventLoop(app)
        asyncio.set_event_loop(loop)

    # Late imports so the GUI check runs first
    from .main_window import build_main_window
    MainWindow = build_main_window()
    window = MainWindow()
    # 上面那次 set_theme 发生在窗口存在之前，_apply_window_background 当时
    # 遍历不到任何顶层窗口，主窗口底色（以及 Win11 的 Mica 关闭）落不下去。
    # 窗口建好后必须再刷一次，否则整体背景会停留在 fluent 默认色。
    set_theme(theme_name)
    window.show()
    finish_splash(splash)

    if not args.no_event_loop:
        with loop:
            loop.run_forever()
    else:
        sys.exit(app.exec())

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
