import { useTranslation } from 'react-i18next';
import Group from './Group';
import Select from '../controls/Select';
import Slider from '../controls/Slider';
import Check from '../controls/Check';
import { DEFAULT_SETTINGS as D, PITCH_MODE_GROUPS, modeCaps } from '../../config/settings';

const pct = (v) => `${Math.round(v)} %`;
const cents = (v) => `${v > 0 ? '+' : ''}${Math.round(v)} ¢`;

/** Pitch mode select plus the controls that mode uses. */
export default function ModeGroup({ settings, onChange, drag }) {
  const { t } = useTranslation();
  const caps = modeCaps(settings.pitch_mode);
  const groups = PITCH_MODE_GROUPS.map((g) => ({
    label: t(`settings.pitch_mode.group_${g.key}`),
    options: g.modes.map((m) => ({ value: m, label: t(`settings.pitch_mode.${m}.label`) })),
  }));

  return (
    <Group title={t('mode.title')} right="1–7">
      <Select ariaLabel={t('mode.title')} value={settings.pitch_mode} defaultValue={D.pitch_mode} groups={groups} onChange={(v) => onChange({ pitch_mode: v })} />
      <div className="help">{t(`settings.pitch_mode.${settings.pitch_mode}.info`)}</div>

      {caps.soft && (
        <>
          <Slider label={t('mode.amount')} value={settings.pitch_amount * 100} min={0} max={100} step={1} defaultValue={D.pitch_amount * 100}
            format={pct} onChange={(v) => onChange({ pitch_amount: v / 100 })} {...drag} />
          <Slider label={t('mode.retune_speed')} value={settings.retune_speed_ms} min={0} max={500} step={1} defaultValue={D.retune_speed_ms}
            format={(v) => `${Math.round(v)} ms`} onChange={(v) => onChange({ retune_speed_ms: v })} {...drag} />
          <Slider label={t('mode.keep_vibrato')} value={settings.preserve_vibrato * 100} min={0} max={100} step={1} defaultValue={D.preserve_vibrato * 100}
            format={pct} onChange={(v) => onChange({ preserve_vibrato: v / 100 })} {...drag} />
        </>
      )}
      {caps.formant && (
        <Slider label={t('mode.formant_shift')} value={settings.formant_shift_cents} min={-500} max={500} step={1} defaultValue={D.formant_shift_cents}
          snap={0} snapZone={15} format={cents} onChange={(v) => onChange({ formant_shift_cents: v })} {...drag} />
      )}
      {caps.vt && (
        <Slider label={t('mode.vocal_tract')} value={settings.formant_shift_beta * 100} min={0} max={100} step={1} defaultValue={D.formant_shift_beta * 100}
          format={(v) => String(Math.round(v))} onChange={(v) => onChange({ formant_shift_beta: v / 100 })} {...drag} />
      )}
      <Check label={t('mode.normalize')} checked={settings.normalize} defaultValue={D.normalize} onChange={(v) => onChange({ normalize: v })} />
    </Group>
  );
}
