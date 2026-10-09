import { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext.jsx';
import { apiJSON } from '../api/client.js';
import { ChangePasswordForm } from '../components/UserSettingsModal.jsx';

/* ─── Users tab ──────────────────────────────────────────────── */

function UsersTab() {
  const { userId } = useAuth();
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      setUsers(await apiJSON('/admin/users'));
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function toggleAdmin(user) {
    try {
      const updated = await apiJSON(`/admin/users/${user.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ is_admin: !user.is_admin }),
      });
      setUsers(prev => prev.map(u => u.id === updated.id ? updated : u));
    } catch (e) {
      alert(e.message);
    }
  }

  async function deleteUser(user) {
    if (!confirm(`Delete user "${user.email}" and all their data?`)) return;
    try {
      await apiJSON(`/admin/users/${user.id}`, { method: 'DELETE' });
      setUsers(prev => prev.filter(u => u.id !== user.id));
    } catch (e) {
      alert(e.message);
    }
  }

  if (loading) return <div className="admin-loading">Loading users…</div>;
  if (error) return <div className="admin-error">{error}</div>;

  return (
    <div className="admin-section">
      <div className="admin-section-header">
        <h2 className="admin-section-title">Users <span className="admin-count">{users.length}</span></h2>
        <button className="btn btn--ghost btn--sm" onClick={load}>Refresh</button>
      </div>
      <div className="admin-table-wrap">
        <table className="admin-table">
          <thead>
            <tr>
              <th>Email</th>
              <th>Joined</th>
              <th>Docs</th>
              <th>Admin</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {users.map(u => (
              <tr key={u.id} className={u.id === userId ? 'admin-table__row--self' : ''}>
                <td className="admin-table__email">
                  {u.email}
                  {u.id === userId && <span className="admin-badge admin-badge--you">you</span>}
                </td>
                <td className="admin-table__date">
                  {new Date(u.created_at).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })}
                </td>
                <td className="admin-table__num">{u.document_count}</td>
                <td>
                  <button
                    className={`admin-toggle${u.is_admin ? ' admin-toggle--on' : ''}`}
                    onClick={() => toggleAdmin(u)}
                    title={u.is_admin ? 'Revoke admin' : 'Grant admin'}
                  >
                    {u.is_admin ? 'Yes' : 'No'}
                  </button>
                </td>
                <td>
                  <button
                    className="btn btn--icon btn--danger-ghost"
                    onClick={() => deleteUser(u)}
                    disabled={u.id === userId}
                    title="Delete user"
                  >
                    ×
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ─── Config tab ─────────────────────────────────────────────── */

const CONFIG_META = {
  api_key:          { label: 'API Key',          type: 'password', hint: 'Leave blank to keep current value' },
  openai_api_base:  { label: 'API Base URL',      type: 'text',     hint: 'e.g. https://api.openai.com/v1' },
  llm_model:        { label: 'LLM Model',         type: 'text',     hint: 'e.g. gpt-4o-mini' },
  embedding_model:  { label: 'Embedding Model',   type: 'text',     hint: 'e.g. text-embedding-3-small' },
};

function ConfigTab() {
  const [config, setConfig] = useState([]);
  const [form, setForm] = useState({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await apiJSON('/admin/config');
      setConfig(data);
      // Pre-fill form with non-sensitive values only
      const initial = {};
      data.forEach(item => {
        initial[item.key] = item.key === 'api_key' ? '' : item.value;
      });
      setForm(initial);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function handleSave(e) {
    e.preventDefault();
    setSaving(true);
    setError('');
    setSuccess('');
    try {
      const updated = await apiJSON('/admin/config', {
        method: 'PATCH',
        body: JSON.stringify({ changes: form }),
      });
      setConfig(updated);
      // Clear api_key field after saving
      setForm(prev => ({ ...prev, api_key: '' }));
      setSuccess('Configuration saved. Changes take effect on the next request.');
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <div className="admin-loading">Loading config…</div>;

  const sourceMap = Object.fromEntries(config.map(c => [c.key, c]));

  return (
    <div className="admin-section">
      <div className="admin-section-header">
        <h2 className="admin-section-title">Configuration</h2>
      </div>
      <p className="admin-section-desc">
        Values saved here override environment variables at runtime — no restart required.
        Delete a field's value (submit empty) to revert to the environment variable.
      </p>

      {error && <div className="admin-error">{error}</div>}
      {success && <div className="admin-success">{success}</div>}

      <form className="config-form" onSubmit={handleSave}>
        {Object.entries(CONFIG_META).map(([key, meta]) => {
          const item = sourceMap[key];
          return (
            <div className="config-field" key={key}>
              <div className="config-field__header">
                <label className="config-field__label" htmlFor={`cfg-${key}`}>{meta.label}</label>
                {item && (
                  <span className={`config-source config-source--${item.source}`}>
                    {item.source === 'database' ? '● DB override' : '○ Environment'}
                  </span>
                )}
              </div>
              {item?.source === 'database' && key !== 'api_key' && (
                <div className="config-current">Current: <code>{item.value}</code></div>
              )}
              {item?.source === 'database' && key === 'api_key' && (
                <div className="config-current">Current: <code>{item.value}</code></div>
              )}
              <input
                id={`cfg-${key}`}
                type={meta.type}
                className="field__input config-field__input"
                value={form[key] ?? ''}
                onChange={e => setForm(prev => ({ ...prev, [key]: e.target.value }))}
                placeholder={key === 'api_key'
                  ? (item?.source === 'database' ? 'Enter new value to replace' : 'Enter API key')
                  : meta.hint}
                autoComplete="off"
              />
              <p className="config-field__hint">{meta.hint}</p>
            </div>
          );
        })}

        <div className="config-form__actions">
          <button type="submit" className="btn btn--primary" disabled={saving}>
            {saving ? 'Saving…' : 'Save changes'}
          </button>
          <button type="button" className="btn btn--ghost" onClick={load} disabled={saving}>
            Reset
          </button>
        </div>
      </form>
    </div>
  );
}

/* ─── Metrics tab ────────────────────────────────────────────── */

function fmtCost(v) {
  return v === null || v === undefined ? '—' : `$${v.toFixed(4)}`;
}
function fmtMs(v) {
  return v === null || v === undefined ? '—' : `${Math.round(v).toLocaleString()} ms`;
}

function StatCard({ label, value }) {
  return (
    <div className="admin-stat-card">
      <div className="admin-stat-card__label">{label}</div>
      <div className="admin-stat-card__value">{value}</div>
    </div>
  );
}

function MetricsTab() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      setData(await apiJSON('/admin/metrics'));
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  if (loading) return <div className="admin-loading">Loading metrics…</div>;
  if (error) return <div className="admin-error">{error}</div>;
  if (!data || data.window_run_count === 0) {
    return (
      <div className="admin-section">
        <div className="admin-section-header">
          <h2 className="admin-section-title">Metrics</h2>
          <button className="btn btn--ghost btn--sm" onClick={load}>Refresh</button>
        </div>
        <p className="admin-section-desc">No agent runs recorded yet — send a chat message to populate this.</p>
      </div>
    );
  }

  const { overall, by_route, avg_node_latency_ms } = data;

  return (
    <div className="admin-section">
      <div className="admin-section-header">
        <h2 className="admin-section-title">Metrics <span className="admin-count">last {data.window_run_count} runs</span></h2>
        <button className="btn btn--ghost btn--sm" onClick={load}>Refresh</button>
      </div>
      <p className="admin-section-desc">
        Token, cost, and latency stats for the most recent agent runs (real chat traffic and eval harness runs alike).
        Cost is a best-effort estimate from a static OpenAI rate table — unpriced or gateway-routed models show as unknown
        rather than $0.
      </p>

      <div className="admin-stat-grid">
        <StatCard label="p50 latency" value={fmtMs(overall.p50_latency_ms)} />
        <StatCard label="p95 latency" value={fmtMs(overall.p95_latency_ms)} />
        <StatCard label="Prompt tokens" value={overall.prompt_tokens.toLocaleString()} />
        <StatCard label="Completion tokens" value={overall.completion_tokens.toLocaleString()} />
        <StatCard label="Total cost" value={fmtCost(overall.total_cost_usd)} />
        <StatCard label="Unpriced runs" value={overall.runs_with_unknown_cost} />
      </div>

      <h3 className="admin-subheading">By route</h3>
      <div className="admin-table-wrap">
        <table className="admin-table">
          <thead>
            <tr>
              <th>Route</th>
              <th>Runs</th>
              <th>p50</th>
              <th>p95</th>
              <th>Tokens (in/out)</th>
              <th>Cost</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(by_route).map(([route, stats]) => (
              <tr key={route}>
                <td className="admin-table__email">{route}</td>
                <td className="admin-table__num">{stats.run_count}</td>
                <td className="admin-table__num">{fmtMs(stats.p50_latency_ms)}</td>
                <td className="admin-table__num">{fmtMs(stats.p95_latency_ms)}</td>
                <td className="admin-table__num">{stats.prompt_tokens.toLocaleString()} / {stats.completion_tokens.toLocaleString()}</td>
                <td className="admin-table__num">{fmtCost(stats.total_cost_usd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3 className="admin-subheading">Avg latency per node</h3>
      <div className="admin-table-wrap">
        <table className="admin-table">
          <thead>
            <tr>
              <th>Node</th>
              <th>Avg latency per run</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(avg_node_latency_ms)
              .sort((a, b) => b[1] - a[1])
              .map(([node, ms]) => (
                <tr key={node}>
                  <td className="admin-table__email">{node}</td>
                  <td className="admin-table__num">{fmtMs(ms)}</td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ─── Profile tab ────────────────────────────────────────────── */

function ProfileTab() {
  return (
    <div className="admin-section">
      <div className="admin-section-header">
        <h2 className="admin-section-title">My Profile</h2>
      </div>

      <div className="admin-profile-card">
        <h3 className="settings-section__title">Security</h3>
        <ChangePasswordForm />
      </div>
    </div>
  );
}

/* ─── Admin page shell ───────────────────────────────────────── */

const TABS = [
  { id: 'Users',   icon: '👤' },
  { id: 'Metrics', icon: '📊' },
  { id: 'Config',  icon: '⚙' },
  { id: 'Profile', icon: '🔑' },
];

export default function AdminPage() {
  const { logout } = useAuth();
  const [tab, setTab] = useState('Users');

  return (
    <div className="admin-shell">
      <aside className="admin-sidebar">
        <div className="admin-sidebar__header">
          <span className="admin-sidebar__brand">CogniFetch</span>
          <span className="admin-sidebar__badge">Admin</span>
        </div>
        <nav className="admin-nav">
          {TABS.map(({ id, icon }) => (
            <button
              key={id}
              className={`admin-nav__item${tab === id ? ' admin-nav__item--active' : ''}`}
              onClick={() => setTab(id)}
            >
              {icon} {id}
            </button>
          ))}
        </nav>
        <div className="admin-sidebar__footer">
          <Link to="/" className="admin-nav__item">← Back to app</Link>
          <button className="admin-nav__item" onClick={logout}>Sign out</button>
        </div>
      </aside>

      <main className="admin-main">
        {tab === 'Users'   && <UsersTab />}
        {tab === 'Metrics' && <MetricsTab />}
        {tab === 'Config'  && <ConfigTab />}
        {tab === 'Profile' && <ProfileTab />}
      </main>
    </div>
  );
}
