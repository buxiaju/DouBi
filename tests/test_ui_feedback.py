"""Unit tests for :mod:`doubi.ui.feedback` (0.3.7 new).

The four ``toast_*`` helpers all funnel through a private ``_show``
that swallows exceptions. We pin:

* severity → method dispatch (``toast_success`` → ``InfoBar.success``)
* uniform position (``Tp.topRight``) and longer duration for errors
* exception swallowing
"""

from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _require_qt():
    try:
        import PySide6  # noqa: F401
    except Exception as exc:   # noqa: BLE001
        pytest.skip(f"PySide6 unavailable: {exc}")


@pytest.fixture(scope="module")
def qapp():
    _require_qt()
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture
def parent(qapp):
    from PySide6.QtWidgets import QWidget
    w = QWidget()
    yield w
    w.deleteLater()


# ---------------------------------------------------------------------------
# smoke
# ---------------------------------------------------------------------------

def test_import_smoke():
    """Module should be importable without an InfoBar parent."""
    from doubi.ui import feedback
    for name in ("toast_success", "toast_info", "toast_warning", "toast_error"):
        assert callable(getattr(feedback, name))


def test_toast_success_calls_infobar_success(qapp, monkeypatch):
    """``toast_success`` must dispatch to ``InfoBar.success`` with
    ``title=`` / ``content=`` keyword args and ``position=Tp.topRight``."""
    from doubi.ui import feedback
    from qfluentwidgets import InfoBar, InfoBarPosition

    captured = {}

    def fake_success(**kwargs):
        captured.update(kwargs)
        # Return a sentinel so we can also verify InfoBar.success wasn't called with 'message='
    monkeypatch.setattr(InfoBar, "success", staticmethod(fake_success))

    feedback.toast_success(parent, "title-s", "body-s")
    assert captured["title"] == "title-s"
    assert captured["content"] == "body-s"
    assert captured["position"] == InfoBarPosition.TOP_RIGHT
    assert captured["duration"] == feedback._DEFAULT_DURATION_MS
    # Make sure no kwarg named 'message' was used (the 0.3.6 silent bug):
    assert "message" not in captured


def test_toast_error_has_longer_duration(qapp, monkeypatch):
    """Errors get 6s, others 4s — long enough for the user to read."""
    from doubi.ui import feedback
    from qfluentwidgets import InfoBar

    durations = {}

    def fake_error(**kwargs):
        durations["error"] = kwargs["duration"]

    def fake_info(**kwargs):
        durations["info"] = kwargs["duration"]

    monkeypatch.setattr(InfoBar, "error", staticmethod(fake_error))
    monkeypatch.setattr(InfoBar, "info",  staticmethod(fake_info))

    feedback.toast_error(parent, "t", "c")
    feedback.toast_info (parent, "t", "c")
    assert durations["error"] > durations["info"]
    assert durations["error"] == feedback._ERROR_DURATION_MS


def test_toast_warning_calls_infobar_warning(qapp, monkeypatch):
    from doubi.ui import feedback
    from qfluentwidgets import InfoBar

    captured = {}

    def fake_warning(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(InfoBar, "warning", staticmethod(fake_warning))

    feedback.toast_warning(parent, "warn", "danger")
    assert captured["title"] == "warn"
    assert captured["content"] == "danger"


def test_toast_helpers_swallow_exceptions(qapp, monkeypatch):
    """If InfoBar raises (e.g. parent already destroyed), the toast
    helpers must not propagate — feedback failure must never raise."""
    from doubi.ui import feedback
    from qfluentwidgets import InfoBar

    def boom(**kwargs):
        raise RuntimeError("InfoBar exploded")

    for sev in ("success", "info", "warning", "error"):
        monkeypatch.setattr(InfoBar, sev, staticmethod(boom))
        # All four must run without raising:
        getattr(feedback, f"toast_{sev}")(parent, "t", "c")


def test_position_uniform_across_severities(qapp, monkeypatch):
    """``TOP_RIGHT`` for all four — the reason feedback.py exists."""
    from doubi.ui import feedback
    from qfluentwidgets import InfoBar, InfoBarPosition

    positions = {}

    def make_fake(name):
        def fake(**kwargs):
            positions[name] = kwargs["position"]
        return fake

    for sev in ("success", "info", "warning", "error"):
        monkeypatch.setattr(InfoBar, sev, staticmethod(make_fake(sev)))

    feedback.toast_success(parent, "t", "c")
    feedback.toast_info   (parent, "t", "c")
    feedback.toast_warning(parent, "t", "c")
    feedback.toast_error  (parent, "t", "c")

    assert all(p == InfoBarPosition.TOP_RIGHT for p in positions.values()), positions
