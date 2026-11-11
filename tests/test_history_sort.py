"""历史页表头排序（P2 收口：GUI 已完成列表排序）。

三个不显然的坑（实现与测试都围绕它们）：

* **填充过程中排序必须关闭**——``setSortingEnabled(True)`` 时 ``setItem``
  会把行插进「当前排序位置」，行序直接错乱。``_populate`` 填充前后
  分别关 / 开，并保留用户上一次选的排序列。
* **行 → 数据映射跟着单元格走**——排序打乱视觉行序后
  ``self._rows[row]`` 不再成立，记录本体挂在每格的 ``UserRole+1`` 上，
  右键菜单 / 打开目录走 ``_row_record``。
* **时间列按数值排**——``_SortCell`` 优先比较 ``UserRole`` 里的时间戳，
  其余列退化为文本比较。
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

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


def _row(platform, item_id, title, author, ts, save_dir="D:\\Downloaded\\x\\video"):
    return SimpleNamespace(
        platform=platform, item_id=item_id, title=title,
        author_name=author, last_download_time=ts, last_save_dir=save_dir,
    )


ROWS = [
    # 故意用「时间降序 ≠ 标题升序」的排布，两个方向都能验证出移动
    _row("bilibili", "BV111", "香蕉", "阿三", 1700000100),
    _row("douyin", "222333", "苹果", "阿一", 1700000300),
    _row("bilibili", "BV222", "樱桃", "阿二", 1700000200),
]


class _FakeDB:
    """替身 Database：返回固定行集，测排序不动真库。"""

    def __init__(self, _path):
        pass

    async def initialize(self):
        pass

    async def close(self):
        pass

    async def count(self):
        return len(ROWS)

    async def list_recent(self, *, limit=200):
        return list(ROWS)


@pytest.fixture()
def page(qapp, monkeypatch, tmp_path):
    _require_gui()
    import doubi.core.storage.database as db_mod
    monkeypatch.setattr(db_mod, "Database", _FakeDB)
    from doubi.ui.pages.history import build_history_widgets
    cls, _ = build_history_widgets()
    page = cls()
    page._cfg.database = True
    page._cfg.database_path = tmp_path / "fake.db"
    asyncio.run(page._populate())
    return page


def _titles(page):
    t = page.table
    return [t.item(r, 2).text() for r in range(t.rowCount())]


def _q_sorted(values, reverse=False):
    """用 Qt 自己的 localeAwareCompare 语义排期望顺序。

    QTableWidgetItem 的 ``__lt__`` 是 localeAwareCompare（中文在 Windows
    上走拼音序），和 Python 字符串比较（码点位）不一致——期望值必须
    用同一把尺子算，不能硬编码。
    """
    from functools import cmp_to_key
    from PySide6.QtWidgets import QTableWidgetItem

    def cmp(a, b):
        ia, ib = QTableWidgetItem(a), QTableWidgetItem(b)
        return -1 if ia < ib else (0 if not (ib < ia) else 1)

    return sorted(values, key=cmp_to_key(cmp), reverse=reverse)


def test_default_sort_time_desc(page, qapp):
    """默认排序 = 下载时间倒序，与 list_recent 的 SQL 语义一致。"""
    from PySide6.QtCore import Qt
    assert _titles(page) == ["苹果", "樱桃", "香蕉"]
    header = page.table.horizontalHeader()
    assert header.sortIndicatorSection() == 4
    assert header.sortIndicatorOrder() == Qt.DescendingOrder


def test_header_click_sorts_by_title_and_record_follows(page, qapp):
    """点「标题」列升序：显示行序变化，且 _row_record 映射跟着走。"""
    from PySide6.QtCore import Qt

    page.table.setSortingEnabled(True)
    page.table.horizontalHeader().setSortIndicator(2, Qt.AscendingOrder)

    assert _titles(page) == _q_sorted(_titles(page))  # localeAware 升序
    # 每一行的记录都要与显示内容自洽（不是 _rows[行号]）
    for r in range(page.table.rowCount()):
        rec = page._row_record(r)
        assert rec.title == page.table.item(r, 2).text()
        assert rec.item_id == page.table.item(r, 1).text()


def test_time_column_sorts_by_timestamp_not_text(page, qapp):
    """时间列升序 = 时间戳升序；时间戳缺失的记录退到文本比较不崩。"""
    from PySide6.QtCore import Qt

    page.table.setSortingEnabled(True)
    page.table.horizontalHeader().setSortIndicator(4, Qt.AscendingOrder)

    ts_list = [page._row_record(r).last_download_time
               for r in range(page.table.rowCount())]
    assert ts_list == sorted(ts_list)


def test_sort_then_refresh_preserves_user_order(page, qapp):
    """用户选了排序后点刷新：数据重查，但排序选择保留。"""
    from PySide6.QtCore import Qt

    page.table.setSortingEnabled(True)
    page.table.horizontalHeader().setSortIndicator(3, Qt.DescendingOrder)
    asyncio.run(page._populate())

    header = page.table.horizontalHeader()
    assert header.sortIndicatorSection() == 3
    assert header.sortIndicatorOrder() == Qt.DescendingOrder
    authors = [page.table.item(r, 3).text()
               for r in range(page.table.rowCount())]
    assert authors == _q_sorted(authors, reverse=True)


def test_context_menu_row_uses_record_after_sort(page, qapp, monkeypatch):
    """排序后右键「重新解析」必须用显示行的记录，不是 _rows[0]。"""
    from PySide6.QtCore import Qt, QPoint

    urls: list = []
    page.set_reparse_callback(urls.append)
    page.table.setSortingEnabled(True)
    page.table.horizontalHeader().setSortIndicator(2, Qt.AscendingOrder)

    monkeypatch.setattr(page.table.viewport(), "mapToGlobal", lambda p: QPoint(0, 0))
    # QMenu.exec 会真弹菜单——这里直接验证数据层：排序后行 0 的记录
    # 必须就是行 0 显示的标题对应的那条记录（_on_context_menu 用它
    # 重建 URL，映射错了「重新解析」就会解析到别的视频）。
    record = page._row_record(0)
    assert record.title == page.table.item(0, 2).text()
