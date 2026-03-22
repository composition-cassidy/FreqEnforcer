from __future__ import annotations

import math
from typing import Iterable

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget


class KnobWidget(QWidget):
    valueChanged = pyqtSignal(float)

    def __init__(
        self,
        label: str,
        minimum: float,
        maximum: float,
        default_value: float,
        step: float = 1.0,
        suffix: str = "",
        decimals: int = 0,
        snap_points: Iterable[float] | None = None,
        snap_dead_zone: float = 0.0,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)

        if float(maximum) <= float(minimum):
            raise ValueError("maximum must be greater than minimum")

        self._label = str(label)
        self._minimum = float(minimum)
        self._maximum = float(maximum)
        self._default_value = float(default_value)
        self._step = abs(float(step)) if float(step) != 0.0 else 1.0
        self._suffix = str(suffix)
        self._decimals = max(0, int(decimals))
        self._snap_points = [float(v) for v in (snap_points or [])]
        self._snap_dead_zone = max(0.0, float(snap_dead_zone))

        self._value = self._clamp(self._default_value)
        self._dragging = False
        self._drag_start_pos = QPointF()
        self._drag_start_value = self._value
        self._drag_units_per_pixel = (self._maximum - self._minimum) / 150.0

        self._theme: dict[str, str] = {
            "bg": "#2E2E2E",
            "panel": "#404040",
            "accent": "#33CED6",
            "text": "#FFFFFF",
        }

        self._style_params = {
            "arc_thickness": 6.40,
            "gap": 0.70,
            "indicator_thickness": 1.60,
            "indicator_start_ratio": 0.44,
            "indicator_end_ratio": 0.91,
            "body_lightness": 67,
            "body_darkness": 101,
            "track_alpha": 44,
            "start_angle": 244.0,
            "sweep_angle": -307.0,
        }

        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def sizeHint(self) -> QSize:
        return QSize(120, 100)

    def minimumSizeHint(self) -> QSize:
        return QSize(100, 90)

    def update_style(self, **kwargs) -> None:
        self._style_params.update(kwargs)
        self.update()

    def value(self) -> float:
        return float(self._value)

    def setValue(self, value: float, emit_signal: bool = True) -> None:
        snapped = self._apply_snap(self._clamp(float(value)))
        if math.isclose(snapped, self._value, rel_tol=0.0, abs_tol=1e-12):
            return

        self._value = snapped
        self.update()
        if emit_signal:
            self.valueChanged.emit(float(self._value))

    def setRange(self, minimum: float, maximum: float) -> None:
        new_min = float(minimum)
        new_max = float(maximum)
        if new_max <= new_min:
            raise ValueError("maximum must be greater than minimum")

        self._minimum = new_min
        self._maximum = new_max
        self._drag_units_per_pixel = (self._maximum - self._minimum) / 150.0
        self._default_value = self._clamp(self._default_value)
        self.setValue(self._value, emit_signal=False)

    def setDefaultValue(self, default_value: float) -> None:
        self._default_value = self._clamp(float(default_value))

    def setStep(self, step: float) -> None:
        s = float(step)
        self._step = abs(s) if s != 0.0 else self._step

    def setSnapPoints(self, points: Iterable[float], dead_zone: float | None = None) -> None:
        self._snap_points = [float(v) for v in points]
        if dead_zone is not None:
            self._snap_dead_zone = max(0.0, float(dead_zone))
        self.setValue(self._value, emit_signal=False)

    def setSuffix(self, suffix: str) -> None:
        self._suffix = str(suffix)
        self.update()

    def setDecimals(self, decimals: int) -> None:
        self._decimals = max(0, int(decimals))
        self.update()

    def apply_theme(self, theme_dict: dict) -> None:
        if isinstance(theme_dict, dict):
            self._theme.update({k: str(v) for k, v in theme_dict.items() if v is not None})
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_start_pos = event.position()
            self._drag_start_value = self._value
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            dy = self._drag_start_pos.y() - event.position().y()
            next_value = self._drag_start_value + (dy * self._drag_units_per_pixel)
            self.setValue(next_value)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.setValue(self._default_value)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y()
        if delta == 0:
            event.ignore()
            return

        direction = 1.0 if delta > 0 else -1.0
        self.setValue(self._value + (direction * self._step))
        event.accept()

    def paintEvent(self, event) -> None:
        _ = event

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        bg = self._to_color("bg", "#2E2E2E")
        panel = self._to_color("panel", "#404040")
        accent = self._to_color("accent", "#33CED6")
        text = self._to_color("text", "#FFFFFF")

        rect = self.rect()
        margin = 4
        label_h = 18
        value_h = 18

        knob_area = rect.adjusted(margin, label_h, -margin, -value_h)
        side = float(max(10, min(knob_area.width(), knob_area.height())))
        cx = knob_area.center().x()
        cy = knob_area.center().y()
        
        # Center everything perfectly
        knob_rect = QRectF(cx - side / 2.0, cy - side / 2.0, side, side)

        # 1. Arc parameters (270 degree sweep, starting at bottom-left)
        start_deg = self._style_params.get("start_angle", 225.0)
        sweep_deg = self._style_params.get("sweep_angle", -270.0) # Negative because Qt draws arcs counter-clockwise
        t = self._normalized()

        arc_thickness = self._style_params.get("arc_thickness", 3.0)
        arc_rect = knob_rect.adjusted(arc_thickness / 2.0, arc_thickness / 2.0, -arc_thickness / 2.0, -arc_thickness / 2.0)

        # Draw background track
        track_alpha = self._style_params.get("track_alpha", 50)
        track_color = QColor(text)
        track_color.setAlpha(int(track_alpha))
        
        track_pen = QPen(track_color)
        track_pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        track_pen.setWidthF(arc_thickness)
        painter.setPen(track_pen)
        painter.drawArc(arc_rect, int(start_deg * 16), int(sweep_deg * 16))

        # Draw active track
        active_pen = QPen(accent)
        active_pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        active_pen.setWidthF(arc_thickness)
        painter.setPen(active_pen)
        painter.drawArc(arc_rect, int(start_deg * 16), int((sweep_deg * t) * 16))

        # 2. Knob Body (Inner circle)
        gap = self._style_params.get("gap", 4.0)
        body_rect = knob_rect.adjusted(arc_thickness + gap, arc_thickness + gap, -(arc_thickness + gap), -(arc_thickness + gap))

        from PyQt6.QtGui import QLinearGradient, QRadialGradient
        
        # Gradient for the 3D lit effect (top-left lighter, bottom-right darker)
        gradient = QLinearGradient(body_rect.topLeft(), body_rect.bottomRight())
        
        lightness = int(self._style_params.get("body_lightness", 120))
        darkness = int(self._style_params.get("body_darkness", 70))
        
        gradient.setColorAt(0.0, QColor(panel).lighter(lightness))
        gradient.setColorAt(1.0, QColor(panel).darker(darkness))

        # Drop shadow for knob body
        shadow_rect = body_rect.translated(1, 2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 80))
        painter.drawEllipse(shadow_rect)

        # Fill knob body
        painter.setBrush(gradient)
        border_pen = QPen(QColor(0, 0, 0, 200))
        border_pen.setWidthF(1.0)
        painter.setPen(border_pen)
        painter.drawEllipse(body_rect)

        # 3. Indicator Line
        indicator_angle = start_deg + (sweep_deg * t)
        theta = math.radians(indicator_angle)
        
        start_ratio = self._style_params.get("indicator_start_ratio", 0.0)
        end_ratio = self._style_params.get("indicator_end_ratio", 1.0)
        
        r_full = body_rect.width() / 2.0
        r_inner = r_full * start_ratio
        r_outer = r_full * end_ratio

        x1 = cx + (r_inner * math.cos(theta))
        y1 = cy - (r_inner * math.sin(theta))
        x2 = cx + (r_outer * math.cos(theta))
        y2 = cy - (r_outer * math.sin(theta))

        indicator_thickness = self._style_params.get("indicator_thickness", 1.5)
        indicator_pen = QPen(text) # Use text color for high contrast indicator like the image
        indicator_pen.setWidthF(indicator_thickness)
        indicator_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(indicator_pen)
        painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        # 4. Text (Label above, Value below)
        painter.setPen(text)
        label_rect = QRectF(float(rect.left() + 2), float(rect.top()), float(max(0, rect.width() - 4)), float(label_h))
        fm = QFontMetrics(painter.font())
        label_txt = fm.elidedText(str(self._label), Qt.TextElideMode.ElideRight, int(label_rect.width()))
        painter.drawText(label_rect, int(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignBottom), label_txt)

        value_rect = QRectF(float(rect.left()), float(rect.bottom() - value_h + 1), float(rect.width()), float(value_h))
        painter.drawText(
            value_rect,
            int(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignTop),
            self._format_value_text(),
        )

    def _normalized(self) -> float:
        denom = self._maximum - self._minimum
        if denom <= 0.0:
            return 0.0
        return max(0.0, min(1.0, (self._value - self._minimum) / denom))

    def _clamp(self, value: float) -> float:
        return max(self._minimum, min(self._maximum, float(value)))

    def _apply_snap(self, value: float) -> float:
        if not self._snap_points or self._snap_dead_zone <= 0.0:
            return value

        best = None
        best_dist = None
        for snap in self._snap_points:
            dist = abs(value - float(snap))
            if dist <= self._snap_dead_zone and (best_dist is None or dist < best_dist):
                best = float(snap)
                best_dist = dist

        if best is None:
            return value
        return self._clamp(best)

    def _to_color(self, key: str, fallback: str) -> QColor:
        c = QColor(str(self._theme.get(key, fallback)))
        if not c.isValid():
            c = QColor(str(fallback))
        return c

    def _format_value_text(self) -> str:
        value_txt = f"{self._value:.{self._decimals}f}"
        if not self._suffix:
            return value_txt
        if self._suffix in {"%", "x"}:
            return f"{value_txt}{self._suffix}"
        return f"{value_txt} {self._suffix}"
