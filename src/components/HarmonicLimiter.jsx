import { useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import i18n from '../i18n';
import { getCssVar, hexToRgba, onThemeChange } from '../utils/themeColors';
import './HarmonicLimiter.css';

const M = { top: 24, right: 50, bottom: 34, left: 44 };
const HIT_R = 10, RESET_H = 16;
const ALL_FREQ_TICKS = [50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000];

function freqToX(freq, plotW, fMin, fMax) {
  return plotW * Math.log(freq / fMin) / Math.log(fMax / fMin);
}
function dbToY(db, plotH, dMin, dMax) {
  return plotH * (dMax - db) / (dMax - dMin);
}
function formatFreq(f) { return f >= 1000 ? (f / 1000) + 'k' : String(f); }
function hexToRgb(hex) {
  const h = hex.replace('#', '').trim();
  if (h.length === 6) return [parseInt(h.slice(0,2),16), parseInt(h.slice(2,4),16), parseInt(h.slice(4,6),16)];
  return [51, 206, 214];
}
function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

// Compute axis ranges from harmonic data so the display auto-fits the content.
function computeRanges(harmonicAnalysis) {
  const preH = harmonicAnalysis?.pre?.harmonics;
  let freqMin = 20, freqMax = 22050, dbMin = -80, dbMax = 0;
  if (preH && preH.length > 0) {
    freqMin = Math.max(20, preH[0].frequency * 0.5);
    freqMax = Math.min(22050, preH[preH.length - 1].frequency * 1.3);
    const mags = preH.map(h => h.magnitude_db).filter(isFinite);
    if (mags.length > 0) {
      const hi = Math.max(...mags), lo = Math.min(...mags);
      dbMax = Math.ceil((hi + 10) / 10) * 10;
      dbMin = Math.floor((lo - 20) / 10) * 10;
    }
  }
  return { freqMin, freqMax, dbMin, dbMax };
}

export default function HarmonicLimiter({
  harmonicAnalysis = null, ceilingOffsets = {}, enabled = true,
  onCeilingChange, onResetAll, vs, performanceMode = false,
}) {
  useTranslation();

  const canvasRef  = useRef(null), drawRef = useRef(null), propsRef = useRef({});
  const hoverRef   = useRef(null), dragRef = useRef(null), resetBtnRef = useRef(null);
  const rangesRef  = useRef({ freqMin: 20, freqMax: 22050, dbMin: -80, dbMax: 0 });
  const glowMapRef = useRef({});
  const glowTargetRef = useRef({});
  const glowRafRef = useRef(null);

  propsRef.current = { harmonicAnalysis, ceilingOffsets, enabled, onCeilingChange, onResetAll, vs, performanceMode };

  function computeNodes(W, H) {
    const { harmonicAnalysis, ceilingOffsets } = propsRef.current;
    const harmonics = harmonicAnalysis?.pre?.harmonics;
    if (!harmonics) return [];
    const { freqMin, freqMax, dbMin, dbMax } = rangesRef.current;
    const plotW = W - M.left - M.right, plotH = H - M.top - M.bottom;
    return harmonics.map((h) => {
      const detectedDb  = h.magnitude_db ?? -40;
      const offset      = ceilingOffsets?.[h.index] ?? 0;
      const ceilingDb   = detectedDb + offset;
      return {
        index: h.index, frequency: h.frequency, detectedDb, ceilingDb,
        x: M.left + freqToX(clamp(h.frequency, freqMin, freqMax), plotW, freqMin, freqMax),
        y: M.top  + dbToY(clamp(ceilingDb, dbMin, dbMax), plotH, dbMin, dbMax),
        plotH, plotW,
      };
    });
  }

  drawRef.current = () => {
    const _drawStart = performance.now();
    const canvas = canvasRef.current;
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    const W = canvas.width / dpr, H = canvas.height / dpr;
    if (W <= 0 || H <= 0) return;
    const ctx = canvas.getContext('2d');
    ctx.setTransform(1,0,0,1,0,0);
    ctx.clearRect(0,0,canvas.width,canvas.height);
    ctx.setTransform(dpr,0,0,dpr,0,0);

    const { harmonicAnalysis, ceilingOffsets, enabled, performanceMode } = propsRef.current;
    const v = vs || {};
    const hv = !!vs;

    // Pre/post data
    const pre      = harmonicAnalysis?.pre  ?? null;
    const post     = harmonicAnalysis?.post ?? null;
    const preH     = pre?.harmonics            ?? null;
    const postSF   = post?.spectrum_freqs      ?? null;
    const postSM   = post?.spectrum_magnitudes ?? null;

    // Axis ranges
    const ranges = computeRanges(harmonicAnalysis);
    rangesRef.current = ranges;
    const { freqMin, freqMax, dbMin, dbMax } = ranges;
    const fToX = (f, pw) => freqToX(f, pw, freqMin, freqMax);
    const dToY = (d, ph) => dbToY(d, ph, dbMin, dbMax);

    // Freq ticks: standard set filtered to visible range
    const freqTicks = ALL_FREQ_TICKS.filter(f => f >= freqMin * 0.85 && f <= freqMax * 1.15);

    // dB ticks: 10 dB steps
    const dbRange = dbMax - dbMin;
    const dbStep  = dbRange > 120 ? 20 : 10;
    const dbTicks = [];
    for (let t = Math.floor(dbMax / dbStep) * dbStep; t >= dbMin; t -= dbStep) dbTicks.push(t);

    const plotW = W - M.left - M.right, plotH = H - M.top - M.bottom;

    // ── Colors ──────────────────────────────────────────────────────────────
    const accentHex  = v.spectrumColor        || getCssVar('--accent',            '#33CED6');
    const hsHex      = v.nodeDefaultGradStart || getCssVar('--harmonic-start',    '#33CED6');
    const heHex      = v.nodeDefaultGradEnd   || getCssVar('--harmonic-end',      '#4EDE83');
    const bgPanel    = getCssVar('--bg-panel', '#252525');
    const textDim    = v.axisLabelColor        || getCssVar('--text-dim',          '#606060');
    const harmGrid   = v.axisLineColor         || getCssVar('--harmonic-grid',     '#3a3a5a');
    const modifiedClrBase = v.nodeModifiedColor || getCssVar('--harmonic-modified','#ffb340');
    const [ar,ag,ab]    = hexToRgb(accentHex);
    const [hsr,hsg,hsb] = hexToRgb(hsHex);

    const NODE_R         = hv ? (v.nodeRadius          ?? 7)    : 6;
    const axisLW         = hv ? (v.axisLineWidth        ?? 0.5)  : 0.5;
    const axisLC         = hv ? (v.axisLineColor        ?? hexToRgba(harmGrid, 0.5)) : hexToRgba(harmGrid, 0.5);
    const axisLSz        = hv ? (v.axisLabelSize        ?? 10)   : 9;
    const postStrokeA    = hv ? (v.spectrumStrokeOpacity    ?? 0.70) : 0.70;
    const postStrokeW    = hv ? (v.spectrumStrokeWidth      ?? 1.5)  : 1.5;
    const stemW          = hv ? (v.stemWidth          ?? 1)    : 1;
    const stemA          = hv ? (v.stemOpacity        ?? 0.22)  : 0.22;
    const nodeGlow       = hv ? (v.nodeGlow  !== false)        : true;
    const nodeGlowBlur   = hv ? (v.nodeGlowBlur       ?? 8)    : 5;
    const nodeBW         = hv ? (v.nodeBorderWidth    ?? 1.5)  : 1;
    const labelSz        = hv ? (v.labelSize          ?? 9)    : 8;
    const labelClr       = v.labelColor || hsHex;
    const labelOffY      = hv ? (v.labelOffsetY       ?? -12)  : -2;
    const ceilGuideClr   = hv ? (v.ceilingGuideColor  ?? 'rgba(245,166,35,0.5)') : 'rgba(255,180,60,0.5)';
    const ceilGuideW     = hv ? (v.ceilingGuideWidth  ?? 1)    : 1;
    const disabledA      = hv ? (v.disabledOpacity    ?? 0.35) : 0.4;

    ctx.globalAlpha = enabled ? 1.0 : disabledA;
    ctx.fillStyle = bgPanel;
    ctx.fillRect(0, 0, W, H);

    // ── Plot clip ────────────────────────────────────────────────────────────
    ctx.save();
    ctx.beginPath(); ctx.rect(M.left, M.top, plotW, plotH); ctx.clip();

    // Grid — dB horizontals
    for (const db of dbTicks) {
      const y = M.top + dToY(db, plotH);
      ctx.strokeStyle = db === 0 ? 'rgba(255,255,255,0.12)' : axisLC;
      ctx.lineWidth = db === 0 ? 0.75 : axisLW;
      ctx.beginPath(); ctx.moveTo(M.left, y); ctx.lineTo(M.left + plotW, y); ctx.stroke();
    }
    // Grid — freq verticals
    for (const freq of freqTicks) {
      const x = M.left + fToX(freq, plotW);
      if (x < M.left || x > M.left + plotW) continue;
      ctx.strokeStyle = axisLC; ctx.lineWidth = axisLW;
      ctx.beginPath(); ctx.moveTo(x, M.top); ctx.lineTo(x, M.top + plotH); ctx.stroke();
    }

    // ── Spectrum curve (post-limiting; equals pre when no limiting applied) ──
    if (postSF && postSM && postSF.length > 0) {
      const strokePath = new Path2D();
      let started = false, firstX = M.left, lastX = M.left + plotW;
      for (let i = 0; i < postSF.length; i++) {
        const freq = postSF[i];
        if (freq < freqMin || freq > freqMax) continue;
        const x = M.left + fToX(freq, plotW);
        const y = M.top  + dToY(clamp(postSM[i], dbMin, dbMax), plotH);
        if (!started) { strokePath.moveTo(x, y); firstX = x; started = true; }
        else strokePath.lineTo(x, y);
        lastX = x;
      }
      if (started) {
        if (!performanceMode) {
          const fillPath = new Path2D(strokePath);
          fillPath.lineTo(lastX, M.top + plotH);
          fillPath.lineTo(firstX, M.top + plotH);
          fillPath.closePath();
          ctx.fillStyle = `rgba(${ar},${ag},${ab},0.08)`;
          ctx.fill(fillPath);
        }
        ctx.strokeStyle = `rgba(${ar},${ag},${ab},${postStrokeA})`;
        ctx.lineWidth = postStrokeW;
        ctx.stroke(strokePath);
      }
    }

    // ── Vertical stems from each ceiling node down to the baseline ──────────
    if (preH) {
      for (const h of preH) {
        if (h.frequency < freqMin || h.frequency > freqMax) continue;
        const x      = M.left + fToX(h.frequency, plotW);
        const offset = ceilingOffsets?.[h.index] ?? 0;
        const yTop   = M.top + dToY(clamp(h.magnitude_db + offset, dbMin, dbMax), plotH);
        ctx.strokeStyle = `rgba(${hsr},${hsg},${hsb},${stemA})`;
        ctx.lineWidth = stemW;
        ctx.beginPath(); ctx.moveTo(x, M.top + plotH); ctx.lineTo(x, yTop); ctx.stroke();
      }
    }

    ctx.restore(); // end clip

    // ── Axis border ──────────────────────────────────────────────────────────
    ctx.strokeStyle = hexToRgba(harmGrid, 0.8); ctx.lineWidth = 1;
    ctx.strokeRect(M.left, M.top, plotW, plotH);

    // ── Y labels ─────────────────────────────────────────────────────────────
    ctx.font = `${axisLSz}px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`;
    ctx.fillStyle = textDim; ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
    for (const db of dbTicks) {
      ctx.fillText(db === 0 ? '0' : String(db), M.left - 5, M.top + dToY(db, plotH));
    }
    // ── X labels ─────────────────────────────────────────────────────────────
    ctx.textAlign = 'center'; ctx.textBaseline = 'top';
    for (const freq of freqTicks) {
      const x = M.left + fToX(freq, plotW);
      if (x < M.left + 8 || x > M.left + plotW - 4) continue;
      ctx.fillText(formatFreq(freq), x, M.top + plotH + 5);
    }
    // ── Axis titles ───────────────────────────────────────────────────────────
    ctx.font = '8px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
    ctx.fillStyle = textDim; ctx.textAlign = 'center'; ctx.textBaseline = 'bottom';
    ctx.fillText(i18n.t('electron.harmonic.frequency_hz'), M.left + plotW / 2, H - 1);
    ctx.save(); ctx.translate(10, M.top + plotH / 2); ctx.rotate(-Math.PI / 2);
    ctx.textBaseline = 'middle'; ctx.fillText(i18n.t('electron.harmonic.level_db'), 0, 0); ctx.restore();

    // ── Reset button ──────────────────────────────────────────────────────────
    const resetW = 38, resetX = W - resetW - 2, resetY = 5;
    resetBtnRef.current = { x: resetX, y: resetY, w: resetW, h: RESET_H };
    ctx.font = '9px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
    ctx.fillStyle = `rgba(${ar},${ag},${ab},0.55)`;
    ctx.textAlign = 'right'; ctx.textBaseline = 'top';
    ctx.fillText(i18n.t('electron.harmonic.reset'), W - 4, resetY + 2);

    // ── Harmonic nodes ────────────────────────────────────────────────────────
    if (preH && preH.length > 0) {
      const nodes      = computeNodes(W, H);
      const dragging   = dragRef.current;
      const hoveredIdx = hoverRef.current;

      for (const node of nodes) {
        const { index, x, y, detectedDb, ceilingDb } = node;
        const offset     = ceilingOffsets?.[index] ?? 0;
        const isDragging = dragging?.index === index;
        const isLimiting = offset < -0.5;
        const cy         = clamp(y, M.top, M.top + plotH);

        // Drag guide line + live dB label
        if (isDragging) {
          ctx.save();
          ctx.strokeStyle = ceilGuideClr; ctx.lineWidth = ceilGuideW;
          ctx.setLineDash([4, 4]);
          ctx.beginPath(); ctx.moveTo(M.left, cy); ctx.lineTo(M.left + plotW, cy); ctx.stroke();
          ctx.setLineDash([]); ctx.restore();
          const labelDb = Math.round(ceilingDb * 10) / 10;
          ctx.font = '8px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
          ctx.fillStyle = 'rgba(255,200,120,0.9)';
          ctx.textAlign = 'left'; ctx.textBaseline = 'bottom';
          ctx.fillText(`${labelDb > 0 ? '+' : ''}${labelDb} dB`, M.left + plotW + 2, cy);
        }

        // Detected peak tick when ceiling is below it
        if (isLimiting) {
          const detY = M.top + dToY(clamp(detectedDb, dbMin, dbMax), plotH);
          ctx.strokeStyle = `rgba(${ar},${ag},${ab},0.35)`; ctx.lineWidth = 1;
          ctx.beginPath(); ctx.moveTo(x - 5, detY); ctx.lineTo(x + 5, detY); ctx.stroke();
        }

        // Glow halo
        const gi = isDragging ? 1 : (glowMapRef.current[index] ?? 0);
        if (gi > 0.01 && nodeGlow) {
          ctx.beginPath(); ctx.arc(x, cy, NODE_R + nodeGlowBlur, 0, Math.PI * 2);
          const glow = ctx.createRadialGradient(x, cy, 0, x, cy, NODE_R + nodeGlowBlur);
          glow.addColorStop(0, `rgba(${hsr},${hsg},${hsb},${0.3 * gi})`);
          glow.addColorStop(1, `rgba(${hsr},${hsg},${hsb},0)`);
          ctx.fillStyle = glow; ctx.fill();
        }

        // Node circle
        const r    = NODE_R + (isDragging ? 1.5 : gi * 1.5);
        const grad = ctx.createLinearGradient(x, cy - r, x, cy + r);
        if (isLimiting) {
          grad.addColorStop(0, modifiedClrBase);
          grad.addColorStop(1, darkenHex(modifiedClrBase, 0.65));
        } else {
          grad.addColorStop(0, hsHex); grad.addColorStop(1, heHex);
        }
        ctx.beginPath(); ctx.arc(x, cy, r, 0, Math.PI * 2);
        ctx.fillStyle = grad; ctx.fill();
        ctx.strokeStyle = isLimiting ? `${modifiedClrBase}bb` : `rgba(${hsr},${hsg},${hsb},0.7)`;
        ctx.lineWidth = nodeBW; ctx.stroke();

        // Harmonic label
        ctx.font = `${labelSz}px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`;
        ctx.fillStyle = isLimiting ? `${modifiedClrBase}ee` : labelClr;
        ctx.textAlign = 'center'; ctx.textBaseline = 'bottom';
        ctx.fillText(`H${index + 1}`, x, cy - r + labelOffY);
      }
    }

    // ── Empty / disabled overlays ─────────────────────────────────────────────
    if (!harmonicAnalysis?.pre) {
      ctx.fillStyle = hexToRgba(textDim, 0.6);
      ctx.font = '11px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText(i18n.t('electron.harmonic.empty'), M.left + plotW / 2, M.top + plotH / 2);
    }
    ctx.globalAlpha = 1;
    if (!enabled) {
      ctx.fillStyle = hexToRgba(textDim, 0.5);
      ctx.font = 'bold 12px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText(
        i18n.t('electron.harmonic.disabled'),
        M.left + plotW / 2,
        M.top  + plotH / 2 + (harmonicAnalysis?.pre ? 0 : 18),
      );
    }

    // ── Performance timing (only log if > 5ms) ───
    const _drawTime = performance.now() - _drawStart;
    if (_drawTime > 5) {
      console.log(`[HarmonicLimiter] draw: ${_drawTime.toFixed(1)} ms`);
    }
  };

  useEffect(() => () => { if (glowRafRef.current) cancelAnimationFrame(glowRafRef.current); }, []);
  useEffect(() => onThemeChange(() => drawRef.current?.()), []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) {
        const { width, height } = e.contentRect;
        const dpr = window.devicePixelRatio || 1;
        canvas.width  = Math.round(width  * dpr);
        canvas.height = Math.round(height * dpr);
        drawRef.current();
      }
    });
    ro.observe(canvas);
    return () => ro.disconnect();
  }, []);

  useEffect(() => { drawRef.current(); });

  function getLogicalXY(e) {
    const rect = canvasRef.current.getBoundingClientRect();
    return [e.clientX - rect.left, e.clientY - rect.top];
  }
  function getLogicalSize() {
    const c = canvasRef.current, dpr = window.devicePixelRatio || 1;
    return [c.width / dpr, c.height / dpr];
  }
  function hitTestNodes(lx, ly) {
    const [W, H] = getLogicalSize();
    const nodes = computeNodes(W, H);
    for (const node of nodes) {
      const dx = lx - node.x, dy = ly - node.y;
      if (Math.sqrt(dx * dx + dy * dy) <= HIT_R) return node;
    }
    return null;
  }

  function startGlowAnim() {
    if (glowRafRef.current) return;
    function tick() {
      let anyActive = false;
      const targets     = glowTargetRef.current;
      const intensities = glowMapRef.current;
      for (const key of Object.keys(targets)) {
        const idx    = Number(key);
        const target = targets[idx];
        const curr   = intensities[idx] ?? 0;
        const next   = curr + (target - curr) * 0.18;
        if (Math.abs(next - target) < 0.005) intensities[idx] = target;
        else { intensities[idx] = next; anyActive = true; }
      }
      drawRef.current();
      if (anyActive) glowRafRef.current = requestAnimationFrame(tick);
      else glowRafRef.current = null;
    }
    glowRafRef.current = requestAnimationFrame(tick);
  }

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    function onMouseMove(e) {
      const { enabled } = propsRef.current;
      const [lx, ly]    = getLogicalXY(e);
      if (dragRef.current) {
        const { index, detectedDb, startCeilingDb, startMouseY, plotH } = dragRef.current;
        const { dbMin, dbMax } = rangesRef.current;
        const deltaY       = ly - startMouseY;
        // Ceiling can only be lowered — cap at the detected magnitude (no boosting)
        const newCeilingDb = clamp(startCeilingDb - (dbMax - dbMin) * deltaY / plotH, dbMin, detectedDb);
        const newOffset    = newCeilingDb - detectedDb;
        dragRef.current.liveOffset    = newOffset;
        dragRef.current.liveCeilingDb = newCeilingDb;
        const prev = propsRef.current.ceilingOffsets;
        propsRef.current = { ...propsRef.current, ceilingOffsets: { ...prev, [index]: newOffset } };
        canvas.style.cursor = 'grabbing';
        drawRef.current();
        propsRef.current = { ...propsRef.current, ceilingOffsets: prev };
        return;
      }
      if (!enabled) return;
      const hit       = hitTestNodes(lx, ly);
      const prevHover = hoverRef.current;
      if (hit) {
        hoverRef.current = hit.index;
        canvas.style.cursor = 'ns-resize';
        if (prevHover !== hit.index) {
          if (prevHover !== null) glowTargetRef.current[prevHover] = 0;
          glowTargetRef.current[hit.index] = 1;
          if (!(hit.index in glowMapRef.current)) glowMapRef.current[hit.index] = 0;
          startGlowAnim();
        }
      } else {
        hoverRef.current = null;
        const btn = resetBtnRef.current;
        canvas.style.cursor = (btn && lx >= btn.x && lx <= btn.x + btn.w && ly >= btn.y && ly <= btn.y + btn.h)
          ? 'pointer' : '';
        if (prevHover !== null) { glowTargetRef.current[prevHover] = 0; startGlowAnim(); }
      }
      drawRef.current();
    }

    function onMouseDown(e) {
      if (e.button !== 0) return;
      const { enabled, onResetAll } = propsRef.current;
      const [lx, ly] = getLogicalXY(e);
      const btn = resetBtnRef.current;
      if (btn && lx >= btn.x && lx <= btn.x + btn.w && ly >= btn.y && ly <= btn.y + btn.h) {
        onResetAll?.(); return;
      }
      if (!enabled) return;
      const hit = hitTestNodes(lx, ly);
      if (!hit) return;
      const [, H] = getLogicalSize();
      dragRef.current = {
        index: hit.index, detectedDb: hit.detectedDb,
        startCeilingDb: hit.ceilingDb, startMouseY: ly,
        plotH: H - M.top - M.bottom,
      };
      canvas.style.cursor = 'grabbing';
      e.preventDefault();
    }

    function onMouseUp() {
      if (!dragRef.current) return;
      const { index, liveOffset }      = dragRef.current;
      const { onCeilingChange }        = propsRef.current;
      if (liveOffset !== undefined) onCeilingChange?.(index, Math.round(liveOffset * 10) / 10);
      dragRef.current = null; hoverRef.current = null;
      canvas.style.cursor = '';
      drawRef.current();
    }

    function onMouseLeave() {
      if (!dragRef.current) {
        const prevHover  = hoverRef.current;
        hoverRef.current = null;
        canvas.style.cursor = '';
        if (prevHover !== null) { glowTargetRef.current[prevHover] = 0; startGlowAnim(); }
        drawRef.current();
      }
    }

    canvas.addEventListener('mousedown',  onMouseDown);
    canvas.addEventListener('mousemove',  onMouseMove);
    canvas.addEventListener('mouseup',    onMouseUp);
    canvas.addEventListener('mouseleave', onMouseLeave);
    window.addEventListener('mouseup',    onMouseUp);
    return () => {
      canvas.removeEventListener('mousedown',  onMouseDown);
      canvas.removeEventListener('mousemove',  onMouseMove);
      canvas.removeEventListener('mouseup',    onMouseUp);
      canvas.removeEventListener('mouseleave', onMouseLeave);
      window.removeEventListener('mouseup',    onMouseUp);
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return <canvas ref={canvasRef} className="harmonic-canvas" />;
}

function darkenHex(hex, factor) {
  const h = hex.replace('#', '');
  if (h.length !== 6) return hex;
  const r = Math.round(parseInt(h.slice(0,2),16) * factor);
  const g = Math.round(parseInt(h.slice(2,4),16) * factor);
  const b = Math.round(parseInt(h.slice(4,6),16) * factor);
  return `rgb(${r},${g},${b})`;
}
