"""回归测试：0.3.7 上线后实测反馈的两个界面缺陷。

**缺陷 1 — 导航栏蓝色指示条卡死**
    qfluentwidgets 的 ``NavigationBar`` 有一条独立的 ``indicator`` 子控件
    （4×24 圆角蓝条），只在 ``setCurrentItem`` 的滑动动画期间可见，动画结束
    由 ``_onIndicatorAniFinished`` 隐藏。窗口未显示、或事件循环被反复打断时
    动画跑不完，它就一直停在**上一个页面**的位置——实测从解析页依次切到
    设置页再切回解析页后，蓝条残留在「设置」旁边，灌 200 次 processEvents
    也不消失，看起来像两个页面同时被选中。

    修法是 ``setIndicatorAnimationEnabled(False)``：``setCurrentItem`` 直接
    走 ``setSelected(k == routeKey)`` 分支，不做动画也不显示该子控件。

    ⚠️ 注意区分 qfluentwidgets 里**两条**不同的蓝条：
      * ``NavigationBar.indicator``（子控件，会卡）← 本测试守的是这条
      * ``NavigationBarPushButton._drawBackground`` 里按 ``isSelected`` 画的
        那条（``drawRoundedRect(0, 16, 4, 24)``）是既定设计，**不该**消失

**缺陷 2 — 历史页表格列宽失衡**
    6 列全用 Qt 默认 100px，表格只用到约 600px：
    「ID」「下载时间」「保存目录」全部只剩省略号，右侧还空 400 多像素。
    修法是给短列按真实内容宽度定量、标题列 Stretch，并把保存目录裁成
    有辨识度的一行。
"""

from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _require_qt():
    try:
        import PySide6  # noqa: F401
        import qfluentwidgets  # noqa: F401
    except Exception as exc:   # noqa: BLE001
        pytest.skip(f"GUI stack unavailable: {exc}")


@pytest.fixture(scope="module")
def qapp():
    _require_qt()
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


def _build_window(qapp):
    from doubi.core.config import load_config
    from doubi.ui.i18n import set_language
    from doubi.ui.main_window import build_main_window
    from doubi.ui.theme import set_theme

    cfg = load_config(None)
    set_theme(cfg.theme)
    set_language(cfg.language)
    MainWindow = build_main_window()
    win = MainWindow()
    win.resize(1100, 760)
    return win


# ---------------------------------------------------------------------------
# 缺陷 1：导航指示条
# ---------------------------------------------------------------------------


def test_nav_indicator_animation_disabled_at_construction(qapp):
    """主窗口构造后，导航指示条动画必须已经是关的。

    这是修复的**唯一前提**——只要它被重新打开，下面的卡死就会复现。
    """
    win = _build_window(qapp)
    assert win.navigationInterface.isIndicatorAnimationEnabled() is False
    win.deleteLater()


def test_nav_indicator_widget_never_stays_visible_after_switching(qapp):
    """反复切页后，动画型指示条子控件不得停留在可见状态。

    这正是用户看到的「两个页面同时选中」：蓝条留在上一页旁边。

    ⚠️ **局限：这条用例在 offscreen 下抓不到真缺陷。**
    实测（``QT_QPA_PLATFORM=offscreen``）即使把动画重新打开，蓝条也不会
    卡住——offscreen 插件没有真实的窗口/曝光状态，动画能正常跑完。
    卡死只在真实平台插件（windows）下复现，因此 CI 里这条用例**必然通过**，
    它守的是「别把动画又打开」这个前提（见上一条用例），以及防止将来
    有人在 offscreen 友好路径上引入新的残留。真正的实机验证见
    ``.scratch/probe_indicator_stuck.py`` / ``.scratch/verify_indicator_fix.py``。
    """
    win = _build_window(qapp)
    bar = win.navigationInterface
    indicator = bar.indicator

    pages = [
        win.parse_interface,
        win.download_interface,
        win.history_interface,
        win.search_interface,
        win.hot_interface,
        win.settings_interface,
    ]

    for _ in range(3):
        for page in pages:
            win.switchTo(page)
            for _ in range(3):
                qapp.processEvents()
            assert not indicator.isVisible(), (
                f"切到 {page.objectName()} 之后动画指示条仍然可见"
                f"（几何 {indicator.geometry().getRect()}），会看起来像双重选中"
            )

    # 回到解析页：真实平台上旧版本会残留在「设置」的位置
    win.switchTo(win.parse_interface)
    for _ in range(50):
        qapp.processEvents()
    assert not indicator.isVisible(), "回到解析页后指示条残留"

    win.deleteLater()


def test_nav_selection_follows_current_page(qapp):
    """关掉动画后选中态必须依然精确（且只有一个）。"""
    win = _build_window(qapp)
    bar = win.navigationInterface

    for page in (
        win.download_interface,
        win.history_interface,
        win.settings_interface,
        win.parse_interface,
    ):
        win.switchTo(page)
        qapp.processEvents()

        selected = [k for k, item in bar.items.items() if item.isSelected]
        assert selected == [page.objectName()], (
            f"当前页 {page.objectName()}，但处于选中态的项是 {selected}"
        )

    win.deleteLater()


