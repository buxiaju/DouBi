"""主题是否真的落到每一个控件上。

单纯断言 ``THEMES`` 里的色值是没用的——之前六套主题的 token 表全是对的，
界面却依旧一片白。真正的失效点全在 qfluentwidgets 的私有实现里：

* ``FluentWindow`` 的 Mica 效果会让 ``setCustomBackgroundColor`` 完全不可见；
* 每个 fluent 控件都有自己的 QSS，优先级高于 ``QApplication`` 的全局样式表；
* ``CardWidget`` 的底色是 ``paintEvent`` 里画死的半透明白，QSS 管不着；
* 切主题之后才创建的控件（下拉、弹窗）会拿到库自带的亮色 QSS。

所以这里断言的是「控件实际生效的颜色」，并且刻意依赖
``_normalBackgroundColor`` / ``_isMicaEnabled`` / ``lightCustomQss``
这些私有接口——它们哪天被上游改名，测试必须当场红掉，而不是界面悄悄变回白色。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Force Qt to render off-screen so the test never needs a display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _require_gui() -> None:
    try:
        import PySide6  # noqa: F401
        import qfluentwidgets  # noqa: F401
    except ImportError as exc:   # pragma: no cover
        pytest.skip(f"GUI deps not installed: {exc}")


@pytest.fixture(scope="module")
def qapp():
    _require_gui()
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture(scope="module")
def window(qapp):
    from doubi.ui.main_window import build_main_window
    MainWindow = build_main_window()
    win = MainWindow()
    yield win


@pytest.fixture(autouse=True)
def restore_theme(qapp):
    """测试会切主题，跑完恢复默认，避免污染同进程的其他 GUI 测试。"""
    yield
    from doubi.ui.theme import set_theme
    set_theme("default_light")


def _theme_names():
    try:
        from doubi.ui.theme import theme_names
    except ImportError:  # pragma: no cover - 无 GUI 依赖时由 _require_gui 跳过
        return []
    return theme_names()


def _custom_qss(widget) -> str:
    return widget.property("lightCustomQss") or ""


@pytest.mark.parametrize("name", _theme_names())
def test_theme_paints_window_background(window, name):
    """主窗口底色必须是 bg_base，且 Mica 必须关掉。

    Mica 开着的时候 ``_normalBackgroundColor()`` 返回全透明，
    这正是「整体的背景没有变」的直接原因。
    """
    from doubi.ui.theme import set_theme

    pack = set_theme(name)
    assert window._normalBackgroundColor().name().lower() == pack.tokens["bg_base"].lower()
    assert not getattr(window, "_isMicaEnabled", False)


@pytest.mark.parametrize("name", _theme_names())
def test_theme_overrides_existing_fluent_widgets(qapp, window, name):
    """已经存在的输入框/按钮/下拉必须被写入自定义 QSS。

    ``line_edit.qss`` 的 ``:focus`` 是写死的纯 ``white``，
    不覆盖的话解析框永远是白的。
    """
    from qfluentwidgets import ComboBox, LineEdit, PushButton

    from doubi.ui.theme import set_theme

    pack = set_theme(name)
    layer = pack.tokens["bg_layer"]

    checked = 0
    for cls in (PushButton, ComboBox, LineEdit):
        for widget in qapp.allWidgets():
            if type(widget) is cls:
                assert layer in _custom_qss(widget), f"{cls.__name__} 未拿到 {layer}"
                checked += 1
                break
    assert checked, "主窗口里一个 fluent 控件都没找到，测试失去意义"


@pytest.mark.parametrize("name", _theme_names())
def test_theme_repaints_cards(qapp, window, name):
    """卡片底色是 paintEvent 里画死的，只能靠猴补丁改。"""
    from qfluentwidgets import CardWidget

    from doubi.ui.theme import set_theme

    pack = set_theme(name)
    layer = pack.tokens["bg_layer"]

    cards = [w for w in qapp.allWidgets() if isinstance(w, CardWidget)]
    assert cards, "找不到任何 CardWidget"
    assert cards[0]._normalBackgroundColor().name().lower() == layer.lower()


@pytest.mark.parametrize("name", _theme_names())
def test_theme_applies_to_widgets_created_after_switch(window, name):
    """切主题之后新建的控件也得跟着变。

    下拉菜单、对话框都是懒创建的，赶不上刷新那一轮，
    只有钩住 ``styleSheetManager.register`` 才能覆盖到。
    """
    from qfluentwidgets import ComboBox

    from doubi.ui.theme import set_theme

    pack = set_theme(name)
    fresh = ComboBox(window)
    try:
        assert pack.tokens["bg_layer"] in _custom_qss(fresh)
    finally:
        fresh.deleteLater()

# 标题栏应用图标的尺寸/换色测试见 tests/test_ui_polish.py：
# 那些用「独立 MainWindow + 调完就 deleteLater」的模式，不在
# 本文件 module-scope 的 window fixture 上累计状态。
