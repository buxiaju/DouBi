"""yt-dlp engine adapter.

yt-dlp is the workhorse. This module is a thin async wrapper around
:class:`yt_dlp.YoutubeDL` plus a progress hook that throttles
emissions to avoid flooding the UI.

Engine contract (M2):
    * Honors ``item.output_template`` (rendered by the pipeline) if
      set, else falls back to ``options.filename_template``.
    * Maps our high-level options (``max_quality``, ``container``,
      ``concurrent_fragments``, ``rate_limit``, ``proxy``,
      ``cookies_file``) to the corresponding yt-dlp options.
    * Emits :class:`EngineProgress` events at most every ~0.5% to
      keep progress bars smooth without spam.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Any, Optional

import yt_dlp

from ..core.models import DownloadOptions, MediaItem
from ..core.storage.file_layout import resolve_item_dir
from .base import Engine, EngineProgress, EngineProgressCallback

logger = logging.getLogger("doubi.engines.yt_dlp")

#: yt-dlp output-template fragment appended to every basename.
#:
#: ``%(playlist_index&_P{:03d}|)s`` reads as "if ``playlist_index`` is
#: set, render ``_P`` plus the zero-padded index; otherwise render
#: nothing". It keeps the multi-part (分P) files of a single Bilibili
#: video apart while leaving plain single-video filenames untouched.
PART_INDEX_SUFFIX = "%(playlist_index&_P{:03d}|)s"


def _try_import_yt_dlp() -> Any:
    try:
        import yt_dlp  # type: ignore
        return yt_dlp
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "yt-dlp is not installed. Run `pip install yt-dlp`."
        ) from e


class YtDlpEngine(Engine):
    """Engine that delegates to yt-dlp."""

    name = "yt-dlp"

    def __init__(self, yt_dlp_module: Any = None):
        self._ytdlp = yt_dlp_module

    @property
    def ytdlp(self) -> Any:
        if self._ytdlp is None:
            self._ytdlp = _try_import_yt_dlp()
        return self._ytdlp

    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_ffmpeg_location() -> Optional[str]:
        """Find an ffmpeg binary, or ``None``.

        Priority:
          1. ffmpeg on PATH
          2. imageio-ffmpeg's bundled static binary (always available
             when the ``imageio-ffmpeg`` pip package is installed)

        yt-dlp needs ffmpeg to merge bestvideo+bestaudio into a single
        file; B 站 (and most sites) only offer DASH split streams, so
        without ffmpeg the download fails. The imageio-ffmpeg fallback
        is what the original douyin-downloader used — it ships a real
        ffmpeg static build inside the wheel, no system install needed.
        """
        on_path = shutil.which("ffmpeg")
        if on_path:
            return on_path
        try:
            import imageio_ffmpeg  # type: ignore
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            return None

    def supports(self, item: MediaItem) -> bool:
        return bool(item.source_url)

    async def download(
        self,
        item: MediaItem,
        options: DownloadOptions,
        *,
        on_progress: Optional[EngineProgressCallback] = None,
    ) -> bool:
        return await asyncio.to_thread(self._download_sync, item, options, on_progress)

    # ------------------------------------------------------------------

    def _resolve_template(self, item: MediaItem, options: DownloadOptions, out_dir: Path) -> str:
        """Pick the basename for this item.

        Priority: ``item.output_template`` (pre-rendered by the pipeline)
        > ``options.filename_template`` (raw, with tokens unresolved).
        Either way, the engine appends ``.%(ext)s`` so yt-dlp fills
        in the actual container extension.

        A conditional ``playlist_index`` suffix is inserted before the
        extension. Bilibili collection episodes are bare ``BVxxx`` URLs
        that yt-dlp expands into *all* of the video's parts (分P); with a
        fixed basename every part would overwrite the previous one. The
        ``%(field&IF_PRESENT|IF_ABSENT)s`` form appends ``_P007`` only
        when an index exists, so single videos and the legacy ``?p=N``
        per-page URLs (which yt-dlp reports as plain videos, index
        ``None``) keep their exact old filenames.
        """
        if item.output_template:
            base = item.output_template
        else:
            base = options.filename_template or "{title}_{item_id}"
        return str(out_dir / (base + PART_INDEX_SUFFIX + ".%(ext)s"))

    def _build_opts(self, item: MediaItem, options: DownloadOptions) -> dict:
        # M4: resolve the per-item directory under output_root
        out_dir = resolve_item_dir(item, options)

        opts: dict[str, Any] = {
            "outtmpl": self._resolve_template(item, options, out_dir),
            "format": options.format_id or self._quality_to_format(options.max_quality),
            "merge_output_format": options.container,
            "writethumbnail": options.write_thumbnail,
            "writeinfojson": options.write_metadata_json,
            "noprogress": True,
            "quiet": True,
            "no_warnings": True,
            "retries": 3,
            "fragment_retries": 3,
            "concurrent_fragment_downloads": max(1, options.concurrent_fragments),
        }
        # Point yt-dlp at an ffmpeg binary (PATH or the bundled static
        # one from imageio-ffmpeg) so bestvideo+bestaudio merging works
        # even on machines without a system ffmpeg install.
        ffmpeg_loc = self._resolve_ffmpeg_location()
        if ffmpeg_loc:
            opts["ffmpeg_location"] = ffmpeg_loc
        if options.cookies_file:
            opts["cookiefile"] = str(options.cookies_file)
        if options.proxy:
            opts["proxy"] = options.proxy
        if options.rate_limit:
            opts["ratelimit"] = options.rate_limit
        if options.user_agent:
            opts["user_agent"] = options.user_agent
        return opts

    @staticmethod
    def _quality_to_format(max_quality: str) -> str:
        """Translate our ``max_quality`` token to a yt-dlp format selector.

        yt-dlp defaults to picking the best single progressive mp4; we
        slightly bias toward bestvideo+bestaudio so the merger kicks in
        and we get the highest-quality stream regardless of muxing.

        **ffmpeg guard**: without ffmpeg on PATH, ``bestvideo+bestaudio``
        would need a merge step and yt-dlp aborts with
        "You have requested merging of multiple formats but ffmpeg is
        not installed". In that case we fall back to ``best`` (a single
        progressive file), which is what yt-dlp would choose anyway.
        """
        q = (max_quality or "best").strip().lower()
        if q in ("best", ""):
            return "bestvideo*+bestaudio/best"
        if q == "worst":
            return "worstvideo*+worstaudio/worst"
        return q

    # ------------------------------------------------------------------

    @staticmethod
    def _cleanup_intermediates(item: MediaItem, options: DownloadOptions) -> None:
        """Delete leftover intermediate artifacts from the item directory.

        The user only wants the finished media files in the folder. yt-dlp
        removes its own per-format fragments after a successful merge, but
        ``.part`` / ``.ytdl`` / ``.temp`` stragglers survive an interrupted
        or retried run, and the playlist-level ``*.info.json`` it writes for
        B 站 multi-P videos is never cleaned up. Sidecars the user opted
        into (``write_thumbnail`` / ``write_metadata_json``) are preserved.
        """
        drop_suffixes = {".part", ".ytdl", ".temp"}
        try:
            item_dir = resolve_item_dir(item, options)
        except Exception:   # noqa: BLE001
            logger.debug("cleanup skipped: cannot resolve item dir", exc_info=True)
            return
        for path in item_dir.iterdir():
            if not path.is_file():
                continue
            name = path.name
            remove = path.suffix.lower() in drop_suffixes
            if not remove and name.endswith(".info.json"):
                remove = not options.write_metadata_json
            if not remove and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                remove = not options.write_thumbnail
            if not remove:
                continue
            try:
                path.unlink()
            except OSError:
                logger.debug("could not remove intermediate %s", name, exc_info=True)

    def _download_sync(
        self,
        item: MediaItem,
        options: DownloadOptions,
        on_progress: Optional[EngineProgressCallback],
    ) -> bool:
        if not shutil.which("ffmpeg") and not options.format_id:
            logger.debug("ffmpeg not on PATH; yt-dlp will fall back to progressive streams")

        opts = self._build_opts(item, options)

        # Pre-create the item's output directory. yt-dlp normally makes
        # it lazily before writing media files, but for B 站 multi-P
        # videos (multi_video playlists) it writes the playlist
        # info.json *before* any media download — at which point the
        # directory doesn't exist yet, and `write_json_file` (which
        # does NOT mkdir) fails with FileNotFoundError. Creating it
        # up-front fixes that edge case.
        try:
            resolve_item_dir(item, options).mkdir(parents=True, exist_ok=True)
        except Exception:   # noqa: BLE001
            logger.debug("pre-create output dir failed; yt-dlp will try", exc_info=True)

        if on_progress is not None:
            last_fraction = {"v": -1.0}

            def _hook(d: dict) -> None:
                status = d.get("status")
                if status == "downloading":
                    total = d.get("total_bytes") or d.get("total_bytes_estimate")
                    done = d.get("downloaded_bytes")
                    if total and done is not None:
                        frac = max(0.0, min(1.0, done / total))
                    else:
                        pct_str = (d.get("_percent_str", "") or "").strip().rstrip("%")
                        try:
                            frac = max(0.0, min(1.0, float(pct_str) / 100.0))
                        except ValueError:
                            frac = last_fraction["v"] if last_fraction["v"] >= 0 else 0.0
                    if frac - last_fraction["v"] >= 0.005 or frac >= 1.0:
                        last_fraction["v"] = frac
                        on_progress(EngineProgress(
                            fraction=frac,
                            message=f"downloading {d.get('_percent_str', '').strip()}",
                            extra={"speed": d.get("speed"), "eta": d.get("eta")},
                        ))
                elif status == "finished":
                    on_progress(EngineProgress(
                        fraction=1.0,
                        message="download finished, post-processing",
                        extra={"filename": d.get("filename")},
                    ))
                elif status == "error":
                    on_progress(EngineProgress(
                        fraction=0.0, message="yt-dlp reported error",
                    ))

            opts["progress_hooks"] = [_hook]

        try:
            with self.ytdlp.YoutubeDL(opts) as ydl:
                ydl.download([item.source_url])
            self._cleanup_intermediates(item, options)
            return True
        except Exception as exc:
            logger.exception("yt-dlp failed for %s: %s", item.source_url, exc)
            if on_progress is not None:
                on_progress(EngineProgress(
                    fraction=0.0, message=f"yt-dlp error: {exc}",
                ))
            return False
