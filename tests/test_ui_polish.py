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


def test_empty_state_has_air_between_title_and_subtitle(qapp):
    """Regression for the 'compressed empty-state text' bug.

    Title (14px) and subtitle (12px) used to render visually overlapping
    because layout spacing was SPACE_MD (12px) and labels had no
    padding/line-height. This test locks the spacing >= SPACE_LG, the
    minimum height, and the existence of line-height in the stylesheet
    so that any future revert breaks loudly.
    """
    _require_gui()
    from doubi.ui.theme import SPACE_LG
    from doubi.ui.widgets import build_empty_state
    EmptyState = build_empty_state()
    e = EmptyState()
    try:
        layout = e.layout()
        assert layout.spacing() >= SPACE_LG, (
            f"EmptyState spacing={layout.spacing()} too tight; "
            f"title and subtitle will visually overlap. "
            f"Must be >= SPACE_LG ({SPACE_LG})."
        )
        assert e.minimumHeight() >= 140, (
            f"EmptyState minHeight={e.minimumHeight()} too small; "
            f"parent QScrollArea + addStretch will squeeze the card flat."
        )
        # Stylesheet must include line-height; without it, padding alone
        # won't save a single line of 12px text.
        title_ss = e._title.styleSheet().lower()
        sub_ss = e._subtitle.styleSheet().lower()
        assert "line-height" in title_ss
        assert "line-height" in sub_ss
        assert "padding" in title_ss
        assert "padding" in sub_ss

        # 实测字号——qfluentwidgets 的 StrongBodyLabel 不响应 widget 级
        # setStyleSheet 的 font-size，会被自身 18px+ 默认样式覆盖，
        # 这是历史上 EmptyState 看起来"被压扁"的真正根因。
        # 一旦字号不是设计值，无论 spacing/padding/line-height 怎么调，
        # 卡片都会被撑爆。锁字号是守住版式的最后一道闸。
        from doubi.ui.theme import TYPE_BODY, TYPE_CAPTION
        title_px = e._title.font().pixelSize()
        if title_px <= 0:
            title_px = e._title.fontInfo().pixelSize()
        assert title_px == TYPE_BODY + 1, (
            f"EmptyState title font.pixelSize={title_px} "
            f"!= TYPE_BODY+1 ({TYPE_BODY + 1}). "
            f"StrongBodyLabel swallows widget-level font-size; "
            f"use QLabel+setFont instead."
        )
        sub_px = e._subtitle.font().pixelSize()
        if sub_px <= 0:
            sub_px = e._subtitle.fontInfo().pixelSize()
        assert sub_px == TYPE_CAPTION, (
            f"EmptyState subtitle font.pixelSize={sub_px} "
            f"!= TYPE_CAPTION ({TYPE_CAPTION})."
        )

        # 实测水平 fill——EmptyState 嵌在 active_list_layout 里时，
        # 若 label 用默认 sizePolicy (Preferred)，layout 给它们的宽度
        # 只有 sizeHint.width()（"刚好装下文字"），副标题就被压缩到 244px
        # 左右、252px 的文字触发换行、最后一个字被甩到第二行。
        # 必须 Expanding，让 label 拿到父容器给的全部宽度。
        from PySide6.QtWidgets import QSizePolicy
        assert e._title.sizePolicy().horizontalPolicy() == QSizePolicy.Expanding, (
            f"EmptyState title horizontalPolicy must be Expanding; "
            f"otherwise the label collapses to sizeHint.width() and "
            f"long subtitles wrap onto a second line with a single orphan."
        )
        assert e._subtitle.sizePolicy().horizontalPolicy() == QSizePolicy.Expanding, (
            f"EmptyState subtitle horizontalPolicy must be Expanding; "
            f"otherwise the label collapses to sizeHint.width() and "
            f"long subtitles wrap onto a second line with a single orphan."
        )
    finally:
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


