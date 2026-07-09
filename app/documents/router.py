import mimetypes
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.dependencies import get_current_user, get_db, get_s3_client
from app.documents import schemas, service
from app.documents.ingestion import ingest_document

router = APIRouter()

_ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
    "text/markdown",
    "text/html",
}


@router.post("", response_model=schemas.DocumentOut, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    s3_client=Depends(get_s3_client),
):
    mime = file.content_type or (mimetypes.guess_type(file.filename or "")[0] or "")
    if mime not in _ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type '{mime}'. Allowed: {sorted(_ALLOWED_MIME_TYPES)}",
        )

    doc = await service.upload_document(db, file, str(current_user.id), s3_client)
    background_tasks.add_task(ingest_document, str(doc.id))
    return doc


@router.get("", response_model=list[schemas.DocumentListItem])
async def list_documents(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.list_documents(db, str(current_user.id))


@router.get("/{document_id}", response_model=schemas.DocumentOut)
async def get_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.get_document(db, str(document_id), str(current_user.id))


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    s3_client=Depends(get_s3_client),
):
    await service.delete_document(db, str(document_id), str(current_user.id), s3_client)
