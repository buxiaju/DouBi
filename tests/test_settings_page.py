"""0.3.4 — settings page UI reorganisation tests.

The settings page was restructured into a clearer card hierarchy
(账号 / 下载 / 网络与性能 / 嗅探折叠 / 主题与外观 / Cookie 与存储) and
the duplicated ``启用数据库`` switch was merged into the Cookie 与存储
card (they were both reaching for ``~/.doubi/doubi.db`` from different
places).

These tests stay at the factory level (same approach as
:mod:`tests.test_search_hot_pages`) — they pin the public surface
without spinning up a Qt event loop, so they pass under ``--mode ci``
without PySide6.
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
    try:
        import PySide6  # noqa: F401
        import qfluentwidgets  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        pytest.skip(f"GUI deps not installed: {exc}")


# -----------------------------------------------------------------------
# Card hierarchy — read the source so a future edit can't accidentally
# drop a card without CI noticing.
# -----------------------------------------------------------------------


def test_settings_page_has_six_card_sections():
    """0.3.4 改版：账号 + 下载 + 网络 + 嗅探 + 主题 + Cookie & 存储 = 6 张卡。"""
    src = (SRC / "doubi" / "ui" / "pages" / "settings.py").read_text(encoding="utf-8")
    # 6 张卡的标题必须在源代码里被引用（任何一处 ``_build_card("XXX"``
    # 或自定义 _build_account_card）。
    for title in (
        "账号",
        "下载",
        "网络与性能",
        "通用嗅探",
        "主题与外观",
        "Cookie 与存储",
    ):
        assert title in src, f"missing settings card title: {title}"


def test_database_switch_lives_in_cookie_card():
    """「启用数据库」与「Cookie 与存储」在 0.3.4 合到同一张卡里。

    之前的 0.3.3 把这两个分别放在「性能与网络」与「Cookie 与存储」
    ——分散到两张卡让用户以为能分别开关；其实两者都指向 ``~/.doubi/doubi.db``。
    """
    src = (SRC / "doubi" / "ui" / "pages" / "settings.py").read_text(encoding="utf-8")
    # 「启用下载历史数据库」必须出现在 ``_cookie_card`` 块内，不能再
    # 出现在 ``_network_card``。
    cookie_section = src[src.index("_cookie_card"):]
    assert "启用下载历史数据库" in cookie_section
    # 反向：网络卡里不再有「数据库」相关行。
    # 因为 _download_card 是先出现，``_cookie_card`` 是后出现，所以
    # 「数据库」要不在 _download_card 与 _cookie_card 之间出现。
    download_section_end = src.index("_cookie_card")
    download_section_start = src.rindex("_download_card", 0, download_section_end)
    download_block = src[download_section_start:download_section_end]
    assert "启用下载历史数据库" not in download_block


def test_sniff_card_is_collapsible():
    """「通用嗅探」卡 0.3.4 默认折叠，少一张卡挤在主页面里。"""
    src = (SRC / "doubi" / "ui" / "pages" / "settings.py").read_text(encoding="utf-8")
    assert "_on_sniff_toggle" in src
    assert "setVisible(False)" in src   # body 默认收起来
    assert "显示高级" in src
    assert "隐藏高级" in src


# -----------------------------------------------------------------------
# Factory-level smoke test
# -----------------------------------------------------------------------


def test_settings_factory_returns_widget_class():
    _require_gui()
    from doubi.ui.pages.settings import build_settings_widgets
    cls, _ = build_settings_widgets()
    assert cls.__name__ == "SettingsPage"
    # New method (the collapse toggle) must exist.
    assert hasattr(cls, "_on_sniff_toggle")
    # Old card methods preserved.
    assert hasattr(cls, "_build_account_card")
    assert hasattr(cls, "_build_card")