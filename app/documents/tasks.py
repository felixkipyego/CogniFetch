import logging
import os
import tempfile
from pathlib import Path

from botocore.exceptions import ClientError, EndpointConnectionError
from celery import Task
from openai import APIConnectionError, APITimeoutError, InternalServerError, RateLimitError
from sqlalchemy.exc import OperationalError

from app.celery_app import celery_app
from app.db.models import Document, DocumentStatus
from app.db.sync_session import SyncSessionLocal
from app.documents.ingestion import _run_pipeline, delete_document_chunks_sync
from app.documents.storage import download_to_path, make_s3_client

logger = logging.getLogger(__name__)

# Transient failures worth retrying (network/service blips). Anything else
# (corrupt file, bad mime type, auth errors) fails immediately with no retry.
TRANSIENT_EXCEPTIONS = (
    ClientError,
    EndpointConnectionError,
    APIConnectionError,
    APITimeoutError,
    RateLimitError,
    InternalServerError,
    OperationalError,
)


def _mark_failed(document_id: str, exc: Exception) -> None:
    with SyncSessionLocal() as db:
        doc = db.get(Document, document_id)
        if doc:
            doc.status = DocumentStatus.failed
            doc.error_message = str(exc)
            db.commit()


class _FailureMarkingTask(Task):
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        document_id = args[0] if args else kwargs.get("document_id")
        if document_id:
            logger.exception("Ingestion failed for document %s", document_id, exc_info=exc)
            _mark_failed(document_id, exc)
        super().on_failure(exc, task_id, args, kwargs, einfo)


@celery_app.task(
    base=_FailureMarkingTask,
    bind=True,
    autoretry_for=TRANSIENT_EXCEPTIONS,
    retry_backoff=3,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=3,
)
def ingest_document_task(self, document_id: str) -> None:
    with SyncSessionLocal() as db:
        doc = db.get(Document, document_id)
        if doc is None:
            logger.error("ingest_document_task: document %s not found", document_id)
            return
        doc.status = DocumentStatus.processing
        doc.error_message = None
        db.commit()
        filename, mime_type, storage_path, user_id = (
            doc.filename,
            doc.mime_type,
            doc.storage_path,
            str(doc.user_id),
        )

    tmp_path: str | None = None
    try:
        suffix = Path(filename).suffix or ".tmp"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp_path = tmp.name

        s3 = make_s3_client()
        download_to_path(s3, storage_path, tmp_path)

        # Idempotency: clear any chunks from a previous attempt before re-inserting,
        # so a Celery-driven retry never double-inserts.
        delete_document_chunks_sync(document_id)
        chunk_count = _run_pipeline(tmp_path, mime_type, document_id, user_id, filename)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)

    with SyncSessionLocal() as db:
        doc = db.get(Document, document_id)
        doc.status = DocumentStatus.ready
        db.commit()
    logger.info("Ingested document %s — %d chunks", document_id, chunk_count)
