import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { createPortal } from 'react-dom';
import './MultiSampleDialog.css';

import { API_BASE } from '../config/api';

const NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
const OCTAVES = [-1, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9];
const BLACK_INDICES = new Set([1, 3, 6, 8, 10]); // C#, D#, F#, G#, A#

function noteToMidi(note, octave) {
  const idx = NOTE_NAMES.indexOf(note);
  if (idx < 0) return 60;
  return (octave + 1) * 12 + idx;
}

function midiToNote(midi) {
  const clamped = Math.max(0, Math.min(127, midi));
  return { note: NOTE_NAMES[clamped % 12], octave: Math.floor(clamped / 12) - 1 };
}

function noteLabel(note, octave) {
  return `${note}${octave}`;
}

// ─────────────────────────────────────────────────────────────────────────────
// Visual Piano Range — thin 128-key strip showing selected range
// ─────────────────────────────────────────────────────────────────────────────

function PianoRange({ lowMidi, highMidi, sourceMidi }) {
  const keys = useMemo(() => {
    const arr = [];
    for (let m = 0; m < 128; m++) {
      const isBlack = BLACK_INDICES.has(m % 12);
      const inRange = m >= lowMidi && m <= highMidi;
      const isSource = m === sourceMidi;
      let cls = 'msd-piano-key';
      if (isSource) cls += ' msd-piano-key--source';
      else if (inRange) cls += ' msd-piano-key--in-range';
      else cls += isBlack ? ' msd-piano-key--black' : ' msd-piano-key--white';
      arr.push(<div key={m} className={cls} title={noteLabel(NOTE_NAMES[m % 12], Math.floor(m / 12) - 1)} />);
    }
    return arr;
  }, [lowMidi, highMidi, sourceMidi]);

  return <div className="msd-piano-range">{keys}</div>;
}

// ─────────────────────────────────────────────────────────────────────────────
// MultiSampleDialog
// ─────────────────────────────────────────────────────────────────────────────

