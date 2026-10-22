import { useCallback, useEffect, useRef, useState } from 'react';
import { API_BASE } from '../config/api';

/**
 * Backend health: 'checking' | 'ok' | 'error'.
 * `recheck()` re-runs the probe; `reconnect()` polls until the backend is back
 * and resolves true (used after a network failure mid-session).
 * Optionally fires POST /api/warmup once the backend is up.
 */
export function useBackend({ warmup }) {
  const [status, setStatus] = useState('checking');
  const pollRef = useRef(null);
  const warmedRef = useRef(false);

  const probe = useCallback(async () => {
    try {
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), 5000);
      const res = await fetch(`${API_BASE}/health`, { signal: ctrl.signal });
      clearTimeout(t);
      return res.ok;
    } catch {
      return false;
    }
  }, []);

  const recheck = useCallback(async () => {
    setStatus('checking');
    const ok = await probe();
    setStatus(ok ? 'ok' : 'error');
    return ok;
  }, [probe]);

  const reconnect = useCallback(() => new Promise((resolve) => {
    if (pollRef.current) return;
    pollRef.current = setInterval(async () => {
      if (await probe()) {
        clearInterval(pollRef.current);
        pollRef.current = null;
        setStatus('ok');
        resolve(true);
      }
    }, 3000);
  }), [probe]);

  useEffect(() => { recheck(); return () => clearInterval(pollRef.current); }, [recheck]);

  useEffect(() => {
    if (status !== 'ok' || !warmup || warmedRef.current) return;
    warmedRef.current = true;
    fetch(`${API_BASE}/api/warmup`, { method: 'POST' }).catch(() => {});
  }, [status, warmup]);

  return { status, recheck, reconnect };
}
