"""Tests for the GUI's parse-and-pick flow.

M5.3 regression: the "解析" button used to drop the parent item for
single-video URLs (``parse_and_expand`` returns ``(item, [])`` for
non-containers) so the picker table always showed empty. The fix is
in the page's ``_on_parse_clicked``: include the parent when no
children were produced.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Headless Qt for the GUI page tests
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _require_gui() -> None:
    try:
        import PySide6  # noqa: F401
    except ImportError as exc:   # pragma: no cover
        pytest.skip(f"PySide6 not installed: {exc}")


@pytest.fixture(scope="module")
def qapp():
    _require_gui()
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


def _make_page(qapp):
    from doubi.ui.pages.parse import build_parse_widgets
    cls, _ = build_parse_widgets()
    return cls()


def _stub_pipeline(monkeypatch, *, single_item, container_children):
    """Patch the page's pipeline to return canned results.

    Three URL shapes are recognised:
    * ``/list/`` or ``space.bilibili.com`` → USER container with the
      given children (used by the existing two tests).
    * ``/video/BVfake`` and ``single_item`` is a container with its
      own children → return ``(single_item, single_item.children)`` so
      the picker renders the section rows (ugc_season test).
    * everything else → return ``(single_item, [])`` so the picker
      shows one row for the single video.
    """
    async def _fake_parse_and_expand(url, *, strategy=None, max_count=0):
        if "/list/" in url or "space.bilibili.com" in url:
            from doubi.core.models import Platform, MediaItem, Author, MediaType
            parent = MediaItem(
                platform=Platform.BILIBILI, item_id="c1", title="c1",
                author=Author(), media_type=MediaType.USER, source_url=url,
            )
            return parent, list(container_children)
        if single_item is not None and getattr(single_item, "children", None):
            return single_item, list(single_item.children)
        return single_item, []

    return _fake_parse_and_expand


def _make_create_task_sync(monkeypatch, page_module):
    """Replace ``asyncio.create_task`` inside the page module with a
    synchronous runner. The GUI uses qasync in production where
    ``create_task`` schedules onto the running event loop, but in the
    test we have no running loop so we want ``asyncio.run`` instead.
    """
    import asyncio as _asyncio

    def _create_task(coro):
        return _asyncio.run(coro)

    monkeypatch.setattr(page_module, "asyncio", _asyncio)
    # Patch the global asyncio reference inside the closure
    # (the page captures it via ``import asyncio`` at module level).
    monkeypatch.setattr(page_module.asyncio, "create_task", _create_task)


def _run_and_drain(page, qapp):
    """Call the parse action and synchronously drain the result."""
    import asyncio
    page._on_parse_clicked()
    # _on_parse_clicked is sync and creates a task via create_task;
    # our patched version runs it inline. processEvents in case
    # any Qt signals are queued.
    qapp.processEvents()


async def _wait_for_tasks(qapp, timeout: float = 2.0) -> None:
    """Process Qt events + drain asyncio tasks until they're all done."""
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        pending = [t for t in asyncio.all_tasks() if not t.done()]
        if not pending:
            return
        await asyncio.gather(*pending, return_exceptions=True)
    qapp.processEvents()


def test_single_video_appears_in_picker_table(qapp, monkeypatch):
    """Single video URLs (no children) must still surface in the table."""
    from doubi.core.models import Platform, MediaItem, Author, MediaType
    from doubi.ui.pages import parse as page_module

    page = _make_page(qapp)
    _make_create_task_sync(monkeypatch, page_module)
    item = MediaItem(
        platform=Platform.BILIBILI, item_id="BV1xx", title="test",
        author=Author(name="u"), media_type=MediaType.VIDEO,
        source_url="https://www.bilibili.com/video/BV1xx",
    )
    monkeypatch.setattr(
        page._pipeline, "parse_and_expand",
        _stub_pipeline(
            monkeypatch, single_item=item, container_children=[],
        ),
    )

    page.url_input.setPlainText("https://www.bilibili.com/video/BV1xx")
    _run_and_drain(page, qapp)

    assert page.result_table.rowCount() == 1, (
        "single video must produce one row in the picker table"
    )
    assert page._parsed_items[0].item_id == "BV1xx"


def test_container_children_appear_in_picker_table(qapp, monkeypatch):
    from doubi.core.models import Platform, MediaItem, Author, MediaType
    from doubi.ui.pages import parse as page_module

    page = _make_page(qapp)
    _make_create_task_sync(monkeypatch, page_module)
    children = [
        MediaItem(
            platform=Platform.BILIBILI, item_id=f"BV{i}", title=f"v{i}",
            author=Author(), media_type=MediaType.VIDEO,
            source_url=f"https://www.bilibili.com/video/BV{i}",
        )
        for i in range(3)
    ]
    monkeypatch.setattr(
        page._pipeline, "parse_and_expand",
        _stub_pipeline(
            monkeypatch, single_item=None, container_children=children,
        ),
    )

    page.url_input.setPlainText("https://space.bilibili.com/123")
    _run_and_drain(page, qapp)

    assert page.result_table.rowCount() == 3
    assert [it.item_id for it in page._parsed_items] == ["BV0", "BV1", "BV2"]


