const { app, BrowserWindow, ipcMain, dialog, shell } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const http = require('http');
const fs   = require('fs');

const isDev = process.env.NODE_ENV === 'development' || !app.isPackaged;

let mainWindow = null;
let splashWindow = null;
let backendProcess = null;
let backendPort = null;

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
function startBackend(timeout = 60000) {
  return new Promise((resolve, reject) => {
    const config = getBackendConfig();
    if (!config) {
      reject(new Error('Backend executable not found'));
      return;
    }

    backendProcess = spawn(config.exe, config.args, {
      cwd: config.cwd,
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    });

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

    backendProcess.stdout.on('data', (data) => {
      console.log(`[backend] ${data}`);
      if (!settled) {
        stdoutBuf += data.toString();
        const m = stdoutBuf.match(PORT_LINE_RE);
        if (m) settle(resolve, Number(m[1]));
      }
    });

    backendProcess.stderr.on('data', (data) => {
      console.error(`[backend] ${data}`);
    });

    backendProcess.on('error', (err) => {
      console.error('Failed to start backend:', err);
      settle(reject, err);
    });

    backendProcess.on('exit', (code) => {
      console.log(`[backend] exited with code ${code}`);
      backendProcess = null;
      settle(reject, new Error(`Backend exited with code ${code} before reporting its port`));
    });
  });
}

function stopBackend() {
  if (backendProcess) {
    backendProcess.kill();
    backendProcess = null;
  }
}

// ── User-data paths ────────────────────────────────────────────────────────
// (resolved after app is ready)
let userThemesDir  = null;
let preferencesPath = null;

function initUserDataPaths() {
  const base    = app.getPath('userData');
  userThemesDir  = path.join(base, 'themes');
  preferencesPath = path.join(base, 'freqenforcer-preferences.json');
  if (!fs.existsSync(userThemesDir)) fs.mkdirSync(userThemesDir, { recursive: true });
}

function readPreferences() {
  try {
    if (fs.existsSync(preferencesPath)) {
      return JSON.parse(fs.readFileSync(preferencesPath, 'utf-8'));
    }
  } catch { /* corrupt or missing */ }
  return {};
}

function writePreferences(prefs) {
  fs.writeFileSync(preferencesPath, JSON.stringify(prefs, null, 2), 'utf-8');
}

