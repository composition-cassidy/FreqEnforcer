import { useTranslation } from 'react-i18next';
import Group from './Group';
import NoteGrid from '../controls/NoteGrid';
import Dwell from '../controls/Dwell';
import { formatHz, noteNameToPC, noteToFreq, parseNoteName, pcName, toMidi } from '../../utils/note_utils';

/** Target note picker with Hz readout and distance from the detected pitch. */
export default function TargetGroup({ settings, detected, notation, onChange }) {
  const { t } = useTranslation();
  const hz = noteToFreq(settings.targetNote, settings.octave);
  const det = detected?.note_name ? parseNoteName(detected.note_name) : null;
  let delta = null;
  if (det && detected.freq_hz) {
    const targetMidi = toMidi(settings.octave, noteNameToPC(settings.targetNote));
    const detMidi = toMidi(det.octave, noteNameToPC(det.note));
    const st = targetMidi - detMidi;
    const cents = (12 * Math.log2(hz / detected.freq_hz) - st) * 100; // residual after the semitone step
    delta = `Δ ${st > 0 ? '+' : ''}${st} st · ${cents > 0 ? '+' : ''}${cents.toFixed(1)} ¢`;
  }

  return (
    <Group title={t('target.title')}>
      <Dwell hint={t('target.hint')}>
        <NoteGrid note={settings.targetNote} octave={settings.octave} notation={notation} defaultNote={det} onChange={onChange} />
      </Dwell>
      <div className="target-readout">
        <span className="target-readout__big">
          {pcName(noteNameToPC(settings.targetNote), notation)}<sub>{settings.octave}</sub>
          <span className="target-readout__hz">{formatHz(hz)} Hz</span>
        </span>
        {delta && <span className="target-readout__delta">{delta}</span>}
      </div>
    </Group>
  );
}
