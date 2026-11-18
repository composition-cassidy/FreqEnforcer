import React from 'react';
import ReactDOM from 'react-dom/client';
import { setLanguage } from './i18n';
import { applyPrefs, readPrefs } from './hooks/usePrefs';
import App from './App';

// Theme, motion and UI scale go on before the first paint; a non-English
// language is fetched first (one small local chunk) so the UI never flashes
// English.
const prefs = readPrefs();
applyPrefs(prefs);
const ready = prefs.language === 'en' ? Promise.resolve() : setLanguage(prefs.language);

ready.finally(() => {
  ReactDOM.createRoot(document.getElementById('root')).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  );
});
