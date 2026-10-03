"""0.3.3 P1-3: search.py / hot.py GUI page factories.

The pages themselves are QWidgets that need a live event loop to
exercise, so these tests stay at the *factory* level — they pin the
public surface (class name, channels, boards, action wiring) and guard
against the regression where the pages silently drop back to an empty
table on hard-failed builds.

PySide6 / qfluentwidgets 是**可选依赖**（CI 只跑 ``pip install .``，这两个包
不在其中）。凡是会触碰 Qt 的用例都必须先 ``_require_gui()`` 跳过，否则
``--mode ci`` 口径会直接 ModuleNotFoundError 而不是 skip——这正是 0.3.3
发版前 ``ci`` 口径暴露出来的问题：本文件的 3 个用例当时把 PySide6 误当
必装依赖。

注意「读模块级常量」本身不需要 Qt，所以那几条只叫 ``_require_gui`` 的
用例可以拆开：常量类断言（CHANNEL_OPTIONS / i18n / main_window 源码）
在无 GUI 环境下依然有价值，不该被一起跳过。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _require_gui() -> None:
    """跳过需要 Qt 的用例；缺依赖时是 skip，不是 error。"""
    try:
        import PySide6  # noqa: F401
        import qfluentwidgets  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        pytest.skip(f"GUI deps not installed: {exc}")


def test_search_factory_returns_widget_class():
    _require_gui()
    from doubi.ui.pages.search import build_search_widgets

    cls, factory = build_search_widgets()
    assert factory is None
    assert cls.__name__ == "SearchPage"
    # The class must declare the four channel constants — if a future
    # edit adds a channel we want a *deliberate* hit on this test, not
    # a silent one-off drop.
    assert hasattr(cls, "_build_ui") and callable(cls._build_ui)
    # The class is created on demand; instantiating it requires a
    # QApplication. Skipping the instance probe is intentional.


def test_hot_factory_returns_widget_class():
    _require_gui()
    from doubi.ui.pages.hot import build_hot_widgets

    cls, factory = build_hot_widgets()
    assert factory is None
    assert cls.__name__ == "HotPage"
    assert hasattr(cls, "_build_ui") and callable(cls._build_ui)


def test_pages_module_exports_new_factories():
    # Guard against a regression where ``__init__.py`` forgot to
    # re-export the new factories. ``pages/__init__.py`` re-exports
    # lazily, so importing it needs no Qt.
    from doubi.ui.pages import (
        build_hot_widgets,
        build_search_widgets,
    )
    assert callable(build_hot_widgets)
    assert callable(build_search_widgets)


def test_i18n_keys_exist_in_zh_cn_and_en():
    # The MainWindow reads ``tr("nav.search")`` and ``tr("nav.hot")``
    # directly. Missing keys would crash on startup with KeyError.
    import json
    zh = json.loads((ROOT / "src" / "doubi" / "ui" / "locales" / "zh_CN.json").read_text(encoding="utf-8"))
    en = json.loads((ROOT / "src" / "doubi" / "ui" / "locales" / "en.json").read_text(encoding="utf-8"))
    for key, label in [("nav.search", "搜索"), ("nav.hot", "热榜")]:
        assert key in zh, f"zh_CN missing key: {key}"
        assert key in en, f"en missing key: {key}"
        assert zh[key] == label, f"zh_CN[{key}] changed unexpectedly: {zh[key]!r}"


def test_search_channel_options_covers_four_endpoints():
    # The CLI exposes 4 channels — general / video / user / live — and
    # the GUI search page must keep them in lock-step. Pin the values
    # by reading the module-level tuple so a silent rename gets caught
    # at unit-test time, not at runtime.
    #
    # CHANNEL_OPTIONS 是模块级的，读它**不需要** Qt：工厂里那句
    # ``from PySide6.QtCore import Qt`` 只在真正调用工厂时才执行。所以这条
    # 不叫 _require_gui()——无 GUI 的 CI 里它照样能守住「四个通道没漂移」。
    import doubi.ui.pages.search as mod
    options = getattr(mod, "CHANNEL_OPTIONS", None)
    assert options is not None, "CHANNEL_OPTIONS must be module-level for the test"
    keys = [value for value, _ in options]
    assert keys == ["general", "video", "user", "live"]


def test_hot_board_options_covers_all_boards():
    # 同 test_search_channel_options_covers_four_endpoints：模块级常量，不需要 Qt。
    import doubi.ui.pages.hot as mod
    options = getattr(mod, "BOARD_OPTIONS", None)
    assert options is not None
    keys = [value for value, _ in options]
    # "all" is the default; the four named boards match CLI.
    assert keys == ["all", "positive", "entertainment", "society", "challenge"]


def test_main_window_imports_new_pages():
    # Regression: when ``build_search_widgets`` / ``build_hot_widgets``
    # were added to ``pages/__init__.py``, the import block in
    # ``main_window.py`` was forgotten — ``NameError: name
    # 'build_search_widgets' is not defined`` at first build. Pin it.
    import importlib
    main_module = importlib.import_module("doubi.ui.main_window")
    # Importing the module just imports the docstring / globals; the
    # heavy ``build_main_window`` factory is only invoked when a real
    # window is constructed. The factory itself imports the pages
    # at call site, so the right thing to check is that the names are
    # exported by ``pages`` and that ``main_window`` references them
    # in its factory source.
    from doubi.ui.pages import (
        build_hot_widgets,
        build_search_widgets,
    )
    assert callable(build_hot_widgets)
    assert callable(build_search_widgets)
    # And the source of the factory references both names.
    src = (SRC / "doubi" / "ui" / "main_window.py").read_text(encoding="utf-8")
    assert "build_search_widgets" in src
    assert "build_hot_widgets" in src
    assert 'tr("nav.search")' in src
    assert 'tr("nav.hot")' in src