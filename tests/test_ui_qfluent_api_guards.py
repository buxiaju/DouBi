"""Guard tests for the qfluentwidgets API misuse class (0.3.6 + 0.3.7).

0.3.6 defects found by driving the real GUI offscreen:

1. ``SegmentedWidget.currentItem()`` returns a ``SegmentedItem`` **object**,
   not the routeKey string. Passing it to ``collect_search_async`` /
   ``collect_hot_async`` raises
   ``ValueError: unknown platform: <SegmentedItem...>``.
   The correct accessor is ``currentRouteKey()``.

2. qfluentwidgets' ``InfoBar.error/warning/success/info`` second parameter
   is named ``content``, not ``message``. Using ``message=`` raises
   ``TypeError`` *inside the exception handler*, which Qt swallows — the
   user sees nothing, and the page stays on its initial empty state.

0.3.7 additions:

3. Pages must not call ``InfoBar.xxx(...)`` directly anymore — they should
   use ``doubi.ui.feedback.toast_*`` helpers so position/duration stay
   consistent. AST scan catches direct calls in the pages/ package.

4. Pages must not call ``QShortcut(...)`` directly — only
   ``doubi.ui.shortcuts.ShortcutManager.register`` is allowed, because the
   manager owns the safe callback wrapper, key dedup, and cheat-sheet data.
   AST scan bans bare ``QShortcut(...)`` constructor calls.
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


def _page_files() -> list[Path]:
    """The 6 page modules + main_window: only these can legitimately call
    InfoBar.* (and even they should prefer toast_*). Test widgets and
    dialogs can use InfoBar directly because they're not the regression
    surface we're guarding against.
    """
    pages_dir = _UI / "pages"
    out = [pages_dir / "parse.py",
           pages_dir / "search.py",
           pages_dir / "hot.py",
           pages_dir / "history.py",
           pages_dir / "settings.py",
           _UI / "main_window.py"]
    return [p for p in out if p.is_file()]


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


# --- 0.3.7 新增：禁止页面直接调 InfoBar/InfoBarPosition ---------------------

def test_pages_must_use_toast_helpers_not_infobar():
    """Page modules + main_window should call ``toast_*`` helpers, not
    ``InfoBar.xxx(...)`` directly. We accept ``feedback.py`` itself calling
    InfoBar internally — that's the helper's job.
    """
    offenders: list[str] = []
    for path in _page_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if not isinstance(fn, ast.Attribute):
                continue
            recv = fn.value
            if isinstance(recv, ast.Name) and recv.id == "InfoBar":
                offenders.append(f"{path.name}:{node.lineno} -> {fn.attr}")
    assert not offenders, (
        "页面 / main_window 不应该直接调 InfoBar.xxx(...); "
        "改用 doubi.ui.feedback.toast_* helpers "
        "(统一位置 + duration + 错误捕获)。Offenders:\n"
        + "\n".join(offenders)
    )


def test_pages_must_not_import_infobarposition():
    """``InfoBarPosition`` is a qfluentwidgets enum; pages shouldn't import
    it directly because the toast_* helpers own the position decision.
    """
    offenders: list[str] = []
    for path in _page_files():
        text = path.read_text(encoding="utf-8")
        if "InfoBarPosition" in text:
            # 报告一下行号方便定位
            for i, line in enumerate(text.splitlines(), 1):
                if "InfoBarPosition" in line:
                    offenders.append(f"{path.name}:{i}: {line.strip()}")
                    break
    assert not offenders, (
        "InfoBarPosition 不应在页面里 import；改用 toast_* helpers。"
        " Offenders:\n" + "\n".join(offenders)
    )


# --- 0.3.7 新增：禁止裸 QShortcut，必须走 ShortcutManager ------------------

def test_no_bare_qshortcut_in_pages():
    """Pages and main_window must go through :class:`ShortcutManager` to
    register shortcuts. Bare ``QShortcut(...)`` constructions make the
    callback wrapper + key dedup + cheat-sheet routing impossible.
    """
    offenders: list[str] = []
    # shortcuts.py 自己当然可以建——它是 manager 的实现
    allowed = {_UI / "shortcuts.py"}
    for path in set(_page_files()) | set(_py_files()):
        if path in allowed:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            # QShortcut(...) 形态：func 是 ast.Name 且 id == "QShortcut"
            if isinstance(fn, ast.Name) and fn.id == "QShortcut":
                offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, (
        "裸 QShortcut(...) 应改走 ShortcutManager.register("
        "name, key, callback, description, category)。Offenders:\n"
        + "\n".join(offenders)
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
