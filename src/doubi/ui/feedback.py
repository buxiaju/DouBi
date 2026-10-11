"""统一的用户反馈 helper（0.3.7 新增）。

历史
----
六个页面里重复写了 **四遍** ``InfoBar.xxx(title=, content=, parent=self, ...)``，
差异是位置（parse 用 ``TOP_RIGHT``，其余五个用 ``TOP``）和 duration。
重复实现的代价是：

* 新页面要复制一遍，复制时容易走形（0.3.6 那次 InfoBar.message= 静默失败
  实际上就是某次复制粘贴漏了 ``InfoBar.success(message=...)`` 的位置）；
* 位置/标题/时长这些"全局观感"东西散在 N 个文件里，调一次就改 N 处；
* AST 静态扫如果想禁掉"裸调 InfoBar"，没法一刀切。

这个模块把 4 个 severity 各封一个具名 helper，让 AST 扫能定位到**所有**
反馈出口；同时把位置 + duration 集中在这一处——0.3.7 顺手统一到
``TOP_RIGHT``（不挡标题文字、与 qfluentwidgets 自带的 nav 也不冲突）。

约束
----
* helper 出错永远 swallow——反馈失败不能再触发反馈，陷入无限循环。
* helper 永远不抛——调用方可以放心在 ``except Exception`` 块里用。
* 用具名 helper 而不是 ``kind`` 参数：AST 静态扫能直接看到
  ``InfoBar.success/warning/error/info`` 这四个调用点，
  重命名/加新 severity 时扫不到就会报——约定比预期更友好。
"""

from __future__ import annotations

import logging

from qfluentwidgets import InfoBar, InfoBarPosition

logger = logging.getLogger("doubi.ui.feedback")


#: 普通提示停留时长（毫秒）。错误更久——见下面。
_DEFAULT_DURATION_MS = 4000

#: 错误提示停留更久，让用户有时间看、点开截图反馈、上 GitHub 提单。
_ERROR_DURATION_MS = 6000


def _show(
    kind,
    parent,
    title: str,
    content: str,
    duration: int,
) -> None:
    """Display an InfoBar; never raise.

    Caller-friendly contract: any failure here is logged at debug
    level and swallowed. The point of a feedback helper is that
    feedback itself is best-effort — if the Qt stack is in a bad
    state, the user already has a bigger problem.
    """
    try:
        kind(
            title=title,
            content=content,
            parent=parent,
            position=InfoBarPosition.TOP_RIGHT,
            duration=duration,
        )
    except Exception:   # noqa: BLE001 — see docstring
        logger.debug("InfoBar display failed", exc_info=True)


def toast_success(parent, title: str, content: str) -> None:
    """Green checkmark — operation completed cleanly."""
    _show(InfoBar.success, parent, title, content, _DEFAULT_DURATION_MS)


def toast_info(parent, title: str, content: str) -> None:
    """Neutral — info the user should see but doesn't need to act on."""
    _show(InfoBar.info, parent, title, content, _DEFAULT_DURATION_MS)


def toast_warning(parent, title: str, content: str) -> None:
    """Yellow — input was accepted but something might be off."""
    _show(InfoBar.warning, parent, title, content, _DEFAULT_DURATION_MS)


def toast_error(parent, title: str, content: str) -> None:
    """Red — operation did not complete; user should look at the message."""
    _show(InfoBar.error, parent, title, content, _ERROR_DURATION_MS)


__all__ = [
    "toast_success",
    "toast_info",
    "toast_warning",
    "toast_error",
]
