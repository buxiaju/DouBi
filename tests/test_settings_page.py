"""0.3.4 — settings page UI reorganisation tests.

The settings page was restructured into a clearer card hierarchy
(账号 / 下载（含行为偏好） / 网络 / 嗅探折叠 / 界面 / 存储) and
the duplicated ``启用数据库`` switch was merged into the 存储
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
    """卡片分组：账号 + 下载（含行为偏好）+ 网络 + 嗅探折叠 + 界面 + 存储。

    2026-11-27 重排：下载行为偏好（询问/剪贴板/通知）从「主题与外观」
    迁入「下载」卡——它们是下载语义不是外观语义；「主题与外观」
    更名「界面」；「Cookie 与存储」简化为「存储」。
    """
    src = (SRC / "doubi" / "ui" / "pages" / "settings.py").read_text(encoding="utf-8")
    # 卡片标题必须在源代码里被引用（任何一处 ``_build_card("XXX"``
    # 或自定义 _build_account_card）。
    for title in (
        "账号",
        "下载",
        "网络",
        "通用嗅探",
        "界面",
        "存储",
    ):
        assert title in src, f"missing settings card title: {title}"
    # 下载行为偏好必须在下载卡区块内（_download_card 与 _network_card 之间）
    download_start = src.index("_download_card")
    network_next = src.index("_network_card", download_start)
    download_block = src[download_start:network_next]
    for pref in ("下载前逐个确认选项", "复制链接后自动填入解析页", "完成通知时机"):
        assert pref in download_block, (
            f"download-behavior pref {pref!r} must live in the download card"
        )
    # 界面卡里不应再出现这些偏好（防回迁）
    appearance_start = src.index("_appearance_card")
    appearance_block = src[appearance_start:src.index("_cookie_card", appearance_start)]
    for pref in ("下载前逐个确认选项", "复制链接后自动填入解析页"):
        assert pref not in appearance_block, (
            f"download-behavior pref {pref!r} leaked back into the appearance card"
        )


def test_database_switch_lives_in_cookie_card():
    """「记录下载历史」开关必须与「存储」卡同卡。

    之前的 0.3.3 把这个开关分别放在「性能与网络」与存储卡——分散到
    两张卡让用户以为能分别开关；其实两者都指向 ``~/.doubi/doubi.db``。
    2026-11-27 文案产品化：开关标签从「启用下载历史数据库」改为
    「记录下载历史」（用户视角说行为，不说实现）。
    """
    src = (SRC / "doubi" / "ui" / "pages" / "settings.py").read_text(encoding="utf-8")
    # 「记录下载历史」必须出现在 ``_cookie_card`` 块内，不能再
    # 出现在 ``_network_card``。
    cookie_section = src[src.index("_cookie_card"):]
    assert "记录下载历史" in cookie_section
    # 反向：网络卡里不再有「下载历史」相关行。
    # 因为 _download_card 是先出现，``_cookie_card`` 是后出现，所以
    # 这个开关要不在 _download_card 与 _cookie_card 之间出现。
    download_section_end = src.index("_cookie_card")
    download_section_start = src.rindex("_download_card", 0, download_section_end)
    download_block = src[download_section_start:download_section_end]
    assert "记录下载历史" not in download_block


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
    # 0.3.14 插件卡（「功能插件」）与更新卡的公共方法。
    assert hasattr(cls, "_build_plugins_card")
    assert hasattr(cls, "_on_install_sniffer")
    assert hasattr(cls, "_refresh_plugin_status")
    assert hasattr(cls, "_build_update_card")


# -----------------------------------------------------------------------
# 0.3.14 — plugins card（体积策略的 GUI 面）
# -----------------------------------------------------------------------


def test_plugins_card_exists_with_sniffer_plugin():
    """「功能插件」卡必须在源码中存在，且管理通用嗅探插件。"""
    src = (SRC / "doubi" / "ui" / "pages" / "settings.py").read_text(encoding="utf-8")
    assert "功能插件" in src
    assert "_build_plugins_card" in src
    # 卡内必须引用 core.plugin_manager（检测与安装的唯一出口）
    assert "plugin_manager" in src
    assert "probe_sniffer_plugin" in src
    assert "install_sniffer_plugin" in src


def test_plugins_card_has_progress_feedback():
    """安装必须有进度反馈：进度条 + 阶段文案 + 日志行三件套。"""
    src = (SRC / "doubi" / "ui" / "pages" / "settings.py").read_text(encoding="utf-8")
    assert "_plugin_progress" in src          # ProgressBar
    assert "_plugin_stage_label" in src       # 当前阶段
    assert "_plugin_log_label" in src         # 最近日志行
    # 安装期间按钮必须禁用（防重复点击）
    assert 'btn.setText("安装中…")' in src
