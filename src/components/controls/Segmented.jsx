/**
 * Radio-group style segmented control.
 * `options` = [{ value, label, title? }]. Arrow keys move the selection;
 * double-click resets to `defaultValue`.
 */
export default function Segmented({ value, defaultValue, options, onChange, ariaLabel, full = false, disabled = false }) {
  function onKey(e) {
    const i = options.findIndex((o) => o.value === value);
    if (i < 0) return;
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') { e.preventDefault(); onChange(options[(i + 1) % options.length].value); }
    if (e.key === 'ArrowLeft' || e.key === 'ArrowUp')    { e.preventDefault(); onChange(options[(i - 1 + options.length) % options.length].value); }
  }
  return (
    <div
      className={`seg${full ? ' seg--full' : ''}`} role="radiogroup" aria-label={ariaLabel}
      onKeyDown={onKey} onDoubleClick={() => defaultValue != null && onChange(defaultValue)}
    >
      {options.map((o) => (
        <button
          key={o.value} type="button" role="radio" aria-checked={o.value === value}
          tabIndex={o.value === value ? 0 : -1} title={o.title} disabled={disabled}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
