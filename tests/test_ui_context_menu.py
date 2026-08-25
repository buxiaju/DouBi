"""Regression tests for the parse-page right-click menu.

Background — the bug these tests exist for:

``ParsePage._on_table_context_menu`` builds the menu, then decides which
entries apply to the row under the cursor. One of those decisions is the
抖音「下载整个合集」 branch, which reads ``item``::

    if (item is not None
            and not item.is_container()
            and getattr(item.platform, "value", "") == "douyin"):

``item`` is assigned *inside the same function* (``item = episode_item or
top_item``). Because Python decides scope at compile time, a name assigned
anywhere in a function body is local for the whole body — so reading it
before the assignment raises ``UnboundLocalError`` instead of falling back
to any enclosing scope. The assignment used to sit *below* that branch, so
**every** right-click anywhere in the results table raised, on every
platform. The fix hoists the assignment above the first read.

Testing this means driving a real Qt context menu, which needs two tricks:

1. ``QMenu.exec`` is modal — an un-intercepted call would hang the suite.
   It cannot be monkeypatched on the class: assigning ``QMenu.exec = ...``
   is silently ignored because Shiboken dispatches straight to C++ (this
   was verified, not assumed). Subclassing and overriding ``exec`` *does*
   get called from Python, so we inject a stub subclass instead.
2. ``QMenu`` is a *closure* variable of ``build_parse_widgets()``, not a
   module global, so ``monkeypatch.setattr(module, "QMenu", ...)`` has
   nothing to bind to. We write the closure cell directly. Each call to
   ``build_parse_widgets()`` mints a fresh class, so the patch is scoped
   to the page under test and cannot leak into other tests.
"""

from __future__ import annotations

import ast
import inspect
import os
import sys
import textwrap
from pathlib import Path

# Force Qt to render off-screen so the test never needs a display.
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
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


class _RecordingTaskManager:
    """Stand-in for ``ui.task_manager`` — records what got enqueued."""

    def __init__(self) -> None:
        self.added: list[tuple[object, object]] = []

    def add(self, item, options) -> None:
        self.added.append((item, options))


def _make_stub_menu_class():
    """A ``QMenu`` subclass whose ``exec`` returns a chosen action.

    Set ``pick`` to the label prefix the "user" clicks, or leave it
    ``None`` to simulate dismissing the menu with Esc.
    """
    from PySide6.QtWidgets import QMenu

    class StubMenu(QMenu):
        pick: str | None = None
        entries: list[tuple[str, bool]] = []

        def exec(self, *args, **kwargs):          # noqa: A003 - Qt's name
            type(self).entries = [
                (a.text(), a.isEnabled()) for a in self.actions()
            ]
            if type(self).pick is None:
                return None
            for action in self.actions():
                if action.text().startswith(type(self).pick):
                    return action
            raise AssertionError(
                f"no menu entry starts with {type(self).pick!r}; "
                f"menu was {type(self).entries!r}"
            )

    return StubMenu


def _make_page(qapp):
    """Build a ParsePage whose context menu is non-modal.

    Returns ``(page, StubMenu)``; assert against ``StubMenu.entries``
    after triggering the menu.
    """
    from doubi.ui.pages.parse import build_parse_widgets

    cls, _ = build_parse_widgets()
    stub = _make_stub_menu_class()

    handler = cls._on_table_context_menu
    freevars = handler.__code__.co_freevars
    assert "QMenu" in freevars, (
        "the context-menu handler no longer closes over QMenu; this test's "
        f"injection point is gone. free variables are {freevars!r}"
    )
    handler.__closure__[freevars.index("QMenu")].cell_contents = stub

    page = cls()
    page._task_manager = _RecordingTaskManager()
    return page, stub


def _item(platform, item_id: str, **extra):
    from doubi.core.models import Author, MediaItem, MediaType

    return MediaItem(
        platform=platform,
        item_id=item_id,
        title=f"标题-{item_id}",
        author=Author(name="UP主"),
        media_type=MediaType.VIDEO,
        source_url=f"https://example.com/{item_id}",
        extra=extra,
    )