def test_section_expand_collapse_reexpand_cycle(qapp, monkeypatch):
    """End-to-end UI exercise for the ugc_season three-level picker:

    1. The picker shows just the section rows.
    2. Right-clicking a section → expand_section runs → episode rows
       are inserted beneath it.
    3. Right-clicking the same row again → collapse removes the
       inserted rows AND clears the section's children so the toggle
       can fire a third time.
    4. A re-expand after collapse must produce the same episode rows.
    """
    import asyncio
    from doubi.core.models import Platform, MediaItem, Author, MediaType
    from doubi.ui.pages import parse as page_module

    page = _make_page(qapp)
    _make_create_task_sync(monkeypatch, page_module)

    # Build a synthetic season container with two sections, each
    # containing two episodes. We sidestep the real Bilibili adapter
    # so the test stays fully offline.
    section_a = MediaItem(
        platform=Platform.BILIBILI,
        item_id="ugcseason1#s1", title="模拟电子技术",
        author=Author(name="UP"), media_type=MediaType.COLLECTION,
        source_url="https://www.bilibili.com/video/BVfake",
        children=[],
        extra={
            "_from_ugc_season_section": True,
            "section_index": 0,
            "section_title": "模拟电子技术",
            "collection_title": "高分必备660！",
            "episode_count": 2,
        },
    )
    section_b = MediaItem(
        platform=Platform.BILIBILI,
        item_id="ugcseason1#s2", title="信号与系统",
        author=Author(name="UP"), media_type=MediaType.COLLECTION,
        source_url="https://www.bilibili.com/video/BVfake",
        children=[],
        extra={
            "_from_ugc_season_section": True,
            "section_index": 1,
            "section_title": "信号与系统",
            "collection_title": "高分必备660！",
            "episode_count": 1,
        },
    )
    season = MediaItem(
        platform=Platform.BILIBILI,
        item_id="ugcseason1", title="高分必备660！",
        author=Author(name="UP"), media_type=MediaType.COLLECTION,
        source_url="https://www.bilibili.com/video/BVfake",
        children=[section_a, section_b],
        extra={"is_ugc_season": True},
    )

    monkeypatch.setattr(
        page._pipeline, "parse_and_expand",
        lambda url, *, strategy=None, max_count=0: _stub_pipeline(
            monkeypatch, single_item=season, container_children=[section_a, section_b],
        )(url, strategy=strategy, max_count=max_count),
    )

    page.url_input.setPlainText("https://www.bilibili.com/video/BVfake")
    _run_and_drain(page, qapp)

    # Initial render: 2 rows (sections only).
    assert page.result_table.rowCount() == 2
    assert {it.item_id for it in page._parsed_items} == {"ugcseason1#s1", "ugcseason1#s2"}

    # Build a fake adapter that hands out episodes for each section.
    episodes_by_section = {
        "ugcseason1#s1": [
            MediaItem(
                platform=Platform.BILIBILI, item_id="eps_a_1", title="1-2章",
                author=Author(name="UP"), media_type=MediaType.VIDEO,
                source_url="https://www.bilibili.com/video/eps_a_1",
                extra={"_from_ugc_season": True, "section_title": "模拟电子技术"},
            ),
            MediaItem(
                platform=Platform.BILIBILI, item_id="eps_a_2", title="3-5章",
                author=Author(name="UP"), media_type=MediaType.VIDEO,
                source_url="https://www.bilibili.com/video/eps_a_2",
                extra={"_from_ugc_season": True, "section_title": "模拟电子技术"},
            ),
        ],
        "ugcseason1#s2": [
            MediaItem(
                platform=Platform.BILIBILI, item_id="eps_b_1", title="第1-2章",
                author=Author(name="UP"), media_type=MediaType.VIDEO,
                source_url="https://www.bilibili.com/video/eps_b_1",
                extra={"_from_ugc_season": True, "section_title": "信号与系统"},
            ),
        ],
    }
    call_counts = {"expand": 0}

    async def _fake_expand(section_item):
        call_counts["expand"] += 1
        eps = episodes_by_section[section_item.item_id]
        section_item.children = list(eps)
        return list(eps)

    fake_adapter = type("FakeAdapter", (), {"expand_section": staticmethod(_fake_expand)})
    from doubi.core.models import Platform as _P
    from doubi.core.registry import PlatformRegistry as _Registry
    monkeypatch.setattr(
        _Registry, "get",
        lambda platform: fake_adapter if platform is _P.BILIBILI else None,
    )

    # ---- expand section A (right-click menu → _expand_section_row) ----
    asyncio.run(page._expand_section_row(0, section_a))
    qapp.processEvents()
    assert page.result_table.rowCount() == 4, (
        "expand must insert the 2 episode rows under the section"
    )
    assert section_a.children, "section_item.children must be populated"
    assert call_counts["expand"] == 1

    # ---- collapse section A (right-click menu → _collapse_section) ----
    page._collapse_section(0)
    qapp.processEvents()
    assert page.result_table.rowCount() == 2, (
        "collapse must remove the inserted episode rows"
    )
    assert section_a.children == [], (
        "section_item.children must be cleared so a re-expand can run"
    )
    assert 0 not in page._expanded_rows

    # ---- re-expand section A (toggle must fire again) ----
    asyncio.run(page._expand_section_row(0, section_a))
    qapp.processEvents()
    assert page.result_table.rowCount() == 4, (
        "re-expand must succeed — the toggle bug would leave the table at 2 rows"
    )
    assert call_counts["expand"] == 2, (
        "expand_section must be invoked twice across the cycle"
    )
    assert [it.item_id for it in page._expanded_rows[(0,)]] == ["eps_a_1", "eps_a_2"]

    # ---- section B (row index 3 after A's 2 episodes: 0=A,1=eps,2=eps,3=B)
    # ---- must also expand -----------------------------------------------
    asyncio.run(page._expand_section_row(3, section_b))
    qapp.processEvents()
    assert page.result_table.rowCount() == 5
    assert call_counts["expand"] == 3

    # ---- collapse the already-expanded A: second time also works ----
    page._collapse_section(0)
    qapp.processEvents()
    # Table shrinks: -2 from A; B's row was at 3, now shifts to 1.
    assert page.result_table.rowCount() == 3
    assert section_a.children == []
    asyncio.run(page._expand_section_row(0, section_a))
    qapp.processEvents()
    assert page.result_table.rowCount() == 5
    assert call_counts["expand"] == 4


