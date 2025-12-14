import os
import sys
import json
from pathlib import Path
import numpy as np
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QFileDialog, QPushButton, QLineEdit, QLabel, QMessageBox,
    QDockWidget, QTextEdit, QProgressDialog, QGraphicsOpacityEffect,
    QSplitter, QScrollArea, QFrame, QSizePolicy, QApplication,
)
from PyQt6.QtCore import (
    Qt,
    QThread,
    pyqtSignal,
    QByteArray,
    QBuffer,
    QIODeviceBase,
    QTimer,
    QSettings,
    QStandardPaths,
    QPropertyAnimation,
    QEasingCurve,
    QAbstractAnimation,
)
from PyQt6.QtGui import QKeySequence, QShortcut, QPixmap, QAction, QColor, QIcon
from PyQt6.QtMultimedia import QAudio, QAudioFormat, QAudioSink, QMediaDevices

from ui.waveform_widget import WaveformWidget
from ui.piano_roll_widget import PianoRollWidget
from ui.settings_panel import SettingsPanel
from ui.theme_editor import ThemeEditorWindow
from utils.note_utils import note_name_to_midi


class ProcessingThread(QThread):
    """Background thread for audio processing to keep UI responsive."""

    finished = pyqtSignal(np.ndarray)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, audio, sr, settings):
        super().__init__()
        self.audio = audio
        self.sr = sr
        self.settings = settings

    def run(self):
        try:
            from audio.autotuner import (
                autotune_to_note,
                autotune_with_formant_shift,
                autotune_soft_to_note,
                autotune_praat_soft_to_note,
            )
            from audio.normalizer import normalize_audio
            from audio.cleanliness import apply_cleanliness, apply_high_shelf, apply_low_cut
            from audio.time_stretch import STRETCHERS

            result = self.audio.copy()

            pitch_mode = str(self.settings.get("pitch_mode", "world_hard"))
            self.progress.emit("Autotuning...")
            if pitch_mode == "world_soft":
                result = autotune_soft_to_note(
                    result,
                    int(self.sr),
                    str(self.settings["target_note"]),
                    preserve_formants=bool(self.settings.get("preserve_formants", True)),
                    formant_shift_cents=int(self.settings.get("formant_shift_cents", 0)),
                    amount=float(self.settings.get("pitch_amount", 1.0)),
                    retune_speed_ms=float(self.settings.get("retune_speed_ms", 40.0)),
                    preserve_vibrato=float(self.settings.get("preserve_vibrato", 1.0)),
                    voicing_mode="strict",
                )
            elif pitch_mode == "praat_soft":
                result = autotune_praat_soft_to_note(
                    result,
                    int(self.sr),
                    str(self.settings["target_note"]),
                    amount=float(self.settings.get("pitch_amount", 1.0)),
                    retune_speed_ms=float(self.settings.get("retune_speed_ms", 40.0)),
                    preserve_vibrato=float(self.settings.get("preserve_vibrato", 1.0)),
                )
            else:
                if self.settings["preserve_formants"]:
                    result = autotune_to_note(result, self.sr, self.settings["target_note"], preserve_formants=True)
                else:
                    result = autotune_with_formant_shift(
                        result, self.sr,
                        self.settings["target_note"],
                        self.settings["formant_shift_cents"]
                    )

            stretch_factor = float(self.settings.get("stretch_factor", 1.0))
            stretch_method = str(self.settings.get("stretch_method", "audiotsm_wsola"))
            if abs(stretch_factor - 1.0) > 1e-6:
                self.progress.emit(f"Stretching... ({stretch_method}, x{stretch_factor:.2f})")
                fn = STRETCHERS.get(stretch_method)
                if fn is None:
                    raise ValueError(f"Unknown stretching method: {stretch_method}")
                result = fn(result, int(self.sr), float(stretch_factor))

            low_cut_hz = float(self.settings.get("clean_lowcut_hz", 0.0))
            if np.isfinite(low_cut_hz) and low_cut_hz > 0.0:
                self.progress.emit(f"Removing sub (low cut {low_cut_hz:.0f} Hz)...")
                result = apply_low_cut(result, int(self.sr), float(low_cut_hz))

            cleanliness = float(self.settings.get("cleanliness_percent", 0.0))
            if np.isfinite(cleanliness) and cleanliness > 0.0:
                self.progress.emit(f"Applying {cleanliness:.0f}% cleanliness...")
                result = apply_cleanliness(result, int(self.sr), float(cleanliness))

            hs_db = float(self.settings.get("clean_high_shelf_db", 0.0))
            hs_hz = float(self.settings.get("clean_high_shelf_hz", 10000.0))
            if np.isfinite(hs_db) and np.isfinite(hs_hz) and abs(hs_db) > 1e-9:
                self.progress.emit(f"Cleaning highs (shelf {hs_db:.1f} dB @ {hs_hz:.0f} Hz)...")
                result = apply_high_shelf(result, int(self.sr), float(hs_hz), float(hs_db))

            if self.settings["normalize"]:
                self.progress.emit("Normalizing...")
                result = normalize_audio(result, target_db=-0.1)

            self.finished.emit(result)

        except Exception as e:
            self.error.emit(str(e))


class WarmupThread(QThread):
    finished = pyqtSignal()
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def run(self):
        try:
            from audio.pitch_detector import get_predominant_pitch

            self.progress.emit("Preparing audio engine...")

            sr = 44100
            t = np.linspace(0.0, 0.25, int(sr * 0.25), endpoint=False, dtype=np.float32)
            x = (0.15 * np.sin(2.0 * np.pi * 220.0 * t)).astype(np.float32)

            if self.isInterruptionRequested():
                return

            self.progress.emit("Preparing fast pitch detector...")
            get_predominant_pitch(x, sr, fast=True)

            self.finished.emit()

        except Exception as e:
            self.error.emit(str(e))


class LoadAudioThread(QThread):
    finished = pyqtSignal(object, int, int, object, object, object)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, file_path: str, fast_pitch: bool):
        super().__init__()
        self.file_path = str(file_path)
        self.fast_pitch = bool(fast_pitch)

    def run(self):
        try:
            from audio.loader import load_audio
            from audio.pitch_detector import get_predominant_pitch

            self.progress.emit("Reading file...")
            audio, sr, original_sr = load_audio(self.file_path)
            if self.isInterruptionRequested():
                return

            self.progress.emit("Detecting pitch...")
            freq, note, cents = get_predominant_pitch(audio, int(sr), fast=bool(self.fast_pitch))
            if self.isInterruptionRequested():
                return

            self.progress.emit("Finalizing...")
            self.finished.emit(audio, int(sr), int(original_sr), freq, note, cents)

        except Exception as e:
            self.error.emit(str(e))


