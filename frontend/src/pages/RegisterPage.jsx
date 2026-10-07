import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext.jsx';
import { apiJSON } from '../api/client.js';

export default function RegisterPage() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [verificationSent, setVerificationSent] = useState(false);
  const [resendLoading, setResendLoading] = useState(false);
  const [resendMessage, setResendMessage] = useState('');

  async function handleSubmit(e) {
    e.preventDefault();
    setError('');
    if (password !== confirm) {
      setError('Passwords do not match.');
      return;
    }
    setLoading(true);
    try {
      const needsVerification = await register(email, password);
      if (needsVerification) {
        setVerificationSent(true);
      } else {
        navigate('/');
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleResend() {
    setResendLoading(true);
    setResendMessage('');
    try {
      await apiJSON('/auth/resend-verification', {
        method: 'POST',
        body: JSON.stringify({ email }),
        skipRefresh: true,
      });
      setResendMessage('Email resent! Check your inbox and spam folder.');
    } catch {
      setResendMessage('Could not resend. Please try again in a moment.');
    } finally {
      setResendLoading(false);
    }
  }

  if (verificationSent) {
    return (
      <div className="auth-page">
        <div className="auth-card">
          <h1 className="auth-brand">CogniFetch</h1>
          <p className="auth-subtitle">Check your email</p>

          <div className="auth-notice">
            <p>
              We sent a verification link to <strong>{email}</strong>.
              Click the link in that email to activate your account.
            </p>
            <p className="auth-notice__hint">
              Don't see it? Check your <strong>spam or junk folder</strong> — verification
              emails sometimes end up there.
            </p>
          </div>

          {resendMessage && (
            <div className="auth-info" role="status">{resendMessage}</div>
          )}

          <button
            className="btn btn--secondary btn--full"
            onClick={handleResend}
            disabled={resendLoading}
          >
            {resendLoading ? 'Sending…' : 'Resend verification email'}
          </button>

          <p className="auth-footer">
            Already verified?{' '}
            <Link to="/login" className="auth-link">Sign in</Link>
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <h1 className="auth-brand">CogniFetch</h1>
        <p className="auth-subtitle">Create an account</p>

        <form onSubmit={handleSubmit} className="auth-form" noValidate>
          {error && <div className="auth-error" role="alert">{error}</div>}

          <label className="field">
            <span className="field__label">Email</span>
            <input
              type="email"
              className="field__input"
              value={email}
              onChange={e => setEmail(e.target.value)}
              autoComplete="email"
              required
              autoFocus
            />
          </label>

          <label className="field">
            <span className="field__label">Password</span>
            <input
              type="password"
              className="field__input"
              value={password}
              onChange={e => setPassword(e.target.value)}
              autoComplete="new-password"
              required
            />
          </label>

          <label className="field">
            <span className="field__label">Confirm password</span>
            <input
              type="password"
              className="field__input"
              value={confirm}
              onChange={e => setConfirm(e.target.value)}
              autoComplete="new-password"
              required
            />
          </label>

          <button type="submit" className="btn btn--primary btn--full" disabled={loading}>
            {loading ? 'Creating account…' : 'Create account'}
          </button>
        </form>

        <p className="auth-footer">
          Already have an account?{' '}
          <Link to="/login" className="auth-link">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
