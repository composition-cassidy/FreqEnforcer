import { useTranslation } from 'react-i18next';
import Group from './Group';
import Segmented from '../controls/Segmented';
import Dwell from '../controls/Dwell';
import { VOICING_MODES, modeCaps } from '../../config/settings';

/**
 * Strict / Force / Dilate for the WORLD modes. `voicing_mode: null` means
 * "backend default for this mode"; the segmented control shows that default
 * selected and only writes an explicit value when the user picks one.
 */
export default function VoicingGroup({ settings, onChange }) {
  const { t } = useTranslation();
  const def = modeCaps(settings.pitch_mode).voicing;
  const effective = settings.voicing_mode ?? def;
  return (
    <Group title={t('voicing.title')} right={def ? t('voicing.default', { mode: t(`voicing.${def}`) }) : t('voicing.world_only')} disabled={!def}>
      <Dwell hint={t('voicing.help')}>
        <Segmented
          full ariaLabel={t('voicing.title')} value={effective} defaultValue={def} disabled={!def}
          options={VOICING_MODES.map((v) => ({ value: v, label: t(`voicing.${v}`) }))}
          onChange={(v) => onChange({ voicing_mode: v === def ? null : v })}
        />
      </Dwell>
    </Group>
  );
}
