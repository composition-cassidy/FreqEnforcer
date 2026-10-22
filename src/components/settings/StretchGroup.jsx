import { useTranslation } from 'react-i18next';
import Group from './Group';
import Select from '../controls/Select';
import Slider from '../controls/Slider';
import Dwell from '../controls/Dwell';
import { DEFAULT_SETTINGS as D, STRETCH_METHODS } from '../../config/settings';

/** Stretch method + factor (0.01-4.00, snaps to 1.00, value is editable). */
export default function StretchGroup({ settings, onChange, drag }) {
  const { t } = useTranslation();
  return (
    <Group title={t('stretch.title')}>
      <Dwell hint={t(`settings.stretch_method.${settings.stretch_method}.info`)}>
        <Select
          ariaLabel={t('stretch.method')} value={settings.stretch_method} defaultValue={D.stretch_method}
          options={STRETCH_METHODS.map((m) => ({ value: m, label: t(`settings.stretch_method.${m}.label`) }))}
          onChange={(v) => onChange({ stretch_method: v })}
        />
      </Dwell>
      <Slider
        label={t('stretch.factor')} value={settings.stretch_factor} min={0.01} max={4} step={0.01} defaultValue={D.stretch_factor}
        snap={1} snapZone={0.03} format={(v) => `${v.toFixed(2)} ×`} parse={(s) => parseFloat(String(s).replace(/[×x]/g, ''))}
        hint={settings.stretch_factor > 2 ? t('stretch.warn_over_2') : null}
        onChange={(v) => onChange({ stretch_factor: Math.round(v * 100) / 100 })} {...drag}
      />
    </Group>
  );
}
