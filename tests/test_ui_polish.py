"""M6.x UI 美化相关的回归测试。

覆盖：

* 「豆比紫」主题存在、token 完整、brand hero 渐变存在
* 排版 / 间距常量在所有主题下都可用
* 主题的「豆比紫」色值取自图标（与图标背景色同色系），不漂移
* 共享 widgets（PageHeader / EmptyState / StatChip / PlatformBadge）不依赖 PySide6
  也能 import（部分辅助方法不需要 Qt）
* resources 模块的图标路径、品牌名、版本号都是可序列化的
* 旧的 token 仍然存在——下游代码（download / parse / settings）按名取色
  不会因为重命名而 KeyError
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


@pytest.fixture(scope="module")
def qapp():
    """共享的 QApplication 实例——避免每个测试都重建导致 hang。"""
    _require_gui()
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


# ---------------------------------------------------------------------------
# 主题
# ---------------------------------------------------------------------------


def test_doubi_brand_theme_registered():
    """「豆比紫」是品牌主题，必须在 THEMES 字典里。"""
    from doubi.ui.theme import THEMES
    assert "doubi" in THEMES, "豆比紫主题应该作为品牌默认主题存在"
    pack = THEMES["doubi"]
    # 配色与图标同色系
    assert pack.dark is True
    # 强调色取自图标嘴巴/腮红的橙色
    assert pack.accent.lower() in ("#f59e6a",), \
        f"豆比紫主色应当是橙色 #f59e6a（图标嘴/腮红），实际是 {pack.accent}"
    # 渐变要存在——品牌 hero 用得上
    assert pack.gradient_header, "豆比紫必须有 header 渐变"


def test_every_theme_has_full_token_set():
    """所有主题必须声明相同的 token 键集——下游代码按名取色，缺一个就红。"""
    from doubi.ui.theme import THEMES

    required = {
        "bg_base", "bg_layer", "bg_hover",
        "text_primary", "text_muted",
        "row_odd", "row_even",
        "status_running_fg", "status_running_bg",
        "status_paused_fg", "status_paused_bg",
        "status_completed_fg", "status_completed_bg",
        "status_failed_fg", "status_failed_bg",
        "status_cancelled_fg", "status_cancelled_bg",
        "progress_normal", "progress_success", "progress_error", "progress_paused",
        "radius", "radius_card", "radius_pill", "row_height",
        "shadow_sm", "shadow_md", "shadow_lg",
    }
    for name, pack in THEMES.items():
        missing = required - pack.tokens.keys()
        assert not missing, f"主题 {name} 缺少 token: {missing}"


def test_theme_pack_has_brand_color_fields():
    """所有主题包都必须有 ``accent_soft`` / ``accent_strong`` 等新字段。

    旧版 dataclass 没有这些字段——给的是空字符串默认值，新代码按字段
    取色时不应该抛 AttributeError。
    """
    from doubi.ui.theme import THEMES
    for name, pack in THEMES.items():
        assert isinstance(pack.accent, str) and pack.accent
        # accent_soft 默认为空字符串，但属性必须存在
        assert hasattr(pack, "accent_soft")
        assert hasattr(pack, "accent_strong")
        assert hasattr(pack, "bg_elevated")
        assert hasattr(pack, "gradient_header")
        assert hasattr(pack, "shadow")


# ---------------------------------------------------------------------------
# 排版 / 间距常量
# ---------------------------------------------------------------------------


def test_typography_constants_are_exposed():
    from doubi.ui import theme as theme_mod

    # 这些常量下游页面代码会用到，命名空间必须存在
    for name in (
        "FONT_FAMILY", "FONT_FAMILY_MONO",
        "TYPE_H1", "TYPE_H2", "TYPE_H3", "TYPE_BODY", "TYPE_CAPTION", "TYPE_TINY",
        "SPACE_XS", "SPACE_SM", "SPACE_MD", "SPACE_LG", "SPACE_XL", "SPACE_XXL",
        "RADIUS_DEFAULT", "RADIUS_CARD", "RADIUS_PILL",
    ):
        assert hasattr(theme_mod, name), f"主题模块应当暴露 {name}"
    # 字号按尺度单调递增
    assert theme_mod.TYPE_H1 > theme_mod.TYPE_H2 > theme_mod.TYPE_H3 > theme_mod.TYPE_BODY
    assert theme_mod.TYPE_BODY > theme_mod.TYPE_CAPTION > theme_mod.TYPE_TINY
    # 间距按尺度单调递增
    assert theme_mod.SPACE_XS < theme_mod.SPACE_SM < theme_mod.SPACE_MD < theme_mod.SPACE_LG
    assert theme_mod.SPACE_XL < theme_mod.SPACE_XXL


def test_helper_qss_functions_return_strings():
    """``heading_qss`` / ``body_qss`` / ``card_qss`` / ``muted_qss`` 应当返回 CSS。"""
    _require_gui()
    from doubi.ui.theme import (
        body_qss, card_qss, heading_qss, muted_qss, set_theme,
    )
    set_theme("default_light")
    for qss in (
        heading_qss(1),
        heading_qss(2),
        heading_qss(3),
        body_qss(),
        card_qss(),
        card_qss(elevated=True),
        muted_qss(),
    ):
        assert isinstance(qss, str) and len(qss) > 0


def test_header_qss_uses_gradient_or_fallback():
    """header_qss 在有渐变的主题里走渐变，没有的走纯色。"""
    _require_gui()
    from doubi.ui.theme import header_qss, set_theme

    set_theme("doubi")
    qss = header_qss(1)
    assert "qlineargradient" in qss  # 豆比紫有渐变

    set_theme("default_light")
    qss = header_qss(1)
    # default_light 没填 gradient_header → 退化到纯色
    assert "qlineargradient" not in qss


# ---------------------------------------------------------------------------
# 颜色辅助
# ---------------------------------------------------------------------------


def test_hex_to_rgba_handles_six_digit():
    from doubi.ui.theme import _hex_to_rgba
    assert _hex_to_rgba("#ff0000", 0.5) == "rgba(255, 0, 0, 0.5)"
    assert _hex_to_rgba("#00ff00", 0.1) == "rgba(0, 255, 0, 0.1)"


def test_hex_to_rgba_falls_back_on_bad_input():
    from doubi.ui.theme import _hex_to_rgba
    # 不是 6 位 → 退化为灰
    assert _hex_to_rgba("#fff", 0.5) == "rgba(128, 128, 128, 0.5)"
    assert _hex_to_rgba("not-a-color", 0.2) == "rgba(128, 128, 128, 0.2)"


def test_lighten_and_darken_move_in_expected_direction():
    from doubi.ui.theme import _darken, _lighten
    base = "#808080"
    # 提亮后 R/G/B 都应 ≥ 原值
    lighter = _lighten(base, 0.5)
    r = int(lighter[1:3], 16)
    assert r >= 128
    # 压暗后 R/G/B 都应 ≤ 原值
    darker = _darken(base, 0.5)
    r = int(darker[1:3], 16)
    assert r <= 128


# ---------------------------------------------------------------------------
# 资源 / 品牌
# ---------------------------------------------------------------------------


def test_brand_metadata_is_static():
    """APP_NAME / APP_VERSION / APP_COPYRIGHT 都是字符串，不依赖 PySide6。"""
    from doubi.ui.resources import (
        APP_COPYRIGHT, APP_DISPLAY_NAME, APP_NAME, APP_TAGLINE, APP_VERSION,
    )
    assert APP_NAME == "DouBi"
    assert isinstance(APP_VERSION, str) and APP_VERSION
    assert isinstance(APP_TAGLINE, str) and APP_TAGLINE
    assert isinstance(APP_COPYRIGHT, str) and APP_COPYRIGHT
    assert isinstance(APP_DISPLAY_NAME, str) and APP_DISPLAY_NAME


def test_icon_path_resolves_inside_package():
    """图标路径必须用 __file__ 锚定，PyInstaller 打包后也能找到。"""
    from doubi.ui.resources import RESOURCE_DIR, icon_path
    p = icon_path()
    # 路径应当是 RESOURCES_DIR/icon.png
    assert p == RESOURCE_DIR / "icon.png"
    # 真实文件存在（资源与代码同步）
    assert p.is_file(), f"图标文件应存在：{p}"


def test_load_app_icon_returns_qicon_when_qt_available(qapp):
    _require_gui()
    from doubi.ui.resources import load_app_icon
    icon = load_app_icon(64)
    assert icon is not None and not icon.isNull()


def test_load_app_icon_size_none_returns_full(qapp):
    _require_gui()
    from doubi.ui.resources import load_app_icon
    icon = load_app_icon()
    assert icon is not None and not icon.isNull()


# ---------------------------------------------------------------------------
# 共享 widgets 工厂（不实例化，只确认可调用且不抛）
# ---------------------------------------------------------------------------


def test_widget_factories_callable_without_error():
    """所有共享 widget 的工厂函数应当可调用。"""
    _require_gui()
    from doubi.ui.widgets import (
        build_empty_state, build_page_header, build_platform_badge,
        build_section_divider, build_stat_chip,
    )
    for factory in (
        build_page_header, build_empty_state, build_stat_chip,
        build_platform_badge, build_section_divider,
    ):
        assert callable(factory)


def test_page_header_set_text_methods(qapp):
    _require_gui()
    from doubi.ui.widgets import build_page_header
    PageHeader = build_page_header()
    h = PageHeader()
    h.set_title("测试")
    h.set_subtitle("副标题")
    h.add_stretch()
    assert h._title.text() == "测试"
    assert h._subtitle.text() == "副标题"
    h.deleteLater()


def test_empty_state_set_text(qapp):
    _require_gui()
    from doubi.ui.widgets import build_empty_state
    EmptyState = build_empty_state()
    e = EmptyState()
    e.set_text("主标题", "副标题")
    assert e._title_text == "主标题"
    assert e._subtitle_text == "副标题"
    e.refresh_text()
    assert e._title.text() == "主标题"
    e.deleteLater()


def test_stat_chip_set_value_and_kind(qapp):
    _require_gui()
    from doubi.ui.widgets import build_stat_chip
    StatChip = build_stat_chip()
    c = StatChip()
    c.set_value(7)
    c.set_label("运行中")
    c.set_kind("running")
    assert c._value.text() == "7"
    assert c._label.text() == "运行中"
    assert c._kind == "running"
    c.deleteLater()


def test_platform_badge_set_platform(qapp):
    _require_gui()
    from doubi.ui.widgets import build_platform_badge
    PlatformBadge = build_platform_badge()
    b = PlatformBadge()
    b.set_platform("抖音")
    assert b._platform == "抖音"
    assert b.text() == "抖音"
    b.deleteLater()


# ---------------------------------------------------------------------------
# 关于对话框
# ---------------------------------------------------------------------------


def test_about_dialog_factory_callable():
    _require_gui()
    from doubi.ui.dialogs.about_dialog import build_about_dialog
    cls = build_about_dialog()
    assert callable(cls)


def test_about_dialog_can_instantiate(qapp):
    _require_gui()
    from doubi.ui.dialogs.about_dialog import build_about_dialog
    cls = build_about_dialog()
    dlg = cls()
    assert dlg.windowTitle().startswith("关于")
    dlg.deleteLater()


# ---------------------------------------------------------------------------
# 关于 app.py / splash
# ---------------------------------------------------------------------------


def test_splash_factory_does_not_crash_without_icon(qapp):
    """图标文件丢失时 splash 应当静默退化到 None，不抛异常。"""
    _require_gui()
    from doubi.ui import splash as splash_mod
    s = splash_mod.show_splash(qapp)
    if s is not None:
        splash_mod.finish_splash(s)


def test_app_help_lists_all_themes(capsys):
    """doubi-gui --help 必须把 7 个主题 key 都列出来。"""
    from doubi.ui.app import main
    import sys
    saved = sys.argv
    try:
        sys.argv = ["doubi-gui", "--help"]
        try:
            main(["--help"])
        except SystemExit:
            pass
    finally:
        sys.argv = saved
    out = capsys.readouterr().out
    # argparse 的 choices 列出的是稳定 key，不是 label
    for key in ("doubi", "default_light", "default_dark",
                "deep_sea", "morandi", "eye_care", "high_contrast"):
        assert key in out, f"--help 应列出主题 {key}"
