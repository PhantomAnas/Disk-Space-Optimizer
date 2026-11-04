"""Generate the app icon (PNG + ICO) with Qt only:  python scripts/make_icon.py"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "diskoptimizer", "assets")


def draw(size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size
    tile = QPainterPath()
    tile.addRoundedRect(QRectF(0, 0, s, s), s * 0.22, s * 0.22)
    g = QLinearGradient(0, 0, s, s)
    g.setColorAt(0, QColor("#0ea5e9"))
    g.setColorAt(1, QColor("#6366f1"))
    p.fillPath(tile, g)
    # A disc (drive platter) with a usage arc
    p.setPen(QPen(QColor(255, 255, 255, 70), s * 0.09))
    p.setBrush(Qt.BrushStyle.NoBrush)
    r = QRectF(s * 0.22, s * 0.22, s * 0.56, s * 0.56)
    p.drawEllipse(r)
    p.setPen(QPen(QColor("#ffffff"), s * 0.09, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawArc(r, 90 * 16, -250 * 16)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#ffffff"))
    p.drawEllipse(QRectF(s * 0.44, s * 0.44, s * 0.12, s * 0.12))
    # Small broom-like sparkle at bottom right
    p.setBrush(QColor("#ffd60a"))
    star = QPainterPath()
    cx, cy, k = s * 0.8, s * 0.8, s * 0.07
    star.moveTo(cx, cy - k); star.lineTo(cx + k * 0.35, cy - k * 0.35); star.lineTo(cx + k, cy)
    star.lineTo(cx + k * 0.35, cy + k * 0.35); star.lineTo(cx, cy + k); star.lineTo(cx - k * 0.35, cy + k * 0.35)
    star.lineTo(cx - k, cy); star.lineTo(cx - k * 0.35, cy - k * 0.35); star.closeSubpath()
    p.fillPath(star, QColor("#ffd60a"))
    p.end()
    return img


def main() -> None:
    QGuiApplication(sys.argv)
    os.makedirs(OUT, exist_ok=True)
    draw(256).save(os.path.join(OUT, "icon.png"))
    draw(256).save(os.path.join(OUT, "icon.ico"), "ICO")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