def test_about_dialog_uses_brand_window_icon(qapp):
    """关于对话框必须设 windowIcon，否则 Windows 任务栏会回退到
    python.exe 的双蛇 logo（与品牌严重不符）。
    """
    _require_gui()
    from doubi.ui.dialogs.about_dialog import build_about_dialog
    dlg = build_about_dialog()()
    try:
        icon = dlg.windowIcon()
        assert not icon.isNull(), "关于 dialog 应当带品牌 windowIcon"
        assert any(s.width() >= 32 for s in icon.availableSizes()), \
            "至少有一档 ≥32px 的图标（任务栏最小需求）"
    finally:
        dlg.deleteLater()


def test_login_dialogs_use_brand_window_icon(qapp):
    """B 站扫码、抖音 browser 两个 dialog 同样要带品牌 icon。

    这两个 dialog 是用户登账号的入口——窗口标题栏 / Alt+Tab 显示
    Python 默认图标会显得很「不专业」，也容易和别的 Python 工具混淆。
    """
    _require_gui()
    from doubi.ui.dialogs.login_dialog import (
        build_bilibili_qr_dialog, build_douyin_browser_dialog,
    )
    for factory in (build_bilibili_qr_dialog, build_douyin_browser_dialog):
        dlg = factory()()
        try:
            icon = dlg.windowIcon()
            assert not icon.isNull(), f"{factory.__name__} 缺品牌 windowIcon"
        finally:
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


# ---------------------------------------------------------------------------
# 图标管线：SVG 模板 + 主题换色 + 矢量渲染
# ---------------------------------------------------------------------------


def _brand_hexes():
    from doubi.ui.resources import BRAND_PALETTE
    return set(BRAND_PALETTE.values())


def test_icon_template_exists_and_holds_all_anchors():
    """模板必须包含全部 7 个品牌色锚点，否则换色会漏项。"""
    from doubi.ui.resources import BRAND_PALETTE, icon_template_path
    p = icon_template_path()
    assert p.is_file(), f"渲染模板应存在：{p}"
    text = p.read_text(encoding="utf-8")
    for key, value in BRAND_PALETTE.items():
        assert value in text, f"模板缺少 {key} 锚点 {value}"


def test_icon_template_has_no_unsupported_svg_features():
    """回归守卫：模板不得含 filter / clipPath。

    Qt 只实现 SVG Tiny 1.2，原始设计稿的 feColorMatrix 会被误渲染成
    实心黑圆角矩形（实测 29% 像素变纯黑），整张图标糊掉。
    """
    import re
    from doubi.ui.resources import icon_template_path
    text = icon_template_path().read_text(encoding="utf-8")
    # 头部注释会解释为什么去掉这些特性，检查前先剥掉注释只看真实标记
    markup = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    for token in ("<filter", "<clipPath", "filter=", "clip-path=", "<fe"):
        assert token not in markup, f"模板含 QtSvg 不支持的 {token}"


def test_icon_palette_none_is_brand_palette():
    from doubi.ui.resources import BRAND_PALETTE, icon_palette
    assert icon_palette(None) == BRAND_PALETTE
    assert icon_palette("") == BRAND_PALETTE


def test_icon_palette_invalid_accent_falls_back_to_brand():
    """脏色值不能让图标渲染失败，必须退化到品牌色。"""
    from doubi.ui.resources import BRAND_PALETTE, icon_palette
    for bad in ("not-a-color", "#12", "#gggggg", "rgb(1,2,3)"):
        assert icon_palette(bad) == BRAND_PALETTE, bad


def test_icon_palette_derives_full_key_set_with_valid_hex():
    from doubi.ui.resources import BRAND_PALETTE, icon_palette
    palette = icon_palette("#2dd4bf")
    assert set(palette) == set(BRAND_PALETTE)
    for key, value in palette.items():
        assert value.startswith("#") and len(value) == 7, f"{key}={value}"
        int(value[1:], 16)  # 必须是合法 hex


