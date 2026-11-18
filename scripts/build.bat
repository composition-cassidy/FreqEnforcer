@echo off
:: Change to project root (one level up from scripts\)
cd /d "%~dp0.."

for /f "delims=" %%v in ('node -p "require('./package.json').version"') do set VER=%%v
echo === FreqEnforcer v%VER% Build ===
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

echo [4/4] Packing portable archive (7z, LZMA2 max)...
:: 7z is ~35 %% smaller than zip here; Windows 11 Explorer and 7-Zip open it.
:: Contents go in one FreqEnforcer-<version> folder.
set SEVENZIP=node_modules\7zip-bin\win\x64\7za.exe
if exist "dist-electron\FreqEnforcer-%VER%-portable.7z" del "dist-electron\FreqEnforcer-%VER%-portable.7z"
"%SEVENZIP%" a -t7z -mx=9 -mmt=on "dist-electron\FreqEnforcer-%VER%-portable.7z" ".\dist-electron\win-unpacked" >nul
if errorlevel 1 (
    echo ERROR: 7z packing failed
    exit /b 1
)
"%SEVENZIP%" rn "dist-electron\FreqEnforcer-%VER%-portable.7z" win-unpacked FreqEnforcer-%VER% >nul
echo.

echo === BUILD COMPLETE ===
echo.
echo Installer:  dist-electron\FreqEnforcer-%VER%-Setup.exe
echo Portable:   dist-electron\FreqEnforcer-%VER%-portable.7z
echo Unpacked:   dist-electron\win-unpacked\FreqEnforcer.exe
