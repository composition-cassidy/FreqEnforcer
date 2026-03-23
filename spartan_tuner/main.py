from __future__ import annotations
import argparse
from pathlib import Path
import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QStandardPaths
from PyQt6.QtGui import QFont, QFontDatabase, QIcon

from ui.main_window import MainWindow
from utils.harmonic_cli import parse_harmonic_ceiling_arg


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--breathiness", type=float, default=1.0)
    parser.add_argument("--hf-bias", type=float, default=0.0)
    parser.add_argument("--harmonic-ceiling", type=str, default="")
    parser.add_argument("--harmonic-amount", type=int, default=50)
    args, qt_args = parser.parse_known_args(sys.argv[1:])

    raw_args = list(sys.argv[1:])
    startup_overrides: dict[str, object] = {}
    if any(str(a).startswith("--breathiness") for a in raw_args):
        startup_overrides["breathiness"] = float(args.breathiness)
    if any(str(a).startswith("--hf-bias") for a in raw_args):
        startup_overrides["hf_bias"] = float(args.hf_bias)
    if any(str(a).startswith("--harmonic-amount") for a in raw_args):
        startup_overrides["harmonic_amount"] = int(args.harmonic_amount)
    if any(str(a).startswith("--harmonic-ceiling") for a in raw_args):
        startup_overrides["harmonic_ceiling_offsets_db"] = parse_harmonic_ceiling_arg(args.harmonic_ceiling)
        startup_overrides["harmonic_limiter_enabled"] = True

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
    window = MainWindow(
        debug=bool(args.debug),
        debug_notes_path=debug_notes_path,
        startup_processing_overrides=startup_overrides if startup_overrides else None,
    )
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
