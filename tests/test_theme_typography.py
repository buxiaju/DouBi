"""0.3.4 — theme + typography pin tests.

We lock down two things:

* The 「豆比紫」 palette is the *re-tuned* blue-gray with amber accent.
  ``accent_strong`` + ``bg_base`` etc. are spelled out so a future edit
  can't quietly revert the 0.3.3「深紫 + 琥珀」 combination that the
  user rejected.

* The typography scale (TYPE_H1..TYPE_TINY) has the bumped sizes.
  These constants are imported by Qt, not Python-level constants — so the
  tests import the module and read the attributes, no Qt event loop
  needed.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def test_doubi_theme_palette_is_re_tuned():
    """0.3.4 — accent from #f59e6a (amber) → #5b8cd6 (blue-gray).

    The amber accent only reappears for ``status_running`` /
    ``progress_normal`` to keep the「进行中」 visual anchor; everything
    else drifts away from amber into the blue-gray family.
    """
    from doubi.ui.theme import THEMES

    pack = THEMES["doubi"]
    assert pack.label == "豆比紫"
    # 主色由琥珀换成中性蓝
    assert pack.accent == "#5b8cd6"
    assert pack.accent_strong == "#7aa4e1"
    # 背景从深邃紫换成中性蓝灰
    assert pack.tokens["bg_base"] == "#1a2030"
    assert pack.tokens["bg_layer"] == "#212a3c"
    assert pack.tokens["bg_hover"] == "#2c3650"
    # 文字色：偏冷的白 + 略提亮的中性 muted
    assert pack.tokens["text_primary"] == "#f0f4fa"
    assert pack.tokens["text_muted"] == "#8d9bb0"
    # status_running 仍保留琥珀：这是「进行中」的视觉锚点
    assert pack.tokens["status_running_fg"] == "#f59e6a"
    assert pack.tokens["progress_normal"] == "#f59e6a"


def test_typography_scale_is_bumped():
    """0.3.4 — TYPE_BODY 13→14, TYPE_CAPTION 12→13, TYPE_H1 22→26."""
    from doubi.ui import theme

    assert theme.TYPE_H1 == 26
    assert theme.TYPE_H2 == 18
    assert theme.TYPE_H3 == 17
    assert theme.TYPE_BODY == 14
    assert theme.TYPE_CAPTION == 13
    assert theme.TYPE_TINY == 12


def test_heading_qss_uses_700_weight():
    """0.3.4 — H1/H2 用 weight 700（旧 600）；H3 用 600（旧 500）。"""
    from doubi.ui.theme import heading_qss

    h1 = heading_qss(1)
    h2 = heading_qss(2)
    h3 = heading_qss(3)
    assert "font-weight: 700" in h1
    assert "font-weight: 700" in h2
    assert "font-weight: 600" in h3
    assert "26px" in h1
    assert "18px" in h2
    assert "17px" in h3


def test_body_qss_uses_500_weight():
    """0.3.4 — 正文 / 次级说明统一 500（默认 400 让字看着糊）。"""
    from doubi.ui.theme import body_qss, muted_qss

    assert "font-weight: 500" in body_qss()
    assert "font-weight: 500" in muted_qss()


def test_font_family_prefers_yahei_ui():
    """0.3.4 — 中文首选 Microsoft YaHei UI（Windows 渲染稳），不再是 PingFang。"""
    from doubi.ui.theme import FONT_FAMILY

    # YaHei UI 必须在 PingFang SC 之前出现。
    assert FONT_FAMILY.index("Microsoft YaHei UI") < FONT_FAMILY.index("PingFang SC")