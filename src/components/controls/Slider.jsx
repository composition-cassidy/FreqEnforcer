import { useEffect, useId, useRef, useState } from 'react';
import { clamp } from '../../utils/note_utils';

/**
 * Label · tabular value · native range.
 * - value box is click-to-edit (Enter commits, Esc cancels, blur commits)
 * - double-click anywhere resets to `defaultValue`
 * - keyboard: arrows step, Home/End jump (native range behaviour)
 * - onDragStart / onDragEnd let the app pause reprocessing during a drag
 * - `snap` (value) + `snapZone`: pull the thumb onto a value when near it
 */
export default function Slider({
  label, value, min, max, step = 1, defaultValue, format, parse,
  onChange, onDragStart, onDragEnd, hint, disabled = false, snap, snapZone = 0,
}) {
  const id = useId();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState('');
  const inputRef = useRef(null);
  const dragging = useRef(false);

  useEffect(() => { if (editing) { inputRef.current?.focus(); inputRef.current?.select(); } }, [editing]);

  const modified = defaultValue != null && Math.abs(value - defaultValue) > 1e-9;
  const display = format ? format(value) : String(value);

  function commitText() {
    const raw = parse ? parse(text) : parseFloat(text);
    if (Number.isFinite(raw)) onChange(clamp(raw, min, max));
    setEditing(false);
  }
  function reset() { if (defaultValue != null) onChange(defaultValue); }
  function handleRange(e) {
    let v = Number(e.target.value);
    if (snap != null && snapZone > 0 && Math.abs(v - snap) <= snapZone) v = snap;
    onChange(v);
  }
  function startDrag() { if (!dragging.current) { dragging.current = true; onDragStart?.(); } }
  function endDrag() { if (dragging.current) { dragging.current = false; onDragEnd?.(); } }

  return (
    <div className={`ctl${modified ? ' ctl--modified' : ''}${disabled ? ' ctl--disabled' : ''}`} onDoubleClick={reset}>
      <label className="ctl__label" htmlFor={id}>{label}</label>
      {editing ? (
        <input
          ref={inputRef} className="ctl__value" value={text}
          onChange={(e) => setText(e.target.value)}
          onBlur={commitText}
          onKeyDown={(e) => { if (e.key === 'Enter') commitText(); else if (e.key === 'Escape') setEditing(false); e.stopPropagation(); }}
          onDoubleClick={(e) => e.stopPropagation()}
          aria-label={label}
        />
      ) : (
        <button
          type="button" className="ctl__value" tabIndex={-1}
          onClick={() => { setText(String(value)); setEditing(true); }}
          onDoubleClick={(e) => e.stopPropagation()}
          title={label}
        >
          {display}
        </button>
      )}
      <input
        id={id} type="range" className="ctl__range"
        min={min} max={max} step={step} value={value}
        onChange={handleRange}
        onPointerDown={startDrag} onPointerUp={endDrag} onPointerCancel={endDrag}
        onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur(); }}
        onBlur={endDrag}
        disabled={disabled}
        aria-valuetext={display}
      />
      {hint && <div className="ctl__hint">{hint}</div>}
    </div>
  );
}
