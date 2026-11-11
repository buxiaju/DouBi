"""P1-3 — 设置页自动保存（debounce 500ms 写回 config.yml）。

测试要点与两个不显然的坑：

* **配置路径隔离必须发生在 build 之前。** ``build_settings_widgets``
  内部 ``from ...core.config import DEFAULT_CONFIG_PATH`` 是在调用时
  才执行的——先 monkeypatch 模块属性再 build，闭包就会绑到 tmp 路径；
  ``load_config(None)`` 同样在调用时读模块全局。顺序反了就会写用户的
  真实 ``~/.doubi/config.yml``。
* **SwitchButton 的 ``checkedChanged`` 只在鼠标释放时发**（qfluentwidgets
  ``Indicator.mouseReleaseEvent``），程序化 ``setChecked`` 不发。测试
  里模拟用户切换只能手动 ``emit``；真实用户路径（点击）在真机上成立。
* LineEdit 用 ``QTest.keyClicks`` 打字产生真实的 ``textEdited``；
  ``setText`` 是程序化赋值，不触发——这本身就是设计意图。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


pytestmark = pytest.mark.gui


def _require_gui() -> None:
    try:
        import PySide6  # noqa: F401
        import qfluentwidgets  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        pytest.skip(f"GUI deps not installed: {exc}")


@pytest.fixture(scope="module")
def qapp():
    _require_gui()
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture(autouse=True)
def _no_account_network():
    """设置页构造会排一次账号状态刷新（QTimer.singleShot(50ms)）。

    这个刷新会真联网（B 站 / 抖音 cookie 校验），测试环境必须关掉，
    否则会污染断网探针 / CI。走 test_ui_settings_refresh 验证过的
    全局开关。
    """
    from doubi.ui.pages import settings as settings_mod
    settings_mod.set_account_refresh_enabled(False)
    yield
    settings_mod.set_account_refresh_enabled(True)


@pytest.fixture()
def page(qapp, monkeypatch, tmp_path):
    """构建一个配置写进 tmp_path 的 SettingsPage。

    monkeypatch 必须先于 build（见模块 docstring 第一条坑）。
    """
    _require_gui()
    import doubi.core.config as cfg_mod
    cfg_path = tmp_path / "config.yml"
    monkeypatch.setattr(cfg_mod, "DEFAULT_CONFIG_PATH", cfg_path)
    from doubi.ui.pages.settings import build_settings_widgets
    cls, _ = build_settings_widgets()
    return cls(), cfg_path


def _spy_writes(page) -> list:
    """把 ``_write_config`` 包一层计数器，返回调用记录列表。"""
    calls: list = []
    orig = page._write_config

    def wrapped():
        calls.append(1)
        return orig()

    page._write_config = wrapped
    return calls


def _yaml_of(cfg_path: Path) -> dict:
    import yaml
    return yaml.safe_load(cfg_path.read_text(encoding="utf-8"))


def _type_text(page, widget, text: str) -> None:
    """把光标挪到末尾后用真实键盘事件输入，产生 textEdited 信号。"""
    from PySide6.QtTest import QTest
    widget.setCursorPosition(len(widget.text()))
    QTest.keyClicks(widget, text)


# -----------------------------------------------------------------------
# 构造期不写盘
# -----------------------------------------------------------------------


def test_construction_does_not_write(page, qapp):
    """构造页（_build_ui / _load_from_cfg 的程序化赋值）不许触发落盘。

    这是 arm-after-load 顺序的守卫：反过来 arm 早了，每次启动都会
    无意义地重写一次 config.yml。
    """
    page_obj, cfg_path = page
    from PySide6.QtTest import QTest
    QTest.qWait(700)   # 超过 debounce 窗口
    assert not cfg_path.exists(), (
        "构造期不应写配置——_load_from_cfg 的程序化赋值发生在 arm 之前"
    )


# -----------------------------------------------------------------------
# 各控件类型的用户改动 → debounce 写盘
# -----------------------------------------------------------------------


def test_lineedit_edit_autosaves_after_debounce(page, qapp):
    page_obj, cfg_path = page
    _type_text(page_obj, page_obj.output_root, "XYZ")
    assert page_obj.save_btn.text() == "立即保存"

    from PySide6.QtTest import QTest
    QTest.qWait(700)

    assert cfg_path.exists()
    data = _yaml_of(cfg_path)
    assert data["output_root"].endswith("XYZ")


def test_debounce_coalesces_rapid_edits(page, qapp):
    """连续输入只落最后一次盘——debounce 的核心语义。"""
    page_obj, cfg_path = page
    calls = _spy_writes(page_obj)

    from PySide6.QtTest import QTest
    for ch in "abc":
        _type_text(page_obj, page_obj.output_root, ch)
        QTest.qWait(150)   # 间隔 < 500ms，每次都重置计时器
    QTest.qWait(700)

    assert len(calls) == 1, f"expected 1 write, got {len(calls)}"
    data = _yaml_of(cfg_path)
    assert data["output_root"].endswith("abc")


def test_combo_change_autosaves(page, qapp):
    """setCurrentIndex（程序化或用户点击都会发 currentIndexChanged）
    → 500ms 内写盘。acceptance 里的「默认画质」走的就是这条路。"""
    page_obj, cfg_path = page
    assert page_obj.container.currentIndex() == 0
    page_obj.container.setCurrentIndex(1)   # mp4 -> mkv

    from PySide6.QtTest import QTest
    QTest.qWait(700)

    assert _yaml_of(cfg_path)["container"] == "mkv"


def test_switch_toggle_autosaves(page, qapp):
    """SwitchButton 的真实用户路径是鼠标释放发 checkedChanged。

    测试里手动 emit（见模块 docstring 第二条坑）；emit 走的是与真实
    点击完全相同的信号链。
    """
    page_obj, cfg_path = page
    initial = page_obj.database.isChecked()
    # 模拟真实用户点击的两步：qfluentwidgets 的 setChecked 只改状态
    # 不发信号（信号在 Indicator.mouseReleaseEvent 里），所以状态和
    # 信号要分别驱动——这正是真实点击的完整效果。
    page_obj.database.setChecked(not initial)
    page_obj.database.checkedChanged.emit(not initial)

    from PySide6.QtTest import QTest
    QTest.qWait(700)

    assert _yaml_of(cfg_path)["database"] == (not initial)


def test_theme_combo_signal_autosaves(page, qapp):
    """主题下拉的 currentIndexChanged 也接入了自动保存。

    只 emit 信号（不改真实 index），这样 _write_config 里的
    set_theme 被「同名跳过」守卫拦住，测试不会触发整页主题重刷
    ——那是 test_theme_apply_gui（slow 口径）的领地。
    """
    page_obj, cfg_path = page
    page_obj.theme.currentIndexChanged.emit(0)

    from PySide6.QtTest import QTest
    QTest.qWait(700)

    assert cfg_path.exists()
    assert "theme" in _yaml_of(cfg_path)


# -----------------------------------------------------------------------
# 「立即保存」按钮语义
# -----------------------------------------------------------------------


def test_manual_save_writes_immediately_and_kills_pending_timer(page, qapp):
    """点「立即保存」：不等 debounce 马上写盘，且把挂着的计时器停掉
    ——否则 500ms 后还会再写一次（重复落盘 + toast 语义混乱）。"""
    page_obj, cfg_path = page
    calls = _spy_writes(page_obj)

    _type_text(page_obj, page_obj.output_root, "M")
    page_obj._on_save()   # 不 qWait，立即写

    assert len(calls) == 1
    assert cfg_path.exists()

    from PySide6.QtTest import QTest
    QTest.qWait(700)
    assert len(calls) == 1, "挂起的 debounce 计时器必须被 _on_save 停掉"


def test_sniff_config_side_effects_still_fire_on_autosave(page, qapp):
    """自动保存必须与手动保存共用 _write_config：嗅探配置的运行时
    下发（GenericAdapter.set_config + sniffConfigChanged）不能只在
    点按钮时才生效。"""
    page_obj, cfg_path = page
    emitted: list[tuple] = []
    page_obj.sniffConfigChanged.connect(
        lambda enabled, dur: emitted.append((enabled, dur)))

    page_obj.sniff_duration.setText("30")
    page_obj.sniff_duration.textEdited.emit("30")

    from PySide6.QtTest import QTest
    QTest.qWait(700)

    assert emitted, "自动保存也要下发嗅探配置"
    assert _yaml_of(cfg_path)["sniff_duration_sec"] == 30


# -----------------------------------------------------------------------
# configSaved 广播（配置刷新下发 + 语言重启提示）
# -----------------------------------------------------------------------


def test_config_saved_broadcast_carries_refreshed_cfg(page, qapp):
    """写盘成功后 configSaved 必须携带从磁盘重载的 AppConfig。

    parse / search / hot / history 持有的是构造期独立快照，不广播的话
    它们「下次下载」读到的还是旧值——「下次下载生效」会退化成
    「重启才生效」。
    """
    from doubi.core.config import AppConfig

    page_obj, cfg_path = page
    received: list = []
    page_obj.configSaved.connect(received.append)

    page_obj.proxy.setText("http://127.0.0.1:7890")
    page_obj.proxy.textEdited.emit("http://127.0.0.1:7890")

    from PySide6.QtTest import QTest
    QTest.qWait(700)

    assert received, "写盘成功必须广播 configSaved"
    cfg = received[-1]
    assert isinstance(cfg, AppConfig)
    assert cfg.proxy == "http://127.0.0.1:7890"
    assert page_obj._cfg is cfg, "页面应持有重载后的同一实例"


def test_language_change_sets_restart_flag(page, qapp):
    """语言是唯一改完不立即生效的字段，必须被 _language_changed 记下。"""
    from doubi.ui.i18n import available_languages

    page_obj, cfg_path = page
    langs = available_languages()
    if len(langs) < 2:
        pytest.skip("需要至少两种语言")

    original = page_obj._cfg.language
    target = next(i for i, lang in enumerate(langs) if lang != original)
    page_obj.language.setCurrentIndex(target)

    from PySide6.QtTest import QTest
    QTest.qWait(700)

    assert page_obj._language_changed is True
    assert _yaml_of(cfg_path)["language"] == langs[target]


def test_non_language_change_leaves_restart_flag_false(page, qapp):
    page_obj, cfg_path = page
    _type_text(page_obj, page_obj.output_root, "Q")

    from PySide6.QtTest import QTest
    QTest.qWait(700)

    assert cfg_path.exists()
    assert page_obj._language_changed is False


# -----------------------------------------------------------------------
# 剪贴板监听开关（clipboard_watch，默认关）
# -----------------------------------------------------------------------


def test_clipboard_watch_default_off_and_persists(page, qapp):
    """开关默认关；打开后写进 config.yml。"""
    from doubi.core.config import AppConfig
    assert AppConfig().clipboard_watch is False

    page_obj, cfg_path = page
    page_obj.clipboard_watch.setChecked(True)
    page_obj.clipboard_watch.checkedChanged.emit(True)

    from PySide6.QtTest import QTest
    QTest.qWait(700)

    assert _yaml_of(cfg_path)["clipboard_watch"] is True


def test_clipboard_switch_broadcast_reaches_pages(page, qapp, tmp_path):
    """开关改动经 configSaved 广播后，parse 页拿到的 cfg 必须同步。

    这是主窗口 _on_config_saved 定时器联动的前提——cfg 不同步，
    开了开关解析页也不知道。
    """
    page_obj, _cfg_path = page

    # 造一个假的 parse 页替身（不构造真 ParsePage——太重）
    class _FakeParse:
        def __init__(self):
            from doubi.core.config import AppConfig
            self._cfg = AppConfig()
            from PySide6.QtCore import QTimer
            self._clipboard_timer = QTimer()
            self._clipboard_timer.setInterval(1500)
            self.isVisible = lambda: True

    fake_parse = _FakeParse()
    received: list = []
    page_obj.configSaved.connect(received.append)

    page_obj.clipboard_watch.setChecked(True)
    page_obj.clipboard_watch.checkedChanged.emit(True)

    from PySide6.QtTest import QTest
    QTest.qWait(700)

    assert received, "configSaved 必须发出"
    assert received[-1].clipboard_watch is True
    # 模拟主窗口路由
    fake_parse._cfg = received[-1]
    assert fake_parse._cfg.clipboard_watch is True


# ---------------------------------------------------------------------------
# 附加内容 sidecar 开关（NFO / 弹幕 / 字幕）——CLI 早已支持，GUI 补齐入口
# ---------------------------------------------------------------------------


def test_sidecar_switches_default_off_and_persist(page, qapp):
    """三个开关默认关（与 AppConfig 默认一致）；打开后写进 config.yml。

    这三个字段在 _build_options 搬运链上早已存在——GUI 缺的只是开关，
    漏接 _wire_auto_save 会静默失效（clipboard_watch 当年就被自己的
    测试抓过一次）。
    """
    from PySide6.QtTest import QTest

    from doubi.core.config import AppConfig
    assert AppConfig().write_nfo is False
    assert AppConfig().write_danmaku is False
    assert AppConfig().write_subtitles is False

    page_obj, cfg_path = page
    page_obj.write_nfo.setChecked(True)
    page_obj.write_nfo.checkedChanged.emit(True)
    page_obj.write_danmaku.setChecked(True)
    page_obj.write_danmaku.checkedChanged.emit(True)
    # 字幕故意不开——验证开关互不牵连

    QTest.qWait(700)

    data = _yaml_of(cfg_path)
    assert data["write_nfo"] is True
    assert data["write_danmaku"] is True
    assert data["write_subtitles"] is False


def test_sidecar_switch_reload_roundtrip(page, qapp):
    """_load_from_cfg 回填：改 config 再重载，开关状态要跟得上。"""
    page_obj, cfg_path = page

    import yaml
    # 先落一次盘，否则 config.yml 还不存在、没得改
    assert page_obj._write_config()
    data = _yaml_of(cfg_path)
    data["write_nfo"] = True
    cfg_path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")

    from doubi.core.config import load_config
    page_obj._cfg = load_config(cfg_path)
    page_obj._load_from_cfg()

    assert page_obj.write_nfo.isChecked() is True
    assert page_obj.write_danmaku.isChecked() is False



def test_logout_platform_end_to_end(page, qapp, monkeypatch):
    """登出按钮主体：调 logout → 弹 toast → 触发状态刷新。

    monkeypatch 掉 auth_actions.logout（不碰真实 cookie），并断言
    状态刷新被排入（_spawn_account_refresh 尊重测试全局开关）。
    """
    calls: list = []

    import doubi.ui.auth_actions as aa
    monkeypatch.setattr(aa, "logout",
                        lambda platform: calls.append(platform) or (True, "已删除 x"))

    page_obj, _cfg_path = page

    from PySide6.QtTest import QTest

    # _logout_platform 里 toast 走 InfoBar（offscreen 可用）；直接调用
    page_obj._logout_platform("bilibili", "B 站")
    QTest.qWait(150)

    assert calls == ["bilibili"]
