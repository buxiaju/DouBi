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

Resume & cancellation (P3-1):
    * ``options.resume`` maps to yt-dlp's ``continuedl`` and also
      protects ``.part`` / ``.ytdl`` files from the intermediate
      cleanup, since deleting them is what defeats a resume.
    * ``options.cancel_check`` is a cooperative abort probe polled from
      the progress hook. The download body runs in a worker thread via
      ``asyncio.to_thread``, so ``asyncio.Task.cancel()`` cannot
      interrupt it — the probe is the only way to stop a transfer in
      flight. A cancelled download returns ``False`` and leaves its
      ``.part`` file in place so it can be resumed later.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Any, Optional

import yt_dlp

from ..core.models import DownloadOptions, MediaItem, MediaType
from ..core.storage.file_layout import resolve_item_dir
from ._subproc import find_bundled_ffmpeg
from .base import Engine, EngineProgress, EngineProgressCallback

logger = logging.getLogger("doubi.engines.yt_dlp")

#: yt-dlp output-template fragment appended to every basename.
#:
#: ``%(playlist_index&_P{:03d}|)s`` reads as "if ``playlist_index`` is
#: set, render ``_P`` plus the zero-padded index; otherwise render
#: nothing". It keeps the multi-part (分P) files of a single Bilibili
#: video apart while leaving plain single-video filenames untouched.
PART_INDEX_SUFFIX = "%(playlist_index&_P{:03d}|)s"

#: Default user agent when the caller did not pin one.
#:
#: YouTube (and increasingly other platforms) reject bare ``yt-dlp/x.y.z``
#: UAs with HTTP 403. The YouTube adapter already uses a Chrome UA for
#: its metadata fetch; using the same string here keeps **parse and
#: download on an equal footing** — otherwise you get the classic
#: "YouTube 可以解析但下载失败" symptom because parse uses Chrome UA
#: while the engine falls through to yt-dlp's built-in string.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)


