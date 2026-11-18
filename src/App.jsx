import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import TitleBar from './components/TitleBar';
import FileHeader from './components/FileHeader';
import PitchView from './components/PitchView';
import HarmonicPane from './components/HarmonicPane';
import Footer from './components/Footer';
import SettingsColumn from './components/settings/SettingsColumn';
import ErrorBoundary from './components/ErrorBoundary';
import { ToastProvider, useToast } from './components/Toast';
import { useAudioPlayer } from './hooks/useAudioPlayer';
import { useProcessing, settingsToBackend } from './hooks/useProcessing';
import { useSettingsHistory } from './hooks/useSettingsHistory';
import { useAudioLoader, EMPTY_AUDIO } from './hooks/useAudioLoader';
import { useExport } from './hooks/useExport';
import { useBackend } from './hooks/useBackend';
import { usePrefs } from './hooks/usePrefs';
import { useKeyboardShortcuts } from './hooks/useKeyboardShortcuts';
import { DEFAULT_SETTINGS, PITCH_MODES } from './config/settings';
import { midiToNote, noteNameToPC, parseNoteName, toMidi, clamp } from './utils/note_utils';
import './styles/tokens.css';
import './styles/base.css';
import './components/controls/controls.css';
import './components/shell.css';
import './components/view.css';
import './components/settings/settings.css';

/** What /process would receive for these settings, as a comparable key. */
const payloadKey = (s) => JSON.stringify(settingsToBackend(s));

const EMPTY_PROCESSED = Object.freeze({ peaks: null, contour: null, duration: 0, peakDb: null, rmsDb: null, harmonic: null });

/** Backend { pre, post } analysis -> what HarmonicPane draws. */
function harmonicFromBackend(raw) {
  if (!raw?.pre || !raw?.post) return null;
  const branch = (p) => ({
    harmonics: (p.harmonic_numbers ?? []).map((n, i) => ({ index: n, frequency: p.harmonic_freqs_hz?.[i] ?? 0, magnitude_db: p.peak_db?.[i] ?? -120 })),
    spectrum_freqs: p.avg_spectrum_freq_hz ?? [], spectrum_magnitudes: p.avg_spectrum_db ?? [],
  });
  return { pre: branch(raw.pre), post: branch(raw.post), f0_hz: raw.pre.f0_hz ?? null };
}

