// Backend base URL.  Inside Electron the backend runs on an OS-assigned port
// that the preload script exposes; plain-browser dev falls back to the
// standalone server's default port.
export const API_BASE = window.electronAPI?.backendUrl ?? 'http://localhost:8765';
