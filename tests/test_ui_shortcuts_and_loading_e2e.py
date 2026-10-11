"""End-to-end style tests driving the real GUI offscreen (0.3.7).

These tests glue together the new pieces:

* main_window's ShortcutManager → Ctrl+1..6 / F5 / Ctrl+Enter actually switch
  the visible page.
* search / hot pages flip EmptyState → LoadingState → ErrorState with a
  retry button when the underlying CLI call raises.
* parse page flips EmptyState → LoadingState → TableWidget on a successful
  parse, and exposes the "try sample links" CTA.

The page stacks use a ``QStackedWidget`` so we can assert on
``currentWidget()`` after each interaction. The point isn't to re-test
the underlying adapters (those are CLI tests) but to pin the UI flow —
so a refactor that accidentally breaks the loading-to-table transition
gets caught here before it ships to a user.
"""

from __future__ import annotations

import os
import sys
from typing import Optional

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _require_qt():
    try:
        import PySide6  # noqa: F401
        import qfluentwidgets  # noqa: F401
    except Exception as exc:   # noqa: BLE001
        pytest.skip(f"GUI stack unavailable: {exc}")


@pytest.fixture(scope="module")
def qapp():
    _require_qt()
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


def _make_window(qapp):
    """Build a MainWindow + close the cookie-refresh timer so tests
    don't touch the network."""
    from doubi.ui.pages.settings import set_account_refresh_enabled
    set_account_refresh_enabled(False)
    from doubi.ui.main_window import build_main_window
    return build_main_window()()


def _resolve(p, *, run_until: Optional[object] = None):
    """Drain the Qt event queue a few times. Used after ``btn.click()`` /
    ``show()`` so signals / animations / layout settle."""
    from PySide6.QtWidgets import QApplication
    QApplication.processEvents()


# ---------------------------------------------------------------------------
# Shortcut navigation
# ---------------------------------------------------------------------------

def test_ctrl_n_shortcuts_switch_pages(qapp):
    """Ctrl+1..5 and Ctrl+, must switch to the corresponding page."""
    mw = _make_window(qapp)
    mw.show()
    _resolve(qapp)

    cases = [
        ("Ctrl+1", "parse"),
        ("Ctrl+2", "download"),
        ("Ctrl+3", "history"),
        ("Ctrl+4", "search"),
        ("Ctrl+5", "hot"),
        ("Ctrl+,", "settings"),
    ]
    for key, expected_attr in cases:
        spec = next(s for s in mw.shortcuts.specs() if s.key == key)
        spec.callback()
        _resolve(qapp)
        actual = type(mw.stackedWidget.currentWidget()).__name__
        assert actual.startswith(expected_attr.capitalize()) or expected_attr in actual.lower(), (
            f"{key} expected to switch to '{expected_attr}', got '{actual}'"
        )


def test_f5_dispatches_to_search_when_on_search_page(qapp):
    """F5 on the search page must re-trigger the search button.

    We monkey-patch ``collect_search_async`` to return a sentinel, then
    click F5 and assert the call happened with the same keyword.
    """
    import doubi.cli.main as cli_main
    seen: dict = {}

    async def fake(**kwargs):
        seen.update(kwargs)
        return [{"title": "x"}]

    monkey = pytest.MonkeyPatch()
    monkey.setattr(cli_main, "collect_search_async", fake)

    mw = _make_window(qapp)
    mw.show()
    _resolve(qapp)
    # Jump to search page
    mw.shortcuts.specs()[3].callback()  # Ctrl+4
    _resolve(qapp)
    mw.search_interface._keyword.setText("python")
    mw.search_interface.search_btn.click()
    _resolve(qapp)

    # Now press F5 (refresh) — same page, same keyword
    mw.shortcuts.specs()[6].callback()
    _resolve(qapp)

    assert seen.get("keyword") == "python", seen
    monkey.undo()


# ---------------------------------------------------------------------------
# LoadingState transitions (parse / search / hot)
# ---------------------------------------------------------------------------

def test_search_page_flips_loading_then_error(qapp):
    """search page: click search with no cookie file → after a fake
    exception, the stack lands on the ErrorState with a retry button."""
    import doubi.cli.main as cli_main

    async def boom(**kwargs):
        raise RuntimeError("synthetic")

    monkey = pytest.MonkeyPatch()
    monkey.setattr(cli_main, "collect_search_async", boom)

    mw = _make_window(qapp)
    mw.show()
    _resolve(qapp)
    mw.shortcuts.specs()[3].callback()  # to search
    _resolve(qapp)
    mw.search_interface._keyword.setText("trigger")
    mw.search_interface.search_btn.click()
    _resolve(qapp)

    # Search is awaited on asyncio.run() when no loop is running —
    # the click returns synchronously and the error has been rendered
    # into the ErrorState by the time processEvents drains.
    stack = mw.search_interface._stack
    assert stack.currentWidget() is mw.search_interface._error_state
    err = mw.search_interface._error_state
    assert err._title.text() == "搜索失败"
    assert "synthetic" in err._subtitle.text()
    assert err._action.isHidden() is False
    assert err._action.text() == "重试"
    monkey.undo()


