// Canvas helpers shared by PitchView and HarmonicPane.
//
// A canvas is sized from its CSS box times devicePixelRatio and drawn in CSS
// pixels through setTransform, so every DPI scale (100 %, 150 %, 175 %, 200 %)
// gets crisp lines at the intended on-screen size.

import { useEffect } from 'react';

/** Resize the bitmap to match the CSS box; returns a ctx in CSS-pixel units. */
export function fitCanvas(canvas) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth, h = canvas.clientHeight;
  const W = Math.max(1, Math.round(w * dpr)), H = Math.max(1, Math.round(h * dpr));
  if (canvas.width !== W || canvas.height !== H) { canvas.width = W; canvas.height = H; }
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, w, h };
}

/** Read a design token from the element's computed style. */
export function token(el, name) {
  return getComputedStyle(el).getPropertyValue(name).trim();
}

/**
 * Re-run `draw` when the canvas box resizes, the DPR changes (window moved
 * to another monitor) or the theme attribute flips.
 */
export function useRedrawTriggers(canvasRef, draw) {
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    const ro = new ResizeObserver(() => draw());
    ro.observe(canvas);

    let mql = null;
    const watchDpr = () => {
      mql?.removeEventListener('change', onDpr);
      mql = window.matchMedia(`(resolution: ${window.devicePixelRatio}dppx)`);
      mql.addEventListener('change', onDpr);
    };
    const onDpr = () => { draw(); watchDpr(); };
    watchDpr();

    const mo = new MutationObserver(() => draw());
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });

    return () => { ro.disconnect(); mql?.removeEventListener('change', onDpr); mo.disconnect(); };
  }, [canvasRef, draw]);
}
