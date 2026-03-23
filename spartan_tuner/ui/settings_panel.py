from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QCheckBox, QSlider, QGroupBox, QPushButton, QSpinBox, QDoubleSpinBox,
    QMessageBox, QStyledItemDelegate, QStyle, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QEvent
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QStandardItem, QStandardItemModel

import importlib
import numpy as np

from ui.knob_widget import KnobWidget
from ui.mini_piano_widget import MiniPianoWidget
from ui.slider_widget import SliderWidget
from utils.note_utils import note_name_to_midi
from utils.i18n import tr


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

    _NOTE_NAMES_SHARPS = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    _NOTE_NAMES_FLATS = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
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

    def eventFilter(self, watched, event):
        if event is not None and event.type() == QEvent.Type.MouseButtonDblClick:
            try:
                if event.button() == Qt.MouseButton.LeftButton:
                    if watched is self.pitch_amount_slider:
                        self.pitch_amount_slider.setValue(100)
                        self.settings_changed.emit()
                        event.accept()
                        return True
                    if watched is self.stretch_slider:
                        self._stretch_over2_confirmed = False
                        self._apply_stretch_effective(1.0, emit=True)
                        event.accept()
                        return True
                    if watched is self.cleanliness_slider:
                        self.cleanliness_slider.setValue(0)
                        self.settings_changed.emit()
                        event.accept()
                        return True
            except Exception:
                pass
        return super().eventFilter(watched, event)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setMinimumWidth(250)
        self.setMaximumWidth(350)

        self._theme = None
        self._sample_rate = 44100
        self._note_notation = "sharps"
        self._harmonic_ceiling_offsets_db: dict[int, float] = {}

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(15)
        layout = root_layout
        layout.setSpacing(15)

        self.note_group = QGroupBox(tr("settings.group.target_note", "Target Note"))
        note_layout = QVBoxLayout(self.note_group)
        note_layout.setSpacing(8)

        self.mini_piano = MiniPianoWidget(self.note_group)
        self.mini_piano.setNotationMode(self._note_notation)
        note_layout.addWidget(self.mini_piano)

        # Single row for Note and Octave
        note_octave_row = QHBoxLayout()
        self.note_label = QLabel(tr("settings.label.note", "Note:"))
        note_octave_row.addWidget(self.note_label)
        self.note_combo = QComboBox()
        self.note_combo.addItems(list(self._NOTE_NAMES_SHARPS))
        self.note_combo.setCurrentText("C")
        note_octave_row.addWidget(self.note_combo)
        
        self.octave_label = QLabel(tr("settings.label.octave", "Octave:"))
        note_octave_row.addWidget(self.octave_label)
        self.octave_spin = QSpinBox()
        self.octave_spin.setRange(2, 7)
        self.octave_spin.setValue(4)
        note_octave_row.addWidget(self.octave_spin)
        note_layout.addLayout(note_octave_row)

        self.target_label = QLabel(tr("settings.target_fmt", "Target: {note}{octave} ({freq:.2f} Hz)").format(note="C", octave=4, freq=261.63))
        self.target_label.setStyleSheet("color: #33CED6; font-weight: bold;")
        note_layout.addWidget(self.target_label)

        layout.addWidget(self.note_group)

        self.process_group = QGroupBox(tr("settings.group.processing", "Processing"))
        process_layout = QVBoxLayout(self.process_group)
        process_layout.setSpacing(8)

        pitch_mode_row = QHBoxLayout()
        self.pitch_mode_label = QLabel(tr("settings.label.pitch_mode", "Pitch Mode:"))
        pitch_mode_row.addWidget(self.pitch_mode_label, 0)
        self.pitch_mode_combo = QComboBox()
        self.pitch_mode_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.pitch_mode_combo.setItemDelegate(PitchModeDelegate(self.pitch_mode_combo))
        self._populate_pitch_modes()
        self.pitch_mode_combo.currentIndexChanged.connect(self._on_pitch_mode_changed)
        pitch_mode_row.addWidget(self.pitch_mode_combo, 1)
        process_layout.addLayout(pitch_mode_row)

        checkbox_row = QHBoxLayout()
        self.normalize_check = QCheckBox(tr("settings.checkbox.normalize", "Normalize to 0dB"))
        self.normalize_check.setChecked(False)
        self.normalize_check.stateChanged.connect(lambda _s: self.settings_changed.emit())
        checkbox_row.addWidget(self.normalize_check)
        process_layout.addLayout(checkbox_row)

        self.soft_widget = QWidget()
        soft_layout = QVBoxLayout(self.soft_widget)
        soft_layout.setContentsMargins(0, 0, 0, 0)
        soft_layout.setSpacing(8)

        # Correction Amount (Horizontal SliderWidget)
        self.pitch_amount_slider = SliderWidget(
            label=tr("settings.label.correction_amount", "Correction Amount"),
            minimum=0,
            maximum=100,
            default_value=100,
            step=1,
            suffix="%",
            decimals=0,
            orientation=Qt.Orientation.Horizontal
        )
        self.pitch_amount_slider.valueChanged.connect(lambda _v: self.settings_changed.emit())
        soft_layout.addWidget(self.pitch_amount_slider)

        # Knobs Row (Retune Speed and Preserve Vibrato)
        knobs_row = QHBoxLayout()
        knobs_row.setSpacing(16)

        self.retune_speed_knob = KnobWidget(
            label=tr("settings.label.retune_speed", "Retune Speed"),
            minimum=0,
            maximum=500,
            default_value=40,
            step=1,
            suffix="ms",
            decimals=0,
        )
        self.retune_speed_knob.setMinimumWidth(130)
        self.retune_speed_knob.setValue(40, emit_signal=False)
        self.retune_speed_knob.valueChanged.connect(lambda _v: self.settings_changed.emit())
        knobs_row.addWidget(self.retune_speed_knob, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.preserve_vibrato_knob = KnobWidget(
            label=tr("settings.label.preserve_vibrato", "Preserve Vibrato"),
            minimum=0,
            maximum=100,
            default_value=100,
            step=1,
            suffix="%",
            decimals=0,
        )
        self.preserve_vibrato_knob.setMinimumWidth(130)
        self.preserve_vibrato_knob.setValue(100, emit_signal=False)
        self.preserve_vibrato_knob.valueChanged.connect(lambda _v: self.settings_changed.emit())
        knobs_row.addWidget(self.preserve_vibrato_knob, alignment=Qt.AlignmentFlag.AlignHCenter)

        soft_layout.addLayout(knobs_row)

        self.soft_widget.setVisible(False)
        process_layout.addWidget(self.soft_widget)

        self.formant_widget = QWidget()
        formant_layout = QVBoxLayout(self.formant_widget)
        formant_layout.setContentsMargins(0, 0, 0, 0)
        
        self.formant_knob = SliderWidget(
            label=tr("settings.label.formant_shift", "Formant Shift"),
            minimum=-250,
            maximum=250,
            default_value=0,
            step=1,
            suffix="ct",
            decimals=0,
            snap_points=[0],
            snap_dead_zone=2.5,
            orientation=Qt.Orientation.Horizontal
        )
        self.formant_knob.valueChanged.connect(lambda _v: self.settings_changed.emit())
        formant_layout.addWidget(self.formant_knob)

        process_layout.addWidget(self.formant_widget)

        self.formant_adapt_widget = QWidget()
        formant_adapt_layout = QVBoxLayout(self.formant_adapt_widget)
        formant_adapt_layout.setContentsMargins(0, 0, 0, 0)
        
        self.formant_adapt_slider = SliderWidget(
            label=tr("settings.label.formant_adapt", "Vocal Tract Model"),
            minimum=0,
            maximum=100,
            default_value=10,
            step=1,
            suffix="",
            decimals=0,
            orientation=Qt.Orientation.Horizontal
        )
        self.formant_adapt_slider.valueChanged.connect(lambda _v: self.settings_changed.emit())
        formant_adapt_layout.addWidget(self.formant_adapt_slider)

        self.formant_adapt_widget.setVisible(False)
        process_layout.addWidget(self.formant_adapt_widget)

        self._stretch_factor_effective = 1.0
        self._stretch_factor_pending = 1.0
        self._stretch_over2_confirmed = False

        stretch_method_row = QHBoxLayout()
        self.stretching_method_label = QLabel(tr("settings.label.stretching_method", "Stretching Method:"))
        stretch_method_row.addWidget(self.stretching_method_label, 0)
        self.stretch_method_combo = QComboBox()
        self.stretch_method_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.stretch_method_combo.setItemDelegate(StretchMethodDelegate(self.stretch_method_combo))
        self._populate_stretch_methods()
        self.stretch_method_combo.currentIndexChanged.connect(lambda _i: self.settings_changed.emit())
        stretch_method_row.addWidget(self.stretch_method_combo, 1)
        process_layout.addLayout(stretch_method_row)

        self.stretch_slider = SliderWidget(
            label=tr("settings.label.stretch_factor", "Stretch Factor"),
            minimum=1.00,
            maximum=5.00,
            default_value=1.00,
            step=0.01,
            suffix="x",
            decimals=2,
            orientation=Qt.Orientation.Horizontal
        )
        self.stretch_slider.valueChanged.connect(self._on_stretch_slider_value_changed)
        self.stretch_slider.sliderReleased.connect(self._on_stretch_slider_released)
        process_layout.addWidget(self.stretch_slider)

        stretch_manual_row = QHBoxLayout()
        self.stretch_manual_label = QLabel(tr("settings.label.manual", "Manual:"))
        stretch_manual_row.addWidget(self.stretch_manual_label)
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

        self.breathiness_slider = SliderWidget(
            label=tr("settings.label.breathiness", "Breathiness"),
            minimum=0.0,
            maximum=5.0,
            default_value=1.0,
            step=0.01,
            suffix="",
            decimals=2,
            orientation=Qt.Orientation.Horizontal,
        )
        self.breathiness_slider.valueChanged.connect(lambda _v: self.settings_changed.emit())
        process_layout.addWidget(self.breathiness_slider)

        self.hf_bias_slider = SliderWidget(
            label=tr("settings.label.hf_bias", "HF Bias"),
            minimum=0.0,
            maximum=1.0,
            default_value=0.0,
            step=0.01,
            suffix="",
            decimals=2,
            orientation=Qt.Orientation.Horizontal,
        )
        self.hf_bias_slider.valueChanged.connect(lambda _v: self.settings_changed.emit())
        process_layout.addWidget(self.hf_bias_slider)

        layout.addWidget(self.process_group)

        self.harmonic_group = QGroupBox(tr("harmonic.title", "Harmonic limiter"))
        harmonic_layout = QVBoxLayout(self.harmonic_group)
        harmonic_layout.setSpacing(8)
        self.harmonic_enabled_check = QCheckBox(tr("harmonic.enabled", "Enabled"))
        self.harmonic_enabled_check.setChecked(False)
        self.harmonic_enabled_check.stateChanged.connect(lambda _s: self.settings_changed.emit())
        harmonic_layout.addWidget(self.harmonic_enabled_check)
        self.harmonic_amount_slider = SliderWidget(
            label=tr("harmonic.amount", "Compression"),
            minimum=0,
            maximum=100,
            default_value=50,
            step=1,
            suffix="%",
            decimals=0,
            orientation=Qt.Orientation.Horizontal,
        )
        self.harmonic_amount_slider.valueChanged.connect(lambda _v: self.settings_changed.emit())
        harmonic_layout.addWidget(self.harmonic_amount_slider)
        layout.addWidget(self.harmonic_group)

        self.clean_group = QGroupBox(tr("settings.group.cleanliness", "Cleanliness"))
        clean_layout = QVBoxLayout(self.clean_group)
        clean_layout.setSpacing(8)

        self.cleanliness_slider = SliderWidget(
            label=tr("settings.label.amount", "Cleanliness Amount"),
            minimum=0,
            maximum=100,
            default_value=0,
            step=1,
            suffix="%",
            decimals=0,
            orientation=Qt.Orientation.Horizontal
        )
        self.cleanliness_slider.valueChanged.connect(self._on_cleanliness_slider)
        clean_layout.addWidget(self.cleanliness_slider)

        clean_chk_row = QHBoxLayout()
        self.clean_advanced_check = QCheckBox(tr("settings.checkbox.advanced_mode", "Advanced Mode"))
        self.clean_advanced_check.setChecked(False)
        self.clean_advanced_check.stateChanged.connect(self._on_clean_advanced_toggled)
        clean_chk_row.addWidget(self.clean_advanced_check)

        self.clean_warning_label = QLabel(tr("settings.warning.robotic", "High values = robotic sound"))
        self.clean_warning_label.setStyleSheet("color: rgba(51, 206, 214, 170); font-size: 10px;")
        clean_chk_row.addWidget(self.clean_warning_label)
        clean_layout.addLayout(clean_chk_row)

        self.clean_advanced_widget = QWidget()
        clean_adv_layout = QVBoxLayout(self.clean_advanced_widget)
        clean_adv_layout.setContentsMargins(0, 0, 0, 0)
        clean_adv_layout.setSpacing(8)

        self.clean_lowcut_slider = SliderWidget(
            label=tr("settings.label.low_cut", "Low Cut"),
            minimum=0,
            maximum=200,
            default_value=50,
            step=1,
            suffix=" Hz",
            decimals=0,
            orientation=Qt.Orientation.Horizontal
        )
        self.clean_lowcut_slider.valueChanged.connect(lambda v: self.settings_changed.emit())
        clean_adv_layout.addWidget(self.clean_lowcut_slider)

        self.clean_high_shelf_gain_slider = SliderWidget(
            label=tr("settings.label.high_shelf", "High Shelf"),
            minimum=-24,
            maximum=0,
            default_value=0,
            step=1,
            suffix=" dB",
            decimals=0,
            orientation=Qt.Orientation.Horizontal
        )
        self.clean_high_shelf_gain_slider.valueChanged.connect(lambda v: self.settings_changed.emit())
        clean_adv_layout.addWidget(self.clean_high_shelf_gain_slider)

        hs_freq_row = QHBoxLayout()
        self.clean_shelf_freq_label = QLabel(tr("settings.label.shelf_freq", "Shelf Freq:"))
        hs_freq_row.addWidget(self.clean_shelf_freq_label)
        self.clean_high_shelf_freq_spin = QSpinBox()
        self.clean_high_shelf_freq_spin.setRange(2000, 48000)
        self.clean_high_shelf_freq_spin.setSingleStep(250)
        self.clean_high_shelf_freq_spin.setValue(10000)
        self.clean_high_shelf_freq_spin.setSuffix(" Hz")
        self.clean_high_shelf_freq_spin.valueChanged.connect(lambda _v: self.settings_changed.emit())
        hs_freq_row.addWidget(self.clean_high_shelf_freq_spin)
        clean_adv_layout.addLayout(hs_freq_row)

        clean_layout.addWidget(self.clean_advanced_widget)

        layout.addWidget(self.clean_group)

        self.info_group = QGroupBox(tr("settings.group.detected_pitch", "Detected Pitch"))
        info_layout = QVBoxLayout(self.info_group)

        self.detected_label = QLabel(tr("settings.detected.no_audio_loaded", "No audio loaded"))
        self.detected_label.setStyleSheet("color: rgba(51, 206, 214, 170);")
        info_layout.addWidget(self.detected_label)

        layout.addWidget(self.info_group)

        button_layout = QVBoxLayout()

        self.export_btn = QPushButton(tr("settings.button.export_wav", "Export WAV"))
        self.export_btn.clicked.connect(lambda: self.export_clicked.emit())
        button_layout.addWidget(self.export_btn)

        self.quick_export_btn = QPushButton(tr("settings.button.quick_export", "Quick Export"))
        self.quick_export_btn.clicked.connect(lambda: self.quick_export_clicked.emit())
        button_layout.addWidget(self.quick_export_btn)

        layout.addLayout(button_layout)

        layout.addStretch()

        self.note_combo.currentTextChanged.connect(self._on_note_combo_changed)
        self.octave_spin.valueChanged.connect(self._update_target_label)
        self.mini_piano.noteChanged.connect(self._on_mini_piano_note_changed)
        self._rebuild_note_combo_items(None)
        self.mini_piano.setNote(self.note_combo.currentText())
        self._update_target_label()

        self._on_pitch_mode_changed(0)
        self._on_clean_lowcut_slider(int(self.clean_lowcut_slider.value()))
        self._on_clean_high_shelf_gain_slider(int(self.clean_high_shelf_gain_slider.value()))
        self._apply_cleanliness_mode_ui()
        try:
            self.retranslate_ui()
        except Exception:
            pass

    def retranslate_ui(self):
        try:
            self.note_group.setTitle(tr("settings.group.target_note", "Target Note"))
            self.note_label.setText(tr("settings.label.note", "Note:"))
            self.octave_label.setText(tr("settings.label.octave", "Octave:"))
        except Exception:
            pass

        try:
            self.process_group.setTitle(tr("settings.group.processing", "Processing"))
            self.pitch_mode_label.setText(tr("settings.label.pitch_mode", "Pitch Mode:"))
            self.normalize_check.setText(tr("settings.checkbox.normalize", "Normalize to 0dB"))
            self.stretching_method_label.setText(tr("settings.label.stretching_method", "Stretching Method:"))
            self.stretch_manual_label.setText(tr("settings.label.manual", "Manual:"))
        except Exception:
            pass

        try:
            self.clean_group.setTitle(tr("settings.group.cleanliness", "Cleanliness"))
            self.clean_advanced_check.setText(tr("settings.checkbox.advanced_mode", "Advanced Mode"))
            self.clean_warning_label.setText(tr("settings.warning.robotic", "High values = robotic sound"))
            self.clean_shelf_freq_label.setText(tr("settings.label.shelf_freq", "Shelf Freq:"))
        except Exception:
            pass
        try:
            self.harmonic_group.setTitle(tr("harmonic.title", "Harmonic limiter"))
            self.harmonic_enabled_check.setText(tr("harmonic.enabled", "Enabled"))
        except Exception:
            pass

        try:
            self.info_group.setTitle(tr("settings.group.detected_pitch", "Detected Pitch"))
        except Exception:
            pass

        try:
            self.export_btn.setText(tr("settings.button.export_wav", "Export WAV"))
            self.quick_export_btn.setText(tr("settings.button.quick_export", "Quick Export"))
        except Exception:
            pass

        try:
            self._update_target_label()
        except Exception:
            pass

        try:
            self._retranslate_pitch_modes()
        except Exception:
            pass

        try:
            self._retranslate_stretch_methods()
        except Exception:
            pass

    def _retranslate_stretch_methods(self):
        role_info = int(Qt.ItemDataRole.UserRole)
        role_key = int(Qt.ItemDataRole.UserRole) + 1

        current = None
        try:
            current = self.stretch_method_combo.currentData(role_key)
        except Exception:
            current = None

        model = self.stretch_method_combo.model()
        if model is None:
            return

        for i in range(int(self.stretch_method_combo.count())):
            key = self.stretch_method_combo.itemData(i, role_key)
            if not key:
                continue
            label = tr(f"settings.stretch_method.{key}.label", str(self.stretch_method_combo.itemText(i) or key))
            info = tr(f"settings.stretch_method.{key}.info", str(model.data(model.index(i, 0), role_info) or ""))

            try:
                it = model.item(i)
            except Exception:
                it = None
            if it is not None:
                it.setText(str(label))
                it.setData(str(info), role_info)
            else:
                self.stretch_method_combo.setItemText(i, str(label))

        if current:
            for i in range(int(self.stretch_method_combo.count())):
                if self.stretch_method_combo.itemData(i, role_key) == current:
                    self.stretch_method_combo.setCurrentIndex(int(i))
                    break

    def _retranslate_pitch_modes(self):
        role_key = int(Qt.ItemDataRole.UserRole)
        role_info = int(Qt.ItemDataRole.UserRole) + 1

        current = None
        try:
            current = self.pitch_mode_combo.currentData()
        except Exception:
            current = None

        model = self.pitch_mode_combo.model()
        if model is None:
            return

        for i in range(int(self.pitch_mode_combo.count())):
            key = self.pitch_mode_combo.itemData(i, role_key)
            if not key:
                continue
            label = tr(f"settings.pitch_mode.{key}.label", str(self.pitch_mode_combo.itemText(i) or key))
            info = tr(f"settings.pitch_mode.{key}.info", str(model.data(model.index(i, 0), role_info) or ""))

            try:
                it = model.item(i)
            except Exception:
                it = None
            if it is not None:
                it.setText(str(label))
                it.setData(str(info), role_info)
            else:
                self.pitch_mode_combo.setItemText(i, str(label))

        if current:
            for i in range(int(self.pitch_mode_combo.count())):
                if self.pitch_mode_combo.itemData(i, role_key) == current:
                    self.pitch_mode_combo.setCurrentIndex(int(i))
                    break

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

        try:
            self.retune_speed_knob.apply_theme(t)
            self.preserve_vibrato_knob.apply_theme(t)

            self.mini_piano.apply_theme(t)

            self.pitch_amount_slider.apply_theme(t)
            self.formant_knob.apply_theme(t)
            self.formant_adapt_slider.apply_theme(t)
            self.stretch_slider.apply_theme(t)
            self.breathiness_slider.apply_theme(t)
            self.hf_bias_slider.apply_theme(t)
            self.harmonic_amount_slider.apply_theme(t)

            self.cleanliness_slider.apply_theme(t)
            self.clean_lowcut_slider.apply_theme(t)
            self.clean_high_shelf_gain_slider.apply_theme(t)
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
                "breathiness": 1.0,
                "hf_bias": 0.0,
                "cleanliness_percent": 0,
                "clean_advanced_mode": False,
                "clean_lowcut_hz": 50,
                "clean_high_shelf_db": 0,
                "clean_high_shelf_hz": 10000,
                "harmonic_limiter_enabled": False,
                "harmonic_amount": 50,
                "harmonic_ceiling_offsets_db": {},
            }
        )

    def get_ui_state(self) -> dict:
        role_key = int(Qt.ItemDataRole.UserRole) + 1
        formant_shift_cents = int(self.formant_knob.value())
        return {
            "note": str(self.note_combo.currentText()),
            "octave": int(self.octave_spin.value()),
            "pitch_mode": str(self.pitch_mode_combo.currentData()),
            "pitch_amount": int(self.pitch_amount_slider.value()),
            "retune_speed_ms": int(self.retune_speed_knob.value()),
            "preserve_vibrato": int(self.preserve_vibrato_knob.value()),
            "normalize": bool(self.normalize_check.isChecked()),
            "preserve_formants": bool(formant_shift_cents == 0),
            "formant_shift_cents": int(formant_shift_cents),
            "formant_shift_beta": int(self.formant_adapt_slider.value()),
            "stretch_method": self.stretch_method_combo.currentData(role_key),
            "stretch_factor": float(self._stretch_factor_effective),
            "breathiness": float(self.breathiness_slider.value()),
            "hf_bias": float(self.hf_bias_slider.value()),
            "cleanliness_percent": int(self.cleanliness_slider.value()),
            "clean_advanced_mode": bool(self.clean_advanced_check.isChecked()),
            "clean_lowcut_hz": int(self.clean_lowcut_slider.value()),
            "clean_high_shelf_db": int(self.clean_high_shelf_gain_slider.value()),
            "clean_high_shelf_hz": int(self.clean_high_shelf_freq_spin.value()),
            "harmonic_limiter_enabled": bool(self.harmonic_enabled_check.isChecked()),
            "harmonic_amount": int(self.harmonic_amount_slider.value()),
            "harmonic_ceiling_offsets_db": {str(k): float(v) for k, v in self._harmonic_ceiling_offsets_db.items()},
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
        formant_shift_beta = state.get("formant_shift_beta")
        stretch_method = state.get("stretch_method")
        stretch_factor = state.get("stretch_factor")
        breathiness = state.get("breathiness")
        hf_bias = state.get("hf_bias")
        cleanliness_percent = state.get("cleanliness_percent")
        clean_advanced_mode = state.get("clean_advanced_mode")
        clean_lowcut_hz = state.get("clean_lowcut_hz")
        clean_high_shelf_db = state.get("clean_high_shelf_db")
        clean_high_shelf_hz = state.get("clean_high_shelf_hz")
        harmonic_limiter_enabled = state.get("harmonic_limiter_enabled")
        harmonic_amount = state.get("harmonic_amount")
        harmonic_ceiling_offsets_db = state.get("harmonic_ceiling_offsets_db")

        self.blockSignals(True)
        try:
            if note is not None:
                self._set_note_combo_from_note_name(str(note))
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
                self.retune_speed_knob.setValue(int(retune_speed_ms), emit_signal=False)
                self._on_retune_speed_slider(int(retune_speed_ms))
            if preserve_vibrato is not None:
                self.preserve_vibrato_knob.setValue(int(preserve_vibrato), emit_signal=False)
                self._on_preserve_vibrato_slider(int(preserve_vibrato))
            if normalize is not None:
                self.normalize_check.setChecked(bool(normalize))
            if formant_shift_cents is not None:
                self.formant_knob.setValue(int(formant_shift_cents), emit_signal=False)
                self._on_formant_slider(int(formant_shift_cents))
            if formant_shift_beta is not None:
                self.formant_adapt_slider.setValue(int(formant_shift_beta))
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
            if breathiness is not None:
                self.breathiness_slider.setValue(float(breathiness))
            if hf_bias is not None:
                self.hf_bias_slider.setValue(float(hf_bias))
            if harmonic_limiter_enabled is not None:
                self.harmonic_enabled_check.setChecked(bool(harmonic_limiter_enabled))
            if harmonic_amount is not None:
                self.harmonic_amount_slider.setValue(int(harmonic_amount))
            if isinstance(harmonic_ceiling_offsets_db, dict):
                cleaned: dict[int, float] = {}
                for k, v in harmonic_ceiling_offsets_db.items():
                    try:
                        kk = int(k)
                        vv = float(v)
                    except Exception:
                        continue
                    if np.isfinite(vv):
                        cleaned[int(kk)] = float(vv)
                self._harmonic_ceiling_offsets_db = cleaned

            try:
                self.mini_piano.setNote(str(self.note_combo.currentText()))
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

    def _on_mini_piano_note_changed(self, note: str):
        pc = self._note_to_pc(note)
        if pc is None:
            return
        next_note = self._pc_to_note_for_mode(pc)
        try:
            if str(self.note_combo.currentText()) == str(next_note):
                return
            self.note_combo.setCurrentIndex(int(pc) % 12)
        except Exception:
            pass

    def _on_note_combo_changed(self, note: str):
        try:
            self.mini_piano.setNote(str(note))
        except Exception:
            pass
        self._update_target_label()

    def _on_pitch_mode_changed(self, _index: int):
        mode = str(self.pitch_mode_combo.currentData())
        is_soft = mode in ("world_soft", "world_vt", "world_hnm", "praat_soft", "sine_spectral", "stft_pitchshift")
        self.soft_widget.setVisible(bool(is_soft))
        self.formant_adapt_widget.setVisible(mode == "world_vt")
        self.settings_changed.emit()

    def _on_pitch_amount_slider(self, value: int):
        pass

    def _on_retune_speed_slider(self, value: int):
        pass

    def _on_preserve_vibrato_slider(self, value: int):
        pass

    def _note_names_for_mode(self) -> list[str]:
        if str(self._note_notation) == "flats":
            return list(self._NOTE_NAMES_FLATS)
        return list(self._NOTE_NAMES_SHARPS)

    def _note_to_pc(self, note: str) -> int | None:
        if note is None:
            return None
        s = str(note).strip()
        if not s:
            return None
        mapped = self._NAME_TO_PC.get(s.upper())
        if mapped is None:
            return None
        return int(mapped)

    def _pc_to_note_for_mode(self, pc: int) -> str:
        names = self._note_names_for_mode()
        return str(names[int(pc) % 12])

    def _rebuild_note_combo_items(self, preserve_note: str | None):
        preserve_pc = self._note_to_pc(preserve_note)
        if preserve_pc is None:
            preserve_pc = self._note_to_pc(str(self.note_combo.currentText()))
        if preserve_pc is None:
            preserve_pc = 0

        self.note_combo.blockSignals(True)
        try:
            self.note_combo.clear()
            self.note_combo.addItems(self._note_names_for_mode())
            self.note_combo.setCurrentIndex(int(preserve_pc) % 12)
        finally:
            self.note_combo.blockSignals(False)

    def _set_note_combo_from_note_name(self, note: str):
        pc = self._note_to_pc(note)
        if pc is None:
            return
        self.note_combo.setCurrentIndex(int(pc) % 12)

    def get_display_note_name(self, note: str) -> str:
        pc = self._note_to_pc(note)
        if pc is None:
            return str(note)
        return self._pc_to_note_for_mode(int(pc))

    def _update_target_label(self, emit_signal: bool = True):
        """Update the target note display label."""
        note = self.note_combo.currentText()
        octave = self.octave_spin.value()

        try:
            midi = int(note_name_to_midi(f"{note}{int(octave)}"))
            freq = 440.0 * (2 ** ((float(midi) - 69.0) / 12.0))
        except Exception:
            freq = 440.0 * (2 ** ((60.0 - 69.0) / 12.0))

        self.target_label.setText(
            tr("settings.target_fmt", "Target: {note}{octave} ({freq:.2f} Hz)").format(
                note=str(note),
                octave=int(octave),
                freq=float(freq),
            )
        )
        try:
            self._apply_cleanliness_automation(int(self.cleanliness_slider.value()))
        except Exception:
            pass
        self.settings_changed.emit()

    def _on_formant_toggle(self, state):
        """Show/hide formant slider based on checkbox."""
        self.formant_widget.setVisible(state == 0)
        self.settings_changed.emit()

    def _on_formant_adapt_slider(self, value: int):
        pass

    def _on_formant_slider(self, value):
        pass

    def _on_cleanliness_slider(self, value):
        try:
            self._apply_cleanliness_automation(int(value))
        except Exception:
            pass
        self.settings_changed.emit()

    def _on_clean_lowcut_slider(self, value: int):
        pass

    def _on_clean_high_shelf_gain_slider(self, value: int):
        pass

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

        try:
            midi = int(note_name_to_midi(f"{note}{int(octave)}"))
        except Exception:
            midi = 12 * (int(octave) + 1)
        return float(440.0 * (2 ** ((midi - 69) / 12)))

    def set_note_notation(self, mode: str):
        mode_str = str(mode or "").strip().lower()
        current_note = str(self.note_combo.currentText())
        self._note_notation = "flats" if mode_str == "flats" else "sharps"
        try:
            self._rebuild_note_combo_items(current_note)
            self.mini_piano.setNotationMode(self._note_notation)
            self.mini_piano.setNote(str(self.note_combo.currentText()))
            self._update_target_label(emit_signal=False)
        except Exception:
            pass

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
                tr("settings.stretch_method.audiotsm_wsola.label", "WSOLA Speech"),
                tr(
                    "settings.stretch_method.audiotsm_wsola.info",
                    "Crisp in quality and the best for general speech audio. Can sound robotic if over-done.",
                ),
                "audiotsm_wsola",
            ),
            (
                tr("settings.stretch_method.audiotsm_phasevocoder.label", "Phasevocoder"),
                tr("settings.stretch_method.audiotsm_phasevocoder.info", "Smoother and more ideal under x2 stretching"),
                "audiotsm_phasevocoder",
            ),
            (
                tr("settings.stretch_method.rubberband_default_engine_finer.label", "Rubberband Default"),
                tr("settings.stretch_method.rubberband_default_engine_finer.info", "Baseline of any stretching method."),
                "rubberband_default_engine_finer",
            ),
            (
                tr("settings.stretch_method.rubberband_percussive_engine_finer.label", "Rubberband Percussive"),
                tr(
                    "settings.stretch_method.rubberband_percussive_engine_finer.info",
                    "Deals with transients and artifact removal a lot better than Rubberband Default.",
                ),
                "rubberband_percussive_engine_finer",
            ),
            (
                tr("settings.stretch_method.tdpsola.label", "TD-PSOLA"),
                tr("settings.stretch_method.tdpsola.info", "Fallback stretcher that works without audiotsm/rubberband (can be slower)."),
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

        sine_available = True
        try:
            import audio.sinusoidal  # noqa: F401
        except Exception:
            sine_available = False

        stft_ps_available = True
        try:
            import stftpitchshift  # noqa: F401
        except Exception:
            stft_ps_available = False

        items = [
            (
                tr("settings.pitch_mode.praat_soft.label", "PSOLA (Praat) Soft"),
                tr(
                    "settings.pitch_mode.praat_soft.info",
                    "Natural + smooth retune using Praat overlap-add. Requires praat-parselmouth.",
                ),
                "praat_soft",
                bool(praat_available),
            ),
            (
                tr("settings.pitch_mode.world_soft.label", "WORLD Soft (Retune)"),
                tr("settings.pitch_mode.world_soft.info", "Smooth retune with amount/speed/vibrato controls (WORLD vocoder)."),
                "world_soft",
                True,
            ),
            (
                tr("settings.pitch_mode.world_vt.label", "WORLD VT (Vocal Tract)"),
                tr(
                    "settings.pitch_mode.world_vt.info",
                    "WORLD vocoder with pitch-adaptive vocal tract modeling. Adjusts formant structure based on pitch change for natural-sounding correction.",
                ),
                "world_vt",
                True,
            ),
            (
                tr("settings.pitch_mode.world_hard.label", "WORLD Hard (Flatten)"),
                tr(
                    "settings.pitch_mode.world_hard.info",
                    "Hard snap to the target note for the most robotic/locked sound (WORLD vocoder).",
                ),
                "world_hard",
                True,
            ),
            (
                tr("settings.pitch_mode.world_hnm.label", "WORLD HNM (Harmonic)"),
                tr(
                    "settings.pitch_mode.world_hnm.info",
                    "Harmonic resynthesis with vocal tract modeling. Cleanest harmonics, best for large pitch shifts.",
                ),
                "world_hnm",
                True,
            ),
            (
                tr("settings.pitch_mode.sine_spectral.label", "Sinusoidal (Spectral)"),
                tr(
                    "settings.pitch_mode.sine_spectral.info",
                    "Tracks and shifts individual harmonics with spectral envelope preservation. Best for clean tonal sources.",
                ),
                "sine_spectral",
                bool(sine_available),
            ),
            (
                tr("settings.pitch_mode.stft_pitchshift.label", "STFT Spectral (Phase Vocoder)"),
                tr(
                    "settings.pitch_mode.stft_pitchshift.info",
                    "STFT phase vocoder with cepstral formant preservation. Clean, natural-sounding pitch shift.",
                ),
                "stft_pitchshift",
                bool(stft_ps_available),
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
        msg.setWindowTitle(tr("settings.stretch.confirm.title", "Warning"))
        msg.setText(tr("settings.stretch.confirm.text", "Going over x2 can cause a lot of artifacts and could make your sample sound fake."))
        msg.setInformativeText(tr("settings.stretch.confirm.info_fmt", "Requested: {factor:.2f}x").format(factor=float(requested)))
        yes_btn = msg.addButton(tr("settings.stretch.confirm.yes", "hell yeah!"), QMessageBox.ButtonRole.AcceptRole)
        no_btn = msg.addButton(tr("settings.stretch.confirm.no", "hell no!!"), QMessageBox.ButtonRole.RejectRole)
        msg.setDefaultButton(no_btn)
        msg.exec()
        return msg.clickedButton() == yes_btn

    def _apply_stretch_effective(self, factor: float, emit: bool):
        f = float(factor)
        self._stretch_factor_effective = f
        if f <= 2.0:
            self._stretch_over2_confirmed = False

        self.stretch_spin.blockSignals(True)
        self.stretch_spin.setValue(f)
        self.stretch_spin.blockSignals(False)

        if f <= 5.0:
            self.stretch_slider.blockSignals(True)
            self.stretch_slider.setValue(f)
            self.stretch_slider.blockSignals(False)
        else:
            self.stretch_slider.blockSignals(True)
            self.stretch_slider.setValue(5.0)
            self.stretch_slider.blockSignals(False)

        if emit:
            self.settings_changed.emit()

    def _apply_stretch_pending_ui(self, factor: float):
        f = float(factor)
        self._stretch_factor_pending = f

        self.stretch_spin.blockSignals(True)
        self.stretch_spin.setValue(f)
        self.stretch_spin.blockSignals(False)

        if f <= 5.0:
            self.stretch_slider.blockSignals(True)
            self.stretch_slider.setValue(f)
            self.stretch_slider.blockSignals(False)
        else:
            self.stretch_slider.blockSignals(True)
            self.stretch_slider.setValue(5.0)
            self.stretch_slider.blockSignals(False)

    def _on_stretch_slider_value_changed(self, value: float):
        factor = float(value)
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
        
        # Formant shift check: if it's exactly 0, we can effectively "preserve formants" 
        # (or just let the backend apply 0 shift). The backend expects preserve_formants boolean
        # for some modes if the shift is disabled.
        formant_shift = int(self.formant_knob.value())
        preserve = (formant_shift == 0)

        # Map compression amount (0-100%) to knee_db and release_ms
        # Amount 0% = Knee 12 dB (soft), Release 200 ms (slow) - gentlest
        # Amount 100% = Knee 0 dB (hard), Release 10 ms (fast) - aggressive
        amount = float(self.harmonic_amount_slider.value())
        knee_db = 12.0 - (amount / 100.0) * 12.0
        release_ms = 200.0 - (amount / 100.0) * 190.0

        return {
            "target_note": self.get_target_note(),
            "pitch_mode": str(self.pitch_mode_combo.currentData()),
            "pitch_amount": float(self.pitch_amount_slider.value()) / 100.0,
            "retune_speed_ms": int(self.retune_speed_knob.value()),
            "preserve_vibrato": float(self.preserve_vibrato_knob.value()) / 100.0,
            "normalize": self.normalize_check.isChecked(),
            "preserve_formants": preserve,
            "formant_shift_cents": formant_shift,
            "formant_shift_beta": float(self.formant_adapt_slider.value()) / 100.0,
            "cleanliness_percent": self.cleanliness_slider.value(),
            "clean_advanced_mode": bool(self.clean_advanced_check.isChecked()),
            "clean_lowcut_hz": float(self.clean_lowcut_slider.value()),
            "clean_high_shelf_db": float(self.clean_high_shelf_gain_slider.value()),
            "clean_high_shelf_hz": float(self.clean_high_shelf_freq_spin.value()),
            "stretch_method": self.stretch_method_combo.currentData(role_key),
            "stretch_factor": float(self._stretch_factor_effective),
            "breathiness": float(self.breathiness_slider.value()),
            "hf_bias": float(self.hf_bias_slider.value()),
            "harmonic_limiter_enabled": bool(self.harmonic_enabled_check.isChecked()),
            "harmonic_knee_db": float(knee_db),
            "harmonic_release_ms": float(release_ms),
            "harmonic_ceiling_offsets_db": {int(k): float(v) for k, v in self._harmonic_ceiling_offsets_db.items()},
        }

    def get_harmonic_ceiling_offsets(self) -> dict[int, float]:
        return {int(k): float(v) for k, v in self._harmonic_ceiling_offsets_db.items()}

    def set_harmonic_ceiling_offsets(self, offsets: dict[int, float]):
        if not isinstance(offsets, dict):
            self._harmonic_ceiling_offsets_db = {}
            return
        cleaned: dict[int, float] = {}
        for k, v in offsets.items():
            try:
                kk = int(k)
                vv = float(v)
            except Exception:
                continue
            if np.isfinite(vv):
                cleaned[int(kk)] = float(vv)
        self._harmonic_ceiling_offsets_db = cleaned

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
            self.detected_label.setText(tr("settings.detected.no_pitch", "No pitch detected"))
            self.detected_label.setStyleSheet(f"color: {primary};")
        else:
            cents_str = f"+{cents}" if cents >= 0 else str(cents)
            self.detected_label.setText(
                tr("settings.detected.pitch_fmt", "{note} ({freq:.1f} Hz, {cents} ct)").format(
                    note=str(note_name),
                    freq=float(freq),
                    cents=str(cents_str),
                )
            )
            self.detected_label.setStyleSheet(f"color: {success};")

    def set_buttons_enabled(self, process: bool, export: bool):
        """Enable/disable action buttons."""
        if hasattr(self, "process_btn") and self.process_btn is not None:
            self.process_btn.setEnabled(process)
        self.export_btn.setEnabled(export)
        if hasattr(self, "quick_export_btn") and self.quick_export_btn is not None:
            self.quick_export_btn.setEnabled(export)
