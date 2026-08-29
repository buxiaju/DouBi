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
        # M6.16：标题修改默认是「不勾选 + 输入框禁用」，避免「我以为我
        # 用默认」的事故——强制用户先勾再编辑。
        assert dlg.modify_title_check.isChecked() is False
        assert dlg.title_input.isEnabled() is False
        # 输入框预填 "{title}" 是个让用户立刻看见「模板可写」的占位提示。
        assert dlg.title_input.text() == "{title}"
    finally:
        dlg.deleteLater()


def test_dialog_modify_title_check_toggles_input_enabled(host):
    """勾上复选框后输入框必须可用——这是「先勾再编辑」契约。"""
    from doubi.ui.pages.parse import PromptOptionsDialog
    from doubi.core.models import DownloadOptions

    dlg = PromptOptionsDialog(host, DownloadOptions())
    try:
        assert dlg.title_input.isEnabled() is False
        dlg.modify_title_check.setChecked(True)
        assert dlg.title_input.isEnabled() is True
        dlg.modify_title_check.setChecked(False)
        assert dlg.title_input.isEnabled() is False
    finally:
        dlg.deleteLater()


def test_dialog_summary_label_reflects_item_count(host):
    """摘要行的措辞随 item_count 切换——单条/多条要明确。"""
    from doubi.ui.pages.parse import PromptOptionsDialog
    from doubi.core.models import DownloadOptions

    single = PromptOptionsDialog(host, DownloadOptions(), item_count=1)
    try:
        assert "1 个视频" in single.summary.text()
    finally:
        single.deleteLater()

    batch = PromptOptionsDialog(host, DownloadOptions(), item_count=5)
    try:
        text = batch.summary.text()
        assert "5 个视频" in text
        # 批量时必须把「模板逐个应用」这层语义写进摘要——否则用户会
        # 误以为「5 个文件都改成同一个标题」。
        assert "模板" in text or "逐个" in text
    finally:
        batch.deleteLater()


def test_collect_prompt_overrides_returns_exactly_five_fields(host):
    from doubi.ui.pages.parse import PromptOptionsDialog, collect_prompt_overrides
    from doubi.core.models import DownloadOptions

    seed = DownloadOptions()
    dlg = PromptOptionsDialog(host, seed)
    try:
        out = collect_prompt_overrides(dlg)
        # M6.16：多了一个 title_template（默认 None = 不改）。
        assert set(out) == {
            "max_quality", "container", "write_thumbnail", "write_metadata_json",
            "title_template",
        }, f"overrides 只能暴露 5 个字段，实际 {set(out)}"
        # 默认未勾选 → title_template 必须是 None（区别于空字符串 ""）。
        assert out["title_template"] is None
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
        dlg.modify_title_check.setChecked(True)
        dlg.title_input.setText("番外-{title}")
        out = collect_prompt_overrides(dlg)
        assert out == {
            "max_quality": "4k",
            "container": "mkv",
            "write_thumbnail": True,
            "write_metadata_json": True,
            "title_template": "番外-{title}",
        }
    finally:
        dlg.deleteLater()


def test_collect_prompt_overrides_title_unchecked_strips_template(host):
    """复选框未勾选时即使输入框里有文字，也必须返回 None——"勾选才生效"。

    这是弹窗的「显式 opt-in」契约：残留文字不能自动生效。回归到这条
    任何一处都会让「我以为我没改标题」的事故重新出现。
    """
    from doubi.ui.pages.parse import PromptOptionsDialog, collect_prompt_overrides
    from doubi.core.models import DownloadOptions

    dlg = PromptOptionsDialog(host, DownloadOptions())
    try:
        # 模拟用户曾在输入框里打过字、但最后没勾复选框就关了弹窗。
        dlg.title_input.setText("番外-{title}")
        out = collect_prompt_overrides(dlg)
        assert out["title_template"] is None
    finally:
        dlg.deleteLater()


def test_collect_prompt_overrides_empty_input_falls_back_to_token(host):
    """勾了但输入框留空 → 模板用 {title}（不修改），不是空串。"""
    from doubi.ui.pages.parse import PromptOptionsDialog, collect_prompt_overrides
    from doubi.core.models import DownloadOptions

    dlg = PromptOptionsDialog(host, DownloadOptions())
    try:
        dlg.modify_title_check.setChecked(True)
        dlg.title_input.setText("")
        out = collect_prompt_overrides(dlg)
        assert out["title_template"] == "{title}"
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


