"""Unit tests for the parser-chain fallback (0.3.7).

0.3.6 had a silent regression: ``pipeline.parse(url)`` ran only the
*highest-priority* matching adapter. When yt-dlp's generic extractor
rejected an unknown URL (``ERROR: Unsupported URL``), the parse fell
through to ``None`` immediately — even though ``GenericAdapter``
(priority=-2, Playwright sniffer) was perfectly able to find the m3u8
inside the page. The user saw "解析结果为空" for any URL yt-dlp didn't
recognize, with no fallback to the sniffer.

The fix walks the chain: highest-priority adapter first, fall through
to the next on ``None`` (or a swallowed data-level error).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# ---------------------------------------------------------------------------
# 1. PlatformRegistry.detect_chain ordering
# ---------------------------------------------------------------------------


@pytest.fixture
def _ensure_adapters_loaded():
    import doubi.platforms  # noqa: F401 触发 self-register
    yield


def test_detect_chain_orders_by_descending_priority(_ensure_adapters_loaded):
    """detected chain must be high→low priority for any http URL."""
    from doubi.core.registry import PlatformRegistry

    chain = PlatformRegistry.detect_chain("https://example.com/something")
    assert chain, "no adapters matched"
    priorities = [a.priority for a in chain]
    assert priorities == sorted(priorities, reverse=True), priorities


def test_detect_chain_includes_generic_for_http_urls(_ensure_adapters_loaded):
    """The Sniffer (GenericAdapter) must be in the chain for plain http URLs."""
    from doubi.core.registry import PlatformRegistry

    chain = PlatformRegistry.detect_chain("https://example.com/something")
    names = [a.name for a in chain]
    assert "ytdlp" in names, names
    assert "generic" in names, "GenericAdapter must be in the chain as fallback"


def test_detect_chain_specific_platform_is_first(_ensure_adapters_loaded):
    """For a B 站 URL, bilibili is first; generic is still in the chain."""
    from doubi.core.registry import PlatformRegistry

    chain = PlatformRegistry.detect_chain("https://www.bilibili.com/video/BV1abc")
    assert chain[0].name == "bilibili"
    # generic must remain last so Playwright is the last resort.
    assert chain[-1].name == "generic"


# ---------------------------------------------------------------------------
# 2. pipeline.parse walks the chain
# ---------------------------------------------------------------------------


def _stub_chain(monkeypatch, parse_results):
    """Replace ``PlatformRegistry.detect_chain`` with a deterministic list.

    ``parse_results`` is an iterable of items the chain will return, one
    per adapter in order. ``None`` = "this adapter couldn't handle the
    URL"; an actual ``MediaItem`` wins and short-circuits the chain.

    Returns the patched chain so the test can inspect what was tried.
    """
    from doubi.core.registry import PlatformRegistry

    tried: list[str] = []
    iterator = iter(parse_results)

    def _chain(_url, *args, **kwargs):
        # Drain the iterator once; subsequent calls return empty so we
        # don't accidentally satisfy multiple tests.
        items = list(iterator)
        chain = []
        for i, _ in enumerate(items):
            chain.append(_FakeAdapter(name=f"fake{i}", priority=-i))
        return chain

    monkeypatch.setattr(PlatformRegistry, "detect_chain", _chain)

    # We also need adapter.parse to consume the items in lockstep.
    # Patch pipeline.parse's loop by rewriting the module-local adapter
    # list. Since pipeline.parse uses detect_chain directly, we
    # instead monkey-patch detect_chain to return adapters whose .parse
    # method pops from the iterator.

    def _chain_with_parse(_url, *args, **kwargs):
        items = list(iterator)
        adapters = []
        for i, item in enumerate(items):
            adapters.append(_FakeAdapter(
                name=f"fake{i}", priority=-i, returns=item, log=tried,
            ))
        return adapters

    monkeypatch.setattr(PlatformRegistry, "detect_chain", _chain_with_parse)
    return tried


class _FakeAdapter:
    def __init__(self, name, priority, returns=None, log=None):
        self.name = name
        self.priority = priority
        self._returns = returns
        self._log = log

    def match_url(self, url):
        return True

    async def parse(self, url):
        if self._log is not None:
            self._log.append(self.name)
        return self._returns


def test_pipeline_parse_returns_first_item(monkeypatch):
    """If the highest-priority adapter succeeds, return its item."""
    from doubi.core.engine_loader import build_default_pipeline
    from doubi.core.models import MediaItem, MediaType, Platform

    item = MediaItem(platform=Platform.UNKNOWN, item_id="x",
                     title="from-first", media_type=MediaType.VIDEO)
    _stub_chain(monkeypatch, [item])

    p = build_default_pipeline()

    async def m():
        return await p.parse("https://example.com/x")

    got = asyncio.run(m())
    assert got is item


def test_pipeline_parse_falls_through_when_first_returns_none(monkeypatch):
    """First adapter None → second tried → its item returned."""
    from doubi.core.engine_loader import build_default_pipeline
    from doubi.core.models import MediaItem, MediaType, Platform

    first_item = MediaItem(platform=Platform.UNKNOWN, item_id="second",
                            title="from-second", media_type=MediaType.VIDEO)
    tried: list[str] = []

    def _chain(_url):
        return [
            _FakeAdapter("first", priority=0, returns=None, log=tried),
            _FakeAdapter("second", priority=-1, returns=first_item, log=tried),
        ]
    monkeypatch.setattr(
        __import__("doubi.core.registry", fromlist=["PlatformRegistry"]).PlatformRegistry,
        "detect_chain", _chain)

    p = build_default_pipeline()

    async def m():
        return await p.parse("https://example.com/x")

    got = asyncio.run(m())
    assert got is first_item
    assert tried == ["first", "second"]


def test_pipeline_parse_returns_none_when_every_adapter_fails(monkeypatch):
    """All adapters return None → pipeline returns None (no exception)."""
    from doubi.core.engine_loader import build_default_pipeline

    def _chain(_url):
        return [_FakeAdapter(f"a{i}", priority=-i, returns=None) for i in range(3)]
    monkeypatch.setattr(
        __import__("doubi.core.registry", fromlist=["PlatformRegistry"]).PlatformRegistry,
        "detect_chain", _chain)

    p = build_default_pipeline()

    async def m():
        return await p.parse("https://example.com/x")

    assert asyncio.run(m()) is None


def test_pipeline_parse_one_adapter_raises_others_continue(monkeypatch):
    """Programming error in one adapter must not kill the chain."""
    from doubi.core.engine_loader import build_default_pipeline
    from doubi.core.models import MediaItem, MediaType, Platform

    good = MediaItem(platform=Platform.UNKNOWN, item_id="third",
                     title="from-third", media_type=MediaType.VIDEO)

    class _Boom:
        name = "boom"
        priority = 0

        def match_url(self, url):
            return True

        async def parse(self, url):
            raise RuntimeError("kaboom")

    def _chain(_url):
        return [_Boom(), _FakeAdapter("none", priority=-1, returns=None),
                _FakeAdapter("good", priority=-2, returns=good)]

    monkeypatch.setattr(
        __import__("doubi.core.registry", fromlist=["PlatformRegistry"]).PlatformRegistry,
        "detect_chain", _chain)

    p = build_default_pipeline()

    async def m():
        return await p.parse("https://example.com/x")

    got = asyncio.run(m())
    assert got is good


def test_pipeline_parse_no_matching_adapter_returns_none(monkeypatch):
    """Empty chain (URL doesn't match anything) → None, not crash."""
    from doubi.core.engine_loader import build_default_pipeline

    def _chain(_url):
        return []
    monkeypatch.setattr(
        __import__("doubi.core.registry", fromlist=["PlatformRegistry"]).PlatformRegistry,
        "detect_chain", _chain)

    p = build_default_pipeline()

    async def m():
        return await p.parse("https://example.com/x")

    assert asyncio.run(m()) is None


# ---------------------------------------------------------------------------
# 3. End-to-end against real adapters (the user's actual URL)
# ---------------------------------------------------------------------------


def test_pipeline_parse_uses_generic_after_ytdlp_rejects(monkeypatch):
    """When yt-dlp returns None, GenericAdapter should get a shot.

    Use only the in-memory chain walking logic; do NOT run yt-dlp or
    Playwright — those would hit the real network. We simulate the
    chain by replacing ``detect_chain`` with a deterministic list of
    adapters that match the real registry's order.
    """
    from doubi.core.engine_loader import build_default_pipeline
    from doubi.core.models import MediaItem, MediaType, Platform

    import doubi.platforms  # noqa: F401
    from doubi.core.registry import PlatformRegistry

    sentinel = MediaItem(platform=Platform.GENERIC, item_id="sniffed",
                         title="sniffed", media_type=MediaType.VIDEO)

    # Replace every adapter's parse with: ytdlp returns None, generic
    # returns the sentinel. Other adapters never run because we only
    # include two chain entries.
    class _FakeAdapter:
        def __init__(self, name, priority, returns):
            self.name = name
            self.priority = priority
            self._returns = returns

        def match_url(self, url):
            return True

        async def parse(self, url):
            return self._returns

    def _chain(_url):
        return [
            _FakeAdapter(name="ytdlp", priority=-1, returns=None),
            _FakeAdapter(name="generic", priority=-2, returns=sentinel),
        ]

    monkeypatch.setattr(PlatformRegistry, "detect_chain", _chain)

    p = build_default_pipeline()

    async def m():
        return await p.parse(
            "https://example-no-extractor.invalid/play/42161-1-1.html")

    got = asyncio.run(m())
    assert got is sentinel
