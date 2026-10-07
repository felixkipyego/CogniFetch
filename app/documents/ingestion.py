import logging
import threading

from langchain_community.document_loaders import (
    BSHTMLLoader,
    Docx2txtLoader,
    PyPDFLoader,
    TextLoader,
)
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_postgres import PGVector

from app.config import settings

logger = logging.getLogger(__name__)

_VECTOR_STORE_COLLECTION = "cognifetch_chunks"
_vector_store: PGVector | None = None
_vector_store_lock = threading.Lock()


def _get_vector_store() -> PGVector:
    """
    Lazily build the PGVector store once per process, behind a lock.

    Constructing PGVector(...) registers a SQLAlchemy declarative class against
    a shared registry; building a fresh instance per call races when two
    ingestion tasks run concurrently (`Table 'langchain_pg_collection' is
    already defined for this MetaData instance`). A single lazily-built
    singleton avoids the race entirely.
    """
    global _vector_store
    if _vector_store is None:
        with _vector_store_lock:
            if _vector_store is None:
                embeddings = OpenAIEmbeddings(
                    model=settings.embedding_model,
                    api_key=settings.api_key,
                    base_url=settings.openai_api_base,
                )
                _vector_store = PGVector(
                    embeddings=embeddings,
                    collection_name=_VECTOR_STORE_COLLECTION,
                    connection=settings.sync_database_url,
                )
    return _vector_store


async def delete_document_chunks(document_id: str) -> None:
    """Remove all pgvector embeddings that belong to a given document."""
    from sqlalchemy import text
    from app.db.session import engine

    async with engine.connect() as conn:
        await conn.execute(
            text("""
                DELETE FROM langchain_pg_embedding
                WHERE collection_id = (
                    SELECT uuid FROM langchain_pg_collection WHERE name = :name
                )
                AND cmetadata->>'document_id' = :doc_id
            """),
            {"name": "cognifetch_chunks", "doc_id": document_id},
        )
        await conn.commit()
    logger.info("Deleted vector chunks for document %s", document_id)


def delete_document_chunks_sync(document_id: str) -> None:
    """Sync counterpart of delete_document_chunks, for use inside the Celery worker."""
    from sqlalchemy import text
    from app.db.sync_session import sync_engine

    with sync_engine.connect() as conn:
        conn.execute(
            text("""
                DELETE FROM langchain_pg_embedding
                WHERE collection_id = (
                    SELECT uuid FROM langchain_pg_collection WHERE name = :name
                )
                AND cmetadata->>'document_id' = :doc_id
            """),
            {"name": _VECTOR_STORE_COLLECTION, "doc_id": document_id},
        )
        conn.commit()
    logger.info("Deleted vector chunks for document %s", document_id)


_LOADER_MAP = {
    "application/pdf": PyPDFLoader,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": Docx2txtLoader,
    "text/plain": TextLoader,
    "text/markdown": TextLoader,
    "text/html": BSHTMLLoader,
}


def _run_pipeline(tmp_path: str, mime_type: str, document_id: str, user_id: str, filename: str) -> int:
    """Load, split, embed, and store a document."""
    loader_cls = _LOADER_MAP.get(mime_type, TextLoader)
    raw_docs = loader_cls(tmp_path).load()

    splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        encoding_name=settings.tiktoken_encoding,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )
    chunks = splitter.split_documents(raw_docs)

    for chunk in chunks:
        chunk.metadata.update({
            "document_id": document_id,
            "user_id": user_id,
            "filename": filename,
        })

    store = _get_vector_store()
    store.add_documents(chunks)
    return len(chunks)
