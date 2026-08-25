"""Download engine adapters.

An engine knows how to actually fetch a media item — it is a thin wrapper
around a transport library (yt-dlp / aria2 / native http). Platforms hand
off to whichever engine supports the URL.
"""

from __future__ import annotations

from .aria2 import Aria2Engine
from .base import Engine
from .direct_http import DirectHttpEngine
from .m3u8 import M3u8Engine
from .nm3u8dl import Nm3u8dlEngine
from .yt_dlp import YtDlpEngine

__all__ = ["Engine", "YtDlpEngine", "Aria2Engine", "M3u8Engine", "DirectHttpEngine", "Nm3u8dlEngine"]
