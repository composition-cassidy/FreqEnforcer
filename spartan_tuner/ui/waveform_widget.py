import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor

from utils.i18n import tr



class _BlobViewBox(pg.ViewBox):
    def __init__(self, owner_widget: "WaveformWidget"):
        super().__init__()
        self._owner_widget = owner_widget

        self.setMouseEnabled(x=True, y=True)
        self.setMenuEnabled(False)
        self.disableAutoRange()

    def mouseDragEvent(self, ev, axis=None):
        if ev.button() != Qt.MouseButton.LeftButton:
            super().mouseDragEvent(ev, axis=axis)
            return

        if self._owner_widget._blob_enabled is False:
            super().mouseDragEvent(ev, axis=axis)
            return

        pt = self.mapSceneToView(ev.scenePos())
        x = float(pt.x())
        y = float(pt.y())

        if ev.isStart():
            if self._owner_widget._hit_test_blob(x, y):
                self._owner_widget._blob_dragging = True
                self._owner_widget._blob_drag_offset = y - float(self._owner_widget._blob_midi_note)
                self._owner_widget._blob_last_pos = (x, y)
                ev.accept()
                return

        if self._owner_widget._blob_dragging:
            self._owner_widget._blob_last_pos = (x, y)

            if ev.isFinish():
                self._owner_widget._blob_dragging = False
                self._owner_widget._blob_drag_offset = 0.0
                ev.accept()
                return

            target_midi = int(round(y - float(self._owner_widget._blob_drag_offset)))
            self._owner_widget.set_blob_midi_note(target_midi, emit_signal=True)
            ev.accept()
            return

        super().mouseDragEvent(ev, axis=axis)


