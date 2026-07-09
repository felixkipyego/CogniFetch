import { useState, useRef } from 'react';
import { Link } from 'react-router-dom';
import { useDocuments } from '../contexts/DocumentsContext.jsx';

/* ─── File-type icon ─────────────────────────────────────────── */

function FileIcon({ mime }) {
  if (mime?.includes('pdf'))  return <span className="doc-page__file-icon doc-page__file-icon--pdf">PDF</span>;
  if (mime?.includes('word') || mime?.includes('docx')) return <span className="doc-page__file-icon doc-page__file-icon--doc">DOC</span>;
  return <span className="doc-page__file-icon doc-page__file-icon--txt">TXT</span>;
}

/* ─── Status badge ───────────────────────────────────────────── */

function StatusBadge({ status }) {
  const label = (status === 'pending' || status === 'processing') ? 'Processing' : status === 'ready' ? 'Ready' : 'Failed';
  const cls   = (status === 'pending' || status === 'processing') ? 'pending' : status;
  return <span className={`doc-status doc-status--${cls}`}>{label}</span>;
}

/* ─── Upload zone ────────────────────────────────────────────── */

function PageUploadZone() {
  const { uploadDocument, uploading } = useDocuments();
  const [dragging, setDragging] = useState(false);
  const [error, setError]       = useState('');
  const [lastFile, setLastFile] = useState('');
  const inputRef = useRef(null);

  async function handleFile(file) {
    if (!file) return;
    setError('');
    setLastFile(file.name);
    try {
      await uploadDocument(file);
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <div
      className={`page-upload${dragging ? ' page-upload--drag' : ''}${uploading ? ' page-upload--busy' : ''}`}
      onDragOver={e => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={e => { e.preventDefault(); setDragging(false); handleFile(e.dataTransfer.files[0]); }}
      onClick={() => !uploading && inputRef.current?.click()}
      role="button"
      tabIndex={0}
      onKeyDown={e => e.key === 'Enter' && !uploading && inputRef.current?.click()}
      aria-label="Upload a document"
      aria-busy={uploading}
    >
      <input
        ref={inputRef}
        type="file"
        accept=".pdf,.docx,.txt,.md,.html"
        className="upload-zone__input"
        onChange={e => { handleFile(e.target.files[0]); e.target.value = ''; }}
        tabIndex={-1}
        aria-hidden
      />
      <div className="page-upload__body">
        <span className="page-upload__arrow">↑</span>
        {uploading ? (
          <>
            <p className="page-upload__title">Uploading {lastFile}…</p>
            <p className="page-upload__sub">Processing will start shortly</p>
          </>
        ) : dragging ? (
          <p className="page-upload__title">Drop to upload</p>
        ) : (
          <>
            <p className="page-upload__title">Drag &amp; drop a file here</p>
            <p className="page-upload__sub">or <span className="page-upload__browse">browse files</span></p>
            <p className="page-upload__types">PDF · DOCX · TXT · MD · HTML</p>
          </>
        )}
        {error && <p className="page-upload__error">{error}</p>}
      </div>
    </div>
  );
}

/* ─── Document row ───────────────────────────────────────────── */

function DocRow({ doc }) {
  const { deleteDocument } = useDocuments();
  const [deleting, setDeleting] = useState(false);

  async function handleDelete() {
    if (!confirm(`Delete "${doc.filename}"? This cannot be undone.`)) return;
    setDeleting(true);
    try {
      await deleteDocument(doc.id);
    } catch {
      setDeleting(false);
    }
  }

  return (
    <div className={`doc-page__row${deleting ? ' doc-page__row--deleting' : ''}`}>
      <FileIcon mime={doc.mime_type} />

      <div className="doc-page__row-info">
        <span className="doc-page__row-name" title={doc.filename}>{doc.filename}</span>
        <span className="doc-page__row-date">
          {new Date(doc.created_at).toLocaleString(undefined, {
            year: 'numeric', month: 'short', day: 'numeric',
            hour: '2-digit', minute: '2-digit',
          })}
        </span>
      </div>

      <StatusBadge status={doc.status} />

      <button
        className="doc-page__delete"
        onClick={handleDelete}
        disabled={deleting}
        aria-label={`Delete ${doc.filename}`}
        title="Delete document"
      >
        {deleting ? '…' : '×'}
      </button>
    </div>
  );
}

/* ─── Page ───────────────────────────────────────────────────── */

export default function DocumentsPage() {
  const { documents, fetchDocuments } = useDocuments();

  return (
    <div className="doc-page-shell">
      {/* Top bar */}
      <header className="doc-page-bar">
        <Link to="/" className="doc-page-bar__back">← Back to chat</Link>
        <span className="doc-page-bar__brand">CogniFetch</span>
        <div className="doc-page-bar__spacer" />
      </header>

      {/* Content */}
      <main className="doc-page-main">
        <div className="doc-page-inner">
          <div className="doc-page-heading">
            <h1 className="doc-page-heading__title">Documents</h1>
            <p className="doc-page-heading__sub">
              Upload files to query with AI. Supported formats: PDF, DOCX, TXT, MD, HTML.
            </p>
          </div>

          {/* Upload zone */}
          <PageUploadZone />

          {/* Document list */}
          <div className="doc-page-list-header">
            <span className="doc-page-list-header__label">
              Your documents <span className="admin-count">{documents.length}</span>
            </span>
            <button className="btn btn--ghost btn--sm" onClick={fetchDocuments}>Refresh</button>
          </div>

          {documents.length === 0 ? (
            <div className="doc-page-empty">
              <p>No documents yet. Upload one above to get started.</p>
            </div>
          ) : (
            <div className="doc-page-list">
              {documents.map(doc => (
                <DocRow key={doc.id} doc={doc} />
              ))}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