def test_icon_palette_keeps_mascot_features_fixed():
    """腮红 / 舌头 / 眼睛是角色辨识度，跟主题变色会丢掉可爱感。"""
    from doubi.ui.resources import BRAND_PALETTE, icon_palette
    for accent in ("#0078d4", "#2dd4bf", "#ffd60a", "#8c7b6b"):
        palette = icon_palette(accent)
        for key in ("ink", "blush", "tongue"):
            assert palette[key] == BRAND_PALETTE[key], f"{accent} 改了 {key}"


def test_icon_palette_recolors_background_and_face():
    from doubi.ui.resources import BRAND_PALETTE, icon_palette
    palette = icon_palette("#0078d4")
    for key in ("bg_from", "bg_to", "face", "tuft"):
        assert palette[key] != BRAND_PALETTE[key], f"{key} 未换色"


def test_icon_palette_respects_low_saturation_accent():
    """莫兰迪这类低饱和主题不能被拉成刺眼的高饱和橙。"""
    import colorsys
    from doubi.ui.resources import icon_palette

    def sat(hex_color: str) -> float:
        r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
        return colorsys.rgb_to_hls(r, g, b)[2]

    muted = sat(icon_palette("#8c7b6b")["bg_from"])   # 莫兰迪
    vivid = sat(icon_palette("#0078d4")["bg_from"])   # 默认亮
    assert muted < vivid, "低饱和主题的图标底板应当更柔和"


def test_icon_svg_substitutes_anchors_without_leak():
    """换色后不能残留任何被替换掉的锚点色。"""
    from doubi.ui.resources import BRAND_PALETTE, icon_svg
    markup = icon_svg("#2dd4bf")
    assert markup
    for key in ("bg_from", "bg_to", "face", "tuft"):
        assert BRAND_PALETTE[key] not in markup, f"{key} 锚点残留"


def test_icon_svg_brand_is_template_verbatim():
    from doubi.ui.resources import icon_svg, icon_template_path
    assert icon_svg(None) == icon_template_path().read_text(encoding="utf-8")


def _to_image(pix):
    return pix.toImage()


