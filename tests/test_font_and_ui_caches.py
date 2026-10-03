"""0.3.5 — 字体族真正落地 + 各处性能缓存的回归。

覆盖四类改动，每类都锚定一个**已实测过的失效模式**，而不是复述实现：

1. 字体族：0.3.4 之前 ``font-family`` 写在 QSS 里，Qt 不解析带引号的
   逗号分隔族列表，全应用静默落到 Segoe UI。这里断言「QSS 里不再出现
   font-family」+「app font / fluent qconfig 都指向 YaHei UI」。
2. TaskRow elide 缓存：宽度/文本没变时不重算，变了要重算。
3. ParsePage 搜索：小写化结果被缓存，重复过滤不重复算；命中语义不变。
4. HistoryPage 懒加载 + 脏标记：首刷推迟，下载落库后必须重查。
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
    except ImportError as exc:
        pytest.skip(f"GUI deps not installed: {exc}")


@pytest.fixture(scope="module")
def qapp():
    _require_gui()
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture(autouse=True)
def _ensure_event_loop():
    """给当前线程装一个 asyncio 事件循环。

    ``TaskManager.add()`` 内部要 ``asyncio.get_event_loop()`` 来起下载
    协程。任何先前跑过的用例只要用过 ``asyncio.run()``，退出时就会把
    线程的 current event loop 清成 None（CPython 的既定行为），于是
    单独跑本文件没事、放进全量套件里就报
    ``RuntimeError: There is no current event loop in thread 'MainThread'``。

    实测会踩到这个的邻居：``tests/test_pipeline_smoke.py``、
    ``tests/test_server.py``。这里显式补一个，不依赖执行顺序。
    """
    import asyncio

    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    yield


# ---------------------------------------------------------------------------
# 1. 字体族
# ---------------------------------------------------------------------------


def test_qss_never_emits_font_family():
    """全应用的 QSS 里不得再出现 ``font-family`` 声明。

    Qt 的样式表实现把 ``font-family: A, B, C`` 整串当一个字面族名查，
    查不到就静默回落。写了不但没用，还会盖掉 fluent 控件自己
    ``setFamilies()`` 的结果——这正是 0.3.4「字看着糊」的真根因。

    只查真正的声明（``font-family:`` 或 ``font-family :``），注释里
    提到这个词不算——代码里刻意留了说明，把注释也一并禁掉会逼着后来
    的人删掉解释。
    """
    import re

    from doubi.ui.theme import app_qss, heading_qss, body_qss, muted_qss

    decl = re.compile(r"font-family\s*:")
    for name, qss in (
        ("app_qss", app_qss()),
        ("heading_qss", heading_qss(1)),
        ("body_qss", body_qss()),
        ("muted_qss", muted_qss()),
    ):
        # 逐行看，跳过 /* */ 注释行。
        body = "\n".join(
            ln for ln in qss.splitlines()
            if not ln.strip().startswith(("/*", "*", "//"))
        )
        assert not decl.search(body), f"{name} 仍在输出 font-family 声明"


def test_source_tree_has_no_qss_font_family():
    """源码树里除了注释，不该再有 ``font-family:`` 的赋值。"""
    src = ROOT / "src" / "doubi"
    offenders = []
    for path in src.rglob("*.py"):
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1,
        ):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if "font-family" in line and "font-family:" in line:
                offenders.append(f"{path.relative_to(ROOT)}:{lineno}")
    assert not offenders, f"仍有 QSS font-family 输出点: {offenders}"


def test_apply_app_font_sets_yahei_ui_on_qapplication(qapp):
    """``apply_app_font()`` 必须把族名装到 QApplication 上。"""
    from PySide6.QtGui import QFont

    from doubi.ui.theme import FONT_FAMILY_PRIMARY, apply_app_font

    assert apply_app_font() is True
    assert qapp.font().family() == FONT_FAMILY_PRIMARY
    # 字重也要一起上，否则「字号对了但中文仍发灰」。
    assert qapp.font().weight() == QFont.Weight.Medium


def test_apply_app_font_overrides_fluent_qconfig(qapp):
    """fluent 控件的族名走 qconfig，不覆盖它就还是 Segoe UI。"""
    from qfluentwidgets.common.config import qconfig

    from doubi.ui.theme import FONT_FAMILIES, apply_app_font

    apply_app_font()
    families = qconfig.get(qconfig.fontFamilies)
    assert families[0] == "Microsoft YaHei UI"
    assert families == list(FONT_FAMILIES)


def test_fluent_labels_render_in_yahei_ui(qapp):
    """端到端：新建的 fluent Label 族名必须是 YaHei UI。"""
    from qfluentwidgets import BodyLabel, StrongBodyLabel, SubtitleLabel

    from doubi.ui.theme import FONT_FAMILY_PRIMARY, apply_app_font

    apply_app_font()
    for cls in (BodyLabel, StrongBodyLabel, SubtitleLabel):
        assert cls("中文样本").font().family() == FONT_FAMILY_PRIMARY, cls.__name__


def test_apply_app_font_is_idempotent(qapp):
    """重复调用不得让字号漂移（``set_theme`` 每次切主题都会调一遍）。"""
    from doubi.ui.theme import apply_app_font

    apply_app_font()
    before = (qapp.font().family(), qapp.font().pointSize(), qapp.font().weight())
    apply_app_font()
    after = (qapp.font().family(), qapp.font().pointSize(), qapp.font().weight())
    assert before == after


def test_apply_app_font_returns_false_without_qapplication(monkeypatch):
    """无 QApplication 时安静返回 False，不该抛异常拖垮无头调用。"""
    _require_gui()  # ci 口径会把 PySide6 整个屏蔽掉
    from PySide6.QtWidgets import QApplication

    from doubi.ui.theme import apply_app_font

    monkeypatch.setattr(
        QApplication, "instance", staticmethod(lambda: None),
    )
    assert apply_app_font() is False


# ---------------------------------------------------------------------------
# 2. TaskRow elide 缓存
# ---------------------------------------------------------------------------


class _IdlePipeline:
    """永不停笔的 pipeline，让行停在 running 态便于测试。"""

    async def download_item(self, item, options, *, on_progress=None):
        import asyncio

        await asyncio.sleep(30)


def _make_row(qapp, title: str):
    """走真实路径造一根 TaskRow：建页 → 建 manager → add → 取 ``_rows``。

    ``TaskRow`` 不是导出符号（``build_download_widgets()`` 返回的是
    ``(DownloadPage, DownloadPage)``），所以只能这样拿到实例——与
    ``tests/test_download_page.py`` 的既有做法一致。
    """
    from doubi.core.models import DownloadOptions, MediaItem
    from doubi.core.models import Platform as ModelPlatform
    from doubi.ui.pages.download import build_download_widgets
    from doubi.ui.task_manager import TaskManager

    cls, _ = build_download_widgets()
    page = cls()
    mgr = TaskManager(_IdlePipeline())
    page.set_task_manager(mgr)
    item = MediaItem(
        item_id="av-test", title=title, source_url="https://x/1",
        platform=ModelPlatform.BILIBILI,
    )
    task_id = mgr.add(item, DownloadOptions())
    qapp.processEvents()
    return page._rows[task_id]


def test_task_row_elide_skips_unchanged(qapp, monkeypatch):
    """文本与宽度都没变时，不得再调 ``elidedText``。"""
    from PySide6.QtGui import QFontMetrics

    row = _make_row(qapp, title="一个足够长的视频标题用来触发省略号")
    # 构造阶段已经算过一轮，先手工确认缓存已就位。
    row._refresh_texts()

    calls = {"n": 0}
    real = QFontMetrics.elidedText

    def _counting(self, *args, **kwargs):
        calls["n"] += 1
        return real(self, *args, **kwargs)

    monkeypatch.setattr(QFontMetrics, "elidedText", _counting)

    row._refresh_texts()
    row._refresh_texts()
    row._refresh_texts()
    assert calls["n"] == 0, "重复刷新不该重算 elide"


def test_task_row_elide_recomputes_on_text_change(qapp, monkeypatch):
    """文本变了必须重算，否则刷新后会显示上一条任务的标题。"""
    from PySide6.QtGui import QFontMetrics

    row = _make_row(qapp, title="短")
    row._refresh_texts()

    calls = {"n": 0}
    real = QFontMetrics.elidedText

    def _counting(self, *args, **kwargs):
        calls["n"] += 1
        return real(self, *args, **kwargs)

    monkeypatch.setattr(QFontMetrics, "elidedText", _counting)
    row._title_full = "换了一根非常长的标题以确保它一定会被截断出省略号"
    row._refresh_texts()
    assert calls["n"] > 0


def test_task_row_resize_event_does_not_thrash(qapp, monkeypatch):
    """尺寸抖动反复触发 resizeEvent 时不得每轮都重算。"""
    from PySide6.QtGui import QFontMetrics

    row = _make_row(qapp, title="一个足够长的视频标题用来触发省略号")
    row._refresh_texts()

    calls = {"n": 0}
    real = QFontMetrics.elidedText

    def _counting(self, *args, **kwargs):
        calls["n"] += 1
        return real(self, *args, **kwargs)

    monkeypatch.setattr(QFontMetrics, "elidedText", _counting)
    for _ in range(20):
        row.resizeEvent(None)
    assert calls["n"] == 0, "宽度未变时 resizeEvent 不该重算"


# ---------------------------------------------------------------------------
# 3. ParsePage 搜索缓存
# ---------------------------------------------------------------------------


def _make_parse_page(qapp):
    from doubi.ui.pages.parse import build_parse_widgets

    cls, _ = build_parse_widgets()
    page = cls()
    page._clipboard_timer.stop()
    return page


def _fill_rows(page, entries):
    """把 (title, author) 直接写进结果表，绕开解析流程。"""
    from PySide6.QtWidgets import QTableWidgetItem

    page.result_table.setRowCount(len(entries))
    for i, (title, author) in enumerate(entries):
        page.result_table.setItem(i, 2, QTableWidgetItem(title))
        page.result_table.setItem(i, 3, QTableWidgetItem(author))


def test_search_filter_matches_title_or_author(qapp):
    """过滤语义不变：命中标题**或**作者即显示（大小写不敏感）。"""
    page = _make_parse_page(qapp)
    _fill_rows(page, [
        ("Python 教程", "张三"),
        ("Rust 入门", "李四"),
        ("Golang", "Pythonista"),
    ])

    page._on_search_changed("python")

    hidden = [page.result_table.isRowHidden(i) for i in range(3)]
    assert hidden == [False, True, False]

    page._on_search_changed("")
    assert not any(
        page.result_table.isRowHidden(i) for i in range(3)
    ), "清空搜索必须全部恢复显示"


def test_search_haystack_is_cached(qapp, monkeypatch):
    """第二次带同样关键字过滤时，不得再对小写化结果重算。"""
    page = _make_parse_page(qapp)
    _fill_rows(page, [("Alpha 标题", "甲"), ("Beta 标题", "乙")])

    page._on_search_changed("alpha")
    item = page.result_table.item(0, 2)

    from doubi.ui.pages import parse as parse_mod

    hay = item.data(parse_mod._HAYSTACK_ROLE)
    assert hay is not None and "alpha" in hay

    # 手动把缓存改成哨兵值：若过滤真的读了缓存，行 0 会变成「不命中」。
    item.setData(parse_mod._HAYSTACK_ROLE, "zzz-sentinel")
    page._on_search_changed("alpha")
    assert page.result_table.isRowHidden(0) is True, "过滤没有走缓存"


def test_search_cache_invalidated_on_row_removal(qapp):
    """删行后缓存必须清，否则行号位移会读到错行的小写串。"""
    page = _make_parse_page(qapp)
    _fill_rows(page, [("第一行", "甲"), ("第二行", "乙")])
    page._on_search_changed("第一")
    assert page.result_table.isRowHidden(0) is False

    from doubi.ui.pages import parse as parse_mod

    page._invalidate_haystack_cache()
    assert page.result_table.item(0, 2).data(parse_mod._HAYSTACK_ROLE) is None


def test_selected_items_dedupes_by_item_id(qapp):
    """``_selected_items`` 的 id 去重语义不变（改用 set 后仍要去重）。"""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QTableWidgetItem

    from doubi.core.models import MediaItem
    from doubi.core.models import Platform as ModelPlatform

    page = _make_parse_page(qapp)
    items = [
        MediaItem(item_id="av1", title="A", source_url="https://x/1",
                  platform=ModelPlatform.BILIBILI),
        MediaItem(item_id="av1", title="A 重复", source_url="https://x/1b",
                  platform=ModelPlatform.BILIBILI),
        MediaItem(item_id="av2", title="B", source_url="https://x/2",
                  platform=ModelPlatform.BILIBILI),
    ]
    page._parsed_items = items
    # ``_expanded_rows`` 正常由构造路径建出来；这里直接塞 ``_parsed_items``
    # 绕过了那一步，得自己补上空表。
    page._expanded_rows = {}
    page.result_table.setRowCount(3)
    for i in range(3):
        chk = QTableWidgetItem()
        chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
        chk.setCheckState(Qt.Checked)
        page.result_table.setItem(i, 0, chk)
    page._refresh_row_mapping()

    selected = page._selected_items()
    ids = [getattr(it, "item_id", None) for it in selected]
    assert len(ids) == len(set(ids)), f"去重失效: {ids}"
    assert set(ids) == {"av1", "av2"}


# ---------------------------------------------------------------------------
# 4. HistoryPage 懒加载 + 脏标记
# ---------------------------------------------------------------------------


def _make_history_page(qapp):
    from doubi.ui.pages.history import build_history_widgets

    cls, _ = build_history_widgets()
    return cls()


def test_history_page_does_not_query_on_construction(qapp):
    """构造阶段不得查库——六个页签里它多数时候根本不会被打开。"""
    page = _make_history_page(qapp)
    assert page._loaded is False


def test_history_page_loads_on_first_show(qapp):
    page = _make_history_page(qapp)
    page._cfg.database = False          # 走「数据库未启用」短路分支
    page.showEvent(None)
    assert page._loaded is True


def test_history_mark_dirty_triggers_reload(qapp):
    """下载落库后必须重查，否则用户切过去看到的还是旧列表。"""
    page = _make_history_page(qapp)
    page._cfg.database = False
    page.showEvent(None)
    assert page._loaded is True and page._dirty is False

    page.mark_dirty()
    assert page._dirty is True
    page.showEvent(None)
    assert page._dirty is False, "showEvent 应消费掉脏标记"
