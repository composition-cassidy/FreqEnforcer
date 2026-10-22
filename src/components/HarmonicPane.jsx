import { useCallback, useLayoutEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { fitCanvas, token, useRedrawTriggers } from '../utils/canvas';
import { clamp } from '../utils/note_utils';

const M = { l: 40, r: 16, t: 28, b: 22 };
const HIT = 9;

function ranges(pre) {
  const hs = pre?.harmonics ?? [];
  let fMin = 20, fMax = 22050, dMin = -80, dMax = 0;
  if (hs.length) {
    fMin = Math.max(20, hs[0].frequency * 0.5);
    fMax = Math.min(22050, hs[hs.length - 1].frequency * 1.3);
    const mags = hs.map((h) => h.magnitude_db).filter(Number.isFinite);
    if (mags.length) {
      dMax = Math.ceil((Math.max(...mags) + 10) / 10) * 10;
      dMin = Math.floor((Math.min(...mags) - 20) / 10) * 10;
    }
  }
  return { fMin, fMax, dMin, dMax };
}

function layout(w, h, pre) {
  const r = ranges(pre);
  const pw = Math.max(1, w - M.l - M.r), ph = Math.max(1, h - M.t - M.b);
  return {
    ...r, pw, ph,
    fx: (f) => M.l + (pw * Math.log(clamp(f, r.fMin, r.fMax) / r.fMin)) / Math.log(r.fMax / r.fMin),
    dy: (d) => M.t + (ph * (r.dMax - clamp(d, r.dMin, r.dMax))) / (r.dMax - r.dMin),
  };
}

function nodes(L, pre, offsets) {
  return (pre?.harmonics ?? []).map((h) => {
    const detected = h.magnitude_db ?? -40, offset = offsets?.[h.index] ?? 0;
    return { index: h.index, frequency: h.frequency, detected, offset, x: L.fx(h.frequency), y: L.dy(detected + offset) };
  });
}

/**
 * Harmonic ceiling editor. Nodes sit at each detected harmonic's level plus
 * its ceiling offset; drag a node down to lower its ceiling (never above the
 * detected level), double-click a node to reset it.
 */
export default function HarmonicPane({ analysis, offsets, onOffsetChange, onResetAll }) {
  const { t } = useTranslation();
  const canvasRef = useRef(null);
  const drag = useRef(null);
  const live = useRef(offsets);
  if (!drag.current) live.current = offsets;

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas || !canvas.clientWidth) return;
    const { ctx, w, h } = fitCanvas(canvas);
    const c = (n) => token(canvas, n);
    ctx.clearRect(0, 0, w, h);
    const pre = analysis?.pre, post = analysis?.post;
    const L = layout(w, h, pre);
    ctx.font = `10px ${c('--font-mono')}`; ctx.lineWidth = 1;

    ctx.strokeStyle = c('--line-1'); ctx.fillStyle = c('--fg-3');
    for (const f of [50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000]) {
      if (f < L.fMin || f > L.fMax) continue;
      const x = Math.round(L.fx(f)) + 0.5;
      ctx.beginPath(); ctx.moveTo(x, M.t); ctx.lineTo(x, M.t + L.ph); ctx.stroke();
      ctx.textAlign = 'center'; ctx.fillText(f >= 1000 ? `${f / 1000}k` : String(f), x, h - 8);
    }
    for (let d = L.dMax; d >= L.dMin; d -= 10) {
      const y = Math.round(L.dy(d)) + 0.5;
      ctx.beginPath(); ctx.moveTo(M.l, y); ctx.lineTo(M.l + L.pw, y); ctx.stroke();
      ctx.textAlign = 'right'; ctx.fillText(String(d), M.l - 6, y + 3);
    }
    if (!pre) {
      ctx.fillStyle = c('--fg-2'); ctx.textAlign = 'center';
      ctx.fillText(t('harm.empty'), M.l + L.pw / 2, M.t + L.ph / 2);
      return;
    }
    const spectrum = (branch, color) => {
      const f = branch?.spectrum_freqs, m = branch?.spectrum_magnitudes;
      if (!f?.length) return;
      ctx.strokeStyle = color; ctx.beginPath(); let pen = false;
      for (let i = 0; i < f.length; i++) {
        if (f[i] < L.fMin || f[i] > L.fMax) continue;
        const x = L.fx(f[i]), y = L.dy(m[i]);
        if (pen) ctx.lineTo(x, y); else ctx.moveTo(x, y);
        pen = true;
      }
      ctx.stroke();
    };
    spectrum(pre, c('--wave-b'));
    spectrum(post, c('--fg-2'));

    for (const n of nodes(L, pre, live.current)) {
      const modified = Math.abs(n.offset) > 0.05;
      ctx.strokeStyle = c('--line-2');
      ctx.beginPath(); ctx.moveTo(n.x, L.dy(n.detected)); ctx.lineTo(n.x, M.t + L.ph); ctx.stroke();
      ctx.fillStyle = modified ? c('--accent') : c('--fg-2');
      ctx.beginPath(); ctx.arc(n.x, n.y, 4, 0, Math.PI * 2); ctx.fill();
      if (modified) { ctx.fillStyle = c('--fg-1'); ctx.textAlign = 'center'; ctx.fillText(`${n.offset.toFixed(1)} dB`, n.x, n.y - 8); }
    }
  }, [analysis, t]);
  useRedrawTriggers(canvasRef, draw);
  useLayoutEffect(draw);

  function hit(e) {
    const canvas = canvasRef.current, r = canvas.getBoundingClientRect();
    const x = e.clientX - r.left, y = e.clientY - r.top;
    const L = layout(canvas.clientWidth, canvas.clientHeight, analysis?.pre);
    return { x, y, L, node: nodes(L, analysis?.pre, live.current).find((n) => Math.hypot(n.x - x, n.y - y) <= HIT) };
  }
  function onDown(e) {
    const { y, node, L } = hit(e);
    if (!node) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { index: node.index, detected: node.detected, start: node.offset, y0: y, L };
  }
  function onMove(e) {
    if (!drag.current) { e.currentTarget.style.cursor = hit(e).node ? 'ns-resize' : 'default'; return; }
    const { index, detected, start, y0, L } = drag.current;
    const y = e.clientY - e.currentTarget.getBoundingClientRect().top;
    const dbPerPx = (L.dMax - L.dMin) / L.ph;
    const offset = clamp(start - (y - y0) * dbPerPx, L.dMin - detected, 0);
    live.current = { ...live.current, [index]: offset };
    draw();
  }
  function onUp() {
    if (!drag.current) return;
    const { index } = drag.current; drag.current = null;
    onOffsetChange(index, live.current[index]);
  }
  function onDouble(e) {
    const { node } = hit(e);
    if (node) onOffsetChange(node.index, 0);
  }

  return (
    <div className="harm">
      <div className="harm__cap">
        <span>{t('harm.hint')}</span>
        <button type="button" className="btn" onClick={onResetAll} disabled={!Object.keys(offsets ?? {}).length}>{t('harm.reset_all')}</button>
      </div>
      <canvas
        ref={canvasRef} role="img" aria-label={t('harm.title')}
        onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp} onDoubleClick={onDouble}
      />
    </div>
  );
}
