"""N_m3u8DL-CLI engine — wraps the native N_m3u8DL-CLI executable.

N_m3u8DL-CLI (https://github.com/nilaoda/N_m3u8DL-CLI) is a
Windows-native HLS downloader written in C#.  It handles AES-128,
ChaCha20, master playlists, live streams, and MPD out of the box.

This engine shells out to the CLI binary, parses its progress lines,
and reports them through the :class:`EngineProgress` interface.

The binary is expected at ``tools/nm3u8dl/N_m3u8DL-CLI_v3.0.2.exe``
relative to the project root.  If it's not found the engine reports
:meth:`is_available` → ``False`` and ``supports()`` still returns
True (so the pipeline can show a clear error instead of silently
falling back to yt-dlp).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Optional

from ..core.models import DownloadOptions, MediaItem
from ..core.storage.file_layout import resolve_item_dir
from ._subproc import (
    SubprocessTimeout,
    find_bundled_ffmpeg,
    run_supervised_subprocess,
)
from .base import (
    Engine,
    EngineProgress,
    EngineProgressCallback,
    output_path_under,
    safe_basename_for_item,
)

logger = logging.getLogger("doubi.engines.nm3u8dl")


def _find_cli() -> Optional[str]:
    """Locate N_m3u8DL-CLI_v3.0.2.exe.

    Search order:
    1. ``tools/nm3u8dl/`` relative to the current working directory
       (matches the project layout).
    2. ``tools/nm3u8dl/`` relative to the script's parent (for
       frozen builds).
    3. System PATH.
    """
    candidates: list[Path] = []

    cwd_candidates = Path.cwd() / "tools" / "nm3u8dl"
    candidates.append(cwd_candidates)

    script_dir = Path(__file__).resolve().parent.parent.parent
    candidates.append(script_dir / "tools" / "nm3u8dl")

    for d in candidates:
        for name in ("N_m3u8DL-CLI_v3.0.2.exe", "N_m3u8DL-CLI.exe"):
            p = d / name
            if p.exists():
                return str(p)

    on_path = shutil.which("N_m3u8DL-CLI_v3.0.2") or shutil.which("N_m3u8DL-CLI")
    if on_path:
        return on_path

    return None


def _find_ffmpeg() -> Optional[str]:
    """Locate ffmpeg — prefer the one sitting next to N_m3u8DL-CLI.

    N_m3u8DL-CLI ships its own ffmpeg build, and that copy is the one
    the release bundle carries (see ``scripts/build_exe.py``), so it is
    tried before PATH. ``find_bundled_ffmpeg`` also covers the frozen
    ``sys._MEIPASS`` layout, which ``_find_cli`` cannot reach.
    """
    cli = _find_cli()
    if cli:
        bundled = Path(cli).parent / "ffmpeg.exe"
        if bundled.exists():
            return str(bundled)

    shipped = find_bundled_ffmpeg()
    if shipped:
        return shipped

    on_path = shutil.which("ffmpeg")
    if on_path:
        return on_path

    return None


# Progress line regex — N_m3u8DL-CLI outputs lines like:
#   [#12/150] 1.23MB / 12.34MB | 1.23MB/s | 00:10/01:45
#   [#150/150] 12.34MB / 12.34MB | completed | 00:45/00:45
#   [INFO] download completed
#   [ERROR] something went wrong
_PROGRESS_RE = re.compile(r"\[#(\d+)/(\d+)\]")
_COMPLETE_RE = re.compile(r"completed", re.IGNORECASE)
_ERROR_RE = re.compile(r"\[ERROR\]", re.IGNORECASE)
# N_m3u8DL-CLI v3.0.2 输出：``总分片：9425, 已选择分片：9425``。
# 旧版用 ``[#150/150]`` 格式，v3.0.2 改成了「时间戳 + 速度」的清爽格式
# ——所以这里正则匹配永远命中不了，watchdog 才是真进度源。
_TOTAL_SEG_RE = re.compile(r"总分片[：:]\s*(\d+)")


def _find_meta_json(out_dir: Path) -> Optional[Path]:
    """Locate N_m3u8DL-CLI's ``meta.json`` anywhere under ``out_dir``.

    N_m3u8DL-CLI writes ``meta.json`` *inside* the directory it
    actually streamed segments to. Because the engine passes
    ``--saveName`` as a *path* (it includes the per-item dir the
    pipeline already computed for ``final_output``), N_m3u8DL-CLI
    creates an extra subdirectory layer that our ``out_dir`` doesn't
    directly contain. The real data lives one or two levels deeper:

        out_dir/                                  ← what we get
        └── <saveName_tail>/                     ← N_m3u8DL-CLI adds this
            ├── meta.json
            └── Part_0/0000.ts, 0001.ts, ...

    We scan up to 3 levels deep under ``out_dir`` for the meta.json
    that N_m3u8DL-CLI actually wrote. Beyond that no layout we've
    seen (live streams or VOD) puts meta.json; the 3-level cap keeps
    the scan bounded on weird filesystems.

    Returns the first meta.json path found, or None if none exists.
    """
    return _find_first_named(out_dir, "meta.json", max_depth=3)


def _count_completed_segments(out_dir: Path) -> int:
    """Count downloaded .ts files anywhere under ``out_dir``.

    Same recursion as :func:`_find_meta_json`: N_m3u8DL-CLI puts
    segments under ``out_dir/<saveName_tail>/Part_*/`` and the count
    has to walk that path. We do this in a single ``scandir`` pass
    per directory level rather than ``Path.rglob`` so we don't stat
    every file — at 9425 segments on Windows, ``rglob`` would issue
    ~10000 stat calls; this version does a few hundred and the rest
    are pure string ``endswith`` checks.

    Returns 0 if ``out_dir`` is missing / unreadable / has no
    segments yet.
    """
    return _count_files_named(out_dir, ".ts", max_depth=3)


def _find_first_named(root: Path, name: str, *, max_depth: int) -> Optional[Path]:
    """Return the first descendant ``root/<...>/<name>`` found by BFS.

    Bounded by ``max_depth`` levels beyond ``root`` — when 0, only
    ``root/<name>`` counts. Returns ``None`` if no match.

    BFS (rather than recursive descent) keeps the call stack flat:
    a 3-level search is 3 explicit loops, not 27 indentation levels,
    and never triggers Python's recursion limit. We tolerate
    individual subdirectory unreadability by catching ``OSError`` and
    just skipping the entry — N_m3u8DL-CLI rotates Part_*/ dirs mid-
    download so transient ``FileNotFoundError`` is the norm.
    """
    current: list[Path] = [root]
    for _ in range(max_depth + 1):
        next_level: list[Path] = []
        for directory in current:
            try:
                with os.scandir(directory) as it:
                    for entry in it:
                        if entry.name == name:
                            return Path(entry.path)
                        try:
                            is_dir = entry.is_dir()
                        except OSError:
                            continue
                        if is_dir:
                            next_level.append(Path(entry.path))
            except OSError:
                continue
        if not next_level:
            return None
        current = next_level
    return None


def _count_files_named(root: Path, suffix: str, *, max_depth: int) -> int:
    """Count files ending with ``suffix`` under ``root`` within ``max_depth`` levels.

    Same BFS shape as :func:`_find_first_named`. Hidden entries
    (``.tmp``, ``.part``) are skipped because they aren't real
    completed segments; this matches the watcher's contract that the
    bar only moves on real, written segments.
    """
    count = 0
    current: list[Path] = [root]
    for _ in range(max_depth + 1):
        next_level: list[Path] = []
        for directory in current:
            try:
                with os.scandir(directory) as it:
                    for entry in it:
                        if (
                            entry.name.endswith(suffix)
                            and not entry.name.startswith(".")
                        ):
                            count += 1
                            continue
                        try:
                            is_dir = entry.is_dir()
                        except OSError:
                            continue
                        if is_dir:
                            next_level.append(Path(entry.path))
            except OSError:
                continue
        if not next_level:
            break
        current = next_level
    return count


def _discover_total_segments(out_dir: Path, save_name: Path) -> int:
    """Try to read the total segment count from N_m3u8DL-CLI's ``meta.json``.

    N_m3u8DL-CLI writes ``{real_workdir}/meta.json`` shortly after
    parse completes; ``real_workdir`` is *not* the ``out_dir`` we hand
    to ``--workDir`` because the engine passes a path-bearing
    ``--saveName`` (see :func:`_find_meta_json` for the full picture).
    We therefore search a few levels deep under ``out_dir`` for the
    file, instead of assuming a fixed layout.

    Returns 0 if no parseable meta.json is found yet — the watchdog
    will retry. 0 is the right failure mode here: ``count=0`` would
    mean a live stream with no known denominator, and the watchdog
    explicitly skips emit when ``total <= 0``.
    """
    meta_path = _find_meta_json(out_dir)
    if meta_path is None:
        return 0
    try:
        with open(meta_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return 0
    info = data.get("m3u8Info") if isinstance(data, dict) else None
    if not isinstance(info, dict):
        return 0
    count = info.get("count")
    try:
        return int(count) if count else 0
    except (TypeError, ValueError):
        return 0


def _count_completed_segments(out_dir: Path) -> int:
    """Count downloaded .ts files anywhere under ``out_dir``.

    Same recursion as :func:`_find_meta_json`: N_m3u8DL-CLI puts
    segments under ``out_dir/<saveName_tail>/Part_*/`` and the count
    has to walk that path. We do this in a single ``scandir`` pass
    per directory level rather than ``Path.rglob`` so we don't stat
    every file — at 9425 segments on Windows, ``rglob`` would issue
    ~10000 stat calls; this version does a few hundred and the rest
    are pure string ``endswith`` checks.

    Returns 0 if ``out_dir`` is missing / unreadable / has no
    segments yet.
    """
    count = 0
    try:
        with os.scandir(out_dir) as it:
            for entry in it:
                if entry.name.endswith(".ts") and not entry.name.startswith("."):
                    count += 1
                    continue
                try:
                    is_dir = entry.is_dir()
                except OSError:
                    continue
                if not is_dir:
                    continue
                # Subdir of out_dir — N_m3u8DL-CLI's data dir.
                try:
                    with os.scandir(entry.path) as sub:
                        for sub_entry in sub:
                            if (
                                sub_entry.name.endswith(".ts")
                                and not sub_entry.name.startswith(".")
                            ):
                                count += 1
                                continue
                            try:
                                sub_is_dir = sub_entry.is_dir()
                            except OSError:
                                continue
                            if not sub_is_dir:
                                continue
                            # Inside sub: either a Part_*/ bucket of
                            # .ts files, or yet another subdir layer
                            # (N_m3u8DL-CLI v3.0.2 wraps the
                            # user-supplied --saveName as a subdir).
                            try:
                                with os.scandir(sub_entry.path) as sub2:
                                    for sub2_entry in sub2:
                                        if (
                                            sub2_entry.name.endswith(".ts")
                                            and not sub2_entry.name.startswith(".")
                                        ):
                                            count += 1
                                            continue
                                        try:
                                            sub2_is_dir = sub2_entry.is_dir()
                                        except OSError:
                                            continue
                                        if not sub2_is_dir:
                                            continue
                                        # Part_*/ bucket — segments live
                                        # here, three levels beyond out_dir.
                                        try:
                                            with os.scandir(sub2_entry.path) as sub3:
                                                for sub3_entry in sub3:
                                                    if (
                                                        sub3_entry.name.endswith(".ts")
                                                        and not sub3_entry.name.startswith(".")
                                                    ):
                                                        count += 1
                                        except OSError:
                                            # The Part_*/ directory vanished
                                            # mid-scan (N_m3u8DL-CLI rotates
                                            # during long downloads). Skip;
                                            # next tick will catch the new state.
                                            continue
                            except OSError:
                                continue
                except OSError:
                    continue
    except OSError:
        # out_dir itself not yet created / accessible — watchdog will retry.
        pass
    return count


class Nm3u8dlEngine(Engine):
    """HLS/m3u8 engine using the N_m3u8DL-CLI native binary.

    This is the preferred engine for generic sniffed m3u8 URLs
    because it handles all HLS edge cases (AES-128, ChaCha20,
    master playlists, etc.) natively.

    ``supports()`` returns True when:
    * ``item.extra["is_hls"]`` is True (set by GenericAdapter), OR
    * The source_url contains ``.m3u8`` / ``.m3u``.
    """

    name = "nm3u8dl"

    def __init__(self, cli_path: Optional[str] = None):
        self._cli = cli_path or _find_cli()
        self._ffmpeg = _find_ffmpeg()
        if self._cli:
            logger.info("[nm3u8dl] using CLI: %s", self._cli)
        else:
            logger.warning("[nm3u8dl] N_m3u8DL-CLI binary not found")
        if self._ffmpeg:
            logger.info("[nm3u8dl] using ffmpeg: %s", self._ffmpeg)

    @property
    def is_available(self) -> bool:
        return self._cli is not None

    def supports(self, item: MediaItem) -> bool:
        if item.extra.get("is_hls"):
            return True
        url = item.source_url or ""
        lower = url.lower()
        return ".m3u8" in lower or ".m3u" in lower

    async def download(
        self,
        item: MediaItem,
        options: DownloadOptions,
        *,
        on_progress: Optional[EngineProgressCallback] = None,
    ) -> bool:
        if not self._cli:
            err_msg = "N_m3u8DL-CLI binary not found. Please download N_m3u8DL-CLI_v3.0.2 to tools/nm3u8dl/"
            logger.error(err_msg)
            if on_progress:
                on_progress(EngineProgress(
                    fraction=0.0,
                    message=f"nm3u8dl error: {err_msg}",
                ))
            return False

        out_dir = resolve_item_dir(item, options)
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            err_msg = f"无法创建输出目录 {out_dir}: {exc}"
            logger.error("[nm3u8dl] %s", err_msg)
            if on_progress:
                on_progress(EngineProgress(fraction=0.0, message=err_msg))
            return False

        basename = safe_basename_for_item(item)
        raw_ext = item.extra.get("sniff_ext") or self._guess_ext(item.source_url) or "mp4"
        ext = self._sanitize_output_ext(raw_ext)
        final_output = output_path_under(out_dir, basename, ext)
        save_name = final_output.with_suffix("")  # N_m3u8DL-CLI appends the extension itself

        cmd = [
            self._cli,
            item.source_url,
            "--workDir", str(out_dir),
            "--saveName", str(save_name),
            "--enableMuxFastStart",
            "--enableBinaryMerge",
            "--enableDelAfterDone",
            "--disableDateInfo",
            "--noProxy",
        ]

        if options.proxy:
            cmd += ["--proxyAddress", options.proxy]

        ffmpeg_dir = str(Path(self._ffmpeg).parent) if self._ffmpeg else None
        env = dict(os.environ)
        if ffmpeg_dir:
            env["PATH"] = ffmpeg_dir + ";" + env.get("PATH", "")

        logger.info("[nm3u8dl] downloading: %s → %s (ext=%s)", item.source_url, save_name, ext)

        # Fire first progress tick so UI leaves "准备中" state.
        if on_progress:
            on_progress(EngineProgress(fraction=0.0, message="m3u8 解析中..."))

        last_frac = -1.0
        fatal_error = ""
        parse_buf = bytearray()
        # Shared mutable bag — see _TOTAL_SEG_RE for the source line.
        # Both the stdout parser and the watchdog write here; whichever
        # discovers the count first wins. A plain ``int`` local would not
        # work because the lambda captures by reference but rebinds
        # on assignment, so the watchdog would never see the value.
        total_segments_box: dict[str, int] = {"count": 0}

        def _parse_and_emit(decoded: str) -> None:
            nonlocal last_frac, fatal_error
            if not decoded:
                return
            if _ERROR_RE.search(decoded):
                fatal_error = decoded
                logger.error("[nm3u8dl] error: %s", decoded)
            if _COMPLETE_RE.search(decoded) and on_progress:
                on_progress(EngineProgress(fraction=1.0, message="m3u8 下载完成"))
            # ``总分片：9425, 已选择分片：9425`` is the v3.0.2 way of
            # telling us the denominator. Capture it so the watchdog
            # doesn't have to wait for meta.json to appear on disk.
            m_total = _TOTAL_SEG_RE.search(decoded)
            if m_total and not total_segments_box["count"]:
                total_segments_box["count"] = int(m_total.group(1))
            if "总分片" in decoded and on_progress:
                on_progress(EngineProgress(
                    fraction=0.0, message="m3u8 解析完成，准备下载..."
                ))
            if "开始下载" in decoded and on_progress:
                on_progress(EngineProgress(
                    fraction=0.0, message="m3u8 下载中 0%"
                ))
            m = _PROGRESS_RE.search(decoded)
            if m and on_progress:
                current = int(m.group(1))
                total = int(m.group(2))
                if total > 0:
                    frac = current / total
                    pct = int(frac * 100)
                    if pct != int(last_frac * 100):
                        last_frac = frac
                        on_progress(EngineProgress(
                            fraction=frac,
                            message=f"m3u8 下载中 {pct}%",
                        ))

        def _on_chunk(chunk: bytes) -> None:
            """Chunk callback splits on \r and \n regardless of platform."""
            parse_buf.extend(chunk)
            while True:
                cr = parse_buf.find(b"\r")
                lf = parse_buf.find(b"\n")
                if cr == -1 and lf == -1:
                    break
                sep_idx = cr if lf == -1 or (cr != -1 and cr < lf) else lf
                line_bytes = bytes(parse_buf[:sep_idx])
                del parse_buf[:sep_idx + 1]
                if sep_idx == cr and parse_buf and parse_buf[0:1] == b"\n":
                    del parse_buf[:1]
                _parse_and_emit(line_bytes.decode("utf-8", errors="replace").strip())

        cancel_flag = getattr(options, "cancel_check", None)

        # ------------------------------------------------------------------
        # Filesystem watchdog: N_m3u8DL-CLI v3.0.2 dropped the
        # ``[#current/total]`` progress format, so the stdout parser
        # above can only flip us from "准备中" to "下载中" — it has no
        # numbers to report. To get an actually-moving bar we sample
        # the output directory on a 1-second tick: count ``.ts`` files
        # under out_dir (and any ``Part_*/`` subdirs N_m3u8DL-CLI
        # creates for chunked downloads) and divide by the total
        # segment count we discovered from the ``总分片：N`` line.
        #
        # This is decoupled from stdout buffering / N_m3u8DL-CLI version
        # — if the binary ever changes its log format again, the
        # watchdog keeps working because it only depends on the file
        # layout, which the binary's stable contract.
        # ------------------------------------------------------------------
        watchdog_stop = asyncio.Event()

        async def _watchdog() -> None:
            last_pct = -1
            # 1 Hz is the sweet spot on Windows: listdir is ~30-50 ms
            # for 9425 segments, so a 1 s tick keeps the bar smooth
            # without burning a CPU on tight loops. Don't go below 500
            # ms without measuring first.
            while not watchdog_stop.is_set():
                try:
                    await asyncio.wait_for(watchdog_stop.wait(), timeout=1.0)
                    break  # event set -> exit
                except asyncio.TimeoutError:
                    pass
                # Cancel propagates fastest this way; the user already
                # pressed pause/cancel and we should stop moving the bar.
                if cancel_flag is not None and getattr(cancel_flag, "stopped", False):
                    return
                if not total_segments_box["count"]:
                    discovered = _discover_total_segments(out_dir, save_name)
                    if discovered:
                        total_segments_box["count"] = discovered
                total = total_segments_box["count"]
                if total <= 0:
                    # No denominator yet — keep waiting for the parse
                    # line / meta.json. Don't emit 0% here, the stdout
                    # parser already did that on "开始下载".
                    continue
                done = _count_completed_segments(out_dir)
                # Cap at 1.0: a stray .ts that survived ``--enableDelAfterDone``
                # (e.g. on error paths) shouldn't push the bar past 100%.
                frac = min(1.0, done / total)
                pct = int(frac * 100)
                if pct == last_pct:
                    continue
                last_pct = pct
                if on_progress:
                    try:
                        on_progress(EngineProgress(
                            fraction=frac,
                            # Message is intentionally free of any ``N%``
                            # — the percentage already lives in
                            # ``EngineProgress.fraction`` and the UI
                            # renders it as a separate column. Including
                            # it here too would print ``60% m3u8 下载中
                            # 60%`` in the message column.
                            message="m3u8 下载中",
                        ))
                    except Exception:
                        # A buggy on_progress must not crash the
                        # watchdog — the stdout parser is still alive.
                        logger.exception("[nm3u8dl] watchdog on_progress raised")

        watchdog_task = asyncio.create_task(_watchdog())

        try:
            rc, _ = await run_supervised_subprocess(
                cmd,
                on_chunk=_on_chunk,
                cancel_check=cancel_flag,
                env=env,
                stdout_limit=1024 * 1024,
                chunk_size=4096,
            )
        except SubprocessTimeout as e:
            rc = -1
            fatal_error = str(e)
        except asyncio.CancelledError:
            # Propagate up; supervisor already killed the subprocess.
            watchdog_stop.set()
            watchdog_task.cancel()
            try:
                await watchdog_task
            except (asyncio.CancelledError, Exception):
                pass
            raise
        finally:
            # Normal completion + error paths: stop the watchdog. We
            # use an event (not cancel) so the coroutine can drain its
            # last tick cleanly instead of raising CancelledError into
            # an in-flight on_progress call.
            watchdog_stop.set()
            if not watchdog_task.done():
                try:
                    await asyncio.wait_for(watchdog_task, timeout=2.0)
                except asyncio.TimeoutError:
                    watchdog_task.cancel()
                    try:
                        await watchdog_task
                    except (asyncio.CancelledError, Exception):
                        pass
                except (asyncio.CancelledError, Exception):
                    pass

        # Drain whatever remained in the parse buffer (trailing line
        # with no terminator on EOF — unlikely here but cheap).
        if parse_buf:
            _parse_and_emit(bytes(parse_buf).decode("utf-8", errors="replace").strip())

        output_path = final_output
        if rc != 0:
            err_msg = fatal_error or f"N_m3u8DL-CLI exited with code {rc}"
            logger.error("[nm3u8dl] failed (rc=%d): %s", rc, err_msg)
            if on_progress:
                on_progress(EngineProgress(
                    fraction=0.0,
                    message=f"nm3u8dl error: {err_msg}",
                ))
            return False

        if not output_path.exists():
            # N_m3u8DL-CLI may have remuxed with a different suffix than
            # we expected. Walk workDir and look for a matching stem.
            target_stem = final_output.with_suffix("").name
            alt_paths: list[Path] = []
            try:
                for p in out_dir.iterdir():
                    if not p.is_file():
                        continue
                    if p.with_suffix("").name == target_stem:
                        alt_paths.append(p)
            except OSError:
                alt_paths = []
            alt_paths.sort(key=lambda p: p.stat().st_size, reverse=True)
            if alt_paths:
                output_path = alt_paths[0]
            else:
                logger.error("[nm3u8dl] output file not found: %s", final_output)
                if on_progress:
                    on_progress(EngineProgress(
                        fraction=0.0,
                        message="nm3u8dl error: output file not found",
                    ))
                return False

        if output_path.stat().st_size == 0:
            logger.error("[nm3u8dl] output file is empty: %s", output_path)
            if on_progress:
                on_progress(EngineProgress(
                    fraction=0.0,
                    message="nm3u8dl error: output file empty",
                ))
            return False

        if on_progress:
            on_progress(EngineProgress(fraction=1.0, message="m3u8 下载完成"))
        logger.info("[nm3u8dl] download complete: %s (%d bytes)", output_path, output_path.stat().st_size)
        return True

    @staticmethod
    def _sanitize_output_ext(ext: str) -> str:
        """Strip input-only extensions, default to mp4."""
        if ext.lower() in {"m3u8", "m3u", "ts", "aac", "mp3"}:
            return "mp4"
        return ext.lower()

    @staticmethod
    def _guess_ext(url: str) -> str:
        m = re.search(r"\.([a-zA-Z0-9]{2,5})(?:$|\?)", url)
        if m:
            return m.group(1).lower()
        return "mp4"
