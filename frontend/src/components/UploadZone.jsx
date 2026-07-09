import { useState, useRef } from 'react';
import { useDocuments } from '../contexts/DocumentsContext.jsx';

export default function UploadZone({ uploading }) {
  const { uploadDocument } = useDocuments();
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState('');
  const inputRef = useRef(null);

  async function handleFile(file) {
    if (!file) return;
    setError('');
    try {
      await uploadDocument(file);
    } catch (err) {
      setError(err.message);
    }
  }

  function onDragOver(e) {
    e.preventDefault();
    setDragging(true);
  }

  function onDragLeave() {
    setDragging(false);
  }

  function onDrop(e) {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  }

  function onChange(e) {
    const file = e.target.files[0];
    if (file) handleFile(file);
    e.target.value = '';
  }

  return (
    <div
      className={`upload-zone${dragging ? ' upload-zone--drag' : ''}${uploading ? ' upload-zone--busy' : ''}`}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
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
        onChange={onChange}
        tabIndex={-1}
        aria-hidden
      />
      {uploading ? (
        <span className="upload-zone__text">Uploading…</span>
      ) : dragging ? (
        <span className="upload-zone__text">Drop to upload</span>
      ) : (
        <span className="upload-zone__text">
          <span className="upload-zone__icon">↑</span> Upload document
        </span>
      )}
      {error && <span className="upload-zone__error">{error}</span>}
    </div>
  );
}
