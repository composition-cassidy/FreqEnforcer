const { contextBridge, ipcRenderer, webUtils } = require('electron');

// Electron 29+ removed File.path.  The replacement is webUtils.getPathForFile()
// which works in the preload context where the File object keeps its native ref.
let _lastDroppedPath = null;
document.addEventListener('drop', (e) => {
  const file = e.dataTransfer?.files?.[0];
  if (file) {
    try {
      _lastDroppedPath = webUtils.getPathForFile(file);
    } catch (_) {
      _lastDroppedPath = null;
    }
  } else {
    _lastDroppedPath = null;
  }
}, true);  // capture phase — fires before renderer handlers

// Backend port chosen by the OS at spawn time; main.js passes it via
// webPreferences.additionalArguments.
const _portArg = process.argv.find((a) => a.startsWith('--fe-backend-port='));
const _backendPort = _portArg ? Number(_portArg.split('=')[1]) : NaN;

contextBridge.exposeInMainWorld('electronAPI', {
  backendUrl: Number.isInteger(_backendPort) && _backendPort > 0
    ? `http://127.0.0.1:${_backendPort}`
    : null,
  getLastDroppedFilePath: () => _lastDroppedPath,
  // Sample passed on the command line (--fe-open=<path>), if any.
  initialFile: (process.argv.find((a) => a.startsWith('--fe-initial-file=')) ?? '').slice('--fe-initial-file='.length) || null,
  // ── Window controls ──────────────────────────────────────────────────
  minimizeWindow: () => ipcRenderer.invoke('window:minimize'),
  maximizeWindow: () => ipcRenderer.invoke('window:maximize'),
  closeWindow:    () => ipcRenderer.invoke('window:close'),
  isMaximized:    () => ipcRenderer.invoke('window:isMaximized'),
  openFileDialog:  () => ipcRenderer.invoke('dialog:openFile'),
  saveFileDialog: (options) => ipcRenderer.invoke('dialog:saveFile', options),
  openDirectoryDialog: (options) => ipcRenderer.invoke('dialog:openDirectory', options),

  onMaximizeChange: (callback) => {
    ipcRenderer.on('maximize-change', (_event, isMaximized) => {
      callback(isMaximized);
    });
  },

});
