import os
import sys

from PyQt6.QtGui import QGuiApplication, QImage


def main() -> int:
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    png_path = os.path.join(base_dir, "spartan_tuner", "ICON.png")
    ico_path = os.path.join(base_dir, "spartan_tuner", "ICON.ico")

    app = QGuiApplication(sys.argv)

    img = QImage(png_path)
    if img.isNull():
        raise RuntimeError(f"Failed to load PNG: {png_path}")

    ok = img.save(ico_path, "ICO")
    if not ok:
        raise RuntimeError(
            "Failed to save ICO. Your Qt build may not support writing ICO. "
            "If this happens, use Pillow/ImageMagick to convert ICON.png to ICON.ico."
        )

    print(f"Wrote: {ico_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
