import os
import sys
from pathlib import Path
import numpy as np
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QFileDialog, QPushButton, QLineEdit, QLabel, QMessageBox,
    QDockWidget, QTextEdit,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QByteArray, QBuffer, QIODeviceBase, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut, QPixmap
from PyQt6.QtMultimedia import QAudio, QAudioFormat, QAudioSink, QMediaDevices

from ui.waveform_widget import WaveformWidget
from ui.piano_roll_widget import PianoRollWidget
from ui.settings_panel import SettingsPanel

from audio.loader import load_audio, save_audio, set_wav_root_note
from audio.pitch_detector import get_predominant_pitch
from audio.autotuner import autotune_to_note, autotune_with_formant_shift
from audio.normalizer import normalize_audio
from audio.cleanliness import apply_cleanliness
from audio.time_stretch import STRETCHERS
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
            result = self.audio.copy()

            self.progress.emit("Autotuning...")
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

            if self.settings["cleanliness_percent"] > 0:
                self.progress.emit(f"Applying {self.settings['cleanliness_percent']}% cleanliness...")
                result = apply_cleanliness(result, self.sr, self.settings["cleanliness_percent"])

            if self.settings["normalize"]:
                self.progress.emit("Normalizing...")
                result = normalize_audio(result, target_db=-0.1)

            self.finished.emit(result)

        except Exception as e:
            self.error.emit(str(e))


