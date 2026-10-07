"""
Unit tests for the ingestion pipeline.

These tests mock all external I/O (S3, OpenAI, PGVector) and focus on:
  - _run_pipeline: correct chunking, metadata tagging, return value
  - ingest_document_task: status transitions, retry-then-succeed, and
    permanent-failure-with-no-retry behavior
"""
import uuid
from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError
from langchain_core.documents import Document as LCDocument

from app.db.models import Document, DocumentStatus, User


@pytest.fixture(autouse=True)
def _reset_vector_store_singleton():
    """The PGVector singleton in ingestion.py must not leak a mock/instance
    from one test into the next test's assertions."""
    import app.documents.ingestion as ingestion_module

    ingestion_module._vector_store = None
    yield
    ingestion_module._vector_store = None


@pytest.fixture(autouse=True)
def _use_test_sync_session(sync_sessionmaker):
    """The task module's own SyncSessionLocal is bound to the real .env
    SYNC_DATABASE_URL (the docker-internal `postgres` host) — point it at the
    test database for the duration of these tests, same idea as conftest's
    `client` fixture overriding FastAPI's get_db dependency."""
    with patch("app.documents.tasks.SyncSessionLocal", sync_sessionmaker):
        yield


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
# ingest_document_task  (sync, uses the real test DB via sync_db/sync_engine)
# ---------------------------------------------------------------------------

def _create_test_user(sync_db) -> User:
    user = User(
        email=f"ingest-{uuid.uuid4()}@example.com",
        hashed_password="not-a-real-hash",
        is_verified=True,
    )
    sync_db.add(user)
    sync_db.commit()
    sync_db.refresh(user)
    return user


def _create_test_document(sync_db) -> Document:
    """Insert a pending Document (owned by a freshly created user) directly,
    bypassing the HTTP layer."""
    user = _create_test_user(sync_db)
    doc = Document(
        user_id=user.id,
        filename="test.txt",
        storage_path=f"{user.id}/{uuid.uuid4()}/test.txt",
        mime_type="text/plain",
        status=DocumentStatus.pending,
    )
    sync_db.add(doc)
    sync_db.commit()
    sync_db.refresh(doc)
    return doc


def test_ingest_document_task_sets_ready(sync_db, sync_engine):
    doc = _create_test_document(sync_db)

    with (
        patch("app.documents.tasks.download_to_path"),
        patch("app.documents.tasks._run_pipeline", return_value=3),
        patch("app.documents.tasks.delete_document_chunks_sync"),
        patch("app.documents.tasks.make_s3_client"),
        patch("os.path.exists", return_value=True),
        patch("os.unlink"),
    ):
        from app.documents.tasks import ingest_document_task
        ingest_document_task.apply(args=[str(doc.id)])

    sync_db.expire_all()
    updated = sync_db.get(Document, doc.id)
    assert updated.status == DocumentStatus.ready


def test_ingest_document_task_sets_failed_on_permanent_error(sync_db, sync_engine):
    """A non-transient error (e.g. a corrupt/unsupported file) should fail
    immediately with no retry."""
    doc = _create_test_document(sync_db)

    with (
        patch("app.documents.tasks.download_to_path"),
        patch("app.documents.tasks._run_pipeline", side_effect=ValueError("corrupt file")) as mock_pipeline,
        patch("app.documents.tasks.delete_document_chunks_sync"),
        patch("app.documents.tasks.make_s3_client"),
        patch("os.path.exists", return_value=True),
        patch("os.unlink"),
    ):
        from app.documents.tasks import ingest_document_task
        ingest_document_task.apply(args=[str(doc.id)])

    assert mock_pipeline.call_count == 1  # no retry for a non-transient exception

    sync_db.expire_all()
    updated = sync_db.get(Document, doc.id)
    assert updated.status == DocumentStatus.failed
    assert "corrupt file" in updated.error_message


def test_ingest_document_task_retries_then_succeeds(sync_db, sync_engine):
    """A transient error (e.g. an S3 blip) should retry and succeed, with
    chunks deleted before every attempt so a retry can't double-insert."""
    doc = _create_test_document(sync_db)

    transient_error = ClientError({"Error": {"Code": "500", "Message": "S3 blip"}}, "GetObject")

    with (
        patch("app.documents.tasks.download_to_path"),
        patch(
            "app.documents.tasks._run_pipeline",
            side_effect=[transient_error, 2],
        ) as mock_pipeline,
        patch("app.documents.tasks.delete_document_chunks_sync") as mock_delete,
        patch("app.documents.tasks.make_s3_client"),
        patch("os.path.exists", return_value=True),
        patch("os.unlink"),
    ):
        from app.documents.tasks import ingest_document_task
        ingest_document_task.apply(args=[str(doc.id)])

    assert mock_pipeline.call_count == 2
    assert mock_delete.call_count == 2  # ran before every attempt, not just the first

    sync_db.expire_all()
    updated = sync_db.get(Document, doc.id)
    assert updated.status == DocumentStatus.ready
