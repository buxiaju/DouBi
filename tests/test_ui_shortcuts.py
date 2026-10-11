"""Unit tests for :mod:`doubi.ui.shortcuts` (0.3.7 new).

The whole shortcuts module is deliberately small and pure: the manager
owns its ``QShortcut`` instances, dedups by key, swallows callback
exceptions, and exposes a cheat-sheet grouping for the Settings page.

These tests don't need a real main window — a vanilla ``QWidget`` parent
is enough for ``QShortcut`` to construct.
"""

from __future__ import annotations

import os
import sys

import pytest

# 整个模块要构造 QShortcut，必须先有 QApplication
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _require_qt():
    try:
        import PySide6  # noqa: F401
    except Exception as exc:   # noqa: BLE001
        pytest.skip(f"PySide6 unavailable: {exc}")


@pytest.fixture(scope="module")
def qapp():
    _require_qt()
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture
def parent(qapp):
    from PySide6.QtWidgets import QWidget
    w = QWidget()
    yield w
    w.deleteLater()


# ---------------------------------------------------------------------------
# import / construction
# ---------------------------------------------------------------------------

def test_import_smoke():
    """The module should be importable without a QApplication around
    (the module-level imports are stdlib + dataclasses only)."""
    from doubi.ui import shortcuts
    assert hasattr(shortcuts, "ShortcutManager")
    assert hasattr(shortcuts, "ShortcutSpec")


def test_register_returns_spec(parent):
    from doubi.ui.shortcuts import ShortcutManager, ShortcutSpec
    mgr = ShortcutManager(parent)
    called = []

    def cb():
        called.append(1)

    spec = mgr.register("test", "Ctrl+T", cb)
    assert isinstance(spec, ShortcutSpec)
    assert spec.name == "test"
    assert spec.key == "Ctrl+T"
    assert spec.description == ""
    assert spec.category == "其他"
    assert mgr.count() == 1


def test_register_with_description_and_category(parent):
    from doubi.ui.shortcuts import ShortcutManager
    mgr = ShortcutManager(parent)
    spec = mgr.register(
        "open settings", "Ctrl+,",
        lambda: None, description="跳到设置", category="导航",
    )
    assert spec.description == "跳到设置"
    assert spec.category == "导航"
    assert mgr.cheat_sheet() == {"导航": [spec]}


# ---------------------------------------------------------------------------
# dedup
# ---------------------------------------------------------------------------

def test_register_dedups_by_key(parent):
    """Same key registered twice → second one wins, count stays the same."""
    from doubi.ui.shortcuts import ShortcutManager
    mgr = ShortcutManager(parent)
    mgr.register("first",  "Ctrl+1", lambda: None, category="导航")
    mgr.register("second", "Ctrl+1", lambda: None, category="导航")
    assert mgr.count() == 1
    specs = mgr.specs()
    assert specs[0].name == "second"


# ---------------------------------------------------------------------------
# callback safety
# ---------------------------------------------------------------------------

def test_callback_exception_swallowed_on_manual_invoke(parent):
    """The wrapper around the user's callback must swallow exceptions so
    ``spec.callback()`` from tests / debug never blows up the call stack.
    """
    from doubi.ui.shortcuts import ShortcutManager
    mgr = ShortcutManager(parent)

    def bad():
        raise RuntimeError("intentional")

    spec = mgr.register("boom", "Ctrl+B", bad)
    # Must not raise:
    spec.callback()


def test_callback_exception_swallowed_on_signal_emit(parent, caplog):
    """The same wrapper protects the QShortcut signal path."""
    import logging
    from doubi.ui.shortcuts import ShortcutManager

    mgr = ShortcutManager(parent)

    def bad():
        raise RuntimeError("via signal")

    spec = mgr.register("boom2", "Ctrl+R", bad)
    with caplog.at_level(logging.ERROR, logger="doubi.ui.shortcuts"):
        # ``QShortcut.activated.emit()`` invokes the connected slot
        # synchronously — if the wrapper isn't in place, RuntimeError
        # would propagate out and fail this test.
        spec._shortcut.activated.emit()
    # We at least logged the exception:
    assert any(
        "boom2" in record.message or "Ctrl+R" in record.message
        for record in caplog.records
    ), f"expected shortcut exception in logs, got {[r.message for r in caplog.records]}"


# ---------------------------------------------------------------------------
# cheat sheet
# ---------------------------------------------------------------------------

def test_cheat_sheet_groups_by_category(parent):
    """``cheat_sheet()`` returns dict[category, list[Spec]], insertion
    order preserved by category and by spec within a category.
    """
    from doubi.ui.shortcuts import ShortcutManager
    mgr = ShortcutManager(parent)
    a = mgr.register("a", "Ctrl+1", lambda: None, category="导航")
    b = mgr.register("b", "Ctrl+2", lambda: None, category="导航")
    c = mgr.register("c", "F5",     lambda: None, category="刷新")
    sheet = mgr.cheat_sheet()
    assert list(sheet.keys()) == ["导航", "刷新"]
    assert sheet["导航"] == [a, b]
    assert sheet["刷新"] == [c]


def test_specs_returns_independent_list(parent):
    """``specs()`` returns a copy, not the internal list — mutating
    it must not affect the manager."""
    from doubi.ui.shortcuts import ShortcutManager
    mgr = ShortcutManager(parent)
    mgr.register("a", "Ctrl+1", lambda: None)
    snapshot = mgr.specs()
    snapshot.clear()
    assert mgr.count() == 1   # internal list untouched


# ---------------------------------------------------------------------------
# QShortcut wiring
# ---------------------------------------------------------------------------

def test_register_binds_qshortcut_to_parent(parent):
    """The QShortcut should be parented to the manager's parent — this
    matters because ``QShortcut`` without an explicit parent will leak
    after the manager is destroyed.
    """
    from PySide6.QtGui import QShortcut
    from doubi.ui.shortcuts import ShortcutManager
    mgr = ShortcutManager(parent)
    spec = mgr.register("a", "Ctrl+1", lambda: None)
    assert spec._shortcut is not None
    assert isinstance(spec._shortcut, QShortcut)
    assert spec._shortcut.parent() is parent
    assert spec._shortcut.context().name == "ApplicationShortcut"


def test_register_replaces_old_qshortcut(parent):
    """When a key is re-registered, the old QShortcut must be deleted
    so we don't have two QShortcuts fighting over the same key sequence.
    """
    from doubi.ui.shortcuts import ShortcutManager
    mgr = ShortcutManager(parent)
    mgr.register("first",  "Ctrl+1", lambda: None)
    old_first_spec = mgr.specs()[0]
    mgr.register("second", "Ctrl+1", lambda: None)
    new_spec = mgr.specs()[0]
    assert new_spec.name == "second"
    # The previous spec object is no longer in the manager; its QShortcut
    # was deleted (the manager called deleteLater on it).
    assert old_first_spec not in mgr.specs()
    assert new_spec._shortcut is not None
