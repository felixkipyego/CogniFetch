import { useState, useEffect, useCallback, useRef } from 'react';
import { useAuth } from '../contexts/AuthContext.jsx';
import { useDocuments } from '../contexts/DocumentsContext.jsx';
import { apiJSON, streamChat } from '../api/client.js';
import Sidebar from '../components/Sidebar.jsx';
import ChatPane from '../components/ChatPane.jsx';
import MarginaliaRail from '../components/MarginaliaRail.jsx';

const sessionsKey = uid => `cf:sessions:${uid}`;

function loadLocalSessions(uid) {
  try {
    return JSON.parse(localStorage.getItem(sessionsKey(uid))) ?? [];
  } catch {
    return [];
  }
}

function saveLocalSessions(uid, sessions) {
  try {
    localStorage.setItem(sessionsKey(uid), JSON.stringify(sessions));
  } catch {}
}

function buildTitle(docIds, documents) {
  if (!docIds || docIds.length === 0) return 'All documents';
  if (docIds.length === 1) {
    const doc = documents.find(d => d.id === docIds[0]);
    const name = doc?.filename ?? 'document';
    return name.length > 36 ? name.slice(0, 33) + '…' : name;
  }
  return `${docIds.length} documents`;
}

export default function ChatPage() {
  const { userId, logout } = useAuth();
  const { documents, checkedDocIds } = useDocuments();

  const [sessions, setSessions] = useState([]);
  const [activeSessionId, setActiveSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  // Prevents the activeSessionId effect from overwriting messages that sendMessage
  // has already set optimistically (race: session created → effect fetches empty list → wipes messages)
  const skipNextMessagesLoadRef = useRef(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [marginaliaDocId, setMarginaliaDocId] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  // Load sessions from API, fall back to localStorage
  useEffect(() => {
    if (!userId) return;
    async function load() {
      try {
        const data = await apiJSON('/chat/sessions');
        const list = data ?? [];
        setSessions(list);
        saveLocalSessions(userId, list);
      } catch {
        setSessions(loadLocalSessions(userId));
      }
    }
    load();
  }, [userId]);

  // Load messages when active session changes
  useEffect(() => {
    if (!activeSessionId) {
      setMessages([]);
      return;
    }
    // sendMessage sets this flag when it creates a new session and will populate
    // messages itself — skip the load to avoid racing with the optimistic update.
    if (skipNextMessagesLoadRef.current) {
      skipNextMessagesLoadRef.current = false;
      return;
    }
    setLoadingMessages(true);
    apiJSON(`/chat/sessions/${activeSessionId}/messages`)
      .then(data => setMessages(data ?? []))
      .catch(() => setMessages([]))
      .finally(() => setLoadingMessages(false));
  }, [activeSessionId]);

  const createSession = useCallback(async (scopeOverride) => {
    const scope = scopeOverride ?? Array.from(checkedDocIds);
    const title = buildTitle(scope, documents);
    const session = await apiJSON('/chat/sessions', {
      method: 'POST',
      body: JSON.stringify({
        title,
        document_scope: scope.length > 0 ? scope : null,
      }),
    });
    setSessions(prev => {
      const next = [session, ...prev];
      saveLocalSessions(userId, next);
      return next;
    });
    setActiveSessionId(session.id);
    setMessages([]);
    return session;
  }, [checkedDocIds, documents, userId]);

  const selectSession = useCallback((id) => {
    if (id === activeSessionId) return;
    setActiveSessionId(id);
    setMarginaliaDocId(null);
    setSidebarOpen(false);
  }, [activeSessionId]);

  const handleNewChat = useCallback(async () => {
    try {
      await createSession();
    } catch (err) {
      console.error('Failed to create session:', err);
    }
  }, [createSession]);

  const sendMessage = useCallback(async (content) => {
    let sessionId = activeSessionId;

    // Create a session implicitly if none is active
    if (!sessionId) {
      skipNextMessagesLoadRef.current = true;
      let session;
      try {
        session = await createSession();
      } catch {
        skipNextMessagesLoadRef.current = false;
        return;
      }
      sessionId = session.id;
    }

    const tmpUserId = `tmp-u-${Date.now()}`;
    const tmpAsstId = `tmp-a-${Date.now()}`;

    setMessages(prev => [
      ...prev,
      { id: tmpUserId, role: 'user', content, cited_chunk_ids: null },
      { id: tmpAsstId, role: 'assistant', content: '', cited_chunk_ids: null, streaming: true },
    ]);
    setIsStreaming(true);

    let accumulated = '';

    await streamChat(sessionId, content, {
      onDelta(text) {
        accumulated += text;
        setMessages(prev =>
          prev.map(m => m.id === tmpAsstId ? { ...m, content: accumulated } : m)
        );
      },
      onDone({ message_id, cited_chunk_ids }) {
        setMessages(prev =>
          prev.map(m =>
            m.id === tmpAsstId
              ? { ...m, id: message_id ?? tmpAsstId, content: accumulated, cited_chunk_ids: cited_chunk_ids ?? null, streaming: false }
              : m
          )
        );
        setIsStreaming(false);
      },
      onError(detail) {
        setMessages(prev =>
          prev.map(m =>
            m.id === tmpAsstId
              ? { ...m, content: '', error: detail, streaming: false }
              : m
          )
        );
        setIsStreaming(false);
      },
    });
  }, [activeSessionId, createSession]);

  const activeSession = sessions.find(s => s.id === activeSessionId) ?? null;

  return (
    <div className={`app-shell${marginaliaDocId ? ' rail-open' : ''}${sidebarOpen ? ' sidebar-open' : ''}`}>
      {sidebarOpen && (
        <div className="sidebar-overlay" onClick={() => setSidebarOpen(false)} aria-hidden />
      )}

      <Sidebar
        sessions={sessions}
        activeSessionId={activeSessionId}
        onSelectSession={selectSession}
        onNewChat={handleNewChat}
        onLogout={logout}
      />

      <ChatPane
        session={activeSession}
        messages={messages}
        isStreaming={isStreaming}
        loadingMessages={loadingMessages}
        onSendMessage={sendMessage}
        onCitationClick={setMarginaliaDocId}
        activeMarginaliaDocId={marginaliaDocId}
        onMenuOpen={() => setSidebarOpen(true)}
      />

      {marginaliaDocId && (
        <MarginaliaRail
          docId={marginaliaDocId}
          onClose={() => setMarginaliaDocId(null)}
        />
      )}
    </div>
  );
}
