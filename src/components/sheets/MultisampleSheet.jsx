import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import Group from '../settings/Group';
import Select from '../controls/Select';
import Slider from '../controls/Slider';
import Check from '../controls/Check';
import Dwell from '../controls/Dwell';
import { API_BASE } from '../../config/api';
import { settingsToBackend } from '../../hooks/useProcessing';
import { readErrorDetail } from '../../utils/errors';
import { NOTE_NAMES_SHARP, midiToNote, noteLabel, noteNameToPC, parseNoteName, pcName, toMidi } from '../../utils/note_utils';

const OCTAVES = [0, 1, 2, 3, 4, 5, 6, 7, 8];

/** Note range, per-note options, output folder, SSE progress, Render. */
export default function MultisampleSheet({ settings, audio, notation, onBack, onTrimPreview }) {
  const { t } = useTranslation();
  const src = parseNoteName(audio.detectedPitch?.note_name) ?? { note: 'C', octave: 4 };
  const srcMidi = toMidi(src.octave, noteNameToPC(src.note));
  const [low, setLow]   = useState(() => midiToNote(Math.max(0, srcMidi - 24)));
  const [high, setHigh] = useState(() => midiToNote(Math.min(127, srcMidi + 24)));
  const [enableLoop, setEnableLoop] = useState(true);
  const [trimOn, setTrimOn] = useState(false);
  const [trimMs, setTrimMs] = useState(0);
  const [sfz, setSfz] = useState(true);
  const [outputDir, setOutputDir] = useState('');
  const [run, setRun] = useState({ status: 'idle', pct: 0, note: '', done: 0, total: 0, result: null, error: '' });
  const abortRef = useRef(null);

  const lowMidi = toMidi(low.octave, noteNameToPC(low.note)), highMidi = toMidi(high.octave, noteNameToPC(high.note));
  const total = highMidi - lowMidi + 1;
  const valid = total >= 1 && lowMidi >= 0 && highMidi <= 127;
  const rendering = run.status === 'rendering';

  useEffect(() => { onTrimPreview(trimOn ? trimMs : null); }, [trimOn, trimMs, onTrimPreview]);
  useEffect(() => () => { onTrimPreview(null); abortRef.current?.abort(); }, [onTrimPreview]);

  const noteOpts = NOTE_NAMES_SHARP.map((n, i) => ({ value: n, label: pcName(i, notation) }));
  const octOpts = OCTAVES.map((o) => ({ value: String(o), label: String(o) }));

  async function render() {
    if (!valid || rendering) return;
    const ctrl = new AbortController(); abortRef.current = ctrl;
    setRun({ status: 'rendering', pct: 0, note: '', done: 0, total, result: null, error: '' });
    try {
      const res = await fetch(`${API_BASE}/api/render-multisample`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: ctrl.signal,
        body: JSON.stringify({
          ...settingsToBackend(settings),
          low_note: noteLabel(low.note, low.octave), high_note: noteLabel(high.note, high.octave),
          enable_loop: enableLoop,
          template_periods: settings.loop_template_periods, min_loop_periods: settings.loop_min_periods, crossfade_periods: settings.loop_crossfade_periods,
          start_trim_ms: trimOn ? trimMs : 0, generate_sfz: sfz, output_dir: outputDir || null,
        }),
      });
      if (!res.ok) throw new Error(await readErrorDetail(res));
      const reader = res.body.getReader(), dec = new TextDecoder();
      let buf = '', ended = false;
      while (!ended) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const parts = buf.split('\n\n'); buf = parts.pop();
        for (const p of parts) {
          const line = p.trim();
          if (!line.startsWith('data: ')) continue;
          const d = JSON.parse(line.slice(6));
          if (d.progress != null) setRun((r) => ({ ...r, pct: Math.round(d.progress * 100), note: d.current_note ?? '', done: d.notes_done ?? 0, total: d.notes_total ?? total }));
          if (d.complete)  { ended = true; setRun((r) => ({ ...r, status: 'complete', pct: 100, result: d })); }
          if (d.error)     { ended = true; setRun((r) => ({ ...r, status: 'error', error: d.error })); }
          if (d.cancelled) { ended = true; setRun((r) => ({ ...r, status: 'cancelled' })); }
        }
      }
      if (!ended) setRun((r) => ({ ...r, status: 'complete', pct: 100 }));
    } catch (e) {
      setRun((r) => ({ ...r, status: e.name === 'AbortError' ? 'cancelled' : 'error', error: e.message ?? '' }));
    } finally { abortRef.current = null; }
  }
  async function pickFolder() {
    const dir = await window.electronAPI?.openDirectoryDialog?.({ defaultPath: outputDir || undefined });
    if (dir) setOutputDir(dir);
  }

  const pos = (m) => `${((m / 127) * 100).toFixed(1)}%`;
  const dispNote = (n) => `${pcName(noteNameToPC(n.note), notation)}${n.octave}`;

  return (
    <section aria-label={t('ms.title')}>
      <div className="sheet__head">
        <button type="button" className="sheet__back" onClick={onBack} aria-label={t('ms.back')} disabled={rendering}>‹</button>
        <h3>{t('ms.title')}</h3>
      </div>
      <Group title={t('ms.range')}>
        <div className="row"><span className="row__label">{t('ms.low')}</span><span style={{ display: 'flex', gap: 4 }}>
          <Select ariaLabel={t('ms.low')} value={low.note} options={noteOpts} onChange={(v) => setLow({ ...low, note: v })} disabled={rendering} />
          <Select ariaLabel={t('target.octave')} value={String(low.octave)} options={octOpts} onChange={(v) => setLow({ ...low, octave: Number(v) })} disabled={rendering} />
        </span></div>
        <div className="row"><span className="row__label">{t('ms.high')}</span><span style={{ display: 'flex', gap: 4 }}>
          <Select ariaLabel={t('ms.high')} value={high.note} options={noteOpts} onChange={(v) => setHigh({ ...high, note: v })} disabled={rendering} />
          <Select ariaLabel={t('target.octave')} value={String(high.octave)} options={octOpts} onChange={(v) => setHigh({ ...high, octave: Number(v) })} disabled={rendering} />
        </span></div>
        <div className="rangebar" aria-hidden="true">
          {valid && <i className="in" style={{ left: pos(lowMidi), width: pos(highMidi - lowMidi + 1) }} />}
          <i className="src" style={{ left: pos(srcMidi) }} />
        </div>
        <div className="help">
          {valid ? t('ms.source', { note: dispNote(src), count: total }) : <span style={{ color: 'var(--err)' }}>{t('ms.invalid_range')}</span>}
        </div>
      </Group>
      <Group title={t('ms.per_note')}>
        <Dwell hint={t('ms.loop_help')}>
          <Check label={t('ms.loop')} checked={enableLoop} defaultValue onChange={setEnableLoop} disabled={rendering} />
        </Dwell>
        <Check label={t('ms.start_trim')} checked={trimOn} defaultValue={false} onChange={setTrimOn} disabled={rendering} />
        <Slider label={t('ms.trim')} value={trimMs} min={0} max={500} defaultValue={0} format={(v) => `${Math.round(v)} ms`} onChange={setTrimMs} disabled={!trimOn || rendering} />
        <Check label={t('ms.sfz')} checked={sfz} defaultValue onChange={setSfz} disabled={rendering} />
      </Group>
      <Group title={t('ms.output')}>
        <Dwell hint={t('ms.output_help')}>
          <div className="pathbox" title={outputDir || t('ms.output_auto')}>{outputDir || t('ms.output_auto')}</div>
        </Dwell>
        <div className="row"><span /><button type="button" className="btn" onClick={pickFolder} disabled={rendering}>{t('ms.change_folder')}</button></div>
      </Group>
      {run.status !== 'idle' && (
        <Group title={t('ms.progress')}>
          {rendering && (
            <>
              <div className="row"><span className="status-line">{t('ms.rendering', { note: run.note, done: run.done, total: run.total })}</span><span className="mono dim">{run.pct} %</span></div>
              <div className="pbar"><i style={{ width: `${run.pct}%` }} /></div>
            </>
          )}
          {run.status === 'complete'  && <div className="status-line status-line--ok">{t('ms.complete', { count: run.result?.notes_rendered ?? total, dir: run.result?.output_dir ?? outputDir })}</div>}
          {run.status === 'error'     && <div className="status-line status-line--err">{t('ms.error', { error: run.error })}</div>}
          {run.status === 'cancelled' && <div className="status-line status-line--err">{t('ms.cancelled')}</div>}
        </Group>
      )}
      <div className="side__grow" />
      <div className="sheet__foot">
        <button type="button" className="btn" onClick={() => (rendering ? abortRef.current?.abort() : onBack())}>{rendering ? t('ms.cancel') : t('ms.close')}</button>
        <button type="button" className="btn btn--primary" onClick={render} disabled={rendering || !audio.loaded || !valid}>{rendering ? t('ms.rendering_btn') : t('ms.render')}</button>
      </div>
    </section>
  );
}
