// Pure drawing for PitchView. All coordinates are CSS pixels (ctx is DPR-scaled).

import { hzToSemitones } from '../utils/note_utils';

export const PAD_R = 44;   // pitch scale column
export const PAD_B = 18;   // time axis
export const HANDLE_HIT = 7;

/** Geometry shared by draw and hit-testing. */
export function geometry(w, h, span) {
  const plotW = Math.max(1, w - PAD_R), plotH = Math.max(1, h - PAD_B);
  const mid = plotH / 2;
  const pxPerSt = (plotH * 0.46) / span;
  return { plotW, plotH, mid, pxPerSt, stToY: (st) => mid - st * pxPerSt, yToSt: (y) => (mid - y) / pxPerSt };
}

function timeStep(duration) {
  for (const s of [0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30]) if (duration / s <= 12) return s;
  return 60;
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
  // s: { peaks, duration, curveA, durationA, curveB, durationB, span, targetLabel,
  //      labelAt(st), loop, trimFrac, playhead }   c: colour tokens
  const g = { ...geometry(w, h, s.span), span: s.span };
  ctx.clearRect(0, 0, w, h);
  ctx.font = `10px ${c.mono}`;

  // time grid + axis labels
  ctx.lineWidth = 1; ctx.strokeStyle = c.line1; ctx.fillStyle = c.fg3; ctx.textAlign = 'left';
  if (s.duration > 0) {
    const step = timeStep(s.duration);
    for (let t = 0; t <= s.duration + 1e-9; t += step) {
      const x = Math.round((t / s.duration) * g.plotW) + 0.5;
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, g.plotH); ctx.stroke();
      if (x < g.plotW - 30) ctx.fillText(t.toFixed(step < 1 ? 2 : 0), x + 3, h - 6);
    }
  }

  // loop region
  if (s.loop) {
    const x0 = s.loop.startFrac * g.plotW, x1 = s.loop.endFrac * g.plotW;
    ctx.fillStyle = c.bg1; ctx.fillRect(x0, 0, x1 - x0, g.plotH);
    ctx.strokeStyle = c.line2;
    for (const x of [x0, x1]) { ctx.beginPath(); ctx.moveTo(Math.round(x) + 0.5, 0); ctx.lineTo(Math.round(x) + 0.5, g.plotH); ctx.stroke(); }
  }
  // start-trim marker
  if (s.trimFrac != null) {
    const x = Math.round(s.trimFrac * g.plotW) + 0.5;
    ctx.strokeStyle = c.fg2; ctx.setLineDash([3, 3]);
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, g.plotH); ctx.stroke(); ctx.setLineDash([]);
  }

  // waveform: peaks are [min, max] per bin (backend WAVEFORM_BINS)
  if (s.peaks?.length) {
    const n = s.peaks.length, amp = g.plotH * 0.42;
    ctx.fillStyle = s.isB ? c.waveB : c.wave; ctx.beginPath();
    for (let i = 0; i < n; i++) ctx.lineTo((i / (n - 1)) * g.plotW, g.mid - s.peaks[i][1] * amp);
    for (let i = n - 1; i >= 0; i--) ctx.lineTo((i / (n - 1)) * g.plotW, g.mid - s.peaks[i][0] * amp);
    ctx.closePath(); ctx.fill();
  }

  // semitone scale (right column)
  const every = s.span <= 6 ? 1 : s.span <= 12 ? 2 : 4;
  ctx.textAlign = 'right';
  for (let st = -s.span; st <= s.span; st += every) {
    const y = Math.round(g.stToY(st)) + 0.5;
    ctx.strokeStyle = st === 0 ? c.fg3 : c.line1;
    ctx.setLineDash(st === 0 ? [4, 3] : []);
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(g.plotW, y); ctx.stroke(); ctx.setLineDash([]);
    ctx.fillStyle = st === 0 ? c.fg1 : c.fg3;
    ctx.fillText(st === 0 ? s.targetLabel : s.labelAt(st), w - 6, y + 3);
  }

  // pitch curves
  drawCurve(ctx, s.curveA, s.durationA, g, c.curveOrig, 1.25);
  drawCurve(ctx, s.curveB, s.durationB, g, c.accent, 1.5);

  // target handle
  ctx.fillStyle = c.accent;
  ctx.fillRect(g.plotW - 4, Math.round(g.stToY(0)) - 1, 4, 3);

  // playhead
  if (s.playhead != null) {
    const x = Math.round(s.playhead * g.plotW) + 0.5;
    ctx.strokeStyle = c.fg1; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, g.plotH); ctx.stroke();
  }
}
