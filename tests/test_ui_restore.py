"""主窗口的跨进程恢复询问（M?.? 断点续传的最后一层）。

持久层（``pending_task`` 表）和 ``TaskManager.restore`` 各自都有单元
测试，但把两者接起来的那段——启动时读表、弹窗问人、按回答分岔——此前
一个测试都没有。这层恰恰是最容易坏且坏了最不容易发现的：

* 「不恢复」如果忘了落库，表面上完全正常，只有下一次启动才暴露；
* 「恢复」如果没把信号送到下载页，用户看到的是一个空列表加一句
  「已恢复 N 个」，比什么都不做更糟。

所以这里断言的是**外部可见的后果**（数据库里还剩几行、下载页建了几个
行控件、当前停在哪一页），而不是内部调用次数。

两处工装上的讲究：

* 测试直接 ``await window._restore_flow()``，不走 ``_offer_restore``。
  后者拿不到「正在运行的」事件循环就安静返回，而它判断的是 qasync 那
  个循环——直接构造窗口的 GUI 测试永远不满足，所以经它调用等于什么都
  没测（见 ``_offer_restore`` 的文档字符串）。这条契约本身由
  ``test_offer_restore_is_a_silent_noop_without_a_running_loop`` 单独盯。
* 弹窗正文读 ``box.content`` 而不是 ``box.contentLabel.text()``：
  qfluentwidgets 的 ``_adjustText()`` 会按宽度重新折行并回写到标签上，
  断言折行后的文本等于把测试绑死在窗口尺寸上。
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
    except ImportError as exc:   # pragma: no cover - 无 GUI 环境
        pytest.skip(f"GUI deps not installed: {exc}")


@pytest.fixture(scope="module")
def qapp():
    _require_gui()
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def window(qapp, tmp_path):
    """一个指向临时库的主窗口，用完就拆。

    刻意按测试函数而不是按模块建：每个场景都要一个干净的
    ``TaskManager``（恢复会往 ``_active`` 里塞任务）和一个干净的下载页
    （断言里要数行控件）。窗口级 fixture 共用一份状态的话，第二个测试
    就得先猜第一个留下了什么。
    """
    from doubi.ui.main_window import build_main_window
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication

    MainWindow = build_main_window()
    win = MainWindow()
    # 解析页是唯一的 AppConfig -> DownloadOptions 搬运点，所以要让恢复
    # 流程看见临时库，改的就是它读的那两个字段（见 parse._build_options）。
    win.parse_interface._cfg.database = True
    win.parse_interface._cfg.database_path = tmp_path / "doubi.db"
    win.parse_interface._cfg.output_root = tmp_path / "out"
    # 关掉切页动画。qfluentwidgets 的 StackedWidget.setCurrentWidget 默认
    # popOut=True，那条分支只记下 _nextIndex 并起一个 300ms 动画，真正的
    # QStackedWidget.setCurrentIndex 要等动画结束才执行——也就是说
    # currentWidget() 在调用后的 300ms 内还是旧页。不关的话「跳到下载页」
    # 只能靠 sleep 去等，既慢又是按时间赌。关掉之后切换同步生效，断言仍然
    # 是在查「产品代码有没有真的切页」这件事。
    win.stackedWidget.setAnimationEnabled(False)
    try:
        yield win
    finally:
        # 构造函数尾部那个 singleShot(0, _offer_restore) 在纯 asyncio 的
        # 测试循环里不会触发，但万一有别的测试转了 Qt 循环，留一个飞在
        # 半空的恢复任务会污染后面的用例。
        task = getattr(win, "_restore_task", None)
        if task is not None and not task.done():
            task.cancel()
        # 光调 deleteLater 等于没拆：它只是往队列里排一个 DeferredDelete，
        # 而这个文件里没人转 Qt 事件循环，队列永远不被消费。实测建 3 个窗口
        # 后 theme._callbacks 是 57，deleteLater 之后还是 57 —— 每个窗口的
        # 主题回调都活着，指向一堆本该死掉的控件。必须自己把这一种事件送出去
        # （processEvents 也行，但它会连带跑别的事件，这里只想要析构）。
        win.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _db_path(window) -> Path:
    return window.parse_interface.current_options().database


async def _seed(db_path: Path, count: int, *, prefix: str = "T", title_prefix: str = "上次的") -> list[str]:
    """往 pending 表里塞 *count* 行「上次没下完」的任务。

    直接写库而不是跑一遍真实下载：要测的是「启动时看见一堆遗留行会
    怎么做」，怎么产生这些行是持久层测试的事。
    """
    from doubi.core.storage import Database, PendingTaskRow

    ids: list[str] = []
    async with Database(db_path) as db:
        for n in range(count):
            task_id = f"{prefix}{n + 1:04d}"
            ids.append(task_id)
            await db.upsert_pending_task(PendingTaskRow(
                task_id=task_id,
                platform="bilibili",
                status="paused",
                source_url=f"https://www.bilibili.com/video/BV{n}",
                item_id=f"BV{n}",
                title=f"{title_prefix}{n}",
                fraction=0.25,
            ))
    return ids


async def _rows(db_path: Path) -> list:
    from doubi.core.storage import Database
    async with Database(db_path) as db:
        return await db.list_unfinished()


async def _wait_rows(db_path: Path, count: int, timeout: float = 2.0) -> list:
    """轮询到表里剩 *count* 行为止。

    ``discard_restorable`` 走的是 ``_run_db`` 那条「发射后不管」的路，
    没有句柄可 await，只能看结果。
    """
    import time
    deadline = time.monotonic() + timeout
    while True:
        rows = await _rows(db_path)
        if len(rows) == count or time.monotonic() > deadline:
            return rows
        await asyncio.sleep(0.01)


def _patch_dialog(monkeypatch, answer: int) -> list:
    """让恢复弹窗立刻返回 *answer*，并把弹出的对话框收集起来。

    返回收集列表：空列表就是「根本没问」，这本身是一条要断言的行为。
    """
    from qfluentwidgets import MessageBox

    boxes: list = []

    def fake_exec(self) -> int:
        boxes.append(self)
        return answer

    monkeypatch.setattr(MessageBox, "exec", fake_exec, raising=False)
    return boxes


async def _settle(window) -> None:
    """把恢复流程排下的落库写等回来。

    ``restore`` / ``discard_restorable`` 都只是 ``create_task``，而
    done-callback 又是 ``call_soon`` 派发的，所以先让循环转一轮再 flush，
    否则 ``_db_tasks`` 可能还是空的、flush 直接短路（同
    tests/test_task_manager.py 里那条注释）。
    """
    await asyncio.sleep(0)
    await window.task_manager.flush_pending_writes()


# ---------------------------------------------------------------------------
# 没有遗留任务：一句话都不该说
# ---------------------------------------------------------------------------


async def test_empty_database_asks_nothing(window, monkeypatch):
    """空表必须完全静默。

    在正常退出的用户身上，这是每次启动都会走的路径。多弹一个「没有需要
    恢复的任务」既没用又要点一下，属于把默认路径做成打扰。
    """
    boxes = _patch_dialog(monkeypatch, 1)
    parse_page = window.parse_interface

    await window._restore_flow()

    assert boxes == [], "空表不该弹窗"
    assert window.task_manager.active_tasks() == []
    assert window.stackedWidget.currentWidget() is parse_page, "不该跳页"


async def test_missing_database_file_asks_nothing(window, monkeypatch):
    """库文件根本不存在（首次运行）也只是静默。

    ``list_restorable`` 吞掉所有异常正是为了这一刻：启动路径上的任何
    毛病都不该拦住用户打开应用。
    """
    boxes = _patch_dialog(monkeypatch, 1)
    window.parse_interface._cfg.database_path = (
        Path(window.parse_interface._cfg.database_path).parent / "nope" / "doubi.db"
    )

    await window._restore_flow()

    assert boxes == []
    assert window.task_manager.active_tasks() == []


# ---------------------------------------------------------------------------
# 「恢复」
# ---------------------------------------------------------------------------


async def test_yes_reinstates_tasks_as_paused_and_shows_the_download_page(window, monkeypatch):
    """点「恢复」的完整后果，一路查到下载页的行控件。

    只断言 ``task_manager`` 里有任务是不够的：``task_added`` 信号没接上
    的话，用户看到的是一个空下载页配一句「已恢复 2 个」——比不恢复更让
    人不知道发生了什么。所以这里连 ``download_interface._rows`` 一起查。
    """
    boxes = _patch_dialog(monkeypatch, 1)
    db_path = _db_path(window)
    ids = await _seed(db_path, 2)

    await window._restore_flow()

    assert len(boxes) == 1, "有遗留任务就必须问"
    tasks = window.task_manager.active_tasks()
    assert sorted(t.task_id for t in tasks) == ids, "原来的 task_id 必须留住"
    assert {t.status for t in tasks} == {"paused"}, "恢复出来的任务只能是暂停态"
    assert all(t.fraction == pytest.approx(0.25) for t in tasks), "进度要接着上次"

    # 信号确实抵达了 UI。
    assert sorted(window.download_interface._rows) == ids

    # 并且真的落在下载页上——不然用户得自己去找这些任务在哪。
    assert window.stackedWidget.currentWidget() is window.download_interface

    # 恢复不等于消费掉：任务还没下完，行还得留着，好让下次退出后再问。
    await _settle(window)
    assert sorted(r.task_id for r in await _rows(db_path)) == ids


async def test_yes_does_not_start_downloading(window, monkeypatch):
    """恢复只是把任务摆回来，不替用户按下继续。

    重启这一刻用户的意图最不确定（应用可能正是因为下载占满带宽才被
    杀掉的），所以要等一次明确的继续。
    """
    _patch_dialog(monkeypatch, 1)
    db_path = _db_path(window)
    await _seed(db_path, 1)

    await window._restore_flow()

    mgr = window.task_manager
    assert [t.status for t in mgr.active_tasks()] == ["paused"]
    # 一个真的在跑的任务会在 _tasks 里留下 asyncio.Task；这里必须是空的。
    assert mgr._tasks == {}, "恢复不该启动传输"
    await _settle(window)


async def test_restored_ids_push_the_counter_so_a_new_task_cannot_collide(window, monkeypatch):
    """恢复完再新建任务，不能撞上恢复回来的编号。

    这条在 TaskManager 层已有单元测试，这里再走一遍窗口路径，是因为
    ``restore`` 的 ``base_options`` 是窗口传的：传错了（比如传了一份不带
    库路径的默认值）计数器照样会重播，而单元测试看不到这个接线。
    """
    _patch_dialog(monkeypatch, 1)
    db_path = _db_path(window)
    ids = await _seed(db_path, 3)
    assert ids[-1] == "T0003"

    await window._restore_flow()
    await _settle(window)

    mgr = window.task_manager
    fresh = mgr.add(_make_item(), window.parse_interface.current_options())
    try:
        assert fresh == "T0004", f"新任务撞上了恢复回来的 id: {fresh}"
    finally:
        # 这一个是真会去下载的，收掉它，别把网络请求漏进测试。
        mgr.remove(fresh)
        await _settle(window)


def _make_item():
    from doubi.core.models import Author, MediaItem, MediaType, Platform
    return MediaItem(
        platform=Platform.BILIBILI, item_id="BV_new", title="新任务",
        author=Author(name="u"), media_type=MediaType.VIDEO,
        source_url="https://www.bilibili.com/video/BV_new",
    )


# ---------------------------------------------------------------------------
# 「不恢复」
# ---------------------------------------------------------------------------


async def test_no_wipes_the_rows_so_the_question_is_asked_only_once(window, monkeypatch):
    """「不恢复」必须落库。

    忘了删行的话，这一版看起来完全正常——用户点了「不恢复」，任务确实
    没回来。代价在下一次启动：同一批任务又被问一遍，第三次用户就不看这
    个弹窗了，而它恰恰是要在真出事那次被看见的。
    """
    boxes = _patch_dialog(monkeypatch, 0)
    db_path = _db_path(window)
    await _seed(db_path, 2)

    await window._restore_flow()

    assert len(boxes) == 1
    assert window.task_manager.active_tasks() == [], "说了不恢复就不能有任务"
    assert window.stackedWidget.currentWidget() is window.parse_interface

    assert await _wait_rows(db_path, 0) == [], "「不恢复」没有落库，下次启动还会问"

    # 同一个进程里再问一次，验证记录真的没了（这就是下一次启动看到的）。
    await window._restore_flow()
    assert len(boxes) == 1, "记录已清掉，不该再问第二遍"


async def test_no_keeps_the_files_and_only_forgets_the_bookkeeping(window, monkeypatch):
    """清掉的是账本，不是硬盘上的字节。

    弹窗正文对用户承诺了这一点，所以这条断言的是承诺本身：删除只发生在
    pending 表上，输出目录不受影响。
    """
    _patch_dialog(monkeypatch, 0)
    db_path = _db_path(window)
    await _seed(db_path, 1)

    partial = Path(window.parse_interface._cfg.output_root)
    partial.mkdir(parents=True, exist_ok=True)
    fragment = partial / "BV0.mp4.part"
    fragment.write_bytes(b"already downloaded")

    await window._restore_flow()
    await _wait_rows(db_path, 0)

    assert fragment.exists(), "「不恢复」不该动已下载的文件片段"
    assert fragment.read_bytes() == b"already downloaded"


# ---------------------------------------------------------------------------
# 弹窗文案
# ---------------------------------------------------------------------------


async def test_prompt_lists_the_titles_it_found(window, monkeypatch):
    """正文要写出具体是哪些任务。

    「有 3 个任务没下完」无法回答用户唯一关心的问题——是我在意的那个
    吗？没有标题，这个弹窗只能靠猜来回答。
    """
    boxes = _patch_dialog(monkeypatch, 0)
    db_path = _db_path(window)
    await _seed(db_path, 3, title_prefix="想要的片子")

    await window._restore_flow()
    await _wait_rows(db_path, 0)

    body = boxes[0].content
    assert "3 个任务" in body
    for n in range(3):
        assert f"想要的片子{n}" in body


async def test_prompt_truncates_a_long_list_but_says_how_many_are_hidden(window, monkeypatch):
    """列表要有上限，但不能让剩下的凭空消失。

    上限保护的是弹窗尺寸；「另有 N 个」保护的是数量的可信度——只列 5 条
    又不说还有多少，用户会以为总共就 5 个。
    """
    boxes = _patch_dialog(monkeypatch, 0)
    db_path = _db_path(window)
    await _seed(db_path, 7)

    await window._restore_flow()
    await _wait_rows(db_path, 0)

    body = boxes[0].content
    assert "7 个任务" in body
    assert body.count("  · ") == 5, "最多列 5 条"
    assert "另有 2 个" in body


async def test_prompt_falls_back_to_the_id_when_a_row_has_no_title(window, monkeypatch):
    """没有标题的行也要能被指认出来。

    标题是解析阶段的产物，可能缺（老库、解析到一半就退出）。这时候退到
    item_id 也比一行空的项目符号有用。
    """
    from doubi.core.storage import Database, PendingTaskRow

    boxes = _patch_dialog(monkeypatch, 0)
    db_path = _db_path(window)
    async with Database(db_path) as db:
        await db.upsert_pending_task(PendingTaskRow(
            task_id="T0001", platform="bilibili", status="paused",
            source_url="https://www.bilibili.com/video/BV_noname",
            item_id="BV_noname",
        ))

    await window._restore_flow()
    await _wait_rows(db_path, 0)

    assert "BV_noname" in boxes[0].content


# ---------------------------------------------------------------------------
# 启动钩子本身
# ---------------------------------------------------------------------------


def test_offer_restore_is_a_silent_noop_without_a_running_loop(window, monkeypatch):
    """没有正在运行的事件循环时，启动钩子必须安静跳过。

    ``--no-event-loop`` 模式和 GUI 测试都属于这种情形。这里刻意是个
    **同步**测试：async 测试自带一个运行中的循环，正好测不到这条路。

    反过来说，这条测试也是上面所有用例直接 await ``_restore_flow`` 的
    理由——经 ``_offer_restore`` 调用在这个环境里等于什么都没做。
    """
    boxes = _patch_dialog(monkeypatch, 1)

    window._offer_restore()

    assert boxes == []
    assert getattr(window, "_restore_task", None) is None


def test_offer_restore_keeps_a_reference_to_the_task(window, monkeypatch):
    """有循环时，任务句柄必须被留住。

    asyncio 只持弱引用，扔掉句柄的话恢复流程可能在半路被回收——而且是
    偶发的，只在恰好赶上一次 GC 时才出问题。
    """
    _patch_dialog(monkeypatch, 0)

    async def _drive() -> None:
        window._offer_restore()
        task = getattr(window, "_restore_task", None)
        assert task is not None, "句柄没留住，恢复流程可能被中途回收"
        await task
        assert task.done() and task.exception() is None

    asyncio.run(_drive())
