import { useEffect, useRef } from 'react';

/**
 * KeyboardEvent -> "ctrl+shift+e", "space", "a", "ctrl+arrowup", ...
 * Ctrl and Meta both map to "ctrl"; modifiers in the order ctrl, shift, alt.
 */
function shortcutKey(e) {
  const parts = [];
  if (e.ctrlKey || e.metaKey) parts.push('ctrl');
  if (e.shiftKey) parts.push('shift');
  if (e.altKey) parts.push('alt');
  parts.push(e.key === ' ' ? 'space' : e.key.toLowerCase());
  return parts.join('+');
}

const TEXT_INPUTS = new Set(['text', 'number', 'search', 'email', 'url', 'password', 'tel']);
const NATIVE_KEYS = new Set(['space', 'arrowup', 'arrowdown', 'arrowleft', 'arrowright', 'home', 'end', 'enter']);

/**
 * One global keydown listener dispatching to `handlers` (keys as above).
 * - text fields, textareas and selects swallow everything except Escape
 * - other controls (range, checkbox, button) keep their native keys
 *   (space, arrows, Enter) unless Ctrl is held
 */
export function useKeyboardShortcuts(handlers) {
  const ref = useRef(handlers);
  ref.current = handlers;

  useEffect(() => {
    function listener(e) {
      const el = e.target;
      const tag = el.tagName;
      const key = shortcutKey(e);
      if (key === 'escape') { ref.current.escape?.(); return; }
      const isText = tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable
        || (tag === 'INPUT' && TEXT_INPUTS.has(el.type || 'text'));
      if (isText) return;
      const isControl = tag === 'INPUT' || tag === 'BUTTON' || el.getAttribute?.('role') === 'radio';
      if (isControl && !key.startsWith('ctrl+') && NATIVE_KEYS.has(key)) return;
      const handler = ref.current[key];
      if (handler) { e.preventDefault(); handler(); }
    }
    window.addEventListener('keydown', listener);
    return () => window.removeEventListener('keydown', listener);
  }, []);
}
