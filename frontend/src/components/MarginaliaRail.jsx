import { useDocuments } from '../contexts/DocumentsContext.jsx';

function formatDate(iso) {
  return new Date(iso).toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

function StatusRow({ status, errorMessage }) {
  return (
    <div className="rail-meta-row">
      <span className="rail-meta-label">Status</span>
      <span className={`doc-status doc-status--${status}`}>
        {(status === 'pending' || status === 'processing') ? 'Processing' : status === 'ready' ? 'Ready' : 'Failed'}
      </span>
      {status === 'failed' && errorMessage && (
        <p className="rail-error">{errorMessage}</p>
      )}
    </div>
  );
}

export default function MarginaliaRail({ docId, pages = [], onClose }) {
  const { documents } = useDocuments();
  const doc = documents.find(d => d.id === docId);

  // PyPDFLoader stores pages 0-indexed; display as 1-indexed to users.
  const displayPages = pages.map(p => p + 1);

  return (
    <aside className="marginalia-rail" aria-label="Source document details">
      <div className="rail-header">
        <span className="rail-header__title">Source</span>
        <button
          className="btn btn--icon"
          onClick={onClose}
          aria-label="Close source panel"
        >
          ×
        </button>
      </div>

      {!doc ? (
        <div className="rail-body">
          <p className="rail-empty">Document not found in your library.</p>
          <p className="rail-id">ID: <code>{docId}</code></p>
        </div>
      ) : (
        <div className="rail-body">
          <h3 className="rail-filename">{doc.filename}</h3>

          <StatusRow status={doc.status} errorMessage={doc.error_message} />

          {displayPages.length > 0 && (
            <div className="rail-meta-row">
              <span className="rail-meta-label">
                {displayPages.length === 1 ? 'Page' : 'Pages'}
              </span>
              <span className="rail-meta-value">{displayPages.join(', ')}</span>
            </div>
          )}

          <div className="rail-meta-row">
            <span className="rail-meta-label">Uploaded</span>
            <span className="rail-meta-value">{formatDate(doc.created_at)}</span>
          </div>

          <div className="rail-meta-row">
            <span className="rail-meta-label">ID</span>
            <code className="rail-doc-id">{doc.id}</code>
          </div>
        </div>
      )}
    </aside>
  );
}
