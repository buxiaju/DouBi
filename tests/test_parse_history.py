"""解析历史（最近解析的链接一键回填）。

行为契约：

* 解析触发时把 URL 记进 config 的 ``extra["recent_parse_urls"]``
  （去重、新者居前、最多 8 条）并落盘；
* 「最近解析」行按 config 当前值渲染，点击条目回填输入框；
* config 没有 extra 字典 / 坏数据时静默当空，不影响解析主流程。

注意：**剪贴板监听在 parse 页早已存在**（``_poll_clipboard``，1.5s
轮询、只认具体平台、防打断），本文件不重复测它。
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
        import qfluentwidgets  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        pytest.skip(f"GUI deps not installed: {exc}")


@pytest.fixture(scope="module")
def qapp():
    _require_gui()
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture()
def page(qapp, monkeypatch, tmp_path):
    """构造一个配置写进 tmp_path 的解析页。

    monkeypatch 必须先于 build（与 test_settings_autosave 同一条坑：
    build 时才解析 DEFAULT_CONFIG_PATH，顺序反了会写用户真实配置）。
    """
    _require_gui()
    import doubi.core.config as cfg_mod
    monkeypatch.setattr(cfg_mod, "DEFAULT_CONFIG_PATH", tmp_path / "config.yml")
    from doubi.ui.pages.parse import build_parse_widgets
    cls, _ = build_parse_widgets()
    page = cls()
    # extra 字典指向被测配置的内存态
    page._cfg.extra = {}
    return page


def _recent_links(page) -> list:
    """收集「最近解析」行的链接按钮文本。"""
    layout = page.recent_links_layout
    return [layout.itemAt(i).widget().text()
            for i in range(layout.count())
            if layout.itemAt(i).widget() is not None]


def test_record_dedupes_and_truncates(page, qapp):
    urls = [f"https://www.bilibili.com/video/BV{i:05d}" for i in range(10)]
    page._record_recent_parse(urls[:3])
    page._record_recent_parse(urls[3:6])
    # 重复记录同一条：挪到最前而不是重复出现
    page._record_recent_parse([urls[4]])

    recent = page._recent_parse_load()
    assert len(recent) <= page.RECENT_PARSE_MAX
    assert recent[0] == urls[4]
    assert recent.count(urls[4]) == 1


def test_record_persists_to_config_file(page, qapp, monkeypatch, tmp_path):
    import yaml
    cfg_path = tmp_path / "config.yml"
    page._record_recent_parse(["https://www.douyin.com/video/123"])
    assert cfg_path.exists()
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    # extra 经 to_dict() 摊平进配置文件
    assert "https://www.douyin.com/video/123" in str(data)


def test_recent_row_hidden_when_empty(page, qapp):
    assert page.recent_row.isHidden()


def test_recent_row_shows_after_record(page, qapp):
    page._record_recent_parse([
        "https://www.bilibili.com/video/BV1GJ411x7h7?share_source=copy",
    ])
    assert not page.recent_row.isHidden()
    links = _recent_links(page)
    assert len(links) == 1
    # 显示压缩：协议 / 查询串剥掉
    assert links[0].startswith("www.bilibili.com")
    assert "share_source" not in links[0]


def test_click_fills_input(page, qapp):
    url = "https://www.bilibili.com/video/BV1GJ411x7h7"
    page._record_recent_parse([url])
    link = page.recent_links_layout.itemAt(0).widget()
    link.click()
    assert page.url_input.toPlainText() == url


def test_corrupt_extra_is_tolerated(page, qapp):
    """extra 不是 dict / 值不是 list 时静默当空，不炸解析页。"""
    page._cfg.extra = None
    assert page._recent_parse_load() == []
    page._cfg.extra = {"recent_parse_urls": "garbage"}
    assert page._recent_parse_load() == []
    page._cfg.extra = {"recent_parse_urls": [1, None, "https://x/1", ""]}
    assert page._recent_parse_load() == ["https://x/1"]
