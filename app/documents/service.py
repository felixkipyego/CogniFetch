import asyncio
import mimetypes
import uuid

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, DocumentStatus
from app.documents import storage


def _detect_mime(filename: str, provided: str) -> str:
    if provided and provided not in ("application/octet-stream", "binary/octet-stream"):
        return provided
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


async def upload_document(
    db: AsyncSession,
    file: UploadFile,
    user_id: str,
    s3_client,
) -> Document:
    mime_type = _detect_mime(file.filename or "", file.content_type or "")
    storage_key = f"{user_id}/{uuid.uuid4()}/{file.filename}"

    file_bytes = await file.read()
    storage.upload_bytes(s3_client, storage_key, file_bytes, mime_type)

    doc = Document(
        user_id=user_id,
        filename=file.filename or "upload",
        storage_path=storage_key,
        mime_type=mime_type,
        status=DocumentStatus.pending,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return doc


async def list_documents(db: AsyncSession, user_id: str) -> list[Document]:
    result = await db.execute(
        select(Document)
        .where(Document.user_id == user_id)
        .order_by(Document.created_at.desc())
    )
    return list(result.scalars().all())


async def get_document(db: AsyncSession, document_id: str, user_id: str) -> Document:
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.user_id == user_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return doc


async def delete_document(
    db: AsyncSession,
    document_id: str,
    user_id: str,
    s3_client,
) -> None:
    from app.documents.ingestion import delete_document_chunks

    doc = await get_document(db, document_id, user_id)

    await asyncio.to_thread(storage.delete_object, s3_client, doc.storage_path)
    await delete_document_chunks(str(doc.id))

    await db.delete(doc)
    await db.commit()
