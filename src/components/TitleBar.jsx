import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import Menu from './Menu';
import { LANGUAGES } from '../config/settings';

const api = () => window.electronAPI;

/**
 * Frameless title bar: brand, File / Export / Options menus, processing
 * status and window controls.
 */
export default function TitleBar({ audioLoaded, processing, busy, prefs, onPrefs, onAction }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(null); // { id, x, y }
  const [maximized, setMaximized] = useState(false);

  useEffect(() => {
    api()?.isMaximized?.().then((m) => setMaximized(Boolean(m)));
    api()?.onMaximizeChange?.((m) => setMaximized(Boolean(m)));
  }, []);

  function toggle(id, e) {
    if (open?.id === id) { setOpen(null); return; }
    const r = e.currentTarget.getBoundingClientRect();
    setOpen({ id, x: r.left, y: r.bottom });
  }

  const act = (id) => () => onAction(id);
  const menus = {
    file: [
      { id: 'open',   label: t('menu.open'),         shortcut: 'Ctrl+O', onSelect: act('open') },
      { id: 'reload', label: t('menu.reload'),       shortcut: 'Ctrl+R', onSelect: act('reload'), disabled: !audioLoaded },
      { id: 'close',  label: t('menu.close_sample'), shortcut: 'Ctrl+N', onSelect: act('close'),  disabled: !audioLoaded },
      { sep: true },
      { id: 'quit',   label: t('menu.quit'),         shortcut: 'Ctrl+Q', onSelect: () => api()?.closeWindow() },
    ],
    export: [
      { id: 'export',      label: t('menu.export_wav'),   shortcut: 'Ctrl+E',       onSelect: act('export'),      disabled: !audioLoaded || busy },
      { id: 'quick',       label: t('menu.quick_export'), shortcut: 'Ctrl+Shift+E', onSelect: act('quickExport'), disabled: !audioLoaded || busy },
      { id: 'multisample', label: t('menu.multisample'),  shortcut: 'Ctrl+M',       onSelect: act('multisample'), disabled: !audioLoaded },
    ],
    options: [
      { id: 'prefs', label: t('menu.preferences'), shortcut: 'Ctrl+,', onSelect: act('preferences') },
      { sep: true },
      { id: 'dark',  label: t('prefs.dark'),  checked: prefs.theme === 'dark',  onSelect: () => onPrefs({ theme: 'dark' }) },
      { id: 'light', label: t('prefs.light'), checked: prefs.theme === 'light', onSelect: () => onPrefs({ theme: 'light' }) },
      { sep: true },
      ...LANGUAGES.map((l) => ({ id: `lang-${l}`, label: t(`language.${l}`), checked: prefs.language === l, onSelect: () => onPrefs({ language: l }) })),
    ],
  };

  return (
    <div className="title">
      <div className="title__brand">{t('app.title')} <span className="ver mono">{__APP_VERSION__}</span></div>
      <nav className="title__menus" aria-label={t('menu.main')}>
        {['file', 'export', 'options'].map((id) => (
          <button key={id} type="button" aria-haspopup="menu" aria-expanded={open?.id === id} onClick={(e) => toggle(id, e)}>
            {t(`menu.${id}`)}
          </button>
        ))}
      </nav>
      <div className="title__spacer" />
      <div className="title__status" aria-live="polite">
        {processing.active && (
          <span>
            {t('status.processing')} <span className="mono">{processing.pct}%</span>
            {processing.stage ? <span className="faint"> · {processing.stage}</span> : null}
          </span>
        )}
      </div>
      <div className="title__wc">
        <button type="button" aria-label={t('window.minimize')} onClick={() => api()?.minimizeWindow()}>–</button>
        <button type="button" aria-label={maximized ? t('window.restore') : t('window.maximize')} onClick={() => api()?.maximizeWindow()}>{maximized ? '❐' : '□'}</button>
        <button type="button" className="close" aria-label={t('window.close')} onClick={() => api()?.closeWindow()}>×</button>
      </div>
      {open && <Menu anchor={open} items={menus[open.id]} onClose={() => setOpen(null)} />}
    </div>
  );
}
