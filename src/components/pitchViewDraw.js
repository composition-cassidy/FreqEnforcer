// Pure drawing for PitchView. All coordinates are CSS pixels (ctx is DPR-scaled).
//
// Two layers: drawPitchView paints everything that only changes on a commit
// (grid, waveform, contours, loop); drawPlayhead paints the overlay canvas on
// every animation frame during playback, so playing never repaints the
// waveform.

import { hzToSemitones, isBlackKey } from '../utils/note_utils';

export const PAD_R = 44;   // pitch scale column
export const PAD_B = 18;   // time axis
export const HANDLE_HIT = 7;
const MIN_GAP = 6;         // grid lines never closer than this (px)

/** Geometry shared by draw and hit-testing. */
export function geometry(w, h, span) {
  const plotW = Math.max(1, w - PAD_R), plotH = Math.max(1, h - PAD_B);
  const mid = plotH / 2;
  const pxPerSt = (plotH * 0.46) / span;
  return { plotW, plotH, mid, pxPerSt, stToY: (st) => mid - st * pxPerSt, yToSt: (y) => (mid - y) / pxPerSt };
}

// Major (labelled) step and how many minor divisions it splits into.
const TIME_STEPS = [[0.05, 5], [0.1, 5], [0.25, 5], [0.5, 5], [1, 4], [2, 4], [5, 5], [10, 5], [30, 6]];
function timeStep(duration) {
  for (const s of TIME_STEPS) if (duration / s[0] <= 12) return s;
  return [60, 6];
}

function vline(ctx, x, h) {
  const px = Math.round(x) + 0.5;
  ctx.beginPath(); ctx.moveTo(px, 0); ctx.lineTo(px, h); ctx.stroke();
}
function hline(ctx, y, w) {
  const py = Math.round(y) + 0.5;
  ctx.beginPath(); ctx.moveTo(0, py); ctx.lineTo(w, py); ctx.stroke();
}

function drawCurve(ctx, contour, duration, g, color, width) {
  if (!contour?.times?.length || !duration) return;
  ctx.strokeStyle = color; ctx.lineWidth = width; ctx.lineJoin = 'round'; ctx.beginPath();
  let pen = false;
  const { times, st } = contour;
  for (let i = 0; i < times.length; i++) {
    const v = st[i];
    if (v == null || Math.abs(v) > g.span + 0.5) { pen = false; continue; }
    const x = (times[i] / duration) * g.plotW, y = g.stToY(v);
    if (pen) ctx.lineTo(x, y); else ctx.moveTo(x, y);
    pen = true;
  }
  ctx.stroke();
}

/** Precompute semitone offsets of a contour relative to targetHz. */
export function contourToSemitones(contour, targetHz) {
  if (!contour?.times?.length || !targetHz) return null;
  return { times: contour.times, st: contour.hz.map((hz) => (hz == null || hz <= 0 ? null : hzToSemitones(hz, targetHz))) };
}

