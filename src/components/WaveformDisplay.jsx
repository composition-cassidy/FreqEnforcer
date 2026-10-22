import { useRef, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import i18n from '../i18n';
import { getCssVar, hexToRgba, onThemeChange } from '../utils/themeColors';
import './WaveformDisplay.css';

const NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
const BLACK_SEMITONES = new Set([1, 3, 6, 8, 10]);

function isBlack(midi) { return BLACK_SEMITONES.has(midi % 12); }
function isNatural(midi) { return !isBlack(midi); }
function midiToName(midi) {
  return NOTE_NAMES[midi % 12] + (Math.floor(midi / 12) - 1);
}
function hexToRgb(hex) {
  const h = hex.replace('#', '').trim();
  if (h.length === 6) return [parseInt(h.slice(0,2),16), parseInt(h.slice(2,4),16), parseInt(h.slice(4,6),16)];
  return [51, 206, 214];
}

export default function WaveformDisplay({
  peaks = null, selectedMidi = 60, midiRange = [48, 72], mode = '',
  onMidiNoteChange, onZoomChange, vs,
  playbackFraction = null,
  // Processing / reveal animation
  isProcessing = false,
  processingProgress = 0,
  revealPeaks = null,
  onRevealComplete,
  // Slide animation
  animateToMidi = null,
  onSlideComplete,
  // Loop points { startFrac, endFrac } — fractions 0.0–1.0 of total audio length
  loopPoints = null,
  // Start trim preview — fraction 0.0–1.0 (null = no marker)
  startTrimFrac = null,
}) {
  useTranslation(); // subscribe to language changes for re-render

  const canvasRef = useRef(null);
  const drawRef   = useRef(null);
  const propsRef  = useRef({});
  const dragRef   = useRef(null);

  // ── Animation state (all in refs to avoid 60fps re-renders) ────────────
  const animRef = useRef({
    // Reveal (drawing-out) animation
    revealActive: false,
    revealFraction: 0,
    revealStartTime: 0,
    revealOldPeaks: null,
    revealNewPeaks: null,
    pendingReveal: false,
    // Slide (note change) animation
    slideActive: false,
    slideFromMidi: 0,
    slideToMidi: 0,
    slideCurrentMidi: 0,
    slideStartTime: 0,
    slideCompletedMidi: null,  // persists target after slide ends until React catches up
    // Interaction lock (during slide animation)
    interactionLocked: false,
    // Processing overlay (delayed — appears after 300ms of processing)
    showProcessingOverlay: false,
  });
  const rafRef        = useRef(null);
  const pulseRafRef   = useRef(null);  // separate RAF for processing overlay pulse
  const overlayTimerRef = useRef(null);

  // Keep callbacks in refs so the animation loop always has fresh ones
  const onRevealCompleteRef = useRef(onRevealComplete);
  const onSlideCompleteRef  = useRef(onSlideComplete);
  const onZoomChangeRef     = useRef(onZoomChange);
  onRevealCompleteRef.current = onRevealComplete;
  onSlideCompleteRef.current  = onSlideComplete;
  onZoomChangeRef.current     = onZoomChange;

  propsRef.current = { peaks, selectedMidi, midiRange, mode, vs, playbackFraction, processingProgress, loopPoints, startTrimFrac };

  // ── Processing overlay pulse loop ──────────────────────────────────────
  function startPulseLoop() {
    if (pulseRafRef.current) return;
    const tick = () => {
      drawRef.current?.();
      if (animRef.current.showProcessingOverlay) {
        pulseRafRef.current = requestAnimationFrame(tick);
      } else {
        pulseRafRef.current = null;
      }
    };
    pulseRafRef.current = requestAnimationFrame(tick);
  }
  function stopPulseLoop() {
    if (pulseRafRef.current) {
      cancelAnimationFrame(pulseRafRef.current);
      pulseRafRef.current = null;
    }
  }

  // ── Shared animation loop ──────────────────────────────────────────────
  function startAnimLoop() {
    if (rafRef.current) return; // already running
    const tick = () => {
      const a = animRef.current;
      let running = false;

      // --- Reveal animation tick ---
      if (a.revealActive) {
        const t = Math.min((performance.now() - a.revealStartTime) / 800, 1);
        a.revealFraction = 1 - (1 - t) * (1 - t); // ease-out quadratic
        if (t >= 1) {
          a.revealActive = false;
          onRevealCompleteRef.current?.();
        } else {
          running = true;
        }
      }

      // --- Slide animation tick ---
      if (a.slideActive) {
        const t = Math.min((performance.now() - a.slideStartTime) / 350, 1);
        const eased = 1 - Math.pow(1 - t, 3); // ease-out cubic
        a.slideCurrentMidi = a.slideFromMidi + (a.slideToMidi - a.slideFromMidi) * eased;

        // Camera follow — re-centre if the sliding note is near the edge
        const { midiRange: mr } = propsRef.current;
        const [lo, hi] = mr;
        const margin = 2;
        if (a.slideCurrentMidi < lo + margin || a.slideCurrentMidi > hi - margin - 1) {
          const num = hi - lo;
          let nLo = Math.round(a.slideCurrentMidi - num / 2);
          if (nLo < 0) nLo = 0;
          if (nLo + num > 128) nLo = 128 - num;
          onZoomChangeRef.current?.([nLo, nLo + num]);
        }

        if (t >= 1) {
          a.slideActive = false;
          a.slideCompletedMidi = a.slideToMidi; // hold target until React updates selectedMidi
          a.interactionLocked = false;
          onSlideCompleteRef.current?.();
          // If reveal was waiting for slide to finish, start it now
          if (a.pendingReveal) {
            a.revealOldPeaks = propsRef.current.peaks;
            a.revealActive = true;
            a.revealFraction = 0;
            a.revealStartTime = performance.now();
            a.pendingReveal = false;
            running = true;
          }
        } else {
          running = true;
        }
      }

      drawRef.current();

      if (running) {
        rafRef.current = requestAnimationFrame(tick);
      } else {
        rafRef.current = null;
      }
    };
    rafRef.current = requestAnimationFrame(tick);
  }

  // ── Trigger reveal animation when revealPeaks arrives ──────────────────
  useEffect(() => {
    if (!revealPeaks) return;
    const a = animRef.current;
    if (a.slideActive) {
      // Slide is still running — queue the reveal for when it finishes
      a.revealNewPeaks = revealPeaks;
      a.pendingReveal = true;
      return;
    }
    // Start reveal immediately
    a.revealOldPeaks  = peaks; // snapshot current peaks
    a.revealNewPeaks  = revealPeaks;
    a.revealActive    = true;
    a.revealFraction  = 0;
    a.revealStartTime = performance.now();
    startAnimLoop();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [revealPeaks]);

  // ── Trigger slide animation when animateToMidi changes ─────────────────
  useEffect(() => {
    if (animateToMidi == null) {
      // React caught up — clear the completed-midi hold
      animRef.current.slideCompletedMidi = null;
      return;
    }
    const a = animRef.current;
    a.slideCompletedMidi = null; // new slide starting, clear any previous hold
    // If already sliding, pick up from current interpolated position
    a.slideFromMidi    = a.slideActive ? a.slideCurrentMidi : selectedMidi;
    a.slideToMidi      = animateToMidi;
    a.slideCurrentMidi = a.slideFromMidi;
    a.slideActive      = true;
    a.slideStartTime   = performance.now();
    a.interactionLocked = true;
    startAnimLoop();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [animateToMidi]);

  // ── Processing overlay: delayed show (300ms), immediate hide ───────────
  useEffect(() => {
    clearTimeout(overlayTimerRef.current);
    if (isProcessing) {
      // Only show overlay if processing takes longer than 300ms
      overlayTimerRef.current = setTimeout(() => {
        animRef.current.showProcessingOverlay = true;
        startPulseLoop();
      }, 300);
    } else {
      animRef.current.showProcessingOverlay = false;
      stopPulseLoop();
      drawRef.current?.();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isProcessing]);

  // ── Main draw function ─────────────────────────────────────────────────
  drawRef.current = (overrideMidi = null) => {
    const _drawStart = performance.now();
    const canvas = canvasRef.current;
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    const W = canvas.width / dpr, H = canvas.height / dpr;
    if (W <= 0 || H <= 0) return;
    const ctx = canvas.getContext('2d');
    ctx.setTransform(1,0,0,1,0,0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.setTransform(dpr,0,0,dpr,0,0);

    const v = vs || {};
    const hv = !!vs;
    const [lo, hi] = midiRange;
    const numNotes = hi - lo;
    if (numNotes <= 0) return;

    const a = animRef.current;

    const LABEL_W   = hv ? (v.noteLabelWidth ?? 40) : 36;
    const laneH     = H / numNotes;
    const waveW     = W - LABEL_W;

    // Determine the active MIDI note — may be fractional during slide animation
    let activeMidi;
    if (a.slideActive) {
      activeMidi = a.slideCurrentMidi;
    } else if (a.slideCompletedMidi != null) {
      // Slide just ended but React hasn't updated selectedMidi yet — hold position
      activeMidi = a.slideCompletedMidi;
    } else if (overrideMidi !== null) {
      activeMidi = overrideMidi;
    } else {
      activeMidi = selectedMidi;
    }
    const activeMidiInt = Math.round(activeMidi);

    // Colors — read from CSS variables so they respond to theme changes
    // Accent-derived colors: always read CSS var, allow vs override only if explicitly set
    const blobHex    = v.blobColor || getCssVar('--accent', '#33CED6');
    const [ar,ag,ab] = hexToRgb(blobHex);
    const wfWhite    = getCssVar('--wf-white-key', '#ffffff');
    const wfBlack    = getCssVar('--wf-black-key', '#000000');
    const wfGrid     = getCssVar('--wf-grid',      '#ffffff');
    const wfLabelClr = getCssVar('--wf-label',     '#a0a0b0');
    const whiteClr   = v.gridWhiteNoteColor || getCssVar('--wf-bg-white', '#1e1e36');
    const blackClr   = v.gridBlackNoteColor || getCssVar('--wf-bg-black', '#16162e');
    const gridClr    = v.gridLineColor || getCssVar('--wf-grid-line', 'rgba(60,60,90,0.4)');
    const gridLW     = hv ? (v.gridLineWidth ?? 0.5) : 0.5;
    const selHighlight = v.selectedLaneHighlight || `rgba(${ar},${ag},${ab},0.1)`;
    const labelSz    = hv ? (v.noteLabelSize ?? 10) : 9;
    const labelClr   = v.noteLabelColor || hexToRgba(wfLabelClr, 0.7);
    const showLabels  = hv ? (v.showNoteLabels !== false) : true;
    const blobFill   = hv ? (v.blobFillOpacity ?? 0.35) : 0.4;
    const blobStroke  = hv ? (v.blobStrokeOpacity ?? 0.8) : 0.8;
    const blobLW     = hv ? (v.blobStrokeWidth ?? 1.5) : 1;
    const modeSz     = hv ? (v.modeLabelSize ?? 11) : 9;
    const emptySz    = hv ? (v.emptyStateSize ?? 14) : 11;

    // ── MIDI grid ──────────────────────────────────────────────────────
    for (let n = lo; n < hi; n++) {
      const y = (hi - n - 1) * laneH;
      ctx.fillStyle = isBlack(n) ? blackClr : whiteClr;
      ctx.fillRect(LABEL_W, y, waveW, laneH);
      if (n === activeMidiInt) {
        ctx.fillStyle = selHighlight;
        ctx.fillRect(LABEL_W, y, waveW, laneH);
      }
      ctx.strokeStyle = gridClr;
      ctx.lineWidth   = gridLW;
      ctx.beginPath(); ctx.moveTo(LABEL_W, y); ctx.lineTo(W, y); ctx.stroke();
      if (showLabels && isNatural(n)) {
        const isActive = n === activeMidiInt;
        ctx.fillStyle = isActive ? `rgba(${ar},${ag},${ab},0.9)` : labelClr;
        ctx.font = `${isActive ? '600 ' : ''}${labelSz}px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`;
        ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
        ctx.fillText(midiToName(n), LABEL_W - 4, y + laneH / 2);
      }
    }
    ctx.strokeStyle = hexToRgba(wfGrid, 0.12); ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(LABEL_W, 0); ctx.lineTo(LABEL_W, H); ctx.stroke();

    // ── Blob drawing helper ────────────────────────────────────────────
    const ampScaleFactor = hv ? (v.blobAmpScale ?? 0.45) : 0.45;

    const drawBlobFromPeaks = (peaksData, midiNote, fo, so) => {
      if (!peaksData || peaksData.length === 0) return;
      const centerY = (hi - midiNote - 0.5) * laneH;
      const ampScale = laneH * ampScaleFactor;
      const n = peaksData.length;
      const path = new Path2D();
      path.moveTo(LABEL_W, centerY - peaksData[0][1] * ampScale);
      for (let i = 1; i < n; i++) {
        path.lineTo(LABEL_W + (i / (n - 1)) * waveW, centerY - peaksData[i][1] * ampScale);
      }
      for (let i = n - 1; i >= 0; i--) {
        path.lineTo(LABEL_W + (i / (n - 1)) * waveW, centerY - peaksData[i][0] * ampScale);
      }
      path.closePath();
      ctx.fillStyle   = `rgba(${ar},${ag},${ab},${fo})`;
      ctx.fill(path);
      ctx.strokeStyle = `rgba(${ar},${ag},${ab},${so})`;
      ctx.lineWidth   = blobLW;
      ctx.stroke(path);
    };

    // ── Blob rendering (with reveal animation support) ─────────────────
    // Dim waveform to 70% opacity when processing overlay is visible
    if (a.showProcessingOverlay) { ctx.save(); ctx.globalAlpha = 0.7; }

    const currentPeaks = peaks;
    if (a.revealActive && a.revealNewPeaks) {
      // Draw blob in two clipped halves — left = new, right = old
      const cursorX = LABEL_W + a.revealFraction * waveW;

      // Left half: new peaks
      ctx.save();
      ctx.beginPath();
      ctx.rect(LABEL_W, 0, cursorX - LABEL_W, H);
      ctx.clip();
      drawBlobFromPeaks(a.revealNewPeaks, activeMidi, blobFill, blobStroke);
      ctx.restore();

      // Right half: old peaks (or nothing if null)
      if (a.revealOldPeaks && a.revealOldPeaks.length > 0) {
        ctx.save();
        ctx.beginPath();
        ctx.rect(cursorX, 0, W - cursorX, H);
        ctx.clip();
        drawBlobFromPeaks(a.revealOldPeaks, activeMidi, blobFill * 0.5, blobStroke * 0.4);
        ctx.restore();
      }

      // White sweep cursor line with subtle glow
      ctx.save();
      ctx.shadowColor = 'rgba(255, 255, 255, 0.4)';
      ctx.shadowBlur  = 4;
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.9)';
      ctx.lineWidth   = 1.5;
      ctx.beginPath();
      ctx.moveTo(cursorX, 0);
      ctx.lineTo(cursorX, H);
      ctx.stroke();
      ctx.shadowBlur = 0;
      ctx.restore();

    } else if (currentPeaks && currentPeaks.length > 0) {
      // Normal blob drawing (no reveal animation)
      drawBlobFromPeaks(currentPeaks, activeMidi, blobFill, blobStroke);
    } else {
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillStyle = hexToRgba(wfLabelClr, 0.35);
      ctx.font = `${emptySz}px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`;
      ctx.fillText(i18n.t('electron.waveform.no_audio'), LABEL_W + waveW / 2, H / 2);
    }

    // Restore globalAlpha after dimmed blob section
    if (a.showProcessingOverlay) ctx.restore();

    // ── Mode label (bottom-right) ──────────────────────────────────────
    if (mode) {
      ctx.font = `${modeSz}px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`;
      ctx.fillStyle = hexToRgba(wfLabelClr, 0.45);
      ctx.textAlign = 'right'; ctx.textBaseline = 'bottom';
      ctx.fillText(mode.toUpperCase(), W - 8, H - 5);
    }

    // ── Processing overlay (appears after 300ms delay) ─────────────────
    if (a.showProcessingOverlay) {
      const pct = propsRef.current.processingProgress ?? 0;

      // Sweep line — only when progress is determinate
      if (pct > 0 && pct < 100) {
        const sweepX = LABEL_W + (pct / 100) * waveW;
        const pulseAlpha = 0.35 + 0.2 * Math.sin((performance.now() / 600) * Math.PI * 2);
        ctx.save();
        ctx.shadowColor = `rgba(${ar},${ag},${ab},0.5)`;
        ctx.shadowBlur  = 4;
        ctx.strokeStyle = `rgba(${ar},${ag},${ab},${pulseAlpha})`;
        ctx.lineWidth   = 1;
        ctx.beginPath();
        ctx.moveTo(sweepX, 0);
        ctx.lineTo(sweepX, H);
        ctx.stroke();
        ctx.restore();
      }

      // Centered "Processing..." text
      ctx.save();
      ctx.font = '12px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
      ctx.fillStyle = getCssVar('--text-dim', '#606060');
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(i18n.t('electron.waveform.processing'), LABEL_W + waveW / 2, H / 2);
      ctx.restore();
    }

    // ── Loop region markers ────────────────────────────────────────────
    const lp = propsRef.current.loopPoints;
    if (lp && lp.startFrac != null && lp.endFrac != null) {
      const lx = LABEL_W + lp.startFrac * waveW;
      const rx = LABEL_W + lp.endFrac   * waveW;

      // Filled region — accent at ~5% opacity
      ctx.save();
      ctx.fillStyle = `rgba(${ar},${ag},${ab},0.05)`;
      ctx.fillRect(lx, 0, rx - lx, H);

      // Vertical lines
      ctx.strokeStyle = `rgba(${ar},${ag},${ab},0.55)`;
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 3]);
      ctx.beginPath(); ctx.moveTo(lx, 0); ctx.lineTo(lx, H); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(rx, 0); ctx.lineTo(rx, H); ctx.stroke();
      ctx.setLineDash([]);

      // Labels "L" and "R" at the top
      ctx.font = '9px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
      ctx.fillStyle = `rgba(${ar},${ag},${ab},0.8)`;
      ctx.textBaseline = 'top';
      ctx.textAlign = 'left';
      ctx.fillText('L', lx + 2, 3);
      ctx.textAlign = 'right';
      ctx.fillText('R', rx - 2, 3);
      ctx.restore();
    }

    // ── Start trim preview marker ──────────────────────────────────────
    const stf = propsRef.current.startTrimFrac;
    if (stf != null && stf > 0 && stf < 1) {
      const tx = LABEL_W + stf * waveW;

      // Shaded region to the left = audio that will be cut
      ctx.save();
      ctx.fillStyle = 'rgba(255, 140, 0, 0.10)';
      ctx.fillRect(LABEL_W, 0, tx - LABEL_W, H);

      // Solid vertical line
      ctx.strokeStyle = 'rgba(255, 140, 0, 0.85)';
      ctx.lineWidth = 1.5;
      ctx.setLineDash([]);
      ctx.beginPath();
      ctx.moveTo(tx, 0);
      ctx.lineTo(tx, H);
      ctx.stroke();

      // "CUT" label just above the line
      ctx.font = '9px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
      ctx.fillStyle = 'rgba(255, 140, 0, 0.9)';
      ctx.textBaseline = 'top';
      ctx.textAlign = 'left';
      ctx.fillText('CUT', tx + 3, 3);
      ctx.restore();
    }

    // ── Playback cursor — drawn last so it sits on top of everything ───
    if (playbackFraction != null && playbackFraction >= 0 && playbackFraction <= 1) {
      const cursorX = LABEL_W + playbackFraction * waveW;
      ctx.save();
      ctx.strokeStyle = `rgba(${ar},${ag},${ab},0.9)`;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(cursorX, 0);
      ctx.lineTo(cursorX, H);
      ctx.stroke();
      ctx.restore();
    }

    // ── Performance timing (only log if > 5ms) ───
    const _drawTime = performance.now() - _drawStart;
    if (_drawTime > 5) {
      console.log(`[WaveformDisplay] draw: ${_drawTime.toFixed(1)} ms`);
    }
  };

  // ── Canvas resize ──────────────────────────────────────────────────────
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        const dpr = window.devicePixelRatio || 1;
        canvas.width = Math.round(width * dpr);
        canvas.height = Math.round(height * dpr);
        drawRef.current();
      }
    });
    observer.observe(canvas);
    return () => observer.disconnect();
  }, []);
  useEffect(() => { drawRef.current(); });

  // ── Cleanup rAF on unmount ─────────────────────────────────────────────
  useEffect(() => {
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      if (pulseRafRef.current) cancelAnimationFrame(pulseRafRef.current);
      clearTimeout(overlayTimerRef.current);
    };
  }, []);

  // ── Redraw when theme changes ──────────────────────────────────────────
  useEffect(() => onThemeChange(() => drawRef.current?.()), []);

  // ── Y-coordinate to MIDI conversion ────────────────────────────────────
  function yToMidi(y, canvasH) {
    const { midiRange: mr } = propsRef.current;
    const [lo, hi] = mr;
    const lH = canvasH / (hi - lo);
    return Math.max(lo, Math.min(hi - 1, Math.round(hi - 0.5 - y / lH)));
  }

  // ── Mouse handlers ─────────────────────────────────────────────────────
  const handleMouseDown = useCallback((e) => {
    if (animRef.current.interactionLocked) return;

    // Middle-click → pan
    if (e.button === 1) {
      e.preventDefault();
      const { midiRange: mr } = propsRef.current;
      dragRef.current = {
        active: true,
        type: 'pan',
        startY: e.clientY,
        startRange: [...mr],
      };
      document.body.style.cursor = 'grabbing';
      return;
    }

    // Left-click → select note
    if (e.button !== 0) return;
    const rect = canvasRef.current.getBoundingClientRect();
    const newMidi = yToMidi(e.clientY - rect.top, rect.height);
    dragRef.current = { active: true, type: 'select' };
    onMidiNoteChange?.(newMidi);
    drawRef.current(newMidi);
    e.preventDefault();
  }, [onMidiNoteChange]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleMouseMove = useCallback((e) => {
    if (!dragRef.current?.active) return;
    if (animRef.current.interactionLocked) return;

    // Pan mode
    if (dragRef.current.type === 'pan') {
      const rect = canvasRef.current.getBoundingClientRect();
      const { startY, startRange } = dragRef.current;
      const numNotes = startRange[1] - startRange[0];
      const lH = rect.height / numNotes;
      const deltaNotes = Math.round((e.clientY - startY) / lH);
      let newLo = startRange[0] + deltaNotes;
      let newHi = newLo + numNotes;
      if (newLo < 0) { newLo = 0; newHi = numNotes; }
      if (newHi > 128) { newHi = 128; newLo = 128 - numNotes; }
      onZoomChange?.([newLo, newHi]);
      return;
    }

    // Select mode
    const rect = canvasRef.current.getBoundingClientRect();
    const newMidi = yToMidi(e.clientY - rect.top, rect.height);
    const { selectedMidi: sm } = propsRef.current;
    if (newMidi !== sm) onMidiNoteChange?.(newMidi);
    drawRef.current(newMidi);
  }, [onMidiNoteChange, onZoomChange]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleMouseUp = useCallback(() => {
    if (dragRef.current?.active) {
      if (dragRef.current.type === 'pan') document.body.style.cursor = '';
      dragRef.current = null;
      drawRef.current();
    }
  }, []);

  const handleWheel = useCallback((e) => {
    if (animRef.current.interactionLocked) return;
    e.preventDefault();
    const { midiRange: mr, selectedMidi: sm } = propsRef.current;
    const [lo, hi] = mr;
    const num = hi - lo;
    const delta = e.deltaY > 0 ? 2 : -2;
    const newNum = Math.max(6, Math.min(48, num + delta));
    if (newNum === num) return;
    let newLo = Math.round(sm - newNum / 2);
    let newHi = newLo + newNum;
    if (newLo < 0) { newLo = 0; newHi = newNum; }
    if (newHi > 128) { newHi = 128; newLo = 128 - newNum; }
    onZoomChange?.([newLo, newHi]);
  }, [onZoomChange]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Event listener setup ───────────────────────────────────────────────
  useEffect(() => {
    const c = canvasRef.current;
    if (!c) return;
    c.addEventListener('wheel', handleWheel, { passive: false });
    return () => c.removeEventListener('wheel', handleWheel);
  }, [handleWheel]);

  useEffect(() => {
    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [handleMouseMove, handleMouseUp]);

  return (
    <canvas
      ref={canvasRef}
      className="waveform-canvas"
      onMouseDown={handleMouseDown}
      onAuxClick={(e) => e.preventDefault()}
    />
  );
}
