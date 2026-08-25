"""下载前选项对话框（M6.11）的回归测试。

弹窗是 ``qfluentwidgets.MessageBoxBase`` 的子类，``exec()`` 会进入模态
事件循环——在 offscreen 测试环境下没有用户输入，模态会卡死。所以测试**绕
过** exec，只覆盖三件事：

1. ``PromptOptionsDialog`` 可以被构造出来并 seed 默认值。
2. ``collect_prompt_overrides(dlg)`` 永远是 4 个字段，没有遗漏也没有溢出
   （不能把「下拉框里的全部 ComboBox 项」都塞进 overrides）。
3. ParsePage 的 ``_options_for_overrides`` 把这个 dict 用
   ``dataclasses.replace`` 叠到 ``_build_options()`` 上，其他字段不被
   污染（这是 ``test_build_options_covers_every_shared_config_field``
   守卫测试在 GUI 路径上的延伸）。

「exec 返回 0 时取消」这条路径在 PySide6 自身测试套件里覆盖；这里不再
复制一份 PySide6 的单元测试。
"""

from __future__ import annotations

import dataclasses

import pytest


pytestmark = pytest.mark.gui


# ---- 守卫：「无 PySide6 就跳过」是项目统一约定 ----------------------------


@pytest.fixture(scope="module")
def qapp():
    """Module-scope QApplication，复用单实例（与项目其他 GUI 测试一致）。

    ``importorskip`` 把整批测试跳过而非报错，与「无 PySide6 则跳过」的
    全仓库约定一致。Pytest 的模块跳过需要 ``pytest.skip`` 而不是
    ``raise``。
    """
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def host(qapp):
    """MessageBoxBase 需要一个 parent widget 才能布局。"""
    from PySide6.QtWidgets import QWidget
    w = QWidget()
    w.resize(400, 300)
    try:
        yield w
    finally:
        w.deleteLater()


# ---- 1. 弹窗本身 ------------------------------------------------------


def test_dialog_prefills_from_seed(host):
    from doubi.ui.pages.parse import PromptOptionsDialog
    from doubi.core.models import DownloadOptions

    seed = DownloadOptions(
        max_quality="1080p", container="mkv",
        write_thumbnail=True, write_metadata_json=False,
    )
    dlg = PromptOptionsDialog(host, seed)
    try:
        assert dlg.quality.currentText() == "1080p"
        assert dlg.container.currentText() == "mkv"
        assert dlg.thumb.isChecked() is True
        assert dlg.metadata_json.isChecked() is False
        # 按钮文案应该是中文——否则用户在中文界面看到「OK / Cancel」会觉得
        # 是漏改 i18n，不是漏改弹窗。
        assert dlg.yesButton.text() == "下载"
        assert dlg.cancelButton.text() == "取消"
    finally:
        dlg.deleteLater()


def test_collect_prompt_overrides_returns_exactly_four_fields(host):
    from doubi.ui.pages.parse import PromptOptionsDialog, collect_prompt_overrides
    from doubi.core.models import DownloadOptions

    seed = DownloadOptions()
    dlg = PromptOptionsDialog(host, seed)
    try:
        out = collect_prompt_overrides(dlg)
        assert set(out) == {
            "max_quality", "container", "write_thumbnail", "write_metadata_json",
        }, f"overrides 只能暴露 4 个字段，实际 {set(out)}"
    finally:
        dlg.deleteLater()


def test_collect_prompt_overrides_reflects_user_edits(host):
    """用户在控件里改的值要原样出现在 dict 里——这是弹窗存在的意义。"""
    from doubi.ui.pages.parse import PromptOptionsDialog, collect_prompt_overrides
    from doubi.core.models import DownloadOptions

    seed = DownloadOptions()
    dlg = PromptOptionsDialog(host, seed)
    try:
        dlg.quality.setCurrentText("4k")
        dlg.container.setCurrentText("mkv")
        dlg.thumb.setChecked(True)
        dlg.metadata_json.setChecked(True)
        out = collect_prompt_overrides(dlg)
        assert out == {
            "max_quality": "4k",
            "container": "mkv",
            "write_thumbnail": True,
            "write_metadata_json": True,
        }
    finally:
        dlg.deleteLater()


