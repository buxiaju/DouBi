"""Batch row actions must ask before fanning out (0.3.6 fix).

Reported: right-clicking ONE row on the hot page queued MANY downloads.

Root cause was not a wrong fan-out but an unannounced one: the 热搜词 row
is a word with no downloadable target of its own, so its action means
"search that word and queue every hit" — 20 videos in the measured case
— and the menu label said only 「下载」.

Rules now pinned:

1. the word-row action is *named* for the fan-out, not 「下载」;
2. the word-row flow searches FIRST and confirms SECOND, so the count in
   the dialog is real rather than an estimate;
3. container rows (B 站 user hits → ``media_type=USER``) confirm too;
4. plain single-video rows do NOT confirm (no double-click tax);
5. declining the dialog must NOT queue anything.

The pure-function half runs without a QApplication, so it still executes
under the ``ci`` profile where PySide6 is blocked. The GUI half drives
real widgets offscreen.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _require_gui():
    pytest.importorskip("PySide6")
    pytest.importorskip("qfluentwidgets")


# ---------------------------------------------------------------------------
# 1. wording (pure — no Qt)
# ---------------------------------------------------------------------------


def test_hot_word_action_name_states_the_fan_out():
    """The label must not be a bare 「下载」 — that is the whole bug."""
    from doubi.ui.row_confirm import HOT_WORD_ACTION

    assert HOT_WORD_ACTION != "下载"
    assert "全部" in HOT_WORD_ACTION
    assert "搜索" in HOT_WORD_ACTION


def test_hot_word_confirm_uses_the_real_count():
    from doubi.ui.row_confirm import confirm_plan

    plan = confirm_plan(kind="hot_word", label="亚运会国足夺铜牌", count=20)

    assert "亚运会国足夺铜牌" in plan.body
    assert "20" in plan.body
    # Must say what is actually downloaded, since the word itself is not.
    assert "搜索结果" in plan.body
    assert plan.cancelled_text == "取消"


def test_hot_word_confirm_without_count_does_not_invent_a_number():
    """``count=None`` means "not known yet" — say so, don't guess."""
    from doubi.ui.row_confirm import confirm_plan

    plan = confirm_plan(kind="hot_word", label="某词", count=None)

    assert not re.search(r"共搜到\s*\d+", plan.body)
    assert "全部" in plan.body


def test_blank_label_never_renders_empty_quotes():
    from doubi.ui.row_confirm import confirm_plan

    plan = confirm_plan(kind="hot_word", label="   ", count=3)

    assert "「" in plan.body
    assert "「」" not in plan.body
    assert "该词条" in plan.body


def test_container_confirm_mentions_expansion():
    from doubi.ui.row_confirm import confirm_plan

    plan = confirm_plan(kind="container", label="某UP主", count=7)

    assert "合集" in plan.body or "主页" in plan.body
    assert "7" in plan.body


def test_container_confirm_without_count_says_many():
    from doubi.ui.row_confirm import confirm_plan

    plan = confirm_plan(kind="container", label="某UP主", count=None)

    assert "很多" in plan.body


def test_unknown_kind_is_loud():
    """A typo must raise, not silently return a generic dialog."""
    from doubi.ui.row_confirm import confirm_plan

    with pytest.raises(ValueError):
        confirm_plan(kind="nope", label="x", count=1)


# ---------------------------------------------------------------------------
# 2. container detection (pure — no Qt)
# ---------------------------------------------------------------------------


class _Item:
    def __init__(self, needs: bool = False):
        self._needs = needs

    def needs_expansion(self) -> bool:
        return self._needs


def test_container_is_batch_true_for_user_hit():
    from doubi.ui.row_confirm import container_is_batch

    assert container_is_batch(_Item(needs=True), []) is True


def test_container_is_batch_true_when_children_attached():
    from doubi.ui.row_confirm import container_is_batch

    assert container_is_batch(_Item(needs=False), [object()]) is True


def test_container_is_batch_false_for_plain_video():
    from doubi.ui.row_confirm import container_is_batch

    assert container_is_batch(_Item(needs=False), []) is False


def test_container_is_batch_tolerates_none_item():
    from doubi.ui.row_confirm import container_is_batch

    assert container_is_batch(None, []) is False


def test_container_is_batch_tolerates_a_broken_probe():
    """A raising probe must not take the whole UI down."""
    from doubi.ui.row_confirm import container_is_batch

    class _Boom:
        def needs_expansion(self):
            raise RuntimeError("nope")

    assert container_is_batch(_Boom(), []) is False


