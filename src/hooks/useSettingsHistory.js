import { useCallback, useRef, useState } from 'react';

const COALESCE_MS = 500;
const MAX_HISTORY = 200;

/**
 * Settings state with undo/redo.
 *
 * `set(patch | updater, opts)` records one history entry. Rapid changes to the
 * same keys (a slider drag) within COALESCE_MS collapse into one entry, so
 * Ctrl+Z steps back one gesture, not one pixel. `opts.silent` replaces the
 * present without recording (used for load-time defaults).
 */
export function useSettingsHistory(initial) {
  const [present, setPresent] = useState(initial);
  const pastRef   = useRef([]);
  const futureRef = useRef([]);
  const lastRef   = useRef({ keys: '', at: 0 });
  const [, bump]  = useState(0); // re-render for canUndo/canRedo
  const presentRef = useRef(present);
  presentRef.current = present;

  const set = useCallback((patchOrFn, opts = {}) => {
    const prev = presentRef.current;
    const patch = typeof patchOrFn === 'function' ? patchOrFn(prev) : patchOrFn;
    const next = { ...prev, ...patch };
    const keys = Object.keys(patch).filter((k) => prev[k] !== patch[k]).sort().join(',');
    if (!keys) return;

    if (!opts.silent) {
      const now = performance.now();
      const same = keys === lastRef.current.keys && now - lastRef.current.at < COALESCE_MS;
      if (!same) {
        pastRef.current.push(prev);
        if (pastRef.current.length > MAX_HISTORY) pastRef.current.shift();
      }
      lastRef.current = { keys, at: now };
      futureRef.current = [];
    }
    presentRef.current = next;
    setPresent(next);
  }, []);

  const undo = useCallback(() => {
    if (!pastRef.current.length) return;
    futureRef.current.push(presentRef.current);
    const prev = pastRef.current.pop();
    lastRef.current = { keys: '', at: 0 };
    presentRef.current = prev;
    setPresent(prev);
    bump((n) => n + 1);
  }, []);

  const redo = useCallback(() => {
    if (!futureRef.current.length) return;
    pastRef.current.push(presentRef.current);
    const next = futureRef.current.pop();
    lastRef.current = { keys: '', at: 0 };
    presentRef.current = next;
    setPresent(next);
    bump((n) => n + 1);
  }, []);

  /** Replace everything and clear history (new sample). */
  const reset = useCallback((value) => {
    pastRef.current = [];
    futureRef.current = [];
    lastRef.current = { keys: '', at: 0 };
    presentRef.current = value;
    setPresent(value);
    bump((n) => n + 1);
  }, []);

  return {
    settings: present, set, undo, redo, reset,
    canUndo: pastRef.current.length > 0,
    canRedo: futureRef.current.length > 0,
  };
}
