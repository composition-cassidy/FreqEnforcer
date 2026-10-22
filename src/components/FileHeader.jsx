import { useTranslation } from 'react-i18next';
import { formatCents, formatHz, parseNoteName, pcName, noteNameToPC } from '../utils/note_utils';

function basename(p) { return p ? p.replace(/\\/g, '/').split('/').pop() : ''; }

/** File name + meta on the left, detected pitch (note, cents, Hz, confidence) on the right. */
export default function FileHeader({ audio, notation, onOpen }) {
  const { t } = useTranslation();
  const d = audio.detectedPitch;
  const parsed = d?.note_name ? parseNoteName(d.note_name) : null;
  const noteName = parsed ? pcName(noteNameToPC(parsed.note), notation) : '—';

  return (
    <div className="header">
      <div className="file">
        <button type="button" className="btn" onClick={onOpen} title="Ctrl+O">{t('header.open')}</button>
        {audio.filePath
          ? <span className="file__name" title={audio.filePath}>{basename(audio.filePath)}</span>
          : <span className="file__name file__name--none">{audio.loading ? t('status.loading') : t('header.no_sample')}</span>}
        {audio.loaded && (
          <span className="file__meta mono">
            <span>{(audio.sampleRate / 1000).toFixed(1)} kHz</span>
            <span>{t('header.mono')}</span>
            <span>{audio.durationSeconds.toFixed(3)} s</span>
            <span>{formatHz(audio.peakDb, 1)} dBFS</span>
          </span>
        )}
      </div>
      <div className="detected" aria-label={t('header.detected')}>
        <div>
          <span className="k">{t('header.detected')}</span>
          <span className="note">{noteName}{parsed && <sub>{parsed.octave}</sub>}</span>
        </div>
        <div><span className="k">{t('header.cents')}</span><span className="v">{d?.cents != null ? `${formatCents(d.cents)} ¢` : '—'}</span></div>
        <div><span className="k">{t('header.frequency')}</span><span className="v">{d?.freq_hz != null ? `${formatHz(d.freq_hz, 1)} Hz` : '—'}</span></div>
        <div><span className="k">{t('header.confidence')}</span><span className="v">{d?.confidence != null ? d.confidence.toFixed(2) : '—'}</span></div>
      </div>
    </div>
  );
}
