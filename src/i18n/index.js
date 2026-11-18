import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import en from './locales/en.json';

// English ships in the main bundle (it is also the fallback); every other
// language is its own chunk, loaded only when selected.
const loaders = import.meta.glob(['./locales/*.json', '!./locales/en.json'], { import: 'default' });

i18n.use(initReactI18next).init({
  resources: { en: { translation: en } },
  lng: 'en',
  fallbackLng: 'en',
  interpolation: { escapeValue: false },
});

/** Load (once) and switch to `lng`. Unknown languages fall back to English. */
export async function setLanguage(lng) {
  const load = loaders[`./locales/${lng}.json`];
  if (load && !i18n.hasResourceBundle(lng, 'translation')) {
    try {
      i18n.addResourceBundle(lng, 'translation', await load());
    } catch {
      return; // chunk missing: stay on the current language
    }
  }
  if (i18n.language !== lng) await i18n.changeLanguage(lng);
}

export default i18n;
