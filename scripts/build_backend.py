"""Build the PyInstaller backend bundle (build-backend/freqenforcer-backend/).

Single source of truth for the backend build; used by `npm run build:backend`
and scripts/build.bat.  All paths are absolute, so it works from any cwd.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
DIST = ROOT / "build-backend"
WORK = ROOT / "build-temp"
NAME = "freqenforcer-backend"

# Runtime DSP dependencies that must end up in the bundle.  A missing one
# would otherwise be skipped silently by PyInstaller and only fail at runtime
# (e.g. audiotsm backs the default stretch method).
REQUIRED = ["numpy", "scipy", "soundfile", "soxr", "pyworld", "parselmouth",
            "pylibrb", "audiotsm", "stftpitchshift", "fastapi", "uvicorn", "multipart"]

HIDDEN_IMPORTS = ["soundfile", "pyworld", "scipy.signal", "scipy.ndimage",
                  "scipy.interpolate", "multipart", "audiotsm", "stftpitchshift",
                  "parselmouth", "pylibrb", "soxr"]

EXCLUDES = ["PyQt6", "PyQt5", "matplotlib", "PIL", "Pillow", "sklearn", "tkinter",
            "librosa", "numba", "llvmlite", "joblib", "pooch", "decorator", "mypy"]

# Leftovers PyInstaller drags in via optional imports.
BLOAT_FILES = ["opengl32sw.dll", "_avif*.pyd", "Qt6*.dll", "Qt6*.pyd", "QtCore.pyd",
               "QtGui.pyd", "QtWidgets.pyd", "llvmlite.dll"]
BLOAT_DIRS = ["PyQt6", "matplotlib", "PIL", "sklearn", "contourpy", "kiwisolver",
              "librosa", "llvmlite", "llvmlite.libs", "numba"]


def _check_requirements() -> None:
    missing = [m for m in REQUIRED if importlib.util.find_spec(m) is None]
    if missing:
        sys.exit(f"ERROR: missing Python packages for the backend build: {', '.join(missing)}\n"
                 f"Install with: {sys.executable} -m pip install -r requirements.txt")


def _clean_bloat(internal: Path) -> None:
    for pattern in BLOAT_FILES:
        for f in internal.glob(pattern):
            f.unlink()
    for d in BLOAT_DIRS:
        shutil.rmtree(internal / d, ignore_errors=True)


def _dir_size(path: Path) -> tuple[int, int]:
    files = [p for p in path.rglob("*") if p.is_file()]
    return sum(p.stat().st_size for p in files), len(files)


def main() -> int:
    _check_requirements()
    import PyInstaller.__main__

    args = [
        "--noconfirm", "--clean",
        "--name", NAME,
        "--distpath", str(DIST),
        "--workpath", str(WORK),
        "--specpath", str(WORK),
        "--add-data", f"{SERVER / 'audio'};audio",
        "--add-data", f"{SERVER / 'utils'};utils",
    ]
    for m in HIDDEN_IMPORTS:
        args += ["--hidden-import", m]
    for m in EXCLUDES:
        args += ["--exclude-module", m]
    args.append(str(SERVER / "main.py"))

    PyInstaller.__main__.run(args)

    bundle = DIST / NAME
    _clean_bloat(bundle / "_internal")
    leaked = [p.name for p in (bundle / "_internal").iterdir() if p.name.lower().startswith("librosa")]
    if leaked:
        sys.exit(f"ERROR: librosa leaked into the bundle: {leaked}")
    size, count = _dir_size(bundle)
    print(f"\nBackend bundle: {bundle}  {size / 1e6:.1f} MB in {count} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
