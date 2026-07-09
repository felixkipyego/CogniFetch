import { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import { apiJSON, apiFetch } from '../api/client.js';
import { useAuth } from './AuthContext.jsx';

const DocsCtx = createContext(null);

export function DocumentsProvider({ children }) {
  const { isAuthenticated } = useAuth();
  const [documents, setDocuments] = useState([]);
  const [checkedDocIds, setCheckedDocIds] = useState(new Set());
  const [uploading, setUploading] = useState(false);
  const pollRef = useRef(null);

  const fetchDocuments = useCallback(async () => {
    try {
      const docs = await apiJSON('/documents');
      setDocuments(docs ?? []);
      return docs ?? [];
    } catch {
      return [];
    }
  }, []);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const startPolling = useCallback(() => {
    if (pollRef.current) return;
    pollRef.current = setInterval(async () => {
      const docs = await fetchDocuments();
      if (docs.every(d => d.status !== 'pending' && d.status !== 'processing')) stopPolling();
    }, 3000);
  }, [fetchDocuments, stopPolling]);

  useEffect(() => {
    if (!isAuthenticated) return;
    fetchDocuments().then(docs => {
      if (docs.some(d => d.status === 'pending' || d.status === 'processing')) startPolling();
    });
    return stopPolling;
  }, [isAuthenticated, fetchDocuments, startPolling, stopPolling]);

  const uploadDocument = useCallback(async (file) => {
    setUploading(true);
    try {
      const body = new FormData();
      body.append('file', file);
      const res = await apiFetch('/documents', { method: 'POST', body });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Upload failed' }));
        throw new Error(err.detail ?? 'Upload failed');
      }
      const doc = await res.json();
      setDocuments(prev => [doc, ...prev]);
      startPolling();
      return doc;
    } finally {
      setUploading(false);
    }
  }, [startPolling]);

  const deleteDocument = useCallback(async (id) => {
    await apiFetch(`/documents/${id}`, { method: 'DELETE' });
    setDocuments(prev => prev.filter(d => d.id !== id));
    setCheckedDocIds(prev => {
      const next = new Set(prev);
      next.delete(id);
      return next;
    });
  }, []);

  const toggleDocCheck = useCallback((id) => {
    setCheckedDocIds(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }, []);

  return (
    <DocsCtx.Provider value={{
      documents,
      checkedDocIds,
      uploading,
      fetchDocuments,
      uploadDocument,
      deleteDocument,
      toggleDocCheck,
    }}>
      {children}
    </DocsCtx.Provider>
  );
}

export const useDocuments = () => useContext(DocsCtx);
