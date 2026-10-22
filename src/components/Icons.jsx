// Tiny inline SVG glyphs (12x12 viewBox, currentColor). No emoji, no icon font.

export const PlayIcon = () => <svg viewBox="0 0 12 12" aria-hidden="true"><path d="M2 1l9 5-9 5z" /></svg>;
export const StopIcon = () => <svg viewBox="0 0 12 12" aria-hidden="true"><rect x="2" y="2" width="8" height="8" /></svg>;
export const UndoIcon = () => (
  <svg viewBox="0 0 12 12" aria-hidden="true"><path d="M4 2L1 5l3 3V6h3.5a2 2 0 010 4H5v1h2.5a3 3 0 000-6H4z" /></svg>
);
export const RedoIcon = () => (
  <svg viewBox="0 0 12 12" aria-hidden="true"><path d="M8 2l3 3-3 3V6H4.5a2 2 0 000 4H7v1H4.5a3 3 0 010-6H8z" /></svg>
);
