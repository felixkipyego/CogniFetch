import asyncio
import logging
import os
import tempfile
from pathlib import Path

from langchain_community.document_loaders import (
    BSHTMLLoader,
    Docx2txtLoader,
    PyPDFLoader,
    TextLoader,
)
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_postgres import PGVector
from sqlalchemy import select

from app.config import settings
from app.db.models import Document, DocumentStatus
from app.db.session import AsyncSessionLocal
from app.documents.storage import download_to_path, make_s3_client

logger = logging.getLogger(__name__)


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


_LOADER_MAP = {
    "application/pdf": PyPDFLoader,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": Docx2txtLoader,
    "text/plain": TextLoader,
    "text/markdown": TextLoader,
    "text/html": BSHTMLLoader,
}


def _run_pipeline(tmp_path: str, mime_type: str, document_id: str, user_id: str, filename: str) -> int:
    """Load, split, embed, and store a document. Runs in a thread pool."""
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

    embeddings = OpenAIEmbeddings(
        model=settings.embedding_model,
        api_key=settings.api_key,
        base_url=settings.openai_api_base,
    )
    store = PGVector(
        embeddings=embeddings,
        collection_name="cognifetch_chunks",
        connection=settings.sync_database_url,
    )
    store.add_documents(chunks)
    return len(chunks)


async def ingest_document(document_id: str) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Document).where(Document.id == document_id))
        doc = result.scalar_one_or_none()
        if not doc:
            logger.error("ingest_document: document %s not found", document_id)
            return

        doc.status = DocumentStatus.processing
        await db.commit()

        tmp_path: str | None = None
        try:
            suffix = Path(doc.filename).suffix or ".tmp"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp_path = tmp.name

            s3 = make_s3_client()
            await asyncio.to_thread(download_to_path, s3, doc.storage_path, tmp_path)

            chunk_count = await asyncio.to_thread(
                _run_pipeline,
                tmp_path,
                doc.mime_type,
                str(doc.id),
                str(doc.user_id),
                doc.filename,
            )

            doc.status = DocumentStatus.ready
            await db.commit()
            logger.info("Ingested document %s — %d chunks", document_id, chunk_count)

        except Exception as exc:
            logger.exception("Ingestion failed for document %s", document_id)
            doc.status = DocumentStatus.failed
            doc.error_message = str(exc)
            await db.commit()

        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)