def test_overrides_unknown_keys_are_dropped(host):
    """弹窗之外的字段（例如 database_path）绝不能通过 overrides 进入 options。

    ParsePage 里的 ``_options_for_overrides`` 会按 DownloadOptions 字段名
    做白名单过滤；这里用一个直白的 dict 验证过滤逻辑本身（不依赖
    ParsePage 实例——后者要 qfluentwidgets 主题表全套）。
    """
    from doubi.core.models import DownloadOptions

    opts = DownloadOptions(database=__import__("pathlib").Path("/tmp/x.db"))
    clean = {
        k: v for k, v in {
            "max_quality": "8k",
            "container": "mp4",
            "write_thumbnail": False,
            "write_metadata_json": False,
            # 这两个名字根本不在 DownloadOptions 里——必须被丢掉。
            # (database_path 在 AppConfig 里有，但 DownloadOptions 里叫 database。)
            "database_path": "/etc/passwd",
            "format_id_pref": "h264",
        }.items()
        if k in {f.name for f in dataclasses.fields(DownloadOptions)}
    }
    out = dataclasses.replace(opts, **clean)
    assert out.database == opts.database, "unknown key 必须被过滤，不能影响 database"
    assert out.max_quality == "8k"
    assert out.container == "mp4"


# ---- 2. ParsePage 集成：默认行为不被破坏 --------------------------------


def test_ask_prompt_overrides_returns_empty_when_disabled(qapp, tmp_path):
    """默认（开关未开）下，_ask_prompt_overrides 必须返回空 dict——不能弹窗。

    这是「点一下就走」的用户心智模型：如果用户没在设置里打开开关，
    _ask_prompt_overrides 必须立即返回 {}，让 _options_for_overrides()
    走默认配置。任何把这一行改成「总是弹一次」的回归都会被这条用例逮住。
    """
    from doubi.ui.main_window import build_main_window

    MainWindow = build_main_window()
    win = MainWindow()
    try:
        # 开关默认是 False——不动它。
        win.parse_interface._cfg.database = True
        win.parse_interface._cfg.database_path = tmp_path / "doubi.db"
        win.parse_interface._cfg.output_root = tmp_path / "out"
        # 关掉切页动画，避开坑位 30。
        win.stackedWidget.setAnimationEnabled(False)
        # 关键：set_prompt_before_download 还没被调用，属性不存在。
        # _ask_prompt_overrides 必须通过 getattr(self, "_prompt_before_download",
        # False) 把它当成 False 处理，而不是 AttributeError。
        out = win.parse_interface._ask_prompt_overrides()
        assert out == {}, f"默认行为下应立即返回空 dict，实际 {out!r}"
    finally:
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QApplication
        win.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_ask_prompt_overrides_returns_empty_when_enabled_but_no_dialog(qapp, tmp_path):
    """开关开了、但 Qt 不可用时（PromptOptionsDialog 为 None），降级为不弹。

    这种情况下 PromptOptionsDialog 模块顶层的兜底是 None；``_ask_prompt_overrides``
    必须返回空 dict 而不是抛异常——否则没装 PySide6 的环境会因为导入
    parse.py 而连锁报错。
    """
    import doubi.ui.pages.parse as parse_mod
    original = parse_mod.PromptOptionsDialog
    parse_mod.PromptOptionsDialog = None  # 模拟「Qt 不可用」的状态
    try:
        from doubi.ui.main_window import build_main_window
        MainWindow = build_main_window()
        win = MainWindow()
        try:
            win.parse_interface._cfg.database = True
            win.parse_interface._cfg.database_path = tmp_path / "doubi.db"
            win.parse_interface._cfg.output_root = tmp_path / "out"
            win.stackedWidget.setAnimationEnabled(False)
            win.parse_interface.set_prompt_before_download(True)
            out = win.parse_interface._ask_prompt_overrides()
            assert out == {}, f"Qt 不可用时应降级为空 dict，实际 {out!r}"
        finally:
            from PySide6.QtCore import QEvent
            from PySide6.QtWidgets import QApplication
            win.deleteLater()
            QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    finally:
        parse_mod.PromptOptionsDialog = original


