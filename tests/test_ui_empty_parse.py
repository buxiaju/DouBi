"""Tests for the M5.2 parse page empty-parse UX.

PySide6 + qfluentwidgets are real deps for the GUI; we run under
``QT_QPA_PLATFORM=offscreen`` so this file works in any headless CI.

M5.4: the parse + empty-parse hints moved to the new ParsePage
(``doubi.ui.pages.parse``); the DownloadPage is now a pure task
manager and no longer holds ``_classify_login_required`` /
``_empty_parse_message``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Force Qt to render off-screen so the test never needs a display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _require_gui() -> None:
    try:
        import PySide6  # noqa: F401
    except ImportError as exc:   # pragma: no cover
        pytest.skip(f"PySide6 not installed: {exc}")


@pytest.fixture(scope="module")
def qapp():
    _require_gui()
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


def _make_page(qapp):
    from doubi.ui.pages.parse import build_parse_widgets
    cls, _ = build_parse_widgets()
    return cls()


def test_classify_login_required_returns_label_for_favlist(qapp):
    page = _make_page(qapp)
    assert page._classify_login_required(
        "https://www.bilibili.com/favlist?fid=12345"
    ) == "收藏夹"


def test_classify_login_required_returns_label_for_watchlater(qapp):
    page = _make_page(qapp)
    assert page._classify_login_required(
        "https://www.bilibili.com/watchlater"
    ) == "稍后再看"


def test_classify_login_required_returns_label_for_space(qapp):
    page = _make_page(qapp)
    assert page._classify_login_required(
        "https://space.bilibili.com/123456"
    ) == "UP 主空间"


def test_classify_login_required_returns_label_for_mix(qapp):
    page = _make_page(qapp)
    assert page._classify_login_required(
        "https://www.bilibili.com/list/ml12345"
    ) == "合集"


def test_classify_login_required_returns_none_for_douyin(qapp):
    page = _make_page(qapp)
    assert page._classify_login_required(
        "https://www.douyin.com/video/7123456789012345678"
    ) is None


def test_build_options_forwards_sidecar_switches_and_resume(qapp):
    """The GUI must honour the same switches as the CLI and REST surfaces.

    The engine reads these off ``DownloadOptions``, never off ``AppConfig``,
    so a field that ``_build_options`` forgets is a switch that silently does
    nothing in the GUI — which is exactly how ``write_nfo`` / ``write_danmaku``
    / ``write_subtitles`` / ``resume`` were dead here at first.
    """
    from doubi.core.config import AppConfig

    page = _make_page(qapp)
    cfg = AppConfig()
    cfg.write_nfo = True
    cfg.write_danmaku = True
    cfg.write_subtitles = True
    cfg.resume = False
    page._cfg = cfg

    options = page._build_options()
    assert options.write_nfo is True
    assert options.write_danmaku is True
    assert options.write_subtitles is True
    assert options.resume is False


def test_build_options_covers_every_shared_config_field(qapp):
    """Guard against the *next* added field being forgotten here.

    Rather than listing today's fields, this compares the names that
    ``AppConfig`` and ``DownloadOptions`` have in common and asserts the GUI
    actually propagates each one. Adding a switch to both dataclasses without
    wiring the GUI will fail this test instead of shipping a dead control.

    Every field is first set to a value *away from its default*: a pristine
    ``AppConfig()`` would compare equal to an un-forwarded option simply
    because both dataclasses declare the same default, which is how this
    check would quietly pass while ``resume`` was in fact dropped (verified
    by removing the line and watching this test go red).
    """
    import dataclasses

    from doubi.core.config import AppConfig
    from doubi.core.models import DownloadOptions

    cfg_names = {f.name for f in dataclasses.fields(AppConfig)}
    opt_names = {f.name for f in dataclasses.fields(DownloadOptions)}
    shared = cfg_names & opt_names
    # ``database`` is intentionally reshaped (bool -> path or None) and
    # ``extra`` is a config-only bag, so neither is a plain hand-off.
    shared -= {"database", "extra"}
    assert shared, "sanity: the two dataclasses must overlap"

    cfg = AppConfig()
    for name in shared:
        current = getattr(cfg, name)
        if isinstance(current, bool):
            setattr(cfg, name, not current)
        elif isinstance(current, str):
            setattr(cfg, name, current + "_probe")
        elif isinstance(current, Path):
            setattr(cfg, name, current / "probe")
        elif current is None:
            setattr(cfg, name, "probe")
        else:
            # An unhandled type would silently weaken the check.
            pytest.fail(f"extend this test for {name}: {type(current)!r}")

    page = _make_page(qapp)
    page._cfg = cfg
    options = page._build_options()

    missing = [
        name for name in sorted(shared)
        if getattr(options, name) != getattr(cfg, name)
    ]
    assert not missing, f"_build_options drops config fields: {missing}"


def test_classify_login_required_returns_none_for_single_video(qapp):
    page = _make_page(qapp)
    assert page._classify_login_required(
        "https://www.bilibili.com/video/BV1GJ411x7h7"
    ) is None


def test_empty_parse_message_only_login_required(qapp):
    """All URLs are B 站 containers that need login → focused message."""
    page = _make_page(qapp)
    per_url = [
        ("https://space.bilibili.com/123", []),
        ("https://www.bilibili.com/favlist?fid=99", []),
    ]
    title, content = page._empty_parse_message(per_url)
    assert "需要登录" in title
    assert "UP 主空间" in content
    assert "收藏夹" in content
    assert "doubi" in content   # cookie path is mentioned
    assert "auth bilibili" in content


def test_empty_parse_message_mixed_login_and_other(qapp):
    page = _make_page(qapp)
    per_url = [
        ("https://space.bilibili.com/123", []),
        ("https://www.bilibili.com/video/BV1", []),  # not a container
    ]
    title, content = page._empty_parse_message(per_url)
    assert "部分链接需要登录" in title
    assert "需要登录" in content
    assert "其他链接" in content
    assert "https://www.bilibili.com/video/BV1" in content


def test_empty_parse_message_no_login_required(qapp):
    page = _make_page(qapp)
    per_url = [
        ("https://www.bilibili.com/video/BV1", []),
    ]
    title, content = page._empty_parse_message(per_url)
    assert title == "解析结果为空"
    assert "请检查链接" in content
