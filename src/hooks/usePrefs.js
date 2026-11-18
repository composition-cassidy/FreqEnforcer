import { useCallback, useEffect, useState } from 'react';
import i18n, { setLanguage } from '../i18n';
import { DEFAULT_PREFS, LANGUAGES, THEMES, UI_SCALES } from '../config/settings';

const KEY = 'freqenforcer.prefs';

export function readPrefs() {
  try {
    const raw = localStorage.getItem(KEY);
    const saved = raw ? JSON.parse(raw) : {};
    const prefs = { ...DEFAULT_PREFS, ...saved };
    if (!LANGUAGES.includes(prefs.language)) prefs.language = DEFAULT_PREFS.language;
    if (!THEMES.includes(prefs.theme)) prefs.theme = DEFAULT_PREFS.theme;
    if (!UI_SCALES.includes(prefs.ui_scale)) prefs.ui_scale = DEFAULT_PREFS.ui_scale;
    return prefs;
  } catch {
    return { ...DEFAULT_PREFS };
  }
}

/**
 * Apply the preferences that live outside React: theme and motion attributes
 * on <html>, the frame zoom (UI scale). main.jsx calls this before the first
 * render so the window never paints in the wrong theme or scale.
 */
export function applyPrefs(prefs) {
  const root = document.documentElement;
  root.dataset.theme = prefs.theme;
  root.dataset.motion = prefs.animations ? 'on' : 'off';
  window.electronAPI?.setZoomFactor?.(prefs.ui_scale / 100);
}

/**
 * UI preferences (theme, UI scale, animations, language, notation,
 * performance mode, warm-up), persisted in localStorage.
 */
export function usePrefs() {
  const [prefs, setPrefs] = useState(readPrefs);

  useEffect(() => {
    applyPrefs(prefs);
    if (i18n.language !== prefs.language) setLanguage(prefs.language);
    try { localStorage.setItem(KEY, JSON.stringify(prefs)); } catch { /* storage unavailable */ }
  }, [prefs]);

  const update = useCallback((patch) => setPrefs((p) => ({ ...p, ...patch })), []);
  return [prefs, update];
}