def test_expected_count_only_reports_attached_children():
    """An unattached container's size is unknown — say None, not 0."""
    from doubi.ui.row_confirm import expected_count

    assert expected_count(_Item(needs=True), []) is None
    assert expected_count(_Item(needs=True), [1, 2, 3]) == 3


def test_container_is_batch_agrees_with_mediatem_needs_expansion():
    """The UI rule and the model rule must not drift apart."""
    from doubi.core.models import MediaItem, MediaType, Platform
    from doubi.ui.row_confirm import container_is_batch

    for media_type, children, expected in (
        (MediaType.VIDEO, [], False),
        (MediaType.USER, [], True),
        (MediaType.MIX, [], True),
        (MediaType.VIDEO, [MediaItem(platform=Platform.UNKNOWN,
                                     item_id="1", title="c")], True),
    ):
        item = MediaItem(platform=Platform.UNKNOWN, item_id="x", title="t",
                         media_type=media_type, children=list(children))
        assert container_is_batch(item, children) is expected, media_type
        assert item.needs_expansion() is expected, media_type


# ---------------------------------------------------------------------------
# 3. GUI — the hot page must search first, confirm second, then queue
# ---------------------------------------------------------------------------

pytestmark_gui = pytest.mark.usefixtures()


@pytest.fixture(scope="module")
def qapp():  # noqa: ANN001
    """Module-scoped QApplication.

    Deliberately NOT ``autouse``: ci blocks PySide6, and an autouse
    fixture would fold every pure-logic test above into a skip.
    """
    _require_gui()
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


class _RecordingManager:
    def __init__(self):
        self.added = []

    def add(self, item, options) -> str:
        self.added.append(item)
        return f"T{len(self.added):04d}"


def _hot_page(qapp, manager, rows):
    from doubi.ui.pages.hot import build_hot_widgets

    factory, _ = build_hot_widgets()
    page = factory()
    page._rows = list(rows)
    page._platform = "bilibili"
    page.set_task_manager(manager)
    page._populate_table()
    return page


def _word_row():
    return {
        "word": "亚运会国足夺铜牌",
        "sentence_id": "1",
        "platform": "bilibili",
        "share_url": "https://search.bilibili.com/all?keyword=x",
    }


def _video_row():
    return {
        "bvid": "BV1PHay6UEaS",
        "title": "赵本山",
        "platform": "bilibili",
        "share_url": "https://www.bilibili.com/video/BV1PHay6UEaS",
    }


def test_hot_word_menu_label_is_not_bare_download(qapp):
    manager = _RecordingManager()
    page = _hot_page(qapp, manager, [_word_row()])

    entries = dict(page._context_menu_entries(_word_row()))

    assert "下载" not in entries
    from doubi.ui.row_confirm import HOT_WORD_ACTION

    assert HOT_WORD_ACTION in entries


def test_hot_page_confirms_before_queueing(qapp, monkeypatch):
    """The core regression: search → confirm → only then enqueue."""
    calls = {}

    async def _fake_search(**kwargs):
        calls["keyword"] = kwargs["keyword"]
        return [
            {"bvid": f"BV{i}", "title": f"t{i}",
             "share_url": f"https://www.bilibili.com/video/BV{i}"}
            for i in range(1, 6)
        ]

    async def _fake_build(url):
        from doubi.core.models import MediaItem, MediaType, Platform

        return MediaItem(platform=Platform.UNKNOWN, item_id=url[-4:],
                         title=url, media_type=MediaType.VIDEO), []

    import doubi.cli.main as cli_main
    import doubi.ui.row_actions as row_actions

    monkeypatch.setattr(cli_main, "collect_search_async", _fake_search)
    monkeypatch.setattr(row_actions, "build_media_item", _fake_build)

    manager = _RecordingManager()
    page = _hot_page(qapp, manager, [_word_row()])

    seen = {}

    def _fake_confirm(plan):
        seen["plan"] = plan
        return True

    monkeypatch.setattr(page, "_confirm", _fake_confirm)

    page._search_word_and_enqueue(_word_row())

    assert calls.get("keyword") == "亚运会国足夺铜牌"
    assert "plan" in seen, "词条行必须先弹确认框"
    assert "5" in seen["plan"].body, "确认框里的条数必须来自真实搜索结果"
    assert len(manager.added) == 5


