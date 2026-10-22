import { useTranslation } from 'react-i18next';
import Group from './Group';
import Slider from '../controls/Slider';
import Check from '../controls/Check';
import Dwell from '../controls/Dwell';
import { DEFAULT_SETTINGS as D, countActiveAdvanced, modeCaps } from '../../config/settings';

const pct = (v) => `${Math.round(v)} %`;
const per = (v) => `${Math.round(v)} per`;

/** Cleanliness, breath, harmonic limiter and crossfade loop. Collapsed by default. */
export default function AdvancedGroup({ settings, onChange, drag, loop, onFindLoop, busy }) {
  const { t } = useTranslation();
  const n = countActiveAdvanced(settings);
  const s = settings;
  const breath = modeCaps(s.pitch_mode).breath;
  return (
    <Group title={t('advanced.title')} right={n ? t('advanced.active', { count: n }) : null} collapsible defaultOpen={false}>
      <div className="sub">{t('advanced.cleanliness')}</div>
      <Slider label={t('advanced.amount')} value={s.cleanliness_percent} min={0} max={100} defaultValue={D.cleanliness_percent} format={pct} onChange={(v) => onChange({ cleanliness_percent: v })} {...drag} />
      <Slider label={t('advanced.low_cut')} value={s.clean_lowcut_percent} min={0} max={100} defaultValue={D.clean_lowcut_percent} format={pct} onChange={(v) => onChange({ clean_lowcut_percent: v })} {...drag} />
      <Slider label={t('advanced.hf_rollback')} value={s.clean_hf_rollback_percent} min={0} max={100} defaultValue={D.clean_hf_rollback_percent} format={pct} onChange={(v) => onChange({ clean_hf_rollback_percent: v })} {...drag} />

      <div className="sub">{t('advanced.breath')}</div>
      {!breath && <div className="sub-note">{t('advanced.breath_world_only')}</div>}
      <Slider label={t('advanced.breathiness')} value={s.breathiness} min={0} max={5} step={0.01} defaultValue={D.breathiness} snap={1} snapZone={0.05}
        format={(v) => `${v.toFixed(2)} ×`} onChange={(v) => onChange({ breathiness: v })} disabled={!breath} {...drag} />
      <Slider label={t('advanced.hf_bias')} value={s.hf_bias} min={0} max={1} step={0.01} defaultValue={D.hf_bias} format={(v) => v.toFixed(2)}
        onChange={(v) => onChange({ hf_bias: v })} disabled={!breath || Math.abs(s.breathiness - 1) < 1e-6} {...drag} />

      <div className="sub">{t('advanced.limiter')}</div>
      <Dwell hint={t('advanced.limiter_help')}>
        <Check label={t('advanced.enable')} checked={s.harmonic_limiter_enabled} defaultValue={D.harmonic_limiter_enabled} onChange={(v) => onChange({ harmonic_limiter_enabled: v })} />
      </Dwell>
      <Slider label={t('advanced.compression')} value={s.harmonic_amount} min={0} max={100} defaultValue={D.harmonic_amount} format={pct}
        onChange={(v) => onChange({ harmonic_amount: v })} disabled={!s.harmonic_limiter_enabled} {...drag} />

      <div className="sub">{t('advanced.loop')}</div>
      <Slider label={t('advanced.template')} value={s.loop_template_periods} min={2} max={16} defaultValue={D.loop_template_periods} format={per} onChange={(v) => onChange({ loop_template_periods: v })} />
      <Slider label={t('advanced.min_loop')} value={s.loop_min_periods} min={2} max={32} defaultValue={D.loop_min_periods} format={per} onChange={(v) => onChange({ loop_min_periods: v })} />
      <Slider label={t('advanced.crossfade')} value={s.loop_crossfade_periods} min={1} max={8} defaultValue={D.loop_crossfade_periods} format={per} onChange={(v) => onChange({ loop_crossfade_periods: v })} />
      <div className="row">
        <span className="mono dim">{loop ? `${loop.startSec.toFixed(3)} – ${loop.endSec.toFixed(3)} s` : t('advanced.no_loop')}</span>
        <button type="button" className="btn" onClick={onFindLoop} disabled={busy}>{t('advanced.find_loop')}</button>
      </div>
    </Group>
  );
}
