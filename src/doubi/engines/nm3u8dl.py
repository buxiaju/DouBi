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
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Optional

from ..core.models import DownloadOptions, MediaItem
from ..core.storage.file_layout import resolve_item_dir
from ._subproc import SubprocessTimeout, run_supervised_subprocess
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
    """Locate ffmpeg — prefer the one bundled with N_m3u8DL-CLI."""
    cli_dir = None
    cli = _find_cli()
    if cli:
        cli_dir = Path(cli).parent

    if cli_dir:
        bundled = cli_dir / "ffmpeg.exe"
        if bundled.exists():
            return str(bundled)

    on_path = shutil.which("ffmpeg")
    if on_path:
        return on_path

    try:
        import imageio_ffmpeg
        path = imageio_ffmpeg.get_ffmpeg_exe()
        if path and Path(path).exists():
            return path
    except Exception:
        pass

    return None


# Progress line regex — N_m3u8DL-CLI outputs lines like:
#   [#12/150] 1.23MB / 12.34MB | 1.23MB/s | 00:10/01:45
#   [#150/150] 12.34MB / 12.34MB | completed | 00:45/00:45
#   [INFO] download completed
#   [ERROR] something went wrong
_PROGRESS_RE = re.compile(r"\[#(\d+)/(\d+)\]")
_COMPLETE_RE = re.compile(r"completed", re.IGNORECASE)
_ERROR_RE = re.compile(r"\[ERROR\]", re.IGNORECASE)


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

        def _parse_and_emit(decoded: str) -> None:
            nonlocal last_frac, fatal_error
            if not decoded:
                return
            if _ERROR_RE.search(decoded):
                fatal_error = decoded
                logger.error("[nm3u8dl] error: %s", decoded)
            if _COMPLETE_RE.search(decoded) and on_progress:
                on_progress(EngineProgress(fraction=1.0, message="m3u8 下载完成"))
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
            raise

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
