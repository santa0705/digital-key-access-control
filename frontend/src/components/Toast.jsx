import { useEffect } from 'react';
import { CheckCircle2, AlertCircle, Info, X } from 'lucide-react';

export default function Toast({ message, type = 'success', onClose, duration = 4000 }) {
  useEffect(() => {
    if (duration > 0 && onClose) {
      const timer = setTimeout(onClose, duration);
      return () => clearTimeout(timer);
    }
  }, [duration, onClose]);

  if (!message) return null;

  const Icon =
    type === 'success'
      ? CheckCircle2
      : type === 'error'
      ? AlertCircle
      : Info;

  return (
    <div className={`toast-banner toast-${type}`} role="status" aria-live="polite">
      <div className="toast-icon">
        <Icon size={16} />
      </div>
      <div className="toast-message">{message}</div>
      {onClose && (
        <button
          type="button"
          onClick={onClose}
          className="toast-close"
          aria-label="Dismiss notification"
        >
          <X size={14} />
        </button>
      )}
    </div>
  );
}
