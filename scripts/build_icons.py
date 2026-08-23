"""从 SVG 模板重新生成图标位图产物。

用法（项目根目录）::

    python scripts/build_icons.py            # 重建 icon.png
    python scripts/build_icons.py --preview  # 额外导出各主题预览图

产物：

* ``src/doubi/ui/resources/icon.png`` —— 1024×1024 品牌色位图。
  运行时只在 QtSvg 不可用时兜底，同时供打包器（PyInstaller / 图标转换）取用。
* ``screenshots/icon_themes.png`` —— ``--preview`` 时生成的主题对照图，
  用来肉眼确认换色结果，不参与运行时。

脚本刻意不写 ``.ico``：Windows 打包时由 PyInstaller 从 PNG 生成，
多存一份二进制只会增加漂移风险。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

PNG_SIZE = 1024
PREVIEW_TILE = 160
PREVIEW_PAD = 20


def _build_png(out: Path) -> None:
    from doubi.ui.resources import render_icon_pixmap

    pix = render_icon_pixmap(PNG_SIZE, themed=False)
    if pix is None:
        raise SystemExit("渲染失败：QtSvg 不可用或模板缺失")
    out.parent.mkdir(parents=True, exist_ok=True)
    if not pix.save(str(out), "PNG"):
        raise SystemExit(f"写入失败：{out}")
    print(f"✓ {out.relative_to(ROOT)}  {PNG_SIZE}×{PNG_SIZE}")


def _build_preview(out: Path) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QFont, QImage, QPainter

    from doubi.ui.resources import render_icon_pixmap
    from doubi.ui.theme import THEMES

    packs = list(THEMES.values())
    label_h = 26
    cell_w = PREVIEW_TILE + PREVIEW_PAD * 2
    cell_h = PREVIEW_TILE + PREVIEW_PAD * 2 + label_h
    img = QImage(cell_w * len(packs), cell_h, QImage.Format_ARGB32)
    img.fill(QColor("#12121a"))

    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing, True)
    font = QFont()
    font.setPointSize(10)
    painter.setFont(font)

    for i, pack in enumerate(packs):
        accent = None if pack.name == "doubi" else pack.accent
        pix = render_icon_pixmap(PREVIEW_TILE, accent, themed=False)
        x = i * cell_w
        if pix is not None:
            painter.drawPixmap(x + PREVIEW_PAD, PREVIEW_PAD, pix)
        painter.setPen(QColor("#e8e4f0"))
        painter.drawText(
            x, PREVIEW_TILE + PREVIEW_PAD * 2, cell_w, label_h,
            Qt.AlignCenter, f"{pack.label}",
        )
    painter.end()

    out.parent.mkdir(parents=True, exist_ok=True)
    if not img.save(str(out), "PNG"):
        raise SystemExit(f"写入失败：{out}")
    print(f"✓ {out.relative_to(ROOT)}  {img.width()}×{img.height()}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--preview", action="store_true", help="额外导出各主题图标对照图",
    )
    args = parser.parse_args()

    # Windows 控制台默认 GBK，输出里的 ✓ / × 会直接抛 UnicodeEncodeError
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):  # pragma: no cover - 非交互管道
        pass

    # QPixmap 需要 QGuiApplication；用 offscreen 平台避免弹窗
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication.instance() or QGuiApplication(sys.argv)

    _build_png(ROOT / "src" / "doubi" / "ui" / "resources" / "icon.png")
    if args.preview:
        _build_preview(ROOT / "screenshots" / "icon_themes.png")

    del app


if __name__ == "__main__":
    main()
