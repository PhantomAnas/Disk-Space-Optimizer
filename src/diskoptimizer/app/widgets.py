"""Reusable pieces: wallpaper backdrop, glass card, pill buttons, filter chips, size bars."""

from __future__ import annotations

import os
import random

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPixmap, QRadialGradient
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QStyledItemDelegate, QVBoxLayout, QWidget

from . import icons


def generate_wallpaper(width: int, height: int, seed: int = 5) -> QPixmap:
    """A soft, dark wallpaper: gradient base plus blurred colour blobs."""
    pm = QPixmap(max(16, width), max(16, height))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    base = QLinearGradient(0, 0, width, height)
    base.setColorAt(0.0, QColor("#0f172a"))
    base.setColorAt(0.5, QColor("#111827"))
    base.setColorAt(1.0, QColor("#1e1b4b"))
    p.fillRect(pm.rect(), QBrush(base))
    rng = random.Random(seed)
    palette = ["#0ea5e9", "#6366f1", "#14b8a6", "#8b5cf6", "#22c55e", "#f59e0b"]
    for i in range(6):
        cx, cy = rng.uniform(0, width), rng.uniform(0, height)
        r = rng.uniform(0.25, 0.55) * max(width, height)
        g = QRadialGradient(cx, cy, r)
        c = QColor(palette[i % len(palette)])
        c.setAlphaF(0.26)
        g.setColorAt(0.0, c)
        c2 = QColor(c)
        c2.setAlphaF(0.0)
        g.setColorAt(1.0, c2)
        p.setBrush(QBrush(g))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(int(cx - r), int(cy - r), int(2 * r), int(2 * r))
    p.end()
    return pm


class Backdrop(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._source: QPixmap | None = None
        self._scaled: QPixmap | None = None
        self.setAutoFillBackground(False)

    def set_image(self, path: str | None) -> bool:
        if path and os.path.isfile(path):
            pm = QPixmap(path)
            if not pm.isNull():
                self._source, self._scaled = pm, None
                self.update()
                return True
        self._source, self._scaled = None, None
        self.update()
        return False

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        w, h = self.width(), self.height()
        if self._source is None:
            if self._scaled is None or self._scaled.size() != self.size():
                self._scaled = generate_wallpaper(w, h)
            p.drawPixmap(0, 0, self._scaled)
        else:
            if self._scaled is None or self._scaled.size() != self.size():
                scaled = self._source.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                             Qt.TransformationMode.SmoothTransformation)
                self._scaled = scaled.copy((scaled.width() - w) // 2, (scaled.height() - h) // 2, w, h)
            p.drawPixmap(0, 0, self._scaled)
            p.fillRect(self.rect(), QColor(0, 0, 0, 90))
        p.end()


class GlassCard(QFrame):
    def __init__(self, title: str | None = None, icon_name: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(18, 16, 18, 18)
        self.body.setSpacing(12)
        self.head = QHBoxLayout()
        if title:
            self.head.setSpacing(8)
            if icon_name:
                ic = QLabel()
                ic.setPixmap(icons.pixmap(icon_name, 18, "#ffffff", dpr=self.devicePixelRatioF()))
                self.head.addWidget(ic)
            lbl = QLabel(title)
            lbl.setObjectName("CardTitle")
            self.head.addWidget(lbl)
            self.head.addStretch(1)
            self.body.addLayout(self.head)


def pill(text: str, icon_name: str | None = None, kind: str = "", tooltip: str = "") -> QPushButton:
    b = QPushButton(text)
    if icon_name:
        color = "#06230f" if kind == "Go" else "#ffffff"
        b.setIcon(icons.icon(icon_name, color, filled=(icon_name == "play")))
        b.setIconSize(icons.ICON_SIZE)
    if kind:
        b.setObjectName(kind)
    if tooltip:
        b.setToolTip(tooltip)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


def round_button(icon_name: str, tooltip: str = "") -> QPushButton:
    b = QPushButton()
    b.setObjectName("Round")
    b.setIcon(icons.icon(icon_name))
    b.setIconSize(QSize(18, 18))
    b.setToolTip(tooltip)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


def hint(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("Hint")
    lbl.setWordWrap(True)
    return lbl


class Chips(QFrame):
    """A row of toggle chips.  `changed(set)` emits the selected keys (empty = all)."""

    changed = Signal(set)

    def __init__(self, options: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self._buttons: dict[str, QPushButton] = {}
        self.all_btn = QPushButton("All")
        self.all_btn.setObjectName("Chip")
        self.all_btn.setCheckable(True)
        self.all_btn.setChecked(True)
        self.all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.all_btn.clicked.connect(self._all)
        lay.addWidget(self.all_btn)
        for key in options:
            b = QPushButton(key.replace("&", "&&"))      # a bare & would become a mnemonic
            b.setObjectName("Chip")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(self._one)
            lay.addWidget(b)
            self._buttons[key] = b
        lay.addStretch(1)

    def _all(self) -> None:
        for b in self._buttons.values():
            b.setChecked(False)
        self.all_btn.setChecked(True)
        self.changed.emit(set())

    def _one(self) -> None:
        sel = self.value()
        self.all_btn.setChecked(not sel)
        self.changed.emit(sel)

    def value(self) -> set[str]:
        return {k for k, b in self._buttons.items() if b.isChecked()}

    def set_value(self, keys) -> None:
        keys = set(keys or ())
        for k, b in self._buttons.items():
            b.setChecked(k in keys)
        self.all_btn.setChecked(not keys)


class SizeBarDelegate(QStyledItemDelegate):
    """Draws the size cell as text over a proportional bar.  The item's
    UserRole holds the fraction 0..1."""

    def paint(self, painter, option, index) -> None:  # noqa: N802
        frac = index.data(Qt.ItemDataRole.UserRole)
        painter.save()
        r = option.rect.adjusted(6, 5, -6, -5)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 18))
        painter.drawRoundedRect(QRectF(r), 5, 5)
        if isinstance(frac, (int, float)) and frac > 0:
            w = max(4, int(r.width() * min(1.0, float(frac))))
            bar = QRectF(r.x(), r.y(), w, r.height())
            g = QLinearGradient(bar.topLeft(), bar.topRight())
            g.setColorAt(0, QColor("#0ea5e9"))
            g.setColorAt(1, QColor("#6366f1"))
            painter.setBrush(QBrush(g))
            painter.drawRoundedRect(bar, 5, 5)
        painter.setPen(QColor("#f5f5f7"))
        painter.drawText(option.rect.adjusted(12, 0, -12, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                         str(index.data(Qt.ItemDataRole.DisplayRole) or ""))
        painter.restore()
