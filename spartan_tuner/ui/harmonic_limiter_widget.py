from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from utils.i18n import tr


def _format_hz(v: float) -> str:
    hz = float(v)
    if hz >= 1000.0:
        return f"{hz / 1000.0:.1f}k"
    return f"{hz:.0f}"


class _FreqAxis(pg.AxisItem):
    def tickStrings(self, values, scale, spacing):
        out = []
        for val in values:
            v = max(1.0, float(val))
            hz = 10.0 ** v
            out.append(_format_hz(hz))
        return out


class _NodeViewBox(pg.ViewBox):
    def __init__(self, owner: "HarmonicLimiterWidget"):
        super().__init__()
        self._owner = owner
        self.setMouseEnabled(x=False, y=False)
        self.setMenuEnabled(False)
        self._drag_idx = None
        self._drag_event_count = 0
        self._drag_start_pointer_y = 0.0
        self._drag_start_node_y = 0.0
        self._drag_pointer_to_node_offset = 0.0

    def mouseDragEvent(self, ev, axis=None):
        if ev.button() != Qt.MouseButton.LeftButton:
            super().mouseDragEvent(ev, axis=axis)
            return
        pt = self.mapSceneToView(ev.scenePos())
        x = float(pt.x())
        y = float(pt.y())

        if ev.isStart():
            idx = self._owner.hit_test_node(x, y)
            if idx is None:
                super().mouseDragEvent(ev, axis=axis)
                return
            self._drag_idx = int(idx)
            self._drag_event_count = 0
            self._drag_start_pointer_y = float(y)
            self._drag_start_node_y = float(self._owner.get_node_db(int(idx)))
            self._drag_pointer_to_node_offset = float(self._drag_start_pointer_y - self._drag_start_node_y)
            self._owner._is_dragging = True
            ev.accept()
            return

        if self._drag_idx is None:
            super().mouseDragEvent(ev, axis=axis)
            return

        self._drag_event_count += 1
        target_y = float(y - self._drag_pointer_to_node_offset)
        self._owner.drag_node_to(self._drag_idx, target_y)
        if ev.isFinish():
            self._owner.finish_drag(self._drag_idx)
            self._drag_idx = None
            self._owner._is_dragging = False
        ev.accept()

    def mouseDoubleClickEvent(self, ev):
        if ev.button() != Qt.MouseButton.LeftButton:
            return super().mouseDoubleClickEvent(ev)
        pt = self.mapSceneToView(ev.scenePos())
        idx = self._owner.hit_test_node(float(pt.x()), float(pt.y()))
        if idx is not None:
            self._owner.reset_node(int(idx))
            ev.accept()
            return
        super().mouseDoubleClickEvent(ev)


