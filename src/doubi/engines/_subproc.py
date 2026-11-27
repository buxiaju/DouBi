"""Subprocess helpers shared by the engine layer.

Provides:
* ``run_supervised_subprocess`` — wraps a long-running subprocess with:
  - cancellation via a ``cancel_check`` pollable,
  - a watchdog timer that kills the process if it emits no stdout for
    too long (handles frozen ffmpeg / N_m3u8DL-CLI),
  - robust \r/\n-aware line splitting at the caller via ``on_chunk``
    instead of default asyncio line-iterator.
* ``find_bundled_ffmpeg`` — locates the ffmpeg shipped with the app.

The cancellation model is intentionally aggressive: the
``cancel_check`` flag is checked *every* time we read a chunk; if the
flag ever fires we first try graceful ``terminate()`` and then
``kill()`` a second later. This prevents orphaned grandchildren when
the engine layer is cancelled from the GUI.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess
import sys
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Optional

logger = logging.getLogger("doubi.engines.subproc")

# Seconds without any stdout/stderr output before we consider the
# subprocess "frozen" and force-kill it. HLS downloads often pause for
# a few seconds between 2835-segment chunks, so 3 minutes is a fairly
# safe upper bound: 180s without *any* output is definitely a hang.
DEFAULT_OUTPUT_WATCHDOG_SECONDS = 180.0

# 打包后的 GUI 是 windowed（无控制台），而 N_m3u8DL-CLI / ffmpeg 都是
# 控制台程序——不设这个标志，Windows 会为每个子进程分配一个新控制台，
# 表现为下载时黑色终端窗口反复弹出。CREATE_NO_WINDOW (0x08000000) 压制
# 分配，子进程 stdout/stderr 照常经管道回传，进度解析不受影响。
# 仅 Windows 有此常量；显式传了 creationflags 的调用方优先于默认注入。
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def find_bundled_ffmpeg() -> Optional[str]:
    """Locate the ffmpeg binary that ships with DouBi.

    All three engines (m3u8, yt_dlp, nm3u8dl) need ffmpeg to mux, and
    all three used to fall back to ``imageio_ffmpeg``. That package is
    83.6 MB of bundle for a single executable, so the release build
    ships ``tools/nm3u8dl/ffmpeg.exe`` (10.91 MB) instead and excludes
    ``imageio_ffmpeg`` from PyInstaller. This helper is the shared
    lookup so the path logic lives in exactly one place.

    Search order:

    1. ``sys._MEIPASS/tools/nm3u8dl`` — the frozen bundle. This must
       come first: in a frozen app ``Path.cwd()`` is wherever the user
       launched the .exe from (often ``C:\\Windows\\System32`` when
       started from a shortcut), so a cwd-relative probe would miss.
    2. ``tools/nm3u8dl`` relative to cwd — the dev checkout layout.
    3. ``tools/nm3u8dl`` relative to the repo root inferred from
       ``__file__`` — dev runs launched from another directory.

    Returns ``None`` when nothing is found; callers then fall back to
    ``shutil.which("ffmpeg")`` and finally degrade gracefully.
    """
    name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    roots: list[Path] = []

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(meipass) / "tools" / "nm3u8dl")
    roots.append(Path.cwd() / "tools" / "nm3u8dl")
    # engines/_subproc.py -> engines -> doubi -> src -> repo root
    roots.append(Path(__file__).resolve().parents[3] / "tools" / "nm3u8dl")

    for root in roots:
        candidate = root / name
        try:
            if candidate.is_file():
                return str(candidate)
        except OSError:
            continue
    return None


class SubprocessTimeout(Exception):
    """Raised by ``run_supervised_subprocess`` when the watchdog fired."""


def make_dir_activity_keepalive(*roots: Path) -> Callable[[], bool]:
    """Build a watchdog keepalive that watches *roots* for file changes.

    The returned callable snapshots ``(file count, total bytes)`` under
    every root (recursive) and reports ``True`` when the snapshot
    changed since the previous call. Typical wiring: pass the engine's
    ``out_dir`` so a subprocess that went stdout-silent during its
    merge/faststart phase still counts as alive while the merged file
    keeps growing. When the process is genuinely frozen nothing changes
    on disk, the probe reports ``False`` and the watchdog kills it one
    tick later — bounded staleness, no unkillable hangs.

    Notes:
    * The first call only *seeds* the baseline and returns ``False``
      (there is no prior snapshot to compare against).
    * A file that vanished mid-scan (N_m3u8DL-CLI rotates its
      ``Part_*/`` buckets) is skipped, not fatal.
    * Scan cost is one ``rglob`` per consult; consults happen at most
      once per second and only while stdout is silent past the
      watchdog threshold, so this is negligible for 10k-segment dirs.
    """
    state: dict[str, Optional[tuple[int, int]]] = {"sig": None}

    def _snapshot() -> tuple[int, int]:
        n_files = 0
        total_bytes = 0
        for root in roots:
            try:
                for path in root.rglob("*"):
                    try:
                        if path.is_file():
                            n_files += 1
                            total_bytes += path.stat().st_size
                    except OSError:
                        continue
            except OSError:
                continue
        return n_files, total_bytes

    def keepalive() -> bool:
        sig = _snapshot()
        prev = state["sig"]
        state["sig"] = sig
        return prev is not None and sig != prev

    return keepalive


async def run_supervised_subprocess(
    args: Sequence[str],
    *,
    on_chunk: Optional[Callable[[bytes], None | Awaitable[None]]] = None,
    cancel_check=None,
    env: Optional[dict[str, str]] = None,
    stdout_limit: int = 1024 * 1024,
    chunk_size: int = 4096,
    watchdog_seconds: float = DEFAULT_OUTPUT_WATCHDOG_SECONDS,
    keepalive: Optional[Callable[[], bool | Awaitable[bool]]] = None,
    **kwargs,
) -> tuple[int, bytes]:
    """Run *args* as a supervised subprocess.

    Parameters
    ----------
    args:
        Executable + argv list (passed directly to
        ``asyncio.create_subprocess_exec``).
    on_chunk:
        Optional callback invoked with every raw chunk read from
        stdout+stderr (caller is responsible for decoding and line
        splitting). May return a coroutine.
    cancel_check:
        Pollable used by TaskManager (``_StopFlag`` or any object with
        a ``cancelled`` / ``stopped`` boolean attribute). When it
        becomes truthy, we terminate the subprocess immediately.
    env:
        Passed verbatim to ``create_subprocess_exec``.
    stdout_limit:
        ``limit`` arg for ``StreamReader`` — raise if you expect long
        ``\r``-style progress lines.
    chunk_size:
        Bytes to ask from each ``stdout.read()`` call.
    watchdog_seconds:
        Kill the process if no output arrives for this long. Set to
        ``0`` or ``<= 0`` to disable (not recommended).
    keepalive:
        Optional liveness probe consulted **only** when stdout has been
        silent past ``watchdog_seconds``. Returning truthy resets the
        watchdog timer instead of killing the process — this is how the
        merge/faststart phase of N_m3u8DL-CLI and ffmpeg survives: both
        legitimately go quiet for minutes while writing the output
        file, and killing them there caused the "downloaded to 100%
        then started over" bug (the pipeline retried from scratch).
        Use :func:`make_dir_activity_keepalive` to build one from
        output directories. If the callable raises, treat as silent.

    Returns
    -------
    (returncode, captured_remainder_bytes)
        ``captured_remainder_bytes`` is everything that didn't fit
        through ``on_chunk`` (last partial buffer on EOF). Mainly
        useful for tests; real engines use ``on_chunk`` for streaming.

    Raises
    ------
    SubprocessTimeout
        When the watchdog fired.
    """
    # Force stdout+stderr into a single combined pipe. The engines
    # already use this pattern and it keeps the watchdog trivially
    # correct because every byte of output counts.
    kwargs.pop("stdout", None)
    kwargs.pop("stderr", None)

    env_final = env if env is not None else dict(os.environ)

    # GUI 窗口化后控制台子进程会弹黑框：默认注入 CREATE_NO_WINDOW，
    # 调用方显式传 creationflags 时尊重调用方（不覆盖）。
    if sys.platform == "win32" and "creationflags" not in kwargs:
        kwargs["creationflags"] = _NO_WINDOW

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env_final,
        limit=stdout_limit,
        **kwargs,
    )
    assert proc.stdout is not None, "PIPE was not allocated"

    cancelled: bool = False
    watchdog_ms = max(0.0, float(watchdog_seconds))
    captured_tail = bytearray()

    def _is_cancelled() -> bool:
        if cancelled:
            return True
        if cancel_check is None:
            return False
        stopped = getattr(cancel_check, "cancelled", None)
        if isinstance(stopped, bool):
            return stopped
        stopped = getattr(cancel_check, "stopped", None)
        if isinstance(stopped, bool):
            return stopped
        call = getattr(cancel_check, "__call__", None)
        if callable(call):
            try:
                return bool(cancel_check())
            except Exception:
                return False
        return False

    async def _force_terminate(reason: str) -> None:
        """Send terminate, wait briefly, then kill."""
        nonlocal cancelled
        cancelled = True
        logger.warning("[subproc] %s for pid %s (%s)", reason, proc.pid,
                       args[0] if args else "<none>")
        try:
            if sys.platform == "win32":
                # Windows has no SIGTERM; terminate() maps to
                # TerminateProcess which is already a hard kill. Try it
                # once and skip the sleep (it's pointless).
                proc.terminate()
            else:
                proc.terminate()
                try:
                    async with asyncio.timeout(1.2):
                        await proc.wait()
                        return
                except TimeoutError:
                    pass
                proc.kill()
        except (ProcessLookupError, OSError):
            pass
        try:
            async with asyncio.timeout(1.5):
                await proc.wait()
        except (TimeoutError, OSError):
            pass

    last_output_at = asyncio.get_event_loop().time()

    async def _reader():
        nonlocal last_output_at
        while True:
            if _is_cancelled():
                return
            try:
                # Use a short-ish timeout so the cancel_check and
                # watchdog both stay responsive even if the subprocess
                # has stopped writing but hasn't actually exited.
                chunk = await asyncio.wait_for(
                    proc.stdout.read(chunk_size),
                    timeout=1.0 if watchdog_ms > 0 else None,
                )
            except asyncio.TimeoutError:
                # No data came in this 1s window — check watchdog / cancel.
                now = asyncio.get_event_loop().time()
                if watchdog_ms > 0 and (now - last_output_at) > watchdog_ms:
                    # Last chance before the kill: the process may be in
                    # a legitimately silent but productive phase (binary
                    # merge / faststart rewrite / moov relocation). Any
                    # evidence of file-system progress resets the timer.
                    if keepalive is not None:
                        try:
                            alive = keepalive()
                            if isinstance(alive, Awaitable):
                                alive = await alive
                            if alive:
                                last_output_at = now
                                continue
                        except Exception:
                            # A broken probe must not wedge supervision:
                            # treat like "no evidence of life".
                            logger.exception("[subproc] keepalive raised, treating as silent")
                    await _force_terminate(
                        f"watchdog: no output for {watchdog_ms:.0f}s"
                    )
                    raise SubprocessTimeout(
                        f"subprocess frozen: no output for {watchdog_ms:.0f}s"
                    )
                continue

            if not chunk:
                # EOF — wait for actual exit on the next gather().
                return

            last_output_at = asyncio.get_event_loop().time()
            captured_tail.extend(chunk)
            if on_chunk is not None:
                try:
                    result = on_chunk(bytes(chunk))
                    if isinstance(result, Awaitable):
                        await result
                except Exception:
                    # A buggy on_chunk must not kill the subprocess
                    # supervision; swallow and keep pumping.
                    logger.exception("[subproc] on_chunk raised, ignoring")

    done_pending = proc.wait()
    try:
        # Run both coroutines concurrently. If the reader raises
        # (watchdog / cancel) we re-raise after giving terminate time
        # to clean up the process.
        results = await asyncio.gather(done_pending, _reader(),
                                       return_exceptions=False)
        rc = results[0]
        return rc, bytes(captured_tail)
    except asyncio.CancelledError:
        await _force_terminate("cancelled by task")
        raise
    except SubprocessTimeout:
        # Already terminated inside _reader; re-raise.
        try:
            await proc.wait()
        except Exception:
            pass
        raise
    except Exception:
        await _force_terminate("reader exception")
        raise
    finally:
        # Parachute: make absolutely sure the child isn't left behind
        # if our caller's finally-clause re-raises after we've exited.
        if proc.returncode is None:
            try:
                await _force_terminate("finally parachute")
            except Exception:
                pass


# Windows-compatible: send ctrl-c would need CREATE_NEW_PROCESS_GROUP
# etc.; we just rely on terminate() above which does the right thing on
# both platforms. The symbols are exported so callers can introspect.
SUPERVISOR_USES_NATIVE_TERMINATE = sys.platform == "win32"
try:
    SIGTERM = signal.SIGTERM
except AttributeError:  # Windows
    SIGTERM = None  # type: ignore[assignment]