def test_switch_to_missing_widget_is_a_noop(qapp):
    """``_switch_to`` 传一个不在 stackedWidget 里的 widget 必须静默返回。

    未加守卫时 ``switchTo`` 会抛 ``Exception: The index '-1' is illegal``。
    """
    from PySide6.QtWidgets import QWidget

    win = _build_window(qapp)
    stranger = QWidget()

    before = win.stackedWidget.currentWidget()
    win._switch_to(stranger)          # 不得抛异常
    qapp.processEvents()
    assert win.stackedWidget.currentWidget() is before

    win._switch_to(None)              # None 也必须安全
    win.deleteLater()


# ---------------------------------------------------------------------------
# 缺陷 2：历史页列宽
# ---------------------------------------------------------------------------


def test_history_columns_use_available_width(qapp):
    """列宽总和应当铺满表格可用宽度，而不是只用掉 600px。"""
    win = _build_window(qapp)
    page = win.history_interface
    win.switchTo(page)
    for _ in range(5):
        qapp.processEvents()

    table = page.table
    total = sum(table.columnWidth(c) for c in range(table.columnCount()))
    avail = table.viewport().width()

    # 允许少量舍入差异；关键是「不再只用掉一半宽度」
    assert total >= avail - 8, (
        f"列宽合计 {total} 远小于表格可用宽度 {avail}，右侧会留大片空白"
    )
    win.deleteLater()


def test_history_title_column_is_the_stretching_one(qapp):
    """标题列必须是 Stretch——它最长、最需要空间。"""
    from PySide6.QtWidgets import QHeaderView

    win = _build_window(qapp)
    page = win.history_interface
    header = page.table.horizontalHeader()
    # 列序：平台 / ID / 标题 / 作者 / 下载时间 / 保存目录
    assert header.sectionResizeMode(2) == QHeaderView.Stretch
    for col in (0, 1, 3, 4, 5):
        assert header.sectionResizeMode(col) == QHeaderView.Fixed
    win.deleteLater()


def test_history_time_column_fits_a_full_timestamp(qapp):
    """「下载时间」列必须能装下 ``YYYY-MM-DD HH:MM``（16 字符）。

    修之前它是默认 100px，连 ``2026-10-...`` 都读不全。
    """
    win = _build_window(qapp)
    page = win.history_interface
    width = page.table.columnWidth(4)
    need = page.table.fontMetrics().horizontalAdvance("2026-10-05 09:16")
    assert width >= need, (
        f"下载时间列宽 {width} 装不下完整时间戳（需要 {need}）"
    )
    win.deleteLater()


def test_short_dir_strips_redundant_affixes(qapp):
    """保存目录要在显示层剥掉固定前缀/后缀，但原始记录保持不变。

    ``_short_dir`` 定义在 ``build_history_widgets`` 工厂内部，属于页面实例
    的私有方法。这里直接调它，并用真实形状的路径断言（实测 351/351 条
    记录都是 ``Downloaded\\<platform>\\<author>\\video``）。
    """
    win = _build_window(qapp)
    page = win.history_interface

    assert page._short_dir(r"Downloaded\bilibili\中华球侠\video") == r"bilibili\中华球侠"
    assert page._short_dir(r"Downloaded\douyin\Rocky讲英语\video") == r"douyin\Rocky讲英语"
    assert page._short_dir(r"Downloaded\generic\unknown_author\video") == r"generic\unknown_author"
    # 正斜杠路径同样处理（跨平台历史数据）
    assert page._short_dir("Downloaded/bilibili/中华球侠/video") == r"bilibili\中华球侠"
    # 空值安全
    assert page._short_dir("") == ""
    assert page._short_dir(None) == ""
    # 形状意外的路径不能被削成空串
    assert page._short_dir(r"D:\我自己的目录\片子") != ""

    win.deleteLater()


# ---------------------------------------------------------------------------
# 缺陷 1 的**真实平台**守卫
#
# 上面那条 indicator 用例在 offscreen 下抓不到卡死（见其 docstring）。
# 这条用例强制跑在真实平台插件上，才能真正复现并守住缺陷。
# 在没有真实图形环境的机器上跳过。
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("QT_QPA_PLATFORM", "").startswith("offscreen"),
    reason="卡死只在真实平台插件下复现；offscreen 跑不出这个缺陷",
)
def test_nav_indicator_does_not_get_stuck_on_real_platform(qapp):
    """真实平台下：反复切页后蓝条必须跟随当前页，不得停留在他处。

    复现路径（0.3.7 实测）：解析 → 下载 → 历史 → 搜索 → 热榜 → 设置 →
    回到解析。旧版本（动画开启）的实际症状比「双重选中」更糟——
    ``item.isSelected`` 全为 False，**没有任何一项处于选中态**，
    而蓝条孤零零地留在「设置」的位置。
    """
    win = _build_window(qapp)
    bar = win.navigationInterface
    indicator = bar.indicator

    pages = [
        win.parse_interface,
        win.download_interface,
        win.history_interface,
        win.search_interface,
        win.hot_interface,
        win.settings_interface,
    ]
    for _ in range(3):
        for page in pages:
            win.switchTo(page)
            qapp.processEvents()

    win.switchTo(win.parse_interface)
    for _ in range(50):
        qapp.processEvents()

    # 关键断言：动画型指示条不得可见。它在旧版本里会停在「设置」旁边。
    assert not indicator.isVisible(), (
        "动画型导航指示条卡住了："
        f"几何 {indicator.geometry().getRect()}，当前页应为解析页"
    )
    # 选中态仍然只有当前页一个
    selected = [k for k, item in bar.items.items() if item.isSelected]
    assert selected == [win.parse_interface.objectName()]

    win.deleteLater()