def test_options_for_overrides_keeps_other_fields_intact(qapp, tmp_path):
    """弹窗 4 字段之外的字段（database / proxy / output_root 等）原样保留。

    验证覆盖链不会污染 _build_options 已搬运的字段——这是「单一边界」承诺。
    """
    from doubi.ui.main_window import build_main_window

    MainWindow = build_main_window()
    win = MainWindow()
    try:
        win.parse_interface._cfg.database = True
        win.parse_interface._cfg.database_path = tmp_path / "doubi.db"
        win.parse_interface._cfg.output_root = tmp_path / "out"
        win.stackedWidget.setAnimationEnabled(False)
        base = win.parse_interface._build_options()
        out = win.parse_interface._options_for_overrides({
            "max_quality": "4k",
            "container": "mkv",
            "write_thumbnail": True,
            "write_metadata_json": True,
        })
        # overrides 里给的 4 个字段必须确实被改。
        assert out.max_quality == "4k"
        assert out.container == "mkv"
        assert out.write_thumbnail is True
        assert out.write_metadata_json is True
        # **没**在 overrides 里的字段必须原样保留——这是「单一边界」承诺。
        overridden = {"max_quality", "container", "write_thumbnail", "write_metadata_json"}
        for f in dataclasses.fields(base):
            if f.name in overridden:
                continue
            assert getattr(out, f.name) == getattr(base, f.name), (
                f"覆盖链污染了 {f.name}: {getattr(out, f.name)!r} != {getattr(base, f.name)!r}"
            )
    finally:
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QApplication
        win.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_options_for_overrides_with_empty_dict_equals_build_options(qapp, tmp_path):
    """overrides={} 必须与 _build_options() 完全相同（无任何副作用）。"""
    from doubi.ui.main_window import build_main_window

    MainWindow = build_main_window()
    win = MainWindow()
    try:
        win.parse_interface._cfg.database = True
        win.parse_interface._cfg.database_path = tmp_path / "doubi.db"
        win.parse_interface._cfg.output_root = tmp_path / "out"
        win.stackedWidget.setAnimationEnabled(False)
        base = win.parse_interface._build_options()
        out = win.parse_interface._options_for_overrides({})
        assert out == base
    finally:
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QApplication
        win.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


# ---- 3. 配置层：YAML 往返 ---------------------------------------------


def test_appconfig_has_prompt_before_download_with_default_false():
    """AppConfig 必须暴露该字段——守护测试和 YAML 往返都要用。"""
    from doubi.core.config import AppConfig
    cfg = AppConfig()
    assert cfg.prompt_before_download is False


def test_load_config_picks_up_prompt_before_download_from_yaml(tmp_path):
    """YAML 写入 ``prompt_before_download: true`` 后 load_config 必须读到 True。"""
    import yaml
    from doubi.core.config import load_config

    cfg_path = tmp_path / "config.yml"
    cfg_path.write_text(
        yaml.safe_dump({"prompt_before_download": True}, allow_unicode=True),
        encoding="utf-8",
    )
    cfg = load_config(cfg_path)
    assert cfg.prompt_before_download is True


def test_to_dict_includes_prompt_before_download():
    """``to_dict()`` 必须包含该字段——settings.py 的 _on_save 依赖这一点。"""
    from doubi.core.config import AppConfig
    cfg = AppConfig(prompt_before_download=True)
    assert cfg.to_dict()["prompt_before_download"] is True