import { useEffect, useRef } from 'react';
import { marked } from 'marked';
import { useDocuments } from '../contexts/DocumentsContext.jsx';

marked.use({ gfm: true, breaks: true });

function CitationChip({ index, docId, isActive, onClick }) {
  const { documents } = useDocuments();
  const doc = documents.find(d => d.id === docId);
  const filename = doc ? doc.filename : docId.slice(0, 8);
  const ext = filename.split('.').pop()?.toUpperCase() ?? '';
  const name = filename.includes('.')
    ? filename.slice(0, filename.lastIndexOf('.'))
    : filename;
  const short = name.length > 28 ? name.slice(0, 25) + '…' : name;

  return (
    <button
      className={`citation-chip${isActive ? ' citation-chip--active' : ''}`}
      onClick={() => onClick(docId)}
      title={filename}
      aria-label={`Source ${index + 1}: ${filename}`}
    >
      <span className="citation-chip__num">{index + 1}</span>
      <span className="citation-chip__ext">{ext}</span>
      <span className="citation-chip__name">{short}</span>
    </button>
  );
}

function TypingDots() {
  return (
    <span className="typing-dots" aria-label="Typing">
      <span /><span /><span />
    </span>
  );
}

export default function MessageBubble({ message, onCitationClick, activeMarginaliaDocId }) {
  const { role, content, cited_chunk_ids, streaming, error } = message;
  const isUser = role === 'user';
  const isEmpty = !content && !error && streaming;

  const contentHtml = !isUser && content
    ? marked.parse(content)
    : null;

  return (
    <div className={`message message--${role}`}>
      <div className="message__bubble">
        {isUser ? (
          <p className="message__text">{content}</p>
        ) : error ? (
          <p className="message__error">
            <span aria-hidden>⚠ </span>{error}
          </p>
        ) : isEmpty ? (
          <TypingDots />
        ) : (
          <div
            className="message__markdown"
            dangerouslySetInnerHTML={{ __html: contentHtml }}
          />
        )}

        {/* Streaming cursor */}
        {streaming && content && <span className="message__cursor" aria-hidden />}

        {/* Citation chips */}
        {!streaming && !error && cited_chunk_ids && cited_chunk_ids.length > 0 && (
          <div className="citations" role="list" aria-label="Sources">
            <p className="citations__label">Sources</p>
            <div className="citations__chips">
              {cited_chunk_ids.map((docId, i) => (
                <CitationChip
                  key={docId}
                  index={i}
                  docId={docId}
                  isActive={activeMarginaliaDocId === docId}
                  onClick={onCitationClick}
                />
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
