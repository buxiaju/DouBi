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


def _install_exception_hooks(app) -> None:
    """Install cross-layer "last chance" exception handlers.

    * ``sys.excepthook`` — fires when a sync function raises on the Qt
      main thread (this is the classic "Qt app just vanishes" path:
      before PySide6.6, exceptions raised in slots were silently
      swallowed by default; now they still kill the process if the
      slot ran on the event loop). We log them and, for the worst
      crashes, keep the process alive long enough for the user to
      notice the trace.
    * A wrapper around ``asyncio.get_event_loop().call_exception_handler``
      — fires on unhandled exceptions inside ``create_task()`` bodies.
      Without this, TaskManager tasks that raise after
      ``_run_download`` has finished would just raise into the void and
      never surface anywhere.

    Neither hook ever shows a modal dialog: crashing in the crash
    reporter is a classic desktop-app pitfall. Log only.
    """
    import traceback

    def _sync_hook(etype, value, tb):
        logger.error("Unhandled exception on Qt main thread:\n%s",
                     "".join(traceback.format_exception(etype, value, tb)))
        # Continue with the default behavior so fatal errors still exit,
        # but first flush the handler (logging buffering can otherwise
        # make the above line disappear when the app crashes).
        for h in logger.handlers:
            try:
                h.flush()
            except Exception:
                pass
        # Keep old hook chain (Python has a default that writes to
        # stderr and PySide may have installed its own).
        try:
            _ORIG_SYSEXCEPTHOOK(etype, value, tb)
        except Exception:
            pass

    def _async_handler(loop, context):
        # context['exception'] is the actual exception object when
        # available; for future-compat we always print the ``message``
        # field as well.
        try:
            lines = ["Unhandled exception in asyncio task:\n"]
            if "message" in context:
                lines.append(f"  message: {context['message']}\n")
            exc = context.get("exception")
            if exc is not None:
                lines.append("".join(
                    traceback.format_exception(type(exc), exc, exc.__traceback__)
                ))
            else:
                for k, v in context.items():
                    if k in {"message", "exception"}:
                        continue
                    lines.append(f"  {k}: {v!r}\n")
            logger.error("".join(lines))
            for h in logger.handlers:
                try:
                    h.flush()
                except Exception:
                    pass
        except Exception:
            pass
        # Fall back to the default handler so Python still warns.
        try:
            _ORIG_ASYNC_HANDLER(loop, context)
        except Exception:
            pass

    global _ORIG_SYSEXCEPTHOOK, _ORIG_ASYNC_HANDLER  # noqa: PLW0603
    _ORIG_SYSEXCEPTHOOK = sys.excepthook
    sys.excepthook = _sync_hook

    try:
        loop = asyncio.get_event_loop()
        _ORIG_ASYNC_HANDLER = loop.get_exception_handler() or loop.default_exception_handler
        loop.set_exception_handler(_async_handler)
    except Exception:
        # No event loop yet (e.g. --no-event-loop is used). We'll miss
        # async tasks in that mode, but it is a developer flag only.
        pass


_ORIG_SYSEXCEPTHOOK = sys.excepthook


def _default_async_handler(loop, context):  # pragma: no cover - trivial
    loop.default_exception_handler(context)


_ORIG_ASYNC_HANDLER = _default_async_handler


def main(argv: list[str] | None = None) -> int:
    # 主题名列表来自 ui/theme.py，它不 import Qt，所以这里可以
    # 在 GUI 可用性检查之前安全导入，让 --help 也能列出主题。
    from .theme import DEFAULT_THEME, theme_names

    parser = argparse.ArgumentParser(
        prog="doubi-gui",
        description="DouBi desktop GUI.",
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
    # 关窗 ≠ 退出进程：默认 Qt 在「最后一个窗口 close」时退出 app，这
    # 与我们 0.3.0 起的「关到托盘」语义直接冲突——主窗口关时 app 会
    # 立即结束，托盘根本来不及跑任何信号，整个 M6.18 的「后台运行 +
    # 通知 + 唤回」链路就废了。这里把 quitOnLastWindowClosed 显式关掉，
    # 让 app 跟着 ``MainWindow.quit()``（托盘「退出」菜单触发）走。
    # 兜底：万一所有窗口都没正常退出（比如用户用任务管理器结束主窗口），
    # 托盘也能让用户「退出」按钮收尾。
    app.setQuitOnLastWindowClosed(False)
    _apply_app_branding(app)

    # Install hooks after logger + QApplication both exist (we need
    # ``logging`` configured, and a valid event loop target for the
    # async handler). The qasync loop is attached a few lines below;
    # _install_exception_hooks will attach to whatever loop is current
    # at that point, or use the default one when --no-event-loop is
    # passed. Hook order doesn't matter for correctness.
    _install_exception_hooks(app)

    # 显示启动闪屏——主窗口构建 + qasync loop 启动期间是几十毫秒
    # 的黑屏期，挂一张品牌图让用户先认得「打开的是豆比」。
    splash = None if args.no_splash else show_splash(app)
    # 让闪屏先实际渲染出来：``build_main_window`` 内部的延迟 import
    # （PySide6 / qfluentwidgets / pages）有几十毫秒开销，不 pump 事件
    # 闪屏会卡在「还没画出来」的状态，等于白 show。
    if splash is not None:
        app.processEvents()

    # 必须在建窗口之前定主题：各页面构造时会按当前 token 取色。
    # load_config 内部已处理 DOUBI_THEME 环境变量与配置文件。
    cfg = load_config(None)
    theme_name = args.theme or cfg.theme
    set_theme(theme_name)
    # 语言同主题：建窗前定下来，导航标签等首次渲染就走正确词表。
    # i18n 模块不 import Qt，可和 theme 一样安全早导。
    from .i18n import set_language
    set_language(cfg.language)

    # 通用嗅探（M6.16）：把 AppConfig 注入兜底适配器。这是 GUI 侧唯一的
    # ``AppConfig → Sniffer`` 注入口，漏掉它设置页的嗅探卡片就只是摆设
    # （adapter 会 lazy 读默认 YAML，但拿不到本进程内的 args 覆盖）。
    # 四个入口各自负责调一次，见硬约束 #4。
    from ..platforms.generic import GenericAdapter
    GenericAdapter.set_config(cfg)

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
