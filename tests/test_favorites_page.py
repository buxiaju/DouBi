"""Favorites page (M6.51 GUI 入口) — factory / 接线 / 行为三层测试.

与 ``tests/test_search_hot_pages.py`` 同模式：页面是 QWidget，需要事件
循环才能完整驱动，所以工厂级用例 pin 公共面（类名 / 常量 / i18n /
main_window 接线），行为级用例用 offscreen QApplication 直接实例化页面、
mock 掉数据源（``collect_favorites_async``），不发真实网络请求。
"""
from __future__ import annotations

import asyncio
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


@pytest.fixture()
def page(qapp, monkeypatch, tmp_path):
    """构造隔离配置下的 FavoritesPage（不发网络、不碰用户配置）。"""
    import doubi.core.config as config_mod

    cfg_path = tmp_path / "config.yml"
    cfg_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(config_mod, "DEFAULT_CONFIG_PATH", cfg_path)

    from doubi.ui.pages.favorites import build_favorites_widgets

    cls, factory = build_favorites_widgets()
    assert factory is None
    return cls()


# ---------------------------------------------------------------------------
# 工厂 / 常量 / i18n（无 Qt 也有价值）
# ---------------------------------------------------------------------------


def test_factory_returns_widget_class():
    _require_gui()
    from doubi.ui.pages.favorites import build_favorites_widgets

    cls, factory = build_favorites_widgets()
    assert factory is None
    assert cls.__name__ == "FavoritesPage"
    assert hasattr(cls, "_build_ui") and callable(cls._build_ui)


def test_pages_module_exports_new_factory():
    from doubi.ui.pages import build_favorites_widgets

    assert callable(build_favorites_widgets)


def test_kind_constants_cover_all_five_kinds():
    from doubi.ui.pages.favorites import FAVORITE_KINDS, KIND_ROW_FIELDS

    kinds = [value for value, _label in FAVORITE_KINDS]
    assert kinds == ["favorites", "videos", "mix", "music", "series"]
    # 每一类都要有展示字段的取值路径，否则表格会静默渲染出空列。
    assert set(KIND_ROW_FIELDS) == set(kinds)
    for fields in KIND_ROW_FIELDS.values():
        assert fields["name"] and fields["id"]


def test_i18n_keys_exist_in_zh_cn_and_en():
    import json

    for locale, expected in (("zh_CN.json", "收藏"), ("en.json", "Favorites")):
        data = json.loads(
            (ROOT / "src" / "doubi" / "ui" / "locales" / locale).read_text(
                encoding="utf-8",
            ),
        )
        assert data["nav.favorites"] == expected


def test_main_window_wires_the_new_page():
    """main_window 必须建页 + 入导航 + 推配置——漏一步就是静默缺口。"""
    src = (ROOT / "src" / "doubi" / "ui" / "main_window.py").read_text(
        encoding="utf-8",
    )
    assert "build_favorites_widgets" in src
    assert "self.favorites_interface" in src
    assert 'tr("nav.favorites")' in src
    assert "self.favorites_interface._cfg = cfg" in src


# ---------------------------------------------------------------------------
# collect_favorites_async（CLI 核心，GUI 共用）
# ---------------------------------------------------------------------------


def test_collect_favorites_videos_without_id_raises_before_io():
    from doubi.cli.main import collect_favorites_async

    with pytest.raises(ValueError, match="collect_id"):
        asyncio.run(collect_favorites_async(kind="videos", collect_id=None))


def test_collect_favorites_unknown_kind_raises():
    from doubi.cli.main import collect_favorites_async

    with pytest.raises(ValueError, match="unknown favorites kind"):
        asyncio.run(collect_favorites_async(kind="nope"))


async def test_collect_favorites_dispatches_by_kind(monkeypatch):
    """5 个 kind 各自路由到正确的 webapi 方法（与 _FAVORITES_DISPATCH 对齐）。"""
    from doubi import cli
    from doubi.cli.main import collect_favorites_async

    calls: list[str] = []

    class FakeAPI:
        def __init__(self, *a, **kw):
            pass

    for kind, method in cli.main._FAVORITES_DISPATCH.items():
        async def _fake(*a, _method=method, **kw):
            calls.append(_method)
            return [{"kind": _method}]

        setattr(FakeAPI, method, _fake)

    monkeypatch.setattr(
        "doubi.platforms.douyin.webapi.DouyinWebAPI", FakeAPI,
    )
    for kind in cli.main._FAVORITES_DISPATCH:
        rows = await collect_favorites_async(
            kind=kind,
            collect_id="123" if kind == "videos" else None,
        )
        assert rows and rows[0]["kind"] == calls[-1]
    assert len(calls) == 5


# ---------------------------------------------------------------------------
# 页面行为（offscreen + mock 数据源）
# ---------------------------------------------------------------------------


def test_kind_switch_toggles_collect_id_row_visibility(page):
    # 页面本身没 show 过，isVisible 恒为 False；isHidden() 才反映
    # setVisible 的程序化状态（与祖先可见性无关）。
    page._kind_tabs.setCurrentItem("favorites")
    assert page._collect_id_input.isHidden() is True
    page._kind_tabs.setCurrentItem("videos")
    assert page._collect_id_input.isHidden() is False


