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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="doubi-gui",
        description="DouBi desktop GUI (M5 — minimal).",
    )
    parser.add_argument("--theme", choices=["light", "dark", "auto"], default="auto")
    parser.add_argument("--no-event-loop", action="store_true",
                        help="(dev) use Qt's default loop instead of qasync")
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
    from qfluentwidgets import setTheme, Theme

    app = QApplication(sys.argv)
    if args.theme == "light":
        setTheme(Theme.LIGHT)
    elif args.theme == "dark":
        setTheme(Theme.DARK)
    # else: let qfluentwidgets auto-detect via SystemThemeListener

    if not args.no_event_loop:
        loop = QEventLoop(app)
        asyncio.set_event_loop(loop)

    # Late imports so the GUI check runs first
    from .main_window import build_main_window
    MainWindow = build_main_window()
    window = MainWindow()
    window.show()

    if not args.no_event_loop:
        with loop:
            loop.run_forever()
    else:
        sys.exit(app.exec())

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
