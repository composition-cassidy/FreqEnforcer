/** Checkbox with label; double-click resets to `defaultValue`. */
export default function Check({ label, checked, defaultValue, onChange, disabled = false }) {
  const modified = defaultValue != null && checked !== defaultValue;
  return (
    <label
      className={`check${modified ? ' check--modified' : ''}`}
      onDoubleClick={(e) => { e.preventDefault(); if (defaultValue != null) onChange(defaultValue); }}
    >
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}
