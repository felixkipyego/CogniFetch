import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { apiJSON, parseTokenPayload } from '../api/client.js';

const AuthCtx = createContext(null);

function readStoredAuth() {
  const token = localStorage.getItem('cf_access_token');
  if (!token) return { token: null, userId: null, isAdmin: false };
  const payload = parseTokenPayload(token);
  return { token, userId: payload.sub ?? null, isAdmin: payload.admin ?? false };
}

export function AuthProvider({ children }) {
  const [{ token, userId, isAdmin }, setAuth] = useState(readStoredAuth);

  const _setTokens = useCallback((access, refresh) => {
    localStorage.setItem('cf_access_token', access);
    if (refresh) localStorage.setItem('cf_refresh_token', refresh);
    const payload = parseTokenPayload(access);
    setAuth({ token: access, userId: payload.sub ?? null, isAdmin: payload.admin ?? false });
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem('cf_access_token');
    localStorage.removeItem('cf_refresh_token');
    setAuth({ token: null, userId: null, isAdmin: false });
  }, []);

  // Sync state when the API client silently refreshes the access token
  useEffect(() => {
    const handler = (e) => {
      const payload = parseTokenPayload(e.detail);
      setAuth(prev => ({ ...prev, token: e.detail, isAdmin: payload.admin ?? false }));
    };
    window.addEventListener('cf:token-refreshed', handler);
    return () => window.removeEventListener('cf:token-refreshed', handler);
  }, []);

  // The API client fires this when a refresh attempt fails
  useEffect(() => {
    const handler = () => logout();
    window.addEventListener('cf:logout', handler);
    return () => window.removeEventListener('cf:logout', handler);
  }, [logout]);

  const login = useCallback(async (email, password) => {
    const data = await apiJSON('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
      skipRefresh: true,
    });
    _setTokens(data.access_token, data.refresh_token);
  }, [_setTokens]);

  const register = useCallback(async (email, password) => {
    await apiJSON('/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
      skipRefresh: true,
    });
    await login(email, password);
  }, [login]);

  return (
    <AuthCtx.Provider value={{ token, userId, isAdmin, isAuthenticated: !!token, login, register, logout }}>
      {children}
    </AuthCtx.Provider>
  );
}

export const useAuth = () => useContext(AuthCtx);
