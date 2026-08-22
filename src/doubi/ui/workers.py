"""Qt <-> asyncio bridge for the GUI download flow.

The QML/Widgets event loop runs on the main thread; the
:mod:`doubi.core.pipeline` is asyncio-native. We connect them via
:class:`qasync.QEventLoop` (set up in :mod:`doubi.ui.app`) and use
:class:`qasync.QTask` to run the async coroutine in that loop.

This module keeps all *async* logic out of the QWidget classes,
which is the standard pattern for PySide6 + asyncio apps. The
workers expose Qt signals (``started``, ``progress``, ``finished``,
``failed``) so QWidgets can subscribe to them with idiomatic
``connect()`` calls.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from ..core.models import DownloadOptions, MediaItem
from ..core.pipeline import DownloadPipeline, ProgressEvent

logger = logging.getLogger("doubi.ui.workers")


@dataclass
class DownloadTask:
    """A single download request held by the GUI."""

    url: str
    options: DownloadOptions
    pipeline: DownloadPipeline

    #: Qt will fill these in (slots) — they're just shape hints
    started: object = None
    progress: object = None
    finished: object = None
    failed: object = None


class DownloadWorker:
    """Wraps :meth:`DownloadPipeline.process_url` as a Qt-friendly coroutine.

    Usage::

        worker = DownloadWorker(url, options, pipeline)
        worker.finished.connect(on_done)
        worker.failed.connect(on_err)
        asyncio.create_task(worker.run())  # from the qasync event loop
    """

    # Qt signal placeholders; the real QSignal-like objects are
    # bound at runtime by the page that owns the worker (the page
    # creates a small QObject subclass to host the signals). We
    # use plain ``None`` here as a documentation hint.

    def __init__(self, url: str, options: DownloadOptions, pipeline: DownloadPipeline):
        self.url = url
        self.options = options
        self.pipeline = pipeline
        # Filled in by the page that creates this worker
        self.signals = None  # type: ignore[assignment]

    async def run(self) -> Optional[MediaItem]:
        """Run the pipeline; emit signals along the way."""
        # Caller is expected to have wired `self.signals` already
        assert self.signals is not None, "wire self.signals before calling run()"
        try:
            self.signals.started.emit(self.url)
            item = await self.pipeline.process_url(
                self.url, self.options, on_progress=self._on_progress,
            )
        except Exception as exc:
            logger.exception("download failed for %s", self.url)
            self.signals.failed.emit(self.url, str(exc))
            return None

        if item is None:
            self.signals.failed.emit(self.url, "no platform matched or parse failed")
            return None
        self.signals.finished.emit(self.url, item)
        return item

    def _on_progress(self, ev: ProgressEvent) -> None:
        self.signals.progress.emit(self.url, ev)


def _asyncio_run(coro) -> None:
    """Helper for CLI-style invocation (rarely used from the GUI)."""
    asyncio.run(coro)
