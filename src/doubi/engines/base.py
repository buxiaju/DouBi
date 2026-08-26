"""Engine abstraction.

An engine is a transport-layer adapter that knows how to fetch a
``MediaItem`` given a set of ``DownloadOptions`` and report progress.
The default engine is :class:`doubi.engines.yt_dlp.YtDlpEngine`. Future
engines (aria2 with rpc, native http, etc.) implement the same
interface and can be plugged in via the pipeline.
"""

from __future__ import annotations

import hashlib
import logging
import re
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..core.models import DownloadOptions, MediaItem

logger = logging.getLogger("doubi.engines")


_ILLEGAL_FS_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WHITESPACE = re.compile(r"\s+")
# Windows MAX_PATH is 260 *including* the null terminator. For a path
# like "<out_dir>\<basename>.<ext>" we reserve 80 chars for the
# directory + extension + separator. Basenames longer than the
# remainder are truncated and suffixed with a stable 8-char SHA1 so
# two different long titles still produce distinct filenames.
_MAX_BASENAME_BYTES = 170


def safe_basename_for_item(item: MediaItem, *, fallback: str = "video") -> str:
    """Filesystem-safe, length-bounded basename for any MediaItem.

    Sanitization steps:
      1. Replace all Windows-illegal characters with ``_``.
      2. Collapse whitespace runs into a single ``_``.
      3. Strip leading/trailing ``.`` and ``_`` (Windows disallows
         filenames that start with a dot, Explorer also hates trailing
         dots).
      4. Truncate basename so that when UTF-8 encoded it fits within
         :data:`_MAX_BASENAME_BYTES`, and append a deterministic
         ``_<sha1[:8]>`` tail so truncation never collides.
    """
    raw = item.output_template or (item.title or item.item_id) or fallback
    s = _ILLEGAL_FS_CHARS.sub("_", str(raw))
    s = _WHITESPACE.sub("_", s).strip("._")
    if not s:
        s = fallback

    encoded = s.encode("utf-8", errors="ignore")
    if len(encoded) <= _MAX_BASENAME_BYTES:
        return s

    # Truncate from the left in such a way that we don't split a
    # multi-byte UTF-8 sequence (decode will drop the half-char).
    tail_hash = hashlib.sha1(encoded).hexdigest()[:8]
    suffix_bytes = f"_{tail_hash}".encode()
    budget = _MAX_BASENAME_BYTES - len(suffix_bytes)
    truncated = encoded[:budget].decode("utf-8", errors="ignore")
    # Double check: an unlucky decode that grows above budget is OK
    # because _MAX_BASENAME_BYTES is 170 and MAX_PATH budget is 180.
    return truncated + "_" + tail_hash


def output_path_under(out_dir: Path, basename: str, ext: str) -> Path:
    """Build an output path, auto-truncating ``basename`` for MAX_PATH.

    On Windows ``CreateFileW`` with a long-path enabled prefix would
    support ~32767 chars, but the shell (Explorer) and many common
    tools (ffmpeg / N_m3u8DL-CLI) still fail above 260. We therefore
    enforce ``len(str(path)) <= 259`` and reapply the sha-suffix trick
    when the basename is too long to fit next to ``out_dir``.

    ``ext`` is expected without a leading dot; empty string is allowed.

    If ``out_dir`` itself is already so long that no basename can fit
    inside 259, we still produce a file under ``out_dir`` — callers are
    expected to pick reasonable output roots (that is the existing
    responsibility of ``DownloadOptions.out_dir`` / ``resolve_item_dir``).
    """
    ext_norm = ("." + ext.lower().lstrip(".")) if ext else ""
    candidate = out_dir / f"{basename}{ext_norm}"
    path_str = str(candidate)
    if len(path_str) <= 259:
        return candidate

    # Basename too long for dir. Compute a character budget by subtracting
    # the *actual* overhead (out_dir + separator + ext) from 259. Use a
    # deterministic SHA1 tail appended to the truncated basename so two
    # distinct long basenames that otherwise happen to share the
    # truncated prefix still produce different files.
    overhead = len(str(out_dir)) + 1 + len(ext_norm)   # dir + sep + ext
    # Reserve 9 chars for "_" + 8 hex of sha1.
    target_budget = 259 - overhead - 9
    min_basename_len = 12
    budget = max(min_basename_len, target_budget)
    hashed = hashlib.sha1(basename.encode("utf-8", errors="ignore")).hexdigest()[:8]
    # First pass: straightforward truncation + sha tail
    truncated_base = f"{basename[:budget]}_{hashed}"
    candidate = out_dir / f"{truncated_base}{ext_norm}"
    if len(str(candidate)) <= 259:
        return candidate

    # Tight loop: either ``out_dir`` itself is already close to 259, or
    # ``basename`` contains multi-unit UTF-16 chars whose Python len()
    # != the path-API char count. Shave one char at a time unconditionally
    # until the path fits; if we blow past min_basename_len we still keep
    # the full 8-char hash tail, so the file remains uniquely named. If
    # even that fails we fall back to the bare 8-char hash (absolute
    # minimum of 8 + sep + ext fits anywhere where out_dir fits).
    stem = truncated_base
    while len(str(out_dir / f"{stem}{ext_norm}")) > 259 and len(stem) > 8:
        stem = stem[:-1]
    candidate = out_dir / f"{stem}{ext_norm}"
    if len(str(candidate)) <= 259:
        return candidate
    # Last resort: use only the hash (8 hex chars). If even this doesn't
    # fit the caller gave us an out_dir that is itself already >= 251
    # chars; we still return the constructed path and let the engine
    # raise a clear "cannot create file" error at mkdir/write time.
    return out_dir / f"{hashed}{ext_norm}"


def cancel_flag_polling(flag) -> bool:
    """Read a :class:`~doubi.ui.task_manager._StopFlag` or compatible.

    Defensive: handles ``flag.cancelled``, ``flag.stopped``, or a
    callable. Any error returns ``False`` (do not spuriously cancel a
    valid download because our introspection misfired).
    """
    if flag is None:
        return False
    stopped = getattr(flag, "cancelled", None)
    if isinstance(stopped, bool):
        return stopped
    stopped = getattr(flag, "stopped", None)
    if isinstance(stopped, bool):
        return stopped
    if callable(getattr(flag, "__call__", None)):
        try:
            return bool(flag())
        except Exception:
            return False
    return False


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
