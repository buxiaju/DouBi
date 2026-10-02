"""账号状态刷新入口 ``_spawn_account_refresh`` 的契约用例。

这个 helper 之所以存在，就是为了「没有可用 asyncio loop」这种边角状态
（测试 / 截屏脚本 / ``--no-event-loop`` 启动）。而它的全部调用点都在 GUI
构造回调与按钮回调里——用真 Qt 页面去打靶，测到的主要是别的路径。所以
这里直接用假 page，不依赖 PySide6。

**关于「协程被丢弃」那条**：helper 里判别失败时显式 ``coro.close()``，
修的是协程对象既没执行也没 await、交给 GC 时抛
``RuntimeWarning: coroutine ... was never awaited`` 的泄漏。这条无法用合成
用例可靠锁住——实测在「loop 已关闭」的构造下，被丢弃的协程按引用计数就
被回收且不触发警告，真实告警只在 pytest 整套 GUI 跑起来、协程落进循环
引用链时才出现（也是它当初被发现的方式）。因此这里不写那条假用例，
改由真实触发点把关：``pytest -m gui -W always::RuntimeWarning`` 下
``tests/test_row_mapping_cache.py`` 必须 0 条 —— 去掉 ``coro.close()``
即复现，这条已验证过。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


class _FakePage:
    """只需要 ``_refresh_account_status_async``，helper 不碰别的属性。"""

    def __init__(self) -> None:
        self.calls = 0

    async def _refresh_account_status_async(self) -> None:
        self.calls += 1


def test_spawn_refresh_without_usable_loop_falls_back_to_sync():
    """loop 不可用 → 同步兜底跑一次，且不向调用方抛异常。

    真实触发条件：current loop 存在但已关闭，``ensure_future`` 拿它
    ``create_task`` 会抛 ``RuntimeError: Event loop is closed``，跟「压根
    没有 loop」走同一分支。按钮回调里没有 try，异常会直接冒到 Qt 槽。
    """
    from doubi.ui.pages import settings

    page = _FakePage()

    dead = asyncio.new_event_loop()
    asyncio.set_event_loop(dead)
    dead.close()
    try:
        settings._spawn_account_refresh(page)
    finally:
        asyncio.set_event_loop(None)

    assert page.calls == 1, "loop 不可用时应退化为同步跑一次"


def test_spawn_refresh_schedules_on_running_loop():
    """loop 可用 → 排到 loop 上跑，而不是就地同步执行（否则会阻塞 GUI）。"""
    from doubi.ui.pages import settings

    page = _FakePage()

    async def _main() -> None:
        settings._spawn_account_refresh(page)
        assert page.calls == 0, "排入 loop 后不应同步执行"
        await asyncio.sleep(0)

    asyncio.run(_main())
    assert page.calls == 1
