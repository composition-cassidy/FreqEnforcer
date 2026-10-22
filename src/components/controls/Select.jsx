import { useId } from 'react';

/**
 * Native select, restyled. `groups` = [{ label, options: [{ value, label }] }]
 * or pass flat `options`. Double-click resets to `defaultValue`.
 * With `label` it renders as a label · select row; without, full width.
 */
export default function Select({ label, value, defaultValue, options, groups, onChange, disabled, ariaLabel }) {
  const id = useId();
  const modified = defaultValue != null && value !== defaultValue;
  const select = (
    <select
      id={id} className="select" value={value} disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
      onDoubleClick={() => defaultValue != null && onChange(defaultValue)}
      aria-label={label ? undefined : ariaLabel}
    >
      {groups
        ? groups.map((g) => (
          <optgroup key={g.label} label={g.label}>
            {g.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </optgroup>
        ))
        : options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
  if (!label) return select;
  return (
    <div className={`row${modified ? ' row--modified' : ''}`}>
      <label className="row__label" htmlFor={id}>{label}</label>
      <div style={{ minWidth: 150 }}>{select}</div>
    </div>
  );
}