def _right_click(page, row: int):
    """Trigger the context menu at *row*, the way a real click would.

    The handler reads the row from the click position via ``rowAt``, so we
    go through real viewport coordinates instead of calling the resolvers
    directly — otherwise the row-resolution logic stays untested.
    """
    from PySide6.QtCore import QPoint

    y = page.result_table.rowViewportPosition(row) + 2
    assert page.result_table.rowAt(y) == row, (
        f"test setup: y={y} maps to row {page.result_table.rowAt(y)}, "
        f"not {row}"
    )
    return page._on_table_context_menu(QPoint(5, y))


def _expand_section_with_episode(page, section, episode):
    """Reproduce the table shape of an expanded ugc_season section.

    Row 0 is the section, row 1 the inserted episode — the exact layout in
    which the original crash was reported.
    """
    from PySide6.QtWidgets import QTableWidgetItem

    page._fill_result_table([section])
    page._expanded_rows[(0,)] = [episode]
    page.result_table.insertRow(1)
    for col in range(page.result_table.columnCount()):
        page.result_table.setItem(1, col, QTableWidgetItem(""))
    page._refresh_row_mapping()


# ----------------------------------------------------------------------
# the crash itself
# ----------------------------------------------------------------------

@pytest.mark.parametrize("platform_name", ["BILIBILI", "DOUYIN"])
def test_right_click_never_raises_unbound_local(qapp, platform_name):
    """Opening the menu must not raise — this is the reported crash.

    Note this fails for *every* platform when the assignment is misplaced,
    not just 抖音: the guard clause reads ``item is not None`` before it
    ever gets to the platform comparison.
    """
    from doubi.core.models import Platform

    page, stub = _make_page(qapp)
    stub.pick = None
    page._fill_result_table([_item(getattr(Platform, platform_name), "v1")])

    _right_click(page, 0)   # must not raise

    labels = [text for text, _ in stub.entries]
    for expected in ("解析此项", "在浏览器中打开", "查看元数据", "查看封面"):
        assert expected in labels, f"{expected} missing from {labels}"


def test_item_is_assigned_before_it_is_read(qapp):
    """Source-level guard: the hoist must not drift back down.

    The runtime tests above only crash if a *reachable* read precedes the
    assignment. A future edit could add an early read on a branch none of
    these fixtures happen to take, and ship the same class of bug. This
    check reads the function's AST instead, so it holds for every branch.
    """
    from doubi.ui.pages.parse import build_parse_widgets

    cls, _ = build_parse_widgets()
    source = textwrap.dedent(
        inspect.getsource(cls._on_table_context_menu),
    )
    tree = ast.parse(source)

    assigns = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name) and target.id == "item"
    ]
    reads = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
        and node.id == "item"
        and isinstance(node.ctx, ast.Load)
    ]
    assert assigns, "expected an `item = ...` assignment in the handler"
    assert reads, "sanity: the handler must read `item` somewhere"
    assert min(assigns) < min(reads), (
        f"`item` is read at line {min(reads)} but only assigned at line "
        f"{min(assigns)} (relative to the function). Python marks it local "
        "for the whole body, so that earlier read is an UnboundLocalError, "
        "not a fallback to an outer scope."
    )


# ----------------------------------------------------------------------
# what the fallback assignment is actually *for*
# ----------------------------------------------------------------------

def test_menu_on_episode_row_acts_on_the_episode(qapp):
    """``episode_item or top_item`` must prefer the deepest row.

    ``_resolve_top_item_for_row`` deliberately maps child rows back to
    their owning section, so without the fallback a right-click on an
    episode would enqueue the whole section instead.
    """
    from doubi.core.models import Platform

    page, stub = _make_page(qapp)
    section = _item(Platform.BILIBILI, "sec", _from_ugc_season_section=True)
    episode = _item(Platform.BILIBILI, "ep", _from_ugc_season=True)
    section.children = [episode]
    _expand_section_with_episode(page, section, episode)

    stub.pick = "作为单个视频下载"
    _right_click(page, 1)

    enqueued = [item.item_id for item, _ in page._task_manager.added]
    assert enqueued == ["ep"], (
        "right-clicking an episode row must enqueue the episode, not its "
        f"owning section; got {enqueued}"
    )


def test_menu_on_top_row_acts_on_the_top_item(qapp):
    from doubi.core.models import Platform

    page, stub = _make_page(qapp)
    page._fill_result_table([_item(Platform.BILIBILI, "top")])

    stub.pick = "作为单个视频下载"
    _right_click(page, 0)

    assert [i.item_id for i, _ in page._task_manager.added] == ["top"]


