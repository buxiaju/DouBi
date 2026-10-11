"""Unit tests for the 0.3.7 widget additions in :mod:`doubi.ui.widgets`.

Three new pieces:
* ``LoadingState`` — spinner + text, used in QStackedWidget during async work.
* ``ErrorState`` — distinguished from EmptyState by a status-failed label and
  a retry button.
* ``EmptyState.set_action`` — reusable CTA button under the subtitle, used
  by parse page's "try sample links" button.

All three have to be safe to instantiate without a real application — the
QStackedWidget-equivalent container is just a QWidget parent.
"""

from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _require_qt():
    try:
        import PySide6  # noqa: F401
        import qfluentwidgets  # noqa: F401
    except Exception as exc:   # noqa: BLE001
        pytest.skip(f"GUI stack unavailable: {exc}")


@pytest.fixture(scope="module")
def qapp():
    _require_qt()
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


# ---------------------------------------------------------------------------
# LoadingState
# ---------------------------------------------------------------------------

def test_loading_state_smoke(qapp):
    from doubi.ui.widgets import build_loading_state
    LoadingState = build_loading_state()
    w = LoadingState()
    w.set_message("正在拉取…")
    assert w._message.text() == "正在拉取…"
    # message setter should hide the label if text is empty
    w.set_message("")
    assert not w._message.isVisible()


def test_loading_state_start_stop(qapp):
    from doubi.ui.widgets import build_loading_state
    LoadingState = build_loading_state()
    w = LoadingState()
    # start / stop should not raise (they're thin wrappers around resume/pause)
    w.stop()
    w.start()
    w.stop()


# ---------------------------------------------------------------------------
# ErrorState
# ---------------------------------------------------------------------------

def test_error_state_default_text(qapp):
    from doubi.ui.widgets import build_error_state
    ErrorState = build_error_state()
    w = ErrorState()
    w.set_text("失败", "网络异常")
    assert w._title.text() == "失败"
    assert w._subtitle.text() == "网络异常"
    # No action set yet → button hidden
    assert not w._action.isVisible()


def test_error_state_action_calls_callback(qapp):
    from doubi.ui.widgets import build_error_state
    ErrorState = build_error_state()
    w = ErrorState()
    seen = []

    def cb():
        seen.append("clicked")

    w.set_action("重试", cb)
    # offscreen 测试没 show() widget，``isVisible()`` 仍会返回 False
    # （"visible" = 父链都 show 且自身 show）。改用 ``not isHidden()``
    # 验证 set_action 是否取消了对按钮的隐藏。
    assert not w._action.isHidden()
    assert w._action.text() == "重试"
    w._action.click()
    assert seen == ["clicked"]


def test_error_state_action_empty_label_hides_button(qapp):
    from doubi.ui.widgets import build_error_state
    ErrorState = build_error_state()
    w = ErrorState()
    w.set_action("重试", lambda: None)
    assert not w._action.isHidden()
    w.set_action("", None)
    assert w._action.isHidden()


# ---------------------------------------------------------------------------
# EmptyState.set_action
# ---------------------------------------------------------------------------

def test_empty_state_action_button(qapp):
    """Parse page uses ``EmptyState.set_action`` for the "try sample
    links" CTA. Pin the contract: visible + text + callback on click,
    hidden when label is empty."""
    from doubi.ui.widgets import build_empty_state
    EmptyState = build_empty_state()
    w = EmptyState()
    seen = []

    def cb():
        seen.append("try sample")

    w.set_text("等待你粘贴链接", "粘贴后点「解析」")
    w.set_action("试试示例链接", cb)
    assert not w._action.isHidden()
    assert w._action.text() == "试试示例链接"
    w._action.click()
    assert seen == ["try sample"]


def test_empty_state_action_hidden_by_default(qapp):
    """The CTA button shouldn't be visible before anyone calls set_action."""
    from doubi.ui.widgets import build_empty_state
    EmptyState = build_empty_state()
    w = EmptyState()
    w.set_text("foo", "bar")
    assert w._action.isHidden()


def test_empty_state_action_empty_hides(qapp):
    from doubi.ui.widgets import build_empty_state
    EmptyState = build_empty_state()
    w = EmptyState()
    w.set_action("say hi", lambda: None)
    assert not w._action.isHidden()
    w.set_action("", None)
    assert w._action.isHidden()