class MainWindow(QMainWindow):
    """Main application window for FreqEnforcer."""

    def __init__(self, debug: bool = False, debug_notes_path: str | None = None):
        super().__init__()

        self.setWindowTitle("FreqEnforcer")
        self.setMinimumSize(1200, 600)
        self.resize(1920, 1080)

        try:
            base_dir = Path(getattr(sys, "_MEIPASS", str(Path(__file__).resolve().parent.parent)))
            icon_path = base_dir / "ICON.ico"
            if icon_path.exists():
                self.setWindowIcon(QIcon(str(icon_path)))
        except Exception:
            pass

        self.original_audio = None
        self.processed_audio = None
        self.sample_rate = 44100
        self.original_sample_rate = 44100
        self.current_file_path = None
        self._waveform_view = "original"  # original | processed

        self._audio_sink = None
        self._audio_buffer = None
        self._audio_bytes = None
        self._preview_cleanup_scheduled = False

        self._preview_volume = 1.0
        self._volume_ramp_timer = QTimer(self)
        self._volume_ramp_timer.setInterval(8)
        self._volume_ramp_timer.timeout.connect(self._on_volume_ramp_tick)
        self._volume_ramp_steps_left = 0
        self._volume_ramp_step = 0.0
        self._volume_ramp_target = 1.0
        self._volume_ramp_on_done = None

        self._processing_debounce_timer = QTimer(self)
        self._processing_debounce_timer.setSingleShot(True)
        self._processing_debounce_timer.setInterval(600)
        self._processing_debounce_timer.timeout.connect(self._on_process)

        self._apply_processed_timer = QTimer(self)
        self._apply_processed_timer.setSingleShot(True)
        self._apply_processed_timer.setInterval(60)
        self._apply_processed_timer.timeout.connect(self._apply_latest_processed_result)
        self._pending_processed_result = None

        self._processing_pending = False
        self._pending_settings = None
        self._processing_token = 0
        self._current_processing_token = 0
        self._latest_completed_token = 0

        self._drop_highlight_active = False

        self._qsettings = QSettings("FreqEnforcer", "FreqEnforcer")

        self._theme = self._read_theme()
        self._theme_editor = None
        self._theme_library = {}

        try:
            settings_version = int(self._qsettings.value("app/settings_version", 0))
        except Exception:
            settings_version = 0

        if settings_version < 2:
            try:
                self._qsettings.setValue("options/show_loading_dialog", True)
                self._qsettings.setValue("options/performance_mode", False)
                self._qsettings.setValue("options/warmup_enabled", True)
                self._qsettings.setValue("app/settings_version", 2)
            except Exception:
                pass

        if settings_version < 3:
            try:
                self._qsettings.setValue("options/performance_mode", False)
                self._qsettings.setValue("app/settings_version", 3)
            except Exception:
                pass

        self._save_settings_timer = QTimer(self)
        self._save_settings_timer.setSingleShot(True)
        self._save_settings_timer.setInterval(250)
        self._save_settings_timer.timeout.connect(self._save_persistent_settings)

        self._performance_mode = bool(self._qsettings.value("options/performance_mode", False, type=bool))
        self._show_loading_dialog = bool(self._qsettings.value("options/show_loading_dialog", True, type=bool))
        self._load_thread = None
        self._load_dialog = None
        self._loading_file_path = None

        self._warmup_enabled = bool(self._qsettings.value("options/warmup_enabled", True, type=bool))
        self._warmup_thread = None
        self._warmup_done = False

        self._saved_settings_panel_state = self._read_settings_panel_state()

        self._debug_enabled = bool(debug)
        self._debug_notes_path = debug_notes_path
        self._debug_text = None

        self._ui_scale = 1.0
        self._base_app_font = None
        try:
            self._base_app_font = QApplication.font()
        except Exception:
            self._base_app_font = None

        self._pending_ui_scale = None
        self._scale_update_timer = QTimer(self)
        self._scale_update_timer.setSingleShot(True)
        self._scale_update_timer.setInterval(80)
        self._scale_update_timer.timeout.connect(self._apply_pending_ui_scale)

        self._setup_ui()

        self._responsive_vertical = None
        try:
            self._update_responsive_layout()
        except Exception:
            pass

        try:
            self._schedule_ui_scale_update()
        except Exception:
            pass

        try:
            self._setup_animations()
        except Exception:
            pass

        self._restore_settings_panel_state()
        self._connect_signals()

        self._setup_menu()

        self._set_performance_mode(self._performance_mode)

        if self._debug_enabled:
            self._setup_debug_dock()

        self._apply_theme()

        self.setAcceptDrops(True)

        self._restore_window_geometry_or_default()

        QTimer.singleShot(2000, self._maybe_start_warmup)

        try:
            self._theme_library = self._load_theme_library()
        except Exception:
            self._theme_library = {}

    def _schedule_save_settings(self):
        try:
            self._save_settings_timer.start()
        except Exception:
            pass

    def _read_settings_panel_state(self) -> dict:
        try:
            raw = self._qsettings.value("settings_panel/state_json", "", type=str)
            if raw:
                obj = json.loads(str(raw))
                if isinstance(obj, dict):
                    return obj
        except Exception:
            pass
        return {}

    def _restore_settings_panel_state(self):
        try:
            if isinstance(self._saved_settings_panel_state, dict) and self._saved_settings_panel_state:
                self.settings_panel.apply_ui_state(self._saved_settings_panel_state)
        except Exception:
            pass

    def _restore_window_geometry_or_default(self):
        try:
            geom = self._qsettings.value("ui/geometry", None)
            if geom is not None and isinstance(geom, QByteArray) and not geom.isEmpty():
                if self.restoreGeometry(geom):
                    return
        except Exception:
            pass

        self._apply_default_window_geometry()

    def _save_persistent_settings(self):
        try:
            self._qsettings.setValue("options/performance_mode", bool(self._performance_mode))
            self._qsettings.setValue("options/show_loading_dialog", bool(self._show_loading_dialog))
            self._qsettings.setValue("options/warmup_enabled", bool(self._warmup_enabled))
        except Exception:
            pass

        try:
            self._qsettings.setValue("theme/json", json.dumps(self._theme))
        except Exception:
            pass

        try:
            state = self.settings_panel.get_ui_state()
            self._qsettings.setValue("settings_panel/state_json", json.dumps(state))
        except Exception:
            pass

        try:
            self._qsettings.setValue("ui/geometry", self.saveGeometry())
        except Exception:
            pass

    def _apply_default_window_geometry(self):
        desired_w = 1342
        desired_h = 967

        try:
            screen = self.screen()
            if screen is not None:
                g = screen.availableGeometry()
                w = min(desired_w, int(g.width() * 0.95))
                h = min(desired_h, int(g.height() * 0.95))
                w = max(int(self.minimumWidth()), int(w))
                h = max(int(self.minimumHeight()), int(h))
                self.resize(int(w), int(h))
                self.move(g.center() - self.frameGeometry().center())
                return
        except Exception:
            pass

        self.resize(desired_w, desired_h)

    def _setup_ui(self):
        """Create and arrange all UI elements."""
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        self._main_layout = main_layout
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)

        file_bar = QHBoxLayout()

        logo_label = QLabel()
        self._logo_label = logo_label
        self._logo_pixmap = None
        base_dir = Path(getattr(sys, "_MEIPASS", str(Path(__file__).resolve().parent.parent)))
        logo_path = base_dir / "LOGO.png"
        if logo_path.exists():
            pix = QPixmap(str(logo_path))
            if not pix.isNull():
                self._logo_pixmap = pix
                logo_label.setPixmap(pix.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        logo_label.setFixedSize(72, 72)
        file_bar.addWidget(logo_label)

        file_label = QLabel("INPUT FILE:")
        file_label.setStyleSheet("font-weight: bold;")
        file_bar.addWidget(file_label)

        self.file_path_edit = QLineEdit()
        self.file_path_edit.setPlaceholderText("/path/to/audio/file.wav")
        self.file_path_edit.setReadOnly(True)
        file_bar.addWidget(self.file_path_edit, stretch=1)

        self.browse_btn = QPushButton("Browse")
        self.browse_btn.clicked.connect(self._on_browse)
        file_bar.addWidget(self.browse_btn)

        main_layout.addLayout(file_bar)

        self._content_splitter = QSplitter(Qt.Orientation.Horizontal)
        try:
            self._content_splitter.setChildrenCollapsible(False)
        except Exception:
            pass
        try:
            self._content_splitter.setHandleWidth(8)
        except Exception:
            pass

        left_widget = QWidget()
        self._left_widget = left_widget
        left_layout = QHBoxLayout(left_widget)
        left_layout.setSpacing(10)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self.piano_roll = PianoRollWidget()
        try:
            self.piano_roll.setMinimumWidth(80)
            self.piano_roll.setMaximumWidth(80)
        except Exception:
            pass
        left_layout.addWidget(self.piano_roll)

        waveform_widget_container = QWidget()
        waveform_container = QVBoxLayout(waveform_widget_container)
        waveform_container.setContentsMargins(0, 0, 0, 0)

        waveform_header = QHBoxLayout()
        self.waveform_label = QLabel("Original")
        self.waveform_label.setStyleSheet("color: rgba(51, 206, 214, 170);")
        waveform_header.addWidget(self.waveform_label)
        waveform_header.addStretch(1)

        self.processing_label = QLabel("")
        self.processing_label.setStyleSheet("color: #4EDE83; font-weight: bold;")
        self.processing_label.setVisible(False)
        waveform_header.addWidget(self.processing_label)

        self.waveform_toggle_btn = QPushButton("Show Processed")
        self.waveform_toggle_btn.setEnabled(False)
        self.waveform_toggle_btn.clicked.connect(self._toggle_waveform_view)
        waveform_header.addWidget(self.waveform_toggle_btn)

        waveform_container.addLayout(waveform_header)

        self.waveform_widget = WaveformWidget()
        try:
            self.waveform_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self.waveform_widget.setMinimumHeight(240)
            self.waveform_widget.setMinimumWidth(520)
        except Exception:
            pass
        waveform_container.addWidget(self.waveform_widget, stretch=1)

        playback_row = QHBoxLayout()
        self.play_btn = QPushButton("Play")
        self.play_btn.setEnabled(False)
        self.play_btn.clicked.connect(self._toggle_playback)
        playback_row.addWidget(self.play_btn)
        playback_row.addStretch(1)
        waveform_container.addLayout(playback_row)

        left_layout.addWidget(waveform_widget_container, stretch=1)
        try:
            left_widget.setMinimumWidth(700)
        except Exception:
            pass

        self._content_splitter.addWidget(left_widget)

        self.settings_panel = SettingsPanel()
        try:
            self.settings_panel.setMinimumWidth(420)
        except Exception:
            pass

        try:
            self.settings_panel.set_sample_rate(int(self.sample_rate))
        except Exception:
            pass

        self._settings_scroll = QScrollArea()
        try:
            self._settings_scroll.setFrameShape(QFrame.Shape.NoFrame)
        except Exception:
            pass
        self._settings_scroll.setWidgetResizable(True)
        try:
            self._settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        except Exception:
            pass
        self._settings_scroll.setWidget(self.settings_panel)
        try:
            self._settings_scroll.setMinimumWidth(420)
        except Exception:
            pass

        self._content_splitter.addWidget(self._settings_scroll)
        try:
            self._content_splitter.setCollapsible(0, False)
            self._content_splitter.setCollapsible(1, False)
        except Exception:
            pass
        try:
            self._content_splitter.setStretchFactor(0, 3)
            self._content_splitter.setStretchFactor(1, 1)
        except Exception:
            pass
        try:
            self._content_splitter.setSizes([900, 420])
        except Exception:
            pass

        main_layout.addWidget(self._content_splitter, stretch=1)

        self.settings_panel.set_buttons_enabled(process=False, export=False)

        self._space_shortcut = QShortcut(QKeySequence("Space"), self)
        self._space_shortcut.activated.connect(self._toggle_playback)

    def resizeEvent(self, event):
        try:
            self._update_responsive_layout()
        except Exception:
            pass

        try:
            self._schedule_ui_scale_update()
        except Exception:
            pass
        return super().resizeEvent(event)

    def showEvent(self, event):
        try:
            self._update_responsive_layout()
        except Exception:
            pass

        try:
            self._schedule_ui_scale_update()
        except Exception:
            pass
        return super().showEvent(event)

    def _compute_ui_scale(self) -> float:
        try:
            w = float(self.width())
            h = float(self.height())
        except Exception:
            return 1.0

        base_w = 1342.0
        base_h = 967.0
        s = min(w / base_w, h / base_h)
        if not np.isfinite(s):
            s = 1.0
        s = max(0.70, min(1.0, float(s)))
        return float(s)

    def _schedule_ui_scale_update(self):
        target = self._compute_ui_scale()
        self._pending_ui_scale = float(target)
        try:
            self._scale_update_timer.start()
        except Exception:
            self._apply_pending_ui_scale()

    def _apply_pending_ui_scale(self):
        target = getattr(self, "_pending_ui_scale", None)
        if target is None:
            return

        try:
            target = float(target)
        except Exception:
            return

        current = float(getattr(self, "_ui_scale", 1.0) or 1.0)
        if abs(target - current) < 0.025:
            return

        self._ui_scale = float(target)
        self._apply_ui_scale()

    def _apply_ui_scale(self):
        s = float(getattr(self, "_ui_scale", 1.0) or 1.0)

        try:
            base = self._base_app_font
            if base is not None:
                f = base
                try:
                    f = base.__class__(base)
                except Exception:
                    pass
                try:
                    size = float(f.pointSizeF())
                    if size > 0:
                        f.setPointSizeF(max(8.0, size * s))
                        QApplication.setFont(f)
                except Exception:
                    pass
        except Exception:
            pass

        try:
            if getattr(self, "_main_layout", None) is not None:
                sp = max(6, int(round(10 * s)))
                mg = max(6, int(round(10 * s)))
                self._main_layout.setSpacing(int(sp))
                self._main_layout.setContentsMargins(int(mg), int(mg), int(mg), int(mg))
        except Exception:
            pass

        try:
            logo = getattr(self, "_logo_label", None)
            pix = getattr(self, "_logo_pixmap", None)
            if logo is not None:
                side = max(44, int(round(72 * s)))
                logo.setFixedSize(int(side), int(side))
                if pix is not None:
                    inner = max(36, int(round(64 * s)))
                    logo.setPixmap(pix.scaled(int(inner), int(inner), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        except Exception:
            pass

        try:
            w = max(60, int(round(80 * s)))
            self.piano_roll.setMinimumWidth(int(w))
            self.piano_roll.setMaximumWidth(int(w))
        except Exception:
            pass

        try:
            self.waveform_widget.setMinimumWidth(max(320, int(round(520 * s))))
            self.waveform_widget.setMinimumHeight(max(160, int(round(240 * s))))
        except Exception:
            pass

        try:
            self.settings_panel.setMinimumWidth(max(280, int(round(420 * s))))
        except Exception:
            pass

        try:
            self._settings_scroll.setMinimumWidth(max(280, int(round(420 * s))))
        except Exception:
            pass

        try:
            self._apply_theme()
        except Exception:
            pass

    def _update_responsive_layout(self):
        try:
            w = int(self.width())
        except Exception:
            return

        splitter = getattr(self, "_content_splitter", None)
        if splitter is None:
            return

        try:
            left_min = int(getattr(self, "_left_widget").minimumWidth())
        except Exception:
            left_min = 0
        try:
            right_min = int(getattr(self, "_settings_scroll").minimumWidth())
        except Exception:
            right_min = 0
        try:
            handle = int(splitter.handleWidth())
        except Exception:
            handle = 8

        threshold = int(left_min + right_min + handle + 60)
        want_vertical = bool(w < threshold)
        if getattr(self, "_responsive_vertical", None) == want_vertical:
            return
        self._responsive_vertical = want_vertical

        if want_vertical:
            try:
                splitter.setOrientation(Qt.Orientation.Vertical)
            except Exception:
                return
            try:
                splitter.setStretchFactor(0, 2)
                splitter.setStretchFactor(1, 1)
            except Exception:
                pass
            try:
                splitter.setSizes([int(self.height() * 0.62), int(self.height() * 0.38)])
            except Exception:
                pass
        else:
            try:
                splitter.setOrientation(Qt.Orientation.Horizontal)
            except Exception:
                return
            try:
                splitter.setStretchFactor(0, 3)
                splitter.setStretchFactor(1, 1)
            except Exception:
                pass
            try:
                splitter.setSizes([900, 420])
            except Exception:
                pass

    def _setup_animations(self):
        self._waveform_fade_phase = None
        self._waveform_fade_target_view = None

        self._waveform_opacity_effect = QGraphicsOpacityEffect(self.waveform_widget)
        self._waveform_opacity_effect.setOpacity(1.0)
        self.waveform_widget.setGraphicsEffect(self._waveform_opacity_effect)

        self._waveform_fade_anim = QPropertyAnimation(self._waveform_opacity_effect, b"opacity", self)
        self._waveform_fade_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._waveform_fade_anim.setDuration(140)
        self._waveform_fade_anim.finished.connect(self._on_waveform_fade_finished)

        self._processing_fade_mode = None
        self._processing_opacity_effect = QGraphicsOpacityEffect(self.processing_label)
        self._processing_opacity_effect.setOpacity(0.0 if not self.processing_label.isVisible() else 1.0)
        self.processing_label.setGraphicsEffect(self._processing_opacity_effect)

        self._processing_fade_anim = QPropertyAnimation(self._processing_opacity_effect, b"opacity", self)
        self._processing_fade_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._processing_fade_anim.setDuration(160)
        self._processing_fade_anim.finished.connect(self._on_processing_fade_finished)

    def _on_waveform_fade_finished(self):
        phase = getattr(self, "_waveform_fade_phase", None)
        if phase == "out":
            target = getattr(self, "_waveform_fade_target_view", None)
            if target in ("original", "processed"):
                self._waveform_view = str(target)
            self._update_waveform_display()
            self._update_play_button_enabled()

            self._waveform_fade_phase = "in"
            try:
                self._waveform_fade_anim.setDuration(160)
                self._waveform_fade_anim.setStartValue(0.0)
                self._waveform_fade_anim.setEndValue(1.0)
                self._waveform_fade_anim.start()
            except Exception:
                try:
                    self._waveform_opacity_effect.setOpacity(1.0)
                except Exception:
                    pass
                self._waveform_fade_phase = None
                self._waveform_fade_target_view = None
            return

        self._waveform_fade_phase = None
        self._waveform_fade_target_view = None

    def _show_processing_label(self, text: str):
        try:
            self.processing_label.setText(str(text))
        except Exception:
            pass

        was_visible = False
        try:
            was_visible = bool(self.processing_label.isVisible())
        except Exception:
            was_visible = False

        anim = getattr(self, "_processing_fade_anim", None)
        fx = getattr(self, "_processing_opacity_effect", None)
        try:
            if anim is not None and anim.state() != QAbstractAnimation.State.Stopped:
                anim.stop()
        except Exception:
            pass

        try:
            self.processing_label.setVisible(True)
        except Exception:
            pass

        if was_visible:
            try:
                self._processing_fade_mode = None
                if fx is not None:
                    fx.setOpacity(1.0)
            except Exception:
                pass
            return

        if anim is None or fx is None:
            return

        try:
            anim.stop()
        except Exception:
            pass
        try:
            self._processing_fade_mode = "show"
            fx.setOpacity(0.0)
            anim.setDuration(160)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.start()
        except Exception:
            self._processing_fade_mode = None
            try:
                fx.setOpacity(1.0)
            except Exception:
                pass

    def _hide_processing_label(self):
        try:
            if not self.processing_label.isVisible():
                return
        except Exception:
            return

        anim = getattr(self, "_processing_fade_anim", None)
        fx = getattr(self, "_processing_opacity_effect", None)
        if anim is None or fx is None:
            try:
                self.processing_label.setVisible(False)
            except Exception:
                pass
            return

        try:
            if anim.state() != QAbstractAnimation.State.Stopped:
                anim.stop()
        except Exception:
            pass

        try:
            start = float(fx.opacity())
        except Exception:
            start = 1.0

        try:
            self._processing_fade_mode = "hide"
            anim.setDuration(140)
            anim.setStartValue(start)
            anim.setEndValue(0.0)
            anim.start()
        except Exception:
            self._processing_fade_mode = None
            try:
                self.processing_label.setVisible(False)
            except Exception:
                pass

    def _on_processing_fade_finished(self):
        mode = getattr(self, "_processing_fade_mode", None)
        if mode == "hide":
            try:
                self.processing_label.setVisible(False)
            except Exception:
                pass
        self._processing_fade_mode = None

    def _setup_menu(self):
        file_menu = self.menuBar().addMenu("File")

        action_new_sample = QAction("New Sample", self)
        action_new_sample.triggered.connect(self._on_file_new_sample)
        file_menu.addAction(action_new_sample)

        action_refresh = QAction("Refresh Sample", self)
        action_refresh.triggered.connect(self._on_file_refresh_sample)
        file_menu.addAction(action_refresh)

        action_quit = QAction("Quit", self)
        action_quit.triggered.connect(self.close)
        file_menu.addAction(action_quit)

        options_menu = self.menuBar().addMenu("Options")

        self._action_show_loading = QAction("Show Loading Dialog", self)
        self._action_show_loading.setCheckable(True)
        self._action_show_loading.setChecked(bool(self._show_loading_dialog))
        self._action_show_loading.toggled.connect(self._set_show_loading_dialog)
        options_menu.addAction(self._action_show_loading)

        self._action_performance_mode = QAction("Performance Mode", self)
        self._action_performance_mode.setCheckable(True)
        self._action_performance_mode.setChecked(bool(self._performance_mode))
        self._action_performance_mode.toggled.connect(self._set_performance_mode)
        options_menu.addAction(self._action_performance_mode)

        self._action_warmup = QAction("Warm Up Audio Engine on Startup", self)
        self._action_warmup.setCheckable(True)
        self._action_warmup.setChecked(bool(self._warmup_enabled))
        self._action_warmup.toggled.connect(self._set_warmup_enabled)
        options_menu.addAction(self._action_warmup)

    def _set_show_loading_dialog(self, enabled: bool):
        self._show_loading_dialog = bool(enabled)
        self._schedule_save_settings()

    def _set_performance_mode(self, enabled: bool):
        self._performance_mode = bool(enabled)
        try:
            self.waveform_widget.set_performance_mode(bool(enabled))
        except Exception:
            pass

        try:
            self._processing_debounce_timer.setInterval(1000 if self._performance_mode else 600)
        except Exception:
            pass

        self._schedule_save_settings()

    def _set_warmup_enabled(self, enabled: bool):
        self._warmup_enabled = bool(enabled)

        self._schedule_save_settings()

        if not self._warmup_enabled:
            if self._warmup_thread is not None and self._warmup_thread.isRunning():
                try:
                    self._warmup_thread.requestInterruption()
                except Exception:
                    pass
            return

        self._maybe_start_warmup()

    def _maybe_start_warmup(self):
        if not bool(self._warmup_enabled):
            return

        if bool(self._warmup_done):
            return

        if self.original_audio is not None:
            return

        if self._load_thread is not None and self._load_thread.isRunning():
            return

        if self._warmup_thread is not None and self._warmup_thread.isRunning():
            return

        self._warmup_thread = WarmupThread()
        self._warmup_thread.progress.connect(self._on_warmup_progress)
        self._warmup_thread.finished.connect(self._on_warmup_finished)
        self._warmup_thread.error.connect(self._on_warmup_error)
        self._warmup_thread.start()

    def _on_warmup_progress(self, msg: str):
        try:
            self.statusBar().showMessage(str(msg))
        except Exception:
            pass

    def _on_warmup_finished(self):
        self._warmup_done = True
        try:
            self.statusBar().clearMessage()
        except Exception:
            pass

    def _on_warmup_error(self, error_msg: str):
        self._warmup_done = True
        try:
            self.statusBar().clearMessage()
        except Exception:
            pass

    def _connect_signals(self):
        """Connect all signals and slots."""
        self.settings_panel.export_clicked.connect(self._on_export)
        self.settings_panel.quick_export_clicked.connect(self._on_quick_export)
        self.settings_panel.settings_changed.connect(self._on_settings_changed)
        self.settings_panel.themes_requested.connect(self._open_theme_editor)
        self.settings_panel.octave_spin.valueChanged.connect(self._sync_piano_roll_to_settings)
        self.settings_panel.note_combo.currentTextChanged.connect(lambda _t: self._sync_piano_roll_to_settings())
        self.waveform_widget.blob_note_changed.connect(self._on_waveform_blob_note_changed)
        self.waveform_widget.midi_view_range_changed.connect(self.piano_roll.set_midi_range)

    def _default_theme(self) -> dict:
        return {
            "bg": "#2E2E2E",
            "panel": "#404040",
            "primary": "#1D5AAA",
            "accent": "#33CED6",
            "highlight": "#6B999F",
            "success": "#4EDE83",
            "text": "#ffffff",
        }

    def _read_theme(self) -> dict:
        theme = self._default_theme()
        try:
            raw = self._qsettings.value("theme/json", "", type=str)
            if raw:
                obj = json.loads(str(raw))
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        if v is None:
                            continue
                        theme[str(k)] = str(v)
        except Exception:
            pass
        return theme

    def _open_theme_editor(self):
        try:
            themes = self._load_theme_library()
        except Exception:
            themes = {}

        if self._theme_editor is None:
            self._theme_editor = ThemeEditorWindow(
                self,
                theme=dict(self._theme),
                themes=dict(themes),
                themes_dir=str(self._get_user_themes_dir()),
            )
            self._theme_editor.theme_applied.connect(self._on_theme_applied)
        else:
            try:
                self._theme_editor.set_theme(dict(self._theme))
            except Exception:
                pass

            try:
                self._theme_editor.set_available_themes(dict(themes))
            except Exception:
                pass

        try:
            self._theme_editor.show()
            self._theme_editor.raise_()
            self._theme_editor.activateWindow()
        except Exception:
            pass

    def _get_resource_base_dir(self) -> Path:
        return Path(getattr(sys, "_MEIPASS", str(Path(__file__).resolve().parent.parent)))

    def _get_user_themes_dir(self) -> Path:
        base = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))
        d = base / "themes"
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        return d

    def _load_theme_library(self) -> dict:
        themes: dict[str, dict] = {}

        candidates: list[Path] = []
        try:
            candidates.append(self._get_resource_base_dir() / "themes")
        except Exception:
            pass
        try:
            candidates.append(self._get_user_themes_dir())
        except Exception:
            pass

        for folder in candidates:
            try:
                if not folder.exists():
                    continue
                for p in sorted(folder.glob("*.json")):
                    try:
                        raw = p.read_text(encoding="utf-8")
                        obj = json.loads(raw)
                        if not isinstance(obj, dict):
                            continue
                        name = str(obj.get("name") or p.stem)
                        colors = obj.get("colors")
                        if isinstance(colors, dict):
                            theme_dict = {str(k): str(v) for k, v in colors.items() if v is not None}
                        else:
                            theme_dict = {str(k): str(v) for k, v in obj.items() if v is not None and k != "name"}

                        if theme_dict:
                            themes[name] = theme_dict
                    except Exception:
                        continue
            except Exception:
                continue

        if "Default" not in themes:
            themes["Default"] = dict(self._default_theme())

        return themes

    def _on_theme_applied(self, theme: dict):
        if not isinstance(theme, dict):
            return

        base = self._default_theme()
        for k, v in theme.items():
            if v is None:
                continue
            base[str(k)] = str(v)
        self._theme = base

        self._apply_theme()

        try:
            self._qsettings.setValue("theme/json", json.dumps(self._theme))
        except Exception:
            pass

    def _midi_to_note_and_octave(self, midi: int) -> tuple[str, int]:
        note_names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
        m = int(midi)
        note = note_names[m % 12]
        octave = (m // 12) - 1
        return note, int(octave)

    def _set_target_midi(self, midi: int, schedule_processing: bool, immediate: bool):
        note, octave = self._midi_to_note_and_octave(midi)

        self.settings_panel.note_combo.blockSignals(True)
        self.settings_panel.octave_spin.blockSignals(True)
        self.settings_panel.note_combo.setCurrentText(note)
        self.settings_panel.octave_spin.setValue(int(octave))
        self.settings_panel.note_combo.blockSignals(False)
        self.settings_panel.octave_spin.blockSignals(False)

        freq = 440.0 * (2 ** ((float(midi) - 69.0) / 12.0))
        self.settings_panel.target_label.setText(f"Target: {note}{octave} ({freq:.2f} Hz)")

        self._sync_piano_roll_to_settings()

        if schedule_processing:
            self._schedule_processing(immediate=bool(immediate))

    def _on_waveform_blob_note_changed(self, midi: int):
        self._set_target_midi(int(midi), schedule_processing=True, immediate=False)

    def _apply_theme(self):
        """Apply dark theme to the application."""
        t = self._theme if isinstance(getattr(self, "_theme", None), dict) else {}
        bg = str(t.get("bg", "#2E2E2E"))
        panel = str(t.get("panel", "#404040"))
        primary = str(t.get("primary", "#1D5AAA"))
        accent = str(t.get("accent", "#33CED6"))
        highlight = str(t.get("highlight", "#6B999F"))
        success = str(t.get("success", "#4EDE83"))
        text = str(t.get("text", "#ffffff"))

        def _qcolor(value: str, fallback: str) -> QColor:
            c = QColor(str(value))
            if not c.isValid():
                c = QColor(str(fallback))
            return c

        def _rgba(c: QColor, alpha: int) -> str:
            a = max(0, min(255, int(alpha)))
            return f"rgba({c.red()}, {c.green()}, {c.blue()}, {a})"

        bg_c = _qcolor(bg, "#2E2E2E")
        panel_c = _qcolor(panel, "#404040")
        primary_c = _qcolor(primary, "#1D5AAA")
        accent_c = _qcolor(accent, "#33CED6")
        highlight_c = _qcolor(highlight, "#6B999F")
        success_c = _qcolor(success, "#4EDE83")
        text_c = _qcolor(text, "#ffffff")

        bg = bg_c.name()
        panel = panel_c.name()
        primary = primary_c.name()
        accent = accent_c.name()
        highlight = highlight_c.name()
        success = success_c.name()
        text = text_c.name()

        panel_2 = panel_c.darker(110).name()
        panel_hover = panel_c.lighter(112).name()
        border_subtle = _rgba(text_c, 34)
        border_hover = _rgba(text_c, 70)
        text_muted = _rgba(text_c, 180)
        text_disabled = _rgba(text_c, 110)

        try:
            s = float(getattr(self, "_ui_scale", 1.0) or 1.0)
        except Exception:
            s = 1.0
        s = max(0.70, min(1.0, float(s)))

        def _px(v: float, min_v: int = 1) -> int:
            try:
                return max(int(min_v), int(round(float(v) * s)))
            except Exception:
                return int(min_v)

        font_px = max(10, _px(13, 10))
        radius_md = _px(10, 6)
        radius_sm = _px(8, 5)
        pad_y_sm = _px(6, 4)
        pad_x_sm = _px(10, 6)
        pad_y_btn = _px(8, 5)
        pad_x_btn = _px(14, 8)
        tab_pad_y = _px(8, 5)
        tab_pad_x = _px(12, 8)
        tab_margin_y = _px(6, 3)
        tab_margin_x = _px(4, 2)
        group_margin_top = _px(14, 10)
        group_padding = _px(10, 6)
        menu_pad = _px(6, 4)
        menu_item_y = _px(8, 6)
        menu_item_left = _px(18, 12)
        menu_item_right = _px(24, 16)
        slider_groove_h = _px(8, 6)
        slider_handle_w = _px(16, 12)
        checkbox_ind = _px(18, 14)
        checkbox_rad = _px(6, 4)
        scrollbar_thick = _px(12, 10)
        scrollbar_rad = _px(6, 5)

        self.setStyleSheet(
            "QMainWindow, QWidget {"
            f"background-color: {bg};"
            f"color: {text};"
            f"selection-background-color: {primary};"
            f"selection-color: {text};"
            f"font-size: {font_px}px;"
            "}"
            "QWidget:disabled {"
            f"color: {text_disabled};"
            "}"
            "QLabel {"
            "background: transparent;"
            "}"
            "QToolTip {"
            f"background-color: {panel};"
            f"color: {text};"
            f"border: 1px solid {border_subtle};"
            f"padding: {menu_pad}px {pad_x_sm}px;"
            f"border-radius: {radius_sm}px;"
            "}"
            "QMenuBar {"
            f"background-color: {bg};"
            f"color: {text};"
            f"padding: {_px(4, 2)}px;"
            "}"
            "QMenuBar::item {"
            "background: transparent;"
            f"padding: {pad_y_sm}px {pad_x_sm}px;"
            f"margin: {_px(2, 1)}px {tab_margin_x}px;"
            f"border-radius: {radius_sm}px;"
            "}"
            "QMenuBar::item:selected {"
            f"background: {panel};"
            "}"
            "QMenu {"
            f"background-color: {panel};"
            f"border: 1px solid {border_subtle};"
            f"color: {text};"
            f"padding: {menu_pad}px;"
            "}"
            "QMenu::item {"
            f"padding: {menu_item_y}px {menu_item_right}px {menu_item_y}px {menu_item_left}px;"
            f"border-radius: {radius_sm}px;"
            "background: transparent;"
            "}"
            "QMenu::item:selected {"
            f"background: {highlight};"
            f"color: {text};"
            "}"
            "QMenu::separator {"
            "height: 1px;"
            f"background: {border_subtle};"
            f"margin: {menu_pad}px {pad_x_sm}px;"
            "}"
            "QTabWidget::pane {"
            f"border: 1px solid {border_subtle};"
            f"border-radius: {radius_md}px;"
            "top: -1px;"
            "}"
            "QTabBar::tab {"
            "background: transparent;"
            f"padding: {tab_pad_y}px {tab_pad_x}px;"
            f"margin: {tab_margin_y}px {tab_margin_x}px;"
            f"border-radius: {_px(9, 6)}px;"
            f"color: {text_muted};"
            "}"
            "QTabBar::tab:hover {"
            f"background: {panel_2};"
            f"color: {text};"
            "}"
            "QTabBar::tab:selected {"
            f"background: {panel};"
            f"color: {text};"
            "}"
            "QGroupBox {"
            f"background-color: {panel_2};"
            f"border: 1px solid {border_subtle};"
            f"border-radius: {_px(12, 8)}px;"
            f"margin-top: {group_margin_top}px;"
            f"padding: {group_padding}px;"
            "}"
            "QGroupBox::title {"
            "subcontrol-origin: margin;"
            "subcontrol-position: top left;"
            f"left: {_px(12, 8)}px;"
            f"padding: 0 {menu_pad}px;"
            "background: transparent;"
            "border: none;"
            "}"
            "QLineEdit, QTextEdit, QPlainTextEdit {"
            f"background-color: {panel};"
            f"border: 1px solid {border_subtle};"
            f"border-radius: {radius_md}px;"
            f"padding: {pad_y_sm}px {pad_x_sm}px;"
            f"color: {text};"
            "}"
            "QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover {"
            f"border-color: {border_hover};"
            "}"
            "QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {"
            f"border-color: {accent};"
            "}"
            "QPushButton {"
            f"background-color: {panel};"
            f"border: 1px solid {border_subtle};"
            f"border-radius: {radius_md}px;"
            f"padding: {pad_y_btn}px {pad_x_btn}px;"
            f"color: {text};"
            "}"
            "QPushButton:hover {"
            f"background-color: {panel_hover};"
            f"border-color: {border_hover};"
            "}"
            "QPushButton:pressed {"
            f"background-color: {panel_2};"
            f"border-color: {primary};"
            "}"
            "QPushButton:disabled {"
            f"background-color: {panel_2};"
            f"border-color: {border_subtle};"
            f"color: {text_disabled};"
            "}"
            "QComboBox {"
            f"background-color: {panel};"
            f"border: 1px solid {border_subtle};"
            f"border-radius: {radius_md}px;"
            f"padding: {pad_y_sm}px {pad_x_sm}px;"
            f"color: {text};"
            "}"
            "QComboBox:hover {"
            f"border-color: {border_hover};"
            "}"
            "QComboBox:focus {"
            f"border-color: {accent};"
            "}"
            "QComboBox::drop-down {"
            "border: none;"
            f"width: {_px(28, 22)}px;"
            "}"
            "QComboBox QAbstractItemView {"
            f"background-color: {panel};"
            f"color: {text};"
            f"border: 1px solid {border_subtle};"
            "outline: 0;"
            f"selection-background-color: {highlight};"
            "}"
            "QAbstractItemView::item {"
            f"padding: {menu_item_y}px {pad_x_sm}px;"
            f"border-radius: {radius_sm}px;"
            "}"
            "QSpinBox, QDoubleSpinBox {"
            f"background-color: {panel};"
            f"border: 1px solid {border_subtle};"
            f"border-radius: {radius_md}px;"
            f"padding: {pad_y_sm}px {pad_x_sm}px;"
            f"color: {text};"
            "}"
            "QSpinBox:hover, QDoubleSpinBox:hover {"
            f"border-color: {border_hover};"
            "}"
            "QSpinBox:focus, QDoubleSpinBox:focus {"
            f"border-color: {accent};"
            "}"
            "QSpinBox::up-button, QDoubleSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::down-button {"
            f"width: {_px(18, 14)}px;"
            "border: none;"
            "background: transparent;"
            "}"
            "QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover, QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {"
            f"background: {panel_2};"
            "border-radius: 8px;"
            "}"
            "QSlider {"
            "background: transparent;"
            "border: none;"
            "outline: none;"
            "}"
            "QSlider:focus {"
            "border: none;"
            "outline: none;"
            "}"
            "QSlider::groove:horizontal {"
            f"background: {panel_2};"
            "border: none;"
            f"height: {slider_groove_h}px;"
            f"border-radius: {_px(4, 3)}px;"
            "}"
            "QSlider::sub-page:horizontal {"
            f"background: {accent};"
            "border: none;"
            "border-radius: 4px;"
            "}"
            "QSlider::add-page:horizontal {"
            f"background: {panel_2};"
            "border: none;"
            "border-radius: 4px;"
            "}"
            "QSlider::handle:horizontal {"
            f"background: {text};"
            f"width: {slider_handle_w}px;"
            f"margin: {-_px(4, 3)}px 0;"
            f"border-radius: {radius_sm}px;"
            f"border: 2px solid {accent};"
            "outline: none;"
            "}"
            "QSlider::handle:horizontal:hover {"
            f"border-color: {primary};"
            "}"
            "QSlider::handle:horizontal:pressed {"
            f"border-color: {success};"
            "}"
            "QCheckBox {"
            f"spacing: {menu_item_y}px;"
            "background: transparent;"
            "}"
            "QCheckBox:hover {"
            f"color: {text};"
            "}"
            "QCheckBox::indicator {"
            f"width: {checkbox_ind}px;"
            f"height: {checkbox_ind}px;"
            f"border-radius: {checkbox_rad}px;"
            f"border: 1px solid {border_subtle};"
            f"background-color: {panel};"
            "}"
            "QCheckBox::indicator:hover {"
            f"border-color: {border_hover};"
            "}"
            "QCheckBox::indicator:checked {"
            f"background-color: {accent};"
            f"border-color: {accent};"
            "}"
            "QCheckBox::indicator:checked:hover {"
            f"background-color: {primary};"
            f"border-color: {primary};"
            "}"
            "QScrollBar:vertical {"
            "background: transparent;"
            f"width: {scrollbar_thick}px;"
            "margin: 0px;"
            "}"
            "QScrollBar::handle:vertical {"
            f"background: {panel_hover};"
            f"border-radius: {scrollbar_rad}px;"
            f"min-height: {_px(28, 20)}px;"
            "}"
            "QScrollBar::handle:vertical:hover {"
            f"background: {highlight};"
            "}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {"
            "height: 0px;"
            "}"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {"
            "background: transparent;"
            "}"
            "QScrollBar:horizontal {"
            "background: transparent;"
            f"height: {scrollbar_thick}px;"
            "margin: 0px;"
            "}"
            "QScrollBar::handle:horizontal {"
            f"background: {panel_hover};"
            f"border-radius: {scrollbar_rad}px;"
            f"min-width: {_px(28, 20)}px;"
            "}"
            "QScrollBar::handle:horizontal:hover {"
            f"background: {highlight};"
            "}"
            "QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {"
            "width: 0px;"
            "}"
            "QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {"
            "background: transparent;"
            "}"
            "QProgressBar {"
            f"border: 1px solid {border_subtle};"
            f"border-radius: {radius_md}px;"
            f"background: {panel_2};"
            "text-align: center;"
            f"padding: {_px(2, 1)}px;"
            "}"
            "QProgressBar::chunk {"
            f"background: {primary};"
            f"border-radius: {radius_sm}px;"
            "}"
            "QStatusBar {"
            f"background: {bg};"
            f"color: {text_muted};"
            "}"
            "QStatusBar::item {"
            "border: none;"
            "}"
        )

        try:
            c = QColor(accent)
            if c.isValid():
                self.waveform_label.setStyleSheet(f"color: rgba({c.red()}, {c.green()}, {c.blue()}, 170);")
        except Exception:
            pass

        try:
            self.processing_label.setStyleSheet(f"color: {success}; font-weight: bold;")
        except Exception:
            pass

        try:
            self.settings_panel.apply_theme(dict(self._theme))
        except Exception:
            pass

        try:
            self.waveform_widget.apply_theme({"bg": bg, "accent": accent})
        except Exception:
            pass

        try:
            self.piano_roll.apply_theme(dict(self._theme))
        except Exception:
            pass

    def _setup_debug_dock(self):
        dock = QDockWidget("Debug", self)
        dock.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)

        container = QWidget()
        layout = QVBoxLayout(container)

        self._debug_text = QTextEdit()
        self._debug_text.setPlaceholderText("Type feedback/approval notes here. Click Save to write to disk.")
        layout.addWidget(self._debug_text)

        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self._save_debug_notes)
        layout.addWidget(save_btn)

        dock.setWidget(container)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)

        self._load_debug_notes()

    def _load_debug_notes(self):
        if not self._debug_notes_path or self._debug_text is None:
            return
        try:
            if os.path.exists(self._debug_notes_path):
                with open(self._debug_notes_path, "r", encoding="utf-8") as f:
                    self._debug_text.setPlainText(f.read())
        except Exception:
            pass

    def _save_debug_notes(self):
        if not self._debug_notes_path or self._debug_text is None:
            return
        try:
            with open(self._debug_notes_path, "w", encoding="utf-8") as f:
                f.write(self._debug_text.toPlainText())
        except Exception:
            pass

    def _on_browse(self):
        """Open file dialog to select audio file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Audio File",
            "",
            "Audio Files (*.wav *.mp3 *.flac *.ogg);;All Files (*)"
        )

        if file_path:
            self._load_audio_file(file_path)

    def _is_supported_audio_file(self, file_path: str) -> bool:
        ext = os.path.splitext(file_path)[1].lower()
        return ext in {".wav", ".mp3", ".flac", ".ogg"}

    def _set_drop_highlight(self, active: bool):
        if self._drop_highlight_active == active:
            return
        self._drop_highlight_active = active
        if active:
            accent = str(getattr(self, "_theme", {}).get("accent", "#33CED6"))
            self.waveform_widget.setStyleSheet(f"border: 2px dashed {accent}; border-radius: 6px;")
        else:
            self.waveform_widget.setStyleSheet("")

    def dragEnterEvent(self, event):
        md = event.mimeData()
        if md.hasUrls():
            urls = md.urls()
            if len(urls) == 1 and urls[0].isLocalFile():
                path = urls[0].toLocalFile()
                if self._is_supported_audio_file(path):
                    event.acceptProposedAction()
                    self._set_drop_highlight(True)
                    return
        event.ignore()

    def dragMoveEvent(self, event):
        md = event.mimeData()
        if md.hasUrls():
            urls = md.urls()
            if len(urls) == 1 and urls[0].isLocalFile():
                path = urls[0].toLocalFile()
                if self._is_supported_audio_file(path):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dragLeaveEvent(self, event):
        self._set_drop_highlight(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        try:
            md = event.mimeData()
            if md.hasUrls():
                urls = md.urls()
                if len(urls) == 1 and urls[0].isLocalFile():
                    path = urls[0].toLocalFile()
                    if self._is_supported_audio_file(path):
                        event.acceptProposedAction()
                        self._set_drop_highlight(False)
                        self._load_audio_file(path)
                        return
            event.ignore()
        finally:
            self._set_drop_highlight(False)

    def _load_audio_file(self, file_path: str, accurate_pitch: bool = False):
        """Load an audio file and update the UI."""
        if self._load_thread is not None and self._load_thread.isRunning():
            return

        if self._warmup_thread is not None and self._warmup_thread.isRunning():
            try:
                self._warmup_thread.requestInterruption()
            except Exception:
                pass

        try:
            self._stop_preview_playback()

            self._loading_file_path = str(file_path)
            self._load_dialog = None

            if self._show_loading_dialog:
                dlg = QProgressDialog("Loading audio...", None, 0, 4, self)
                dlg.setWindowTitle("Loading")
                dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
                dlg.setMinimumDuration(0)
                dlg.setCancelButton(None)
                try:
                    dlg.setAutoClose(False)
                    dlg.setAutoReset(False)
                    dlg.setValue(0)
                except Exception:
                    pass
                dlg.show()
                self._load_dialog = dlg

            self.browse_btn.setEnabled(False)
            self.settings_panel.set_buttons_enabled(process=False, export=False)
            self.waveform_toggle_btn.setEnabled(False)
            self.play_btn.setEnabled(False)

            self._load_thread = LoadAudioThread(str(file_path), fast_pitch=not bool(accurate_pitch))
            self._load_thread.progress.connect(self._on_load_progress)
            self._load_thread.finished.connect(self._on_load_finished)
            self._load_thread.error.connect(self._on_load_error)
            self._load_thread.start()

        except Exception as e:
            self._close_load_dialog()
            try:
                self.browse_btn.setEnabled(True)
            except Exception:
                pass
            QMessageBox.critical(self, "Error", f"Failed to load audio file:\n{str(e)}")

    def _on_load_progress(self, msg: str):
        if self._load_dialog is not None:
            try:
                self._load_dialog.setLabelText(str(msg))
                m = str(msg).lower()
                if "reading" in m:
                    self._load_dialog.setValue(1)
                elif "detecting" in m:
                    self._load_dialog.setValue(2)
                elif "final" in m:
                    self._load_dialog.setValue(3)
            except Exception:
                pass

    def _close_load_dialog(self):
        if self._load_dialog is None:
            return
        try:
            self._load_dialog.close()
        except Exception:
            pass
        self._load_dialog = None

    def _on_load_finished(self, audio, sr: int, original_sr: int, freq, note, cents):
        if self._load_dialog is not None:
            try:
                self._load_dialog.setLabelText("Rendering waveform...")
                self._load_dialog.setValue(4)
            except Exception:
                pass

        self.original_audio = np.asarray(audio, dtype=np.float32)
        self.sample_rate = int(sr)
        self.original_sample_rate = int(original_sr)
        self.current_file_path = str(self._loading_file_path) if self._loading_file_path else None
        self.processed_audio = None
        self._waveform_view = "processed"

        if self.current_file_path:
            self.file_path_edit.setText(self.current_file_path)

        self._update_waveform_display()

        try:
            self.settings_panel.set_sample_rate(int(self.sample_rate))
        except Exception:
            pass

        self.settings_panel.set_detected_pitch(note, freq, cents)

        if note is not None:
            self._set_target_midi(note_name_to_midi(note), schedule_processing=False, immediate=False)

        self._sync_piano_roll_to_settings()

        self._close_load_dialog()
        try:
            self.browse_btn.setEnabled(True)
        except Exception:
            pass

        self.settings_panel.set_buttons_enabled(process=False, export=False)
        self.waveform_toggle_btn.setEnabled(False)
        self._update_play_button_enabled()

        self._schedule_processing(immediate=True)

    def _on_load_error(self, error_msg: str):
        self._close_load_dialog()
        try:
            self.browse_btn.setEnabled(True)
        except Exception:
            pass
        QMessageBox.critical(self, "Error", f"Failed to load audio file:\n{str(error_msg)}")

    def _schedule_processing(self, immediate: bool = False):
        if self.original_audio is None:
            return

        self.settings_panel.set_buttons_enabled(process=False, export=False)

        if immediate:
            self._processing_debounce_timer.start(0)
        else:
            self._processing_debounce_timer.start()

    def _on_process(self):
        """Process the audio with current settings."""
        if self.original_audio is None:
            return

        settings = self.settings_panel.get_settings()
        self._start_processing_with_settings(settings)

    def _start_processing_with_settings(self, settings: dict):
        if self.original_audio is None:
            return

        if hasattr(self, "processing_thread") and self.processing_thread is not None and self.processing_thread.isRunning():
            self._processing_pending = True
            self._pending_settings = settings
            return

        self._stop_preview_playback()

        self._show_processing_label("Processing...")

        self._processing_token += 1
        token = self._processing_token
        self._current_processing_token = token

        self.processing_thread = ProcessingThread(self.original_audio, self.sample_rate, settings)
        self.processing_thread.finished.connect(lambda result, _t=token: self._on_processing_finished(result, _t))
        self.processing_thread.error.connect(lambda msg, _t=token: self._on_processing_error(msg, _t))
        self.processing_thread.progress.connect(lambda msg, _t=token: self._on_processing_progress(msg, _t))

        self.processing_thread.start()

    def _on_processing_progress(self, msg: str, token: int):
        if token != self._current_processing_token:
            return
        self._show_processing_label(f"Processing... {msg}")

    def _on_processing_finished(self, result: np.ndarray, token: int):
        """Handle completed processing."""
        if token != self._current_processing_token:
            return

        self._latest_completed_token = int(token)
        self._pending_processed_result = result

        try:
            self._apply_processed_timer.start()
        except Exception:
            self._apply_latest_processed_result()

        if self._processing_pending and self._pending_settings is not None:
            pending = self._pending_settings
            self._processing_pending = False
            self._pending_settings = None
            self._start_processing_with_settings(pending)

    def _apply_latest_processed_result(self):
        token = int(self._latest_completed_token)
        if token != self._current_processing_token:
            return

        if self._pending_processed_result is None:
            return

        self._hide_processing_label()
        self.processed_audio = self._pending_processed_result
        self._pending_processed_result = None

        if self._waveform_view == "processed" or self.processed_audio is None:
            self._waveform_view = "processed"
        self._update_waveform_display()

        self._sync_piano_roll_to_settings()

        self.settings_panel.set_buttons_enabled(process=False, export=True)
        self.waveform_toggle_btn.setEnabled(True)
        self._update_play_button_enabled()

    def _on_processing_error(self, error_msg: str, token: int):
        """Handle processing error."""
        if token != self._current_processing_token:
            return

        self._hide_processing_label()
        QMessageBox.critical(self, "Processing Error", f"Failed to process audio:\n{error_msg}")

        if self._processing_pending:
            self._processing_pending = False
            self._pending_settings = None

    def _on_export(self):
        """Export processed audio to file."""
        if self.processed_audio is None:
            return

        from audio.loader import save_audio, set_wav_root_note

        if self.current_file_path:
            base = os.path.splitext(os.path.basename(self.current_file_path))[0]
            target = self.settings_panel.get_target_note()
            default_name = f"{base}_{target}_tuned.wav"
        else:
            default_name = "output.wav"

        start_path = default_name
        if self.current_file_path:
            try:
                start_path = os.path.join(os.path.dirname(self.current_file_path), default_name)
            except Exception:
                start_path = default_name

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Audio",
            start_path,
            "WAV Files (*.wav)"
        )

        if file_path:
            try:
                save_audio(file_path, self.processed_audio, self.sample_rate)
                try:
                    target = self.settings_panel.get_target_note()
                    if target:
                        set_wav_root_note(file_path, note_name_to_midi(target), self.sample_rate)
                except Exception:
                    pass
                self.statusBar().showMessage("Exported!", 2000)
            except Exception as e:
                QMessageBox.critical(self, "Export Error", f"Failed to export:\n{str(e)}")

    def _make_unique_export_path(self, path: str) -> str:
        base, ext = os.path.splitext(str(path))
        candidate = str(path)
        i = 1
        while os.path.exists(candidate):
            candidate = f"{base} ({i}){ext}"
            i += 1
        return candidate

    def _on_quick_export(self):
        if self.processed_audio is None:
            return

        if not self.current_file_path:
            QMessageBox.information(self, "Quick Export", "Load a sample first.")
            return

        base = os.path.splitext(os.path.basename(self.current_file_path))[0]
        target = self.settings_panel.get_target_note()
        default_name = f"{base}_{target}_tuned.wav" if target else f"{base}_tuned.wav"
        out_path = os.path.join(os.path.dirname(self.current_file_path), default_name)
        out_path = self._make_unique_export_path(out_path)

        try:
            from audio.loader import save_audio, set_wav_root_note
            save_audio(out_path, self.processed_audio, self.sample_rate)
            try:
                if target:
                    set_wav_root_note(out_path, note_name_to_midi(target), self.sample_rate)
            except Exception:
                pass
            self.statusBar().showMessage(f"Quick exported: {os.path.basename(out_path)}", 2500)
        except Exception as e:
            QMessageBox.critical(self, "Quick Export Error", f"Failed to export:\n{str(e)}")

    def _on_file_new_sample(self):
        self._on_browse()

    def _on_file_refresh_sample(self):
        if not self.current_file_path:
            return

        try:
            self.settings_panel.blockSignals(True)
            self.settings_panel.reset_to_defaults()
        finally:
            try:
                self.settings_panel.blockSignals(False)
            except Exception:
                pass

        self._load_audio_file(self.current_file_path, accurate_pitch=True)

    def _on_settings_changed(self):
        """Handle settings changes - invalidate processed audio."""
        self._schedule_save_settings()
        self._schedule_processing()

    def _sync_piano_roll_to_settings(self):
        target = self.settings_panel.get_target_note()
        self.piano_roll.set_selected_note(target)
        self.piano_roll.set_display_octave(self.settings_panel.octave_spin.value())

        try:
            self.waveform_widget.set_blob_midi_note(note_name_to_midi(target), emit_signal=False)
        except Exception:
            pass

        try:
            y_min, y_max = self.waveform_widget.get_midi_view_range()
            self.piano_roll.set_midi_range(y_min, y_max)
        except Exception:
            pass

    def _toggle_waveform_view(self):
        if self.processed_audio is None:
            return

        if self._is_preview_playing():
            self._ramp_volume(0.0, duration_ms=40, on_done=self._stop_preview_playback)

        try:
            current = str(self._waveform_view)
        except Exception:
            current = "original"

        try:
            phase = getattr(self, "_waveform_fade_phase", None)
            pending = getattr(self, "_waveform_fade_target_view", None)
            if phase in ("out", "in") and pending in ("original", "processed"):
                current = str(pending)
        except Exception:
            pass

        target = "original" if current == "processed" else "processed"

        anim = getattr(self, "_waveform_fade_anim", None)
        fx = getattr(self, "_waveform_opacity_effect", None)
        if anim is None or fx is None:
            self._waveform_view = target
            self._update_waveform_display()
            self._update_play_button_enabled()
            return

        try:
            if anim.state() != QAbstractAnimation.State.Stopped:
                anim.stop()
        except Exception:
            pass

        try:
            start = float(fx.opacity())
        except Exception:
            start = 1.0

        try:
            self._waveform_fade_target_view = target
            self._waveform_fade_phase = "out"
            anim.setDuration(140)
            anim.setStartValue(start)
            anim.setEndValue(0.0)
            anim.start()
        except Exception:
            self._waveform_view = target
            self._update_waveform_display()
            self._update_play_button_enabled()

    def _update_waveform_display(self):
        if self._waveform_view == "processed" and self.processed_audio is not None:
            self.waveform_label.setText("Processed")
            self.waveform_widget.set_audio(self.processed_audio, self.sample_rate)
            self.waveform_toggle_btn.setText("Show Original")
        else:
            self.waveform_label.setText("Original")
            if self.original_audio is not None:
                self.waveform_widget.set_audio(self.original_audio, self.sample_rate)
            else:
                self.waveform_widget.clear()
            self.waveform_toggle_btn.setText("Show Processed")
            self.waveform_toggle_btn.setEnabled(self.processed_audio is not None)

    def _current_preview_audio(self):
        if self._waveform_view == "processed" and self.processed_audio is not None:
            return self.processed_audio
        return self.original_audio

    def _update_play_button_enabled(self):
        self.play_btn.setEnabled(self._current_preview_audio() is not None)

    def _is_preview_playing(self) -> bool:
        if self._audio_sink is None:
            return False
        try:
            return self._audio_sink.state() == QAudio.State.ActiveState
        except Exception:
            return False

    def _stop_preview_playback(self):
        try:
            if self._volume_ramp_timer.isActive():
                self._volume_ramp_timer.stop()
        except Exception:
            pass
        self._volume_ramp_on_done = None

        if self._audio_sink is None:
            try:
                self.play_btn.setText("Play")
            except Exception:
                pass
            return

        try:
            self._audio_sink.stop()
        except Exception:
            pass

        self._schedule_preview_cleanup()

    def _schedule_preview_cleanup(self):
        if self._preview_cleanup_scheduled:
            return
        self._preview_cleanup_scheduled = True
        QTimer.singleShot(0, self._finalize_preview_cleanup)

    def _finalize_preview_cleanup(self):
        self._preview_cleanup_scheduled = False

        sink = self._audio_sink
        if sink is None:
            return

        try:
            if sink.state() == QAudio.State.ActiveState:
                self._schedule_preview_cleanup()
                return
        except Exception:
            pass

        try:
            sink.stateChanged.disconnect(self._on_preview_state_changed)
        except Exception:
            pass

        try:
            sink.stop()
        except Exception:
            pass

        buf = self._audio_buffer
        self._audio_sink = None
        self._audio_buffer = None
        self._audio_bytes = None

        try:
            if buf is not None:
                buf.close()
                buf.deleteLater()
        except Exception:
            pass

        try:
            sink.deleteLater()
        except Exception:
            pass

        try:
            self.play_btn.setText("Play")
        except Exception:
            pass

    def _build_preview_pcm_bytes(self, audio: np.ndarray, sr: int) -> bytes:
        audio_arr = np.asarray(audio, dtype=np.float32)
        if audio_arr.ndim != 1:
            audio_arr = np.asarray(audio_arr.reshape(-1), dtype=np.float32)

        n = int(audio_arr.shape[0])
        if n <= 0:
            return b""

        pre_ms = 0
        pre_n = max(0, int(int(sr) * (float(pre_ms) / 1000.0)))
        if pre_n > 0:
            audio_arr = np.concatenate([np.zeros(pre_n, dtype=np.float32), audio_arr], axis=0)

        fade_ms = 3
        fade_n = max(0, min(int(audio_arr.shape[0]), int(int(sr) * (float(fade_ms) / 1000.0))))
        if fade_n > 1:
            ramp = np.linspace(0.0, 1.0, fade_n, dtype=np.float32)
            audio_arr = audio_arr.copy()
            audio_arr[:fade_n] *= ramp

        audio_arr = np.clip(audio_arr, -1.0, 1.0)
        pcm = (audio_arr * 32767.0).astype(np.int16, copy=False)
        return pcm.tobytes(order="C")

    def _start_preview_playback(self):
        self._stop_preview_playback()

        audio = self._current_preview_audio()
        if audio is None:
            return

        pcm_bytes = self._build_preview_pcm_bytes(audio, int(self.sample_rate))
        if not pcm_bytes:
            return

        fmt = QAudioFormat()
        fmt.setSampleRate(int(self.sample_rate))
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)

        device = QMediaDevices.defaultAudioOutput()
        self._audio_sink = QAudioSink(device, fmt, self)
        self._audio_sink.stateChanged.connect(self._on_preview_state_changed)
        try:
            self._audio_sink.setBufferSize(int(self.sample_rate) * 2 * 2)
        except Exception:
            pass
        self._audio_sink.setVolume(float(max(0.0, min(1.0, self._preview_volume))))

        self._audio_bytes = QByteArray(pcm_bytes)
        self._audio_buffer = QBuffer(self)
        self._audio_buffer.setData(self._audio_bytes)
        self._audio_buffer.open(QIODeviceBase.OpenModeFlag.ReadOnly)

        self._audio_sink.start(self._audio_buffer)

    def _toggle_playback(self):
        if self._is_preview_playing():
            self._ramp_volume(0.0, duration_ms=35, on_done=self._stop_preview_playback)
            return

        try:
            self._start_preview_playback()
        except Exception as e:
            QMessageBox.critical(self, "Playback Error", f"Failed to play audio:\n{str(e)}")

    def _ramp_volume(self, target: float, duration_ms: int = 40, on_done=None):
        """Small preview-only fade to prevent clicks/pops on some audio devices."""
        t = float(max(0.0, min(1.0, target)))
        if self._volume_ramp_timer.isActive():
            self._volume_ramp_timer.stop()

        self._volume_ramp_on_done = on_done
        self._volume_ramp_target = t

        try:
            if self._audio_sink is not None:
                cur = float(self._audio_sink.volume())
            else:
                cur = float(self._preview_volume)
        except Exception:
            cur = float(self._preview_volume)

        interval = int(self._volume_ramp_timer.interval())
        steps = max(1, int(max(0, int(duration_ms)) / max(1, interval)))
        self._volume_ramp_steps_left = steps
        self._volume_ramp_step = (t - cur) / float(steps)

        self._volume_ramp_timer.start()

    def _on_volume_ramp_tick(self):
        if self._volume_ramp_steps_left <= 0:
            self._volume_ramp_timer.stop()
            if callable(self._volume_ramp_on_done):
                fn = self._volume_ramp_on_done
                self._volume_ramp_on_done = None
                fn()
            return

        self._volume_ramp_steps_left -= 1
        try:
            if self._audio_sink is not None:
                cur = float(self._audio_sink.volume())
            else:
                cur = 0.0
        except Exception:
            cur = 0.0

        new_v = cur + float(self._volume_ramp_step)
        if (self._volume_ramp_step >= 0 and new_v > self._volume_ramp_target) or (
            self._volume_ramp_step < 0 and new_v < self._volume_ramp_target
        ):
            new_v = float(self._volume_ramp_target)

        try:
            if self._audio_sink is not None:
                self._audio_sink.setVolume(float(max(0.0, min(1.0, new_v))))
        except Exception:
            pass

    def _on_preview_state_changed(self, state):
        try:
            if state == QAudio.State.ActiveState:
                self.play_btn.setText("Stop")
            else:
                self.play_btn.setText("Play")
        except Exception:
            pass

        try:
            if state in (QAudio.State.IdleState, QAudio.State.StoppedState):
                self._schedule_preview_cleanup()
        except Exception:
            pass

    def closeEvent(self, event):
        try:
            self._stop_preview_playback()
        except Exception:
            pass
        try:
            self._save_persistent_settings()
        except Exception:
            pass
        try:
            self._save_debug_notes()
        except Exception:
            pass
        super().closeEvent(event)
