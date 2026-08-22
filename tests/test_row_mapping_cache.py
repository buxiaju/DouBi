"""Test the row→top_idx cache survives multiple expand/collapse cycles.

Specifically:
  - parse 1 season with 4 sections × 3 episodes
  - expand section 0 → assert row mappings
  - expand section 0 episode 0 (its pages) → assert row mappings
  - collapse section 0 → assert clean state
  - re-expand section 0 → mapping must be consistent (no stale entries
    from the previous expansion)
  - expand section 2 → mapping must include both expansions

This guards against the "row mapping goes stale after re-expanding"
class of bugs that confuse the GUI (right-click menu acts on the
wrong item, 「下载选中」 counts the wrong rows).
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _require_gui() -> None:
    try:
        import PySide6  # noqa: F401
    except ImportError as exc:
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


def _make_create_task_sync(monkeypatch, page_module):
    import asyncio as _asyncio

    def _create_task(coro):
        return _asyncio.run(coro)

    monkeypatch.setattr(page_module.asyncio, "create_task", _create_task)


def _make_season():
    """1 season with 4 sections × 3 episodes; episode 0 has 5 pages."""
    from doubi.core.models import (
        Platform, MediaItem, Author, MediaType,
    )
    sections = []
    episodes = []
    pages = []
    for s in range(4):
        eps = []
        for e in range(3):
            ep = MediaItem(
                platform=Platform.BILIBILI, item_id=f"ep{s}{e}",
                title=f"ep{s}{e}", author=Author(name="UP"),
                media_type=MediaType.VIDEO,
                source_url=f"https://www.bilibili.com/video/ep{s}{e}",
                extra={"_from_ugc_season": True},
            )
            eps.append(ep)
            episodes.append(ep)
            if s == 0 and e == 0:
                for p in range(5):
                    pages.append(
                        MediaItem(
                            platform=Platform.BILIBILI, item_id=f"pg{p}",
                            title=f"p{p}", author=Author(name="UP"),
                            media_type=MediaType.VIDEO,
                            source_url=f"https://www.bilibili.com/video/ep00?p={p+1}",
                            extra={"_from_ugc_season": True},
                        ),
                    )
        sections.append(
            MediaItem(
                platform=Platform.BILIBILI, item_id=f"sec{s}",
                title=f"sec{s}", author=Author(name="UP"),
                media_type=MediaType.COLLECTION,
                source_url=f"https://www.bilibili.com/video/BVfake",
                children=eps,
                extra={
                    "_from_ugc_season_section": True,
                    "section_index": s,
                    "section_title": f"sec{s}",
                    "collection_title": "合集",
                    "episode_count": 3,
                },
            ),
        )
    season = MediaItem(
        platform=Platform.BILIBILI, item_id="season", title="合集",
        author=Author(name="UP"), media_type=MediaType.COLLECTION,
        source_url="https://www.bilibili.com/video/BVfake",
        children=sections,
        extra={"is_ugc_season": True},
    )
    return season, sections, episodes, pages


def _stub_pipeline(monkeypatch, page, season):
    async def _fake_parse_and_expand(url, *, strategy=None, max_count=0):
        return season, list(season.children)
    monkeypatch.setattr(page._pipeline, "parse_and_expand", _fake_parse_and_expand)


def _stub_adapter(monkeypatch, page, sections, pages):
    """Stub the Bilibili adapter so expand_section / expand_episode_pages
    return canned data without network."""
    from doubi.core.models import Platform
    from doubi.core.registry import PlatformRegistry

    # Pre-compute one immutable list per section so the stub can
    # return the same episodes every time ``expand_section`` is
    # called, even after the page's ``_collapse_section`` resets
    # ``section_item.children`` to ``[]``.
    section_episodes = {s.item_id: list(s.children) for s in sections}

    async def _fake_expand_section(section_item):
        eps = list(section_episodes[section_item.item_id])
        section_item.children = eps
        return eps

    async def _fake_expand_pages(episode_item):
        if episode_item.item_id == "ep00":
            return list(pages)
        return [episode_item]

    fake_adapter = type("FakeAdapter", (), {
        "expand_section": staticmethod(_fake_expand_section),
        "expand_episode_pages": staticmethod(_fake_expand_pages),
    })
    monkeypatch.setattr(
        PlatformRegistry, "get",
        lambda platform: fake_adapter if platform is Platform.BILIBILI else None,
    )


def test_row_mapping_full_cycle(qapp, monkeypatch):
    import doubi.ui.pages.parse as page_module

    page = _make_page(qapp)
    _make_create_task_sync(monkeypatch, page_module)
    season, sections, episodes, pages = _make_season()
    _stub_pipeline(monkeypatch, page, season)
    _stub_adapter(monkeypatch, page, sections, pages)

    # ---- parse ---------------------------------------------------------
    page.url_input.setPlainText("https://www.bilibili.com/video/BVfake")
    page._on_parse_clicked()
    qapp.processEvents()

    assert page.result_table.rowCount() == 4  # only the 4 section rows
    assert page._row_to_top_idx == {0: 0, 1: 1, 2: 2, 3: 3}
    assert page._top_to_row == {0: 0, 1: 1, 2: 2, 3: 3}

    # ---- expand section 0 ----------------------------------------------
    asyncio.run(page._expand_section_row(0, sections[0]))
    qapp.processEvents()
    # rows: 0=sec0, 1=ep00, 2=ep01, 3=ep02, 4=sec1, 5=sec2, 6=sec3
    assert page.result_table.rowCount() == 7
    expected = {0: 0, 1: 0, 2: 0, 3: 0, 4: 1, 5: 2, 6: 3}
    assert page._row_to_top_idx == expected, page._row_to_top_idx

    # ---- expand episode 0 (rows 1) → its 5 pages -----------------------
    asyncio.run(page._expand_episode_row(1, episodes[0]))
    qapp.processEvents()
    # rows: 0=sec0, 1=ep00, 2..6=pages, 7=ep01, 8=ep02, 9=sec1, 10=sec2, 11=sec3
    assert page.result_table.rowCount() == 12
    expected = {
        0: 0, 1: 0,
        2: 0, 3: 0, 4: 0, 5: 0, 6: 0,  # pages
        7: 0, 8: 0,                       # ep01, ep02
        9: 1, 10: 2, 11: 3,               # remaining sections
    }
    assert page._row_to_top_idx == expected, page._row_to_top_idx

    # ---- collapse section 0 --------------------------------------------
    page._collapse_section(0)
    qapp.processEvents()
    assert page.result_table.rowCount() == 4
    assert page._row_to_top_idx == {0: 0, 1: 1, 2: 2, 3: 3}
    # Stale page-expansion keys must be gone too:
    assert page._expanded_episode_rows == {}

    # ---- re-expand section 0: mapping must reflect fresh state -------
    asyncio.run(page._expand_section_row(0, sections[0]))
    qapp.processEvents()
    assert page.result_table.rowCount() == 7
    assert page._row_to_top_idx == {0: 0, 1: 0, 2: 0, 3: 0, 4: 1, 5: 2, 6: 3}

    # ---- collapse the re-expanded section 0 again ---------------------
    page._collapse_section(0)
    qapp.processEvents()
    assert page._row_to_top_idx == {0: 0, 1: 1, 2: 2, 3: 3}

    # ---- expand section 2, then section 0, expect both sets in mapping
    # The actual row of section 2 is whatever ``_top_to_row`` says
    # for top_idx 2 at this point (after the re-collapse the table
    # is back to the original 4 rows, so section 2 is at row 2).
    sec2_row = page._top_to_row[2]
    asyncio.run(page._expand_section_row(sec2_row, sections[2]))
    qapp.processEvents()
    # rows: 0=sec0, 1=sec1, 2=sec2, 3=ep20, 4=ep21, 5=ep22, 6=sec3
    assert page._row_to_top_idx == {
        0: 0, 1: 1, 2: 2, 3: 2, 4: 2, 5: 2, 6: 3,
    }

    sec0_row = page._top_to_row[0]
    asyncio.run(page._expand_section_row(sec0_row, sections[0]))
    qapp.processEvents()
    # rows: 0=sec0, 1=ep00, 2=ep01, 3=ep02, 4=sec1, 5=sec2, 6=ep20,
    #       7=ep21, 8=ep22, 9=sec3
    assert page._row_to_top_idx == {
        0: 0, 1: 0, 2: 0, 3: 0,       # sec 0 + its eps
        4: 1,                          # sec 1
        5: 2, 6: 2, 7: 2, 8: 2,       # sec 2 + its eps
        9: 3,                          # sec 3
    }


def _titles(page) -> list[str]:
    """Column-2 text of every table row, stripped of decoration.

    Section rows are rendered as ``▸ sec0  (3 分集)``; we normalise
    that back to the bare title so the expected lists stay readable.
    """
    import re
    out = []
    for r in range(page.result_table.rowCount()):
        cell = page.result_table.item(r, 2)
        text = (cell.text() if cell is not None else "").strip()
        text = re.sub(r"^[▸▾]\s*", "", text)
        text = re.sub(r"\s*\(\d+ 分集\)$", "", text)
        out.append(text)
    return out


def test_interleaved_page_rows_resolve_correctly(qapp, monkeypatch):
    """Expanding an episode's pages must not break the rows below it.

    ``_expand_episode_row`` inserts the page rows *directly beneath*
    the episode row, so the physical layout is interleaved::

        sec0, ep00, pg0..pg4, ep01, ep02, sec1, sec2, sec3

    Any code that reconstructs "which episode owns row N" by doing
    ``row - section_row - 1`` silently breaks here: ep01 lands at
    offset 6 while the section only has 3 episodes, and the page rows
    themselves land at offsets 1..5 — two of which (1 and 2) look like
    valid episode indices. This test pins the correct answers.
    """
    import doubi.ui.pages.parse as page_module

    page = _make_page(qapp)
    _make_create_task_sync(monkeypatch, page_module)
    season, sections, episodes, pages = _make_season()
    _stub_pipeline(monkeypatch, page, season)
    _stub_adapter(monkeypatch, page, sections, pages)

    page.url_input.setPlainText("https://www.bilibili.com/video/BVfake")
    page._on_parse_clicked()
    qapp.processEvents()

    asyncio.run(page._expand_section_row(0, sections[0]))
    qapp.processEvents()
    asyncio.run(page._expand_episode_row(1, episodes[0]))
    qapp.processEvents()

    # Sanity: the interleaved layout is what we think it is.
    assert _titles(page) == [
        "sec0", "ep00", "p0", "p1", "p2", "p3", "p4",
        "ep01", "ep02", "sec1", "sec2", "sec3",
    ], _titles(page)

    # ---- episode keys --------------------------------------------------
    # Only the three real episode rows may yield an episode key, and
    # each must map to its own child_idx.
    assert page._episode_key_for_row(1) == (0, 0)
    assert page._episode_key_for_row(7) == (0, 1)
    assert page._episode_key_for_row(8) == (0, 2)
    # Page rows are NOT episode rows.
    for r in range(2, 7):
        assert page._episode_key_for_row(r) is None, r
    # Section rows are not episode rows either.
    for r in (0, 9, 10, 11):
        assert page._episode_key_for_row(r) is None, r

    # ---- owning episode for every row ----------------------------------
    assert page._resolve_episode_for_row(1) is episodes[0]
    for r in range(2, 7):
        # page rows belong to ep00
        assert page._resolve_episode_for_row(r) is episodes[0], r
    assert page._resolve_episode_for_row(7) is episodes[1]
    assert page._resolve_episode_for_row(8) is episodes[2]
    assert page._resolve_episode_for_row(0) is None
    for r in (9, 10, 11):
        assert page._resolve_episode_for_row(r) is None, r

    # ---- the expanded-pages key must point at ep00, not a page row ----
    assert set(page._expanded_episode_rows) == {(0, 0)}


def test_collapse_section_removes_exactly_the_child_rows(qapp, monkeypatch):
    """Collapsing a section with interleaved page rows must remove the
    right rows — not merely the right *number* of rows.

    The old implementation computed ``ep_row = row + 1 + child_idx``,
    which produces duplicate row numbers once pages are interleaved
    ([1, 2..6, 2, 3] for 3 episodes with 5 pages under the first).
    Deleting 8 rows from a 12-row table happens to leave 4 rows, so a
    ``rowCount`` assertion passes by accident. Asserting the surviving
    titles catches it.
    """
    import doubi.ui.pages.parse as page_module

    page = _make_page(qapp)
    _make_create_task_sync(monkeypatch, page_module)
    season, sections, episodes, pages = _make_season()
    _stub_pipeline(monkeypatch, page, season)
    _stub_adapter(monkeypatch, page, sections, pages)

    page.url_input.setPlainText("https://www.bilibili.com/video/BVfake")
    page._on_parse_clicked()
    qapp.processEvents()

    # Expand section 1 first so section 0's children are not the only
    # inserted rows — collapsing section 0 must leave section 1's
    # expansion untouched.
    asyncio.run(page._expand_section_row(1, sections[1]))
    qapp.processEvents()
    asyncio.run(page._expand_section_row(0, sections[0]))
    qapp.processEvents()
    # rows: 0=sec0, 1=ep00, 2=ep01, 3=ep02, 4=sec1, 5=ep10, 6=ep11,
    #       7=ep12, 8=sec2, 9=sec3
    asyncio.run(page._expand_episode_row(1, episodes[0]))
    qapp.processEvents()
    assert _titles(page) == [
        "sec0", "ep00", "p0", "p1", "p2", "p3", "p4", "ep01", "ep02",
        "sec1", "ep10", "ep11", "ep12", "sec2", "sec3",
    ], _titles(page)

    page._collapse_section(0)
    qapp.processEvents()

    # Section 0's 3 episodes + 5 pages are gone; section 1 keeps its own.
    assert _titles(page) == [
        "sec0", "sec1", "ep10", "ep11", "ep12", "sec2", "sec3",
    ], _titles(page)
    assert page._expanded_episode_rows == {}
    assert set(page._expanded_rows) == {(1,)}
    assert page._row_to_top_idx == {
        0: 0, 1: 1, 2: 1, 3: 1, 4: 1, 5: 2, 6: 3,
    }


def test_download_targets_with_interleaved_pages(qapp, monkeypatch):
    """Checking every row of an expanded tree must enqueue each video
    exactly once — ep00's 5 pages plus ep01 and ep02, and never the
    section container itself."""
    import doubi.ui.pages.parse as page_module

    page = _make_page(qapp)
    _make_create_task_sync(monkeypatch, page_module)
    season, sections, episodes, pages = _make_season()
    _stub_pipeline(monkeypatch, page, season)
    _stub_adapter(monkeypatch, page, sections, pages)

    page.url_input.setPlainText("https://www.bilibili.com/video/BVfake")
    page._on_parse_clicked()
    qapp.processEvents()
    asyncio.run(page._expand_section_row(0, sections[0]))
    qapp.processEvents()
    asyncio.run(page._expand_episode_row(1, episodes[0]))
    qapp.processEvents()

    # Only section 0's subtree, no other section rows.
    rows = [1, 2, 3, 4, 5, 6, 7, 8]
    targets = asyncio.run(page._resolve_download_targets(rows))
    ids = [t.item_id for t in targets]
    assert ids == [
        "pg0", "pg1", "pg2", "pg3", "pg4", "ep01", "ep02",
    ], ids
    assert all(not t.is_container() for t in targets)


def test_only_section_rows_are_section_rows(qapp, monkeypatch):
    """Episode/page rows must never be treated as section rows.

    ``_resolve_top_item_for_row`` deliberately maps a child row back to
    its owning *section* — that is what ``_row_to_top_idx`` encodes. So
    deciding "is this a section row?" from the resolved item alone
    reports every episode and page as a section. In the GUI that made
    右键 an episode offer 「折叠分类」, which collapsed the whole
    category and took the sibling episodes with it.
    """
    import doubi.ui.pages.parse as page_module

    page = _make_page(qapp)
    _make_create_task_sync(monkeypatch, page_module)
    season, sections, episodes, pages = _make_season()
    _stub_pipeline(monkeypatch, page, season)
    _stub_adapter(monkeypatch, page, sections, pages)

    page.url_input.setPlainText("https://www.bilibili.com/video/BVfake")
    page._on_parse_clicked()
    qapp.processEvents()
    asyncio.run(page._expand_section_row(0, sections[0]))
    qapp.processEvents()
    asyncio.run(page._expand_episode_row(1, episodes[0]))
    qapp.processEvents()

    # layout: 0=sec0, 1=ep00, 2..6=pages, 7=ep01, 8=ep02, 9..11=sec1..3
    assert page._is_section_row(0) is True
    for r in (9, 10, 11):
        assert page._is_section_row(r) is True, r
    # Episodes and pages are not sections, even though they resolve to
    # a section item via _row_to_top_idx.
    for r in range(1, 9):
        assert page._is_section_row(r) is False, r
        assert page._resolve_top_item_for_row(r) is sections[0], r


def test_collapse_section_ignores_non_top_rows(qapp, monkeypatch):
    """A stray ``_collapse_section`` on a child row must be a no-op.

    Child rows share their section's ``top_idx``, so without a
    row-identity guard collapsing "from" an episode row would pop
    ``_expanded_rows[(0,)]`` and then delete rows starting at
    ``episode_row + 1`` — eating the page rows and sibling episodes and
    leaving the table structurally inconsistent with the caches.
    """
    import doubi.ui.pages.parse as page_module

    page = _make_page(qapp)
    _make_create_task_sync(monkeypatch, page_module)
    season, sections, episodes, pages = _make_season()
    _stub_pipeline(monkeypatch, page, season)
    _stub_adapter(monkeypatch, page, sections, pages)

    page.url_input.setPlainText("https://www.bilibili.com/video/BVfake")
    page._on_parse_clicked()
    qapp.processEvents()
    asyncio.run(page._expand_section_row(0, sections[0]))
    qapp.processEvents()
    asyncio.run(page._expand_episode_row(1, episodes[0]))
    qapp.processEvents()

    before_titles = _titles(page)
    before_expanded = dict(page._expanded_rows)
    before_pages = dict(page._expanded_episode_rows)

    # Every child row (episodes 1/7/8 and pages 2..6) must be ignored.
    for row in range(1, 9):
        page._collapse_section(row)
        qapp.processEvents()
        assert _titles(page) == before_titles, row
        assert page._expanded_rows == before_expanded, row
        assert page._expanded_episode_rows == before_pages, row

    # The real section row still collapses normally afterwards.
    page._collapse_section(0)
    qapp.processEvents()
    assert _titles(page) == ["sec0", "sec1", "sec2", "sec3"]
    assert page._expanded_rows == {}
    assert page._expanded_episode_rows == {}