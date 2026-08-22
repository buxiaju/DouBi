"""DouBi desktop GUI (M5).

PySide6 + qfluentwidgets. The GUI is a thin shell on top of
``doubi.core.pipeline`` — it does not duplicate any download /
parse / database logic. Each page is a QWidget subclass; long-
running operations are offloaded to asyncio via
:class:`doubi.ui.workers.DownloadWorker`.

PySide6 is an **optional** dependency. Importing this package
without PySide6 installed raises :class:`GUIUnavailableError` at
*use* time, not at import time, so the CLI / REST surfaces
keep working on headless servers.
"""

from __future__ import annotations

__all__ = ["GUIUnavailableError", "is_gui_available"]


class GUIUnavailableError(RuntimeError):
    """Raised when GUI modules are imported without PySide6 installed."""


def is_gui_available() -> bool:
    """True if PySide6 + qfluentwidgets are importable."""
    try:
        import PySide6  # noqa: F401
        import qfluentwidgets  # noqa: F401
        return True
    except ImportError:
        return False
