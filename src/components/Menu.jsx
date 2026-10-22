import { useEffect, useRef } from 'react';

/**
 * Dropdown menu anchored at `anchor` ({ x, y } in viewport px).
 * `items` = [{ id, label, shortcut?, disabled?, checked?, onSelect }] or { sep: true }.
 * Closes on outside click, Escape, or after a selection. Arrow keys move focus.
 */
export default function Menu({ anchor, items, onClose }) {
  const ref = useRef(null);

  useEffect(() => {
    const onDown = (e) => { if (!ref.current?.contains(e.target)) onClose(); };
    const onKey = (e) => {
      if (e.key === 'Escape') { onClose(); return; }
      if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
      e.preventDefault();
      const btns = [...ref.current.querySelectorAll('button:not(:disabled)')];
      const i = btns.indexOf(document.activeElement);
      const n = e.key === 'ArrowDown' ? (i + 1) % btns.length : (i - 1 + btns.length) % btns.length;
      btns[n]?.focus();
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    ref.current?.querySelector('button:not(:disabled)')?.focus();
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey); };
  }, [onClose]);

  return (
    <div ref={ref} className="menu" role="menu" style={{ left: anchor.x, top: anchor.y }}>
      {items.map((it, i) => it.sep
        ? <div key={`sep${i}`} className="sep" role="separator" />
        : (
          <button
            key={it.id} type="button" role={it.checked != null ? 'menuitemradio' : 'menuitem'}
            aria-checked={it.checked} disabled={it.disabled}
            onClick={() => { it.onSelect?.(); onClose(); }}
          >
            <span>{it.label}</span>
            {it.shortcut && <kbd>{it.shortcut}</kbd>}
          </button>
        ))}
    </div>
  );
}