class _LocalDownloadCancelled(Exception):
    """Fallback abort signal when ``yt_dlp.utils.DownloadCancelled`` is absent.

    Only used when the injected yt-dlp module does not expose the real
    class (e.g. a test double). See
    :meth:`YtDlpEngine._cancelled_exception`.
    """


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
          1. the ffmpeg shipped with DouBi (``tools/nm3u8dl/ffmpeg.exe``,
             also present inside the frozen bundle)
          2. ffmpeg on PATH

        yt-dlp needs ffmpeg to merge bestvideo+bestaudio into a single
        file; B 站 (and most sites) only offer DASH split streams, so
        without ffmpeg the download fails. That is why the release build
        carries its own copy instead of relying on the user having
        installed ffmpeg system-wide.
        """
        bundled = find_bundled_ffmpeg()
        if bundled:
            return bundled
        on_path = shutil.which("ffmpeg")
        if on_path:
            return on_path
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

        # 直播流是 HLS，与点播有几个本质区别：
        # * 没有片尾，merge_output_format 在直播录制中途没意义，
        #   强行设 mp4 会在结束时做一次 remux，可能失败。
        # * ``live_from_start`` 让 yt-dlp 从直播开播时间点开始录
        #   （时移），而不是从加入那一刻才开始。B 站支持该特性。
        # * 片段重试次数调高：直播中途断流很常见。
        is_live = item.media_type == MediaType.LIVE

        opts: dict[str, Any] = {
            "outtmpl": self._resolve_template(item, options, out_dir),
            "format": options.format_id or self._quality_to_format(options.max_quality),
            "writethumbnail": options.write_thumbnail,
            "writeinfojson": options.write_metadata_json,
            "noprogress": True,
            "quiet": True,
            "no_warnings": True,
            "retries": 3,
            "fragment_retries": 3,
            "concurrent_fragment_downloads": max(1, options.concurrent_fragments),
            # Resume an interrupted transfer from the existing ``.part``
            # file instead of re-downloading from byte 0. yt-dlp's own
            # default is True, but we set it explicitly so the behaviour
            # is contractual rather than inherited.
            "continuedl": options.resume,
        }
        if is_live:
            # 直播流不 merge：HLS 分片是 ts，合并 mp4 需要完整流，
            # 直播中途 remux 会因流未结束而失败。
            opts["live_from_start"] = True
            opts["fragment_retries"] = 10
        else:
            opts["merge_output_format"] = options.container
        # Point yt-dlp at an ffmpeg binary (PATH or the bundled static
        # one from imageio-ffmpeg) so bestvideo+bestaudio merging works
        # even on machines without a system ffmpeg install.
        ffmpeg_loc = self._resolve_ffmpeg_location()
        if ffmpeg_loc:
            opts["ffmpeg_location"] = ffmpeg_loc
        # Subtitles are a pure yt-dlp passthrough: the extractor knows
        # which tracks a site offers. ``writeautomaticsub`` is included
        # because most 抖音 / B 站 videos only carry auto-generated
        # (AI 字幕) tracks, and requesting only manual ones would make
        # the switch silently produce nothing. ``subtitlesformat``
        # prefers srt and falls back to whatever the site has.
        if options.write_subtitles:
            opts["writesubtitles"] = True
            opts["writeautomaticsub"] = True
            opts["subtitleslangs"] = ["all"]
            opts["subtitlesformat"] = "srt/best"
        if options.cookies_file:
            opts["cookiefile"] = str(options.cookies_file)
        if options.proxy:
            opts["proxy"] = options.proxy
        if options.rate_limit:
            opts["ratelimit"] = options.rate_limit
        # UA：显式传了就用显式的，否则用 DEFAULT_USER_AGENT（Chrome UA）。
        # 不能留空让 yt-dlp 决定——它的默认 UA 是 ``yt-dlp/<版本号>``，
        # YouTube 会对这个 UA 直接 403。于是出现「解析能拿到标题/作者
        # （adapter._extract_meta 用的是浏览器 UA）但下载阶段 403」的
        # 不对称失败。详见 DEFAULT_USER_AGENT 处的注释。
        opts["user_agent"] = options.user_agent or DEFAULT_USER_AGENT
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

        **Resume interaction (P3-1)**: a ``.part`` file *is* the resume
        state, so deleting it makes ``continuedl`` a no-op on the next
        attempt. When ``options.resume`` is on we therefore keep
        ``.part`` / ``.ytdl``. This also removes a latent concurrency
        hazard: the default ``output_dir_template``
        (``{platform}/{author}/{media_type}``) puts every video by one
        author in a *shared* directory, so an unconditional sweep here
        could delete the in-flight ``.part`` of a sibling item still
        being downloaded by another worker.
        """
        drop_suffixes = {".temp"} if options.resume else {".part", ".ytdl", ".temp"}
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

    def _cancelled_exception(self) -> type[BaseException]:
        """Return the exception class used to abort a yt-dlp transfer.

        ``yt_dlp.utils.DownloadCancelled`` is the sanctioned mechanism:
        ``YoutubeDL.download()`` runs inside ``__download_wrapper``, which
        re-raises it unless ``break_per_url`` is set (off by default), so
        raising it from a progress hook cleanly unwinds out of
        ``ydl.download([url])``.

        The lookup is defensive because ``self.ytdlp`` is injectable — tests
        pass a ``MagicMock`` module, whose attribute access yields a Mock
        that is neither raisable nor catchable. Anything that is not a real
        exception class falls back to a private local class, which keeps the
        ``raise`` / ``except`` pair coherent under a fake module.
        """
        exc = getattr(getattr(self.ytdlp, "utils", None), "DownloadCancelled", None)
        if isinstance(exc, type) and issubclass(exc, BaseException):
            return exc
        return _LocalDownloadCancelled

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

            def _emit_progress(d: dict) -> None:
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
        else:
            def _emit_progress(d: dict) -> None:
                return None

        cancel_check = options.cancel_check
        cancelled_exc = self._cancelled_exception()

        def _hook(d: dict) -> None:
            # Cancellation is checked *before* reporting progress so an
            # abort is not preceded by a misleading progress event. The
            # hook is installed unconditionally (even without
            # ``on_progress``) because it is the only place we get
            # control back from yt-dlp mid-transfer.
            if cancel_check is not None and cancel_check():
                raise cancelled_exc("cancelled by caller")
            _emit_progress(d)

        opts["progress_hooks"] = [_hook]

        try:
            with self.ytdlp.YoutubeDL(opts) as ydl:
                ydl.download([item.source_url])
            self._cleanup_intermediates(item, options)
            return True
        except cancelled_exc as exc:
            # Must be caught *before* the blanket handler below:
            # DownloadCancelled subclasses Exception, so it would
            # otherwise be logged and reported as a genuine failure.
            # Intermediates are deliberately NOT cleaned up here — the
            # ``.part`` file is what makes resuming possible.
            logger.info("yt-dlp cancelled for %s: %s", item.source_url, exc)
            if on_progress is not None:
                on_progress(EngineProgress(
                    fraction=0.0, message="cancelled",
                    extra={"cancelled": True},
                ))
            return False
        except Exception as exc:
            logger.exception("yt-dlp failed for %s: %s", item.source_url, exc)
            if on_progress is not None:
                on_progress(EngineProgress(
                    fraction=0.0, message=f"yt-dlp error: {exc}",
                ))
            return False
