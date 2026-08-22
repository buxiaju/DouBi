"""UI pages — Parse / Download / History / Settings.

Each module exposes ``build_<page>_widgets()`` that returns a
``(class_, factory)`` pair. The factory is convenient for
:class:`qfluentwidgets.MSFluentWindow.addSubInterface` which
wants a class, not an instance.
"""

from __future__ import annotations

from .download import build_download_widgets
from .history import build_history_widgets
from .parse import build_parse_widgets
from .settings import build_settings_widgets

__all__ = [
    "build_parse_widgets",
    "build_download_widgets",
    "build_history_widgets",
    "build_settings_widgets",
]