def test_videos_kind_without_collect_id_never_fetches(page, monkeypatch):
    """缺 collects_id 时必须短路——不发请求、不切加载态。"""
    page._kind_tabs.setCurrentItem("videos")
    page._collect_id_input.setText("")
    called = []

    def _boom(*a, **kw):
        called.append(True)
        raise AssertionError("must not fetch")

    monkeypatch.setattr(page, "_run_async", _boom)
    page._on_refresh()
    assert not called
    # 停留在空态，而不是「加载中」的假象。
    assert page._stack.currentWidget() is page._empty_state


def test_no_cookie_file_shows_need_login_error_state(page, monkeypatch):
    """没有抖音 cookie 文件 → 引导态，不发网络请求。"""
    from doubi.platforms.douyin import auth as dy_auth

    monkeypatch.setattr(
        dy_auth, "default_cookie_path", lambda: Path("Z:/nonexistent/douyin.txt"),
    )
    def _boom(_coro):
        raise AssertionError("must not fetch")

    monkeypatch.setattr(page, "_run_async", _boom)
    jumps = []
    page.set_open_settings_callback(lambda: jumps.append(1))
    page._on_refresh()
    assert page._stack.currentWidget() is page._error_state
    # 引导动作指向设置页（主窗口接线后可用）。
    page._error_state._action.click()
    assert jumps


def test_populate_table_maps_each_kind_columns(page):
    """5 类行的名称 / ID / 链接取值路径逐类 pin 死。"""
    page._kind_tabs.setCurrentItem("favorites")
    page._rows = [{"collect_name": "我的收藏夹", "collects_id": "C1"}]
    page._populate_table()
    assert page.table.item(0, 0).text() == "我的收藏夹"
    assert page.table.item(0, 1).text() == "C1"
    assert page.table.item(0, 2).text() == "收藏夹"

    page._kind_tabs.setCurrentItem("videos")
    page._rows = [{
        "aweme_id": "730", "desc": "一个视频",
        "share_url": "https://www.douyin.com/video/730",
    }]
    page._populate_table()
    assert page.table.item(0, 0).text() == "一个视频"
    assert page.table.item(0, 1).text() == "730"
    assert page.table.item(0, 3).text().endswith("/video/730")

    page._kind_tabs.setCurrentItem("mix")
    page._rows = [{"mix_name": "合集A", "mix_id": "M1"}]
    page._populate_table()
    assert page.table.item(0, 1).text() == "M1"

    page._kind_tabs.setCurrentItem("music")
    page._rows = [{"mc_name": "音乐B", "mc_id": "MC1"}]
    page._populate_table()
    assert page.table.item(0, 1).text() == "MC1"

    page._kind_tabs.setCurrentItem("series")
    page._rows = [{"series_name": "短剧C", "series_id": "S1"}]
    page._populate_table()
    assert page.table.item(0, 1).text() == "S1"


def test_drill_into_videos_fills_id_and_switches_kind(page):
    page._kind_tabs.setCurrentItem("favorites")
    page._rows = [{"collect_name": "夹", "collects_id": "C9"}]
    page._populate_table()
    # setCurrentItem 会触发 currentItemChanged → _on_kind_changed → 刷新；
    # 这里 mock 掉网络入口，只验证「切类 + 填 ID」两个副作用。
    page._run_async = lambda coro: coro.close()
    page._drill_into_videos(page._rows[0])
    assert page._current_kind() == "videos"
    assert page._collect_id_input.text() == "C9"


def test_context_menu_entries_per_kind(page):
    """menu 动作分叉表：favorites 下钻 / mix 整包 / videos 三件套 / 其余无。"""
    page.set_task_manager(object())  # 入队动作可用

    page._kind_tabs.setCurrentItem("favorites")
    entries = page._menu_actions_for({"collects_id": "C1"}, "favorites")
    assert entries == [("查看收藏夹视频", True)]
    assert page._menu_actions_for({}, "favorites") == [
        ("查看收藏夹视频", False),
    ]

    page._kind_tabs.setCurrentItem("mix")
    assert page._menu_actions_for({"mix_id": "M1"}, "mix") == [
        ("下载整个合集", True),
    ]

    page._kind_tabs.setCurrentItem("videos")
    entries = page._menu_actions_for(
        {"aweme_id": "730", "share_url": "https://www.douyin.com/video/730"},
        "videos",
    )
    assert [label for label, _e in entries] == [
        "下载", "复制链接", "在浏览器中打开",
    ]
    assert all(enabled for _label, enabled in entries)
    # 只有 aweme_id 也能合成直链（row_actions 的兜底行为），三个动作可用。
    assert page._menu_actions_for({"aweme_id": "730"}, "videos") == [
        ("下载", True), ("复制链接", True), ("在浏览器中打开", True),
    ]
    # 未接任务管理器时只有「下载」不可用。
    page._task_manager = None
    entries = page._menu_actions_for(
        {"aweme_id": "730", "share_url": "https://www.douyin.com/video/730"},
        "videos",
    )
    assert entries[0] == ("下载", False)
    assert entries[1] == ("复制链接", True)

    page._kind_tabs.setCurrentItem("music")
    assert page._menu_actions_for({"mc_id": "MC1"}, "music") == []
    page._kind_tabs.setCurrentItem("series")
    assert page._menu_actions_for({"series_id": "S1"}, "series") == []
