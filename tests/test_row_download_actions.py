"""0.3.6 — 搜索页 / 热榜页右键下载。

用户报告「搜索结果和热搜可以直接下载」——即这两个页面只能看不能用。
它们渲染的是上游**原始记录**（CLI 打印的同一批 dict），不是
``MediaItem``，所以「能下载」需要三件事：

1. 从记录里合成一个可解析的 URL（``ui/row_actions.py``）；
2. 把 URL 交给平台适配器 ``parse()`` 变成 ``MediaItem``；
3. 交给 ``TaskManager.add()`` 入队。

抖音热榜是特例：抖音热榜行**只有** ``word`` + ``sentence_id``，
没有 ``share_url``、没有任何视频 id——热榜行实测 ``has_share_url: 0``。
所以词条行的语义只能是「搜该词条，把搜到的视频入队」（用户在问卷里
确认了这个设计）。

本文件的用例分三层：
  * 纯函数层（URL 合成 / 词条判定）——**不需要 Qt**，因此 ci 口径下
    也真实执行；
  * 菜单项可用性层——同上，``_context_menu_entries`` 是刻意抽出来的
    纯函数；
  * 接线层——main_window 是否真的把 task_manager 传下去（源码级断言，
    不需要 Qt）。
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

import pytest

# Qt must render off-screen in this environment; the pages below are
# real QWidgets, so they cannot be instantiated before an application
# exists ("QWidget: Must construct a QApplication before a QWidget" —
# which aborts the whole process, not just the one test).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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
    """One QApplication for the whole file.

    Module scope (not function) because Qt refuses to build a second
    application in a process, and the pages here are widgets.

    Deliberately **not** ``autouse``: the pure-function tests at the top
    of this file (URL synthesis / hot-word detection) must keep running
    under the ``ci`` profile, where PySide6 is absent. An autouse
    fixture would skip the entire module instead of just the widget
    tests — that is exactly how a "lint-style" guard silently stops
    guarding. Widget tests therefore request this fixture explicitly,
    via ``_page()`` below.
    """
    _require_gui()
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    yield app


def _page(qapp, factory):
    """Build a page, guaranteeing the QApplication exists first.

    Qt *aborts the process* (not just the test) when a QWidget is built
    without an application, so the fixture must be taken here rather
    than trusted to each call site.
    """
    cls, _ = factory()
    return cls()


# ----------------------------------------------------------------------
# 1) URL 合成 —— 纯函数，不需要 Qt
# ----------------------------------------------------------------------

def test_douyin_video_row_builds_video_url():
    from doubi.ui.row_actions import douyin_share_url

    assert douyin_share_url({"aweme_id": "7123"}) == (
        "https://www.douyin.com/video/7123"
    )


def test_douyin_explicit_share_url_wins():
    """记录自带 ``share_url`` 时不得覆盖——上游知道的比我们猜得准。"""
    from doubi.ui.row_actions import douyin_share_url

    row = {"aweme_id": "1", "share_url": "https://www.douyin.com/video/999"}
    assert douyin_share_url(row) == "https://www.douyin.com/video/999"


def test_douyin_hot_word_row_builds_search_url():
    """热榜词条没有 id，唯一有意义的 URL 是「搜这个词」。"""
    from doubi.ui.row_actions import douyin_share_url

    url = douyin_share_url({"word": "小猫咪", "sentence_id": "777"})
    assert url is not None
    assert url.startswith("https://www.douyin.com/search/")
    assert "%E5%B0%8F%E7%8C%AB%E5%92%AA" in url, url


def test_douyin_hot_word_url_is_percent_encoded():
    """词条里出现 ``&`` / ``?`` / 空格时不能被当成查询参数分隔符。"""
    from doubi.ui.row_actions import douyin_share_url

    url = douyin_share_url({"word": "a&b c?d"})
    assert url == "https://www.douyin.com/search/a%26b%20c%3Fd"


def test_douyin_live_row_prefers_room_over_video():
    """直播记录同时带 ``uid``（主播）与 ``room_id``。

    如果先走视频分支就会错判——直播间记录里没有 ``aweme_id``，
    而 ``uid`` 会被误当作者主页，所以顺序必须是先 room 后 user。
    """
    from doubi.ui.row_actions import douyin_share_url

    assert douyin_share_url({"room_id": "555", "uid": "12"}) == (
        "https://live.douyin.com/555"
    )


def test_douyin_user_row_uses_sec_uid():
    from doubi.ui.row_actions import douyin_share_url

    assert douyin_share_url({"sec_uid": "MS4wLjABAAAA"}) == (
        "https://www.douyin.com/user/MS4wLjABAAAA"
    )


def test_douyin_row_without_any_id_has_no_url():
    """纯热度行（无 word / 无 id）必须返回 None，不能拼出个假 URL。"""
    from doubi.ui.row_actions import douyin_share_url

    assert douyin_share_url({}) is None
    assert douyin_share_url({"hot_value": 12345}) is None


def test_bilibili_video_row_builds_bvid_url():
    from doubi.ui.row_actions import bilibili_share_url

    assert bilibili_share_url({"bvid": "BV1GJ411x7h7"}) == (
        "https://www.bilibili.com/video/BV1GJ411x7h7"
    )


def test_bilibili_aid_fallback_uses_av_prefix():
    """B 站搜索偶尔只回 ``aid``（老接口），URL 形如 ``/video/av<aid>``。"""
    from doubi.ui.row_actions import bilibili_share_url

    assert bilibili_share_url({"aid": 170001}) == (
        "https://www.bilibili.com/video/av170001"
    )


def test_bilibili_user_row_uses_space_url():
    from doubi.ui.row_actions import bilibili_share_url

    assert bilibili_share_url({"mid": 486906719, "uname": "某UP"}) == (
        "https://space.bilibili.com/486906719"
    )


def test_share_url_for_dispatches_by_platform():
    from doubi.ui.row_actions import share_url_for

    assert share_url_for({"bvid": "BV1"}, "bilibili") == (
        "https://www.bilibili.com/video/BV1"
    )
    assert share_url_for({"aweme_id": "7"}, "douyin") == (
        "https://www.douyin.com/video/7"
    )
    # 未知平台不猜——宁可没有菜单项，也不要拼错平台的链接。
    assert share_url_for({"aweme_id": "7"}, "youtube") is None


def test_row_item_id_prefers_aweme_over_uid():
    """``aweme_id`` 必须排在 ``uid`` 前面。

    抖音「综合」搜索的 video 命中同时带作者的 ``uid``；
    若先取 ``uid`` 就会给一条视频拼出用户主页链接。
    """
    from doubi.ui.row_actions import row_item_id

    assert row_item_id({"aweme_id": "7123", "uid": "99"}) == "7123"


def test_row_item_id_handles_non_dict():
    from doubi.ui.row_actions import row_item_id

    assert row_item_id(None) == ""          # type: ignore[arg-type]
    assert row_item_id({"uid": None}) == ""


# ----------------------------------------------------------------------
# 2) 词条行判定 —— 决定菜单分叉
# ----------------------------------------------------------------------

def test_hot_word_row_detected():
    from doubi.ui.row_actions import is_hot_word_row

    assert is_hot_word_row({"word": "热搜词", "sentence_id": "1"}) is True
    assert is_hot_word_row({"sentence_id": "1"}) is True


@pytest.mark.parametrize("row", [
    {"aweme_id": "1", "word": "带 word 的视频行"},
    {"bvid": "BV1", "word": "带 word 的视频行"},
    {"room_id": "5", "word": "直播间"},
])
def test_video_rows_are_not_hot_words(row):
    """有可下载 id 的行永远走「下载」分支，哪怕它凑巧也带 ``word``。"""
    from doubi.ui.row_actions import is_hot_word_row

    assert is_hot_word_row(row) is False


def test_plain_row_is_not_hot_word():
    from doubi.ui.row_actions import is_hot_word_row

    assert is_hot_word_row({}) is False
    assert is_hot_word_row({"hot_value": 1}) is False


# ----------------------------------------------------------------------
# 3) 菜单项可用性 —— 纯函数，不需要 Qt
# ----------------------------------------------------------------------

class _RecordingManager:
    def __init__(self) -> None:
        self.added: list = []

    def add(self, item, options):
        self.added.append((item, options))
        return f"T{len(self.added):04d}"


def _menu_map(entries):
    return dict(entries)


def test_search_menu_entries_all_enabled_for_video_row(qapp):
    from doubi.ui.pages.search import build_search_widgets

    _require_gui()
    page = _page(qapp, build_search_widgets)
    page._task_manager = _RecordingManager()

    entries = _menu_map(page._context_menu_entries({"aweme_id": "7123"}))
    assert entries == {
        "下载": True,
        "复制链接": True,
        "在浏览器中打开": True,
    }


def test_search_menu_disables_download_without_task_manager(qapp):
    """页面独立构造（没有主窗口接线）时，「下载」必须灰掉而不是抛异常。"""
    from doubi.ui.pages.search import build_search_widgets

    _require_gui()
    page = _page(qapp, build_search_widgets)
    assert page._task_manager is None

    entries = _menu_map(page._context_menu_entries({"aweme_id": "7123"}))
    assert entries["下载"] is False
    # 复制链接 / 浏览器打开不依赖任务管理器，仍然可用。
    assert entries["复制链接"] is True
    assert entries["在浏览器中打开"] is True


def test_search_menu_all_disabled_for_unidentifiable_row(qapp):
    from doubi.ui.pages.search import build_search_widgets

    _require_gui()
    page = _page(qapp, build_search_widgets)
    page._task_manager = _RecordingManager()

    entries = _menu_map(page._context_menu_entries({"hot_value": 1}))
    assert entries == {
        "下载": False,
        "复制链接": False,
        "在浏览器中打开": False,
    }


def test_hot_menu_offers_only_word_search_for_hot_word_row(qapp):
    """词条行不给「复制链接」——它没有直链，给了就是骗人。

    0.3.6 修正：动作名不再叫「下载」。用户实测反馈是「点了一条却下了
    20 个」——一次点击会展开成整批搜索结果，标签必须说清这件事。
    """
    from doubi.ui.pages.hot import build_hot_widgets
    from doubi.ui.row_confirm import HOT_WORD_ACTION

    _require_gui()
    page = _page(qapp, build_hot_widgets)
    page._task_manager = _RecordingManager()

    entries = page._context_menu_entries({"word": "小猫咪"})
    assert [label for label, _ in entries] == [HOT_WORD_ACTION]
    assert entries[0][1] is True
    # A bare 「下载」 is exactly what misled the user.
    assert entries[0][0] != "下载"
    assert "复制链接" not in {label for label, _ in entries}


def test_hot_menu_word_entry_disabled_without_task_manager(qapp):
    from doubi.ui.pages.hot import build_hot_widgets
    from doubi.ui.row_confirm import HOT_WORD_ACTION

    _require_gui()
    page = _page(qapp, build_hot_widgets)

    entries = _menu_map(page._context_menu_entries({"word": "小猫咪"}))
    assert entries[HOT_WORD_ACTION] is False


def test_hot_menu_video_row_matches_search_page_shape(qapp):
    """B 站热门视频行是热榜里唯一真能直下的内容，菜单必须是完整三件套。

    注意必须先把页面切到 B 站：默认平台是抖音，一条 ``bvid`` 记录
    在抖音规则下合成不出 URL（这是**正确**行为，不是缺陷）。
    """
    from doubi.ui.pages.hot import build_hot_widgets

    _require_gui()
    page = _page(qapp, build_hot_widgets)
    page._task_manager = _RecordingManager()
    page._platform = "bilibili"

    entries = _menu_map(page._context_menu_entries({"bvid": "BV1GJ411x7h7"}))
    assert entries == {
        "下载": True,
        "复制链接": True,
        "在浏览器中打开": True,
    }
    assert "搜索该词条并下载" not in entries


def test_platform_mismatch_disables_the_row(qapp):
    """抖音规则下一条 B 站记录不该给出可点但会失败的菜单项。

    这就是「宁可没有菜单项，也不要拼错平台的链接」的运行时体现。
    """
    from doubi.ui.pages.hot import build_hot_widgets

    _require_gui()
    page = _page(qapp, build_hot_widgets)
    page._task_manager = _RecordingManager()
    assert page._platform == "douyin"

    entries = _menu_map(page._context_menu_entries({"bvid": "BV1GJ411x7h7"}))
    assert entries == {
        "下载": False,
        "复制链接": False,
        "在浏览器中打开": False,
    }


# ----------------------------------------------------------------------
# 4) 接线 —— main_window 必须把任务管理器交给这两个页面
# ----------------------------------------------------------------------

def test_main_window_wires_task_manager_into_search_and_hot():
    """源码级断言：``set_task_manager`` 少了任何一处，「下载」就永远是灰的。

    用 AST 而不是字符串搜索，避免注释里提到函数名就误判为通过。
    """
    src = (SRC / "doubi" / "ui" / "main_window.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    wired: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        if func.attr != "set_task_manager":
            continue
        value = func.value
        if isinstance(value, ast.Attribute):
            wired.append(value.attr)

    assert "search_interface" in wired, (
        f"search_interface.set_task_manager(...) is missing; wired={wired}"
    )
    assert "hot_interface" in wired, (
        f"hot_interface.set_task_manager(...) is missing; wired={wired}"
    )


def test_both_pages_expose_set_task_manager(qapp):
    from doubi.ui.pages.hot import build_hot_widgets
    from doubi.ui.pages.search import build_search_widgets

    for factory, name in (
        (build_search_widgets, "SearchPage"),
        (build_hot_widgets, "HotPage"),
    ):
        cls, _ = factory()
        assert cls.__name__ == name
        assert callable(getattr(cls, "set_task_manager", None)), name


@pytest.mark.parametrize("module_name,factory_name", [
    ("doubi.ui.pages.search", "build_search_widgets"),
    ("doubi.ui.pages.hot", "build_hot_widgets"),
])
def test_context_menu_handler_closes_over_qmenu(qapp, module_name, factory_name):
    """``QMenu`` 必须是**闭包变量**，不能是函数内 import。

    右键菜单的测试（含本文件的实机验证）靠替换闭包 cell 里的
    ``QMenu`` 为非模态子类来避免模态 ``exec`` 挂住进程。
    shiboken 会绕过 ``QMenu.exec = ...`` 直接派发到 C++，所以闭包
    是唯一可靠的注入点——一旦有人把 import 挪回函数体内，
    注入点就消失，测试会以「挂住」而不是「失败」的形式暴露。
    """
    import importlib

    module = importlib.import_module(module_name)
    cls, _ = getattr(module, factory_name)()
    handler = cls._on_table_context_menu
    freevars = handler.__code__.co_freevars
    assert "QMenu" in freevars, (
        f"{module_name}: QMenu is not a closure variable of "
        f"_on_table_context_menu; free variables are {freevars!r}. "
        "It must be imported at factory scope so tests can inject a "
        "non-modal replacement."
    )


# ----------------------------------------------------------------------
# 5) 入队路径 —— 用桩适配器打通 URL → MediaItem → TaskManager
# ----------------------------------------------------------------------

def test_enqueue_row_adds_parsed_item_to_task_manager(qapp):
    from doubi.ui.pages.search import build_search_widgets

    _require_gui()
    from doubi.core.models import Platform

    page = _page(qapp, build_search_widgets)
    manager = _RecordingManager()
    page._task_manager = manager

    import doubi.ui.row_actions as ra

    async def fake_build(url):
        from doubi.core.models import MediaItem

        return MediaItem(
            platform=Platform.DOUYIN, item_id="7123", title="某视频",
            source_url=url,
        ), []

    orig = ra.build_media_item
    ra.build_media_item = fake_build
    try:
        page._enqueue_row({"aweme_id": "7123"}, "https://www.douyin.com/video/7123")
    finally:
        ra.build_media_item = orig

    assert len(manager.added) == 1, manager.added
    item, opts = manager.added[0]
    assert item.item_id == "7123"
    assert opts is not None


def test_enqueue_row_reports_failure_instead_of_silence(qapp):
    """解析不出来时必须给出可见提示。

    0.3.6 的教训：静默失败是最贵的 bug——界面什么都不显示，
    用户以为软件坏了。
    """
    from doubi.ui.pages.search import build_search_widgets

    _require_gui()
    page = _page(qapp, build_search_widgets)
    manager = _RecordingManager()
    page._task_manager = manager

    toasts: list[tuple[str, str, str]] = []
    page._toast = lambda title, content, kind="success": toasts.append(
        (title, content, kind)
    )

    import doubi.ui.row_actions as ra

    async def fake_build(url):
        return None, []

    orig = ra.build_media_item
    ra.build_media_item = fake_build
    try:
        page._enqueue_row({"aweme_id": "1"}, "https://www.douyin.com/video/1")
    finally:
        ra.build_media_item = orig

    assert manager.added == []
    assert toasts and toasts[-1][2] == "error", toasts


def test_hot_word_enqueue_searches_then_adds_every_hit(qapp):
    """热榜词条行的完整链路：collect_search → 每命中一条 → 入队。

    0.3.6 起链路中间多了**一次确认**：搜完先弹框（带真实条数），
    用户确认后才入队。这里把 ``_confirm`` 打桩成「同意」，
    否则会阻塞在真实的模态 ``QMessageBox`` 上（CI 无人点击）。
    """
    from doubi.ui.pages.hot import build_hot_widgets

    _require_gui()

    page = _page(qapp, build_hot_widgets)
    manager = _RecordingManager()
    page._task_manager = manager
    # 词条搜索走的是「当前平台」；B 站热搜词能正常出结果。
    page._platform = "bilibili"

    seen: dict = {}
    page._confirm = lambda plan: (seen.setdefault("plan", plan), True)[1]

    import doubi.cli.main as cli_main
    import doubi.ui.row_actions as ra
    from doubi.core.models import MediaItem, Platform

    calls: list[dict] = []

    async def fake_search(**kwargs):
        calls.append(kwargs)
        return [
            {"bvid": "BV1", "title": "一"},
            {"bvid": "BV2", "title": "二"},
            {"title": "无法合成 URL 的行"},
        ]

    async def fake_build(url):
        return MediaItem(
            platform=Platform.BILIBILI, item_id=url.rsplit("/", 1)[-1],
            title="x", source_url=url,
        ), []

    orig_search = cli_main.collect_search_async
    orig_build = ra.build_media_item
    cli_main.collect_search_async = fake_search
    ra.build_media_item = fake_build
    try:
        page._search_word_and_enqueue({"word": "小猫咪"})
    finally:
        cli_main.collect_search_async = orig_search
        ra.build_media_item = orig_build

    assert calls and calls[0]["keyword"] == "小猫咪", calls
    assert calls[0]["channel"] == "video", calls
    # 确认框必须出现，且条数是**解析成功后**的真实条数（2 条），
    # 不是命中数（3 条）——否则弹框上的数字和实际入队数对不上。
    assert "plan" in seen, "词条行必须先弹确认框"
    assert "2" in seen["plan"].body, seen["plan"].body
    # 3 条命中里只有 2 条能合成 URL → 只入队 2 条。
    assert [i.item_id for i, _ in manager.added] == ["BV1", "BV2"], manager.added


def test_hot_word_enqueue_empty_result_explains_douyin_gate(qapp):
    """抖音搜索被风控拦是**平台侧**限制，客户端只能解释、不能装没事。

    0.3.6 已证实四个搜索通道全部返回 ``verify_check``；如果这里
    静默返回，用户就会重复点、以为软件坏了。
    """
    from doubi.ui.pages.hot import build_hot_widgets

    _require_gui()

    page = _page(qapp, build_hot_widgets)
    manager = _RecordingManager()
    page._task_manager = manager
    page._platform = "douyin"

    toasts: list[tuple[str, str, str]] = []
    page._toast = lambda title, content, kind="success": toasts.append(
        (title, content, kind)
    )

    import doubi.cli.main as cli_main

    async def fake_search(**kwargs):
        return []

    orig = cli_main.collect_search_async
    cli_main.collect_search_async = fake_search
    try:
        page._search_word_and_enqueue({"word": "小猫咪"})
    finally:
        cli_main.collect_search_async = orig

    assert manager.added == []
    assert toasts, "空结果必须给出提示，不能静默"
    title, content, kind = toasts[-1]
    assert kind == "warning"
    assert "风控" in content, content


def test_hot_word_enqueue_refuses_empty_keyword(qapp):
    from doubi.ui.pages.hot import build_hot_widgets

    _require_gui()
    page = _page(qapp, build_hot_widgets)
    page._task_manager = _RecordingManager()

    toasts: list[tuple[str, str, str]] = []
    page._toast = lambda title, content, kind="success": toasts.append(
        (title, content, kind)
    )
    page._search_word_and_enqueue({"sentence_id": "9"})
    assert toasts and toasts[-1][2] == "warning", toasts
