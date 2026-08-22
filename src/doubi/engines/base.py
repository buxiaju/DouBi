"""Engine abstraction.

An engine is a transport-layer adapter that knows how to fetch a
``MediaItem`` given a set of ``DownloadOptions`` and report progress.
The default engine is :class:`doubi.engines.yt_dlp.YtDlpEngine`. Future
engines (aria2 with rpc, native http, etc.) implement the same
interface and can be plugged in via the pipeline.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Optional

from ..core.models import DownloadOptions, MediaItem

logger = logging.getLogger("doubi.engines")


@dataclass
class EngineProgress:
    """A raw progress notification from an engine.

    The pipeline wraps this into a :class:`ProgressEvent`; engines do
    not need to know about job ids.
    """

    fraction: float = 0.0
    message: str = ""
    extra: Optional[dict] = None


#: Signature: (ev: EngineProgress) -> None
EngineProgressCallback = Callable[[EngineProgress], None]


class Engine(ABC):
    """Base class for download engines."""

    #: Stable identifier, e.g. ``"yt-dlp"`` / ``"aria2"``.
    name: str = "base"

    @abstractmethod
    def supports(self, item: MediaItem) -> bool:
        """Return True if this engine can handle the given item."""
        raise NotImplementedError

    @abstractmethod
    async def download(
        self,
        item: MediaItem,
        options: DownloadOptions,
        *,
        on_progress: Optional[EngineProgressCallback] = None,
    ) -> bool:
        """Download ``item`` per ``options``. Returns True on success.

        Engines must be safe to call from a worker thread (i.e. they
        should not block the event loop with sync I/O without first
        offloading via :func:`asyncio.to_thread`).
        """
        raise NotImplementedError
