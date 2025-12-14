from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QCheckBox, QSlider, QGroupBox, QPushButton, QSpinBox, QDoubleSpinBox,
    QMessageBox, QStyledItemDelegate, QStyle, QSizePolicy, QTabWidget
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QStandardItem, QStandardItemModel

import importlib


class StretchMethodDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme_selected_bg = QColor("#6B999F")
        self._theme_info_fg = QColor(51, 206, 214, 170)

    def set_theme(self, theme: dict):
        try:
            hl = str(theme.get("highlight", "#6B999F"))
            acc = str(theme.get("accent", "#33CED6"))
            self._theme_selected_bg = QColor(hl)
            c = QColor(acc)
            self._theme_info_fg = QColor(c.red(), c.green(), c.blue(), 170)
        except Exception:
            pass

    def paint(self, painter, option, index):
        painter.save()

        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        bg = self._theme_selected_bg if selected else option.palette.base().color()
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

        info_fg = fg if selected else self._theme_info_fg
        painter.setPen(info_fg)
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom), info)

        painter.restore()

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        return QSize(size.width(), max(size.height(), 52))


class PitchModeDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme_selected_bg = QColor("#6B999F")
        self._theme_info_fg = QColor(51, 206, 214, 170)

    def set_theme(self, theme: dict):
        try:
            hl = str(theme.get("highlight", "#6B999F"))
            acc = str(theme.get("accent", "#33CED6"))
            self._theme_selected_bg = QColor(hl)
            c = QColor(acc)
            self._theme_info_fg = QColor(c.red(), c.green(), c.blue(), 170)
        except Exception:
            pass

    def paint(self, painter, option, index):
        painter.save()

        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        bg = self._theme_selected_bg if selected else option.palette.base().color()
        painter.fillRect(option.rect, bg)

        label = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        info = str(index.data(int(Qt.ItemDataRole.UserRole) + 1) or "")

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

        info_fg = fg if selected else self._theme_info_fg
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
    quick_export_clicked = pyqtSignal()
    themes_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setMinimumWidth(250)
        self.setMaximumWidth(350)

        self._theme = None
        self._sample_rate = 44100

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(False)

        controls_page = QWidget()
        layout = QVBoxLayout(controls_page)
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

        pitch_mode_row = QHBoxLayout()
        pitch_mode_row.addWidget(QLabel("Pitch Mode:"), 0)
        self.pitch_mode_combo = QComboBox()
        self.pitch_mode_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.pitch_mode_combo.setItemDelegate(PitchModeDelegate(self.pitch_mode_combo))
        self._populate_pitch_modes()
        self.pitch_mode_combo.currentIndexChanged.connect(self._on_pitch_mode_changed)
        pitch_mode_row.addWidget(self.pitch_mode_combo, 1)
        process_layout.addLayout(pitch_mode_row)

        self.normalize_check = QCheckBox("Normalize to 0dB")
        self.normalize_check.setChecked(False)
        self.normalize_check.stateChanged.connect(lambda _s: self.settings_changed.emit())
        process_layout.addWidget(self.normalize_check)

        self.preserve_formants_check = QCheckBox("Preserve Formants")
        self.preserve_formants_check.setChecked(True)
        self.preserve_formants_check.stateChanged.connect(self._on_formant_toggle)
        process_layout.addWidget(self.preserve_formants_check)

        self.soft_widget = QWidget()
        soft_layout = QVBoxLayout(self.soft_widget)
        soft_layout.setContentsMargins(0, 0, 0, 0)

        amount_row = QHBoxLayout()
        amount_row.addWidget(QLabel("Correction Amount:"))
        self.pitch_amount_value_label = QLabel("100%")
        amount_row.addWidget(self.pitch_amount_value_label)
        soft_layout.addLayout(amount_row)

        self.pitch_amount_slider = QSlider(Qt.Orientation.Horizontal)
        self.pitch_amount_slider.setRange(0, 100)
        self.pitch_amount_slider.setValue(100)
        self.pitch_amount_slider.valueChanged.connect(self._on_pitch_amount_slider)
        self.pitch_amount_slider.sliderReleased.connect(lambda: self.settings_changed.emit())
        soft_layout.addWidget(self.pitch_amount_slider)

        retune_row = QHBoxLayout()
        retune_row.addWidget(QLabel("Retune Speed:"))
        self.retune_speed_value_label = QLabel("40 ms")
        retune_row.addWidget(self.retune_speed_value_label)
        soft_layout.addLayout(retune_row)

        self.retune_speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.retune_speed_slider.setRange(0, 200)
        self.retune_speed_slider.setValue(40)
        self.retune_speed_slider.valueChanged.connect(self._on_retune_speed_slider)
        self.retune_speed_slider.sliderReleased.connect(lambda: self.settings_changed.emit())
        soft_layout.addWidget(self.retune_speed_slider)

        vib_row = QHBoxLayout()
        vib_row.addWidget(QLabel("Preserve Vibrato:"))
        self.preserve_vibrato_value_label = QLabel("100%")
        vib_row.addWidget(self.preserve_vibrato_value_label)
        soft_layout.addLayout(vib_row)

        self.preserve_vibrato_slider = QSlider(Qt.Orientation.Horizontal)
        self.preserve_vibrato_slider.setRange(0, 100)
        self.preserve_vibrato_slider.setValue(100)
        self.preserve_vibrato_slider.valueChanged.connect(self._on_preserve_vibrato_slider)
        self.preserve_vibrato_slider.sliderReleased.connect(lambda: self.settings_changed.emit())
        soft_layout.addWidget(self.preserve_vibrato_slider)

        self.soft_widget.setVisible(False)
        process_layout.addWidget(self.soft_widget)

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

        self.clean_advanced_check = QCheckBox("Advanced Mode")
        self.clean_advanced_check.setChecked(False)
        self.clean_advanced_check.stateChanged.connect(self._on_clean_advanced_toggled)
        clean_layout.addWidget(self.clean_advanced_check)

        self.clean_warning_label = QLabel("High values = robotic sound")
        self.clean_warning_label.setStyleSheet("color: rgba(51, 206, 214, 170); font-size: 10px;")
        clean_layout.addWidget(self.clean_warning_label)

        self.clean_advanced_widget = QWidget()
        clean_adv_layout = QVBoxLayout(self.clean_advanced_widget)
        clean_adv_layout.setContentsMargins(0, 0, 0, 0)

        lowcut_label_row = QHBoxLayout()
        lowcut_label_row.addWidget(QLabel("Low Cut:"))
        self.clean_lowcut_value_label = QLabel("50 Hz")
        lowcut_label_row.addWidget(self.clean_lowcut_value_label)
        clean_adv_layout.addLayout(lowcut_label_row)

        self.clean_lowcut_slider = QSlider(Qt.Orientation.Horizontal)
        self.clean_lowcut_slider.setRange(0, 200)
        self.clean_lowcut_slider.setValue(50)
        self.clean_lowcut_slider.valueChanged.connect(self._on_clean_lowcut_slider)
        self.clean_lowcut_slider.sliderReleased.connect(lambda: self.settings_changed.emit())
        clean_adv_layout.addWidget(self.clean_lowcut_slider)

        hs_gain_row = QHBoxLayout()
        hs_gain_row.addWidget(QLabel("High Shelf:"))
        self.clean_high_shelf_gain_label = QLabel("0 dB")
        hs_gain_row.addWidget(self.clean_high_shelf_gain_label)
        clean_adv_layout.addLayout(hs_gain_row)

        self.clean_high_shelf_gain_slider = QSlider(Qt.Orientation.Horizontal)
        self.clean_high_shelf_gain_slider.setRange(-24, 0)
        self.clean_high_shelf_gain_slider.setValue(0)
        self.clean_high_shelf_gain_slider.valueChanged.connect(self._on_clean_high_shelf_gain_slider)
        self.clean_high_shelf_gain_slider.sliderReleased.connect(lambda: self.settings_changed.emit())
        clean_adv_layout.addWidget(self.clean_high_shelf_gain_slider)

        hs_freq_row = QHBoxLayout()
        hs_freq_row.addWidget(QLabel("Shelf Freq:"))
        self.clean_high_shelf_freq_spin = QSpinBox()
        self.clean_high_shelf_freq_spin.setRange(2000, 48000)
        self.clean_high_shelf_freq_spin.setSingleStep(250)
        self.clean_high_shelf_freq_spin.setValue(10000)
        self.clean_high_shelf_freq_spin.setSuffix(" Hz")
        self.clean_high_shelf_freq_spin.valueChanged.connect(lambda _v: self.settings_changed.emit())
        hs_freq_row.addWidget(self.clean_high_shelf_freq_spin)
        clean_adv_layout.addLayout(hs_freq_row)

        clean_layout.addWidget(self.clean_advanced_widget)

        layout.addWidget(clean_group)

        info_group = QGroupBox("Detected Pitch")
        info_layout = QVBoxLayout(info_group)

        self.detected_label = QLabel("No audio loaded")
        self.detected_label.setStyleSheet("color: rgba(51, 206, 214, 170);")
        info_layout.addWidget(self.detected_label)

        layout.addWidget(info_group)

        button_layout = QVBoxLayout()

        self.export_btn = QPushButton("Export WAV")
        self.export_btn.clicked.connect(lambda: self.export_clicked.emit())
        button_layout.addWidget(self.export_btn)

        self.quick_export_btn = QPushButton("Quick Export")
        self.quick_export_btn.clicked.connect(lambda: self.quick_export_clicked.emit())
        button_layout.addWidget(self.quick_export_btn)

        layout.addLayout(button_layout)

        layout.addStretch()

        themes_page = QWidget()
        themes_layout = QVBoxLayout(themes_page)
        themes_layout.setSpacing(12)
        themes_layout.addWidget(QLabel("Customize the app colors."))
        self.open_theme_editor_btn = QPushButton("Open Theme Editor")
        self.open_theme_editor_btn.clicked.connect(lambda: self.themes_requested.emit())
        themes_layout.addWidget(self.open_theme_editor_btn)
        themes_layout.addStretch()

        self.tabs.addTab(controls_page, "Settings")
        self.tabs.addTab(themes_page, "Themes")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        root_layout.addWidget(self.tabs)

        self.note_combo.currentTextChanged.connect(self._update_target_label)
        self.octave_spin.valueChanged.connect(self._update_target_label)
        self._update_target_label()

        self._on_pitch_mode_changed(0)
        self._on_clean_lowcut_slider(int(self.clean_lowcut_slider.value()))
        self._on_clean_high_shelf_gain_slider(int(self.clean_high_shelf_gain_slider.value()))
        self._apply_cleanliness_mode_ui()

    def _on_tab_changed(self, index: int):
        try:
            if self.tabs.tabText(int(index)) == "Themes":
                self.themes_requested.emit()
        except Exception:
            pass

    def apply_theme(self, theme: dict):
        self._theme = dict(theme) if isinstance(theme, dict) else None
        t = self._theme or {}
        accent = str(t.get("accent", "#33CED6"))
        primary = str(t.get("primary", "#1D5AAA"))
        _bg = str(t.get("bg", "#2E2E2E"))
        _panel = str(t.get("panel", "#404040"))
        _text = str(t.get("text", "#ffffff"))

        try:
            self.target_label.setStyleSheet(f"color: {accent}; font-weight: bold;")
        except Exception:
            pass

        try:
            c = QColor(accent)
            if c.isValid():
                rgba = f"rgba({c.red()}, {c.green()}, {c.blue()}, 170)"
                if hasattr(self, "clean_warning_label") and self.clean_warning_label is not None:
                    self.clean_warning_label.setStyleSheet(f"color: {rgba}; font-size: 10px;")
                if hasattr(self, "detected_label") and self.detected_label is not None:
                    self.detected_label.setStyleSheet(f"color: {rgba};")
        except Exception:
            pass

        try:
            delegate = self.stretch_method_combo.itemDelegate()
            if isinstance(delegate, StretchMethodDelegate):
                delegate.set_theme(t)
                self.stretch_method_combo.view().viewport().update()
        except Exception:
            pass

        try:
            delegate = self.pitch_mode_combo.itemDelegate()
            if isinstance(delegate, PitchModeDelegate):
                delegate.set_theme(t)
                self.pitch_mode_combo.view().viewport().update()
        except Exception:
            pass

    def reset_to_defaults(self):
        role_key = int(Qt.ItemDataRole.UserRole) + 1
        default_stretch_method = None
        try:
            model = self.stretch_method_combo.model()
            for i in range(int(self.stretch_method_combo.count())):
                it = None
                try:
                    it = model.item(i)
                except Exception:
                    it = None

                if it is not None and not it.isEnabled():
                    continue

                default_stretch_method = self.stretch_method_combo.itemData(i, role_key)
                break
        except Exception:
            default_stretch_method = None

        self.apply_ui_state(
            {
                "note": "C",
                "octave": 4,
                "pitch_mode": "praat_soft",
                "pitch_amount": 100,
                "retune_speed_ms": 40,
                "preserve_vibrato": 100,
                "normalize": False,
                "preserve_formants": True,
                "formant_shift_cents": 0,
                "stretch_method": default_stretch_method,
                "stretch_factor": 1.0,
                "cleanliness_percent": 0,
                "clean_advanced_mode": False,
                "clean_lowcut_hz": 50,
                "clean_high_shelf_db": 0,
                "clean_high_shelf_hz": 10000,
            }
        )

    def get_ui_state(self) -> dict:
        role_key = int(Qt.ItemDataRole.UserRole) + 1
        return {
            "note": str(self.note_combo.currentText()),
            "octave": int(self.octave_spin.value()),
            "pitch_mode": str(self.pitch_mode_combo.currentData()),
            "pitch_amount": int(self.pitch_amount_slider.value()),
            "retune_speed_ms": int(self.retune_speed_slider.value()),
            "preserve_vibrato": int(self.preserve_vibrato_slider.value()),
            "normalize": bool(self.normalize_check.isChecked()),
            "preserve_formants": bool(self.preserve_formants_check.isChecked()),
            "formant_shift_cents": int(self.formant_slider.value()),
            "stretch_method": self.stretch_method_combo.currentData(role_key),
            "stretch_factor": float(self._stretch_factor_effective),
            "cleanliness_percent": int(self.cleanliness_slider.value()),
            "clean_advanced_mode": bool(self.clean_advanced_check.isChecked()),
            "clean_lowcut_hz": int(self.clean_lowcut_slider.value()),
            "clean_high_shelf_db": int(self.clean_high_shelf_gain_slider.value()),
            "clean_high_shelf_hz": int(self.clean_high_shelf_freq_spin.value()),
        }

    def apply_ui_state(self, state: dict):
        role_key = int(Qt.ItemDataRole.UserRole) + 1

        note = state.get("note")
        octave = state.get("octave")
        pitch_mode = state.get("pitch_mode")
        pitch_amount = state.get("pitch_amount")
        retune_speed_ms = state.get("retune_speed_ms")
        preserve_vibrato = state.get("preserve_vibrato")
        normalize = state.get("normalize")
        preserve_formants = state.get("preserve_formants")
        formant_shift_cents = state.get("formant_shift_cents")
        stretch_method = state.get("stretch_method")
        stretch_factor = state.get("stretch_factor")
        cleanliness_percent = state.get("cleanliness_percent")
        clean_advanced_mode = state.get("clean_advanced_mode")
        clean_lowcut_hz = state.get("clean_lowcut_hz")
        clean_high_shelf_db = state.get("clean_high_shelf_db")
        clean_high_shelf_hz = state.get("clean_high_shelf_hz")

        self.blockSignals(True)
        try:
            if note is not None:
                self.note_combo.setCurrentText(str(note))
            if octave is not None:
                self.octave_spin.setValue(int(octave))
            if pitch_mode is not None:
                try:
                    pitch_mode_set = False
                    for i in range(int(self.pitch_mode_combo.count())):
                        if self.pitch_mode_combo.itemData(i) == pitch_mode:
                            model = self.pitch_mode_combo.model()
                            it = None
                            try:
                                it = model.item(i)
                            except Exception:
                                it = None
                            if it is None or bool(it.isEnabled()):
                                self.pitch_mode_combo.setCurrentIndex(int(i))
                                pitch_mode_set = True
                            break

                    if not bool(pitch_mode_set):
                        model = self.pitch_mode_combo.model()
                        for i in range(int(self.pitch_mode_combo.count())):
                            it = None
                            try:
                                it = model.item(i)
                            except Exception:
                                it = None
                            if it is None or bool(it.isEnabled()):
                                self.pitch_mode_combo.setCurrentIndex(int(i))
                                break
                except Exception:
                    pass
            if pitch_amount is not None:
                self.pitch_amount_slider.setValue(int(pitch_amount))
            if retune_speed_ms is not None:
                self.retune_speed_slider.setValue(int(retune_speed_ms))
            if preserve_vibrato is not None:
                self.preserve_vibrato_slider.setValue(int(preserve_vibrato))
            if normalize is not None:
                self.normalize_check.setChecked(bool(normalize))
            if preserve_formants is not None:
                self.preserve_formants_check.setChecked(bool(preserve_formants))
            if formant_shift_cents is not None:
                self.formant_slider.setValue(int(formant_shift_cents))
            if cleanliness_percent is not None:
                self.cleanliness_slider.setValue(int(cleanliness_percent))

            if clean_advanced_mode is not None:
                self.clean_advanced_check.setChecked(bool(clean_advanced_mode))

            if clean_lowcut_hz is not None:
                self.clean_lowcut_slider.setValue(int(clean_lowcut_hz))

            if clean_high_shelf_db is not None:
                self.clean_high_shelf_gain_slider.setValue(int(clean_high_shelf_db))

            if clean_high_shelf_hz is not None:
                self.clean_high_shelf_freq_spin.setValue(int(clean_high_shelf_hz))

            if stretch_method is not None:
                try:
                    for i in range(int(self.stretch_method_combo.count())):
                        if self.stretch_method_combo.itemData(i, role_key) == stretch_method:
                            self.stretch_method_combo.setCurrentIndex(i)
                            break
                except Exception:
                    pass

            if stretch_factor is not None:
                try:
                    self._stretch_over2_confirmed = False
                    self._apply_stretch_effective(float(stretch_factor), emit=False)
                except Exception:
                    pass

            self._update_target_label()

        finally:
            self.blockSignals(False)
        try:
            self._apply_cleanliness_mode_ui()
        except Exception:
            pass
        try:
            self._apply_cleanliness_automation(int(self.cleanliness_slider.value()))
        except Exception:
            pass
        self.settings_changed.emit()

    def _on_pitch_mode_changed(self, _index: int):
        mode = str(self.pitch_mode_combo.currentData())
        is_soft = mode in ("world_soft", "praat_soft")
        self.soft_widget.setVisible(bool(is_soft))
        self.settings_changed.emit()

    def _on_pitch_amount_slider(self, value: int):
        self.pitch_amount_value_label.setText(f"{int(value)}%")

    def _on_retune_speed_slider(self, value: int):
        self.retune_speed_value_label.setText(f"{int(value)} ms")

    def _on_preserve_vibrato_slider(self, value: int):
        self.preserve_vibrato_value_label.setText(f"{int(value)}%")

    def _update_target_label(self):
        """Update the target note display label."""
        note = self.note_combo.currentText()
        octave = self.octave_spin.value()

        note_names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
        semitone = note_names.index(note)
        midi = 12 * (octave + 1) + semitone
        freq = 440.0 * (2 ** ((midi - 69) / 12))

        self.target_label.setText(f"Target: {note}{octave} ({freq:.2f} Hz)")
        try:
            self._apply_cleanliness_automation(int(self.cleanliness_slider.value()))
        except Exception:
            pass
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
        try:
            self._apply_cleanliness_automation(int(value))
        except Exception:
            pass

    def _on_clean_lowcut_slider(self, value: int):
        v = int(value)
        if v <= 0:
            self.clean_lowcut_value_label.setText("Off")
        else:
            self.clean_lowcut_value_label.setText(f"{v} Hz")

    def _on_clean_high_shelf_gain_slider(self, value: int):
        self.clean_high_shelf_gain_label.setText(f"{int(value)} dB")

    def _on_clean_advanced_toggled(self, _state: int):
        try:
            self._apply_cleanliness_mode_ui()
        except Exception:
            pass
        try:
            self._apply_cleanliness_automation(int(self.cleanliness_slider.value()))
        except Exception:
            pass
        self.settings_changed.emit()

    def _apply_cleanliness_mode_ui(self):
        advanced = bool(self.clean_advanced_check.isChecked())
        if hasattr(self, "clean_advanced_widget") and self.clean_advanced_widget is not None:
            self.clean_advanced_widget.setVisible(bool(advanced))
        self.clean_lowcut_slider.setEnabled(bool(advanced))
        self.clean_high_shelf_gain_slider.setEnabled(bool(advanced))
        self.clean_high_shelf_freq_spin.setEnabled(bool(advanced))

    def _get_target_f0_hz(self) -> float:
        note = str(self.note_combo.currentText())
        octave = int(self.octave_spin.value())

        note_names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
        try:
            semitone = int(note_names.index(note))
        except Exception:
            semitone = 0
        midi = 12 * (octave + 1) + semitone
        return float(440.0 * (2 ** ((midi - 69) / 12)))

    def _get_nyquist_hz(self) -> float:
        try:
            sr = int(self._sample_rate)
        except Exception:
            sr = 44100
        if sr <= 0:
            sr = 44100
        return float(sr) / 2.0

    def _apply_cleanliness_automation(self, amount: int):
        if bool(self.clean_advanced_check.isChecked()):
            return

        a = float(max(0, min(100, int(amount))))
        f0 = float(self._get_target_f0_hz())
        margin = float(min(20.0, 0.10 * f0))
        lowcut_25 = float(max(0.0, f0 - margin))

        if a <= 0.0:
            lowcut = 0.0
        elif a < 25.0:
            lowcut = lowcut_25 * (a / 25.0)
        else:
            lowcut = lowcut_25

        lowcut_i = int(round(max(0.0, min(float(self.clean_lowcut_slider.maximum()), lowcut))))

        nyq = float(self._get_nyquist_hz())
        nyq_ui = float(max(float(self.clean_high_shelf_freq_spin.minimum()), min(float(self.clean_high_shelf_freq_spin.maximum()), nyq)))

        if a <= 25.0:
            shelf_db = 0.0
            shelf_hz = nyq_ui
        else:
            t = float((a - 25.0) / 75.0)
            shelf_db = -24.0 * t
            shelf_hz = nyq_ui + (10000.0 - nyq_ui) * t
            shelf_hz = float(max(10000.0, min(nyq_ui, shelf_hz)))

        shelf_db_i = int(round(max(float(self.clean_high_shelf_gain_slider.minimum()), min(float(self.clean_high_shelf_gain_slider.maximum()), shelf_db))))
        shelf_hz_i = int(round(max(float(self.clean_high_shelf_freq_spin.minimum()), min(float(self.clean_high_shelf_freq_spin.maximum()), shelf_hz))))

        self.clean_lowcut_slider.blockSignals(True)
        self.clean_high_shelf_gain_slider.blockSignals(True)
        self.clean_high_shelf_freq_spin.blockSignals(True)
        try:
            self.clean_lowcut_slider.setValue(int(lowcut_i))
            self.clean_high_shelf_gain_slider.setValue(int(shelf_db_i))
            self.clean_high_shelf_freq_spin.setValue(int(shelf_hz_i))
        finally:
            self.clean_lowcut_slider.blockSignals(False)
            self.clean_high_shelf_gain_slider.blockSignals(False)
            self.clean_high_shelf_freq_spin.blockSignals(False)

        self._on_clean_lowcut_slider(int(self.clean_lowcut_slider.value()))
        self._on_clean_high_shelf_gain_slider(int(self.clean_high_shelf_gain_slider.value()))

    def _populate_stretch_methods(self):
        role_info = int(Qt.ItemDataRole.UserRole)
        role_key = int(Qt.ItemDataRole.UserRole) + 1

        def _module_available(name: str) -> bool:
            try:
                importlib.import_module(str(name))
                return True
            except Exception:
                return False

        audiotsm_available = _module_available("audiotsm")
        pylibrb_available = _module_available("pylibrb")
        librosa_available = _module_available("librosa")

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
            (
                "TD-PSOLA",
                "Fallback stretcher that works without audiotsm/rubberband (can be slower).",
                "tdpsola",
            ),
        ]

        model = QStandardItemModel(self.stretch_method_combo)
        for label, info, key in items:
            enabled = True
            if str(key).startswith("audiotsm_"):
                enabled = bool(audiotsm_available)
            elif str(key).startswith("rubberband_"):
                enabled = bool(pylibrb_available)
            elif str(key) == "tdpsola":
                enabled = bool(librosa_available)

            item = QStandardItem(str(label))
            item.setData(str(info), role_info)
            item.setData(str(key), role_key)
            item.setEnabled(bool(enabled))
            model.appendRow(item)

        self.stretch_method_combo.setModel(model)

        fm = QFontMetrics(self.stretch_method_combo.font())
        max_w = 0
        for label, info, _key in items:
            max_w = max(max_w, fm.horizontalAdvance(label), fm.horizontalAdvance(info))
        view = self.stretch_method_combo.view()
        view.setTextElideMode(Qt.TextElideMode.ElideNone)
        desired = max_w + 60
        view.setMinimumWidth(max(320, min(520, desired)))

        selected = None
        for i in range(model.rowCount()):
            it = model.item(i)
            if it is not None and it.isEnabled():
                selected = i
                break

        self.stretch_method_combo.setCurrentIndex(int(selected) if selected is not None else 0)

    def _populate_pitch_modes(self):
        role_key = int(Qt.ItemDataRole.UserRole)
        role_info = int(Qt.ItemDataRole.UserRole) + 1

        def _module_available(name: str) -> bool:
            try:
                importlib.import_module(str(name))
                return True
            except Exception:
                return False

        praat_available = _module_available("parselmouth")

        items = [
            (
                "PSOLA (Praat) Soft",
                "Natural + smooth retune using Praat overlap-add. Requires praat-parselmouth.",
                "praat_soft",
                bool(praat_available),
            ),
            (
                "WORLD Soft (Retune)",
                "Smooth retune with amount/speed/vibrato controls (WORLD vocoder).",
                "world_soft",
                True,
            ),
            (
                "WORLD Hard (Flatten)",
                "Hard snap to the target note for the most robotic/locked sound (WORLD vocoder).",
                "world_hard",
                True,
            ),
        ]

        model = QStandardItemModel(self.pitch_mode_combo)
        for label, info, key, enabled in items:
            item = QStandardItem(str(label))
            item.setData(str(key), role_key)
            item.setData(str(info), role_info)
            item.setEnabled(bool(enabled))
            model.appendRow(item)

        self.pitch_mode_combo.setModel(model)

        default_index = None
        for i in range(int(self.pitch_mode_combo.count())):
            it = None
            try:
                it = model.item(i)
            except Exception:
                it = None
            if it is None or bool(it.isEnabled()):
                default_index = int(i)
                break

        if default_index is not None:
            try:
                self.pitch_mode_combo.setCurrentIndex(int(default_index))
            except Exception:
                pass

        fm = QFontMetrics(self.pitch_mode_combo.font())
        max_w = 0
        for label, info, _key, _enabled in items:
            max_w = max(max_w, fm.horizontalAdvance(label), fm.horizontalAdvance(info))
        view = self.pitch_mode_combo.view()
        view.setTextElideMode(Qt.TextElideMode.ElideNone)
        desired = max_w + 60
        view.setMinimumWidth(max(320, min(520, desired)))

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
            "pitch_mode": str(self.pitch_mode_combo.currentData()),
            "pitch_amount": float(self.pitch_amount_slider.value()) / 100.0,
            "retune_speed_ms": int(self.retune_speed_slider.value()),
            "preserve_vibrato": float(self.preserve_vibrato_slider.value()) / 100.0,
            "normalize": self.normalize_check.isChecked(),
            "preserve_formants": self.preserve_formants_check.isChecked(),
            "formant_shift_cents": self.formant_slider.value() if not self.preserve_formants_check.isChecked() else 0,
            "cleanliness_percent": self.cleanliness_slider.value(),
            "clean_advanced_mode": bool(self.clean_advanced_check.isChecked()),
            "clean_lowcut_hz": float(self.clean_lowcut_slider.value()),
            "clean_high_shelf_db": float(self.clean_high_shelf_gain_slider.value()),
            "clean_high_shelf_hz": float(self.clean_high_shelf_freq_spin.value()),
            "stretch_method": self.stretch_method_combo.currentData(role_key),
            "stretch_factor": float(self._stretch_factor_effective),
        }

    def set_sample_rate(self, sr: int):
        try:
            self._sample_rate = int(sr)
        except Exception:
            self._sample_rate = 44100
        try:
            nyq = int(max(1, int(self._get_nyquist_hz())))
            self.clean_high_shelf_freq_spin.setMaximum(int(max(2000, nyq)))
        except Exception:
            pass
        try:
            self._apply_cleanliness_automation(int(self.cleanliness_slider.value()))
        except Exception:
            pass

    def set_detected_pitch(self, note_name: str, freq: float, cents: int):
        """Update the detected pitch display."""
        t = self._theme or {}
        primary = str(t.get("primary", "#1D5AAA"))
        success = str(t.get("success", "#4EDE83"))

        if note_name is None:
            self.detected_label.setText("No pitch detected")
            self.detected_label.setStyleSheet(f"color: {primary};")
        else:
            cents_str = f"+{cents}" if cents >= 0 else str(cents)
            self.detected_label.setText(f"{note_name} ({freq:.1f} Hz, {cents_str} ct)")
            self.detected_label.setStyleSheet(f"color: {success};")

    def set_buttons_enabled(self, process: bool, export: bool):
        """Enable/disable action buttons."""
        if hasattr(self, "process_btn") and self.process_btn is not None:
            self.process_btn.setEnabled(process)
        self.export_btn.setEnabled(export)
        if hasattr(self, "quick_export_btn") and self.quick_export_btn is not None:
            self.quick_export_btn.setEnabled(export)
