from __future__ import annotations

from PyQt6.QtCore import QSettings, Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ui.theme_editor import ThemeEditorWindow
from utils.i18n import tr


class PreferencesDialog(QDialog):
    preferences_changed = pyqtSignal()
    theme_applied = pyqtSignal(dict)

    def __init__(
        self,
        parent=None,
        qsettings: QSettings | None = None,
        theme: dict | None = None,
        themes: dict | None = None,
        themes_dir: str | None = None,
    ):
        super().__init__(parent)
        self.setModal(False)
        self.resize(520, 360)

        self._qsettings = qsettings if isinstance(qsettings, QSettings) else QSettings("FreqEnforcer", "FreqEnforcer")
        self._theme = dict(theme) if isinstance(theme, dict) else {}
        self._themes = dict(themes) if isinstance(themes, dict) else {}
        self._themes_dir = str(themes_dir) if themes_dir else ""

        root = QVBoxLayout(self)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs)

        self.preferences_page = QWidget()
        prefs_layout = QVBoxLayout(self.preferences_page)
        prefs_layout.setSpacing(10)

        self.show_loading_checkbox = QCheckBox()
        self.performance_mode_checkbox = QCheckBox()
        self.warmup_checkbox = QCheckBox()
        self.note_notation_label = QLabel()
        self.note_notation_segment = QWidget()
        self.note_notation_segment.setObjectName("noteNotationSegment")
        notation_row = QHBoxLayout(self.note_notation_segment)
        notation_row.setContentsMargins(0, 0, 0, 0)
        notation_row.setSpacing(0)
        self.note_notation_group = QButtonGroup(self)
        self.note_notation_group.setExclusive(True)

        self.note_notation_flats_btn = QPushButton()
        self.note_notation_flats_btn.setCheckable(True)
        self.note_notation_flats_btn.setObjectName("noteNotationFlats")

        self.note_notation_sharps_btn = QPushButton()
        self.note_notation_sharps_btn.setCheckable(True)
        self.note_notation_sharps_btn.setObjectName("noteNotationSharps")

        self.note_notation_group.addButton(self.note_notation_flats_btn)
        self.note_notation_group.addButton(self.note_notation_sharps_btn)
        notation_row.addWidget(self.note_notation_flats_btn, 1)
        notation_row.addWidget(self.note_notation_sharps_btn, 1)

        self.show_loading_checkbox.toggled.connect(
            lambda checked: self._on_preference_toggled("options/show_loading_dialog", checked)
        )
        self.performance_mode_checkbox.toggled.connect(
            lambda checked: self._on_preference_toggled("options/performance_mode", checked)
        )
        self.warmup_checkbox.toggled.connect(
            lambda checked: self._on_preference_toggled("options/warmup_enabled", checked)
        )
        self.note_notation_flats_btn.toggled.connect(lambda checked: self._on_note_notation_toggled("flats", checked))
        self.note_notation_sharps_btn.toggled.connect(lambda checked: self._on_note_notation_toggled("sharps", checked))

        prefs_layout.addWidget(self.show_loading_checkbox)
        prefs_layout.addWidget(self.performance_mode_checkbox)
        prefs_layout.addWidget(self.warmup_checkbox)
        prefs_layout.addWidget(self.note_notation_label)
        prefs_layout.addWidget(self.note_notation_segment)
        prefs_layout.addStretch(1)

        self.theme_page = QWidget()
        theme_layout = QVBoxLayout(self.theme_page)
        theme_layout.setSpacing(12)

        self.theme_editor = ThemeEditorWindow(
            self.theme_page,
            theme=dict(self._theme),
            themes=dict(self._themes),
            themes_dir=str(self._themes_dir),
        )
        try:
            self.theme_editor.setWindowFlags(Qt.WindowType.Widget)
        except Exception:
            pass
        try:
            self.theme_editor.close_btn.hide()
        except Exception:
            pass
        try:
            self.theme_editor.setWindowTitle("")
        except Exception:
            pass
        self.theme_editor.theme_applied.connect(self._on_theme_applied)
        theme_layout.addWidget(self.theme_editor)

        self.tabs.addTab(self.preferences_page, "")
        self.tabs.addTab(self.theme_page, "")

        self.retranslate_ui()
        self.load_preferences()
        self.set_theme(dict(self._theme))

    def retranslate_ui(self):
        self.setWindowTitle(tr("ui.menu.options.preferences", "Preferences…"))
        self.show_loading_checkbox.setText(tr("ui.menu.options.show_loading_dialog", "Show Loading Dialog"))
        self.performance_mode_checkbox.setText(tr("ui.menu.options.performance_mode", "Performance Mode"))
        self.warmup_checkbox.setText(tr("ui.menu.options.warmup_enabled", "Warm Up Audio Engine on Startup"))
        self.note_notation_label.setText(tr("preferences.note_notation.label", "Note Notation:"))
        self.note_notation_flats_btn.setText(tr("preferences.note_notation.flats", "Flats (Db)"))
        self.note_notation_sharps_btn.setText(tr("preferences.note_notation.sharps", "Sharps (C#)"))
        self.tabs.setTabText(0, tr("preferences.tabs.preferences", "Preferences"))
        self.tabs.setTabText(1, tr("preferences.tabs.theme", "Theme"))

    def load_preferences(self):
        show_loading = bool(self._qsettings.value("options/show_loading_dialog", True, type=bool))
        performance_mode = bool(self._qsettings.value("options/performance_mode", False, type=bool))
        warmup_enabled = bool(self._qsettings.value("options/warmup_enabled", True, type=bool))
        note_notation = str(self._qsettings.value("options/note_notation", "sharps", type=str) or "sharps").strip().lower()
        if note_notation not in ("sharps", "flats"):
            note_notation = "sharps"

        for checkbox, value in (
            (self.show_loading_checkbox, show_loading),
            (self.performance_mode_checkbox, performance_mode),
            (self.warmup_checkbox, warmup_enabled),
        ):
            try:
                checkbox.blockSignals(True)
                checkbox.setChecked(bool(value))
            finally:
                try:
                    checkbox.blockSignals(False)
                except Exception:
                    pass

        for btn in (self.note_notation_flats_btn, self.note_notation_sharps_btn):
            try:
                btn.blockSignals(True)
            except Exception:
                pass
        try:
            self.note_notation_flats_btn.setChecked(note_notation == "flats")
            self.note_notation_sharps_btn.setChecked(note_notation != "flats")
        finally:
            for btn in (self.note_notation_flats_btn, self.note_notation_sharps_btn):
                try:
                    btn.blockSignals(False)
                except Exception:
                    pass

    def _on_preference_toggled(self, key: str, checked: bool):
        try:
            self._qsettings.setValue(str(key), bool(checked))
        except Exception:
            pass
        self.preferences_changed.emit()

    def current_preferences(self) -> dict:
        notation = self._current_note_notation()
        if notation not in ("sharps", "flats"):
            notation = "sharps"
        return {
            "show_loading_dialog": bool(self.show_loading_checkbox.isChecked()),
            "performance_mode": bool(self.performance_mode_checkbox.isChecked()),
            "warmup_enabled": bool(self.warmup_checkbox.isChecked()),
            "note_notation": notation,
        }

    def _current_note_notation(self) -> str:
        try:
            if bool(self.note_notation_flats_btn.isChecked()):
                return "flats"
        except Exception:
            pass
        return "sharps"

    def _on_note_notation_toggled(self, notation: str, checked: bool):
        if not bool(checked):
            return
        notation = str(notation or "sharps").strip().lower()
        if notation not in ("sharps", "flats"):
            notation = "sharps"
        try:
            self._qsettings.setValue("options/note_notation", str(notation))
        except Exception:
            pass
        self.preferences_changed.emit()

    def set_theme_context(self, theme: dict | None = None, themes: dict | None = None, themes_dir: str | None = None):
        if isinstance(theme, dict):
            self._theme = dict(theme)
            self.set_theme(self._theme)
        if isinstance(themes, dict):
            self._themes = dict(themes)
            try:
                self.theme_editor.set_available_themes(self._themes)
            except Exception:
                pass
        if themes_dir is not None:
            self._themes_dir = str(themes_dir)
            try:
                self.theme_editor._themes_dir = str(self._themes_dir)
            except Exception:
                pass

    def set_theme(self, theme: dict):
        self._theme = dict(theme) if isinstance(theme, dict) else {}
        try:
            self.theme_editor.set_theme(dict(self._theme))
        except Exception:
            pass
        self._apply_stylesheet()

    def _apply_stylesheet(self):
        t = self._theme if isinstance(self._theme, dict) else {}
        bg = str(t.get("bg", "#2E2E2E"))
        panel = str(t.get("panel", "#404040"))
        primary = str(t.get("primary", "#1D5AAA"))
        accent = str(t.get("accent", "#33CED6"))
        highlight = str(t.get("highlight", "#6B999F"))
        text = str(t.get("text", "#ffffff"))

        def _safe_color(value: str, fallback: str) -> str:
            c = QColor(str(value))
            if c.isValid():
                return str(c.name())
            return str(fallback)

        bg = _safe_color(bg, "#2E2E2E")
        panel = _safe_color(panel, "#404040")
        primary = _safe_color(primary, "#1D5AAA")
        accent = _safe_color(accent, "#33CED6")
        highlight = _safe_color(highlight, "#6B999F")
        text = _safe_color(text, "#ffffff")

        self.setStyleSheet(
            f"""
            QDialog {{ background-color: {bg}; color: {text}; }}
            QTabWidget::pane {{ border: 1px solid {highlight}; background: {panel}; border-radius: 6px; }}
            QTabBar::tab {{ background: {panel}; color: {text}; padding: 8px 12px; border: 1px solid {highlight}; border-bottom: none; border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 4px; }}
            QTabBar::tab:selected {{ background: {primary}; }}
            QLabel {{ color: {text}; }}
            QCheckBox {{ color: {text}; spacing: 6px; }}
            QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {highlight}; background: {panel}; border-radius: 3px; }}
            QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent}; }}
            #noteNotationSegment {{ border: 1px solid {highlight}; border-radius: 6px; background: {panel}; }}
            #noteNotationSegment QPushButton {{
                background: transparent;
                color: {text};
                border: none;
                border-radius: 0px;
                padding: 8px 10px;
            }}
            #noteNotationSegment QPushButton:checked {{
                background: {accent};
                color: #111111;
            }}
            #noteNotationFlats {{ border-right: 1px solid {highlight}; }}
            QPushButton {{ background-color: {primary}; color: {text}; border: 1px solid {highlight}; border-radius: 6px; padding: 8px 12px; }}
            QPushButton:hover {{ background-color: {accent}; color: #111111; }}
            """
        )

    def open_theme_editor(self):
        try:
            self.tabs.setCurrentIndex(1)
        except Exception:
            pass

    def _on_theme_applied(self, theme: dict):
        if not isinstance(theme, dict):
            return
        self._theme = dict(theme)
        self.theme_applied.emit(dict(theme))
