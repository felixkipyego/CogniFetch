"""
Unit tests for the ingestion pipeline.

These tests mock all external I/O (S3, OpenAI, PGVector) and focus on:
  - _run_pipeline: correct chunking, metadata tagging, return value
  - ingest_document: status transitions and error handling
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.documents import Document as LCDocument
from sqlalchemy import select

from app.db.models import Document, DocumentStatus
from app.db.session import AsyncSessionLocal


# ---------------------------------------------------------------------------
# _run_pipeline  (pure sync, no DB — easy to unit test)
# ---------------------------------------------------------------------------

def test_run_pipeline_returns_chunk_count(tmp_path):
    txt = tmp_path / "sample.txt"
    txt.write_text("CogniFetch is an agentic RAG platform. " * 80)

    fake_doc = LCDocument(page_content=txt.read_text(), metadata={})

    with (
        patch("app.documents.ingestion.TextLoader") as MockLoader,
        patch("app.documents.ingestion.OpenAIEmbeddings"),
        patch("app.documents.ingestion.PGVector") as MockStore,
    ):
        MockLoader.return_value.load.return_value = [fake_doc]
        MockStore.return_value.add_documents.return_value = None

        from app.documents.ingestion import _run_pipeline
        count = _run_pipeline(str(txt), "text/plain", "doc-id", "user-id", "sample.txt")

    assert count >= 1


def test_run_pipeline_tags_metadata(tmp_path):
    txt = tmp_path / "doc.txt"
    txt.write_text("Some content about RAG systems. " * 60)

    captured_chunks = []
    fake_doc = LCDocument(page_content=txt.read_text(), metadata={})

    def fake_add(chunks):
        captured_chunks.extend(chunks)

    with (
        patch("app.documents.ingestion.TextLoader") as MockLoader,
        patch("app.documents.ingestion.OpenAIEmbeddings"),
        patch("app.documents.ingestion.PGVector") as MockStore,
    ):
        MockLoader.return_value.load.return_value = [fake_doc]
        MockStore.return_value.add_documents.side_effect = fake_add

        from app.documents.ingestion import _run_pipeline
        _run_pipeline(str(txt), "text/plain", "my-doc-id", "my-user-id", "doc.txt")

    assert all(c.metadata["document_id"] == "my-doc-id" for c in captured_chunks)
    assert all(c.metadata["user_id"] == "my-user-id" for c in captured_chunks)
    assert all(c.metadata["filename"] == "doc.txt" for c in captured_chunks)


# ---------------------------------------------------------------------------
# ingest_document  (async, uses real DB via AsyncSessionLocal)
# ---------------------------------------------------------------------------

async def _create_test_document(user_id: str) -> Document:
    """Insert a pending Document directly, bypassing the HTTP layer."""
    async with AsyncSessionLocal() as db:
        doc = Document(
            user_id=user_id,
            filename="test.txt",
            storage_path=f"{user_id}/{uuid.uuid4()}/test.txt",
            mime_type="text/plain",
            status=DocumentStatus.pending,
        )
        db.add(doc)
        await db.commit()
        await db.refresh(doc)
        return doc


@pytest.mark.asyncio
async def test_ingest_document_sets_ready(engine):
    fake_user_id = str(uuid.uuid4())
    doc = await _create_test_document(fake_user_id)

    with (
        patch("app.documents.ingestion.download_to_path"),
        patch("app.documents.ingestion._run_pipeline", return_value=3),
        patch("app.documents.ingestion.make_s3_client"),
        patch("builtins.open"),
        patch("os.path.exists", return_value=True),
        patch("os.unlink"),
        patch("tempfile.NamedTemporaryFile") as mock_tmp,
    ):
        mock_tmp.return_value.__enter__.return_value.name = "/tmp/fake.txt"

        from app.documents.ingestion import ingest_document
        await ingest_document(str(doc.id))

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Document).where(Document.id == doc.id))
        updated = result.scalar_one()

    assert updated.status == DocumentStatus.ready


@pytest.mark.asyncio
async def test_ingest_document_sets_failed_on_error(engine):
    fake_user_id = str(uuid.uuid4())
    doc = await _create_test_document(fake_user_id)

    with (
        patch("app.documents.ingestion.download_to_path", side_effect=RuntimeError("S3 down")),
        patch("app.documents.ingestion.make_s3_client"),
        patch("os.path.exists", return_value=True),
        patch("os.unlink"),
        patch("tempfile.NamedTemporaryFile") as mock_tmp,
    ):
        mock_tmp.return_value.__enter__.return_value.name = "/tmp/fake.txt"

        from app.documents.ingestion import ingest_document
        await ingest_document(str(doc.id))

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Document).where(Document.id == doc.id))
        updated = result.scalar_one()

    assert updated.status == DocumentStatus.failed
    assert "S3 down" in updated.error_message