class MainWindow(QMainWindow):
    """Main application window for FreqEnforcer."""

    def __init__(self, debug: bool = False, debug_notes_path: str | None = None):
        super().__init__()

        self.setWindowTitle("FreqEnforcer")
        self.setMinimumSize(900, 600)
        self.resize(1100, 700)

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

        self._processing_pending = False
        self._pending_settings = None
        self._processing_token = 0
        self._current_processing_token = 0

        self._drop_highlight_active = False

        self._debug_enabled = bool(debug)
        self._debug_notes_path = debug_notes_path
        self._debug_text = None

        self._setup_ui()
        self._connect_signals()

        if self._debug_enabled:
            self._setup_debug_dock()

        self._apply_theme()

        self.setAcceptDrops(True)

    def _setup_ui(self):
        """Create and arrange all UI elements."""
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)

        file_bar = QHBoxLayout()

        logo_label = QLabel()
        base_dir = Path(getattr(sys, "_MEIPASS", str(Path(__file__).resolve().parent.parent)))
        logo_path = base_dir / "LOGO.png"
        if logo_path.exists():
            pix = QPixmap(str(logo_path))
            if not pix.isNull():
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

        content_layout = QHBoxLayout()

        self.piano_roll = PianoRollWidget()
        self.piano_roll.setMaximumWidth(80)
        content_layout.addWidget(self.piano_roll)

        waveform_container = QVBoxLayout()

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
        waveform_container.addWidget(self.waveform_widget, stretch=1)

        playback_row = QHBoxLayout()
        self.play_btn = QPushButton("Play")
        self.play_btn.setEnabled(False)
        self.play_btn.clicked.connect(self._toggle_playback)
        playback_row.addWidget(self.play_btn)
        playback_row.addStretch(1)
        waveform_container.addLayout(playback_row)

        content_layout.addLayout(waveform_container, stretch=1)

        self.settings_panel = SettingsPanel()
        content_layout.addWidget(self.settings_panel)

        main_layout.addLayout(content_layout, stretch=1)

        self.settings_panel.set_buttons_enabled(process=False, export=False)

        self._space_shortcut = QShortcut(QKeySequence("Space"), self)
        self._space_shortcut.activated.connect(self._toggle_playback)

    def _connect_signals(self):
        """Connect all signals and slots."""
        self.settings_panel.export_clicked.connect(self._on_export)
        self.settings_panel.settings_changed.connect(self._on_settings_changed)
        self.settings_panel.octave_spin.valueChanged.connect(self._sync_piano_roll_to_settings)
        self.settings_panel.note_combo.currentTextChanged.connect(lambda _t: self._sync_piano_roll_to_settings())
        self.waveform_widget.blob_note_changed.connect(self._on_waveform_blob_note_changed)
        self.waveform_widget.midi_view_range_changed.connect(self.piano_roll.set_midi_range)

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
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #2E2E2E;
                color: #ffffff;
            }
            QLineEdit {
                background-color: #404040;
                border: 1px solid #1D5AAA;
                border-radius: 4px;
                padding: 5px;
                color: #ffffff;
            }
            QPushButton {
                background-color: #404040;
                border: 1px solid #1D5AAA;
                border-radius: 4px;
                padding: 5px 15px;
                color: #ffffff;
            }
            QPushButton:hover {
                background-color: #1D5AAA;
            }
            QGroupBox {
                border: 1px solid #1D5AAA;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QComboBox {
                background-color: #404040;
                border: 1px solid #1D5AAA;
                border-radius: 4px;
                padding: 5px;
                color: #ffffff;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox QAbstractItemView {
                background-color: #404040;
                color: #ffffff;
                selection-background-color: #33CED6;
            }
            QSpinBox {
                background-color: #404040;
                border: 1px solid #1D5AAA;
                border-radius: 4px;
                padding: 5px;
                color: #ffffff;
            }
            QSlider::groove:horizontal {
                background: #404040;
                height: 8px;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #33CED6;
                width: 16px;
                margin: -4px 0;
                border-radius: 8px;
            }
            QSlider::sub-page:horizontal {
                background: #4EDE83;
                border-radius: 4px;
            }
            QCheckBox {
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 3px;
                border: 1px solid #1D5AAA;
                background-color: #404040;
            }
            QCheckBox::indicator:checked {
                background-color: #33CED6;
                border-color: #33CED6;
            }
        """)

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
            self.waveform_widget.setStyleSheet("border: 2px dashed #33CED6; border-radius: 6px;")
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

    def _load_audio_file(self, file_path: str):
        """Load an audio file and update the UI."""
        try:
            self._stop_preview_playback()

            self.original_audio, self.sample_rate, self.original_sample_rate = load_audio(file_path)
            self.current_file_path = file_path
            self.processed_audio = None
            self._waveform_view = "processed"

            self.file_path_edit.setText(file_path)
            self._update_waveform_display()

            freq, note, cents = get_predominant_pitch(self.original_audio, self.sample_rate)
            self.settings_panel.set_detected_pitch(note, freq, cents)

            if note is not None:
                self._set_target_midi(note_name_to_midi(note), schedule_processing=False, immediate=False)

            self._sync_piano_roll_to_settings()

            self.settings_panel.set_buttons_enabled(process=False, export=False)
            self.waveform_toggle_btn.setEnabled(False)
            self._update_play_button_enabled()

            self._schedule_processing(immediate=True)

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load audio file:\n{str(e)}")

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

        self.processing_label.setText("Processing...")
        self.processing_label.setVisible(True)

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
        self.processing_label.setText(f"Processing... {msg}")

    def _on_processing_finished(self, result: np.ndarray, token: int):
        """Handle completed processing."""
        if token != self._current_processing_token:
            return

        self.processing_label.setVisible(False)
        self.processed_audio = result

        if self._waveform_view == "processed" or self.processed_audio is None:
            self._waveform_view = "processed"
        self._update_waveform_display()

        self._sync_piano_roll_to_settings()

        self.settings_panel.set_buttons_enabled(process=False, export=True)
        self.waveform_toggle_btn.setEnabled(True)
        self._update_play_button_enabled()

        if self._processing_pending and self._pending_settings is not None:
            pending = self._pending_settings
            self._processing_pending = False
            self._pending_settings = None
            self._start_processing_with_settings(pending)

    def _on_processing_error(self, error_msg: str, token: int):
        """Handle processing error."""
        if token != self._current_processing_token:
            return

        self.processing_label.setVisible(False)
        QMessageBox.critical(self, "Processing Error", f"Failed to process audio:\n{error_msg}")

        if self._processing_pending:
            self._processing_pending = False
            self._pending_settings = None

    def _on_export(self):
        """Export processed audio to file."""
        if self.processed_audio is None:
            return

        if self.current_file_path:
            base = os.path.splitext(os.path.basename(self.current_file_path))[0]
            target = self.settings_panel.get_target_note()
            default_name = f"{base}_{target}_tuned.wav"
        else:
            default_name = "output.wav"

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Audio",
            default_name,
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

    def _on_settings_changed(self):
        """Handle settings changes - invalidate processed audio."""
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

        self._waveform_view = "original" if self._waveform_view == "processed" else "processed"
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
            self._save_debug_notes()
        except Exception:
            pass
        super().closeEvent(event)
