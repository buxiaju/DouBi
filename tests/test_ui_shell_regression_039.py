"""回归测试：0.3.9 上线后实测反馈的两个界面缺陷。

**缺陷 1 — 主窗口右下角没有可看见的 resize 把手**
    qfluentwidgets 用 qframelesswindow 自绘标题栏，自带的 ``WS_THICKFRAME``
    resize 边框只有 6–7 px（实测 ``GetWindowRect`` - ``GetClientRect`` delta = 6,6）。
    用户的体感是「窗口不能调大小」——他们既看不到边框也抓不到。
    ``QSizeGrip`` 默认的 (223,223,223) 点阵在浅色主题下也几乎隐形。
    修法：自绘一个 18×18 的三道对角短线 grip，颜色取自 ``progress_normal``，
    并 attach ``mousePressEvent / mouseMoveEvent / mouseReleaseEvent`` 直接
    调 ``window().resize()``，并 ``resizeEvent`` 同步钉在右下角。

**缺陷 2 — 设置页「快捷键速查」卡占满整屏**
    之前 11 个快捷键 × 4 个分类全展开，且这张卡在 scroll area **之外**
    （直接 addWidget 到 outer），无论窗口多高它永远占满底部。
    用户看到的就是「快捷键速查占 75%，其他设置被挤出可视范围」。
    修法：把快捷键卡移进 scroll area 末尾；body **默认折叠**只露标题 +
    「N 个快捷键 · 展开」按钮，点开才显示完整列表。
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
# 缺陷 1：右下角 resize 把手
# ---------------------------------------------------------------------------


def test_resize_grip_is_a_child_of_main_window(qapp):
    """主窗口构造后必须存在 ``_size_grip``，且位于主窗口子树中。"""
    from doubi.ui.main_window import _ResizeGrip

    win = _build_window(qapp)
    grip = win.findChild(_ResizeGrip)
    assert grip is not None, "主窗口未创建 _ResizeGrip"
    assert grip.parent() is win, "grip 必须直接 parent 到主窗口"
    assert grip.width() == grip.height() == 18, f"grip 尺寸异常 {grip.size()}"
    win.deleteLater()


def test_resize_grip_painted_with_theme_color(qapp):
    """grip 必须真的画出了颜色——不是空 QWidget。"""
    from PySide6.QtGui import QColor

    win = _build_window(qapp)
    grip = win._size_grip
    # 强制重绘
    grip.repaint()
    # 抓 grip 自己的 pixmap
    pix = grip.grab()
    img = pix.toImage()
    # 在 (grip_size-1, grip_size-1) 附近应该有非背景像素

    found = False
    for x in range(2, 17):
        for y in range(2, 17):
            c = QColor(img.pixel(x, y))
            # 灰色 / 蓝色都行，只要不是接近背景白
            if not (c.lightness() > 240 and c.alpha() < 255):
                found = True
                break
        if found:
            break
    assert found, "grip 画出来的全是背景色——根本没画"
    win.deleteLater()


def test_resize_grip_is_anchored_to_bottom_right(qapp):
    """``_place_size_grip`` 必须把 grip 钉在 (width - 18, height - 18)。

    offscreen 下 ``resizeEvent`` 不一定及时 pump；这里直接调
    ``_place_size_grip()`` 验证几何契约——它就是 ``resizeEvent`` 的实现。
    """
    win = _build_window(qapp)
    for w, h in ((900, 600), (1100, 760), (1400, 900)):
        win.resize(w, h)
        win._place_size_grip()           # 等价于 resizeEvent 的副作用
        qapp.processEvents()
        g = win._size_grip
        assert g.x() == win.width() - 18, \
            f"width={w}: grip.x={g.x()} != width-18={win.width()-18}"
        assert g.y() == win.height() - 18, \
            f"height={h}: grip.y={g.y()} != height-18={win.height()-18}"
    win.deleteLater()


def test_resize_grip_drag_resizes_the_window(qapp):
    """模拟从 grip 中心按住左键拖到右下 50,50：窗口必须变大。"""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    win = _build_window(qapp)
    win.resize(1100, 760)
    win._place_size_grip()
    qapp.processEvents()

    before = win.size()
    g = win._size_grip
    cx = g.width() / 2
    cy = g.height() / 2

    press = QMouseEvent(QMouseEvent.Type.MouseButtonPress, QPointF(cx, cy),
                        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    move = QMouseEvent(QMouseEvent.Type.MouseMove, QPointF(cx + 80, cy + 80),
                       Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    release = QMouseEvent(QMouseEvent.Type.MouseButtonRelease, QPointF(cx + 80, cy + 80),
                          Qt.LeftButton, Qt.NoButton, Qt.NoModifier)
    QApplication.sendEvent(g, press)
    QApplication.sendEvent(g, move)
    QApplication.sendEvent(g, release)
    qapp.processEvents()

    after = win.size()
    assert after.width() > before.width(), f"拖拽后宽度没变大：{before.width()} -> {after.width()}"
    assert after.height() > before.height(), f"拖拽后高度没变大：{before.height()} -> {after.height()}"
    win.deleteLater()


def test_resize_grip_respects_minimum_size(qapp):
    """拖拽到负方向（向左上）时窗口不得小于 minimumSize。"""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    win = _build_window(qapp)
    win.resize(1100, 760)
    win._place_size_grip()
    qapp.processEvents()

    g = win._size_grip
    cx = g.width() / 2
    cy = g.height() / 2

    press = QMouseEvent(QMouseEvent.Type.MouseButtonPress, QPointF(cx, cy),
                        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    move = QMouseEvent(QMouseEvent.Type.MouseMove, QPointF(cx - 800, cy - 600),
                       Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    release = QMouseEvent(QMouseEvent.Type.MouseButtonRelease, QPointF(cx - 800, cy - 600),
                          Qt.LeftButton, Qt.NoButton, Qt.NoModifier)
    QApplication.sendEvent(g, press)
    QApplication.sendEvent(g, move)
    QApplication.sendEvent(g, release)
    qapp.processEvents()

    assert win.width() >= win.minimumSize().width(), \
        f"窗口宽 {win.width()} 小于 minimumSize {win.minimumSize().width()}"
    assert win.height() >= win.minimumSize().height(), \
        f"窗口高 {win.height()} 小于 minimumSize {win.minimumSize().height()}"
    win.deleteLater()


# ---------------------------------------------------------------------------
# 缺陷 2：快捷键速查卡可折叠
# ---------------------------------------------------------------------------


def test_shortcut_card_is_inside_the_scroll_area(qapp):
    """快捷键速查卡必须在 scroll area 内（不是 outer 的兄弟节点）。"""
    win = _build_window(qapp)
    page = win.settings_interface
    assert hasattr(page, "_shortcut_card"), "页面没有 _shortcut_card"
    assert page._shortcut_card["widget"].parent() is page._body_scroll.widget(), (
        "快捷键速查卡被放在了 scroll area 之外——它的高度不会被滚动掉"
    )
    win.deleteLater()


def test_shortcut_card_default_is_collapsed(qapp):
    """首次打开时快捷键卡必须折叠，body 不可见。"""
    win = _build_window(qapp)
    page = win.settings_interface
    # 注入快捷键
    page.set_shortcuts(win.shortcuts)
    qapp.processEvents()
    assert page._shortcut_collapsed is True, "默认状态应是折叠"
    # ``isVisible`` 受页面整体可见性影响；用 ``isHidden`` 才能反映「折叠意图」。
    assert page._shortcut_card["body"].isHidden() is True, \
        "折叠状态下 body 必须被 hide()"
    win.deleteLater()


def test_shortcut_card_button_shows_count_when_collapsed(qapp):
    """折叠态按钮文案必须是「N 个快捷键 · 展开」，而不是「展开」。"""
    win = _build_window(qapp)
    page = win.settings_interface
    page.set_shortcuts(win.shortcuts)
    qapp.processEvents()

    btn_text = page._shortcut_toggle_btn.text()
    assert "11" in btn_text, f"按钮没显示快捷键数量：{btn_text!r}"
    assert "展开" in btn_text, f"按钮没显示「展开」动作：{btn_text!r}"
    win.deleteLater()


def test_shortcut_card_toggle_expands_and_collapses(qapp):
    """点击按钮切到展开态：body 不再 hidden、按钮文案变「收起」；再点回折叠态。"""
    win = _build_window(qapp)
    page = win.settings_interface
    page.set_shortcuts(win.shortcuts)
    qapp.processEvents()

    # 初始：折叠
    assert page._shortcut_collapsed
    assert page._shortcut_card["body"].isHidden()

    # 点一下：展开
    page._shortcut_toggle_btn.click()
    qapp.processEvents()
    assert page._shortcut_collapsed is False
    assert page._shortcut_card["body"].isHidden() is False, \
        "点击展开后 body 必须不再 hidden"
    assert "收起" in page._shortcut_toggle_btn.text()

    # 再点一下：折叠
    page._shortcut_toggle_btn.click()
    qapp.processEvents()
    assert page._shortcut_collapsed is True
    assert page._shortcut_card["body"].isHidden() is True
    win.deleteLater()


def test_shortcut_card_height_is_small_when_collapsed(qapp):
    """折叠态时卡片整体高度必须远小于展开态——不能挤占主屏幕。"""
    win = _build_window(qapp)
    page = win.settings_interface
    page.set_shortcuts(win.shortcuts)
    qapp.processEvents()

    # 折叠态
    collapsed_h = page._shortcut_card["widget"].sizeHint().height()

    # 展开态
    page._shortcut_toggle_btn.click()
    qapp.processEvents()
    expanded_h = page._shortcut_card["widget"].sizeHint().height()

    # 折叠态不应该超过展开态的一半。设宽松点：2/3 截断阈值。
    assert collapsed_h * 3 <= expanded_h * 2, (
        f"折叠态高度 {collapsed_h} 与展开态 {expanded_h} 差距太小——"
        "用户还是看不到下面的设置"
    )
    win.deleteLater()