def test_single_download_passes_options_from_the_transfer_point(qapp):
    """The enqueued options must come from ``_build_options``.

    Guards the single ``AppConfig -> DownloadOptions`` boundary: the menu
    must not hand-roll its own options bag.
    """
    from doubi.core.models import DownloadOptions, Platform

    page, stub = _make_page(qapp)
    page._cfg.container = "mkv"
    page._fill_result_table([_item(Platform.BILIBILI, "top")])

    stub.pick = "作为单个视频下载"
    _right_click(page, 0)

    _, options = page._task_manager.added[0]
    assert isinstance(options, DownloadOptions)
    assert options.container == "mkv", (
        "options must be built via _build_options so config changes apply"
    )


# ----------------------------------------------------------------------
# the branches that read `item` to decide what to offer
# ----------------------------------------------------------------------

def test_container_row_disables_single_download(qapp):
    """Containers can't go to the engine — the entry must be disabled.

    The pipeline refuses containers outright, so offering the action would
    surface an error the user cannot act on.
    """
    from doubi.core.models import Platform

    page, stub = _make_page(qapp)
    container = _item(Platform.BILIBILI, "sec")
    container.children = [_item(Platform.BILIBILI, "child")]
    page._fill_result_table([container])

    stub.pick = None
    _right_click(page, 0)

    single = [
        (text, enabled) for text, enabled in stub.entries
        if text.startswith("作为单个视频下载")
    ]
    assert single, f"entry missing from {stub.entries!r}"
    text, enabled = single[0]
    assert enabled is False
    assert "不可用" in text, "disabled entries should say why"


def test_douyin_row_offers_the_collection_entry(qapp):
    from doubi.core.models import Platform

    page, stub = _make_page(qapp)
    page._fill_result_table([_item(Platform.DOUYIN, "d1")])

    stub.pick = None
    _right_click(page, 0)

    assert any(
        text == "下载整个合集" for text, _ in stub.entries
    ), f"抖音 rows should offer the collection lookup; got {stub.entries!r}"


def test_non_douyin_row_has_no_collection_entry(qapp):
    from doubi.core.models import Platform

    page, stub = _make_page(qapp)
    page._fill_result_table([_item(Platform.BILIBILI, "b1")])

    stub.pick = None
    _right_click(page, 0)

    assert not any(text == "下载整个合集" for text, _ in stub.entries)


def test_expand_entry_offered_on_section_row_only(qapp):
    """「展开分类」 is decided by row identity, not by resolved item.

    ``_resolve_top_item_for_row`` returns the *section* for child rows too,
    so keying this off the resolved item would offer 「折叠分类」 on an
    episode and collapse all of its siblings.
    """
    from doubi.core.models import Platform

    page, stub = _make_page(qapp)
    section = _item(Platform.BILIBILI, "sec", _from_ugc_season_section=True)
    episode = _item(Platform.BILIBILI, "ep", _from_ugc_season=True)
    section.children = [episode]
    _expand_section_with_episode(page, section, episode)

    stub.pick = None
    _right_click(page, 0)
    section_labels = [text for text, _ in stub.entries]

    stub.entries = []
    _right_click(page, 1)
    episode_labels = [text for text, _ in stub.entries]

    assert any("分类" in text for text in section_labels), (
        f"section row should offer expand/collapse; got {section_labels}"
    )
    assert not any("分类" in text for text in episode_labels), (
        f"episode row must not offer section collapse; got {episode_labels}"
    )


# ----------------------------------------------------------------------
# boundaries
# ----------------------------------------------------------------------

def test_dismissing_the_menu_changes_nothing(qapp):
    from doubi.core.models import Platform

    page, stub = _make_page(qapp)
    page._fill_result_table([_item(Platform.BILIBILI, "v1")])

    stub.pick = None
    _right_click(page, 0)

    assert page._task_manager.added == []


def test_click_below_the_last_row_is_ignored(qapp):
    """``rowAt`` returns -1 in empty space; the handler must bail out."""
    from PySide6.QtCore import QPoint
    from doubi.core.models import Platform

    page, stub = _make_page(qapp)
    page._fill_result_table([_item(Platform.BILIBILI, "v1")])
    stub.entries = []

    page._on_table_context_menu(QPoint(5, 100_000))

    assert stub.entries == [], "no menu should be built for an invalid row"
    assert page._task_manager.added == []
