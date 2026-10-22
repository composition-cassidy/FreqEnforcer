@echo off
:: Change to project root (one level up from scripts\)
cd /d "%~dp0.."

echo === FreqEnforcer v2 Build ===
echo.

echo [1/6] Building React frontend...
call npx vite build
if errorlevel 1 (
    echo ERROR: Vite build failed
    exit /b 1
)
echo.

echo [2/6] Building Python backend with PyInstaller...
set ROOT=%CD%
python -m PyInstaller --noconfirm --clean ^
    --name freqenforcer-backend ^
    --distpath "%ROOT%\build-backend" ^
    --workpath "%ROOT%\build-temp" ^
    --specpath "%ROOT%\build-temp" ^
    --add-data "%ROOT%\server\audio;audio" ^
    --add-data "%ROOT%\server\utils;utils" ^
    --hidden-import soundfile ^
    --hidden-import pyworld ^
    --hidden-import scipy.signal ^
    --hidden-import scipy.ndimage ^
    --hidden-import scipy.interpolate ^
    --hidden-import multipart ^
    --exclude-module PyQt6 ^
    --exclude-module PyQt5 ^
    --exclude-module matplotlib ^
    --exclude-module PIL ^
    --exclude-module Pillow ^
    --exclude-module sklearn ^
    --exclude-module tkinter ^
    --exclude-module librosa ^
    --exclude-module numba ^
    --exclude-module llvmlite ^
    --exclude-module joblib ^
    --exclude-module pooch ^
    --exclude-module decorator ^
    "%ROOT%\server\main.py"
if errorlevel 1 (
    echo ERROR: PyInstaller build failed
    exit /b 1
)

echo [2b/6] Cleaning bloat from backend build...
set BACKEND=%ROOT%\build-backend\freqenforcer-backend\_internal
if exist "%BACKEND%\opengl32sw.dll" del /Q "%BACKEND%\opengl32sw.dll"
del /Q "%BACKEND%\_avif*.pyd" 2>nul
del /Q "%BACKEND%\Qt6*.dll" 2>nul
del /Q "%BACKEND%\Qt6*.pyd" 2>nul
del /Q "%BACKEND%\QtCore.pyd" 2>nul
del /Q "%BACKEND%\QtGui.pyd" 2>nul
del /Q "%BACKEND%\QtWidgets.pyd" 2>nul
if exist "%BACKEND%\PyQt6" rmdir /S /Q "%BACKEND%\PyQt6"
if exist "%BACKEND%\matplotlib" rmdir /S /Q "%BACKEND%\matplotlib"
if exist "%BACKEND%\PIL" rmdir /S /Q "%BACKEND%\PIL"
if exist "%BACKEND%\sklearn" rmdir /S /Q "%BACKEND%\sklearn"
if exist "%BACKEND%\contourpy" rmdir /S /Q "%BACKEND%\contourpy"
if exist "%BACKEND%\kiwisolver" rmdir /S /Q "%BACKEND%\kiwisolver"
if exist "%BACKEND%\librosa" rmdir /S /Q "%BACKEND%\librosa"
if exist "%BACKEND%\llvmlite" rmdir /S /Q "%BACKEND%\llvmlite"
if exist "%BACKEND%\llvmlite.libs" rmdir /S /Q "%BACKEND%\llvmlite.libs"
if exist "%BACKEND%\numba" rmdir /S /Q "%BACKEND%\numba"
del /Q "%BACKEND%\llvmlite.dll" 2>nul
echo.

echo [3/4] Building Electron app (unpacked + NSIS installer)...
call npx electron-builder --win dir nsis
if errorlevel 1 (
    echo ERROR: electron-builder failed
    exit /b 1
)
echo.

echo [4/4] Zipping portable package...
powershell -NoProfile -Command "Compress-Archive -Path 'dist-electron\win-unpacked\*' -DestinationPath 'dist-electron\FreqEnforcer-2.0.1-portable.zip' -Force"
echo.

echo === BUILD COMPLETE ===
echo.
echo Installer:  dist-electron\FreqEnforcer-2.0.1-Setup.exe
echo Portable:   dist-electron\FreqEnforcer-2.0.1-portable.zip
echo Unpacked:   dist-electron\win-unpacked\FreqEnforcer.exe
