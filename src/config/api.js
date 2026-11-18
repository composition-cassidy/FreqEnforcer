// Backend base URL. Inside Electron the backend runs on an OS-assigned port
// that is only known once it has started (in parallel with this window), so
// this is a live binding: useBackend() sets it before reporting 'ok', and
// every caller reads it at request time. Plain-browser dev keeps the
// standalone server's default port.
export let API_BASE = 'http://localhost:8765';

export function setApiBase(url) {
  if (url) API_BASE = url;
}