def test_render_icon_pixmap_size_and_no_black_block(qapp):
    """核心回归：渲染结果不得出现大面积纯黑（旧 filter bug 的症状）。"""
    _require_gui()
    from doubi.ui.resources import render_icon_pixmap
    pix = render_icon_pixmap(128, themed=False)
    assert pix is not None and not pix.isNull()
    assert pix.width() == 128 and pix.height() == 128

    img = _to_image(pix)
    black = 0
    for y in range(0, 128, 2):
        for x in range(0, 128, 2):
            c = img.pixelColor(x, y)
            if c.alpha() == 255 and c.red() < 8 and c.green() < 8 and c.blue() < 8:
                black += 1
    total = (128 // 2) ** 2
    assert black / total < 0.05, f"纯黑占比 {black / total:.1%}，filter 又被渲染了"


def test_render_icon_pixmap_is_full_bleed(qapp):
    """viewBox 收紧后圆角方块必须铺满画布：中心不透明、角上透明。"""
    _require_gui()
    from doubi.ui.resources import render_icon_pixmap
    img = _to_image(render_icon_pixmap(128, themed=False))
    assert img.pixelColor(64, 64).alpha() == 255, "中心应当不透明"
    assert img.pixelColor(0, 0).alpha() == 0, "左上角应当被圆角切掉"
    # 出血：边线中点必须落在图形上，说明没有留白边
    assert img.pixelColor(64, 1).alpha() == 255, "顶边中点应当有像素（无留白）"


def test_render_icon_pixmap_rejects_non_positive_size(qapp):
    _require_gui()
    from doubi.ui.resources import render_icon_pixmap
    assert render_icon_pixmap(0) is None
    assert render_icon_pixmap(-8) is None


def test_load_app_icon_offers_all_declared_sizes(qapp):
    """多档尺寸是为了标题栏 / 任务栏各挑一档，避免系统缩放出锯齿。"""
    _require_gui()
    from doubi.ui.resources import ICON_SIZES, load_app_icon
    icon = load_app_icon()
    assert icon is not None and not icon.isNull()
    widths = {s.width() for s in icon.availableSizes()}
    for size in ICON_SIZES:
        assert size in widths, f"缺少 {size}px 档位"


def test_themed_icons_differ_between_themes(qapp):
    """不同主题渲染出的图标像素必须不同，否则换色没生效。"""
    _require_gui()
    from doubi.ui.resources import render_icon_pixmap

    def signature(accent):
        img = _to_image(render_icon_pixmap(48, accent, themed=False))
        # 取左上偏内一点：稳定落在底板渐变上
        return img.pixelColor(10, 24).rgb()

    brand = signature(None)
    blue = signature("#0078d4")
    teal = signature("#2dd4bf")
    assert len({brand, blue, teal}) == 3, "三套配色应当渲染出三种底板色"


def test_active_accent_is_none_for_brand_theme(qapp):
    """豆比紫本身取自图标，二次推导只会偏离原图，必须走品牌原色。"""
    _require_gui()
    from doubi.ui import resources
    from doubi.ui.theme import current_theme_name, set_theme
    saved = current_theme_name()
    try:
        set_theme("doubi")
        assert resources._active_accent() is None
        set_theme("deep_sea")
        assert resources._active_accent() == "#2dd4bf"
    finally:
        set_theme(saved)


def test_load_app_icon_follows_current_theme(qapp):
    """load_app_icon() 不传参时应当跟着当前主题换色。"""
    _require_gui()
    from doubi.ui.resources import render_icon_pixmap
    from doubi.ui.theme import current_theme_name, set_theme
    saved = current_theme_name()
    try:
        set_theme("doubi")
        brand = _to_image(render_icon_pixmap(48)).pixelColor(10, 24).rgb()
        set_theme("high_contrast")
        vivid = _to_image(render_icon_pixmap(48)).pixelColor(10, 24).rgb()
        assert brand != vivid, "切主题后图标底板色应当变化"
    finally:
        set_theme(saved)


def test_load_splash_pixmap_uses_min_side(qapp):
    _require_gui()
    from doubi.ui.resources import load_splash_pixmap
    pix = load_splash_pixmap(256, 256)
    assert pix is not None and pix.width() == 256
    assert load_splash_pixmap(0, 0) is None


def test_clear_icon_cache_is_safe(qapp):
    _require_gui()
    from doubi.ui.resources import clear_icon_cache, load_app_icon
    assert load_app_icon(32) is not None
    clear_icon_cache()
    assert load_app_icon(32) is not None


def test_fallback_png_is_high_resolution():
    """兜底 PNG 至少 1024px——标题栏缩放和打包转 ico 都靠它。"""
    _require_gui()
    from PySide6.QtGui import QImageReader
    from doubi.ui.resources import icon_path
    size = QImageReader(str(icon_path())).size()
    assert size.width() >= 1024, f"兜底图标只有 {size.width()}px"
    assert size.width() == size.height(), "图标应当是正方形"


# ---------------------------------------------------------------------------
# 标题栏应用图标：尺寸放大 + 随主题换色
# ---------------------------------------------------------------------------


# 注：标题栏图标的「尺寸放大 + 主题换色」原本要在单元测试里覆盖，
# 但每多构造一个 MainWindow 都会向 subscribe_theme 注册一个
# ``_refresh_app_icon`` 回调，deleteLater 排队未执行 → 跨文件串联时
# 残留 4~5 个死回调，导致 test_theme_apply_gui 那 28 个 set_theme
# 用例从「3 分慢」劣化成 hang。
# 既然这套链路在真机已被 ``verify_icon_*.png`` 量化采样（7 主题
# 7 种底板色）和 ``verify_window_doubi.png`` 视觉确认过，单元测试
# 就不再重复构造主窗口——以防把整个 GUI 测试套锁死。