class HarmonicLimiterWidget(QWidget):
    ceiling_changed = pyqtSignal(int, float)
    reset_all_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme = {
            "bg": "#2E2E2E",
            "accent": "#33CED6",
            "primary": "#1D5AAA",
            "harmonic_node_grad_start": "#33CED6",
            "harmonic_node_grad_end": "#4EDE83",
            "text": "#ffffff",
        }
        self._analysis = {}
        self._peak_db = []
        self._current_db = []
        self._freq_hz = []
        self._harm_numbers = []
        self._offsets = {}
        self._is_dragging = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        hdr = QHBoxLayout()
        self.title_label = QLabel(tr("harmonic.title", "Harmonic limiter"))
        self.meta_label = QLabel("-")
        self.meta_label.setStyleSheet("opacity:0.7;")
        hdr.addWidget(self.title_label)
        hdr.addWidget(self.meta_label)
        hdr.addStretch(1)
        self.reset_btn = QPushButton(tr("harmonic.button.reset_all", "Reset all"))
        self.reset_btn.clicked.connect(self.reset_all_clicked.emit)
        hdr.addWidget(self.reset_btn)
        root.addLayout(hdr)

        self.plot = pg.PlotWidget(viewBox=_NodeViewBox(self), axisItems={"bottom": _FreqAxis(orientation="bottom")})
        self.plot.setLabel("left", tr("harmonic.axis.db", "dB"))
        self.plot.setLabel("bottom", tr("harmonic.axis.freq", "Frequency"))
        self.plot.showGrid(x=True, y=True, alpha=0.2)
        self.plot.setYRange(-60.0, 6.0)
        # Pre-logged data is passed to all items; do NOT use setLogMode which
        # would double-apply log10 and push curves off-screen.
        self.plot.getPlotItem().getViewBox().setAutoVisible(x=False, y=False)
        self.plot.getPlotItem().enableAutoRange(axis='x', enable=False)
        self.plot.getPlotItem().enableAutoRange(axis='y', enable=False)
        root.addWidget(self.plot, 1)

        self._spectrum_curve = self.plot.plot([], [], pen=pg.mkPen("#33CED6", width=2))
        self._spectrum_fill = pg.FillBetweenItem(
            self._spectrum_curve,
            self.plot.plot([], [], pen=pg.mkPen(None)),
            brush=pg.mkBrush(51, 206, 214, 32),
        )
        self.plot.addItem(self._spectrum_fill)
        self._harmonic_rms_curve = self.plot.plot([], [], pen=pg.mkPen(255, 255, 255, 0))
        self._harmonic_peak_curve = self.plot.plot([], [], pen=pg.mkPen(235, 235, 235, 205, width=1.4))
        self._harmonic_peak_fill = pg.FillBetweenItem(
            self._harmonic_peak_curve,
            self._harmonic_rms_curve,
            brush=pg.mkBrush(255, 255, 255, 36),
        )
        self.plot.addItem(self._harmonic_peak_fill)
        self._vlines: list[pg.PlotDataItem] = []
        self._ceiling_lines: list[pg.PlotDataItem] = []
        self._nodes = pg.ScatterPlotItem(size=24, pen=pg.mkPen("#33CED6", width=2), brush=pg.mkBrush(0, 0, 0, 0), symbol="o")
        self.plot.addItem(self._nodes)
        self._labels: list[pg.TextItem] = []

    def retranslate_ui(self):
        self.title_label.setText(tr("harmonic.title", "Harmonic limiter"))
        self.reset_btn.setText(tr("harmonic.button.reset_all", "Reset all"))
        self.plot.setLabel("left", tr("harmonic.axis.db", "dB"))
        self.plot.setLabel("bottom", tr("harmonic.axis.freq", "Frequency"))

    def apply_theme(self, theme: dict):
        if isinstance(theme, dict):
            for k, v in theme.items():
                if v is not None:
                    self._theme[str(k)] = str(v)
        bg = str(self._theme.get("bg", "#2E2E2E"))
        primary = str(self._theme.get("primary", "#1D5AAA"))
        accent = str(self._theme.get("accent", "#33CED6"))
        self.plot.setBackground(bg)
        self._spectrum_curve.setPen(pg.mkPen(primary, width=2))
        c = QColor(accent)
        self._spectrum_fill.setBrush(pg.mkBrush(c.red(), c.green(), c.blue(), 28))
        self._harmonic_peak_curve.setPen(pg.mkPen(235, 235, 235, 205, width=1.4))
        self._harmonic_peak_fill.setBrush(pg.mkBrush(255, 255, 255, 36))
        self._render()

    def set_analysis(self, pre_analysis: dict, post_analysis: dict, harmonic_offsets_db: dict[int, float], note_label: str):
        pre = dict(pre_analysis or {})
        post = dict(post_analysis or {})
        self._analysis = post if post.get("avg_spectrum_freq_hz") else pre
        self._offsets = {int(k): float(v) for k, v in (harmonic_offsets_db or {}).items()}
        self._harm_numbers = list(pre.get("harmonic_numbers", []))
        self._freq_hz = list(pre.get("harmonic_freqs_hz", []))
        self._peak_db = list(pre.get("peak_db", []))
        self._current_db = [float(self._peak_db[i] + self._offsets.get(int(self._harm_numbers[i]), 0.0)) for i in range(len(self._harm_numbers))]
        count = len(self._harm_numbers)
        self.meta_label.setText(
            tr("harmonic.meta_fmt", "{note} - {count} harmonics detected").format(note=str(note_label or "-"), count=int(count))
        )
        self._render()

    def _clear_dynamic(self):
        for it in self._vlines + self._ceiling_lines:
            try:
                self.plot.removeItem(it)
            except Exception:
                pass
        self._vlines = []
        self._ceiling_lines = []
        for t in self._labels:
            try:
                self.plot.removeItem(t)
            except Exception:
                pass
        self._labels = []

    def _render(self):
        self._clear_dynamic()
        avg_freq = np.asarray(self._analysis.get("avg_spectrum_freq_hz", []), dtype=np.float64)
        avg_db = np.asarray(self._analysis.get("avg_spectrum_db", []), dtype=np.float64)
        if avg_freq.size and avg_db.size:
            x = np.log10(np.maximum(avg_freq, 1.0))
            self._spectrum_curve.setData(x, avg_db)
        else:
            self._spectrum_curve.setData([], [])
        if not self._harm_numbers:
            self._nodes.setData([])
            self._harmonic_peak_curve.setData([], [])
            self._harmonic_rms_curve.setData([], [])
            return
        xh = np.log10(np.maximum(np.asarray(self._freq_hz, dtype=np.float64), 1.0))
        yh = np.asarray(self._current_db, dtype=np.float64)
        peak_db = np.asarray(self._peak_db, dtype=np.float64)
        rms_src = np.asarray(self._analysis.get("rms_db", []), dtype=np.float64)
        if rms_src.size != peak_db.size:
            rms_src = peak_db - 6.0
        rms_src = np.minimum(rms_src, peak_db)

        # Build thin harmonic "peak" envelopes (Parametric EQ style) in log-frequency space.
        x_grid = np.linspace(float(xh[0]), float(xh[-1]), int(max(700, len(xh) * 90)))
        y_floor = -60.0
        y_peak_curve = np.full_like(x_grid, y_floor, dtype=np.float64)
        y_rms_curve = np.full_like(x_grid, y_floor, dtype=np.float64)
        for i in range(len(xh)):
            x0 = float(xh[i])
            prev_gap = float(x0 - xh[i - 1]) if i > 0 else float(xh[min(i + 1, len(xh) - 1)] - x0)
            next_gap = float(xh[i + 1] - x0) if i < len(xh) - 1 else float(x0 - xh[max(i - 1, 0)])
            local_gap = max(0.012, min(prev_gap, next_gap))
            sigma = float(max(0.010, min(0.060, local_gap * 0.20)))
            g = np.exp(-0.5 * np.square((x_grid - x0) / sigma))
            y_peak_shape = y_floor + (float(peak_db[i]) - y_floor) * g
            y_rms_shape = y_floor + (float(rms_src[i]) - y_floor) * g
            y_peak_curve = np.maximum(y_peak_curve, y_peak_shape)
            y_rms_curve = np.maximum(y_rms_curve, y_rms_shape)

        self._harmonic_peak_curve.setData(x_grid, y_peak_curve)
        self._harmonic_rms_curve.setData(x_grid, y_rms_curve)

        spots = []
        accent = QColor(str(self._theme.get("accent", "#33CED6")))
        for i, h in enumerate(self._harm_numbers):
            alpha = int(max(90, 255 - i * 6))
            modified = abs(float(self._current_db[i]) - float(self._peak_db[i])) > 1e-6
            fill_alpha = 100 if modified else 40
            spots.append(
                {
                    "pos": (float(xh[i]), float(yh[i])),
                    "data": int(h),
                    "pen": pg.mkPen(accent.red(), accent.green(), accent.blue(), alpha, width=2),
                    "brush": pg.mkBrush(accent.red(), accent.green(), accent.blue(), fill_alpha),
                    "symbol": "o",
                    "size": 26,
                }
            )
            vl = self.plot.plot([float(xh[i]), float(xh[i])], [-60.0, float(yh[i])], pen=pg.mkPen(accent.red(), accent.green(), accent.blue(), 50, width=1))
            self._vlines.append(vl)
            if modified:
                cl = self.plot.plot([float(xh[i]) - 0.02, float(xh[i]) + 0.02], [float(yh[i]), float(yh[i])], pen=pg.mkPen(accent.red(), accent.green(), accent.blue(), 170, width=1, style=Qt.PenStyle.DashLine))
                self._ceiling_lines.append(cl)
            txt = pg.TextItem(text=str(int(h)), color=str(self._theme.get("text", "#ffffff")), anchor=(0.5, 0.5))
            txt.setPos(float(xh[i]), float(yh[i]))
            self.plot.addItem(txt)
            self._labels.append(txt)
        self._nodes.setData(spots)
        try:
            self.plot.setXRange(float(xh[0]), float(xh[-1]), padding=0.02)
            y_max = float(max(self._peak_db)) + 6.0 if self._peak_db else 6.0
            self.plot.setYRange(-60.0, y_max, padding=0)
        except Exception:
            pass

    def hit_test_node(self, logx: float, y: float) -> int | None:
        if not self._harm_numbers:
            return None
        xh = np.log10(np.maximum(np.asarray(self._freq_hz, dtype=np.float64), 1.0))
        yh = np.asarray(self._current_db, dtype=np.float64)
        best = None
        best_score = 1e9
        for i in range(len(self._harm_numbers)):
            dx = abs(float(logx - xh[i]))
            dy = abs(float(y - yh[i]))
            score = dx * 14.0 + dy * 0.22
            if score < best_score:
                best_score = score
                best = i
        if best is None:
            return None
        dx_best = abs(float(logx - xh[int(best)]))
        dy_best = abs(float(y - yh[int(best)]))
        if dx_best > 0.06 and dy_best > 10.0:
            return None
        return int(best)

    def drag_node_to(self, idx: int, target_db: float):
        i = int(idx)
        if i < 0 or i >= len(self._current_db):
            return
        max_db = float(self._peak_db[i])
        clamped_db = float(max(-60.0, min(max_db, float(target_db))))
        self._current_db[i] = clamped_db
        self._render()

    def finish_drag(self, idx: int):
        i = int(idx)
        if i < 0 or i >= len(self._harm_numbers):
            return
        self.ceiling_changed.emit(int(self._harm_numbers[i]), float(self._current_db[i]))

    def reset_node(self, idx: int):
        i = int(idx)
        if i < 0 or i >= len(self._harm_numbers):
            return
        self._current_db[i] = float(self._peak_db[i])
        self._render()
        self.ceiling_changed.emit(int(self._harm_numbers[i]), float(self._peak_db[i]))

    def get_node_db(self, idx: int) -> float:
        i = int(idx)
        if i < 0 or i >= len(self._current_db):
            return 0.0
        return float(self._current_db[i])
