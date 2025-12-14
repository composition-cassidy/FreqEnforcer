from __future__ import annotations
import argparse
from pathlib import Path
import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QStandardPaths
from PyQt6.QtGui import QFont, QFontDatabase, QIcon

from ui.main_window import MainWindow


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--debug", action="store_true")
    args, qt_args = parser.parse_known_args(sys.argv[1:])

    app = QApplication([sys.argv[0]] + qt_args)
    app.setApplicationName("FreqEnforcer")

    base_dir = Path(getattr(sys, "_MEIPASS", str(Path(__file__).resolve().parent)))

    icon_path = base_dir / "ICON.ico"
    if icon_path.exists():
        try:
            app.setWindowIcon(QIcon(str(icon_path)))
        except Exception:
            pass

    fonts_dir = base_dir / "fonts"
    if fonts_dir.exists():
        for font_path in sorted(fonts_dir.glob("*.ttf")):
            QFontDatabase.addApplicationFont(str(font_path))
        app.setFont(QFont("Helvetica", 10))

    appdata_dir = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))
    appdata_dir.mkdir(parents=True, exist_ok=True)
    debug_notes_path = str(appdata_dir / "debug_notes.txt")
    window = MainWindow(debug=bool(args.debug), debug_notes_path=debug_notes_path)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