// ── Generic HTTP polling ───────────────────────────────────────────────────
function pollFor(url, timeout = 60000, interval = 500) {
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

// ── Splash window ──────────────────────────────────────────────────────────
function createSplashWindow() {
  splashWindow = new BrowserWindow({
    width: 420,
    height: 520,
    frame: false,
    transparent: true,
    resizable: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    center: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  splashWindow.loadFile(path.join(__dirname, 'splash.html'));
  splashWindow.on('closed', () => { splashWindow = null; });
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
    backgroundColor: '#1a1a2e',
    icon: path.join(__dirname, '..', 'src', 'assets', 'icon.ico'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false, // File.path requires sandbox off; contextIsolation still protects the renderer
      additionalArguments: [`--fe-backend-port=${backendPort}`],
    },
  });

  if (isDev) {
    mainWindow.loadURL('http://localhost:5174');
  } else {
    mainWindow.loadFile(path.join(__dirname, '..', 'dist', 'index.html'));
  }

  mainWindow.once('ready-to-show', () => {
    if (splashWindow) splashWindow.close();
    mainWindow.show();
  });

  mainWindow.on('maximize',   () => { mainWindow.webContents.send('maximize-change', true);  });
  mainWindow.on('unmaximize', () => { mainWindow.webContents.send('maximize-change', false); });

  // F12 opens DevTools in the packaged app for debugging
  mainWindow.webContents.on('before-input-event', (event, input) => {
    if (input.key === 'F12') mainWindow.webContents.toggleDevTools();
  });
}

// ── App ready ─────────────────────────────────────────────────────────────
app.whenReady().then(async () => {
  if (!gotSingleInstanceLock) return;
  initUserDataPaths();

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

  // ── Theme: preference persistence ─────────────────────────────────────
  ipcMain.handle('themes:getPreference', () => {
    return readPreferences().theme ?? null;
  });

  ipcMain.handle('themes:savePreference', (_, theme) => {
    const prefs = readPreferences();
    prefs.theme = theme;
    writePreferences(prefs);
  });

  // ── Theme: user themes directory ──────────────────────────────────────
  ipcMain.handle('themes:getUserThemesDir', () => userThemesDir);

  ipcMain.handle('themes:listUserThemes', () => {
    try {
      return fs.readdirSync(userThemesDir)
        .filter((f) => f.endsWith('.json'))
        .map((f) => {
          try { return JSON.parse(fs.readFileSync(path.join(userThemesDir, f), 'utf-8')); }
          catch { return null; }
        })
        .filter(Boolean);
    } catch { return []; }
  });

  ipcMain.handle('themes:saveUserTheme', (_, theme) => {
    const safeName = theme.name.replace(/[^a-zA-Z0-9_\- ]/g, '_');
    const filePath = path.join(userThemesDir, `${safeName}.json`);
    fs.writeFileSync(filePath, JSON.stringify(theme, null, 2), 'utf-8');
    return filePath;
  });

  ipcMain.handle('themes:deleteUserTheme', (_, themeName) => {
    const safeName = themeName.replace(/[^a-zA-Z0-9_\- ]/g, '_');
    const filePath = path.join(userThemesDir, `${safeName}.json`);
    if (fs.existsSync(filePath)) fs.unlinkSync(filePath);
  });

  // ── Theme: import / export via file dialog ────────────────────────────
  ipcMain.handle('themes:importTheme', async () => {
    const result = await dialog.showOpenDialog(mainWindow, {
      properties: ['openFile'],
      filters: [{ name: 'FreqEnforcer Theme', extensions: ['json'] }],
    });
    if (result.canceled || result.filePaths.length === 0) return null;
    try { return JSON.parse(fs.readFileSync(result.filePaths[0], 'utf-8')); }
    catch { return null; }
  });

  ipcMain.handle('themes:exportTheme', async (_, theme) => {
    const result = await dialog.showSaveDialog(mainWindow, {
      defaultPath: `${theme.name.replace(/[^a-zA-Z0-9_\- ]/g, '_')}.json`,
      filters: [{ name: 'FreqEnforcer Theme', extensions: ['json'] }],
    });
    if (result.canceled) return false;
    fs.writeFileSync(result.filePath, JSON.stringify(theme, null, 2), 'utf-8');
    return true;
  });

  // ── New theme system (v2) — CSS-variable-based ─────────────────────────
  // Save/load active theme to preferences
  ipcMain.handle('themes:save', (_, themeData) => {
    const prefs = readPreferences();
    prefs.activeTheme = themeData;
    writePreferences(prefs);
  });

  ipcMain.handle('themes:load', () => {
    const prefs = readPreferences();
    // Support both new format (activeTheme) and legacy format (theme)
    if (prefs.activeTheme) return prefs.activeTheme;
    if (prefs.theme?.colors) {
      // Convert legacy format on the fly
      const c = prefs.theme.colors;
      return {
        variables: {
          '--bg-app': c.bg || '#1e1e1e',
          '--bg-titlebar': c.bg || '#1e1e1e',
          '--bg-panel': c.panel || '#252525',
          '--bg-panel-hover': '#2e2e2e',
          '--bg-panel-light': c.panel || '#383838',
          '--border': '#3a3a3a',
          '--border-emphasis': '#505050',
          '--text-primary': c.text || '#e8e8e8',
          '--text-secondary': '#a0a0a0',
          '--text-dim': '#606060',
          '--text-bright': '#ffffff',
          '--accent': c.accent || '#33CED6',
          '--accent-hover': '#26a8b0',
          '--wf-white-key': '#ffffff',
          '--wf-black-key': '#000000',
          '--wf-grid': '#ffffff',
          '--wf-label': '#a0a0b0',
          '--harmonic-start': c.harmonic_node_grad_start || c.accent || '#33CED6',
          '--harmonic-end': c.harmonic_node_grad_end || c.success || '#4EDE83',
          '--harmonic-grid': '#3a3a5a',
          '--harmonic-modified': '#ffb340',
          '--success': c.success || '#4EDE83',
          '--color-error': '#e94560',
          '--color-warning': '#e6c84a',
          '--primary': c.primary || '#1D5AAA',
        },
      };
    }
    return null;
  });

  // List user theme files
  ipcMain.handle('themes:list', () => {
    try {
      return fs.readdirSync(userThemesDir).filter((f) => f.endsWith('.json'));
    } catch { return []; }
  });

  // Save named theme file
  ipcMain.handle('themes:saveFile', (_, filename, data) => {
    const safe = path.basename(filename).replace(/[^a-zA-Z0-9_\-. ]/g, '_');
    fs.writeFileSync(path.join(userThemesDir, safe), JSON.stringify(data, null, 2), 'utf-8');
  });

  // Load named theme file
  ipcMain.handle('themes:loadFile', (_, filename) => {
    const safe = path.basename(filename);
    return JSON.parse(fs.readFileSync(path.join(userThemesDir, safe), 'utf-8'));
  });

  // Open themes folder in file explorer
  ipcMain.handle('themes:openFolder', () => {
    shell.openPath(userThemesDir);
  });

  // Load theme from file picker dialog
  ipcMain.handle('themes:dialog', async () => {
    const result = await dialog.showOpenDialog(mainWindow, {
      properties: ['openFile'],
      filters: [{ name: 'FreqEnforcer Theme', extensions: ['json'] }],
    });
    if (result.canceled || result.filePaths.length === 0) return null;
    try { return JSON.parse(fs.readFileSync(result.filePaths[0], 'utf-8')); }
    catch { return null; }
  });

  // ── Show splash immediately ──────────────────────────────────────────
  createSplashWindow();

  // Start the Python backend and wait for it to be ready
  try {
    backendPort = await startBackend();
    await pollFor(`http://127.0.0.1:${backendPort}/health`);
  } catch (err) {
    console.error('Backend failed to start:', err.message);
    dialog.showErrorBox('FreqEnforcer', 'Backend failed to start. Please reinstall or contact support.');
    if (splashWindow) splashWindow.close();
    stopBackend();
    app.quit();
    return;
  }

  if (isDev) {
    // Also wait for Vite dev server
    try {
      await pollFor('http://localhost:5174');
    } catch (err) {
      console.error(err.message);
      if (splashWindow) splashWindow.close();
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
