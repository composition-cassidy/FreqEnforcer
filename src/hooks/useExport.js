import { useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { API_BASE } from '../config/api';
import { exportErrorKey, readErrorDetail } from '../utils/errors';
import { noteLabel } from '../utils/note_utils';

const shorten = (p) => (p.length > 55 ? `…${p.slice(-52)}` : p);

/** Export WAV (save dialog), quick export next to the source, and crossfade-loop finding. */
export function useExport({ audio, settings, processing, showToast, onLoop }) {
  const { t } = useTranslation();
  const [exporting, setExporting] = useState(false);

  const guard = useCallback(() => {
    if (!audio.loaded) return false;
    if (processing) { showToast(t('toast.wait_processing'), 'warning', 3000); return false; }
    return true;
  }, [audio.loaded, processing, showToast, t]);

  const post = useCallback(async (path, body) => {
    const res = await fetch(`${API_BASE}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!res.ok) throw new Error(await readErrorDetail(res));
    return res.json();
  }, []);

  const fail = useCallback((prefixKey, e) => {
    const key = exportErrorKey(e.message ?? '');
    showToast(key ? t(key) : `${t(prefixKey)}: ${e.message}`, 'error', 5000);
  }, [showToast, t]);

  const exportWav = useCallback(async () => {
    if (!guard()) return;
    const note = noteLabel(settings.targetNote, settings.octave);
    const src = audio.filePath ?? '';
    const base = src.replace(/\.[^/.]+$/, '').split(/[\\/]/).pop() || 'output';
    const dir = src.replace(/[\\/][^\\/]+$/, '');
    const savePath = await window.electronAPI?.saveFileDialog?.({
      defaultPath: dir ? `${dir}/${base}_${note}_tuned.wav` : `${base}_${note}_tuned.wav`,
      filters: [{ name: 'WAV', extensions: ['wav'] }],
    });
    if (!savePath) return;
    setExporting(true);
    try {
      const d = await post('/api/export', { output_path: savePath, target_note: note });
      showToast(t('toast.exported', { path: shorten(d.output_path) }), 'success', 4000);
    } catch (e) { fail('toast.export_failed', e); } finally { setExporting(false); }
  }, [guard, settings.targetNote, settings.octave, audio.filePath, post, showToast, t, fail]);

  const quickExport = useCallback(async (overwrite = false) => {
    if (!guard()) return;
    const note = noteLabel(settings.targetNote, settings.octave);
    setExporting(true);
    try {
      const d = await post('/api/quick-export', { target_note: note, overwrite });
      if (d.exists) {
        showToast(t('toast.file_exists', { name: d.output_path.split(/[\\/]/).pop() }), 'warning', 0,
          { label: t('toast.overwrite'), onClick: () => quickExport(true) });
        return;
      }
      showToast(t('toast.exported', { path: shorten(d.output_path) }), 'success', 4000);
    } catch (e) { fail('toast.export_failed', e); } finally { setExporting(false); }
  }, [guard, settings.targetNote, settings.octave, post, showToast, t, fail]);

  const findLoop = useCallback(async () => {
    if (!guard()) return;
    setExporting(true);
    try {
      const d = await post('/api/crossfade-loop', {
        template_periods: settings.loop_template_periods, min_loop_periods: settings.loop_min_periods, crossfade_periods: settings.loop_crossfade_periods,
      });
      if (d.loop_start == null) { showToast(t('toast.loop_none'), 'warning', 4000); return; }
      const sr = audio.sampleRate || 44100, n = d.sample_count;
      const loop = { startFrac: d.loop_start / n, endFrac: d.loop_end / n, startSec: d.loop_start / sr, endSec: d.loop_end / sr };
      onLoop(loop);
      showToast(t('toast.loop_set', { start: loop.startSec.toFixed(3), end: loop.endSec.toFixed(3) }), 'success', 4000);
    } catch (e) { showToast(`${t('toast.loop_failed')}: ${e.message}`, 'error', 4000); } finally { setExporting(false); }
  }, [guard, post, settings.loop_template_periods, settings.loop_min_periods, settings.loop_crossfade_periods, audio.sampleRate, onLoop, showToast, t]);

  return { exporting, exportWav, quickExport, findLoop };
}
