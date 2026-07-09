const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

// Deduplicate concurrent refresh attempts
let _refreshPromise = null;

async function _doRefresh() {
  const rt = localStorage.getItem('cf_refresh_token');
  if (!rt) throw new Error('No refresh token');
  const res = await fetch(`${API_BASE}/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: rt }),
  });
  if (!res.ok) throw new Error('Token refresh failed');
  const { access_token } = await res.json();
  localStorage.setItem('cf_access_token', access_token);
  window.dispatchEvent(new CustomEvent('cf:token-refreshed', { detail: access_token }));
  return access_token;
}

function _refresh() {
  if (!_refreshPromise) {
    _refreshPromise = _doRefresh().finally(() => {
      _refreshPromise = null;
    });
  }
  return _refreshPromise;
}

export async function apiFetch(path, options = {}) {
  const { skipRefresh, ...fetchOptions } = options;
  const token = localStorage.getItem('cf_access_token');
  const isFormData = fetchOptions.body instanceof FormData;

  const headers = {
    ...(!isFormData && fetchOptions.body ? { 'Content-Type': 'application/json' } : {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...fetchOptions.headers,
  };

  let res = await fetch(`${API_BASE}${path}`, { ...fetchOptions, headers });

  if (res.status === 401 && !skipRefresh) {
    try {
      const newToken = await _refresh();
      headers.Authorization = `Bearer ${newToken}`;
      res = await fetch(`${API_BASE}${path}`, { ...options, headers });
    } catch {
      localStorage.removeItem('cf_access_token');
      localStorage.removeItem('cf_refresh_token');
      window.dispatchEvent(new Event('cf:logout'));
      const err = new Error('Session expired. Please sign in again.');
      err.code = 'AUTH_EXPIRED';
      throw err;
    }
  }

  return res;
}

export async function apiJSON(path, options = {}) {
  const res = await apiFetch(path, options);
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (Array.isArray(body.detail)) {
        // FastAPI validation errors: [{loc, msg, type}, ...]
        detail = body.detail.map(e => e.msg).join(', ');
      } else {
        detail = body.detail ?? detail;
      }
    } catch {}
    throw new Error(detail);
  }
  if (res.status === 204) return null;
  return res.json();
}

export async function streamChat(sessionId, content, { onDelta, onDone, onError }) {
  let res;
  try {
    res = await apiFetch(`/chat/sessions/${sessionId}/messages`, {
      method: 'POST',
      body: JSON.stringify({ content }),
    });
  } catch (e) {
    onError(e.message);
    return;
  }

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {}
    onError(detail);
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  let currentEvent = '';

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;

      buf += decoder.decode(value, { stream: true });

      let nl;
      while ((nl = buf.indexOf('\n')) !== -1) {
        const line = buf.slice(0, nl);
        buf = buf.slice(nl + 1);

        if (line.startsWith('event: ')) {
          currentEvent = line.slice(7).trim();
        } else if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6));
            if (currentEvent === 'delta') onDelta(data.text ?? '');
            else if (currentEvent === 'done') onDone(data);
            else if (currentEvent === 'error') onError(data.detail ?? 'Stream error');
          } catch {
            // ignore malformed data lines
          }
          currentEvent = '';
        }
      }
    }
  } catch (e) {
    onError(e.message || 'Connection lost');
  }
}

export function parseTokenPayload(token) {
  try {
    // Handle base64url encoding
    const b64 = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    return JSON.parse(atob(b64));
  } catch {
    return {};
  }
}
