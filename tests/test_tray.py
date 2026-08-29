"""Tests for the M6.18 system-tray integration (``doubi.ui.tray``).

Why these tests exist
---------------------
Two real bugs shipped in the first cut of the tray and both were
invisible to the test suite, because "close the window, then click the
tray menu" is a two-step GUI interaction nobody had encoded:

1. ``_on_activated`` called ``int(reason)`` on a PySide6
   ``ActivationReason``, which is a ``QFlags``-style enum, not an
   ``int``. Every stray ``Hover`` / ``MiddleClick`` the shell sent
   raised ``TypeError`` *before* the ``emit()`` line.

2. ``MainWindow.closeEvent`` called
   ``tray.show_window_requested.disconnect()`` under a bogus «防止重复连»
   comment. Closing the window — the exact moment the app goes to the
   tray — severed every slot, so "显示主窗口" emitted into the void and
   the window could never be recovered.

``MainWindow`` itself can't be instantiated in this suite (constructing
it hangs; see the ``test_prompt_options`` integration tests), so bug 2
is guarded at the source level instead of behaviourally. That's an
honest tradeoff: a source guard can't prove the window reappears, but
it does fail loudly if anyone reintroduces the disconnect.
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
    except ImportError as exc:  # pragma: no cover
        pytest.skip(f"PySide6 not installed: {exc}")


@pytest.fixture(scope="module")
def qapp():
    _require_gui()
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture()
def tray(qapp):
    """A live ``TrayController``.

    Under ``offscreen`` the platform may report no system tray, in
    which case ``_icon`` stays ``None`` and the icon-dependent paths
    silently no-op. That's deliberate — every test below either
    monkeypatches ``show_message`` or exercises pure signal logic, so
    they pass in both worlds.
    """
    from doubi.ui.tray import TrayController
    controller = TrayController()
    yield controller
    controller.shutdown()


class _Recorder:
    """Collect ``show_message`` calls instead of hitting the shell."""

    def __init__(self):
        self.calls = []

    def __call__(self, title, body, *, icon_kind="info", msec=5000):
        self.calls.append({
            "title": title, "body": body, "icon_kind": icon_kind, "msec": msec,
        })


class TestActivationReason:
    """Regression guard for bug 1 — the ``int(reason)`` TypeError."""

    def test_trigger_emits_show_request(self, tray):
        from PySide6.QtWidgets import QSystemTrayIcon
        seen = []
        tray.show_window_requested.connect(lambda: seen.append(1))
        tray._on_activated(QSystemTrayIcon.ActivationReason.Trigger)
        assert seen == [1]

    def test_double_click_emits_show_request(self, tray):
        from PySide6.QtWidgets import QSystemTrayIcon
        seen = []
        tray.show_window_requested.connect(lambda: seen.append(1))
        tray._on_activated(QSystemTrayIcon.ActivationReason.DoubleClick)
        assert seen == [1]

    @pytest.mark.parametrize("reason_name", ["Unknown", "Context", "MiddleClick"])
    def test_other_reasons_are_silent_and_do_not_raise(self, tray, reason_name):
        # The shell fires these constantly. They must neither emit nor
        # blow up — the original code raised TypeError on every one.
        from PySide6.QtWidgets import QSystemTrayIcon
        seen = []
        tray.show_window_requested.connect(lambda: seen.append(1))
        reason = getattr(QSystemTrayIcon.ActivationReason, reason_name)
        tray._on_activated(reason)
        assert seen == []


class TestNotifyCompletion:
    """The ``notify_on_completion`` mode gate lives in one place."""

    def test_success_mode_notifies_on_success(self, tray):
        rec = _Recorder()
        tray.show_message = rec
        tray.notify_completion(mode="success", success=True, title="video A")
        assert len(rec.calls) == 1
        assert rec.calls[0]["title"] == "下载完成"
        assert "video A" in rec.calls[0]["body"]

    def test_success_mode_stays_silent_on_failure(self, tray):
        rec = _Recorder()
        tray.show_message = rec
        tray.notify_completion(
            mode="success", success=False, title="video A", error="boom",
        )
        assert rec.calls == []

    def test_all_mode_notifies_on_failure(self, tray):
        rec = _Recorder()
        tray.show_message = rec
        tray.notify_completion(
            mode="all", success=False, title="video A", error="HTTP 403",
        )
        assert len(rec.calls) == 1
        assert rec.calls[0]["title"] == "下载失败"
        assert "HTTP 403" in rec.calls[0]["body"]
        assert rec.calls[0]["icon_kind"] == "warning"

    def test_summary_mode_never_fires_per_task(self, tray):
        # ``summary`` is driven by DownloadPage's queue-drain check, not
        # by individual task events.
        rec = _Recorder()
        tray.show_message = rec
        tray.notify_completion(mode="summary", success=True, title="video A")
        tray.notify_completion(mode="summary", success=False, title="video B")
        assert rec.calls == []

    def test_unknown_mode_falls_back_to_success(self, tray):
        # A hand-edited config.yml can hand us anything.
        rec = _Recorder()
        tray.show_message = rec
        tray.notify_completion(mode="nonsense", success=True, title="video A")
        tray.notify_completion(mode="nonsense", success=False, title="video B")
        assert len(rec.calls) == 1
        assert rec.calls[0]["title"] == "下载完成"

    def test_failure_body_is_truncated_to_one_line(self, tray):
        rec = _Recorder()
        tray.show_message = rec
        tray.notify_completion(
            mode="all",
            success=False,
            title="video A",
            error="first line\nsecond line\nthird line",
        )
        body = rec.calls[0]["body"]
        assert "first line" in body
        assert "second line" not in body

    def test_missing_title_uses_placeholder(self, tray):
        rec = _Recorder()
        tray.show_message = rec
        tray.notify_completion(mode="success", success=True, title="")
        assert "（无标题）" in rec.calls[0]["body"]


class TestNotifySummary:
    def test_counts_appear_in_body(self, tray):
        rec = _Recorder()
        tray.show_message = rec
        tray.notify_summary(succeeded=3, failed=2)
        assert len(rec.calls) == 1
        body = rec.calls[0]["body"]
        assert "完成 3 项" in body
        assert "失败 2 项" in body

    def test_failed_clause_omitted_when_zero(self, tray):
        rec = _Recorder()
        tray.show_message = rec
        tray.notify_summary(succeeded=1, failed=0)
        assert "失败" not in rec.calls[0]["body"]

    def test_empty_summary_is_silent(self, tray):
        rec = _Recorder()
        tray.show_message = rec
        tray.notify_summary(succeeded=0, failed=0)
        assert rec.calls == []


class TestCloseEventDoesNotDisconnectTray:
    """Regression guard for bug 2 — the severed ``show_window_requested``.

    Source-level rather than behavioural because ``MainWindow()`` can't
    be constructed in this suite. If the assertion ever feels
    obstructive, replace it with a real integration test — don't just
    delete it.

    We read the file directly via ``ast`` rather than importing the
    module — that way the test doesn't require PySide6 (CI doesn't
    have it) and doesn't pull the whole ``ui.main_window`` import
    graph into the test process.
    """

    @staticmethod
    def _close_event_source() -> str:
        import ast
        from pathlib import Path
        path = Path(__file__).resolve().parent.parent / "src" / "doubi" / "ui" / "main_window.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        # ``closeEvent`` is a method on the class returned by
        # ``build_main_window``. ast.walk is recursive, so it finds
        # methods inside nested class defs too.
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "closeEvent":
                segment = ast.get_source_segment(source, node)
                if segment is not None:
                    return segment
        raise AssertionError("closeEvent not found in main_window.py")

    def test_close_event_never_disconnects_a_tray_signal(self):
        source = self._close_event_source()
        # Strip comments so the explanatory note about the old bug
        # (which mentions ``disconnect()``) doesn't trip the check.
        code = "\n".join(
            line.split("#", 1)[0] for line in source.splitlines()
        )
        assert "disconnect" not in code, (
            "closeEvent must not disconnect tray signals — doing so breaks "
            "'显示主窗口' forever after the first close."
        )

    def test_close_event_hides_instead_of_quitting_by_default(self):
        source = self._close_event_source()
        assert "event.ignore()" in source
        assert "self.hide()" in source


class TestMenuLifetime:
    """``setContextMenu`` doesn't take ownership — we must hold a ref."""

    def test_controller_keeps_menu_reference(self, tray):
        from PySide6.QtWidgets import QSystemTrayIcon
        if not QSystemTrayIcon.isSystemTrayAvailable():
            pytest.skip("no system tray on this platform")
        assert getattr(tray, "_menu", None) is not None
        # 显示主窗口 / sep / 全部暂停 / 全部继续 / sep / 退出
        assert len(tray._menu.actions()) == 6

    def test_show_action_emits_show_window_requested(self, tray):
        from PySide6.QtWidgets import QSystemTrayIcon
        if not QSystemTrayIcon.isSystemTrayAvailable():
            pytest.skip("no system tray on this platform")
        seen = []
        tray.show_window_requested.connect(lambda: seen.append(1))
        show_action = tray._menu.actions()[0]
        assert show_action.text() == "显示主窗口"
        show_action.trigger()
        assert seen == [1]

    def test_update_running_state_toggles_pause_resume(self, tray):
        from PySide6.QtWidgets import QSystemTrayIcon
        if not QSystemTrayIcon.isSystemTrayAvailable():
            pytest.skip("no system tray on this platform")
        tray.update_running_state(running=0, paused=0)
        assert not tray._pause_action.isEnabled()
        assert not tray._resume_action.isEnabled()
        tray.update_running_state(running=2, paused=0)
        assert tray._pause_action.isEnabled()
        assert not tray._resume_action.isEnabled()
        tray.update_running_state(running=0, paused=3)
        assert not tray._pause_action.isEnabled()
        assert tray._resume_action.isEnabled()


class TestShutdown:
    def test_shutdown_is_idempotent(self, tray):
        tray.shutdown()
        tray.shutdown()  # must not raise
        assert tray._icon is None
