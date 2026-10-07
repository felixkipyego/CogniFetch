import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { apiFetch } from '../api/client.js';

export default function VerifyEmailPage() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token');

  const [status, setStatus] = useState('loading'); // 'loading' | 'success' | 'error'
  const [errorMsg, setErrorMsg] = useState('');

  useEffect(() => {
    if (!token) {
      setStatus('error');
      setErrorMsg('No verification token found. Please use the link from your email.');
      return;
    }

    apiFetch(`/auth/verify-email?token=${encodeURIComponent(token)}`, { skipRefresh: true })
      .then(res => {
        if (res.ok || res.status === 204) {
          setStatus('success');
        } else {
          return res.json().then(body => {
            setErrorMsg(body.detail ?? `Verification failed (${res.status}).`);
            setStatus('error');
          });
        }
      })
      .catch(() => {
        setErrorMsg('Could not connect to the server. Please try again.');
        setStatus('error');
      });
  }, [token]);

  return (
    <div className="auth-page">
      <div className="auth-card">
        <h1 className="auth-brand">CogniFetch</h1>

        {status === 'loading' && (
          <>
            <p className="auth-subtitle">Verifying your email…</p>
            <div className="spinner" role="status" aria-label="Loading" />
          </>
        )}

        {status === 'success' && (
          <>
            <p className="auth-subtitle">Email verified!</p>
            <div className="auth-notice">
              <p>Your account is now active. You can sign in.</p>
            </div>
            <Link to="/login" className="btn btn--primary btn--full">
              Sign in
            </Link>
          </>
        )}

        {status === 'error' && (
          <>
            <p className="auth-subtitle">Verification failed</p>
            <div className="auth-error" role="alert">{errorMsg}</div>
            <p className="auth-footer">
              <Link to="/register" className="auth-link">Back to register</Link>
              {' · '}
              <Link to="/login" className="auth-link">Sign in</Link>
            </p>
          </>
        )}
      </div>
    </div>
  );
}
