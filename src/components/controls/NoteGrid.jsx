import { useTranslation } from 'react-i18next';
import { NOTE_NAMES_SHARP, isBlackKey, pcName, noteNameToPC } from '../../utils/note_utils';

export const OCTAVE_MIN = 0;
export const OCTAVE_MAX = 8;

/**
 * 12 pitch-class buttons (radio group, arrow keys move) + octave stepper.
 * Double-click on the grid resets to `defaultNote` (the detected note).
 */
export default function NoteGrid({ note, octave, notation, defaultNote, onChange }) {
  const { t } = useTranslation();
  const pc = noteNameToPC(note) ?? 0;

  function onKey(e) {
    const d = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
    if (!d) return;
    e.preventDefault();
    const next = (pc + d + 12) % 12;
    onChange({ targetNote: NOTE_NAMES_SHARP[next] });
  }
  function reset() { if (defaultNote) onChange({ targetNote: defaultNote.note, octave: defaultNote.octave }); }

  return (
    <>
      <div className="notes-grid" role="radiogroup" aria-label={t('target.title')} onKeyDown={onKey} onDoubleClick={reset}>
        {NOTE_NAMES_SHARP.map((n, i) => (
          <button
            key={n} type="button" role="radio" aria-checked={i === pc} tabIndex={i === pc ? 0 : -1}
            className={isBlackKey(i) ? 'black' : undefined}
            onClick={() => onChange({ targetNote: n })}
          >
            {pcName(i, notation)}
          </button>
        ))}
      </div>
      <div className="row">
        <span className="row__label">{t('target.octave')}</span>
        <span className="stepper">
          <button type="button" aria-label={t('target.octave_down')} disabled={octave <= OCTAVE_MIN} onClick={() => onChange({ octave: octave - 1 })}>−</button>
          <output aria-live="polite">{octave}</output>
          <button type="button" aria-label={t('target.octave_up')} disabled={octave >= OCTAVE_MAX} onClick={() => onChange({ octave: octave + 1 })}>+</button>
        </span>
      </div>
    </>
  );
}
