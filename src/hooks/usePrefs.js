import { useCallback, useEffect, useState } from 'react';
import i18n from '../i18n';
import { DEFAULT_PREFS, LANGUAGES } from '../config/settings';

const KEY = 'freqenforcer.prefs';

function readPrefs() {
  try {
    const raw = localStorage.getItem(KEY);
    const saved = raw ? JSON.parse(raw) : {};
    const prefs = { ...DEFAULT_PREFS, ...saved };
    if (!LANGUAGES.includes(prefs.language)) prefs.language = DEFAULT_PREFS.language;
    return prefs;
  } catch {
    return { ...DEFAULT_PREFS };
  }
}

/**
 * UI preferences (theme, language, notation, performance mode, warm-up),
 * persisted in localStorage. Applies the theme attribute and i18n language
 * as side effects.
 */
export function usePrefs() {
  const [prefs, setPrefs] = useState(readPrefs);

  useEffect(() => {
    document.documentElement.dataset.theme = prefs.theme;
    if (i18n.language !== prefs.language) i18n.changeLanguage(prefs.language);
    try { localStorage.setItem(KEY, JSON.stringify(prefs)); } catch { /* storage unavailable */ }
  }, [prefs]);

  const update = useCallback((patch) => setPrefs((p) => ({ ...p, ...patch })), []);
  return [prefs, update];
}
