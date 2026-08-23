"""把矢量 SVG 渲染成 .ico（Windows 应用图标资源）。

手写 ICONDIR / ICONDIRENTRY，不依赖 Pillow。
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

ICO_SIZES = (16, 32, 48, 64, 128, 256)


def _render_png_bytes(size: int) -> bytes:
    from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    from doubi.ui.resources import icon_svg

    markup = icon_svg(accent=None)
    if not markup:
        raise SystemExit("图标模板不可用")
    renderer = QSvgRenderer(QByteArray(markup.encode("utf-8")))

    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    try:
        renderer.render(painter)
    finally:
        painter.end()

    # 走 QImage.save 而不是 QPixmap.save——offscreen 平台下
    # QPixmap.save(QBuffer, "PNG") 会触发 STATUS_STACK_BUFFER_OVERRUN。
    buf = QByteArray()
    dev = QBuffer(buf)
    dev.open(QIODevice.WriteOnly)
    img.save(dev, "PNG")
    dev.close()
    return bytes(buf)


def build_ico(out: Path) -> None:
    pngs = [(s, _render_png_bytes(s)) for s in ICO_SIZES]
    print(f"rendered {len(pngs)} frames", flush=True)

    header = struct.pack("<HHH", 0, 1, len(pngs))
    dir_size = 6 + 16 * len(pngs)
    entries = b""
    image_data = b""
    offset = dir_size
    for size, png in pngs:
        entries += struct.pack(
            "<BBBBHHII",
            0 if size >= 256 else size,
            0 if size >= 256 else size,
            0, 0, 1, 32,
            len(png),
            offset,
        )
        image_data += png
        offset += len(png)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(header + entries + image_data)
    print(f"{out.name}  sizes={ICO_SIZES}  total={out.stat().st_size} bytes", flush=True)


if __name__ == "__main__":
    out = ROOT / "src" / "doubi" / "ui" / "resources" / "icon.ico"
    build_ico(out)
