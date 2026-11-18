const { app, BrowserWindow, ipcMain, dialog, screen } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const http = require('http');
const fs   = require('fs');

const isDev = process.env.NODE_ENV === 'development' || !app.isPackaged;

let mainWindow = null;

// ── CLI flags ─────────────────────────────────────────────────────────────
//   --fe-open=<path>            load this sample once the backend is up
//   --fe-screenshot=<png>[,ms]  dev helper: capture the window after <ms>
//                               (default 4000) to <png>, then quit
const argValue = (name) => {
  const a = process.argv.find((x) => x.startsWith(`--${name}=`));
  return a ? a.slice(name.length + 3) : null;
};
const initialFile = argValue('fe-open');
const screenshotArg = argValue('fe-screenshot');
let backendProcess = null;

// ── Single instance ───────────────────────────────────────────────────────
// A second launch focuses the existing window instead of starting another
// backend.
const gotSingleInstanceLock = app.requestSingleInstanceLock();
if (!gotSingleInstanceLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.show();
      mainWindow.focus();
    }
  });
}

// ── Backend process management ───────────────────────────────────────────
// The backend is spawned at process start (see the end of this section), in
// parallel with Electron's own startup and the renderer's first paint.
// The backend binds an OS-assigned port (--port 0) and announces it on stdout
// as "FREQENFORCER_PORT=<n>", so several backends never collide on 8765.
const BACKEND_ARGS = ['--port', '0'];
const PORT_LINE_RE = /^FREQENFORCER_PORT=(\d+)\s*$/m;

function getBackendConfig() {
  if (isDev) {
    return { exe: 'python', args: ['server/main.py', ...BACKEND_ARGS], cwd: path.join(__dirname, '..') };
  }

  // Production: find the PyInstaller bundle
  const primary = path.join(process.resourcesPath, 'backend', 'freqenforcer-backend.exe');
  if (fs.existsSync(primary)) {
    return { exe: primary, args: BACKEND_ARGS, cwd: path.dirname(primary) };
  }

  // Fallback locations
  const alternatives = [
    path.join(process.resourcesPath, 'freqenforcer-backend', 'freqenforcer-backend.exe'),
    path.join(path.dirname(app.getPath('exe')), 'backend', 'freqenforcer-backend.exe'),
    path.join(path.dirname(app.getPath('exe')), 'resources', 'backend', 'freqenforcer-backend.exe'),
  ];
  for (const alt of alternatives) {
    if (fs.existsSync(alt)) {
      console.log(`Backend found at fallback: ${alt}`);
      return { exe: alt, args: BACKEND_ARGS, cwd: path.dirname(alt) };
    }
  }

  console.error(`Backend not found. Searched:\n  ${primary}\n  ${alternatives.join('\n  ')}`);
  return null;
}

// Spawns the backend and resolves with the port it announces on stdout.
// The renderer probes /health itself, so nothing here waits for the DSP
// imports; the window opens while the backend is still starting.
function startBackend(timeout = 60000) {
  return new Promise((resolve, reject) => {
    const config = getBackendConfig();
    if (!config) {
      reject(new Error('Backend executable not found'));
      return;
    }

    const proc = spawn(config.exe, config.args, {
      cwd: config.cwd,
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    });
    backendProcess = proc;

    let stdoutBuf = '';
    let settled = false;
    const settle = (fn, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      fn(value);
    };
    const timer = setTimeout(
      () => settle(reject, new Error('Timed out waiting for backend port')), timeout);

    proc.stdout.on('data', (data) => {
      if (isDev) console.log(`[backend] ${data}`);
      if (!settled) {
        stdoutBuf += data.toString();
        const m = stdoutBuf.match(PORT_LINE_RE);
        if (m) { stdoutBuf = ''; settle(resolve, Number(m[1])); }
      }
    });

    proc.stderr.on('data', (data) => {
      console.error(`[backend] ${data}`);
    });

    proc.on('error', (err) => {
      console.error('Failed to start backend:', err);
      settle(reject, err);
    });

    proc.on('exit', (code) => {
      console.log(`[backend] exited with code ${code}`);
      if (backendProcess === proc) backendProcess = null;
      settle(reject, new Error(`Backend exited with code ${code} before reporting its port`));
    });
  });
}

// Current backend: a promise of its port. Started as early as possible (see
// below), restarted on demand from the renderer's Retry / reconnect.
let backendPort = null;
function launchBackend() {
  backendPort = startBackend();
  backendPort.catch((err) => console.error('Backend failed to start:', err.message));
  return backendPort;
}
const backendUrl = () => backendPort.then((port) => `http://127.0.0.1:${port}`, () => null);

function stopBackend() {
  if (backendProcess) {
    if (process.platform === 'win32' && backendProcess.pid) {
      // Kill the whole tree: the backend may have multisample worker processes.
      spawn('taskkill', ['/pid', String(backendProcess.pid), '/T', '/F'], { windowsHide: true });
    } else {
      backendProcess.kill();
    }
    backendProcess = null;
  }
}

if (gotSingleInstanceLock) launchBackend();

// ── Generic HTTP polling ───────────────────────────────────────────────────
function pollFor(url, timeout = 60000, interval = 50) {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + timeout;

    function attempt() {
      if (Date.now() > deadline) {
        reject(new Error(`Timed out waiting for ${url}`));
        return;
      }

      const req = http.get(url, () => { resolve(); });

      req.on('error', () => { setTimeout(attempt, interval); });

      req.setTimeout(1000, () => {
        req.destroy();
        setTimeout(attempt, interval);
      });
    }

    attempt();
  });
}

