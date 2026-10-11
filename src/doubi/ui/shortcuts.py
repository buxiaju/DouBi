"""全局快捷键注册中心（0.3.7 新增）。

历史
----
0.3.6 之前的 GUI 完全靠鼠标点导航——全 UI 只有两处 ``QShortcut`` 哑调用。
键盘用户（「不打开鼠标光标就找不到北」）和重度用户（「点六次能省六次」）
都直接劝退。

设计取舍
========

* **不依赖菜单栏**：qfluentwidgets 的 ``MSFluentWindow`` 没有 menuBar，
  ``setMenuBar`` 挂上去也会被它自己的标题栏盖掉。所有快捷键走
  :class:`QShortcut`，与是否打开菜单无关。
* **context 全部用 ``Qt.ApplicationShortcut``**：
  - 应用切换、显示主窗口等系统级动作**必须**全局生效，关窗到托盘
    也要响应。
  - ``Ctrl+1..6`` 跳转、``F5`` 刷新、``Ctrl+Q`` 退出——不会和任何
    文本输入抢键（``QLineEdit`` 不消费 ``Ctrl+数字``，也不消费
    ``F5`` / ``Ctrl+Q`` / ``Ctrl+,``）。
  - ``Ctrl+Enter`` 解析只挂解析页（页面级），不抢设置/搜索页的回车。
* **不调 ``setShortcutAutoRepeat(False)``**：所有快捷键都是「按下一次
  触发一次」的语义，``autoRepeat`` 关掉反而会让长按不再触发。
* **callback 异常必须 swallow**：快捷键回调是用户事件路径上的代码，
  它抛异常会被 Qt 转成 ``showMessage`` 弹窗，反而把用户的操作打断。
  这里包一层 try / except + swallow + log。

使用方式
========
::
    mgr = ShortcutManager(self)
    mgr.register("解析",   "Ctrl+1", lambda: self._switch_to(self.parse_interface),
                 description="跳到解析页", category="导航")
    mgr.register("刷新",   "F5",     self._refresh_current_page,
                 description="刷新当前页面", category="刷新")
    # 给设置页的「快捷键速查」卡片喂数据
    for cat, specs in mgr.cheat_sheet().items():
        ...
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut

logger = logging.getLogger("doubi.ui.shortcuts")


@dataclass
class ShortcutSpec:
    """一条快捷键的元数据。注册到 :class:`ShortcutManager` 后会拿到
    一个绑定的 :class:`QShortcut`，挂在 parent 上。

    不是 frozen——需要设置内部 ``_shortcut`` 字段。其它字段保持
    只读语义（manager 自己不会改 name / key 等）。
    """
    name: str                       # 显示名（中文），如「跳到解析」
    key: str                        # QKeySequence 字符串，如 "Ctrl+1"
    callback: Callable[[], None]    # 触发回调
    description: str = ""           # 「干什么的」详细描述，给速查卡片
    category: str = "其他"          # 分组，给速查卡片
    _shortcut: Optional[QShortcut] = field(default=None, init=False, repr=False)


class ShortcutManager:
    """持有所有快捷键的 QShortcut，parent 通常是 MainWindow。"""

    def __init__(self, parent):
        # 用 object 注解避免硬 import Qt——单测用 dummy parent 验证注册流。
        self._parent = parent
        self._specs: list[ShortcutSpec] = []

    def register(
        self,
        name: str,
        key: str,
        callback: Callable[[], None],
        description: str = "",
        category: str = "其他",
    ) -> ShortcutSpec:
        """Register one shortcut.

        重复 ``(name, key)`` 会被去重：第二次注册静默覆盖第一次的
        QShortcut，不留 dangling reference。

        Callback 包装
        -------------
        用户传入的 callback 会被一个 ``_safe`` 包装函数替换（写到
        ``spec.callback`` 上）——所有触发路径（QShortcut.activated、
        测试里的 ``spec.callback()`` 手动调用）走同一个包装，
        异常一律 swallow 并记日志。**不要**绕过包装直接调用
        原始 callable，否则异常会冒到 Qt 的事件循环。
        """
        # 去重：如果同 key 已有注册，覆盖之（避免重复 QShortcut 抢同一个键）
        existing = next(
            (s for s in self._specs if s.key == key), None,
        )
        if existing is not None:
            logger.debug(
                "快捷键 %s 重复注册：覆盖 %s -> %s",
                key, existing.name, name,
            )
            self._specs.remove(existing)
            if existing._shortcut is not None:
                existing._shortcut.setParent(None)
                existing._shortcut.deleteLater()

        # 把 callback 包一层 try / except：
        # 快捷键是用户事件路径上的代码，异常被 Qt 转成 showMessage 弹窗
        # 会打断用户操作；这里直接 swallow 并记日志。
        original = callback

        def _safe(*_args, **_kwargs):
            try:
                original()
            except Exception:   # noqa: BLE001
                logger.exception(
                    "快捷键回调异常 [%s %s]", key, name,
                )

        spec = ShortcutSpec(
            name=name, key=key, callback=_safe,
            description=description, category=category,
        )
        sc = QShortcut(QKeySequence(key), self._parent)
        sc.setContext(Qt.ApplicationShortcut)
        sc.activated.connect(_safe)
        spec._shortcut = sc
        self._specs.append(spec)
        return spec

    def specs(self) -> list[ShortcutSpec]:
        """Return all registered shortcuts, registration order preserved."""
        return list(self._specs)

    def cheat_sheet(self) -> dict[str, list[ShortcutSpec]]:
        """Group specs by category, for the Settings page cheat-sheet card.

        Returns a dict ordered by first-seen category. ``dict`` 在
        Python 3.7+ 保留插入顺序，正好对应注册顺序。
        """
        out: dict[str, list[ShortcutSpec]] = {}
        for spec in self._specs:
            out.setdefault(spec.category, []).append(spec)
        return out

    def count(self) -> int:
        return len(self._specs)


__all__ = ["ShortcutManager", "ShortcutSpec"]
