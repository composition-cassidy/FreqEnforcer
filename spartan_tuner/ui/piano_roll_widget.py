from PyQt6.QtWidgets import QWidget
from PyQt6.QtGui import QPainter, QColor, QFont, QPen
from PyQt6.QtCore import Qt

from utils.note_utils import note_name_to_midi


class PianoRollWidget(QWidget):
    """
    Vertical piano roll display showing keys from C2 to B7.
    Highlights the currently selected note.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self.selected_note = "C4"
        self.selected_octave = 4
        self.display_octave = 4

        self._selected_midi = None
        self._midi_range = (48, 72)

        self.note_names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
        self.white_notes = ["C", "D", "E", "F", "G", "A", "B"]
        self.black_notes = ["C#", "D#", "F#", "G#", "A#"]

        self.key_height = 20
        self.white_key_width = 40
        self.black_key_width = 25

        self.setMinimumWidth(50)
        self.setMinimumHeight(200)

    def set_selected_note(self, note_name: str):
        """Set the currently selected/highlighted note. E.g., 'C4', 'F#3'."""
        self.selected_note = note_name
        if note_name and note_name[-1].isdigit():
            try:
                self.selected_octave = int(note_name[-1])
            except ValueError:
                pass

        try:
            self._selected_midi = int(note_name_to_midi(note_name))
        except Exception:
            self._selected_midi = None
        self.update()

    def set_midi_range(self, midi_min: float, midi_max: float):
        lo = float(midi_min)
        hi = float(midi_max)
        if hi < lo:
            lo, hi = hi, lo

        lo_i = int(lo)
        hi_i = int(hi)
        if lo_i == hi_i:
            hi_i = lo_i + 1

        if (lo_i, hi_i) == self._midi_range:
            return

        self._midi_range = (lo_i, hi_i)
        self.update()

    def set_display_octave(self, octave: int):
        """Set which octave to display (2-7)."""
        self.display_octave = max(2, min(7, int(octave)))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        height = self.height()

        midi_min, midi_max = self._midi_range
        midi_top = int(midi_max)
        midi_bottom = int(midi_min)
        if midi_top < midi_bottom:
            midi_top, midi_bottom = midi_bottom, midi_top

        count = max(1, (midi_top - midi_bottom) + 1)
        row_h = max(6, int(height / count))
        total_h = row_h * count
        y0 = max(0, int((height - total_h) / 2))

        y = y0
        for midi in range(midi_top, midi_bottom - 1, -1):
            note_name = self.note_names[midi % 12]
            is_black = note_name in self.black_notes
            is_selected = (self._selected_midi is not None) and (int(self._selected_midi) == int(midi))

            if is_selected:
                color = QColor("#1D5AAA") if is_black else QColor("#33CED6")
            else:
                color = QColor("#2E2E2E") if is_black else QColor("#404040")

            key_width = self.black_key_width if is_black else self.white_key_width
            x = 0 if not is_black else 0
            painter.fillRect(x, y, key_width, row_h - 1, color)

            painter.setPen(QPen(QColor("#1D5AAA"), 1))
            painter.drawRect(x, y, key_width, row_h - 1)

            if row_h >= 10:
                painter.setPen(QColor("#ffffff") if is_selected else QColor(51, 206, 214, 220))
                font = QFont("Arial", 8)
                painter.setFont(font)
                painter.drawText(x + 4, y + row_h - 3, note_name)

            y += row_h

        painter.end()
