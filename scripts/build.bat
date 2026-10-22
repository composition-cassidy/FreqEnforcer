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
:: Same script as `npm run build:backend` (includes bloat cleanup)
python scripts\build_backend.py
if errorlevel 1 (
    echo ERROR: PyInstaller build failed
    exit /b 1
)
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
