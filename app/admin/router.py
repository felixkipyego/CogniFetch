import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin import schemas, service
from app.db.models import User
from app.dependencies import get_current_admin_user, get_db

router = APIRouter()


@router.get("/users", response_model=list[schemas.UserAdminOut])
async def list_users(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin_user),
):
    return await service.list_users(db)


@router.patch("/users/{user_id}", response_model=schemas.UserAdminOut)
async def update_user(
    user_id: uuid.UUID,
    body: schemas.UserAdminUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin_user),
):
    return await service.update_user(db, str(user_id), body.is_admin, str(admin.id))


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin_user),
):
    await service.delete_user(db, str(user_id), str(admin.id))


@router.get("/config", response_model=list[schemas.ConfigOut])
async def get_config(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin_user),
):
    return await service.get_config(db)


@router.patch("/config", response_model=list[schemas.ConfigOut])
async def patch_config(
    body: schemas.ConfigPatch,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin_user),
):
    return await service.patch_config(db, body.changes)
