@echo off
title FreqEnforcer Dev
cd /d "%~dp0"

echo Cleaning up leftover processes on port 5174...
for /f "tokens=5" %%a in ('netstat -aon ^| find ":5174 " ^| find "LISTENING" 2^>nul') do taskkill /F /PID %%a >nul 2>&1

echo [1/2] Starting Vite dev server (port 5174)...
start "" /b npx vite > "%TEMP%\fe-vite.log" 2>&1

:: Electron starts its own backend (python server/main.py --port 0) and
:: waits for Vite, so no separate backend is launched here.
echo [2/2] Launching Electron...
npx electron electron/main.js

echo.
echo Dev session ended.
pause
