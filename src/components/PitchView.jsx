import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { fitCanvas, token, useRedrawTriggers } from '../utils/canvas';
import { contourToSemitones, drawPitchView, drawPlayhead, geometry, HANDLE_HIT } from './pitchViewDraw';
import { midiToNote, noteNameToPC, pcName, toMidi } from '../utils/note_utils';

const SPANS = [3, 6, 12, 24];

/**
 * Waveform of the A or B side with both pitch contours overlaid on a
 * semitone scale centred on the target note.
 * - drag the target line (or its handle) vertically to change the target note
 * - click elsewhere to seek
 * - +/- change the visible semitone span
 * The playhead lives on its own overlay canvas, redrawn from the player's
 * frame callback (`subscribe`), so playback never re-renders this component
 * or repaints the waveform.
 */
export default function PitchView({
  audio, processed, abMode, target, notation, playing, subscribe, loop, trimFrac, busy,
  onTargetShift, onSeek,
}) {
  const { t } = useTranslation();
  const canvasRef = useRef(null);
  const overlayRef = useRef(null);
  const headColor = useRef('#fff');
  const playingRef = useRef(playing); playingRef.current = playing;
  const [span, setSpan] = useState(6);
  const drag = useRef(null);

  const isB = abMode === 'processed' && processed.peaks;
  const targetMidi = toMidi(target.octave, noteNameToPC(target.note) ?? 0);
  const targetHz = 440 * Math.pow(2, (targetMidi - 69) / 12);
  const targetLabel = `${pcName(targetMidi % 12, notation)}${target.octave}`;
  const labelAt = useCallback((st) => {
    const n = midiToNote(targetMidi + st);
    return `${pcName(noteNameToPC(n.note), notation)}${n.octave}`;
  }, [targetMidi, notation]);

  const curveA = useMemo(() => contourToSemitones(audio.contour, targetHz), [audio.contour, targetHz]);
  const curveB = useMemo(() => contourToSemitones(processed.contour, targetHz), [processed.contour, targetHz]);

  const state = useRef({});
  state.current = {
    peaks: isB ? processed.peaks : audio.peaks, isB,
    duration: isB ? processed.duration : audio.duration,
    curveA, durationA: audio.duration, curveB, durationB: processed.duration,
    span, targetMidi, targetLabel, labelAt, loop, trimFrac,
  };

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas || !canvas.clientWidth) return;
    const { ctx, w, h } = fitCanvas(canvas);
    const el = canvas;
    const c = {
      mono: token(el, '--font-mono'), bg1: token(el, '--bg-1'),
      line1: token(el, '--line-1'), line2: token(el, '--line-2'),
      fg1: token(el, '--fg-1'), fg2: token(el, '--fg-2'), fg3: token(el, '--fg-3'),
      wave: token(el, '--wave'), waveB: token(el, '--wave-b'),
      curveOrig: token(el, '--curve-orig'), accent: token(el, '--accent'),
      gridMajor: token(el, '--grid-major'), gridMinor: token(el, '--grid-minor'),
      gridSub: token(el, '--grid-sub'), rowBlack: token(el, '--row-black'),
    };
    headColor.current = c.fg1;
    drawPitchView(ctx, w, h, state.current, c);
  }, []);
  useRedrawTriggers(canvasRef, draw);
  useLayoutEffect(draw); // repaint after every commit (cheap, ~1 ms)

  // playhead overlay: one draw per animation frame while playing
  const audioLoadedRef = useRef(audio.loaded); audioLoadedRef.current = audio.loaded;
  const last = useRef({ pos: 0, dur: 0 });
  const head = useRef(null); // { ctx, w, h }, refitted only on resize / commit
  const drawHead = useCallback((refit = true) => {
    const canvas = overlayRef.current;
    if (!canvas) return;
    // Per-frame calls reuse the cached size: reading clientWidth every frame
    // would force a synchronous layout.
    if (refit || !head.current) {
      if (!canvas.clientWidth) return;
      head.current = fitCanvas(canvas);
    }
    const { ctx, w, h } = head.current;
    const { pos, dur } = last.current;
    const show = audioLoadedRef.current && dur > 0 && (playingRef.current || pos > 0);
    drawPlayhead(ctx, w, h, show ? pos / dur : null, headColor.current);
  }, []);
  useEffect(() => subscribe?.((pos, dur) => { last.current = { pos, dur }; drawHead(false); }), [subscribe, drawHead]);
  const refitHead = useCallback(() => drawHead(true), [drawHead]);
  useRedrawTriggers(overlayRef, refitHead);
  useEffect(refitHead, [playing, audio.loaded, refitHead]);

  function geo() { const c = canvasRef.current; return geometry(c.clientWidth, c.clientHeight, span); }
  function onPointerDown(e) {
    if (!audio.loaded) return;
    const r = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - r.left, y = e.clientY - r.top;
    const g = geo();
    const onLine = Math.abs(y - g.stToY(0)) <= HANDLE_HIT || x >= g.plotW;
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { mode: onLine ? 'target' : 'seek', y0: y, emitted: 0, moved: false, x };
  }
  function onPointerMove(e) {
    const r = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - r.left, y = e.clientY - r.top;
    const g = geo();
    if (!drag.current) {
      e.currentTarget.style.cursor = audio.loaded && (Math.abs(y - g.stToY(0)) <= HANDLE_HIT || x >= g.plotW) ? 'ns-resize' : 'default';
      return;
    }
    drag.current.moved = true;
    if (drag.current.mode === 'target') {
      const total = Math.round((drag.current.y0 - y) / g.pxPerSt);
      const delta = total - drag.current.emitted;
      if (delta) { drag.current.emitted = total; onTargetShift(delta); }
    }
  }
  function onPointerUp(e) {
    const d = drag.current; drag.current = null;
    if (!d) return;
    if (d.mode === 'seek') {
      const r = e.currentTarget.getBoundingClientRect();
      const g = geo();
      onSeek(Math.max(0, Math.min(1, (e.clientX - r.left) / g.plotW)));
    }
  }
  function zoom(dir) {
    const i = SPANS.indexOf(span);
    setSpan(SPANS[Math.max(0, Math.min(SPANS.length - 1, i + dir))]);
  }

  return (
    <>
      <div className="viewbar">
        <span className="viewbar__caption">{isB ? `B · ${t('view.corrected')}` : `A · ${t('view.original')}`}</span>
        <span className="legend">
          <span className="orig"><i />{t('view.original_pitch')}</span>
          <span className="corr"><i />{t('view.corrected_pitch')}</span>
        </span>
        <span className="viewbar__spacer" />
        {loop && <span>{t('view.loop')} <span className="mono">{loop.startSec.toFixed(3)} – {loop.endSec.toFixed(3)} s</span></span>}
        <span className="viewbar__zoom">
          <button type="button" aria-label={t('view.zoom_out')} onClick={() => zoom(1)} disabled={span === SPANS[SPANS.length - 1]}>−</button>
          <span className="mono">±{span} st</span>
          <button type="button" aria-label={t('view.zoom_in')} onClick={() => zoom(-1)} disabled={span === SPANS[0]}>+</button>
        </span>
      </div>
      <div className={`wave${busy ? ' wave--busy' : ''}`}>
        <canvas ref={canvasRef} aria-hidden="true" />
        <canvas
          ref={overlayRef} className="wave__overlay" role="img" aria-label={t('view.aria', { target: targetLabel })}
          onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={() => { drag.current = null; }}
          onWheel={(e) => { if (audio.loaded) zoom(e.deltaY > 0 ? 1 : -1); }}
        />
        {!audio.loaded && !audio.loading && (
          <div className="wave__empty">
            <span>{t('view.drop_hint')}</span>
            <span className="dim">{t('view.open_hint')} <kbd>Ctrl+O</kbd> · {t('view.formats')}</span>
          </div>
        )}
      </div>
    </>
  );
}