class WaveformWidget(QWidget):
    """
    Displays audio waveform using pyqtgraph for fast rendering.
    """

    blob_note_changed = pyqtSignal(int)
    midi_view_range_changed = pyqtSignal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._theme = {
            "bg": "#2E2E2E",
            "accent": "#33CED6",
        }

        self.audio_data = None
        self.sample_rate = 44100
        self._duration_s = 0.0
        self._x_bounds = (0.0, 0.0)

        self._blob_enabled = True
        self._blob_midi_note = 60
        self._blob_last_pos = (0.0, 0.0)
        self._blob_dragging = False
        self._blob_drag_offset = 0.0
        self._blob_note_min = 36
        self._blob_note_max = 107
        self._blob_hit_tolerance_notes = 1.0
        self._blob_scale_semitones = 2.25
        self._blob_min_thickness_semitones = 0.35
        self._y_view_half_range_notes = 8.0
        self._soft_follow_margin_notes = 2.0
        self._last_emitted_midi_view_range = None

        self._display_time_axis = np.array([], dtype=np.float64)
        self._display_audio = np.array([], dtype=np.float64)
        self._display_delta = np.array([], dtype=np.float64)
        self._blob_needs_data_rebuild = True

        self._performance_mode = False
        self._max_points = 100000

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.plot_widget = pg.PlotWidget(viewBox=_BlobViewBox(self))
        self.plot_widget.setBackground(self._theme.get("bg", "#2E2E2E"))
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.setLabel('bottom', tr("waveform.axis.time", "Time"), units='s')
        self.plot_widget.setLabel('left', tr("waveform.axis.midi_note", "MIDI Note"))
        self.plot_widget.setYRange(self._blob_note_min, self._blob_note_max)

        self._view_box = self.plot_widget.getPlotItem().getViewBox()
        self._view_box.sigRangeChanged.connect(self._on_range_changed)
        self._view_box.setLimits(yMin=float(self._blob_note_min), yMax=float(self._blob_note_max))

        accent = str(self._theme.get("accent", "#33CED6"))
        self._blob_top_curve = self.plot_widget.plot(pen=pg.mkPen(color=accent, width=1))
        self._blob_bottom_curve = self.plot_widget.plot(pen=pg.mkPen(color=accent, width=1))
        self._blob_fill = pg.FillBetweenItem(
            self._blob_top_curve,
            self._blob_bottom_curve,
            brush=pg.mkBrush(51, 206, 214, 110),
        )
        self.plot_widget.addItem(self._blob_fill)

        layout.addWidget(self.plot_widget)

        self._update_y_view(center_midi=float(self._blob_midi_note), force=True)

    def retranslate_ui(self):
        try:
            self.plot_widget.setLabel('bottom', tr("waveform.axis.time", "Time"), units='s')
        except Exception:
            pass

        try:
            self.plot_widget.setLabel('left', tr("waveform.axis.midi_note", "MIDI Note"))
        except Exception:
            pass

    def apply_theme(self, theme: dict):
        if isinstance(theme, dict):
            self._theme.update({k: str(v) for k, v in theme.items() if v is not None})

        bg = str(self._theme.get("bg", "#2E2E2E"))
        accent = str(self._theme.get("accent", "#33CED6"))

        try:
            self.plot_widget.setBackground(bg)
        except Exception:
            pass

        try:
            pen = pg.mkPen(color=accent, width=1)
            self._blob_top_curve.setPen(pen)
            self._blob_bottom_curve.setPen(pen)
        except Exception:
            pass

        try:
            c = QColor(accent)
            if c.isValid():
                self._blob_fill.setBrush(pg.mkBrush(c.red(), c.green(), c.blue(), 110))
        except Exception:
            pass

    def set_performance_mode(self, enabled: bool):
        self._performance_mode = bool(enabled)
        self._max_points = 30000 if self._performance_mode else 100000
        try:
            if self._performance_mode:
                self.plot_widget.showGrid(x=False, y=False)
            else:
                self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        except Exception:
            pass

        self._update_plot()

    def set_audio(self, audio: np.ndarray, sample_rate: int):
        """
        Set the audio data to display.

        Args:
            audio: Audio samples as numpy array
            sample_rate: Sample rate in Hz
        """
        was_empty = self.audio_data is None
        self.audio_data = audio
        self.sample_rate = sample_rate
        self._duration_s = float(len(self.audio_data)) / float(self.sample_rate) if self.sample_rate > 0 else 0.0
        self._set_x_bounds(0.0, max(0.0, self._duration_s))
        self._update_plot()
        if was_empty:
            self._update_y_view(center_midi=float(self._blob_midi_note), force=True)

    def _update_plot(self):
        """Redraw the waveform."""
        if self.audio_data is None:
            self._display_time_axis = np.array([], dtype=np.float64)
            self._display_audio = np.array([], dtype=np.float64)
            self._display_delta = np.array([], dtype=np.float64)
            self._blob_needs_data_rebuild = True
            self._blob_top_curve.setData([], [])
            self._blob_bottom_curve.setData([], [])
            return

        max_points = int(self._max_points)
        if len(self.audio_data) > max_points:
            step = max(1, (len(self.audio_data) + max_points - 1) // max_points)
            display_audio = self.audio_data[::step]
        else:
            step = 1
            display_audio = self.audio_data

        time_axis = (np.arange(len(display_audio), dtype=np.float64) * (float(step) / float(self.sample_rate)))

        self._display_time_axis = np.asarray(time_axis, dtype=np.float64)
        self._display_audio = np.asarray(display_audio, dtype=np.float64)

        amp = np.abs(np.clip(self._display_audio, -1.0, 1.0))
        self._display_delta = (amp * float(self._blob_scale_semitones)) + float(self._blob_min_thickness_semitones)
        self._blob_needs_data_rebuild = True
        self._rebuild_blob()

        self._set_x_bounds(0.0, max(0.0, float(len(self.audio_data)) / float(self.sample_rate)))

    def clear(self):
        """Clear the waveform display."""
        self.audio_data = None
        self._duration_s = 0.0
        self._x_bounds = (0.0, 0.0)
        self._display_time_axis = np.array([], dtype=np.float64)
        self._display_audio = np.array([], dtype=np.float64)
        self._display_delta = np.array([], dtype=np.float64)
        self._blob_needs_data_rebuild = True
        self._blob_top_curve.setData([], [])
        self._blob_bottom_curve.setData([], [])

    def _set_x_bounds(self, xmin: float, xmax: float):
        xmin_f = float(xmin)
        xmax_f = float(xmax)
        if xmax_f < xmin_f:
            xmin_f, xmax_f = xmax_f, xmin_f

        self._x_bounds = (xmin_f, xmax_f)

        width = xmax_f - xmin_f
        if width <= 0.0:
            self._view_box.setLimits(xMin=0.0, xMax=0.0)
            self._view_box.setRange(xRange=(0.0, 0.0), padding=0.0)
            return

        min_x_range = max(0.01, width / 400.0)
        self._view_box.setLimits(xMin=xmin_f, xMax=xmax_f, minXRange=min_x_range, maxXRange=width)
        self._view_box.setRange(xRange=(xmin_f, xmax_f), padding=0.0)

    def _on_range_changed(self, view_box, view_range):
        (x_range, _y_range) = view_range
        self._emit_midi_view_range_if_changed(_y_range)
        xmin, xmax = float(x_range[0]), float(x_range[1])
        bmin, bmax = self._x_bounds
        bound_width = float(bmax - bmin)
        if bound_width <= 0.0:
            return

        width = float(xmax - xmin)
        width = min(width, bound_width)

        if xmin < bmin:
            xmin = bmin
            xmax = xmin + width
        if xmax > bmax:
            xmax = bmax
            xmin = xmax - width

        xmin = max(bmin, xmin)
        xmax = min(bmax, xmax)

        if abs(x_range[0] - xmin) < 1e-9 and abs(x_range[1] - xmax) < 1e-9:
            return

        self._view_box.blockSignals(True)
        self._view_box.setRange(xRange=(xmin, xmax), padding=0.0)
        self._view_box.blockSignals(False)

    def set_blob_midi_note(self, midi_note: int, emit_signal: bool = False):
        midi = int(midi_note)
        midi = max(self._blob_note_min, min(self._blob_note_max, midi))
        if midi == self._blob_midi_note:
            return
        self._blob_midi_note = midi
        self._soft_follow_blob(center_midi=float(midi))
        self._rebuild_blob()
        if emit_signal:
            self.blob_note_changed.emit(int(midi))

    def _emit_midi_view_range_if_changed(self, y_range=None):
        if y_range is None:
            _x_range, y_range = self._view_box.viewRange()

        ymin = float(y_range[0])
        ymax = float(y_range[1])
        last = self._last_emitted_midi_view_range
        if last is not None and abs(float(last[0]) - ymin) < 1e-6 and abs(float(last[1]) - ymax) < 1e-6:
            return

        self._last_emitted_midi_view_range = (ymin, ymax)
        self.midi_view_range_changed.emit(ymin, ymax)

    def _soft_follow_blob(self, center_midi: float):
        center = float(center_midi)
        _x_range, y_range = self._view_box.viewRange()
        ymin = float(y_range[0])
        ymax = float(y_range[1])
        span = float(ymax - ymin)
        if span <= 0.0:
            return

        margin = float(self._soft_follow_margin_notes)
        new_ymin = ymin
        new_ymax = ymax
        if center < ymin + margin:
            new_ymin = center - margin
            new_ymax = new_ymin + span
        elif center > ymax - margin:
            new_ymax = center + margin
            new_ymin = new_ymax - span
        else:
            return

        min_allowed = float(self._blob_note_min)
        max_allowed = float(self._blob_note_max)
        if new_ymin < min_allowed:
            new_ymin = min_allowed
            new_ymax = new_ymin + span
        if new_ymax > max_allowed:
            new_ymax = max_allowed
            new_ymin = new_ymax - span

        if new_ymax - new_ymin < 1.0:
            return

        self._view_box.blockSignals(True)
        self._view_box.setRange(yRange=(new_ymin, new_ymax), padding=0.0)
        self._view_box.blockSignals(False)
        self._emit_midi_view_range_if_changed((new_ymin, new_ymax))

    def _rebuild_blob(self):
        if self._display_time_axis.size == 0 or self._display_delta.size == 0:
            self._blob_top_curve.setData([], [])
            self._blob_bottom_curve.setData([], [])
            return

        center = float(self._blob_midi_note)
        delta = self._display_delta

        if self._blob_needs_data_rebuild:
            self._blob_top_curve.setData(self._display_time_axis, delta)
            self._blob_bottom_curve.setData(self._display_time_axis, -delta)
            self._blob_needs_data_rebuild = False

        try:
            self._blob_top_curve.setPos(0.0, center)
            self._blob_bottom_curve.setPos(0.0, center)
        except Exception:
            y_top = center + delta
            y_bottom = center - delta
            self._blob_top_curve.setData(self._display_time_axis, y_top)
            self._blob_bottom_curve.setData(self._display_time_axis, y_bottom)

    def _hit_test_blob(self, x: float, y: float) -> bool:
        if self._display_time_axis.size == 0:
            return False

        xmin, xmax = self._x_bounds
        if x < xmin or x > xmax:
            return False

        return abs(float(y) - float(self._blob_midi_note)) <= float(self._blob_hit_tolerance_notes)

    def get_midi_view_range(self) -> tuple[float, float]:
        _x_range, y_range = self._view_box.viewRange()
        return float(y_range[0]), float(y_range[1])

    def _update_y_view(self, center_midi: float, force: bool):
        center = float(center_midi)
        half = float(self._y_view_half_range_notes)
        ymin = center - half
        ymax = center + half

        ymin = max(float(self._blob_note_min), ymin)
        ymax = min(float(self._blob_note_max), ymax)

        if ymax - ymin < 1.0:
            return

        _x_range, current_y = self._view_box.viewRange()
        if (not force) and abs(float(current_y[0]) - ymin) < 1e-6 and abs(float(current_y[1]) - ymax) < 1e-6:
            return

        self._view_box.blockSignals(True)
        self._view_box.setRange(yRange=(ymin, ymax), padding=0.0)
        self._view_box.blockSignals(False)
        self._emit_midi_view_range_if_changed((ymin, ymax))