export function drawPitchView(ctx, w, h, s, c) {
  // s: { peaks, duration, curveA, durationA, curveB, durationB, span, targetMidi,
  //      targetLabel, labelAt(st), loop, trimFrac }   c: colour tokens
  const g = { ...geometry(w, h, s.span), span: s.span };
  ctx.clearRect(0, 0, w, h);
  ctx.font = `10px ${c.mono}`;
  ctx.lineWidth = 1;

  // time grid: minor divisions (only when they stay MIN_GAP apart), then
  // labelled major lines
  if (s.duration > 0) {
    const [step, div] = timeStep(s.duration);
    const pxPerStep = (step / s.duration) * g.plotW;
    if (pxPerStep / div >= MIN_GAP) {
      ctx.strokeStyle = c.gridSub;
      const minor = step / div;
      for (let i = 1, t = minor; t < s.duration; i++, t = i * minor) {
        if (i % div) vline(ctx, (t / s.duration) * g.plotW, g.plotH);
      }
    }
    ctx.strokeStyle = c.gridMinor; ctx.fillStyle = c.fg3; ctx.textAlign = 'left';
    for (let t = 0; t <= s.duration + 1e-9; t += step) {
      const x = (t / s.duration) * g.plotW;
      vline(ctx, x, g.plotH);
      if (x < g.plotW - 30) ctx.fillText(t.toFixed(step < 1 ? 2 : 0), Math.round(x) + 3, h - 6);
    }
  }

  // loop region
  if (s.loop) {
    const x0 = s.loop.startFrac * g.plotW, x1 = s.loop.endFrac * g.plotW;
    ctx.fillStyle = c.bg1; ctx.fillRect(x0, 0, x1 - x0, g.plotH);
    ctx.strokeStyle = c.line2;
    vline(ctx, x0, g.plotH); vline(ctx, x1, g.plotH);
  }

  // waveform: peaks are [min, max] per bin (backend WAVEFORM_BINS)
  if (s.peaks?.length) {
    const n = s.peaks.length, amp = g.plotH * 0.42;
    ctx.fillStyle = s.isB ? c.waveB : c.wave; ctx.beginPath();
    for (let i = 0; i < n; i++) ctx.lineTo((i / (n - 1)) * g.plotW, g.mid - s.peaks[i][1] * amp);
    for (let i = n - 1; i >= 0; i--) ctx.lineTo((i / (n - 1)) * g.plotW, g.mid - s.peaks[i][0] * amp);
    ctx.closePath(); ctx.fill();
  }

  // semitone rows, piano-roll style: accidental rows shaded, natural notes
  // get a line, C (each octave) the strongest line, the target its own dash.
  // Labels thin out as rows get shorter: every row, then naturals, then Cs.
  const rowPx = g.pxPerSt;
  const labelEvery = rowPx >= 11 ? 'all' : rowPx >= 6 ? 'natural' : 'c';
  ctx.textAlign = 'right';
  for (let st = -s.span; st <= s.span; st++) {
    const pc = (((s.targetMidi + st) % 12) + 12) % 12;
    const black = isBlackKey(pc), y = g.stToY(st);
    if (black && rowPx >= 3) {
      ctx.fillStyle = c.rowBlack;
      ctx.fillRect(0, Math.round(y - rowPx / 2), g.plotW, Math.round(rowPx));
    }
    if (st === 0) continue; // drawn last, on top
    if (!black && (pc === 0 || rowPx >= MIN_GAP)) {
      ctx.strokeStyle = pc === 0 ? c.gridMajor : c.gridMinor;
      hline(ctx, y, g.plotW);
    }
    const show = labelEvery === 'all' || (labelEvery === 'natural' ? !black : pc === 0);
    if (show) {
      ctx.fillStyle = pc === 0 ? c.fg2 : c.fg3;
      ctx.fillText(s.labelAt(st), w - 6, Math.round(y) + 3);
    }
  }

  // start-trim marker
  if (s.trimFrac != null) {
    ctx.strokeStyle = c.fg2; ctx.setLineDash([3, 3]);
    vline(ctx, s.trimFrac * g.plotW, g.plotH); ctx.setLineDash([]);
  }

  // target line + handle
  const yT = g.stToY(0);
  ctx.strokeStyle = c.fg2; ctx.setLineDash([4, 3]);
  hline(ctx, yT, g.plotW); ctx.setLineDash([]);
  ctx.fillStyle = c.fg1; ctx.font = `600 10px ${c.mono}`;
  ctx.fillText(s.targetLabel, w - 6, Math.round(yT) + 3);
  ctx.fillStyle = c.accent;
  ctx.fillRect(g.plotW - 4, Math.round(yT) - 1, 4, 3);

  // pitch curves on top of everything
  drawCurve(ctx, s.curveA, s.durationA, g, c.curveOrig, 1.25);
  drawCurve(ctx, s.curveB, s.durationB, g, c.accent, 1.5);
}

/** Overlay layer: the playhead only. frac = null clears it. */
export function drawPlayhead(ctx, w, h, frac, color) {
  ctx.clearRect(0, 0, w, h);
  if (frac == null) return;
  const plotW = Math.max(1, w - PAD_R), plotH = Math.max(1, h - PAD_B);
  ctx.strokeStyle = color; ctx.lineWidth = 1;
  vline(ctx, Math.min(1, Math.max(0, frac)) * plotW, plotH);
}
