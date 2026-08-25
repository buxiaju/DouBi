"""Pipeline-level automatic retry (exponential backoff).

Why this file exists separately from ``test_pipeline_smoke.py``: the smoke
tests all use a stub engine that *succeeds*, so they can never tell whether
the retry loop exists at all. Every test here fails on the pre-retry code.

Six invariants are pinned, each one guarding a decision that is easy to
undo by accident:

1. ``DownloadPipeline`` stays a single-attempt primitive (``max_retries=0``).
   The ~24 construction sites in the other test files depend on it, and so
   does anybody who wants exactly one engine call.
2. Retry fires on ``ok is False``, not only on a raised exception --
   ``engines.yt_dlp`` funnels every real-world failure into ``return False``,
   so an exception-only retry would be dead code in production.
3. A user-requested stop (``options.cancel_check``) must NOT be retried:
   the engine reports a cancellation as ``ok is False`` too, so without the
   probe a paused download would be silently re-downloaded.
4. The retry notice is machine-readable (``extra["retry"]``), because the
   surfaces have to render it -- see the ``[retry]`` branch in ``cli.main``.
5. The backoff sleep does not hold the concurrency semaphore.
6. The product default (auto-retry on) lives on
   ``engine_loader.build_default_pipeline``, not on the class.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from doubi.core import pipeline as pipeline_mod  # noqa: E402
from doubi.core.engine_loader import build_default_pipeline  # noqa: E402
from doubi.core.models import (  # noqa: E402
    DownloadOptions,
    MediaItem,
    MediaType,
    Platform,
)
from doubi.core.pipeline import (  # noqa: E402
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_BACKOFF,
    DownloadPipeline,
    ProgressEvent,
)
from doubi.engines.base import Engine, EngineProgress  # noqa: E402


@pytest.fixture(autouse=True)
def _no_platform_cookies(monkeypatch, tmp_path):
    """Keep cookie resolution out of the picture.

    ``_download_with_progress`` injects the platform cookie file persisted
    by the login flow. Pointing the env var at a missing path makes these
    tests independent of whatever the developer happens to have logged
    into locally.
    """
    monkeypatch.setenv("DOUBI_DOUYIN_COOKIES", str(tmp_path / "no-such-cookies.txt"))
    yield


def _item(item_id: str = "7676517073484352822") -> MediaItem:
    return MediaItem(
        platform=Platform.DOUYIN,
        item_id=item_id,
        title="retry test",
        media_type=MediaType.VIDEO,
        source_url=f"https://www.douyin.com/video/{item_id}",
    )


class _CountingEngine(Engine):
    """Engine whose per-attempt outcome the test dictates.

    ``outcomes`` is consumed one entry per attempt: ``True`` -> success,
    ``False`` -> ``return False`` (how yt-dlp reports every real failure),
    an exception instance -> raised. Running past the end of the list keeps
    yielding the last entry, so a test can say "always fail" with ``[False]``.
    """

    name = "counting"

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def supports(self, item: MediaItem) -> bool:
        return True

    async def download(self, item, options, *, on_progress=None):
        self.calls += 1
        idx = min(self.calls - 1, len(self.outcomes) - 1)
        outcome = self.outcomes[idx]
        if on_progress is not None:
            on_progress(EngineProgress(fraction=0.1, message="started"))
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


@pytest.fixture
def _instant_backoff(monkeypatch):
    """Swallow the real waiting, but record what was asked for.

    Returns the list of requested delays so a test can assert the curve is
    exponential without spending 6 seconds of wall clock doing it.
    """
    delays: list[float] = []
    real_sleep = asyncio.sleep

    async def _fake_sleep(delay, *a, **kw):
        delays.append(delay)
        await real_sleep(0)

    monkeypatch.setattr(pipeline_mod.asyncio, "sleep", _fake_sleep)
    return delays


def _run(pipeline, item, options, events=None):
    """Drive one item through the pipeline the way the smoke tests do.

    ``_download_with_progress``'s trailing parameter is keyword-only
    (``index``); the first four are positional on purpose -- that is how
    ``process_batch`` and the existing tests call it, so this helper keeps
    the call shape under test.
    """
    on_progress = events.append if events is not None else None
    return asyncio.run(
        pipeline._download_with_progress(item, options, on_progress, "job-ret1")
    )


# ---------------------------------------------------------------------------
# 1. The primitive stays single-attempt
# ---------------------------------------------------------------------------


def test_bare_pipeline_does_not_retry(tmp_path):
    """A hand-built DownloadPipeline calls the engine exactly once.

    This is the contract the other test files silently rely on: several use
    deterministically failing stubs and assert exact call counts. Flipping
    the class default to a nonzero value would multiply every one of them.
    """
    engine = _CountingEngine([False])
    pipeline = DownloadPipeline(engine=engine)
    ok = _run(pipeline, _item(), DownloadOptions(output_root=tmp_path / "out"))
    assert ok is False
    assert engine.calls == 1


def test_bare_pipeline_single_attempt_on_exception(tmp_path):
    """An exception must not escape, and must not be retried either."""
    engine = _CountingEngine([RuntimeError("engine exploded")])
    pipeline = DownloadPipeline(engine=engine)
    ok = _run(pipeline, _item(), DownloadOptions(output_root=tmp_path / "out"))
    assert ok is False
    assert engine.calls == 1


# ---------------------------------------------------------------------------
# 2. Retry fires on BOTH failure shapes
# ---------------------------------------------------------------------------


def test_retry_on_returned_false(tmp_path, _instant_backoff):
    """``ok is False`` is the failure shape that actually happens in prod."""
    engine = _CountingEngine([False])
    pipeline = DownloadPipeline(engine=engine, max_retries=2, retry_backoff=2.0)
    ok = _run(pipeline, _item(), DownloadOptions(output_root=tmp_path / "out"))
    assert ok is False
    assert engine.calls == 3, "max_retries=2 means 1 initial attempt + 2 retries"


def test_retry_on_raised_exception(tmp_path, _instant_backoff):
    engine = _CountingEngine([RuntimeError("boom")])
    pipeline = DownloadPipeline(engine=engine, max_retries=2, retry_backoff=2.0)
    ok = _run(pipeline, _item(), DownloadOptions(output_root=tmp_path / "out"))
    assert ok is False
    assert engine.calls == 3


def test_retry_stops_at_first_success(tmp_path, _instant_backoff):
    """A recovered download reports success, and burns no further attempts."""
    engine = _CountingEngine([False, True])
    pipeline = DownloadPipeline(engine=engine, max_retries=2, retry_backoff=2.0)
    events: list[ProgressEvent] = []
    ok = _run(pipeline, _item(), DownloadOptions(output_root=tmp_path / "out"), events)
    assert ok is True
    assert engine.calls == 2
    phases = [e.phase for e in events]
    assert "failed" not in phases
    assert phases[-1] == "done"


def test_backoff_is_exponential(tmp_path, _instant_backoff):
    """Delays double: retry_backoff * 2**(attempt-1)."""
    engine = _CountingEngine([False])
    pipeline = DownloadPipeline(engine=engine, max_retries=3, retry_backoff=1.5)
    _run(pipeline, _item(), DownloadOptions(output_root=tmp_path / "out"))
    assert _instant_backoff == [1.5, 3.0, 6.0]


def test_no_sleep_after_the_final_attempt(tmp_path, _instant_backoff):
    """The loop must not wait after the attempt it will never follow up on."""
    engine = _CountingEngine([False])
    pipeline = DownloadPipeline(engine=engine, max_retries=1, retry_backoff=2.0)
    _run(pipeline, _item(), DownloadOptions(output_root=tmp_path / "out"))
    assert engine.calls == 2
    assert len(_instant_backoff) == 1, "2 attempts means exactly 1 backoff"


# ---------------------------------------------------------------------------
# 3. Cancellation is not a failure to retry
# ---------------------------------------------------------------------------


def test_cancelled_download_is_not_retried(tmp_path, _instant_backoff):
    """A paused download must stay paused.

    ``engines.yt_dlp`` swallows its own DownloadCancelled and returns False,
    making a user stop indistinguishable from a network error at this level.
    Retrying here would re-download exactly what the user asked to stop.
    """
    engine = _CountingEngine([False])
    pipeline = DownloadPipeline(engine=engine, max_retries=3, retry_backoff=2.0)
    options = DownloadOptions(
        output_root=tmp_path / "out", cancel_check=lambda: True
    )
    ok = _run(pipeline, _item(), options)
    assert ok is False
    assert engine.calls == 1
    assert _instant_backoff == [], "a cancelled item must not even wait"


def test_cancel_check_flipping_midway_stops_retrying(tmp_path, _instant_backoff):
    """Stopping during the backoff ends the loop at the next check."""
    stopped = {"v": False}
    engine = _CountingEngine([False])

    def _probe() -> bool:
        return stopped["v"]

    original = pipeline_mod.asyncio.sleep

    async def _sleep_then_stop(delay, *a, **kw):
        await original(delay)
        stopped["v"] = True

    pipeline = DownloadPipeline(engine=engine, max_retries=5, retry_backoff=2.0)
    options = DownloadOptions(output_root=tmp_path / "out", cancel_check=_probe)
    pipeline_mod.asyncio.sleep = _sleep_then_stop
    try:
        ok = _run(pipeline, _item(), options)
    finally:
        pipeline_mod.asyncio.sleep = original

    assert ok is False
    assert engine.calls == 2, "attempt 1, one backoff, attempt 2, then cancelled"


def test_broken_cancel_probe_does_not_kill_the_download(tmp_path, _instant_backoff):
    """A raising probe degrades to "not cancelled" instead of exploding."""

    def _probe() -> bool:
        raise RuntimeError("probe is broken")

    engine = _CountingEngine([False, True])
    pipeline = DownloadPipeline(engine=engine, max_retries=2, retry_backoff=2.0)
    options = DownloadOptions(output_root=tmp_path / "out", cancel_check=_probe)
    ok = _run(pipeline, _item(), options)
    assert ok is True
    assert engine.calls == 2


# ---------------------------------------------------------------------------
# 4. The retry notice is renderable
# ---------------------------------------------------------------------------


def test_retry_emits_machine_readable_event(tmp_path, _instant_backoff):
    """Surfaces key off ``extra["retry"]``, not off the message text.

    ``cli.main``'s progress printer has a dedicated ``elif
    ev.extra.get("retry")`` branch; if these keys move, the user watches a
    stalled progress line for the whole backoff with no explanation.
    """
    engine = _CountingEngine([False])
    pipeline = DownloadPipeline(engine=engine, max_retries=2, retry_backoff=2.0)
    events: list[ProgressEvent] = []
    _run(pipeline, _item(), DownloadOptions(output_root=tmp_path / "out"), events)

    notices = [e for e in events if e.extra.get("retry")]
    assert len(notices) == 2
    first = notices[0]
    assert first.phase == "downloading"
    assert first.extra["retry"] == 1
    assert first.extra["max_retries"] == 2
    assert first.extra["delay"] == 2.0
    assert first.extra["reason"] == "engine returned False"
    assert "retrying" in first.message


def test_final_failure_event_carries_the_last_error(tmp_path, _instant_backoff):
    """The terminal event must say *why*, not just "failed"."""
    engine = _CountingEngine([RuntimeError("connection reset")])
    pipeline = DownloadPipeline(engine=engine, max_retries=1, retry_backoff=2.0)
    events: list[ProgressEvent] = []
    _run(pipeline, _item(), DownloadOptions(output_root=tmp_path / "out"), events)

    failed = [e for e in events if e.phase == "failed"]
    assert len(failed) == 1
    assert "connection reset" in failed[0].message


# ---------------------------------------------------------------------------
# 5. The backoff does not squat on a concurrency slot
# ---------------------------------------------------------------------------


async def test_backoff_releases_the_semaphore():
    """A retrying item must not block a healthy one.

    With ``max_concurrent=1``, if the sleep happened inside ``async with
    self._sem`` the second download could not start until the first item
    exhausted its retries -- one slow failure would stall the whole queue
    for the entire backoff. Uses a real sleep: the point is the interleaving.
    """
    timeline: list[str] = []

    class _TimelineEngine(Engine):
        name = "timeline"

        def supports(self, item):
            return True

        async def download(self, item, options, *, on_progress=None):
            timeline.append(item.item_id)
            return item.item_id == "good"

    import tempfile

    with tempfile.TemporaryDirectory() as td:
        options = DownloadOptions(output_root=Path(td) / "out")
        pipeline = DownloadPipeline(
            engine=_TimelineEngine(), max_concurrent=1,
            max_retries=1, retry_backoff=0.5,
        )

        bad = asyncio.create_task(
            pipeline._download_with_progress(_item("bad"), options, None, "job-bad")
        )
        # Let "bad" take the only slot, fail, and enter its backoff.
        await asyncio.sleep(0.05)
        assert timeline == ["bad"]

        good = asyncio.create_task(
            pipeline._download_with_progress(_item("good"), options, None, "job-good")
        )
        assert await good is True
        assert not bad.done(), "the retrying item should still be backing off"
        assert timeline == ["bad", "good"], (
            "'good' ran during 'bad's backoff -> the semaphore was released"
        )
        assert await bad is False
        assert timeline == ["bad", "good", "bad"]


# ---------------------------------------------------------------------------
# 6. The product default lives on the factory
# ---------------------------------------------------------------------------


def test_factory_enables_retry_by_default():
    """Every surface goes through build_default_pipeline, so retry is on.

    Reading the private attributes is deliberate: the alternative is a live
    download, and what needs guarding is precisely that the factory does not
    silently stop forwarding these.
    """
    pipeline = build_default_pipeline()
    assert DEFAULT_MAX_RETRIES > 0
    assert pipeline._max_retries == DEFAULT_MAX_RETRIES
    assert pipeline._retry_backoff == DEFAULT_RETRY_BACKOFF


def test_factory_retry_is_overridable():
    pipeline = build_default_pipeline(max_retries=0, retry_backoff=9.0)
    assert pipeline._max_retries == 0
    assert pipeline._retry_backoff == 9.0


def test_retry_settings_are_clamped():
    """Nonsense input must not turn into an infinite loop or a negative wait."""
    pipeline = DownloadPipeline(
        engine=_CountingEngine([True]), max_retries=-5, retry_backoff=-1.0
    )
    assert pipeline._max_retries == 0
    assert pipeline._retry_backoff == 0.0
