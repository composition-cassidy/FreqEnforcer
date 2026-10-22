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
  getLastDroppedFilePath: () => _lastDroppedPath,
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

  // ── Theme persistence ────────────────────────────────────────────────
  getThemePreference:  ()        => ipcRenderer.invoke('themes:getPreference'),
  saveThemePreference: (theme)   => ipcRenderer.invoke('themes:savePreference', theme),

  // ── User themes ──────────────────────────────────────────────────────
  getUserThemesDir: ()           => ipcRenderer.invoke('themes:getUserThemesDir'),
  listUserThemes:   ()           => ipcRenderer.invoke('themes:listUserThemes'),
  saveUserTheme:    (theme)      => ipcRenderer.invoke('themes:saveUserTheme', theme),
  deleteUserTheme:  (themeName)  => ipcRenderer.invoke('themes:deleteUserTheme', themeName),

  // ── Import / Export ──────────────────────────────────────────────────
  importTheme:  ()       => ipcRenderer.invoke('themes:importTheme'),
  exportTheme:  (theme)  => ipcRenderer.invoke('themes:exportTheme', theme),

  // ── Theme system v2 (CSS-variable-based) ─────────────────────────────
  themesSave:       (data)             => ipcRenderer.invoke('themes:save', data),
  themesLoad:       ()                 => ipcRenderer.invoke('themes:load'),
  themesList:       ()                 => ipcRenderer.invoke('themes:list'),
  themesSaveFile:   (filename, data)   => ipcRenderer.invoke('themes:saveFile', filename, data),
  themesLoadFile:   (filename)         => ipcRenderer.invoke('themes:loadFile', filename),
  themesOpenFolder: ()                 => ipcRenderer.invoke('themes:openFolder'),
  themesDialog:     ()                 => ipcRenderer.invoke('themes:dialog'),
});