def test_hot_page_declining_queues_nothing(qapp, monkeypatch):
    async def _fake_search(**kwargs):
        return [{"bvid": "BV1", "title": "t",
                 "share_url": "https://www.bilibili.com/video/BV1"}]

    async def _fake_build(url):
        from doubi.core.models import MediaItem, MediaType, Platform

        return MediaItem(platform=Platform.UNKNOWN, item_id="BV1",
                         title="t", media_type=MediaType.VIDEO), []

    import doubi.cli.main as cli_main
    import doubi.ui.row_actions as row_actions

    monkeypatch.setattr(cli_main, "collect_search_async", _fake_search)
    monkeypatch.setattr(row_actions, "build_media_item", _fake_build)

    manager = _RecordingManager()
    page = _hot_page(qapp, manager, [_word_row()])
    monkeypatch.setattr(page, "_confirm", lambda plan: False)

    page._search_word_and_enqueue(_word_row())

    assert manager.added == []


def test_hot_page_empty_search_never_opens_the_dialog(qapp, monkeypatch):
    """Nothing to confirm when nothing was found — just the 风控 warning."""
    async def _fake_search(**kwargs):
        return []

    import doubi.cli.main as cli_main

    monkeypatch.setattr(cli_main, "collect_search_async", _fake_search)

    manager = _RecordingManager()
    page = _hot_page(qapp, manager, [_word_row()])

    def _boom(plan):
        raise AssertionError("空结果不该弹确认框")

    monkeypatch.setattr(page, "_confirm", _boom)

    page._search_word_and_enqueue(_word_row())

    assert manager.added == []


def test_search_page_container_row_confirms(qapp, monkeypatch):
    from doubi.core.models import MediaItem, MediaType, Platform

    async def _fake_build(url):
        return MediaItem(platform=Platform.BILIBILI, item_id="898198",
                         title="某UP主", media_type=MediaType.USER), []

    import doubi.ui.row_actions as row_actions

    monkeypatch.setattr(row_actions, "build_media_item", _fake_build)

    from doubi.ui.pages.search import build_search_widgets

    factory, _ = build_search_widgets()
    page = factory()
    manager = _RecordingManager()
    page.set_task_manager(manager)

    seen = {}
    monkeypatch.setattr(page, "_confirm",
                       lambda plan: seen.setdefault("plan", plan) and False or False)

    page._enqueue_row({"mid": 898198, "uname": "某UP主"},
                      "https://space.bilibili.com/898198")

    assert "plan" in seen, "用户（容器）行必须先弹确认框"
    assert manager.added == []


def test_search_page_plain_video_row_does_not_confirm(qapp, monkeypatch):
    """Single-video rows stay one-click — no double-click tax."""
    from doubi.core.models import MediaItem, MediaType, Platform

    async def _fake_build(url):
        return MediaItem(platform=Platform.BILIBILI, item_id="BV1",
                         title="v", media_type=MediaType.VIDEO), []

    import doubi.ui.row_actions as row_actions

    monkeypatch.setattr(row_actions, "build_media_item", _fake_build)

    from doubi.ui.pages.search import build_search_widgets

    factory, _ = build_search_widgets()
    page = factory()
    manager = _RecordingManager()
    page.set_task_manager(manager)

    def _boom(plan):
        raise AssertionError("单视频行不该弹确认框")

    monkeypatch.setattr(page, "_confirm", _boom)

    page._enqueue_row({"bvid": "BV1"}, "https://www.bilibili.com/video/BV1")

    assert len(manager.added) == 1


# ---------------------------------------------------------------------------
# 4. the confirm dialog is actually wired to QMessageBox (AST, no Qt)
# ---------------------------------------------------------------------------


def test_both_pages_render_a_real_confirm_dialog():
    """``_confirm`` must build a QMessageBox, not just return a bool."""
    import ast

    for name in ("search.py", "hot.py"):
        path = _SRC / "doubi" / "ui" / "pages" / name
        tree = ast.parse(path.read_text(encoding="utf-8"))

        fn = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_confirm":
                fn = node
        assert fn is not None, f"{name} 缺少 _confirm"

        used = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
        assert "QMessageBox" in used, f"{name}._confirm 没用 QMessageBox"

        # The plan's own button labels must reach the dialog.
        src = ast.unparse(fn)
        assert "confirmed_text" in src, f"{name} 未使用 plan.confirmed_text"
        assert "cancelled_text" in src, f"{name} 未使用 plan.cancelled_text"


def test_hot_page_confirm_happens_after_the_search():
    """Ordering matters: the count must come from real results."""
    import ast

    path = _SRC / "doubi" / "ui" / "pages" / "hot.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))

    fn = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_search_word_and_enqueue":
            fn = node
    assert fn is not None

    src = ast.unparse(fn)
    assert src.index("collect_search_async") < src.index("confirm_plan"), (
        "必须先搜索再确认，否则弹框里的条数是猜的"
    )
    assert src.index("confirm_plan") < src.rindex(".add("), (
        "确认必须在入队之前"
    )