# ---- 1b. apply_title_template 纯函数（不依赖 PySide6）---------------------
#
# 这组用例不依赖 Qt——只验证「标题模板」这个 per-item 操作的渲染逻辑。
# 模板可能在弹窗外被复用（比如未来从 REST 入口接收 rename_rule），所以
# 把核心规则锁在纯函数上、不与 QLineEdit 强耦合。


def _make_item(title: str, item_id: str = "x1"):
    """构造一个最小可用的 MediaItem 供纯函数测试用。"""
    from doubi.core.models import MediaItem, Platform
    return MediaItem(platform=Platform.BILIBILI, item_id=item_id, title=title)


def test_apply_title_template_none_is_noop():
    """None / 空串 → 一律不动 — 这是「未勾选复选框」对应的语义。"""
    from doubi.ui.pages.parse import apply_title_template

    items = [_make_item("原标题 A"), _make_item("原标题 B")]
    apply_title_template(items, None)
    apply_title_template(items, "")
    assert [i.title for i in items] == ["原标题 A", "原标题 B"]


def test_apply_title_template_token_passthrough():
    """{title} 单独作为模板 → 等价于不改。"""
    from doubi.ui.pages.parse import apply_title_template

    items = [_make_item("原标题 A"), _make_item("原标题 B")]
    apply_title_template(items, "{title}")
    assert [i.title for i in items] == ["原标题 A", "原标题 B"]


def test_apply_title_template_prefix_per_item():
    """「番外-{title}」→ 每个 item 各自加前缀，互不影响。"""
    from doubi.ui.pages.parse import apply_title_template

    items = [_make_item("第一集"), _make_item("第二集"), _make_item("第三集")]
    apply_title_template(items, "番外-{title}")
    assert [i.title for i in items] == [
        "番外-第一集", "番外-第二集", "番外-第三集",
    ]


def test_apply_title_template_suffix_per_item():
    """「{title}_4K」→ 追加后缀。"""
    from doubi.ui.pages.parse import apply_title_template

    items = [_make_item("高清测试")]
    apply_title_template(items, "{title}_4K")
    assert items[0].title == "高清测试_4K"


def test_apply_title_template_literal_string_renames_all():
    """模板里没有 {title} → 全部用同一字符串（用户明确选择）。"""
    from doubi.ui.pages.parse import apply_title_template

    items = [_make_item("A"), _make_item("B"), _make_item("C")]
    apply_title_template(items, "我的合集")
    assert [i.title for i in items] == ["我的合集", "我的合集", "我的合集"]


def test_apply_title_template_sanitizes_illegal_chars():
    """注入文件系统非法字符必须被净化——这是「不污染文件系统」承诺。

    复用 naming._sanitize 的规则，把 Windows 保留字（<>:"/\\|?*）替换
    成下划线。任何「我注入特殊字符想覆盖其他文件」的攻击在这里都会
    变成「和正常文件路径一样」的下划线，没机会逃逸。
    """
    from doubi.ui.pages.parse import apply_title_template

    items = [_make_item("原始")]
    apply_title_template(items, '邪恶<:"|?*>{title}')
    # 注意：原始的「原始」仍然出现在结果里（template 末尾是 {title}），
    # 非法字符全部变下划线。
    assert "<" not in items[0].title
    assert ">" not in items[0].title
    assert '"' not in items[0].title
    assert ":" not in items[0].title
    assert "|" not in items[0].title
    assert "?" not in items[0].title
    assert "*" not in items[0].title
    assert "原始" in items[0].title


def test_apply_title_template_multiple_tokens_replaced():
    """模板里出现多次 {title} 也只取当前 item 的 title——不会出现串号。"""
    from doubi.ui.pages.parse import apply_title_template

    items = [_make_item("苹果"), _make_item("香蕉")]
    apply_title_template(items, "{title}的{title}相册")
    assert items[0].title == "苹果的苹果相册"
    assert items[1].title == "香蕉的香蕉相册"


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
            # M6.16：title_template 不在 DownloadOptions 里，必须被
            # _options_for_overrides 的白名单过滤掉——否则 dataclasses.replace
            # 会因为 unknown kwarg 抛 TypeError，弹窗 5 字段契约被破坏。
            "title_template": "番外-{title}",
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