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
