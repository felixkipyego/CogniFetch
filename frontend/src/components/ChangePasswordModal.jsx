import { useState, useEffect, useRef } from 'react';
import { apiJSON } from '../api/client.js';

export default function ChangePasswordModal({ onClose }) {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);
  const [loading, setLoading] = useState(false);
  const firstRef = useRef(null);

  useEffect(() => {
    firstRef.current?.focus();
    function onKey(e) { if (e.key === 'Escape') onClose(); }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  async function handleSubmit(e) {
    e.preventDefault();
    setError('');
    if (next !== confirm) { setError('New passwords do not match.'); return; }
    if (next.length < 8)  { setError('New password must be at least 8 characters.'); return; }
    setLoading(true);
    try {
      await apiJSON('/auth/me/password', {
        method: 'PATCH',
        body: JSON.stringify({ current_password: current, new_password: next }),
      });
      setSuccess(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose} aria-modal="true" role="dialog">
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal__header">
          <h2 className="modal__title">Change password</h2>
          <button className="btn btn--icon" onClick={onClose} aria-label="Close">×</button>
        </div>

        {success ? (
          <div className="modal__body">
            <p className="modal__success">Password updated successfully.</p>
            <button className="btn btn--primary btn--full" onClick={onClose}>Done</button>
          </div>
        ) : (
          <form className="modal__body" onSubmit={handleSubmit}>
            {error && <div className="auth-error" role="alert">{error}</div>}

            <label className="field">
              <span className="field__label">Current password</span>
              <input
                ref={firstRef}
                type="password"
                className="field__input"
                value={current}
                onChange={e => setCurrent(e.target.value)}
                autoComplete="current-password"
                required
              />
            </label>

            <label className="field">
              <span className="field__label">New password</span>
              <input
                type="password"
                className="field__input"
                value={next}
                onChange={e => setNext(e.target.value)}
                autoComplete="new-password"
                required
              />
            </label>

            <label className="field">
              <span className="field__label">Confirm new password</span>
              <input
                type="password"
                className="field__input"
                value={confirm}
                onChange={e => setConfirm(e.target.value)}
                autoComplete="new-password"
                required
              />
            </label>

            <div className="modal__actions">
              <button type="submit" className="btn btn--primary" disabled={loading}>
                {loading ? 'Updating…' : 'Update password'}
              </button>
              <button type="button" className="btn btn--ghost" onClick={onClose}>
                Cancel
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