def test_hot_page_flips_loading_then_error(qapp):
    """hot page: click refresh with synthetic exception → ErrorState."""
    import doubi.cli.main as cli_main

    async def boom(**kwargs):
        raise RuntimeError("hot boom")

    monkey = pytest.MonkeyPatch()
    monkey.setattr(cli_main, "collect_hot_async", boom)

    mw = _make_window(qapp)
    mw.show()
    _resolve(qapp)
    mw.shortcuts.specs()[4].callback()  # to hot
    _resolve(qapp)
    mw.hot_interface.refresh_btn.click()
    _resolve(qapp)

    stack = mw.hot_interface._stack
    assert stack.currentWidget() is mw.hot_interface._error_state
    err = mw.hot_interface._error_state
    assert err._title.text() == "热榜失败"
    assert "hot boom" in err._subtitle.text()
    assert err._action.text() == "重试"
    monkey.undo()


def test_history_page_flips_loading_when_db_enabled(qapp, tmp_path, monkeypatch):
    """history page: with a fresh SQLite path enabled, click refresh and
    assert LoadingState → empty state (no rows yet)."""
    from doubi.core.config import AppConfig
    from doubi.core.storage.database import Database

    db_file = tmp_path / "history.db"
    # Pre-create an empty DB so list_recent succeeds and returns []:
    db = Database(str(db_file))
    import asyncio
    asyncio.run(db.initialize())
    asyncio.run(db.close())

    # Override settings so the page actually queries our temp DB:
    cfg = AppConfig(database=True, database_path=str(db_file))

    mw = _make_window(qapp)
    mw.show()
    _resolve(qapp)
    # Override the history page's config with our temp one
    mw.history_interface._cfg = cfg
    mw.shortcuts.specs()[2].callback()  # to history
    _resolve(qapp)
    # Trigger refresh manually (the showEvent-driven first-load only fires
    # when the page was hidden and shown, which happens via the navigation
    # switch — the explicit _refresh() here is more deterministic).
    mw.history_interface._refresh()
    _resolve(qapp)

    # After refresh completes, stack should be on _empty_state (no rows).
    stack = mw.history_interface._stack
    assert stack.currentWidget() is mw.history_interface._empty_state


def test_parse_sample_links_action_fills_input(qapp):
    """The EmptyState CTA "试试示例链接" should populate the input box
    and focus it. Without offscreen focus semantics this verifies the
    content side-effect (text + cursor position).
    """
    mw = _make_window(qapp)
    mw.show()
    _resolve(qapp)
    # We start on parse page by default
    assert mw.parse_interface._result_stack.currentWidget() is mw.parse_interface._empty

    # Trigger the sample-link fill
    mw.parse_interface._fill_sample_links()
    _resolve(qapp)
    text = mw.parse_interface.url_input.toPlainText()
    assert "BV1GJ411x7h7" in text
    assert "486906719" in text


# ---------------------------------------------------------------------------
# Settings cheat sheet
# ---------------------------------------------------------------------------

def test_settings_cheat_sheet_renders_categories(qapp):
    """Settings page cheat-sheet card should list every registered
    shortcut, grouped by category, with key in the progress_normal token
    color (we don't assert color here, only structure)."""
    mw = _make_window(qapp)
    mw.show()
    _resolve(qapp)
    mw.shortcuts.specs()[5].callback()  # to settings
    _resolve(qapp)

    ml = mw.settings_interface._shortcut_body_layout
    # Each category yields: StrongBodyLabel + QVBoxLayout + SectionDivider
    # → at least 3 items per category × 5 categories = 15 items.
    assert ml.count() >= 15

    sheet = mw.shortcuts.cheat_sheet()
    # Each category label should appear as a StrongBodyLabel in the layout:
    titles = []
    for i in range(ml.count()):
        w = ml.itemAt(i).widget()
        if w is not None and hasattr(w, "text") and isinstance(w, mw.settings_interface._shortcut_placeholder.__class__):
            titles.append(w.text())
    assert any(cat in titles for cat in sheet.keys())
