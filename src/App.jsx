import { useState, useRef, useCallback, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import TitleBar from './components/TitleBar';
import FileBar from './components/FileBar';
import WaveformDisplay from './components/WaveformDisplay';
import HarmonicLimiter from './components/HarmonicLimiter';
import SettingsPanel from './components/SettingsPanel';
import ThemeEditor, { loadSavedTheme } from './components/ThemeEditor';
import PreferencesDialog from './components/PreferencesDialog';
import MultiSampleDialog from './components/MultiSampleDialog';
import { ToastProvider, useToast } from './components/Toast';
import ErrorBoundary from './components/ErrorBoundary';
import { useProcessing } from './hooks/useProcessing';
import { useAudioPlayer } from './hooks/useAudioPlayer';
import { useKeyboardShortcuts } from './hooks/useKeyboardShortcuts';
import VS from './config/visualSettings.json';
import './index.css';

// ── Layout constants ───────────────────────────────────────────────────────
const PLAYBACK_ROW_H = 32;
const SPLITTER_H     = 4;
const API_BASE       = 'http://localhost:8765';

// ── Default options (UI/app-level preferences, separate from audio settings) ─
const DEFAULT_OPTIONS = {
  show_loading_dialog: true,
  performance_mode:    false,
  warmup_enabled:      true,
  note_notation:       'sharps',
};

// ── Default settings ───────────────────────────────────────────────────────
const DEFAULT_SETTINGS = {
  targetNote: 'C', octave: 4, notation: 'sharps',
  pitch_mode: 'world_hard',
  pitch_amount: 1.0,          // stored 0-1
  retune_speed_ms: 40,
  preserve_vibrato: 1.0,      // stored 0-1
  normalize: false,
  formant_shift_cents: 0,
  formant_shift_beta: 0.10,   // stored 0-1
  stretch_method: 'audiotsm_wsola',
  stretch_factor: 1.0,
  breathiness: 1.0,
  hf_bias: 0.0,
  cleanliness_percent: 0,
  clean_advanced_mode: false,
  clean_lowcut_percent: 0,
  clean_hf_rollback_percent: 0,
  harmonic_limiter_enabled: false,
  harmonic_amount: 50,
  harmonic_ceiling_offsets_db: {},
};

// Ordered exactly as shown in the pitch-mode selector (groups: WORLD → PSOLA → Experimental)
const NOTE_SEMITONES_SCALE = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'];
const PITCH_MODES = [
  'world_hard', 'world_soft', 'world_vt', 'world_hnm',
  'praat_soft',
  'sine_spectral', 'stft_pitchshift',
];

const DEFAULT_AUDIO_STATE = {
  loading:             false,
  loaded:              false,
  filePath:            null,
  originalPeaks:       null,
  processedPeaks:      null,
  processedPeakDb:     null,
  processedRmsDb:      null,
  processedTempPath:   null,
  detectedPitch:       null,
  peakDb:              null,
  rmsDb:               null,
  durationSeconds:     null,
  sampleRate:          null,
};

// ── Helpers ────────────────────────────────────────────────────────────────
function basename(p) {
  return p ? p.replace(/\\/g, '/').split('/').pop() : '';
}

function parseNoteName(noteStr) {
  if (!noteStr) return null;
  const m = noteStr.match(/^([A-G][#b]?)(\d)$/i);
  if (!m) return null;
  return {
    note:   m[1].charAt(0).toUpperCase() + m[1].slice(1),
    octave: parseInt(m[2], 10),
  };
}

function isNetworkError(err) {
  return err instanceof TypeError && /fetch|network|failed/i.test(err.message);
}

/** Map an export error message to a user-friendly i18n toast string. */
function categorizeExportError(detail, t) {
  const d = detail.toLowerCase();
  if (/permission denied|access is denied|cannot write/i.test(d))
    return t('electron.toast.export_permission');
  if (/no space left|disk full|not enough space/i.test(d))
    return t('electron.toast.export_disk_full');
  if (/path too long|file path too long/i.test(d))
    return t('electron.toast.export_path_too_long');
  return `Export failed: ${detail}`;
}

/** Format seconds as MM:SS */
function formatTime(s) {
  if (!s || s < 0) return '00:00';
  const m = Math.floor(s / 60);
  return `${String(m).padStart(2, '0')}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
}

/** Reduce peaks array to at most maxBins entries by picking max in each bucket */
function downsamplePeaks(peaks, maxBins) {
  if (!peaks || peaks.length <= maxBins) return peaks;
  const out = new Array(maxBins);
  const step = peaks.length / maxBins;
  for (let i = 0; i < maxBins; i++) {
    const lo = Math.floor(i * step);
    const hi = Math.min(Math.ceil((i + 1) * step), peaks.length);
    let max = 0;
    for (let j = lo; j < hi; j++) if (peaks[j] > max) max = peaks[j];
    out[i] = max;
  }
  return out;
}

// ── AppInner ───────────────────────────────────────────────────────────────
function AppInner() {
  const { t } = useTranslation();
  const { showToast } = useToast();

  // ── App-level preferences ──────────────────────────────────────────────
  const [options,    setOptions]    = useState(DEFAULT_OPTIONS);
  const [prefsOpen,  setPrefsOpen]  = useState(false);
  const [multiSampleOpen, setMultiSampleOpen] = useState(false);
  const optionsRef = useRef(options);
  optionsRef.current = options;

  // ── Backend health check ───────────────────────────────────────────────
  // 'checking' on first load, 'ok' once backend responds, 'error' if unreachable
  const [backendStatus, setBackendStatus] = useState('checking');
  const pendingDropRef = useRef(null); // file dropped while backend is starting

  const checkBackendHealth = useCallback(async () => {
    try {
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), 5000);
      const res = await fetch(`${API_BASE}/health`, { signal: ctrl.signal });
      clearTimeout(t);
      if (res.ok) {
        setBackendStatus('ok');
        return true;
      }
    } catch (_) {}
    return false;
  }, []);

  useEffect(() => {
    let cancelled = false;
    checkBackendHealth().then((ok) => {
      if (!cancelled && !ok) setBackendStatus('error');
    });
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { loadSavedTheme(); }, []);

  // Auto-load any file that was dropped while the backend was still starting
  useEffect(() => {
    if (backendStatus === 'ok' && pendingDropRef.current) {
      const pending = pendingDropRef.current;
      pendingDropRef.current = null;
      loadAudio(pending);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [backendStatus]);

  // ── Audio player ───────────────────────────────────────────────────────
  const {
    play, stop, reset,
    loadOriginal, loadProcessed, loadProcessedFromFile, switchBuffer,
    isPlaying: audioIsPlaying,
    playbackPosition,
    duration: audioDuration,
  } = useAudioPlayer();

  // ── State ──────────────────────────────────────────────────────────────
  const [audioState, setAudioState] = useState(DEFAULT_AUDIO_STATE);
  const [settings,   setSettings]   = useState(DEFAULT_SETTINGS);
  const [viewState,  setViewState]  = useState({
    showProcessed:       false,
    isProcessing:        false,
    processingProgress:  0,
    harmonicAnalysis:    null,
  });

  const [isExporting,  setIsExporting]  = useState(false);
  // Loop points for the current processed audio; fractions 0.0–1.0 relative to audio length
  const [loopPoints, setLoopPoints] = useState(null); // { startFrac, endFrac, startSec, endSec }
  // Start trim preview — fraction 0.0–1.0 (null = no marker shown)
  const [startTrimPreviewFrac, setStartTrimPreviewFrac] = useState(null);
  const [selectedMidi, setSelectedMidi] = useState(60);
  const [midiRange,    setMidiRange]    = useState([48, 72]);
  const [splitRatio,   setSplitRatio]   = useState(0.65);
  const [draggingFile, setDraggingFile] = useState(false);
  const [splitterDragging, setSplitterDragging] = useState(false);

  // A/B crossfade opacity (briefly 0 when switching)
  const [waveformFading, setWaveformFading] = useState(false);

  // Reveal animation: peaks waiting to be sweep-revealed on the waveform
  const [revealPeaks, setRevealPeaks] = useState(null);

  // Slide animation: target MIDI note for smooth blob transition (SettingsPanel-initiated)
  const [animateToMidi, setAnimateToMidi] = useState(null);

  const mainRef = useRef(null);

  // ── Refs for stable access inside callbacks ────────────────────────────
  const settingsRef         = useRef(settings);
  const audioLoadedRef      = useRef(audioState.loaded);
  const loadAbortRef        = useRef(null);
  const loadTokenRef        = useRef(0);        // incremented on each new load; stale results are discarded
  const processDebounce     = useRef(null);
  const isFirstSettings     = useRef(true);
  const noteChangeSourceRef = useRef(null);  // 'waveform' when drag-initiated
  const dragActiveRef       = useRef(false); // true while any slider/knob is being dragged
  const processingCompleteTimer = useRef(null); // for 200ms hold at 100% after completion
  const backendReconnecting = useRef(false);    // prevents overlapping reconnect polls

  settingsRef.current    = settings;
  audioLoadedRef.current = audioState.loaded;

  // Sync note notation from preferences → settings (affects MiniPiano, note dropdown, etc.)
  useEffect(() => {
    setSettings((s) => ({ ...s, notation: options.note_notation }));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [options.note_notation]);

  // ── Processing callbacks ───────────────────────────────────────────────
  const handleProcessStart = useCallback(() => {
    clearTimeout(processingCompleteTimer.current);
    setViewState((v) => ({ ...v, isProcessing: true, processingProgress: 0 }));
    setLoopPoints(null);
  }, []);

  const handleProcessProgress = useCallback((pct) => {
    setViewState((v) => ({ ...v, processingProgress: pct }));
  }, []);

  const handleProcessComplete = useCallback((data) => {
    // Route peaks through the reveal (sweep) animation instead of setting immediately
    setRevealPeaks(data.waveform_peaks ?? null);
    setAudioState((s) => ({
      ...s,
      processedPeakDb:   data.peak_db           ?? null,
      processedRmsDb:    data.rms_db            ?? null,
      processedTempPath: data.audio_temp_path   ?? null,
    }));
    // Transform backend { pre, post } into { pre: {...}, post: {...} }
    // Each branch: harmonics:[{index,frequency,magnitude_db}], spectrum_freqs, spectrum_magnitudes
    const _txBranch = (p) => ({
      harmonics: (p.harmonic_numbers ?? []).map((n, i) => ({
        index:        n,
        frequency:    p.harmonic_freqs_hz?.[i] ?? 0,
        magnitude_db: p.peak_db?.[i] ?? -120,
      })),
      spectrum_freqs:      p.avg_spectrum_freq_hz ?? [],
      spectrum_magnitudes: p.avg_spectrum_db      ?? [],
    });
    let harmonicAnalysis = null;
    const raw = data.harmonic_analysis;
    if (raw?.pre && raw?.post) {
      harmonicAnalysis = {
        pre:   _txBranch(raw.pre),
        post:  _txBranch(raw.post),
        f0_hz: raw.pre.f0_hz ?? null,
      };
    }
    // Show 100% progress first, keep isProcessing=true for 200ms hold
    setViewState((v) => ({
      ...v,
      processingProgress: 100,
      showProcessed:      true,
      harmonicAnalysis,
    }));
    // After 200ms hold at 100%, fade back to file info
    clearTimeout(processingCompleteTimer.current);
    processingCompleteTimer.current = setTimeout(() => {
      setViewState((v) => ({ ...v, isProcessing: false, processingProgress: 0 }));
    }, 200);
    // Load processed audio: prefer direct file URL (skips base64), fall back to fetch
    if (data.audio_temp_filename) {
      loadProcessedFromFile(data.audio_temp_filename);
      switchBuffer('processed');
    } else {
      loadProcessed()
        .then(() => switchBuffer('processed'))
        .catch((e) => console.warn('useAudioPlayer: loadProcessed failed', e));
    }
  }, [loadProcessed, loadProcessedFromFile, switchBuffer]);

  const handleProcessError = useCallback((message) => {
    clearTimeout(processingCompleteTimer.current);
    setViewState((v) => ({ ...v, isProcessing: false, processingProgress: 0 }));
    const isNetwork = /network|fetch|ECONNREFUSED|failed to fetch/i.test(message);
    const isTimeout = /timeout/i.test(message);
    const isOOM     = /out of memory|memory error/i.test(message);
    let toastMsg;
    if (isTimeout)      toastMsg = t('electron.toast.processing_timeout');
    else if (isOOM)     toastMsg = t('electron.toast.out_of_memory');
    else if (isNetwork) {
      toastMsg = t('electron.toast.backend_reconnecting');
      // Start background reconnection polling
      if (!backendReconnecting.current) {
        backendReconnecting.current = true;
        const poll = setInterval(async () => {
          try {
            const res = await fetch(`${API_BASE}/health`);
            if (res.ok) {
              clearInterval(poll);
              backendReconnecting.current = false;
              setBackendStatus('ok');
              showToast(t('electron.toast.backend_reconnected'), 'success', 3000);
            }
          } catch (_) {}
        }, 3000);
      }
    } else              toastMsg = `${t('electron.toast.processing_failed')}: ${message}`;
    showToast(toastMsg, 'error', 6000);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showToast, t]);

  // ── useProcessing hook ─────────────────────────────────────────────────
  const { queueProcess, cancelProcess } = useProcessing({
    onStart:    handleProcessStart,
    onProgress: handleProcessProgress,
    onComplete: handleProcessComplete,
    onError:    handleProcessError,
  });

  // ── Debounce scheduling helper ─────────────────────────────────────────
  const scheduleProcessing = useCallback(() => {
    if (!audioLoadedRef.current) return;
    clearTimeout(processDebounce.current);
    processDebounce.current = setTimeout(() => {
      if (audioLoadedRef.current) queueProcess(settingsRef.current);
    }, optionsRef.current.performance_mode ? 1000 : 600);
  }, [queueProcess]);

  // Called when any slider/knob starts a drag — suppress debounce until release
  const handleControlDragStart = useCallback(() => {
    dragActiveRef.current = true;
    clearTimeout(processDebounce.current); // cancel any pending timer during drag
  }, []);

  // Called when any slider/knob releases — start debounce now
  const handleControlRelease = useCallback(() => {
    dragActiveRef.current = false;
    scheduleProcessing();
  }, [scheduleProcessing]);

  // ── Debounced processing trigger on settings change ───────────────────
  useEffect(() => {
    if (!audioState.loaded) {
      clearTimeout(processDebounce.current);
      return;
    }
    // Audio just became loaded — kick off the first process immediately
    queueProcess(settingsRef.current);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [audioState.loaded]);

  useEffect(() => {
    if (isFirstSettings.current) { isFirstSettings.current = false; return; }
    if (!audioLoadedRef.current) return;
    // Skip debounce while a slider/knob is being dragged — onRelease will schedule
    if (dragActiveRef.current) return;
    scheduleProcessing();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settings]);

  // ── Keep selectedMidi in sync with settings.targetNote / octave ────────
  // Waveform-drag changes → jump directly. SettingsPanel/load changes → animate.
  useEffect(() => {
    const NOTE_SEMITONES = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'];
    const idx = NOTE_SEMITONES.indexOf(settings.targetNote);
    if (idx === -1) return;
    const newMidi = (settings.octave + 1) * 12 + idx;

    // If the change came from waveform drag or file load, jump directly (no animation)
    if (noteChangeSourceRef.current === 'waveform' || noteChangeSourceRef.current === 'load') {
      noteChangeSourceRef.current = null;
      setSelectedMidi(newMidi);
      return;
    }

    // SettingsPanel-initiated → trigger slide animation
    if (newMidi !== selectedMidi && audioState.loaded) {
      setAnimateToMidi(newMidi);
    } else {
      setSelectedMidi(newMidi);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settings.targetNote, settings.octave]);

  // ── loadAudio ──────────────────────────────────────────────────────────
  // Accepts either a string path (from Browse dialog) or a File object
  // (from drag-and-drop, where Electron 32+ doesn't expose native paths).
  const loadAudio = useCallback(async (fileOrPath) => {
    const isFile = typeof fileOrPath !== 'string' && fileOrPath != null && typeof fileOrPath.name === 'string' && typeof fileOrPath.size === 'number';
    const displayPath = isFile ? fileOrPath.name : fileOrPath;
    console.log('[loadAudio] type:', typeof fileOrPath, '| isFile:', isFile, '| constructor:', fileOrPath?.constructor?.name, '| name:', fileOrPath?.name, '| size:', fileOrPath?.size);

    if (loadAbortRef.current) loadAbortRef.current.abort();
    const abort = new AbortController();
    loadAbortRef.current = abort;

    // Bump token so any result from a previous in-flight load is discarded
    const loadToken = ++loadTokenRef.current;

    // Cancel any in-progress processing before loading new file
    cancelProcess();
    clearTimeout(processingCompleteTimer.current);

    // Stop audio and reset to original side immediately
    stop();
    switchBuffer('original');

    setAudioState((s) => ({ ...s, loading: true, loaded: false, filePath: displayPath }));
    setViewState((v) => ({ ...v, showProcessed: false }));
    isFirstSettings.current = true;

    const slowTimer = setTimeout(() => {
      showToast(t('electron.toast.still_loading'), 'info', 8000);
    }, 15000);

    try {
      const _loadStart = performance.now();
      let res;
      if (isFile) {
        // Drag-and-drop: upload file content to the backend
        const formData = new FormData();
        formData.append('file', fileOrPath);
        res = await fetch(`${API_BASE}/api/load-audio-upload`, {
          method: 'POST',
          body:   formData,
          signal: abort.signal,
        });
      } else {
        // Browse dialog: send the native path
        res = await fetch(`${API_BASE}/api/load-audio`, {
          method:  'POST',
          headers: { 'Content-Type': 'application/json' },
          body:    JSON.stringify({ file_path: fileOrPath }),
          signal:  abort.signal,
        });
      }
      const _fetchTime = performance.now() - _loadStart;

      if (!res.ok) {
        let detail = res.statusText;
        try {
          const body = await res.json();
          const d = body.detail;
          if (Array.isArray(d)) {
            detail = d.map((e) => {
              const loc = (e.loc || []).slice(1).join(' → ');
              return loc ? `${loc}: ${e.msg}` : (e.msg || String(e));
            }).join('; ');
          } else if (typeof d === 'string') {
            detail = d;
          } else if (d != null) {
            detail = JSON.stringify(d);
          }
        } catch (_) {}
        throw new Error(detail);
      }

      // Discard result if a newer load was started while we were waiting
      if (loadToken !== loadTokenRef.current) return;

      const data = await res.json();
      const _totalLoadTime = performance.now() - _loadStart;
      console.log('%c=== FILE LOAD PERFORMANCE ===', 'color: #33CED6; font-weight: bold');
      console.log(`  Fetch round-trip: ${_fetchTime.toFixed(1)} ms`);
      console.log(`  Total (w/ JSON):  ${_totalLoadTime.toFixed(1)} ms`);
      if (data.timings) {
        console.log('  Backend breakdown:', data.timings);
      }

      const parsed = parseNoteName(data.detected_pitch?.note_name);
      if (parsed) {
        noteChangeSourceRef.current = 'load'; // skip slide animation on initial load
        setSettings((s) => ({ ...s, targetNote: parsed.note, octave: parsed.octave }));
        const NOTE_SEMITONES = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'];
        const semitoneIdx = NOTE_SEMITONES.indexOf(parsed.note);
        if (semitoneIdx !== -1) {
          const detectedMidi = (parsed.octave + 1) * 12 + semitoneIdx;
          setSelectedMidi(detectedMidi);
          // Also re-centre the visible range around the detected note
          const half = Math.round((midiRange[1] - midiRange[0]) / 2);
          const newLo = Math.max(0,   detectedMidi - half);
          const newHi = Math.min(128, newLo + (midiRange[1] - midiRange[0]));
          setMidiRange([newLo, newHi]);
        }
      }

      const resolvedPath = displayPath;

      const newAudioState = {
        loading:           false,
        loaded:            true,
        filePath:          resolvedPath,
        originalPeaks:     data.waveform_peaks   ?? null,
        processedPeaks:    null,
        processedPeakDb:   null,
        processedRmsDb:    null,
        processedTempPath: null,
        detectedPitch:     data.detected_pitch   ?? null,
        peakDb:            data.peak_db          ?? null,
        rmsDb:             data.rms_db           ?? null,
        durationSeconds:   data.duration_seconds ?? null,
        sampleRate:        data.sample_rate      ?? null,
      };
      setAudioState(newAudioState);

      // Delay clearing the first-settings flag so the useEffect([settings])
      // doesn't auto-trigger processing on the settings change from parseNoteName.
      // The effect fires AFTER render; this setTimeout fires AFTER that.
      setTimeout(() => { isFirstSettings.current = false; }, 0);

      // Fetch original audio buffer for playback (fire and forget)
      loadOriginal().catch((e) => console.warn('useAudioPlayer: loadOriginal failed', e));

      showToast(t('electron.toast.loaded', { name: basename(displayPath) }), 'success', 3000);
    } catch (err) {
      if (err.name === 'AbortError') return;
      if (loadToken !== loadTokenRef.current) return; // superseded by a newer load
      const detail = err.message ?? '';
      let toastMsg;
      if (isNetworkError(err)) {
        toastMsg = t('electron.toast.backend_not_running');
      } else if (/unsupported audio format/i.test(detail)) {
        toastMsg = t('electron.toast.unsupported_format');
      } else if (/file too large/i.test(detail)) {
        toastMsg = t('electron.toast.file_too_large');
      } else if (/failed to (read|decode)|failed to read/i.test(detail)) {
        toastMsg = t('electron.toast.decode_failed');
      } else if (/out of memory/i.test(detail)) {
        toastMsg = t('electron.toast.out_of_memory');
      } else {
        toastMsg = `${t('electron.toast.load_failed')}: ${detail}`;
      }
      showToast(toastMsg, 'error', 6000);
      setAudioState((s) => ({ ...s, loading: false }));
    } finally {
      clearTimeout(slowTimer);
    }
  }, [showToast, stop, switchBuffer, loadOriginal, cancelProcess, t]);

  // ── Animation callbacks ───────────────────────────────────────────────
  const handleRevealComplete = useCallback(() => {
    setAudioState((s) => ({ ...s, processedPeaks: revealPeaks }));
    setRevealPeaks(null);
  }, [revealPeaks]);

  const handleSlideComplete = useCallback(() => {
    if (animateToMidi != null) setSelectedMidi(animateToMidi);
    setAnimateToMidi(null);
  }, [animateToMidi]);

  // ── App-level handlers ─────────────────────────────────────────────────
  function handleFileLoad(fileOrPath) {
    if (fileOrPath) loadAudio(fileOrPath);
  }

  // ── Full-window drag-and-drop ───────────────────────────────────────────
  function handleAppDragEnter(e) {
    if (!e.dataTransfer.types.includes('Files')) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
  }
  function handleAppDragOver(e) {
    if (!e.dataTransfer.types.includes('Files')) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
    setDraggingFile(true);
  }
  function handleAppDragLeave(e) {
    // Only clear when the cursor leaves the browser window entirely
    if (e.relatedTarget === null) setDraggingFile(false);
  }
  function handleAppDrop(e) {
    e.preventDefault();
    setDraggingFile(false);
    const file = e.dataTransfer.files[0];
    if (file) {
      const realPath = window.electronAPI?.getLastDroppedFilePath?.();
      const fileOrPath = realPath || file;
      if (backendStatus === 'ok') {
        handleFileLoad(fileOrPath);
      } else {
        pendingDropRef.current = fileOrPath;
      }
    }
  }

  function handleNewSample() {
    reset();                                     // stop audio + clear buffers
    loadAbortRef.current?.abort();
    cancelProcess();
    clearTimeout(processDebounce.current);
    clearTimeout(processingCompleteTimer.current);
    isFirstSettings.current = true;
    setAudioState(DEFAULT_AUDIO_STATE);
    setSettings(DEFAULT_SETTINGS);
    setRevealPeaks(null);
    setAnimateToMidi(null);
    setLoopPoints(null);
    setViewState((v) => ({
      ...v,
      showProcessed:      false,
      isProcessing:       false,
      processingProgress: 0,
      harmonicAnalysis:   null,
    }));
  }

  function handleRefreshSample() {
    if (!audioState.filePath) return;
    // Reset all audio settings to defaults before re-loading the sample
    setSettings((s) => ({
      ...DEFAULT_SETTINGS,
      // Keep the user's notation preference
      notation: s.notation,
    }));
    loadAudio(audioState.filePath);
  }

  // ── Keyboard shortcut helpers ─────────────────────────────────────────

  /** Shift the target note by `semitones` (positive = up, negative = down). */
  function shiftNote(semitones) {
    setSettings((s) => {
      const idx = NOTE_SEMITONES_SCALE.indexOf(s.targetNote);
      if (idx === -1) return s;
      const currentMidi = (s.octave + 1) * 12 + idx;
      const newMidi     = Math.max(12, Math.min(115, currentMidi + semitones));
      return {
        ...s,
        targetNote: NOTE_SEMITONES_SCALE[newMidi % 12],
        octave:     Math.floor(newMidi / 12) - 1,
      };
    });
  }

  /** Open the file dialog and load the chosen file (same flow as FileBar browse). */
  async function handleOpenFile() {
    try {
      const path = await window.electronAPI?.openFileDialog();
      if (path) loadAudio(path);
    } catch (e) {
      console.warn('File dialog error:', e);
    }
  }

  // ── Global keyboard shortcuts (single listener via useKeyboardShortcuts) ──
  useKeyboardShortcuts({
    // Playback
    'space':             handlePlayToggle,

    // File
    'ctrl+n':            handleNewSample,
    'ctrl+o':            handleOpenFile,
    'ctrl+r':            () => { if (audioState.loaded) handleRefreshSample(); },
    'ctrl+shift+e':      handleExport,
    'ctrl+e':            handleQuickExport,
    'ctrl+m':            () => { if (audioState.loaded) setMultiSampleOpen(true); },
    'ctrl+q':            () => window.electronAPI?.closeWindow(),

    // UI
    'ctrl+,':            () => setPrefsOpen(true),
    'escape':            () => setPrefsOpen(false),

    // A/B toggle (only meaningful when audio is loaded)
    'a':                 toggleAB,

    // Target note — semitone steps
    'ctrl+arrowup':      () => shiftNote(1),
    'ctrl+arrowdown':    () => shiftNote(-1),

    // Target note — octave steps
    'ctrl+shift+arrowup':   () => shiftNote(12),
    'ctrl+shift+arrowdown': () => shiftNote(-12),

    // Pitch mode 1-7 (matches PITCH_MODES order)
    '1': () => setSettings((s) => ({ ...s, pitch_mode: PITCH_MODES[0] })),
    '2': () => setSettings((s) => ({ ...s, pitch_mode: PITCH_MODES[1] })),
    '3': () => setSettings((s) => ({ ...s, pitch_mode: PITCH_MODES[2] })),
    '4': () => setSettings((s) => ({ ...s, pitch_mode: PITCH_MODES[3] })),
    '5': () => setSettings((s) => ({ ...s, pitch_mode: PITCH_MODES[4] })),
    '6': () => setSettings((s) => ({ ...s, pitch_mode: PITCH_MODES[5] })),
    '7': () => setSettings((s) => ({ ...s, pitch_mode: PITCH_MODES[6] })),

  });

  /** Main play/stop toggle — ■ means stop-to-beginning, not pause */
  function handlePlayToggle() {
    if (audioIsPlaying) {
      stop();
    } else {
      play();
    }
  }

  function toggleAB() {
    if (options.performance_mode) {
      // Instant switch in performance mode — skip fade animation
      setViewState((v) => {
        const next = !v.showProcessed;
        switchBuffer(next ? 'processed' : 'original');
        return { ...v, showProcessed: next };
      });
    } else {
      setWaveformFading(true);
      setTimeout(() => {
        setViewState((v) => {
          const next = !v.showProcessed;
          switchBuffer(next ? 'processed' : 'original');
          return { ...v, showProcessed: next };
        });
        setWaveformFading(false);
      }, 100);
    }
  }

  async function handleExport() {
    if (viewState.isProcessing) {
      showToast('Wait for processing to complete before exporting', 'warning', 3000);
      return;
    }
    if (!audioState.loaded) return;

    const filePath   = audioState.filePath ?? '';
    const noteStr    = `${settings.targetNote}${settings.octave}`;
    const baseName   = filePath
      ? filePath.replace(/\.[^/.]+$/, '').split(/[\\/]/).pop()
      : 'output';
    const sourceDir  = filePath ? filePath.replace(/[\\/][^\\/]+$/, '') : '';
    const defaultPath = sourceDir
      ? `${sourceDir}/${baseName}_${noteStr}_tuned.wav`
      : `${baseName}_${noteStr}_tuned.wav`;

    const savePath = await window.electronAPI.saveFileDialog({
      defaultPath,
      filters: [{ name: 'WAV Audio', extensions: ['wav'] }],
    });
    if (!savePath) return;

    setIsExporting(true);
    try {
      const res = await fetch(`${API_BASE}/api/export`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ output_path: savePath, target_note: noteStr }),
      });
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({ detail: 'Unknown error' }));
        showToast(categorizeExportError(errBody.detail ?? 'Unknown error', t), 'error', 5000);
        return;
      }
      const data = await res.json();
      const display = data.output_path.length > 55
        ? '...' + data.output_path.slice(-52)
        : data.output_path;
      showToast(`Exported to ${display}`, 'success', 4000);
    } catch (e) {
      showToast(categorizeExportError(e.message ?? '', t), 'error', 5000);
    } finally {
      setIsExporting(false);
    }
  }

  async function handleQuickExport() {
    if (viewState.isProcessing) {
      showToast('Wait for processing to complete before exporting', 'warning', 3000);
      return;
    }
    if (!audioState.loaded) return;

    const noteStr = `${settings.targetNote}${settings.octave}`;

    async function doQuickExport(overwrite) {
      setIsExporting(true);
      try {
        const res = await fetch(`${API_BASE}/api/quick-export`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ target_note: noteStr, overwrite }),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({ detail: 'Unknown error' }));
          showToast(categorizeExportError(err.detail ?? 'Unknown error', t), 'error', 5000);
          return;
        }
        const data = await res.json();
        if (data.exists) {
          const fname = data.output_path.split(/[\\/]/).pop();
          showToast(
            `File exists: ${fname}. Overwrite?`,
            'warning',
            0,
            { label: 'Yes', onClick: () => doQuickExport(true) },
          );
          return;
        }
        const display = data.output_path.length > 55
          ? '...' + data.output_path.slice(-52)
          : data.output_path;
        showToast(`Quick exported to ${display}`, 'success', 4000);
      } catch (e) {
        showToast(categorizeExportError(e.message ?? '', t), 'error', 5000);
      } finally {
        setIsExporting(false);
      }
    }

    await doQuickExport(false);
  }

  function handleStartTrimPreview(ms) {
    if (ms == null || ms <= 0) {
      setStartTrimPreviewFrac(null);
      return;
    }
    const duration = audioState.durationSeconds;
    if (!duration || duration <= 0) return;
    const frac = (ms / 1000) / duration;
    setStartTrimPreviewFrac(Math.min(frac, 0.99));
  }

  async function handleApplyLoop() {
    if (viewState.isProcessing || !audioState.loaded) return;
    setIsExporting(true);
    try {
      const res = await fetch(`${API_BASE}/api/crossfade-loop`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ template_periods: 6, min_loop_periods: 10, crossfade_periods: 2 }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Unknown error' }));
        showToast(`Loop failed: ${err.detail}`, 'error', 4000);
        return;
      }
      const data = await res.json();
      if (data.loop_start == null) {
        showToast('Could not find a suitable loop region', 'warning', 4000);
        return;
      }
      const sr = 44100;
      const totalSamples = data.sample_count;
      const startFrac = data.loop_start / totalSamples;
      const endFrac   = data.loop_end   / totalSamples;
      const startSec  = data.loop_start / sr;
      const endSec    = data.loop_end   / sr;
      setLoopPoints({ startFrac, endFrac, startSec, endSec });
      showToast(
        `Loop points set: ${startSec.toFixed(3)}s\u2013${endSec.toFixed(3)}s`,
        'success',
        5000,
      );
    } catch (e) {
      showToast(`Loop failed: ${e.message}`, 'error', 4000);
    } finally {
      setIsExporting(false);
    }
  }

  function handleCeilingChange(idx, offset) {
    setSettings((s) => ({
      ...s,
      harmonic_ceiling_offsets_db: { ...s.harmonic_ceiling_offsets_db, [idx]: offset },
    }));
  }

  function handleCeilingReset() {
    setSettings((s) => ({ ...s, harmonic_ceiling_offsets_db: {} }));
  }

  // ── Waveform note drag ─────────────────────────────────────────────────
  // Dragging the blob updates both the visual lane AND the target note in
  // settings, which triggers debounced reprocessing just like SettingsPanel.
  const handleMidiNoteChange = useCallback((midi) => {
    noteChangeSourceRef.current = 'waveform'; // tag so useEffect skips animation
    setSelectedMidi(midi);
    const NOTE_SEMITONES = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'];
    const note   = NOTE_SEMITONES[midi % 12];
    const octave = Math.floor(midi / 12) - 1;
    setSettings((s) => ({ ...s, targetNote: note, octave }));
  }, []);

  // ── Splitter drag ──────────────────────────────────────────────────────
  const handleSplitterMouseDown = useCallback((e) => {
    e.preventDefault();
    const container = mainRef.current;
    if (!container) return;

    setSplitterDragging(true);
    document.body.style.cursor = 'row-resize';

    function onMove(ev) {
      const rect      = container.getBoundingClientRect();
      const available = rect.height - PLAYBACK_ROW_H - SPLITTER_H;
      if (available <= 0) return;
      const rawRatio = (ev.clientY - rect.top) / available;
      const minTop   = 150 / available;
      const minBot   = 120 / available;
      setSplitRatio(Math.max(minTop, Math.min(1 - minBot, rawRatio)));
    }

    function onUp() {
      setSplitterDragging(false);
      document.body.style.cursor = '';
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup',   onUp);
    }

    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup',   onUp);
  }, []);

  // ── Derived display values ─────────────────────────────────────────────
  const peaks        = viewState.showProcessed ? audioState.processedPeaks : audioState.originalPeaks;
  const displayPeaks = options.performance_mode ? downsamplePeaks(peaks, 1000) : peaks;
  const abMode       = viewState.showProcessed ? 'processed' : 'original';

  const sampleName = audioState.filePath ? basename(audioState.filePath) : null;
  const sampleMeta = audioState.sampleRate
    ? `${(audioState.sampleRate / 1000).toFixed(1)} kHz`
    : null;

  const displayPeakDb = viewState.showProcessed && audioState.processedPeakDb != null
    ? audioState.processedPeakDb
    : audioState.peakDb;
  const displayRmsDb  = viewState.showProcessed && audioState.processedRmsDb != null
    ? audioState.processedRmsDb
    : audioState.rmsDb;

  // Playback cursor fraction (0–1) — null when stopped
  const playbackFraction = audioIsPlaying && audioDuration > 0
    ? Math.min(1, playbackPosition / audioDuration)
    : null;

  // ── Render ─────────────────────────────────────────────────────────────
  // Backend error / startup check screens
  if (backendStatus === 'checking') {
    return (
      <div className="backend-status-screen"
        onDragEnter={handleAppDragEnter}
        onDragOver={handleAppDragOver}
        onDrop={handleAppDrop}
      >
        <span className="backend-status-screen__spinner" />
        <span className="backend-status-screen__text">
          {t('electron.toast.backend_starting')}
        </span>
      </div>
    );
  }

  if (backendStatus === 'error') {
    return (
      <div className="backend-status-screen backend-status-screen--error"
        onDragEnter={handleAppDragEnter}
        onDragOver={handleAppDragOver}
        onDrop={handleAppDrop}
      >
        <div className="backend-status-screen__icon">&#x26A0;</div>
        <div className="backend-status-screen__title">
          {t('electron.toast.backend_failed')}
        </div>
        <button
          className="backend-status-screen__retry"
          onClick={() => {
            setBackendStatus('checking');
            checkBackendHealth().then((ok) => { if (!ok) setBackendStatus('error'); });
          }}
          type="button"
        >
          {t('electron.toast.backend_retry')}
        </button>
      </div>
    );
  }

  return (
    <div
      className="app-root"
      onDragEnter={handleAppDragEnter}
      onDragOver={handleAppDragOver}
      onDragLeave={handleAppDragLeave}
      onDrop={handleAppDrop}
    >
      {draggingFile && (
        <div className="app-drop-overlay">
          <div className="app-drop-overlay-box">
            <span className="app-drop-overlay-icon">♪</span>
            <span className="app-drop-overlay-text">Drop audio file</span>
          </div>
        </div>
      )}

      <TitleBar
        sampleName={sampleName}
        sampleMeta={sampleMeta}
        peakDb={displayPeakDb}
        rmsDb={displayRmsDb}
        abMode={abMode}
        onABToggle={toggleAB}
        isPlaying={audioIsPlaying}
        onPlay={handlePlayToggle}
        onNewSample={handleNewSample}
        onRefreshSample={handleRefreshSample}
        audioLoaded={audioState.loaded}
        isProcessing={viewState.isProcessing}
        processingProgress={viewState.processingProgress}
        onOpenPreferences={() => setPrefsOpen(true)}
        onExport={handleExport}
        onQuickExport={handleQuickExport}
        onMultiSample={() => setMultiSampleOpen(true)}
      />

      <FileBar
        filePath={audioState.filePath}
        onFileLoad={handleFileLoad}
        loading={audioState.loading}
      />

      {/* ── 2 px progress bar ── */}
      <div className={`app-progress-bar${viewState.isProcessing ? ' app-progress-bar--active' : ''}`}>
        {viewState.isProcessing && (
          viewState.processingProgress > 0 && viewState.processingProgress < 100
            ? <div className="app-progress-fill" style={{ width: `${viewState.processingProgress}%` }} />
            : <div className="app-progress-fill app-progress-fill--indeterminate" />
        )}
      </div>

      <div className="app-body">
        <div className="app-main" ref={mainRef}>

          {/* Waveform pane */}
          <div
            className="app-pane"
            style={{
              flex: splitRatio,
              opacity: waveformFading ? 0 : 1,
              transition: options.performance_mode ? 'none' : 'opacity 100ms ease',
            }}
          >
            <ErrorBoundary label="WaveformDisplay">
            <WaveformDisplay
              peaks={displayPeaks}
              selectedMidi={selectedMidi}
              midiRange={midiRange}
              mode="chromatic"
              onMidiNoteChange={handleMidiNoteChange}
              onZoomChange={setMidiRange}
              vs={VS.waveform}
              playbackFraction={playbackFraction}
              isProcessing={viewState.isProcessing}
              processingProgress={viewState.processingProgress}
              revealPeaks={viewState.showProcessed ? revealPeaks : null}
              onRevealComplete={handleRevealComplete}
              animateToMidi={animateToMidi}
              onSlideComplete={handleSlideComplete}
              loopPoints={loopPoints}
              startTrimFrac={startTrimPreviewFrac}
            />
          </ErrorBoundary>
          </div>

          {/* Splitter */}
          <div
            className={`app-splitter${splitterDragging ? ' app-splitter--dragging' : ''}`}
            onMouseDown={handleSplitterMouseDown}
          />

          {/* Harmonic limiter pane */}
          <div className="app-pane" style={{ flex: 1 - splitRatio }}>
            <ErrorBoundary label="HarmonicLimiter">
            <HarmonicLimiter
              harmonicAnalysis={viewState.harmonicAnalysis}
              ceilingOffsets={settings.harmonic_ceiling_offsets_db}
              enabled={settings.harmonic_limiter_enabled}
              onCeilingChange={handleCeilingChange}
              onResetAll={handleCeilingReset}
              vs={VS.harmonic}
              performanceMode={options.performance_mode}
            />
          </ErrorBoundary>
          </div>

          {/* Playback row */}
          <div className="app-playback-row">
            <button
              className={`app-play-btn${audioIsPlaying ? ' app-play-btn--playing' : ''}`}
              onClick={handlePlayToggle}
              title={audioIsPlaying ? t('main.button.stop') : t('main.button.play')}
              type="button"
            >
              {audioIsPlaying ? '■' : '▶'}
            </button>

            <span className="app-playback-time">
              {formatTime(playbackPosition)} / {formatTime(audioDuration)}
            </span>

            {viewState.isProcessing && (
              <span className="app-processing-badge">{t('electron.waveform.processing')}</span>
            )}
          </div>
        </div>

        {/* Settings panel */}
        <SettingsPanel
          settings={settings}
          onSettingsChange={setSettings}
          detectedPitch={audioState.detectedPitch}
          audioLoaded={audioState.loaded}
          isProcessing={viewState.isProcessing || isExporting}
          performanceMode={options.performance_mode}
          onControlDragStart={handleControlDragStart}
          onControlRelease={handleControlRelease}
          vs={VS}
        />
      </div>

      {/* ── Preferences Dialog (modeless side panel) ── */}
      <ErrorBoundary label="ThemeEditor">
        <PreferencesDialog
          isOpen={prefsOpen}
          onClose={() => setPrefsOpen(false)}
          options={options}
          onOptionsChange={setOptions}
          showToast={showToast}
        />
      </ErrorBoundary>

      {/* ── Multi-Sample Export Dialog ── */}
      <MultiSampleDialog
        isOpen={multiSampleOpen}
        onClose={() => { setMultiSampleOpen(false); setStartTrimPreviewFrac(null); }}
        settings={settings}
        detectedPitch={audioState.detectedPitch}
        sourcePath={audioState.filePath}
        audioLoaded={audioState.loaded}
        onStartTrimPreview={handleStartTrimPreview}
      />
    </div>
  );
}

// ── Root ───────────────────────────────────────────────────────────────────
export default function App() {
  return (
    <ToastProvider>
      <AppInner />
    </ToastProvider>
  );
}
