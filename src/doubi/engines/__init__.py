"""Download engine adapters.

An engine knows how to actually fetch a media item — it is a thin wrapper
around a transport library (yt-dlp / aria2 / native http). Platforms hand
off to whichever engine supports the URL.
"""

from __future__ import annotations

from .base import Engine
from .yt_dlp import YtDlpEngine

__all__ = ["Engine", "YtDlpEngine"]
