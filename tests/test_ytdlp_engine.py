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
