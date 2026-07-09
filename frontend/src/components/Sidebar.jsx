import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext.jsx';
import UserSettingsModal from './UserSettingsModal.jsx';

export default function Sidebar({ sessions, activeSessionId, onSelectSession, onNewChat, onLogout }) {
  const { isAdmin } = useAuth();
  const [showSettings, setShowSettings] = useState(false);

  return (
    <aside className="sidebar" aria-label="Navigation">
      {/* Brand header */}
      <div className="sidebar__header">
        <span className="sidebar__brand">CogniFetch</span>
        <button className="btn btn--icon" onClick={onLogout} title="Sign out" aria-label="Sign out">
          ↪
        </button>
      </div>

      {/* New chat */}
      <div className="sidebar__section">
        <button className="btn btn--primary btn--full" onClick={onNewChat}>
          + New chat
        </button>
      </div>

      {/* Session list */}
      <nav className="sidebar__section sidebar__sessions" aria-label="Chat sessions">
        {sessions.length === 0 ? (
          <p className="sidebar__empty">No sessions yet</p>
        ) : (
          sessions.map(s => (
            <button
              key={s.id}
              className={`session-item${s.id === activeSessionId ? ' session-item--active' : ''}`}
              onClick={() => onSelectSession(s.id)}
              aria-current={s.id === activeSessionId ? 'page' : undefined}
            >
              <span className="session-item__title">{s.title}</span>
              <span className="session-item__date">
                {new Date(s.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
              </span>
            </button>
          ))
        )}
      </nav>

      {/* Footer: documents + settings */}
      <div className="sidebar__footer">
        <Link to="/documents" className="sidebar__footer-link">
          ↑ Documents
        </Link>
        {isAdmin ? (
          <Link to="/admin" className="sidebar__footer-link">
            ⚙ Settings
          </Link>
        ) : (
          <button
            className="sidebar__footer-link"
            onClick={() => setShowSettings(true)}
          >
            Profile Settings
          </button>
        )}
      </div>

      {showSettings && (
        <UserSettingsModal onClose={() => setShowSettings(false)} />
      )}
    </aside>
  );
}
