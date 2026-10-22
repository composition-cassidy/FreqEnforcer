import { useEffect, useId, useRef, useState } from 'react';

const DWELL_MS = 700;

/**
 * Wraps a control and reveals its explanatory caption only after the pointer
 * rests on it for DWELL_MS, or while a keyboard focus (focus-visible) is
 * inside. The caption overlays whatever sits below, so nothing shifts.
 * It stays in the DOM for screen readers via aria-describedby on the group.
 */
export default function Dwell({ hint, children }) {
  const id = useId();
  const [show, setShow] = useState(false);
  const timer = useRef(null);
  const focused = useRef(false);

  const clear = () => { clearTimeout(timer.current); timer.current = null; };
  useEffect(() => clear, []);

  if (!hint) return children;
  return (
    <div
      className={`dwell${show ? ' dwell--show' : ''}`} role="group" aria-describedby={id}
      onPointerEnter={() => { clear(); timer.current = setTimeout(() => setShow(true), DWELL_MS); }}
      onPointerLeave={() => { clear(); if (!focused.current) setShow(false); }}
      onFocusCapture={(e) => { if (e.target.matches?.(':focus-visible')) { focused.current = true; clear(); setShow(true); } }}
      onBlurCapture={() => { focused.current = false; setShow(false); }}
    >
      {children}
      <div className="dwell__tip" id={id} role="tooltip">{hint}</div>
    </div>
  );
}