// ── Window creation ────────────────────────────────────────────────────────
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 1100,
    minHeight: 700,
    frame: false,
    titleBarStyle: 'hidden',
    titleBarOverlay: false,
    title: 'FreqEnforcer',
    show: false,
    backgroundColor: '#131313',
    icon: path.join(__dirname, '..', 'src', 'assets', 'icon.ico'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false, // File.path requires sandbox off; contextIsolation still protects the renderer
      additionalArguments: initialFile ? [`--fe-initial-file=${initialFile}`] : [],
    },
  });
  // Chromium restores its own per-origin zoom on navigation, which can land
  // after the renderer's early ui:scale request; re-assert after every load.
  mainWindow.webContents.on('did-finish-load', () => {
    if (Math.abs(mainWindow.webContents.getZoomFactor() - uiZoom) > 1e-3) mainWindow.webContents.setZoomFactor(uiZoom);
  });

  if (isDev) {
    mainWindow.loadURL('http://localhost:5174');
  } else {
    mainWindow.loadFile(path.join(__dirname, '..', 'dist', 'index.html'));
  }

  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
    if (screenshotArg) {
      const [file, delay] = screenshotArg.split(',');
      setTimeout(async () => {
        const img = await mainWindow.webContents.capturePage();
        fs.writeFileSync(file, img.toPNG());
        console.log(`[screenshot] ${file} ${img.getSize().width}x${img.getSize().height}`);
        app.quit();
      }, Number(delay) || 4000);
    }
  });

  mainWindow.on('maximize',   () => { mainWindow.webContents.send('maximize-change', true);  });
  mainWindow.on('unmaximize', () => { mainWindow.webContents.send('maximize-change', false); });

  // F12 opens DevTools in the packaged app for debugging
  mainWindow.webContents.on('before-input-event', (event, input) => {
    if (input.key === 'F12') mainWindow.webContents.toggleDevTools();
  });
}

// ── UI scale ──────────────────────────────────────────────────────────────
// The layout is designed for at least 1100 x 700 CSS px. A UI scale is
// clamped so that minimum still fits the display's work area, and the
// window's minimum size grows with the scale.
// The renderer asks for its saved scale synchronously before React's first
// paint (preload: ipcRenderer.sendSync('ui:scale')).
const MIN_W = 1100, MIN_H = 700;
let uiZoom = 1;
function applyUiScale(want) {
  if (!mainWindow) return 1;
  want = Number(want) || 1;
  const bounds = mainWindow.getBounds();
  const wa = screen.getDisplayMatching(bounds).workAreaSize;
  const f = Math.max(1, Math.min(want, wa.width / MIN_W, wa.height / MIN_H));
  uiZoom = f;
  const minW = Math.round(MIN_W * f), minH = Math.round(MIN_H * f);
  mainWindow.setMinimumSize(minW, minH);
  if (bounds.width < minW || bounds.height < minH) {
    mainWindow.setSize(Math.max(bounds.width, minW), Math.max(bounds.height, minH));
  }
  // Zoom from here, never with webFrame.setZoomFactor in the preload: that,
  // called while the page loads, leaves the window producing no animation
  // frames (no playhead) on Electron 41. Skip no-op calls.
  const wc = mainWindow.webContents;
  if (Math.abs(wc.getZoomFactor() - f) > 1e-3) wc.setZoomFactor(f);
  return f;
}

// ── App ready ─────────────────────────────────────────────────────────────
app.whenReady().then(async () => {
  if (!gotSingleInstanceLock) return;

  // ── Window IPC ────────────────────────────────────────────────────────
  ipcMain.handle('window:minimize',   () => { mainWindow.minimize(); });
  ipcMain.handle('window:maximize',   () => {
    if (mainWindow.isMaximized()) mainWindow.unmaximize();
    else                          mainWindow.maximize();
  });
  ipcMain.handle('window:close',      () => { mainWindow.close(); });
  ipcMain.handle('window:isMaximized',() => mainWindow.isMaximized());

  // ── Audio file dialog ─────────────────────────────────────────────────
  ipcMain.handle('dialog:openFile', async () => {
    const result = await dialog.showOpenDialog(mainWindow, {
      properties: ['openFile'],
      filters: [{ name: 'Audio Files', extensions: ['wav', 'mp3', 'flac', 'ogg', 'aiff'] }],
    });
    return result.canceled || result.filePaths.length === 0 ? null : result.filePaths[0];
  });

  ipcMain.handle('dialog:saveFile', async (_, options) => {
    const result = await dialog.showSaveDialog(mainWindow, options);
    return result.canceled ? null : result.filePath;
  });

  ipcMain.handle('dialog:openDirectory', async (_, options) => {
    const result = await dialog.showOpenDialog(mainWindow, {
      properties: ['openDirectory', 'createDirectory'],
      ...options,
    });
    return result.canceled || result.filePaths.length === 0 ? null : result.filePaths[0];
  });

  // Synchronous on purpose: the preload applies the zoom before React's
  // first paint, so the window never shows a frame at the wrong scale.
  ipcMain.on('ui:scale', (e, want) => { e.returnValue = applyUiScale(want); });

  // ── Backend handshake ─────────────────────────────────────────────
  // Resolves with the base URL once the backend has announced its port, or
  // null if it could not start. 'backend:restart' replaces a dead backend.
  ipcMain.handle('backend:url', () => backendUrl());
  ipcMain.handle('backend:restart', () => {
    stopBackend();
    launchBackend();
    return backendUrl();
  });

  if (isDev) {
    try {
      await pollFor('http://localhost:5174');
    } catch (err) {
      console.error(err.message);
      stopBackend();
      app.quit();
      return;
    }
  }

  createWindow();
});

app.on('will-quit', () => {
  stopBackend();
});

app.on('window-all-closed', () => { app.quit(); });

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});
