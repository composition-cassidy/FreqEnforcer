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

contextBridge.exposeInMainWorld('electronAPI', {
  // Backend base URL. The backend starts in parallel with this window, so
  // these resolve once it has announced its OS-assigned port (null = failed).
  backendUrl:     () => ipcRenderer.invoke('backend:url'),
  restartBackend: () => ipcRenderer.invoke('backend:restart'),
  // Global UI scale. The main process clamps it to what fits the screen and
  // zooms the page (not CSS zoom, so devicePixelRatio changes and the
  // canvases stay sharp). Returns the applied factor.
  setZoomFactor: (want) => ipcRenderer.sendSync('ui:scale', want),
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
