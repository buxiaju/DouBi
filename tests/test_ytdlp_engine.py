"""Tests for the yt-dlp engine adapter.

Covers the M5.4 fix: ``_download_sync`` pre-creates the item's output
directory. yt-dlp writes the *playlist* info.json before any media
download for multi-P B 站 videos, and ``write_json_file`` does NOT
mkdir — without pre-creating the directory that write fails with
FileNotFoundError (the exact bug the user hit on BV1zygDzDES2).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from doubi.core.models import (  # noqa: E402
    Author,
    DownloadOptions,
    MediaItem,
    MediaType,
    Platform,
)


def _make_item(item_id="BV1zygDzDES2_p1", title="测试分P视频"):
    return MediaItem(
        platform=Platform.BILIBILI,
        item_id=item_id,
        title=title,
        author=Author(name="UP主"),
        media_type=MediaType.VIDEO,
        source_url="https://www.bilibili.com/video/BV1zygDzDES2",
    )


def _make_options(tmp_path) -> DownloadOptions:
    return DownloadOptions(
        output_root=tmp_path,
        filename_template="{title}_{item_id}",
        write_metadata_json=True,
        write_thumbnail=False,
    )


class _FakeYDL:
    """Records the opts it was constructed with."""

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def download(self, urls):
        pass


def test_download_precreates_output_dir(tmp_path):
    """Before calling yt-dlp, the item dir must already exist on disk."""
    from doubi.engines.yt_dlp import YtDlpEngine
    from doubi.core.storage.file_layout import resolve_item_dir

    item = _make_item()
    opts = _make_options(tmp_path)
    item_dir = resolve_item_dir(item, opts)   # expected out dir

    fake_mod = MagicMock()
    fake_mod.YoutubeDL = _FakeYDL
    engine = YtDlpEngine(yt_dlp_module=fake_mod)

    ok = asyncio.run(engine.download(item, opts))

    assert ok is True
    assert item_dir.is_dir(), (
        "engine must pre-create the output directory before yt-dlp runs"
    )


def test_download_precreates_dir_before_write(tmp_path, monkeypatch):
    """Simulate yt-dlp trying to write an info.json into the item dir —
    the parent must already exist (regression for the playlist
    info.json FileNotFoundError)."""
    from doubi.engines.yt_dlp import YtDlpEngine

    # Track whether the directory existed when yt-dlp "ran".
    state = {"dir_existed_at_call": False, "outtmpl": None}

    class _ProbeYDL:
        def __init__(self, opts):
            self.opts = opts
            state["outtmpl"] = opts.get("outtmpl")
            # The dir that yt-dlp would write pl_infojson into:
            candidate = Path(str(opts.get("outtmpl", ""))).parent
            state["dir_existed_at_call"] = candidate.is_dir()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def download(self, urls):
            pass

    fake_mod = MagicMock()
    fake_mod.YoutubeDL = _ProbeYDL
    engine = YtDlpEngine(yt_dlp_module=fake_mod)

    ok = asyncio.run(engine.download(_make_item(), _make_options(tmp_path)))

    assert ok is True
    assert state["dir_existed_at_call"] is True, (
        "outtmpl parent directory must exist before yt-dlp runs"
    )
    assert state["outtmpl"] is not None


# ---------------------------------------------------------------------------
# P0-1: write_subtitles must actually reach yt-dlp
#
# Root cause of the bug: ``DownloadOptions.write_subtitles`` was exposed
# all the way to ``doubi download --subtitles`` but ``_build_opts`` never
# read it, so the flag silently did nothing.
# 判据: the opts dict handed to YoutubeDL carries the subtitle keys when
# the switch is on, and carries none of them when it is off.
# ---------------------------------------------------------------------------

_SUBTITLE_KEYS = (
    "writesubtitles",
    "writeautomaticsub",
    "subtitleslangs",
    "subtitlesformat",
)


def _capture_opts(item, opts) -> dict:
    """Run a download against a recording fake and return the yt-dlp opts."""
    from doubi.engines.yt_dlp import YtDlpEngine

    captured: dict = {}

    class _RecordingYDL(_FakeYDL):
        def __init__(self, ydl_opts):
            super().__init__(ydl_opts)
            captured.update(ydl_opts)

    fake_mod = MagicMock()
    fake_mod.YoutubeDL = _RecordingYDL
    engine = YtDlpEngine(yt_dlp_module=fake_mod)

    assert asyncio.run(engine.download(item, opts)) is True
    return captured


def test_write_subtitles_sets_ytdlp_options(tmp_path):
    opts = _make_options(tmp_path)
    opts.write_subtitles = True

    captured = _capture_opts(_make_item(), opts)

    assert captured["writesubtitles"] is True
    # Auto-generated tracks matter: most 抖音 / B 站 videos have only
    # AI 字幕, so requesting manual-only would make the switch useless.
    assert captured["writeautomaticsub"] is True
    assert captured["subtitleslangs"] == ["all"]
    assert captured["subtitlesformat"] == "srt/best"


def test_subtitles_off_by_default(tmp_path):
    captured = _capture_opts(_make_item(), _make_options(tmp_path))

    for key in _SUBTITLE_KEYS:
        assert key not in captured, f"{key} must not be set when the switch is off"


# ---------------------------------------------------------------------------
# P3-1: resume (continuedl) + cooperative cancellation
#
# Root cause of the two bugs fixed here:
#   1. ``_build_opts`` never set ``continuedl``, so resume behaviour was
#      merely inherited from yt-dlp rather than being contractual, and no
#      surface could turn it off.
#   2. ``_cleanup_intermediates`` deleted ``.part`` / ``.ytdl``
#      unconditionally after every success. A ``.part`` file *is* the
#      resume state, so the cleanup defeated resuming outright. It was
#      also a concurrency hazard: the default output_dir_template groups
#      every video of one author into a shared directory, so the sweep
#      could delete a sibling item's in-flight ``.part``.
#   3. The download body runs in ``asyncio.to_thread``, so
#      ``Task.cancel()`` cannot interrupt it. Cancellation therefore has
#      to be cooperative, polled from the progress hook — which was
#      previously installed ONLY when an ``on_progress`` callback was
#      supplied.
# 判据: continuedl mirrors options.resume; .part survives cleanup iff
# resume is on; a cancel_check returning True aborts the transfer, is
# reported as not-success, and leaves the .part file on disk.
# ---------------------------------------------------------------------------


def test_resume_on_by_default_sets_continuedl(tmp_path):
    captured = _capture_opts(_make_item(), _make_options(tmp_path))

    assert captured["continuedl"] is True


def test_resume_off_clears_continuedl(tmp_path):
    opts = _make_options(tmp_path)
    opts.resume = False

    captured = _capture_opts(_make_item(), opts)

    assert captured["continuedl"] is False


def test_progress_hook_installed_without_progress_callback(tmp_path):
    """The hook carries the cancel probe, so it must always be present.

    Regression guard: it used to be attached only when ``on_progress``
    was passed, which would silently make cancellation a no-op for the
    (very common) callback-free callers.
    """
    captured = _capture_opts(_make_item(), _make_options(tmp_path))

    hooks = captured.get("progress_hooks")
    assert hooks, "progress_hooks must be installed even without on_progress"
    assert callable(hooks[0])


def _run_with_cancel(tmp_path, *, resume: bool, cancel_after: int = 0):
    """Drive a download whose fake yt-dlp reports progress, then read state.

    The fake writes a ``.part`` file and invokes the progress hook, which
    is exactly where the engine polls ``cancel_check``.
    """
    from doubi.engines.yt_dlp import YtDlpEngine
    from doubi.core.storage.file_layout import resolve_item_dir

    item = _make_item()
    opts = _make_options(tmp_path)
    opts.resume = resume

    calls = {"n": 0}

    def _cancel_check() -> bool:
        calls["n"] += 1
        return calls["n"] > cancel_after

    opts.cancel_check = _cancel_check

    item_dir = resolve_item_dir(item, opts)
    part_file = item_dir / "video.mp4.part"

    class _ProgressYDL(_FakeYDL):
        def download(self, urls):
            part_file.parent.mkdir(parents=True, exist_ok=True)
            part_file.write_bytes(b"partial")
            for hook in self.opts.get("progress_hooks", []):
                hook({
                    "status": "downloading",
                    "total_bytes": 100,
                    "downloaded_bytes": 10,
                })

    fake_mod = MagicMock()
    fake_mod.YoutubeDL = _ProgressYDL
    engine = YtDlpEngine(yt_dlp_module=fake_mod)

    events: list = []
    ok = asyncio.run(engine.download(item, opts, on_progress=events.append))
    return ok, part_file, events


def test_cancel_check_aborts_download(tmp_path):
    ok, part_file, events = _run_with_cancel(tmp_path, resume=True)

    assert ok is False, "a cancelled download must not report success"
    assert part_file.exists(), (
        "the .part file must survive cancellation so the transfer can resume"
    )
    assert any(e.extra.get("cancelled") for e in events if e.extra), (
        "cancellation must be reported distinctly, not as a generic error"
    )


def test_cancelled_download_is_not_reported_as_error(tmp_path):
    """DownloadCancelled subclasses Exception, so the blanket handler
    would otherwise mislabel an abort as a genuine yt-dlp failure."""
    _, _, events = _run_with_cancel(tmp_path, resume=True)

    messages = [e.message for e in events]
    assert "cancelled" in messages
    assert not any(m.startswith("yt-dlp error:") for m in messages)


def test_part_file_kept_when_resume_enabled(tmp_path):
    """A successful run must not delete .part while resume is on."""
    ok, part_file, _ = _run_with_cancel(tmp_path, resume=True, cancel_after=99)

    assert ok is True
    assert part_file.exists(), "resume must protect .part from cleanup"


def test_part_file_removed_when_resume_disabled(tmp_path):
    """With resume off the old tidy-up behaviour is preserved."""
    ok, part_file, _ = _run_with_cancel(tmp_path, resume=False, cancel_after=99)

    assert ok is True
    assert not part_file.exists(), (
        "with resume off, .part files should still be swept away"
    )
