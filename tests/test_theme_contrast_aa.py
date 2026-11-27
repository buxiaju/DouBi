"""WCAG AA 对比度守护——把 UI_DESIGN.md §5 的文档承诺变成测试事实。

``UI_DESIGN.md`` 声称 ``muted_qss()``「在每个主题下都重新计算对比度，
保证 WCAG AA（4.5:1 文本对比度）」。但在 2026-11-27 之前这只是文档
承诺：三个亮色主题的 ``text_muted`` 实测只有 3.11 / 2.79 / 3.17:1。

本文件是纯数学守护：不 import Qt、不开 QApplication，直接按 WCAG 2.x
的相对亮度公式算每套主题的（前景, 背景）对比度。任何未来新增主题或
改动 ``text_muted`` / 背景色的编辑，低于 AA 线当场红掉。

口径：

* 正文 / 次级说明字号（TYPE_BODY 14px / TYPE_CAPTION 13px）不属于
  WCAG「large text」（≥18pt 或 ≥14pt bold），统一按 4.5:1 口径。
* ``text_muted`` 同时对 ``bg_base`` 与 ``bg_layer`` 验证——muted 文字
  既出现在窗口底色上（页面副标题）也出现在卡片上（分组副标题）。
* ``text_primary`` 按 7:1（AAA）验证——它是正文主色，理应远超 AA。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


AA = 4.5   # WCAG AA：normal text
AAA = 7.0  # WCAG AAA：normal text


def _relative_luminance(hex_color: str) -> float:
    """WCAG 2.x 相对亮度。只接受 ``#rrggbb``（主题包内统一六位 hex）。"""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        raise ValueError(f"not a 6-digit hex color: {hex_color!r}")
    rgb = [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]

    def _linear(channel: float) -> float:
        return channel / 12.92 if channel <= 0.04045 else (
            (channel + 0.055) / 1.055
        ) ** 2.4

    r, g, b = (_linear(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(fg: str, bg: str) -> float:
    lo = _relative_luminance(fg)
    hi = _relative_luminance(bg)
    lower, upper = min(lo, hi), max(lo, hi)
    return (upper + 0.05) / (lower + 0.05)


def test_all_theme_packs_exposed():
    """守卫前提：THEMES 可离线导入（本模块不依赖 Qt，若此测试挂了
    说明 theme.py 引入了 Qt 顶层依赖，是另一类回归）。"""
    from doubi.ui.theme import THEMES

    assert len(THEMES) == 7


@pytest.mark.parametrize("theme_key", [
    "default_light", "default_dark", "doubi", "deep_sea",
    "morandi", "eye_care", "high_contrast",
])
def test_theme_text_muted_meets_aa(theme_key: str):
    """text_muted 对 bg_base / bg_layer 都要 ≥ 4.5:1（WCAG AA）。

    2026-11-27 修的历史值（供回溯）：
    default_light #8a8a8a→#6b6b6b、morandi #948b80→#6f665b、
    eye_care #8b8874→#6d6a58。暗色主题本来就达标，一并锁进测试。
    """
    from doubi.ui.theme import THEMES

    tokens = THEMES[theme_key].tokens
    muted = tokens["text_muted"]
    for bg_key in ("bg_base", "bg_layer"):
        ratio = _contrast(muted, tokens[bg_key])
        assert ratio >= AA, (
            f"{theme_key}: text_muted({muted}) on {bg_key}"
            f"({tokens[bg_key]}) = {ratio:.2f}:1 < {AA}:1"
        )


@pytest.mark.parametrize("theme_key", [
    "default_light", "default_dark", "doubi", "deep_sea",
    "morandi", "eye_care", "high_contrast",
])
def test_theme_text_primary_meets_aaa(theme_key: str):
    """text_primary 是正文主色，按 AAA（7:1）锁——给未来的调色留足余量。"""
    from doubi.ui.theme import THEMES

    tokens = THEMES[theme_key].tokens
    ratio = _contrast(tokens["text_primary"], tokens["bg_base"])
    assert ratio >= AAA, (
        f"{theme_key}: text_primary({tokens['text_primary']}) on "
        f"bg_base({tokens['bg_base']}) = {ratio:.2f}:1 < {AAA}:1"
    )
