import { useCallback, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { API_BASE } from '../config/api';
import { isNetworkError, loadErrorKey, readErrorDetail } from '../utils/errors';

export const EMPTY_AUDIO = Object.freeze({
  loading: false, loaded: false, filePath: null,
  peaks: null, contour: null, detectedPitch: null,
  peakDb: null, rmsDb: null, durationSeconds: 0, sampleRate: null,
});

function basename(p) { return p ? p.replace(/\\/g, '/').split('/').pop() : ''; }

/**
 * Loads a sample by path (Browse) or File (drag-drop upload) into audio state.
 * Superseded loads are discarded by token. Returns { loadAudio, abortLoad }.
 */
export function useAudioLoader({ setAudio, onLoaded, showToast }) {
  const { t } = useTranslation();
  const abortRef = useRef(null);
  const tokenRef = useRef(0);

  const abortLoad = useCallback(() => { abortRef.current?.abort(); tokenRef.current++; }, []);

  const loadAudio = useCallback(async (fileOrPath) => {
    const isFile = typeof fileOrPath !== 'string' && typeof fileOrPath?.name === 'string';
    const displayPath = isFile ? fileOrPath.name : fileOrPath;
    abortRef.current?.abort();
    const abort = new AbortController(); abortRef.current = abort;
    const token = ++tokenRef.current;

    setAudio((a) => ({ ...a, loading: true, loaded: false, filePath: displayPath }));
    const slow = setTimeout(() => showToast(t('toast.still_loading'), 'info', 8000), 15000);
    try {
      const res = isFile
        ? await fetch(`${API_BASE}/api/load-audio-upload`, { method: 'POST', body: (() => { const f = new FormData(); f.append('file', fileOrPath); return f; })(), signal: abort.signal })
        : await fetch(`${API_BASE}/api/load-audio`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ file_path: fileOrPath }), signal: abort.signal });
      if (!res.ok) throw new Error(await readErrorDetail(res));
      if (token !== tokenRef.current) return;
      const data = await res.json();
      const next = {
        loading: false, loaded: true, filePath: data.uploaded_path ?? displayPath,
        peaks: data.waveform_peaks ?? null, contour: data.f0_contour ?? null,
        detectedPitch: data.detected_pitch ?? null,
        peakDb: data.peak_db ?? null, rmsDb: data.rms_db ?? null,
        durationSeconds: data.duration_seconds ?? 0, sampleRate: data.sample_rate ?? null,
      };
      setAudio(next);
      onLoaded(next);
      showToast(t('toast.loaded', { name: basename(displayPath) }), 'success', 3000);
    } catch (err) {
      if (err.name === 'AbortError' || token !== tokenRef.current) return;
      const detail = err.message ?? '';
      const key = isNetworkError(err) ? 'toast.backend_not_running' : loadErrorKey(detail);
      showToast(key ? t(key) : `${t('toast.load_failed')}: ${detail}`, 'error', 6000);
      setAudio((a) => ({ ...a, loading: false }));
    } finally { clearTimeout(slow); }
  }, [setAudio, onLoaded, showToast, t]);

  return { loadAudio, abortLoad };
}
