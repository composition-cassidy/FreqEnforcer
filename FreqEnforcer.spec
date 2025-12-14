# -*- mode: python ; coding: utf-8 -*-

block_cipher = None


from PyInstaller.utils.hooks import collect_submodules

try:
    from PyInstaller.utils.hooks import collect_all
except Exception:  # pragma: no cover
    collect_all = None


_binaries = []
_datas = [
    ("spartan_tuner/LOGO.png", "."),
    ("spartan_tuner/ICON.png", "."),
    ("spartan_tuner/ICON.ico", "."),
    ("spartan_tuner/fonts", "fonts"),
    ("spartan_tuner/themes", "themes"),
]

_hiddenimports = []

try:
    _hiddenimports += collect_submodules("audiotsm")
except Exception:
    pass

for _pkg in ["pylibrb"]:
    try:
        __import__(_pkg)
        _hiddenimports.append(_pkg)
    except Exception:
        pass

for _pkg in ["parselmouth"]:
    try:
        __import__(_pkg)
        _hiddenimports.append(_pkg)
    except Exception:
        pass

if collect_all is not None:
    for _pkg in ["audiotsm", "pylibrb", "parselmouth"]:
        try:
            _datas_pkg, _binaries_pkg, _hidden_pkg = collect_all(_pkg)
            _datas += list(_datas_pkg)
            _binaries += list(_binaries_pkg)
            _hiddenimports += list(_hidden_pkg)
        except Exception:
            pass

a = Analysis(
    ["spartan_tuner/main.py"],
    pathex=["spartan_tuner"],
    binaries=_binaries,
    datas=_datas,
    hiddenimports=_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FreqEnforcer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon="spartan_tuner/ICON.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    name="FreqEnforcer",
)
