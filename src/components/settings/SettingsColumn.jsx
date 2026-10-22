import { useTranslation } from 'react-i18next';
import TargetGroup from './TargetGroup';
import ModeGroup from './ModeGroup';
import VoicingGroup from './VoicingGroup';
import StretchGroup from './StretchGroup';
import AdvancedGroup from './AdvancedGroup';
import MultisampleSheet from '../sheets/MultisampleSheet';
import PreferencesSheet from '../sheets/PreferencesSheet';

/**
 * The right column. `sheet` picks what fills it: 'settings' (default),
 * 'multisample' or 'preferences'. Sheets replace the column rather than
 * opening a modal, and return with their back button.
 */
export default function SettingsColumn({ sheet, onSheet, settings, onChange, drag, audio, prefs, onPrefs, loop, onFindLoop, busy, onTrimPreview }) {
  const { t } = useTranslation();
  return (
    <aside className="side">
      {sheet === 'settings' && (
        <section className="side-main" aria-label={t('settings.title')}>
          <TargetGroup settings={settings} detected={audio.detectedPitch} notation={prefs.notation} onChange={onChange} />
          <ModeGroup settings={settings} onChange={onChange} drag={drag} />
          <VoicingGroup settings={settings} onChange={onChange} />
          <StretchGroup settings={settings} onChange={onChange} drag={drag} />
          <AdvancedGroup settings={settings} onChange={onChange} drag={drag} loop={loop} onFindLoop={onFindLoop} busy={busy} />
        </section>
      )}
      {sheet === 'multisample' && (
        <MultisampleSheet settings={settings} audio={audio} notation={prefs.notation} onBack={() => onSheet('settings')} onTrimPreview={onTrimPreview} />
      )}
      {sheet === 'preferences' && (
        <PreferencesSheet prefs={prefs} onPrefs={onPrefs} onBack={() => onSheet('settings')} />
      )}
    </aside>
  );
}
