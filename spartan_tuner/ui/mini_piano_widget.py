from __future__ import annotations

from PyQt6.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QWidget


class MiniPianoWidget(QWidget):
    noteChanged = pyqtSignal(str)

    _SHARP_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    _FLAT_NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
    _NAME_TO_PC = {
        "C": 0,
        "B#": 0,
        "C#": 1,
        "DB": 1,
        "D": 2,
        "D#": 3,
        "EB": 3,
        "E": 4,
        "FB": 4,
        "E#": 5,
        "F": 5,
        "F#": 6,
        "GB": 6,
        "G": 7,
        "G#": 8,
        "AB": 8,
        "A": 9,
        "A#": 10,
        "BB": 10,
        "B": 11,
        "CB": 11,
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._selected_pc = 0
        self._notation_mode = "sharps"
        self._theme = {
            "accent": "#33CED6",
            "panel": "#404040",
            "highlight": "#6B999F",
            "text": "#ffffff",
        }
        self._white_key_rects: list[tuple[int, QRectF]] = []
        self._black_key_rects: list[tuple[int, QRectF]] = []
        self.setFixedHeight(46)
        self.setMinimumWidth(180)

    def sizeHint(self) -> QSize:
        return QSize(230, 46)

    def minimumSizeHint(self) -> QSize:
        return QSize(160, 40)

    def apply_theme(self, theme_dict: dict) -> None:
        if isinstance(theme_dict, dict):
            for key in ("accent", "panel", "highlight", "text"):
                value = theme_dict.get(key)
                if value is not None:
                    self._theme[str(key)] = str(value)
        self.update()

    def setNotationMode(self, mode: str) -> None:
        mode_str = str(mode or "").strip().lower()
        self._notation_mode = "flats" if mode_str == "flats" else "sharps"
        self.update()

    def setNote(self, note: str) -> None:
        pc = self._note_to_pc(note)
        if pc is None:
            return
        self._selected_pc = int(pc)
        self.update()

    def _note_to_pc(self, note: str) -> int | None:
        if note is None:
            return None
        s = str(note).strip()
        if not s:
            return None
        mapped = self._NAME_TO_PC.get(s.upper())
        if mapped is not None:
            return int(mapped)
        return None

    def _pc_to_name(self, pc: int) -> str:
        idx = int(pc) % 12
        if self._notation_mode == "flats":
            return self._FLAT_NAMES[idx]
        return self._SHARP_NAMES[idx]

    def _rebuild_key_geometry(self) -> tuple[QRectF, float, float]:
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if r.width() <= 2.0 or r.height() <= 2.0:
            self._white_key_rects = []
            self._black_key_rects = []
            return r, 0.0, 0.0

        white_w = r.width() / 7.0
        black_w = white_w * 0.62
        black_h = r.height() * 0.62

        white_pcs = [0, 2, 4, 5, 7, 9, 11]
        self._white_key_rects = []
        for i, pc in enumerate(white_pcs):
            x = r.left() + (i * white_w)
            key_rect = QRectF(x, r.top(), white_w, r.height())
            self._white_key_rects.append((pc, key_rect))

        black_offsets = {1: 1, 3: 2, 6: 4, 8: 5, 10: 6}
        self._black_key_rects = []
        for pc, anchor in black_offsets.items():
            x = r.left() + (anchor * white_w) - (black_w / 2.0)
            key_rect = QRectF(x, r.top(), black_w, black_h)
            self._black_key_rects.append((pc, key_rect))

        return r, white_w, black_h

    def paintEvent(self, event) -> None:
        _ = event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        panel = QColor(str(self._theme.get("panel", "#404040")))
        accent = QColor(str(self._theme.get("accent", "#33CED6")))
        border = QColor(str(self._theme.get("highlight", "#6B999F")))

        if not panel.isValid():
            panel = QColor("#404040")
        if not accent.isValid():
            accent = QColor("#33CED6")
        if not border.isValid():
            border = QColor("#6B999F")

        outer, _white_w, _black_h = self._rebuild_key_geometry()
        painter.fillRect(outer, panel)

        white_fill = QColor("#F7F8F8")
        white_selected = QColor(accent)
        white_selected = white_selected.lighter(145)
        key_border = QColor("#202020")

        painter.setPen(QPen(key_border, 1.0))
        for pc, rect in self._white_key_rects:
            fill = white_selected if int(pc) == int(self._selected_pc) else white_fill
            painter.setBrush(fill)
            painter.drawRect(rect)

        black_fill = QColor("#26282B")
        black_selected = QColor(accent)
        black_selected = black_selected.darker(120)
        painter.setPen(QPen(QColor("#111111"), 1.0))
        for pc, rect in self._black_key_rects:
            fill = black_selected if int(pc) == int(self._selected_pc) else black_fill
            painter.setBrush(fill)
            painter.drawRoundedRect(rect, 2.0, 2.0)

        painter.setPen(QPen(border, 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(outer, 3.0, 3.0)

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)

        pos = event.position()

        chosen_pc = None
        for pc, rect in self._black_key_rects:
            if rect.contains(pos):
                chosen_pc = int(pc)
                break

        if chosen_pc is None:
            for pc, rect in self._white_key_rects:
                if rect.contains(pos):
                    chosen_pc = int(pc)
                    break

        if chosen_pc is not None and int(chosen_pc) != int(self._selected_pc):
            self._selected_pc = int(chosen_pc)
            self.update()
            self.noteChanged.emit(self._pc_to_name(self._selected_pc))

        event.accept()
