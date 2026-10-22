import { createContext, useCallback, useContext, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';

const ToastContext = createContext(null);

/**
 * showToast(message, type = 'info', duration = 4000, action = { label, onClick })
 * type: 'info' | 'success' | 'warning' | 'error'. duration 0 = sticky.
 */
export function ToastProvider({ children }) {
  const { t } = useTranslation();
  const [toasts, setToasts] = useState([]);
  const counter = useRef(0);

  const remove = useCallback((id) => setToasts((p) => p.filter((x) => x.id !== id)), []);
  const showToast = useCallback((message, type = 'info', duration = 4000, action = null) => {
    const id = ++counter.current;
    setToasts((p) => [...p.slice(-3), { id, message, type, action }]);
    if (duration > 0) setTimeout(() => remove(id), duration);
    return id;
  }, [remove]);

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      {createPortal(
        <div className="toasts" aria-live="polite">
          {toasts.map((x) => (
            <div key={x.id} className={`toast toast--${x.type}`} role="status">
              <span>{x.message}</span>
              {x.action && (
                <button type="button" className="btn" onClick={() => { x.action.onClick(); remove(x.id); }}>{x.action.label}</button>
              )}
              <button type="button" className="toast-x" onClick={() => remove(x.id)} aria-label={t('toast.dismiss')}>×</button>
            </div>
          ))}
        </div>,
        document.body,
      )}
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used inside <ToastProvider>');
  return ctx;
}
