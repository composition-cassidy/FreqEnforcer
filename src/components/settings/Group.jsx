import { useId, useState } from 'react';

/**
 * Titled settings section. With `collapsible` the header is a button that
 * toggles the body (Enter/Space work natively). `right` renders in mono at
 * the far end of the header (shortcut hint, badge).
 */
export default function Group({ title, right, collapsible = false, defaultOpen = true, disabled = false, children }) {
  const [open, setOpen] = useState(defaultOpen);
  const id = useId();
  const cls = ['group', collapsible && 'group--collapsible', open && 'group--open', disabled && 'group--disabled'].filter(Boolean).join(' ');
  return (
    <section className={cls} aria-labelledby={id}>
      {collapsible ? (
        <button type="button" className="group__head" id={id} aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          {title}{right != null && <span className="r">{right}</span>}
        </button>
      ) : (
        <div className="group__head" id={id}>{title}{right != null && <span className="r">{right}</span>}</div>
      )}
      {(!collapsible || open) && <div className="group__body">{children}</div>}
    </section>
  );
}