function AppInner() {
  const { t } = useTranslation();
  const { showToast } = useToast();
  const [prefs, setPrefs] = usePrefs();
  const backend = useBackend({ warmup: prefs.warmup });
  const player = useAudioPlayer();
  const history = useSettingsHistory(DEFAULT_SETTINGS);
  const { settings, set: setSettings } = history;

  const [audio, setAudio] = useState(EMPTY_AUDIO);
  const [processed, setProcessed] = useState(EMPTY_PROCESSED);
  const [proc, setProc] = useState({ active: false, pct: 0, stage: '' });
  const [abMode, setAbMode] = useState('original');
  const [sheet, setSheet] = useState('settings');
  const [loop, setLoop] = useState(null);
  const [trimFrac, setTrimFrac] = useState(null);
  const [dropping, setDropping] = useState(false);
  const [harmH, setHarmH] = useState(200);

  const settingsRef = useRef(settings); settingsRef.current = settings;
  const audioRef = useRef(audio); audioRef.current = audio;
  const debounce = useRef(null);
  const dragging = useRef(false);
  const queuedRef = useRef(null);   // backend payload (JSON) already sent; identical payloads are skipped
  const pendingDrop = useRef(null); // file opened/dropped while the backend was starting
  const backendStatus = useRef(backend.status); backendStatus.current = backend.status;

  // ── processing ──────────────────────────────────────────────────────────
  const { queueProcess, cancelProcess } = useProcessing({
    onStart: useCallback(() => { setProc({ active: true, pct: 0, stage: '' }); setLoop(null); }, []),
    onProgress: useCallback((pct, stage) => setProc({ active: true, pct, stage }), []),
    onComplete: useCallback((d) => {
      setProcessed({
        peaks: d.waveform_peaks ?? null, contour: d.f0_contour ?? null, duration: d.duration_seconds ?? 0,
        peakDb: d.peak_db ?? null, rmsDb: d.rms_db ?? null, harmonic: harmonicFromBackend(d.harmonic_analysis),
      });
      setProc({ active: false, pct: 100, stage: '' });
      setAbMode('processed');
      if (d.audio_temp_filename) player.loadProcessedFromFile(d.audio_temp_filename);
      player.switchBuffer('processed');
    }, [player]),
    onError: useCallback((msg) => {
      setProc({ active: false, pct: 0, stage: '' });
      if (/timeout/i.test(msg)) showToast(t('toast.processing_timeout'), 'error', 6000);
      else if (/out of memory/i.test(msg)) showToast(t('toast.out_of_memory'), 'error', 6000);
      else if (/network|fetch|ECONNREFUSED/i.test(msg)) {
        showToast(t('toast.backend_reconnecting'), 'error', 6000);
        backend.reconnect().then((ok) => { if (ok) showToast(t('toast.backend_reconnected'), 'success', 3000); });
      } else showToast(`${t('toast.processing_failed')}: ${msg}`, 'error', 6000);
    }, [showToast, t, backend]),
  });

  const schedule = useCallback(() => {
    clearTimeout(debounce.current);
    debounce.current = setTimeout(() => {
      if (audioRef.current.loaded) { queuedRef.current = payloadKey(settingsRef.current); queueProcess(settingsRef.current); }
    }, prefs.performance_mode ? 1000 : 600);
  }, [queueProcess, prefs.performance_mode]);

  useEffect(() => {
    // Only settings the backend reads trigger a run: the loop-finder sliders
    // (and anything else not in the /process payload) do not.
    if (!audio.loaded || payloadKey(settings) === queuedRef.current || dragging.current) return;
    schedule();
  }, [settings, audio.loaded, schedule]);

  const drag = {
    onDragStart: useCallback(() => { dragging.current = true; clearTimeout(debounce.current); }, []),
    onDragEnd: useCallback(() => { dragging.current = false; schedule(); }, [schedule]),
  };

  // ── load / new / reload ─────────────────────────────────────────────────
  const onLoaded = useCallback((a) => {
    const det = parseNoteName(a.detectedPitch?.note_name);
    const s = { ...DEFAULT_SETTINGS, ...(det ? { targetNote: det.note, octave: det.octave } : {}) };
    history.reset(s);
    queuedRef.current = payloadKey(s);
    player.loadOriginal(a.audioFile);
    queueProcess(s);
  }, [history, player, queueProcess]);
  const { loadAudio, abortLoad } = useAudioLoader({ setAudio, onLoaded, showToast });

  function beginLoad(fileOrPath) {
    cancelProcess(); clearTimeout(debounce.current);
    player.stop(); player.switchBuffer('original');
    setProcessed(EMPTY_PROCESSED); setLoop(null); setAbMode('original'); setProc({ active: false, pct: 0, stage: '' });
    loadAudio(fileOrPath);
  }
  function closeSample() {
    abortLoad(); cancelProcess(); clearTimeout(debounce.current); player.reset();
    setAudio(EMPTY_AUDIO); setProcessed(EMPTY_PROCESSED); setLoop(null); setAbMode('original');
    setProc({ active: false, pct: 0, stage: '' }); history.reset(DEFAULT_SETTINGS);
  }
  // A file opened or dropped before the engine is up waits in pendingDrop and
  // loads as soon as it is (see the effect below).
  function openOrQueue(f) {
    if (backendStatus.current === 'ok') beginLoad(f); else pendingDrop.current = f;
  }
  async function openFile() {
    const p = await window.electronAPI?.openFileDialog?.();
    if (p) openOrQueue(p);
  }
  useEffect(() => {
    if (backend.status !== 'ok') return;
    // --fe-open=<path> in Electron; ?open=<path> when served by Vite alone (dev)
    const f = pendingDrop.current ?? window.electronAPI?.initialFile ?? new URLSearchParams(window.location.search).get('open');
    pendingDrop.current = null;
    if (f && !audioRef.current.loaded && !audioRef.current.loading) beginLoad(f);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [backend.status]);

  // ── export / loop ───────────────────────────────────────────────────────
  const { exporting, exportWav, quickExport, findLoop } = useExport({ audio, settings, processing: proc.active, showToast, onLoop: setLoop });
  const busy = proc.active || exporting;

  // ── derived ─────────────────────────────────────────────────────────────
  const hasProcessed = Boolean(processed.peaks);
  const toggleAB = useCallback(() => {
    if (!hasProcessed) return;
    setAbMode((m) => { const next = m === 'original' ? 'processed' : 'original'; player.switchBuffer(next); return next; });
  }, [hasProcessed, player]);
  const setAB = (next) => { if (next !== abMode) toggleAB(); };
  const shiftNote = (st) => setSettings((s) => {
    const midi = clamp(toMidi(s.octave, noteNameToPC(s.targetNote)) + st, 12, 115);
    const n = midiToNote(midi);
    return { targetNote: n.note, octave: n.octave };
  });
  const onTrimPreview = useCallback((ms) => {
    const d = audioRef.current.durationSeconds;
    setTrimFrac(ms == null || ms <= 0 || !d ? null : Math.min(0.99, ms / 1000 / d));
  }, []);
  const action = (id) => ({
    open: openFile, reload: () => audio.filePath && beginLoad(audio.filePath), close: closeSample,
    export: exportWav, quickExport: () => quickExport(false),
    multisample: () => audio.loaded && setSheet('multisample'), preferences: () => setSheet('preferences'),
  })[id]?.();

  useKeyboardShortcuts({
    space: player.isPlaying ? player.stop : player.play, a: toggleAB,
    'ctrl+o': openFile, 'ctrl+n': closeSample, 'ctrl+r': () => action('reload'),
    'ctrl+e': exportWav, 'ctrl+shift+e': () => quickExport(false), 'ctrl+m': () => action('multisample'),
    'ctrl+,': () => setSheet('preferences'), escape: () => setSheet('settings'), 'ctrl+q': () => window.electronAPI?.closeWindow(),
    'ctrl+z': history.undo, 'ctrl+shift+z': history.redo, 'ctrl+y': history.redo,
    'ctrl+arrowup': () => shiftNote(1), 'ctrl+arrowdown': () => shiftNote(-1),
    'ctrl+shift+arrowup': () => shiftNote(12), 'ctrl+shift+arrowdown': () => shiftNote(-12),
    ...Object.fromEntries(PITCH_MODES.map((m, i) => [String(i + 1), () => setSettings({ pitch_mode: m })])),
  });

  // ── drag & drop ─────────────────────────────────────────────────────────
  const dragProps = {
    onDragEnter: (e) => { if (e.dataTransfer.types.includes('Files')) { e.preventDefault(); setDropping(true); } },
    onDragOver: (e) => { if (e.dataTransfer.types.includes('Files')) { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; } },
    onDragLeave: (e) => { if (e.relatedTarget === null) setDropping(false); },
    onDrop: (e) => {
      e.preventDefault(); setDropping(false);
      const file = e.dataTransfer.files[0]; if (!file) return;
      openOrQueue(window.electronAPI?.getLastDroppedFilePath?.() || file);
    },
  };

  // ── harmonic pane resize ────────────────────────────────────────────────
  // 1:1 with the pointer: the drag writes the grid row straight onto the
  // element and commits to React state once, on release.
  const centerRef = useRef(null);
  function onSplitter(e) {
    const y0 = e.clientY, h0 = harmH;
    let h = h0;
    const move = (ev) => { h = clamp(h0 - (ev.clientY - y0), 120, 480); centerRef.current?.style.setProperty('--harm-h', `${h}px`); };
    const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); setHarmH(h); };
    window.addEventListener('pointermove', move); window.addEventListener('pointerup', up);
  }

  const showHarm = settings.harmonic_limiter_enabled;
  const levels = abMode === 'processed' && processed.peakDb != null ? { peak: processed.peakDb, rms: processed.rmsDb } : { peak: audio.peakDb, rms: audio.rmsDb };
  const engine = backend.status === 'ok' ? 'ready' : backend.status === 'error' ? 'error' : 'starting';

  return (
    <div className={`app${audio.loaded ? '' : ' app--idle'}`} data-engine={engine} {...dragProps}>
      {dropping && <div className="drop"><div>{t('view.drop_now')}</div></div>}
      <TitleBar audioLoaded={audio.loaded} processing={proc} busy={busy} prefs={prefs} onPrefs={setPrefs} onAction={action} engine={engine} onRetryEngine={backend.recheck} />
      <FileHeader audio={audio} notation={prefs.notation} onOpen={openFile} />
      <div className="progress" aria-hidden="true">{proc.active && <i className={proc.pct > 0 ? '' : 'indeterminate'} style={proc.pct > 0 ? { transform: `scaleX(${proc.pct / 100})` } : undefined} />}</div>
      <div ref={centerRef} className={`center${showHarm ? ' center--harm' : ''}`} style={{ '--harm-h': `${harmH}px` }}>
        <ErrorBoundary label="PitchView">
          <PitchView
            audio={{ loaded: audio.loaded, loading: audio.loading, peaks: audio.peaks, contour: audio.contour, duration: audio.durationSeconds }}
            processed={processed} abMode={abMode} target={{ note: settings.targetNote, octave: settings.octave }} notation={prefs.notation}
            playing={player.isPlaying} subscribe={player.subscribe} loop={loop} trimFrac={trimFrac} busy={proc.active}
            onTargetShift={shiftNote} onSeek={(f) => player.seek(f * player.duration)}
          />
        </ErrorBoundary>
        {showHarm && (
          <>
            <div className="splitter" role="separator" aria-orientation="horizontal" onPointerDown={onSplitter} />
            <ErrorBoundary label="HarmonicPane">
              <HarmonicPane
                analysis={processed.harmonic} offsets={settings.harmonic_ceiling_offsets_db}
                onOffsetChange={(i, db) => setSettings((s) => ({ harmonic_ceiling_offsets_db: { ...s.harmonic_ceiling_offsets_db, [i]: db } }))}
                onResetAll={() => setSettings({ harmonic_ceiling_offsets_db: {} })}
              />
            </ErrorBoundary>
          </>
        )}
      </div>
      <SettingsColumn
        sheet={sheet} onSheet={setSheet} settings={settings} onChange={setSettings} drag={drag} audio={audio}
        prefs={prefs} onPrefs={setPrefs} loop={loop} onFindLoop={findLoop} busy={busy} onTrimPreview={onTrimPreview}
      />
      <Footer
        player={{ playing: player.isPlaying, subscribe: player.subscribe, duration: player.duration, toggle: player.isPlaying ? player.stop : player.play }}
        abMode={abMode} onAB={setAB} hasProcessed={hasProcessed} levels={levels}
        history={history} audioLoaded={audio.loaded} busy={busy} onAction={action}
      />
    </div>
  );
}

export default function App() {
  return <ToastProvider><AppInner /></ToastProvider>;
}
