import { useCallback, useEffect, useRef, useState } from 'react';
import { API_BASE, setApiBase } from '../config/api';

const api = () => window.electronAPI;

/** One GET /health with a short timeout. */
async function probe() {
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 2000);
    const res = await fetch(`${API_BASE}/health`, { signal: ctrl.signal });
    clearTimeout(t);
    return res.ok;
  } catch {
    return false;
  }
}

/**
 * Poll /health until it answers or `deadline` (ms) passes. Starts at 20 ms
 * and backs off to 250 ms, so a backend that comes up mid-wait is noticed
 * within a frame or two instead of on the next half-second tick.
 */
async function waitHealthy(deadline, alive) {
  const end = performance.now() + deadline;
  let delay = 20;
  while (alive() && performance.now() < end) {
    if (await probe()) return true;
    await new Promise((r) => setTimeout(r, delay));
    delay = Math.min(250, delay * 1.5);
  }
  return false;
}

/**
 * Audio-engine (backend) status: 'checking' | 'ok' | 'error'.
 * The UI renders immediately; this resolves the backend URL from the main
 * process (the backend starts in parallel with the window), then polls
 * /health. `recheck()` restarts a dead backend; `reconnect()` polls until it
 * is back after a network failure mid-session and resolves true.
 * Optionally fires POST /api/warmup once the backend is up.
 */
export function useBackend({ warmup }) {
  const [status, setStatus] = useState('checking');
  const reconnecting = useRef(null);
  const warmedRef = useRef(false);
  const mounted = useRef(true);

  const connect = useCallback(async (getUrl, deadline = 60000) => {
    setStatus('checking');
    const url = await getUrl();
    if (url) setApiBase(url);
    // In Electron a null URL means the backend never reported a port.
    const ok = (url || !api()) && await waitHealthy(deadline, () => mounted.current);
    if (mounted.current) setStatus(ok ? 'ok' : 'error');
    return Boolean(ok);
  }, []);

  const recheck = useCallback(
    () => connect(async () => (api()?.restartBackend ? api().restartBackend() : API_BASE)),
    [connect],
  );

  const reconnect = useCallback(() => {
    if (!reconnecting.current) {
      reconnecting.current = (async () => {
        // The backend may still be alive (a transient error) or gone; give it
        // a few seconds before restarting it.
        if (await waitHealthy(4000, () => mounted.current)) { setStatus('ok'); return true; }
        return recheck();
      })().finally(() => { reconnecting.current = null; });
    }
    return reconnecting.current;
  }, [recheck]);

  useEffect(() => {
    mounted.current = true;
    connect(async () => (api()?.backendUrl ? api().backendUrl() : API_BASE));
    return () => { mounted.current = false; };
  }, [connect]);

  useEffect(() => {
    if (status !== 'ok' || !warmup || warmedRef.current) return;
    warmedRef.current = true;
    fetch(`${API_BASE}/api/warmup`, { method: 'POST' }).catch(() => {});
  }, [status, warmup]);

  return { status, recheck, reconnect };
}