def test_download_selected_skips_section_rows(qapp, monkeypatch):
    """Regression: clicking 「下载选中」 with the season container's
    section rows pre-checked must NOT add the section itself to the
    download queue. Only its episode children should be enqueued.
    """
    import asyncio
    from doubi.core.models import Platform, MediaItem, Author, MediaType
    from doubi.ui.pages import parse as page_module

    page = _make_page(qapp)
    _make_create_task_sync(monkeypatch, page_module)

    section = MediaItem(
        platform=Platform.BILIBILI,
        item_id="ugcseason1#s1", title="模拟电子技术",
        author=Author(name="UP"), media_type=MediaType.COLLECTION,
        source_url="https://www.bilibili.com/video/BVfake",
        children=[],
        extra={
            "_from_ugc_season_section": True,
            "section_index": 0,
            "section_title": "模拟电子技术",
            "collection_title": "高分必备660！",
        },
    )
    season = MediaItem(
        platform=Platform.BILIBILI,
        item_id="ugcseason1", title="高分必备660！",
        author=Author(name="UP"), media_type=MediaType.COLLECTION,
        source_url="https://www.bilibili.com/video/BVfake",
        children=[section],
        extra={"is_ugc_season": True},
    )

    monkeypatch.setattr(
        page._pipeline, "parse_and_expand",
        lambda url, *, strategy=None, max_count=0: _stub_pipeline(
            monkeypatch, single_item=season, container_children=[section],
        )(url, strategy=strategy, max_count=max_count),
    )

    page.url_input.setPlainText("https://www.bilibili.com/video/BVfake")
    _run_and_drain(page, qapp)
    assert page.result_table.rowCount() == 1

    # Stub adapter so the auto-expand on download produces real episodes.
    eps = [
        MediaItem(
            platform=Platform.BILIBILI, item_id=f"eps{i}", title=f"ep{i}",
            author=Author(name="UP"), media_type=MediaType.VIDEO,
            source_url=f"https://www.bilibili.com/video/eps{i}",
            extra={"_from_ugc_season": True},
        )
        for i in range(2)
    ]

    async def _fake_expand(section_item):
        section_item.children = list(eps)
        return list(eps)

    fake_adapter = type("FakeAdapter", (), {"expand_section": staticmethod(_fake_expand)})
    from doubi.core.models import Platform as _P
    from doubi.core.registry import PlatformRegistry as _Registry
    monkeypatch.setattr(
        _Registry, "get",
        lambda platform: fake_adapter if platform is _P.BILIBILI else None,
    )

    # Replace task_manager.add with a recorder so we can inspect the queue.
    captured: list[MediaItem] = []

    def _fake_add(item, options):
        captured.append(item)

    page._task_manager = type("FakeTM", (), {"add": staticmethod(_fake_add)})()

    # Section rows are tristate containers — they never appear in
    # ``_checked_rows`` themselves. Click 「全选」 to mark every
    # child row (which forces an auto-expand via _resolve_download_targets)
    # and then 「下载选中」.
    page._select_all()
    qapp.processEvents()
    page._download_selected()
    qapp.processEvents()
    qapp.processEvents()

    assert len(captured) == 2, (
        f"section row must not be enqueued; got {len(captured)} items: "
        f"{[it.item_id for it in captured]}"
    )
    assert all(it.item_id.startswith("eps") for it in captured)
    assert not any(it.item_id == "ugcseason1#s1" for it in captured)
