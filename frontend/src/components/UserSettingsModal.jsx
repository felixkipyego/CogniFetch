import { useState, useEffect, useRef } from 'react';
import { apiJSON } from '../api/client.js';

export function ChangePasswordForm() {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError('');
    setSuccess(false);
    if (next !== confirm) { setError('New passwords do not match.'); return; }
    if (next.length < 8)  { setError('New password must be at least 8 characters.'); return; }
    setLoading(true);
    try {
      await apiJSON('/auth/me/password', {
        method: 'PATCH',
        body: JSON.stringify({ current_password: current, new_password: next }),
      });
      setSuccess(true);
      setCurrent(''); setNext(''); setConfirm('');
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <form className="settings-section__form" onSubmit={handleSubmit}>
      {error   && <div className="auth-error"   role="alert">{error}</div>}
      {success && <div className="modal__success">Password updated successfully.</div>}

      <label className="field">
        <span className="field__label">Current password</span>
        <input type="password" className="field__input" value={current}
          onChange={e => setCurrent(e.target.value)} autoComplete="current-password" required />
      </label>

      <label className="field">
        <span className="field__label">New password</span>
        <input type="password" className="field__input" value={next}
          onChange={e => setNext(e.target.value)} autoComplete="new-password" required />
      </label>

      <label className="field">
        <span className="field__label">Confirm new password</span>
        <input type="password" className="field__input" value={confirm}
          onChange={e => setConfirm(e.target.value)} autoComplete="new-password" required />
      </label>

      <button type="submit" className="btn btn--primary" disabled={loading}>
        {loading ? 'Updating…' : 'Update password'}
      </button>
    </form>
  );
}

export default function UserSettingsModal({ onClose }) {
  const firstRef = useRef(null);

  useEffect(() => {
    firstRef.current?.focus();
    const onKey = e => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div className="modal-backdrop" onClick={onClose} aria-modal="true" role="dialog">
      <div className="modal modal--settings" onClick={e => e.stopPropagation()}>
        <div className="modal__header">
          <h2 className="modal__title">Profile settings</h2>
          <button ref={firstRef} className="btn btn--icon" onClick={onClose} aria-label="Close">×</button>
        </div>

        <div className="modal__body modal__body--settings">
          <section className="settings-section">
            <h3 className="settings-section__title">Security</h3>
            <ChangePasswordForm />
          </section>
        </div>
      </div>
    </div>
  );
}
