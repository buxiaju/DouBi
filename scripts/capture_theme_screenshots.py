"""Capture the main window under each built-in theme pack.

Run with::

    QT_QPA_PLATFORM=offscreen python scripts/capture_theme_screenshots.py

It is intentionally not wired into ``pyproject.toml``; it is a docs helper
used to refresh ``README.md`` screenshots after layout/theme changes.

What it does:

1. Boot a QApplication under the offscreen platform plugin.
2. Apply branding (application name + window icon) so the title bar shows
   the correct text and the ``setMicaEffectEnabled(False)`` in
   ``set_theme()`` has something to operate on.
3. For each theme in ``THEMES``, call ``set_theme(name)`` twice (matching
   ``ui/app.py``: once before the window exists so pages pick up tokens
   during construction, once after so the top-level window background is
   actually painted).
4. ``window.grab()`` to a ``QPixmap`` and save as PNG.

The output filenames match what ``README.md`` references; running this
script overwrites them.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# NOTE: we deliberately do NOT use the ``offscreen`` Qt platform plugin.
# On Windows, the offscreen plugin does not register any system fonts
# (``QFontDatabase.families()`` returns 0), so all CJK glyphs render as
# empty "tofu" boxes. Instead we run under the real ``windows`` plugin
# but move the window far off-screen and never show it — the user
# never sees anything, and the window manager never gets a chance to
# raise the taskbar entry. See ICONS.md §7 for related QtSvg-on-Windows
# quirks that informed this choice.
os.environ.pop("QT_QPA_PLATFORM", None)

# QT_SCALE_FACTOR stays at 1.0; on Windows the system DPI scaling
# already gives us 2x and the offscreen grab captures at 2200x1520,
# which is plenty sharp for the 720px-wide display in README.md.
# (Setting it to 1.5 here stacks with the OS scale factor and produces
# 3300x2280 PNGs that are wasteful for a doc screenshot.)
os.environ.pop("QT_SCALE_FACTOR", None)

REPO_ROOT = Path(__file__).resolve().parent.parent
SCREENSHOTS = REPO_ROOT / "screenshots"
SCREENSHOTS.mkdir(exist_ok=True)

# Make `doubi` importable without installing.
sys.path.insert(0, str(REPO_ROOT / "src"))


def main() -> int:
    from PySide6.QtCore import QSize, Qt
    from PySide6.QtGui import QFont, QFontDatabase, QPixmap
    from PySide6.QtWidgets import QApplication

    from doubi.ui.app import _apply_app_branding  # noqa: WPS433 - intentional private reuse
    from doubi.ui.main_window import build_main_window
    from doubi.ui.theme import set_theme, theme_names

    app = QApplication.instance() or QApplication(sys.argv)
    _apply_app_branding(app)

    # offscreen platform plugin does NOT inherit the Windows system font
    # fallback chain; without an explicit font, all CJK glyphs render as
    # "tofu" boxes. Pick the first CJK-capable font available on the host.
    cjk_candidates = [
        "Microsoft YaHei UI", "Microsoft YaHei",
        "微软雅黑", "PingFang SC", "Source Han Sans SC",
        "Noto Sans CJK SC", "WenQuanYi Micro Hei",
    ]
    available_families = set(QFontDatabase.families())
    chosen = next((f for f in cjk_candidates if f in available_families), None)
    if chosen is not None:
        base = QFont(chosen, 10)
        app.setFont(base)
        print(f"  font: {chosen} (of {len(available_families)} families)")
    else:
        print(f"  font: <no CJK font found; tofu expected>", file=sys.stderr)

    # Tuple order matches the README display order: the brand theme first,
    # then the two system defaults, then the two accent themes we use as
    # secondaries. Filenames are the ones already referenced in README.md.
    targets = [
        ("doubi", "01_doubi.png"),
        ("default_light", "02_default_light.png"),
        ("default_dark", "03_default_dark.png"),
        ("deep_sea", "04_deep_sea.png"),
        ("eye_care", "06_eye_care.png"),
    ]
    available = set(theme_names())
    for name, _ in targets:
        if name not in available:
            print(f"!! theme {name!r} not found, skipping", file=sys.stderr)

    # Build the window factory once; reuse it across themes. Pages pick up
    # tokens during construction so the theme MUST already be set here.
    MainWindow = build_main_window()

    for name, fname in targets:
        if name not in available:
            continue
        set_theme(name)
        window = MainWindow()
        # second set_theme: see ui/app.py docstring for why the call is duplicated
        set_theme(name)
        # Park the window off-screen so the user never sees it; without
        # ``show()`` the taskbar stays clean and the OS does not flash
        # an icon. ``grab()`` still works on a hidden window in Qt 6.
        window.setAttribute(Qt.WA_DontShowOnScreen, True)
        window.move(-32000, -32000)
        window.show()
        # Pump events so layout / qfluentwidgets widget customisation runs
        # before grab. Two passes is enough on every theme I've tried.
        for _ in range(3):
            app.processEvents()
        pixmap: QPixmap = window.grab()
        out = SCREENSHOTS / fname
        ok = pixmap.save(str(out), "PNG")
        size = out.stat().st_size if out.exists() else 0
        print(f"  {name:14s} -> {fname:24s} {pixmap.width()}x{pixmap.height()}  {size} bytes  ok={ok}")
        window.close()
        window.deleteLater()
        # Drain any pending events so the next window starts from a clean slate
        for _ in range(2):
            app.processEvents()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
