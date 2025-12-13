from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QCheckBox, QSlider, QGroupBox, QPushButton, QSpinBox, QDoubleSpinBox,
    QMessageBox, QStyledItemDelegate, QStyle, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QColor, QFont, QFontMetrics


class StretchMethodDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        painter.save()

        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        bg = option.palette.highlight().color() if selected else option.palette.base().color()
        painter.fillRect(option.rect, bg)

        label = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        info = str(index.data(Qt.ItemDataRole.UserRole) or "")

        rect = option.rect.adjusted(10, 6, -10, -6)

        label_font = QFont(option.font)
        label_font.setBold(True)
        painter.setFont(label_font)

        fg = option.palette.highlightedText().color() if selected else option.palette.text().color()
        painter.setPen(fg)
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop), label)

        info_font = QFont(option.font)
        info_font.setPointSize(max(7, int(info_font.pointSize() - 2)))
        painter.setFont(info_font)

        info_fg = fg if selected else QColor(51, 206, 214, 170)
        painter.setPen(info_fg)
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom), info)

        painter.restore()

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        return QSize(size.width(), max(size.height(), 52))


class SettingsPanel(QWidget):
    """
    Right-side panel with all the settings controls.
    """

    settings_changed = pyqtSignal()
    process_clicked = pyqtSignal()
    export_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setMinimumWidth(250)
        self.setMaximumWidth(350)

        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        note_group = QGroupBox("Target Note")
        note_layout = QVBoxLayout(note_group)

        note_row = QHBoxLayout()
        note_row.addWidget(QLabel("Note:"))
        self.note_combo = QComboBox()
        self.note_combo.addItems(["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"])
        self.note_combo.setCurrentText("C")
        note_row.addWidget(self.note_combo)
        note_layout.addLayout(note_row)

        octave_row = QHBoxLayout()
        octave_row.addWidget(QLabel("Octave:"))
        self.octave_spin = QSpinBox()
        self.octave_spin.setRange(2, 7)
        self.octave_spin.setValue(4)
        octave_row.addWidget(self.octave_spin)
        note_layout.addLayout(octave_row)

        self.target_label = QLabel("Target: C4 (261.63 Hz)")
        self.target_label.setStyleSheet("color: #33CED6; font-weight: bold;")
        note_layout.addWidget(self.target_label)

        layout.addWidget(note_group)

        process_group = QGroupBox("Processing")
        process_layout = QVBoxLayout(process_group)

        self.normalize_check = QCheckBox("Normalize to 0dB")
        self.normalize_check.setChecked(True)
        self.normalize_check.stateChanged.connect(lambda _s: self.settings_changed.emit())
        process_layout.addWidget(self.normalize_check)

        self.preserve_formants_check = QCheckBox("Preserve Formants")
        self.preserve_formants_check.setChecked(True)
        self.preserve_formants_check.stateChanged.connect(self._on_formant_toggle)
        process_layout.addWidget(self.preserve_formants_check)

        self.formant_widget = QWidget()
        formant_layout = QVBoxLayout(self.formant_widget)
        formant_layout.setContentsMargins(0, 0, 0, 0)

        formant_label_row = QHBoxLayout()
        formant_label_row.addWidget(QLabel("Formant Shift:"))
        self.formant_value_label = QLabel("0 ct")
        formant_label_row.addWidget(self.formant_value_label)
        formant_layout.addLayout(formant_label_row)

        self.formant_slider = QSlider(Qt.Orientation.Horizontal)
        self.formant_slider.setRange(-500, 500)
        self.formant_slider.setValue(0)
        self.formant_slider.valueChanged.connect(self._on_formant_slider)
        self.formant_slider.sliderReleased.connect(lambda: self.settings_changed.emit())
        formant_layout.addWidget(self.formant_slider)

        self.formant_widget.setVisible(False)
        process_layout.addWidget(self.formant_widget)

        self._stretch_factor_effective = 1.0
        self._stretch_factor_pending = 1.0
        self._stretch_over2_confirmed = False

        stretch_method_row = QHBoxLayout()
        stretch_method_row.addWidget(QLabel("Stretching Method:"), 0)
        self.stretch_method_combo = QComboBox()
        self.stretch_method_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.stretch_method_combo.setItemDelegate(StretchMethodDelegate(self.stretch_method_combo))
        self._populate_stretch_methods()
        self.stretch_method_combo.currentIndexChanged.connect(lambda _i: self.settings_changed.emit())
        stretch_method_row.addWidget(self.stretch_method_combo, 1)
        process_layout.addLayout(stretch_method_row)

        stretch_factor_label_row = QHBoxLayout()
        stretch_factor_label_row.addWidget(QLabel("Stretch Factor:"))
        self.stretch_value_label = QLabel("1.00x")
        stretch_factor_label_row.addWidget(self.stretch_value_label)
        process_layout.addLayout(stretch_factor_label_row)

        self.stretch_slider = QSlider(Qt.Orientation.Horizontal)
        self.stretch_slider.setRange(100, 500)
        self.stretch_slider.setSingleStep(1)
        self.stretch_slider.setPageStep(10)
        self.stretch_slider.setValue(100)
        self.stretch_slider.valueChanged.connect(self._on_stretch_slider_value_changed)
        self.stretch_slider.sliderReleased.connect(self._on_stretch_slider_released)
        process_layout.addWidget(self.stretch_slider)

        stretch_manual_row = QHBoxLayout()
        stretch_manual_row.addWidget(QLabel("Manual:"))
        self.stretch_spin = QDoubleSpinBox()
        self.stretch_spin.setRange(0.01, 9999.0)
        self.stretch_spin.setDecimals(2)
        self.stretch_spin.setSingleStep(0.01)
        self.stretch_spin.setValue(1.00)
        self.stretch_spin.setSuffix("x")
        self.stretch_spin.valueChanged.connect(self._on_stretch_spin_value_changed)
        self.stretch_spin.editingFinished.connect(self._on_stretch_spin_editing_finished)
        stretch_manual_row.addWidget(self.stretch_spin)
        process_layout.addLayout(stretch_manual_row)

        layout.addWidget(process_group)

        clean_group = QGroupBox("Cleanliness")
        clean_layout = QVBoxLayout(clean_group)

        clean_label_row = QHBoxLayout()
        clean_label_row.addWidget(QLabel("Amount:"))
        self.clean_value_label = QLabel("0%")
        clean_label_row.addWidget(self.clean_value_label)
        clean_layout.addLayout(clean_label_row)

        self.cleanliness_slider = QSlider(Qt.Orientation.Horizontal)
        self.cleanliness_slider.setRange(0, 100)
        self.cleanliness_slider.setValue(0)
        self.cleanliness_slider.valueChanged.connect(self._on_cleanliness_slider)
        self.cleanliness_slider.sliderReleased.connect(lambda: self.settings_changed.emit())
        clean_layout.addWidget(self.cleanliness_slider)

        clean_warning = QLabel("High values = robotic sound")
        clean_warning.setStyleSheet("color: rgba(51, 206, 214, 170); font-size: 10px;")
        clean_layout.addWidget(clean_warning)

        layout.addWidget(clean_group)

        info_group = QGroupBox("Detected Pitch")
        info_layout = QVBoxLayout(info_group)

        self.detected_label = QLabel("No audio loaded")
        self.detected_label.setStyleSheet("color: rgba(51, 206, 214, 170);")
        info_layout.addWidget(self.detected_label)

        layout.addWidget(info_group)

        button_layout = QVBoxLayout()

        self.export_btn = QPushButton("Export WAV")
        self.export_btn.setStyleSheet("""
            QPushButton {
                background-color: #404040;
                color: white;
                border: 1px solid #1D5AAA;
                padding: 10px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #1D5AAA;
            }
            QPushButton:disabled {
                background-color: #2E2E2E;
                border-color: #404040;
            }
        """)
        self.export_btn.clicked.connect(lambda: self.export_clicked.emit())
        button_layout.addWidget(self.export_btn)

        layout.addLayout(button_layout)

        layout.addStretch()

        self.note_combo.currentTextChanged.connect(self._update_target_label)
        self.octave_spin.valueChanged.connect(self._update_target_label)
        self._update_target_label()

    def _update_target_label(self):
        """Update the target note display label."""
        note = self.note_combo.currentText()
        octave = self.octave_spin.value()

        note_names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
        semitone = note_names.index(note)
        midi = 12 * (octave + 1) + semitone
        freq = 440.0 * (2 ** ((midi - 69) / 12))

        self.target_label.setText(f"Target: {note}{octave} ({freq:.2f} Hz)")
        self.settings_changed.emit()

    def _on_formant_toggle(self, state):
        """Show/hide formant slider based on checkbox."""
        self.formant_widget.setVisible(state == 0)
        self.settings_changed.emit()

    def _on_formant_slider(self, value):
        """Update formant slider label."""
        self.formant_value_label.setText(f"{value} ct")

    def _on_cleanliness_slider(self, value):
        """Update cleanliness slider label."""
        self.clean_value_label.setText(f"{value}%")

    def _populate_stretch_methods(self):
        role_info = int(Qt.ItemDataRole.UserRole)
        role_key = int(Qt.ItemDataRole.UserRole) + 1

        items = [
            (
                "WSOLA Speech",
                "Crisp in quality and the best for general speech audio. Can sound robotic if over-done.",
                "audiotsm_wsola",
            ),
            (
                "Phasevocoder",
                "Smoother and more ideal under x2 stretching",
                "audiotsm_phasevocoder",
            ),
            (
                "Rubberband Default",
                "Baseline of any stretching method.",
                "rubberband_default_engine_finer",
            ),
            (
                "Rubberband Percussive",
                "Deals with transients and artifact removal a lot better than Rubberband Default.",
                "rubberband_percussive_engine_finer",
            ),
        ]

        self.stretch_method_combo.clear()
        for label, info, key in items:
            idx = self.stretch_method_combo.count()
            self.stretch_method_combo.addItem(label)
            self.stretch_method_combo.setItemData(idx, info, role_info)
            self.stretch_method_combo.setItemData(idx, key, role_key)

        fm = QFontMetrics(self.stretch_method_combo.font())
        max_w = 0
        for label, info, _key in items:
            max_w = max(max_w, fm.horizontalAdvance(label), fm.horizontalAdvance(info))
        view = self.stretch_method_combo.view()
        view.setTextElideMode(Qt.TextElideMode.ElideNone)
        desired = max_w + 60
        view.setMinimumWidth(max(320, min(520, desired)))

        self.stretch_method_combo.setCurrentIndex(0)

    def _confirm_over_2x(self, requested: float) -> bool:
        msg = QMessageBox(self)
        msg.setWindowTitle("Warning")
        msg.setText("Going over x2 can cause a lot of artifacts and could make your sample sound fake.")
        msg.setInformativeText(f"Requested: {float(requested):.2f}x")
        yes_btn = msg.addButton("hell yeah!", QMessageBox.ButtonRole.AcceptRole)
        no_btn = msg.addButton("hell no!!", QMessageBox.ButtonRole.RejectRole)
        msg.setDefaultButton(no_btn)
        msg.exec()
        return msg.clickedButton() == yes_btn

    def _apply_stretch_effective(self, factor: float, emit: bool):
        f = float(factor)
        self._stretch_factor_effective = f
        if f <= 2.0:
            self._stretch_over2_confirmed = False

        self.stretch_value_label.setText(f"{f:.2f}x")

        self.stretch_spin.blockSignals(True)
        self.stretch_spin.setValue(f)
        self.stretch_spin.blockSignals(False)

        if f <= 5.0:
            self.stretch_slider.blockSignals(True)
            self.stretch_slider.setValue(int(round(f * 100.0)))
            self.stretch_slider.blockSignals(False)
        else:
            self.stretch_slider.blockSignals(True)
            self.stretch_slider.setValue(500)
            self.stretch_slider.blockSignals(False)

        if emit:
            self.settings_changed.emit()

    def _apply_stretch_pending_ui(self, factor: float):
        f = float(factor)
        self._stretch_factor_pending = f
        self.stretch_value_label.setText(f"{f:.2f}x")

        self.stretch_spin.blockSignals(True)
        self.stretch_spin.setValue(f)
        self.stretch_spin.blockSignals(False)

        if f <= 5.0:
            self.stretch_slider.blockSignals(True)
            self.stretch_slider.setValue(int(round(f * 100.0)))
            self.stretch_slider.blockSignals(False)
        else:
            self.stretch_slider.blockSignals(True)
            self.stretch_slider.setValue(500)
            self.stretch_slider.blockSignals(False)

    def _on_stretch_slider_value_changed(self, value: int):
        factor = float(value) / 100.0
        self._apply_stretch_pending_ui(factor)

    def _on_stretch_slider_released(self):
        requested = float(self._stretch_factor_pending)

        if requested <= 2.0 or self._stretch_over2_confirmed:
            self._apply_stretch_effective(requested, emit=True)
            return

        if self._confirm_over_2x(requested):
            self._stretch_over2_confirmed = True
            self._apply_stretch_effective(requested, emit=True)
        else:
            self._apply_stretch_effective(2.0, emit=True)

    def _on_stretch_spin_value_changed(self, value: float):
        v = float(value)
        self._apply_stretch_pending_ui(v)

    def _on_stretch_spin_editing_finished(self):
        requested = float(self.stretch_spin.value())
        if requested <= 2.0 or self._stretch_over2_confirmed:
            self._apply_stretch_effective(requested, emit=True)
            return

        if self._confirm_over_2x(requested):
            self._stretch_over2_confirmed = True
            self._apply_stretch_effective(requested, emit=True)
        else:
            self._apply_stretch_effective(2.0, emit=True)

    def get_target_note(self) -> str:
        """Get the full target note name, e.g. 'C4'."""
        return f"{self.note_combo.currentText()}{self.octave_spin.value()}"

    def get_settings(self) -> dict:
        """Get all current settings as a dictionary."""
        role_key = int(Qt.ItemDataRole.UserRole) + 1
        return {
            "target_note": self.get_target_note(),
            "normalize": self.normalize_check.isChecked(),
            "preserve_formants": self.preserve_formants_check.isChecked(),
            "formant_shift_cents": self.formant_slider.value() if not self.preserve_formants_check.isChecked() else 0,
            "cleanliness_percent": self.cleanliness_slider.value(),
            "stretch_method": self.stretch_method_combo.currentData(role_key),
            "stretch_factor": float(self._stretch_factor_effective),
        }

    def set_detected_pitch(self, note_name: str, freq: float, cents: int):
        """Update the detected pitch display."""
        if note_name is None:
            self.detected_label.setText("No pitch detected")
            self.detected_label.setStyleSheet("color: #1D5AAA;")
        else:
            cents_str = f"+{cents}" if cents >= 0 else str(cents)
            self.detected_label.setText(f"{note_name} ({freq:.1f} Hz, {cents_str} ct)")
            self.detected_label.setStyleSheet("color: #4EDE83;")

    def set_buttons_enabled(self, process: bool, export: bool):
        """Enable/disable action buttons."""
        if hasattr(self, "process_btn") and self.process_btn is not None:
            self.process_btn.setEnabled(process)
        self.export_btn.setEnabled(export)
