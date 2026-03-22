from __future__ import annotations

import math
from typing import Iterable

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetrics, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QSizePolicy, QWidget


class SliderWidget(QWidget):
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
        orientation: Qt.Orientation = Qt.Orientation.Vertical,
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
        self._orientation = orientation

        self._value = self._clamp(self._default_value)
        self._dragging = False
        self._drag_start_pos = QPointF()
        self._drag_start_value = self._value

        self._theme: dict[str, str] = {
            "bg": "#2E2E2E",
            "panel": "#404040",
            "accent": "#33CED6",  # Match the KnobWidget and UI theme
            "text": "#FFFFFF",
        }

        self._style_params = {
            "handle_w": 33.0,
            "handle_h": 49.0,
            "bevel_x": 7.0,
            "bevel_y": 8.0,
            "face_lightness": 85,
            "top_lightness": 155,
            "bottom_lightness": 83,
            "left_lightness": 130,
            "right_lightness": 108,
            "track_w": 4.0,
            "fill_w": 3.0,
            "indicator_h": 1.0,
            "tick_w": 44.0,
            "tick_alpha": 26,
            "tick_count": 11,
            "bg_radius": 16.0,
            "bg_alpha": 255,
        }

        self.setMouseTracking(True)
        if self._orientation == Qt.Orientation.Vertical:
            self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        else:
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def sizeHint(self) -> QSize:
        if self._orientation == Qt.Orientation.Vertical:
            return QSize(80, 200)
        return QSize(200, 80)

    def minimumSizeHint(self) -> QSize:
        if self._orientation == Qt.Orientation.Vertical:
            return QSize(60, 150)
        return QSize(150, 60)

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

    def _get_track_rect(self) -> QRectF:
        rect = self.rect()
        # Add padding for text labels when in horizontal orientation
        if self._orientation == Qt.Orientation.Vertical:
            margin_y = 20.0
            handle_h = self._style_params.get("handle_h", 49.0)
            usable_h = rect.height() - (margin_y * 2) - handle_h
            cx = rect.width() / 2.0
            return QRectF(cx, margin_y + handle_h / 2.0, 0, usable_h)
        else:
            margin_x = 20.0
            label_h = 16.0
            value_h = 16.0
            handle_w = self._style_params.get("handle_h", 49.0) # Swap W/H for horizontal track
            usable_w = rect.width() - (margin_x * 2) - handle_w
            
            # The usable area is between the label and value
            usable_area_y = label_h
            usable_area_h = rect.height() - label_h - value_h
            cy = usable_area_y + (usable_area_h / 2.0)
            
            return QRectF(margin_x + handle_w / 2.0, cy, usable_w, 0)

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
            track = self._get_track_rect()
            if self._orientation == Qt.Orientation.Vertical:
                if track.height() > 0:
                    dy = self._drag_start_pos.y() - event.position().y()
                    units_per_pixel = (self._maximum - self._minimum) / track.height()
                    next_value = self._drag_start_value + (dy * units_per_pixel)
                    self.setValue(next_value)
            else:
                if track.width() > 0:
                    dx = event.position().x() - self._drag_start_pos.x()
                    units_per_pixel = (self._maximum - self._minimum) / track.width()
                    next_value = self._drag_start_value + (dx * units_per_pixel)
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
            delta = event.angleDelta().x()
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

        bg_color = self._to_color("bg", "#2E2E2E")
        panel_color = self._to_color("panel", "#404040")
        accent_color = self._to_color("accent", "#33CED6")
        text_color = self._to_color("text", "#FFFFFF")

        rect = self.rect()
        cx = rect.width() / 2.0
        cy = rect.height() / 2.0

        # Optional background container 
        bg_radius = self._style_params.get("bg_radius", 16.0)
        bg_alpha = int(self._style_params.get("bg_alpha", 255))
        if bg_alpha > 0:
            container_color = QColor(bg_color).darker(110)
            container_color.setAlpha(bg_alpha)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(container_color)
            painter.drawRoundedRect(self.rect(), bg_radius, bg_radius)

        track_line = self._get_track_rect()

        # 1. Ticks
        tick_count = int(self._style_params.get("tick_count", 11))
        tick_span = self._style_params.get("tick_w", 44.0)
        tick_alpha = int(self._style_params.get("tick_alpha", 26))

        if tick_count > 1 and tick_alpha > 0:
            tick_color = QColor(text_color)
            tick_color.setAlpha(tick_alpha)
            tick_pen = QPen(tick_color)
            tick_pen.setWidthF(1.0)
            painter.setPen(tick_pen)

            for i in range(tick_count):
                t = i / (tick_count - 1)
                if self._orientation == Qt.Orientation.Vertical:
                    y = track_line.bottom() - (t * track_line.height())
                    painter.drawLine(QPointF(cx - tick_span / 2, y), QPointF(cx + tick_span / 2, y))
                else:
                    x = track_line.left() + (t * track_line.width())
                    painter.drawLine(QPointF(x, cy - tick_span / 2), QPointF(x, cy + tick_span / 2))

        # 2. Track
        track_w = self._style_params.get("track_w", 4.0)
        t_color = QColor(panel_color).darker(150)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(t_color)
        if self._orientation == Qt.Orientation.Vertical:
            painter.drawRect(QRectF(cx - track_w / 2, track_line.top(), track_w, track_line.height()))
        else:
            painter.drawRect(QRectF(track_line.left(), cy - track_w / 2, track_line.width(), track_w))

        # 3. Active Fill
        t_val = self._normalized()
        fill_w = self._style_params.get("fill_w", 3.0)
        painter.setBrush(accent_color)
        
        if self._orientation == Qt.Orientation.Vertical:
            handle_pos = track_line.bottom() - (t_val * track_line.height())
            fill_height = track_line.bottom() - handle_pos
            painter.drawRect(QRectF(cx - fill_w / 2, handle_pos, fill_w, fill_height))
        else:
            handle_pos = track_line.left() + (t_val * track_line.width())
            fill_width = handle_pos - track_line.left()
            painter.drawRect(QRectF(track_line.left(), cy - fill_w / 2, fill_width, fill_w))

        # 4. Handle (Fader Cap)
        hw = self._style_params.get("handle_w", 33.0)
        hh = self._style_params.get("handle_h", 49.0)
        bx = self._style_params.get("bevel_x", 7.0)
        by = self._style_params.get("bevel_y", 8.0)

        # Swap handle dimensions for horizontal orientation
        if self._orientation == Qt.Orientation.Horizontal:
            hw, hh = hh, hw
            bx, by = by, bx

        if self._orientation == Qt.Orientation.Vertical:
            hx = cx - hw / 2.0
            hy = handle_pos - hh / 2.0
        else:
            hx = handle_pos - hw / 2.0
            hy = cy - hh / 2.0

        # Drop shadow
        shadow_rect = QRectF(hx + 2, hy + 4, hw, hh)
        painter.setBrush(QColor(0, 0, 0, 100))
        painter.drawRect(shadow_rect)

        # Polygon coordinates
        out_tl = QPointF(hx, hy)
        out_tr = QPointF(hx + hw, hy)
        out_bl = QPointF(hx, hy + hh)
        out_br = QPointF(hx + hw, hy + hh)

        in_tl = QPointF(hx + bx, hy + by)
        in_tr = QPointF(hx + hw - bx, hy + by)
        in_bl = QPointF(hx + bx, hy + hh - by)
        in_br = QPointF(hx + hw - bx, hy + hh - by)

        def make_poly(*pts):
            poly = QPolygonF()
            for p in pts:
                poly.append(p)
            return poly

        poly_top = make_poly(out_tl, out_tr, in_tr, in_tl)
        poly_bottom = make_poly(in_bl, in_br, out_br, out_bl)
        poly_left = make_poly(out_tl, in_tl, in_bl, out_bl)
        poly_right = make_poly(in_tr, out_tr, out_br, in_br)
        poly_face = make_poly(in_tl, in_tr, in_br, in_bl)

        l_face = int(self._style_params.get("face_lightness", 85))
        l_top = int(self._style_params.get("top_lightness", 155))
        l_bottom = int(self._style_params.get("bottom_lightness", 83))
        l_left = int(self._style_params.get("left_lightness", 130))
        l_right = int(self._style_params.get("right_lightness", 108))

        # Rotate lighting if horizontal so it looks correctly lit from above
        if self._orientation == Qt.Orientation.Horizontal:
            l_top, l_bottom, l_left, l_right = l_left, l_right, l_bottom, l_top

        def get_shade(l):
            if l >= 100:
                return QColor(panel_color).lighter(l)
            else:
                return QColor(panel_color).darker(200 - l)

        painter.setPen(Qt.PenStyle.NoPen)

        painter.setBrush(get_shade(l_top))
        painter.drawPolygon(poly_top)

        painter.setBrush(get_shade(l_bottom))
        painter.drawPolygon(poly_bottom)

        painter.setBrush(get_shade(l_left))
        painter.drawPolygon(poly_left)

        painter.setBrush(get_shade(l_right))
        painter.drawPolygon(poly_right)

        painter.setBrush(get_shade(l_face))
        painter.drawPolygon(poly_face)

        # Handle indicator line
        ind_thickness = self._style_params.get("indicator_h", 1.0)
        painter.setBrush(accent_color)
        if self._orientation == Qt.Orientation.Vertical:
            painter.drawRect(QRectF(in_tl.x(), hy + hh / 2.0 - ind_thickness / 2.0, in_tr.x() - in_tl.x(), ind_thickness))
        else:
            painter.drawRect(QRectF(hx + hw / 2.0 - ind_thickness / 2.0, in_tl.y(), ind_thickness, in_bl.y() - in_tl.y()))

        # Draw text labels
        if self._orientation == Qt.Orientation.Horizontal and self._label:
            painter.setPen(text_color)
            margin_x = 20.0
            label_h = 16.0
            value_h = 16.0
            
            # Label on the top left
            label_rect = QRectF(margin_x, 0, rect.width() - margin_x * 2, label_h)
            fm = QFontMetrics(painter.font())
            available = int(max(0.0, label_rect.width() * 0.70))
            label_txt = fm.elidedText(str(self._label), Qt.TextElideMode.ElideRight, available)
            painter.drawText(label_rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), label_txt)

            # Value on the top right
            painter.drawText(
                label_rect,
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
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
