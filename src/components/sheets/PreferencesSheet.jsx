import { Fragment } from 'react';
import { useTranslation } from 'react-i18next';
import Group from '../settings/Group';
import Segmented from '../controls/Segmented';
import Select from '../controls/Select';
import { LANGUAGES, THEMES, UI_SCALES } from '../../config/settings';

const SHORTCUTS = [
  ['Space', 'play'], ['A', 'ab'], ['Ctrl+E', 'export'], ['Ctrl+Shift+E', 'quick_export'],
  ['Ctrl+Z', 'undo'], ['Ctrl+Shift+Z', 'redo'], ['1–7', 'mode'], ['Ctrl+↑ / ↓', 'semitone'],
  ['Ctrl+Shift+↑ / ↓', 'octave'], ['Ctrl+O', 'open'], ['Ctrl+M', 'multisample'], ['Ctrl+,', 'preferences'],
  ['Double-click', 'reset'], ['Hover', 'hint'],
];

function Pref({ label, desc, children }) {
  return <div className="pref"><span>{label}</span><span className="pref__ctl">{children}</span><span className="pref__desc">{desc}</span></div>;
}

/** Theme, UI scale, animations, language, notation, performance mode, warm-up, and the shortcut list. */
export default function PreferencesSheet({ prefs, onPrefs, onBack }) {
  const { t } = useTranslation();
  const onOff = (key, def) => (
    <Segmented ariaLabel={t(`prefs.${key}`)} value={prefs[key] ? 'on' : 'off'} defaultValue={def ? 'on' : 'off'}
      onChange={(v) => onPrefs({ [key]: v === 'on' })} options={[{ value: 'off', label: t('prefs.off') }, { value: 'on', label: t('prefs.on') }]} />
  );
  return (
    <section aria-label={t('prefs.title')}>
      <div className="sheet__head">
        <button type="button" className="sheet__back" onClick={onBack} aria-label={t('ms.back')}>‹</button>
        <h3>{t('prefs.title')}</h3>
      </div>
      <Group title={t('prefs.general')}>
        <Pref label={t('prefs.theme')} desc={t('prefs.theme_help')}>
          <Segmented ariaLabel={t('prefs.theme')} value={prefs.theme} defaultValue="dark" onChange={(v) => onPrefs({ theme: v })}
            options={THEMES.map((th) => ({ value: th, label: t(`prefs.${th}`) }))} />
        </Pref>
        <Pref label={t('prefs.ui_scale')} desc={t('prefs.ui_scale_help')}>
          <Select ariaLabel={t('prefs.ui_scale')} value={String(prefs.ui_scale)} defaultValue="100" onChange={(v) => onPrefs({ ui_scale: Number(v) })}
            options={UI_SCALES.map((p) => ({ value: String(p), label: `${p} %` }))} />
        </Pref>
        <Pref label={t('prefs.animations')} desc={t('prefs.animations_help')}>{onOff('animations', true)}</Pref>
        <Pref label={t('prefs.language')} desc={t('prefs.language_help')}>
          <Select ariaLabel={t('prefs.language')} value={prefs.language} defaultValue="en" onChange={(v) => onPrefs({ language: v })}
            options={LANGUAGES.map((l) => ({ value: l, label: t(`language.${l}`) }))} />
        </Pref>
        <Pref label={t('prefs.notation')} desc={t('prefs.notation_help')}>
          <Segmented ariaLabel={t('prefs.notation')} value={prefs.notation} defaultValue="sharps" onChange={(v) => onPrefs({ notation: v })}
            options={[{ value: 'sharps', label: 'C♯' }, { value: 'flats', label: 'D♭' }]} />
        </Pref>
        <Pref label={t('prefs.performance')} desc={t('prefs.performance_help')}>{onOff('performance_mode', false)}</Pref>
        <Pref label={t('prefs.warmup')} desc={t('prefs.warmup_help')}>{onOff('warmup', true)}</Pref>
      </Group>
      <Group title={t('prefs.shortcuts')}>
        <div className="shortcuts">
          {SHORTCUTS.map(([k, id]) => <Fragment key={k}><kbd>{k}</kbd><span>{t(`shortcuts.${id}`)}</span></Fragment>)}
        </div>
      </Group>
    </section>
  );
}
