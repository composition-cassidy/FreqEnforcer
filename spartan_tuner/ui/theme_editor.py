from __future__ import annotations

import json
import re
from pathlib import Path

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QColorDialog,
    QMessageBox,
    QFrame,
    QWidget,
    QScrollArea,
    QFileDialog,
    QComboBox,
)


class ThemeEditorWindow(QDialog):
    theme_applied = pyqtSignal(dict)

    def __init__(self, parent=None, theme: dict | None = None, themes: dict | None = None, themes_dir: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("Theme Editor")
        self.setModal(False)
        self.resize(520, 420)

        self._rows: dict[str, dict] = {}
        self._themes: dict[str, dict] = dict(themes) if isinstance(themes, dict) else {}
        self._themes_dir = str(themes_dir) if themes_dir else ""

        root = QVBoxLayout(self)

        info = QLabel("Edit theme colors as hex (#RRGGBB).")
        info.setWordWrap(True)
        root.addWidget(info)

        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Preset:"))
        self.preset_combo = QComboBox()
        preset_row.addWidget(self.preset_combo, 1)
        self.load_preset_btn = QPushButton("Load")
        self.load_preset_btn.clicked.connect(self._on_load_preset)
        preset_row.addWidget(self.load_preset_btn)
        root.addLayout(preset_row)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Name:"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Theme name")
        name_row.addWidget(self.name_edit, 1)
        root.addLayout(name_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        root.addWidget(scroll, 1)

        container = QWidget()
        scroll.setWidget(container)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)

        for key, label in (
            ("bg", "Background"),
            ("panel", "Panel"),
            ("primary", "Primary"),
            ("accent", "Accent"),
            ("highlight", "Highlight"),
            ("success", "Success"),
            ("text", "Text"),
        ):
            container_layout.addLayout(self._make_color_row(key, label))

        container_layout.addStretch(1)

        btn_row = QHBoxLayout()

        self.import_btn = QPushButton("Import")
        self.import_btn.clicked.connect(self._on_import)
        btn_row.addWidget(self.import_btn)

        self.export_btn = QPushButton("Export")
        self.export_btn.clicked.connect(self._on_export)
        btn_row.addWidget(self.export_btn)

        self.save_btn = QPushButton("Save")
        self.save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(self.save_btn)

        btn_row.addStretch(1)

        self.apply_btn = QPushButton("Apply")
        self.apply_btn.clicked.connect(self._on_apply)
        btn_row.addWidget(self.apply_btn)

        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.close)
        btn_row.addWidget(self.close_btn)

        root.addLayout(btn_row)

        self.set_available_themes(self._themes)

        if theme is not None:
            self.set_theme(theme)

    def set_available_themes(self, themes: dict):
        self._themes = dict(themes) if isinstance(themes, dict) else {}
        try:
            current = str(self.preset_combo.currentText() or "")
        except Exception:
            current = ""

        try:
            self.preset_combo.blockSignals(True)
            self.preset_combo.clear()
            for name in sorted(self._themes.keys(), key=lambda s: str(s).lower()):
                self.preset_combo.addItem(str(name))

            if current and current in self._themes:
                self.preset_combo.setCurrentText(current)
        except Exception:
            pass
        finally:
            try:
                self.preset_combo.blockSignals(False)
            except Exception:
                pass

    def _on_load_preset(self):
        name = ""
        try:
            name = str(self.preset_combo.currentText() or "")
        except Exception:
            name = ""

        if not name:
            return

        t = self._themes.get(name)
        if not isinstance(t, dict):
            return

        self.set_theme(t)
        try:
            self.name_edit.setText(str(name))
        except Exception:
            pass

    def _make_color_row(self, key: str, label: str):
        row = QHBoxLayout()

        name = QLabel(str(label))
        name.setMinimumWidth(120)
        row.addWidget(name)

        edit = QLineEdit()
        edit.setPlaceholderText("#RRGGBB")
        edit.textChanged.connect(lambda _t, k=key: self._on_hex_changed(k))
        row.addWidget(edit, 1)

        preview = QFrame()
        preview.setFrameShape(QFrame.Shape.StyledPanel)
        preview.setFixedSize(44, 22)
        preview.setAutoFillBackground(True)
        row.addWidget(preview)

        pick_btn = QPushButton("Pick")
        pick_btn.setFixedWidth(70)
        pick_btn.clicked.connect(lambda _c=False, k=key: self._pick_color(k))
        row.addWidget(pick_btn)

        self._rows[key] = {"edit": edit, "preview": preview}
        return row

    def _normalize_hex(self, s: str) -> str:
        txt = str(s or "").strip()
        if not txt:
            return txt
        if not txt.startswith("#"):
            txt = "#" + txt
        return txt

    def _qcolor_from_hex(self, s: str) -> QColor | None:
        txt = self._normalize_hex(s)
        if not txt:
            return None
        c = QColor(txt)
        if not c.isValid():
            return None
        return c

    def _set_preview(self, key: str, hex_value: str):
        row = self._rows.get(key)
        if not row:
            return

        preview: QFrame = row["preview"]
        c = self._qcolor_from_hex(hex_value)
        if c is None:
            preview.setStyleSheet("background-color: transparent;")
        else:
            preview.setStyleSheet(f"background-color: {c.name()};")

    def _on_hex_changed(self, key: str):
        row = self._rows.get(key)
        if not row:
            return
        edit: QLineEdit = row["edit"]
        self._set_preview(key, edit.text())

    def _pick_color(self, key: str):
        row = self._rows.get(key)
        if not row:
            return

        edit: QLineEdit = row["edit"]
        current = self._qcolor_from_hex(edit.text())
        initial = current if current is not None else QColor("#ffffff")

        c = QColorDialog.getColor(initial, self, f"Pick {key} color")
        if not c.isValid():
            return

        edit.setText(str(c.name()))

    def set_theme(self, theme: dict):
        t = dict(theme) if isinstance(theme, dict) else {}
        for key, row in self._rows.items():
            val = t.get(key, "")
            try:
                row["edit"].setText(str(val))
            except Exception:
                pass

    def _sanitize_filename(self, name: str) -> str:
        txt = str(name or "").strip()
        if not txt:
            return "theme"
        txt = re.sub(r"[^a-zA-Z0-9 _\-]", "", txt)
        txt = txt.strip().replace(" ", "_")
        return txt or "theme"

    def _theme_payload(self, name: str, colors: dict) -> dict:
        return {"name": str(name or "Custom"), "colors": dict(colors)}

    def _parse_theme_obj(self, obj: dict) -> tuple[str, dict] | None:
        if not isinstance(obj, dict):
            return None

        name = str(obj.get("name") or "")
        colors = obj.get("colors")

        if isinstance(colors, dict):
            theme_dict = {str(k): str(v) for k, v in colors.items() if v is not None}
        else:
            theme_dict = {str(k): str(v) for k, v in obj.items() if v is not None and k != "name"}

        if not theme_dict:
            return None

        if not name:
            name = "Imported"
        return name, theme_dict

    def _on_import(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import Theme", "", "Theme JSON (*.json)")
        if not path:
            return

        try:
            obj = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            QMessageBox.warning(self, "Import Failed", "Could not read theme file.")
            return

        parsed = self._parse_theme_obj(obj)
        if parsed is None:
            QMessageBox.warning(self, "Import Failed", "Theme file is invalid.")
            return

        name, theme = parsed
        self.set_theme(theme)
        try:
            self.name_edit.setText(str(name))
        except Exception:
            pass

        try:
            self._themes[str(name)] = dict(theme)
            self.set_available_themes(self._themes)
            self.preset_combo.setCurrentText(str(name))
        except Exception:
            pass

    def _on_export(self):
        colors = self.get_theme()
        if colors is None:
            QMessageBox.warning(self, "Invalid Theme", "One or more colors are invalid. Use #RRGGBB.")
            return

        try:
            name = str(self.name_edit.text() or "Custom")
        except Exception:
            name = "Custom"

        default_name = self._sanitize_filename(name) + ".json"
        path, _ = QFileDialog.getSaveFileName(self, "Export Theme", default_name, "Theme JSON (*.json)")
        if not path:
            return

        if not str(path).lower().endswith(".json"):
            path = str(path) + ".json"

        try:
            Path(path).write_text(json.dumps(self._theme_payload(name, colors), indent=2), encoding="utf-8")
        except Exception:
            QMessageBox.warning(self, "Export Failed", "Could not write theme file.")

    def _on_save(self):
        if not self._themes_dir:
            QMessageBox.warning(self, "Save Failed", "Themes folder is unavailable.")
            return

        colors = self.get_theme()
        if colors is None:
            QMessageBox.warning(self, "Invalid Theme", "One or more colors are invalid. Use #RRGGBB.")
            return

        try:
            name = str(self.name_edit.text() or "Custom").strip()
        except Exception:
            name = "Custom"

        if not name:
            name = "Custom"

        folder = Path(self._themes_dir)
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        file_path = folder / (self._sanitize_filename(name) + ".json")
        try:
            file_path.write_text(json.dumps(self._theme_payload(name, colors), indent=2), encoding="utf-8")
        except Exception:
            QMessageBox.warning(self, "Save Failed", "Could not write theme into themes folder.")
            return

        try:
            self._themes[str(name)] = dict(colors)
            self.set_available_themes(self._themes)
            self.preset_combo.setCurrentText(str(name))
        except Exception:
            pass

    def get_theme(self) -> dict | None:
        out: dict[str, str] = {}
        for key, row in self._rows.items():
            edit: QLineEdit = row["edit"]
            val = self._normalize_hex(edit.text())
            c = self._qcolor_from_hex(val)
            if c is None:
                return None
            out[str(key)] = str(c.name())
        return out

    def _on_apply(self):
        theme = self.get_theme()
        if theme is None:
            QMessageBox.warning(self, "Invalid Theme", "One or more colors are invalid. Use #RRGGBB.")
            return
        self.theme_applied.emit(theme)
