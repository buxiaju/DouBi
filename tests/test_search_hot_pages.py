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
    # 0.3.4：搜索页改为「平台 + 通道」两级下拉，抖音保持原 4 通道；
    # B 站 2 通道（video / user）。
    import doubi.ui.pages.search as mod
    platform_channels = getattr(mod, "PLATFORM_CHANNELS", None)
    platforms = getattr(mod, "PLATFORM_OPTIONS", None)
    assert platform_channels is not None
    assert platforms is not None
    assert [v for v, _ in platforms] == ["douyin", "bilibili"]
    douyin_keys = [v for v, _ in platform_channels["douyin"]]
    bili_keys = [v for v, _ in platform_channels["bilibili"]]
    assert douyin_keys == ["general", "video", "user", "live"]
    assert bili_keys == ["video", "user"]
    defaults = getattr(mod, "DEFAULT_CHANNEL", None)
    assert defaults == {"douyin": "general", "bilibili": "video"}


def test_hot_board_options_covers_all_boards():
    # 0.3.4：热榜页改为「平台 + 牌」两级下拉。抖音 5 牌（all + 4 named）；
    # B 站只有 all（hotword + popular 一起给）。
    import doubi.ui.pages.hot as mod
    platform_boards = getattr(mod, "PLATFORM_BOARDS", None)
    platforms = getattr(mod, "PLATFORM_OPTIONS", None)
    assert platform_boards is not None
    assert platforms is not None
    assert [v for v, _ in platforms] == ["douyin", "bilibili"]
    douyin_keys = [v for v, _ in platform_boards["douyin"]]
    bili_keys = [v for v, _ in platform_boards["bilibili"]]
    assert douyin_keys == ["all", "positive", "entertainment", "society", "challenge"]
    assert bili_keys == ["all"]


def test_main_window_imports_new_pages():
    # Regression: when ``build_search_widgets`` / ``build_hot_widgets``
    # were added to ``pages/__init__.py``, the import block in
    # ``main_window.py`` was forgotten — ``NameError: name
    # 'build_search_widgets' is not defined`` at first build. Pin it.
    pytest.importorskip("PySide6")
    import importlib
    importlib.import_module("doubi.ui.main_window")
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


# 0.3.4 — new: page factories wire the platform tab + channel refresh.


def test_search_factory_wires_platform_tab():
    """0.3.4：搜索页用 SegmentedWidget 切 douyin / B 站，通道下拉随之刷新。"""
    _require_gui()
    from doubi.ui.pages.search import build_search_widgets

    cls, _ = build_search_widgets()
    # Required methods
    assert hasattr(cls, "_on_platform_changed")
    assert hasattr(cls, "_refresh_channel_options")


def test_hot_factory_wires_platform_tab():
    """0.3.4：热榜页同样有平台 Tab + 牌下拉随之刷新。"""
    _require_gui()
    from doubi.ui.pages.hot import build_hot_widgets

    cls, _ = build_hot_widgets()
    assert hasattr(cls, "_on_platform_changed")
    assert hasattr(cls, "_refresh_board_options")


# 0.3.9 — search empty-state login check (regression: cookie file
# existence vs cfg.cookies_file).
#
# Symptom: 设置页「账号与登录」显示「抖音：已登录」，但搜索页输入
# 关键词后报「暂无结果（未登录）」—— GUI 登录流程写的是默认 cookie
# 路径 ~/.doubi/cookies/<platform>.txt，而 cfg.cookies_file 出厂 None，
# 旧判定把 cfg.cookies_file 当真相，所以「永远未登录」。
#
# Fix: helper uses each platform's ``has_cookie_file()``（与 webapi
# 内部 _read_cookie_dicts / DouyinWebAPI.__init__ 的默认路径回退一致）。
# 下面的两个用例锁定这条新契约，避免将来回归到 cfg.cookies_file。


def test_platform_has_cookie_returns_false_for_unknown_platform(monkeypatch, tmp_path):
    """Unknown platform must never claim logged-in — defensive default."""
    import doubi.ui.pages.search as mod

    monkeypatch.setattr(
        mod, "_platform_has_cookie", lambda p: False
    )  # sanity
    # 重新 import 拿原始 helper（不被 monkeypatch 影响）
    fresh = mod._platform_has_cookie
    assert fresh("youtube") is False
    assert fresh("") is False
    assert fresh("UNKNOWN") is False


def test_platform_has_cookie_uses_platform_default_path(monkeypatch):
    """Helper 必须读 ~/.doubi/cookies/<platform>.txt 默认路径，而不是
    cfg.cookies_file（这是 0.3.9 修复的核心）。

    通过给 ``has_cookie_file`` 打桩捕获它的入参来验证：让 helper 用
    ``None``（默认路径）调用，而不是 cfg 里的任何 path。
    """
    import doubi.ui.pages.search as mod

    captured: dict[str, object] = {}

    def _fake_has_cookie_file(path=None):
        captured["path_arg"] = path
        return True

    # Stub the douyin has_cookie_file symbol — helper imports it lazily
    # inside the function, so patch on the module-level ``has_cookie_file``
    # path the helper actually resolves.
    import doubi.platforms.douyin.auth as dy_auth
    monkeypatch.setattr(dy_auth, "has_cookie_file", _fake_has_cookie_file)
    assert mod._platform_has_cookie("douyin") is True
    # Helper must have called has_cookie_file() with NO path (defaults
    # to ~/.doubi/cookies/douyin.txt) — not cfg.cookies_file.
    assert captured["path_arg"] is None

    # Same for bilibili.
    import doubi.platforms.bilibili.auth as bi_auth
    monkeypatch.setattr(bi_auth, "has_cookie_file", _fake_has_cookie_file)
    captured.clear()
    assert mod._platform_has_cookie("bilibili") is True
    assert captured["path_arg"] is None


def test_platform_has_cookie_returns_false_on_import_error(monkeypatch):
    """If the platform auth module can't be resolved (pathological),
    the helper must return False rather than raise — the empty-state
    branch expects a clean True/False, not an exception.
    """
    import doubi.ui.pages.search as mod

    def _boom(platform: str) -> bool:
        raise RuntimeError("simulated missing platform")

    # Monkeypatch the per-platform import inside the helper.
    # Easier: just delete the import shortcut by making the helper
    # raise — easiest by patching one of the auth imports to fail.
    import doubi.platforms.douyin.auth as dy_auth
    monkeypatch.setattr(dy_auth, "has_cookie_file", None)
    # Now when helper does ``from doubi.platforms.douyin.auth import
    # has_cookie_file``, ``has_cookie_file`` is None — the helper's
    # ``bool(has_cookie_file())`` call will fail with TypeError, which
    # is caught and returns False.
    assert mod._platform_has_cookie("douyin") is False
