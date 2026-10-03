"""Guard tests for the qfluentwidgets API misuse class (0.3.6).

Two defects found by driving the real GUI offscreen:

1. ``SegmentedWidget.currentItem()`` returns a ``SegmentedItem`` **object**,
   not the routeKey string. Passing it to ``collect_search_async`` /
   ``collect_hot_async`` raises
   ``ValueError: unknown platform: <SegmentedItem...>``.
   The correct accessor is ``currentRouteKey()``.

2. qfluentwidgets' ``InfoBar.error/warning/success/info`` second parameter
   is named ``content``, not ``message``. Using ``message=`` raises
   ``TypeError`` *inside the exception handler*, which Qt swallows — the
   user sees nothing, and the page stays on its initial empty state.

Both defects are **silent**: the feature is broken and the error reporter is
broken too. These tests pin the correct API usage so the class cannot return.
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
_UI = _SRC / "doubi" / "ui"


# ---------------------------------------------------------------------------
# Static guards — no QApplication needed, so they run under the CI profile.
# ---------------------------------------------------------------------------

def _py_files() -> list[Path]:
    return sorted(_UI.rglob("*.py"))


def test_no_currentitem_used_as_platform_route():
    """``SegmentedWidget.currentItem()`` must never feed a platform argument.

    We scan for any call to ``currentItem()`` in the UI package. The only
    legitimate uses today are none — all call sites must use
    ``currentRouteKey()``.
    """
    offenders: list[str] = []
    for path in _py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if not isinstance(fn, ast.Attribute):
                continue
            if fn.attr == "currentItem":
                offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, (
        "SegmentedWidget.currentItem() returns a SegmentedItem object, not a "
        "routeKey string; use currentRouteKey() instead. Offenders: "
        f"{offenders}"
    )


def test_infobar_calls_never_use_message_keyword():
    """qfluentwidgets' ``InfoBar.*`` take ``content``, not ``message``.

    Note: ``TaskInfo(message=...)`` in task_manager.py is a dataclass field
    and is legitimately named ``message`` — we therefore only inspect calls
    whose receiver is the ``InfoBar`` object.
    """
    offenders: list[str] = []
    for path in _py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if not isinstance(fn, ast.Attribute):
                continue
            recv = fn.value
            if not (isinstance(recv, ast.Name) and recv.id == "InfoBar"):
                continue
            for kw in node.keywords:
                if kw.arg == "message":
                    offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, (
        "InfoBar.* second parameter is 'content', not 'message'; using "
        "'message' raises TypeError inside the error handler and Qt swallows "
        f"it. Offenders: {offenders}"
    )


def test_infobar_method_names_exist():
    """``InfoBar.information`` does not exist; the real name is ``info``."""
    valid = {"error", "warning", "success", "info"}
    offenders: list[str] = []
    for path in _py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if not isinstance(fn, ast.Attribute):
                continue
            recv = fn.value
            if isinstance(recv, ast.Name) and recv.id == "InfoBar":
                if fn.attr not in valid:
                    offenders.append(f"{path.name}:{node.lineno} -> {fn.attr}")
    assert not offenders, (
        f"Unknown InfoBar method(s); valid: {sorted(valid)}. Offenders: "
        f"{offenders}"
    )


# ---------------------------------------------------------------------------
# Runtime guards — need PySide6 + qfluentwidgets (copied from the style used
# by the other GUI test modules in this repo).
# ---------------------------------------------------------------------------

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _require_gui():
    try:
        import PySide6  # noqa: F401
        import qfluentwidgets  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"GUI stack unavailable: {exc}")


@pytest.fixture(scope="module")
def qapp():
    _require_gui()
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


def test_current_route_key_returns_string(qapp):
    """Pin the actual qfluentwidgets behaviour we depend on."""
    from qfluentwidgets import SegmentedWidget

    sw = SegmentedWidget()
    sw.addItem(routeKey="douyin", text="抖音")
    sw.addItem(routeKey="bilibili", text="B 站")
    sw.setCurrentItem("bilibili")

    assert sw.currentRouteKey() == "bilibili"
    # currentItem() gives an object; this is exactly the trap we fixed.
    item = sw.currentItem()
    assert not isinstance(item, str)
    assert type(item).__name__ == "SegmentedItem"


def test_hot_page_uses_current_route_key(qapp):
    """The hot page must resolve its platform via currentRouteKey()."""
    from doubi.ui.pages.hot import PLATFORM_OPTIONS, build_hot_widgets

    HotPage = build_hot_widgets()[0]
    page = HotPage()

    assert page._platform_tabs.currentRouteKey() in {
        v for v, _ in PLATFORM_OPTIONS
    }


def test_search_page_uses_current_route_key(qapp):
    """The search page must resolve its platform via currentRouteKey()."""
    from doubi.ui.pages.search import PLATFORM_OPTIONS, build_search_widgets

    SearchPage = build_search_widgets()[0]
    page = SearchPage()

    assert page._platform_tabs.currentRouteKey() in {
        v for v, _ in PLATFORM_OPTIONS
    }


def test_hot_refresh_passes_valid_platform(qapp, monkeypatch):
    """Clicking 刷新 must hand a real platform name to collect_hot_async.

    Regression guard: previously ``currentItem()`` leaked a SegmentedItem
    object into ``collect_hot_async``, which raised ValueError.
    """
    import doubi.cli.main as cli_main

    seen: dict = {}

    async def _fake_collect_hot_async(**kwargs):
        seen.update(kwargs)
        return [{"word": "x", "board": "positive", "board_name": "抖音热榜"}]

    monkeypatch.setattr(cli_main, "collect_hot_async", _fake_collect_hot_async)

    from doubi.ui.pages.hot import PLATFORM_OPTIONS, build_hot_widgets

    HotPage = build_hot_widgets()[0]
    page = HotPage()
    page.refresh_btn.click()

    # _on_refresh runs the coroutine via asyncio.run in this context.
    assert seen, "collect_hot_async was never called"
    assert seen["platform"] in {v for v, _ in PLATFORM_OPTIONS}, (
        f"platform must be a route string, got {seen['platform']!r}"
    )


def test_search_passes_valid_platform(qapp, monkeypatch):
    """Clicking 搜索 must hand a real platform name to collect_search_async."""
    import doubi.cli.main as cli_main

    seen: dict = {}

    async def _fake_collect_search_async(**kwargs):
        seen.update(kwargs)
        return [{"title": "x", "platform": "bilibili"}]

    monkeypatch.setattr(
        cli_main, "collect_search_async", _fake_collect_search_async,
    )

    from doubi.ui.pages.search import PLATFORM_OPTIONS, build_search_widgets

    SearchPage = build_search_widgets()[0]
    page = SearchPage()
    page._keyword.setText("python")
    page.search_btn.click()

    assert seen, "collect_search_async was never called"
    assert seen["platform"] in {v for v, _ in PLATFORM_OPTIONS}, (
        f"platform must be a route string, got {seen['platform']!r}"
    )
