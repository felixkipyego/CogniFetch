import { useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import MessageBubble from './MessageBubble.jsx';
import Composer from './Composer.jsx';

function EmptyState() {
  return (
    <div className="chat-empty">
      <h2 className="chat-empty__title">Ask your documents anything</h2>
      <p className="chat-empty__sub">
        Upload PDFs, Word docs, or text files, then start a conversation.
      </p>
      <Link to="/documents" className="btn btn--primary chat-empty__upload-btn">
        ↑ Upload documents
      </Link>
    </div>
  );
}

function Spinner() {
  return <div className="spinner" aria-label="Loading" role="status" />;
}

export default function ChatPane({
  session,
  messages,
  isStreaming,
  loadingMessages,
  onSendMessage,
  onCitationClick,
  activeMarginaliaDocId,
  onMenuOpen,
}) {
  const bottomRef = useRef(null);
  const listRef = useRef(null);

  // Auto-scroll: only scroll if user is near the bottom
  useEffect(() => {
    const list = listRef.current;
    if (!list) return;
    const threshold = 120;
    const nearBottom = list.scrollHeight - list.scrollTop - list.clientHeight < threshold;
    if (nearBottom || isStreaming) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, isStreaming]);

  return (
    <main className="chat-pane" aria-label="Chat">
      <header className="chat-header">
        <button
          className="btn btn--icon chat-header__menu"
          onClick={onMenuOpen}
          aria-label="Open sidebar"
        >
          ☰
        </button>
        <span className="chat-header__title">
          {session ? session.title : 'CogniFetch'}
        </span>
        {session?.document_scope && session.document_scope.length > 0 && (
          <span className="chat-header__scope">
            {session.document_scope.length === 1
              ? '1 document'
              : `${session.document_scope.length} documents`}
          </span>
        )}
      </header>

      <div className="chat-messages" ref={listRef}>
        {loadingMessages ? (
          <div className="chat-messages__loading"><Spinner /></div>
        ) : messages.length === 0 ? (
          <EmptyState />
        ) : (
          messages.map(msg => (
            <MessageBubble
              key={msg.id}
              message={msg}
              onCitationClick={onCitationClick}
              activeMarginaliaDocId={activeMarginaliaDocId}
            />
          ))
        )}
        <div ref={bottomRef} />
      </div>

      <Composer onSend={onSendMessage} isStreaming={isStreaming} />
    </main>
  );
}