export default function MultiSampleDialog({
  isOpen,
  onClose,
  settings,
  detectedPitch,
  sourcePath,
  audioLoaded,
  onStartTrimPreview,
}) {
  // ── Derive source MIDI from detected pitch ─────────────────────────────
  const sourceMidi = useMemo(() => {
    if (!detectedPitch?.note_name) return 60;
    const match = detectedPitch.note_name.match(/^([A-G]#?)(-?\d+)$/);
    if (!match) return 60;
    return noteToMidi(match[1], parseInt(match[2], 10));
  }, [detectedPitch]);

  // ── Note range state (default: 2 octaves below/above source) ───────────
  const defaultLow = useMemo(() => midiToNote(Math.max(0, sourceMidi - 24)), [sourceMidi]);
  const defaultHigh = useMemo(() => midiToNote(Math.min(127, sourceMidi + 24)), [sourceMidi]);

  const [lowNote, setLowNote] = useState(defaultLow.note);
  const [lowOctave, setLowOctave] = useState(defaultLow.octave);
  const [highNote, setHighNote] = useState(defaultHigh.note);
  const [highOctave, setHighOctave] = useState(defaultHigh.octave);

  // Reset defaults when source changes
  useEffect(() => {
    const lo = midiToNote(Math.max(0, sourceMidi - 24));
    const hi = midiToNote(Math.min(127, sourceMidi + 24));
    setLowNote(lo.note);
    setLowOctave(lo.octave);
    setHighNote(hi.note);
    setHighOctave(hi.octave);
  }, [sourceMidi]);

  // ── Options ────────────────────────────────────────────────────────────
  const [enableLoop, setEnableLoop] = useState(true);
  const [templatePeriods, setTemplatePeriods] = useState(6);
  const [startTrimEnabled, setStartTrimEnabled] = useState(false);
  const [startTrimMs, setStartTrimMs] = useState(0);
  const [generateSfz, setGenerateSfz] = useState(true);
  const [outputDir, setOutputDir] = useState('');

  // Notify parent of start trim preview (null = clear marker)
  useEffect(() => {
    if (!isOpen) {
      onStartTrimPreview?.(null);
      return;
    }
    onStartTrimPreview?.(startTrimEnabled ? startTrimMs : null);
  }, [isOpen, startTrimEnabled, startTrimMs, onStartTrimPreview]);

  // Auto-generate output dir from source path
  useEffect(() => {
    if (sourcePath) {
      const lastDot = sourcePath.lastIndexOf('.');
      const base = lastDot > 0 ? sourcePath.substring(0, lastDot) : sourcePath;
      setOutputDir(base);
    }
  }, [sourcePath]);

  // ── Rendering state ────────────────────────────────────────────────────
  const [status, setStatus] = useState('idle'); // idle | rendering | complete | error | cancelled
  const [progress, setProgress] = useState(0);
  const [currentNote, setCurrentNote] = useState('');
  const [notesDone, setNotesDone] = useState(0);
  const [notesTotal, setNotesTotal] = useState(0);
  const [resultInfo, setResultInfo] = useState(null);
  const [errorMsg, setErrorMsg] = useState('');
  const abortRef = useRef(null);

  // ── Computed values ────────────────────────────────────────────────────
  const lowMidi = noteToMidi(lowNote, lowOctave);
  const highMidi = noteToMidi(highNote, highOctave);
  const totalNotes = Math.max(0, highMidi - lowMidi + 1);
  const rangeValid = lowMidi <= highMidi && lowMidi >= 0 && highMidi <= 127;

  const sourceNoteName = detectedPitch?.note_name || '?';

  // ── Close guard ────────────────────────────────────────────────────────
  const handleClose = useCallback(() => {
    if (status === 'rendering') return; // don't close during render
    setStatus('idle');
    setProgress(0);
    setResultInfo(null);
    setErrorMsg('');
    onClose();
  }, [status, onClose]);

  // Escape key
  useEffect(() => {
    if (!isOpen) return;
    function onKey(e) {
      if (e.key === 'Escape' && status !== 'rendering') handleClose();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [isOpen, status, handleClose]);

  // ── Change folder ──────────────────────────────────────────────────────
  async function handleChangeFolder() {
    try {
      const result = await window.electronAPI?.openDirectoryDialog({
        title: 'Choose output folder',
        defaultPath: outputDir,
      });
      if (result) setOutputDir(result);
    } catch {
      // Fallback: no-op
    }
  }

  // ── Render ─────────────────────────────────────────────────────────────
  async function handleRender() {
    if (!audioLoaded || !rangeValid || status === 'rendering') return;

    setStatus('rendering');
    setProgress(0);
    setNotesDone(0);
    setNotesTotal(totalNotes);
    setCurrentNote('');
    setResultInfo(null);
    setErrorMsg('');

    const controller = new AbortController();
    abortRef.current = controller;

    const body = {
      low_note: noteLabel(lowNote, lowOctave),
      high_note: noteLabel(highNote, highOctave),
      enable_loop: enableLoop,
      template_periods: templatePeriods,
      start_trim_ms: startTrimEnabled ? startTrimMs : 0.0,
      generate_sfz: generateSfz,
      output_dir: outputDir || null,
      // Forward all current processing settings
      ...settings,
    };

    try {
      const res = await fetch(`${API_BASE}/api/render-multisample`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: controller.signal,
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        let detail = err.detail;
        if (Array.isArray(detail)) {
          detail = detail.map((e) => {
            const loc = (e.loc || []).slice(1).join(' → ');
            return loc ? `${loc}: ${e.msg}` : (e.msg || String(e));
          }).join('; ');
        }
        throw new Error(detail || `HTTP ${res.status}`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const parts = buffer.split('\n\n');
        buffer = parts.pop();

        for (const part of parts) {
          const trimmed = part.trim();
          if (!trimmed || trimmed.startsWith(':')) continue; // keepalive
          if (!trimmed.startsWith('data: ')) continue;
          try {
            const data = JSON.parse(trimmed.slice(6));
            if (data.progress != null) {
              setProgress(Math.round(data.progress * 100));
              setCurrentNote(data.current_note || '');
              setNotesDone(data.notes_done ?? 0);
              setNotesTotal(data.notes_total ?? totalNotes);
            }
            if (data.complete) {
              setStatus('complete');
              setProgress(100);
              setResultInfo(data);
            }
            if (data.error) {
              setStatus('error');
              setErrorMsg(data.error);
            }
            if (data.cancelled) {
              setStatus('cancelled');
            }
          } catch {
            // ignore parse errors
          }
        }
      }

      // If we finished reading without a terminal event
      if (status === 'rendering') {
        setStatus('complete');
        setProgress(100);
      }
    } catch (err) {
      if (err.name === 'AbortError') {
        setStatus('cancelled');
      } else {
        setStatus('error');
        setErrorMsg(err.message || 'Render failed');
      }
    } finally {
      abortRef.current = null;
    }
  }

  // ── Cancel ─────────────────────────────────────────────────────────────
  function handleCancel() {
    if (status === 'rendering' && abortRef.current) {
      abortRef.current.abort();
    } else {
      handleClose();
    }
  }

  // ── Render ─────────────────────────────────────────────────────────────
  if (!isOpen) return null;

  const isRendering = status === 'rendering';
  const showProgress = status !== 'idle';

  return createPortal(
    <div className="msd-backdrop" onMouseDown={isRendering ? undefined : handleClose}>
      <div className="msd-dialog" onMouseDown={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="msd-header">
          <span className="msd-title">Multi-Sample Export</span>
          <button
            className="msd-close"
            onClick={handleClose}
            disabled={isRendering}
            type="button"
          >
            ×
          </button>
        </div>

        {/* Body */}
        <div className="msd-body">
          {/* Note Range */}
          <div>
            <div className="msd-range-label">Note Range</div>
            <div className="msd-range-row">
              <select className="msd-select" value={lowNote} onChange={(e) => setLowNote(e.target.value)} disabled={isRendering}>
                {NOTE_NAMES.map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
              <select className="msd-select" value={lowOctave} onChange={(e) => setLowOctave(Number(e.target.value))} disabled={isRendering}>
                {OCTAVES.map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
              <span>to</span>
              <select className="msd-select" value={highNote} onChange={(e) => setHighNote(e.target.value)} disabled={isRendering}>
                {NOTE_NAMES.map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
              <select className="msd-select" value={highOctave} onChange={(e) => setHighOctave(Number(e.target.value))} disabled={isRendering}>
                {OCTAVES.map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
            </div>
          </div>

          {/* Visual Piano Range */}
          <PianoRange lowMidi={lowMidi} highMidi={highMidi} sourceMidi={sourceMidi} />

          {/* Info line */}
          <div className="msd-info">
            Source: <span className="msd-info-note">{sourceNoteName}</span> (detected)
            {rangeValid && <> — {totalNotes} note{totalNotes !== 1 ? 's' : ''} to render</>}
            {!rangeValid && <> — <span style={{ color: 'var(--color-error)' }}>invalid range</span></>}
          </div>

          {/* Options */}
          <div className="msd-option">
            <input type="checkbox" id="msd-loop" checked={enableLoop} onChange={(e) => setEnableLoop(e.target.checked)} disabled={isRendering} />
            <label htmlFor="msd-loop">Enable Crossfade Loop</label>
          </div>
          {enableLoop && (
            <div className="msd-slider-row">
              <input type="range" min={2} max={16} step={1} value={templatePeriods} onChange={(e) => setTemplatePeriods(Number(e.target.value))} disabled={isRendering} />
              <span className="msd-slider-val">{templatePeriods} period template</span>
            </div>
          )}

          <div className="msd-option">
            <input
              type="checkbox"
              id="msd-start-trim"
              checked={startTrimEnabled}
              onChange={(e) => setStartTrimEnabled(e.target.checked)}
              disabled={isRendering}
            />
            <label htmlFor="msd-start-trim">Start Trim Offset</label>
          </div>
          {startTrimEnabled && (
            <div className="msd-slider-row">
              <input
                type="range"
                min={0}
                max={500}
                step={1}
                value={startTrimMs}
                onChange={(e) => setStartTrimMs(Number(e.target.value))}
                disabled={isRendering}
              />
              <input
                type="number"
                className="msd-trim-input"
                min={0}
                max={500}
                step={1}
                value={startTrimMs}
                onChange={(e) => setStartTrimMs(Math.max(0, Math.min(500, Number(e.target.value) || 0)))}
                disabled={isRendering}
              />
              <span className="msd-slider-val">ms</span>
            </div>
          )}

          <div className="msd-option">
            <input type="checkbox" id="msd-sfz" checked={generateSfz} onChange={(e) => setGenerateSfz(e.target.checked)} disabled={isRendering} />
            <label htmlFor="msd-sfz">Generate SFZ Instrument (.sfz)</label>
          </div>

          {/* Output folder */}
          <div>
            <div className="msd-output-label">Output</div>
            <div className="msd-output-path">{outputDir || '(auto)'}</div>
            <button className="msd-change-folder" onClick={handleChangeFolder} disabled={isRendering} type="button">
              Change Folder…
            </button>
          </div>

          {/* Progress */}
          {showProgress && (
            <div className="msd-progress">
              {isRendering && (
                <>
                  <div className="msd-progress-text">
                    Rendering {currentNote}… ({notesDone}/{notesTotal})
                  </div>
                  <div className="msd-progress-bar">
                    <div className="msd-progress-fill" style={{ width: `${progress}%` }} />
                  </div>
                  <div className="msd-progress-pct">{progress}%</div>
                </>
              )}
              {status === 'complete' && (
                <div className="msd-complete">
                  Rendered {resultInfo?.notes_rendered ?? totalNotes} notes to {resultInfo?.output_dir || outputDir}
                </div>
              )}
              {status === 'error' && (
                <div className="msd-error">Error: {errorMsg}</div>
              )}
              {status === 'cancelled' && (
                <div className="msd-error">Cancelled</div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="msd-footer">
          <button className="msd-btn msd-btn--cancel" onClick={handleCancel} type="button">
            {isRendering ? 'Cancel' : 'Close'}
          </button>
          {status !== 'complete' && (
            <button
              className="msd-btn msd-btn--render"
              onClick={handleRender}
              disabled={isRendering || !audioLoaded || !rangeValid}
              type="button"
            >
              {isRendering ? 'Rendering…' : 'Render'}
            </button>
          )}
        </div>
      </div>
    </div>,
    document.body
  );
}
