import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import runtime_config
from app.admin.schemas import ConfigOut, UserAdminOut
from app.config import settings
from app.db.models import Document, SystemConfig, User

# Config keys exposed to the admin UI, in display order
CONFIG_KEYS = ["api_key", "openai_api_base", "llm_model", "embedding_model"]

_ENV_DEFAULTS = {
    "api_key": settings.api_key,
    "openai_api_base": settings.openai_api_base,
    "llm_model": settings.llm_model,
    "embedding_model": settings.embedding_model,
}


def _mask(key: str, value: str) -> str:
    if key == "api_key" and value:
        visible = min(6, len(value))
        return value[:visible] + "••••••••"
    return value


async def list_users(db: AsyncSession) -> list[UserAdminOut]:
    rows = await db.execute(
        select(User, func.count(Document.id).label("doc_count"))
        .outerjoin(Document, Document.user_id == User.id)
        .group_by(User.id)
        .order_by(User.created_at)
    )
    return [
        UserAdminOut(
            id=str(user.id),
            email=user.email,
            is_admin=user.is_admin,
            created_at=user.created_at,
            document_count=doc_count,
        )
        for user, doc_count in rows
    ]


async def update_user(db: AsyncSession, user_id: str, is_admin: bool, current_admin_id: str) -> UserAdminOut:
    if user_id == current_admin_id and not is_admin:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot remove your own admin rights")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user.is_admin = is_admin
    await db.commit()
    await db.refresh(user)
    doc_count_result = await db.execute(
        select(func.count(Document.id)).where(Document.user_id == user.id)
    )
    return UserAdminOut(
        id=str(user.id),
        email=user.email,
        is_admin=user.is_admin,
        created_at=user.created_at,
        document_count=doc_count_result.scalar() or 0,
    )


async def delete_user(db: AsyncSession, user_id: str, current_admin_id: str) -> None:
    if user_id == current_admin_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete your own account from admin panel")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    await db.delete(user)
    await db.commit()


async def get_config(db: AsyncSession) -> list[ConfigOut]:
    result = await db.execute(select(SystemConfig))
    db_rows = {row.key: row for row in result.scalars()}

    out = []
    for key in CONFIG_KEYS:
        if key in db_rows:
            row = db_rows[key]
            out.append(ConfigOut(
                key=key,
                value=_mask(key, row.value),
                source="database",
                updated_at=row.updated_at,
            ))
        else:
            env_val = _ENV_DEFAULTS.get(key, "")
            out.append(ConfigOut(
                key=key,
                value=_mask(key, env_val),
                source="environment",
            ))
    return out


async def patch_config(db: AsyncSession, changes: dict[str, str]) -> list[ConfigOut]:
    for key, value in changes.items():
        if key not in runtime_config.ALLOWED_KEYS:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown config key: {key}")

        result = await db.execute(select(SystemConfig).where(SystemConfig.key == key))
        row = result.scalar_one_or_none()

        if value == "":
            # Empty string = delete the DB override (fall back to env)
            if row:
                await db.delete(row)
            runtime_config.delete(key)
        else:
            if row:
                row.value = value
                row.updated_at = datetime.now(timezone.utc)
            else:
                db.add(SystemConfig(key=key, value=value, updated_at=datetime.now(timezone.utc)))
            runtime_config.set_one(key, value)

    await db.commit()
    return await get_config(db)


async def load_config_into_runtime(db: AsyncSession) -> None:
    """Called at startup to seed runtime_config from DB."""
    result = await db.execute(select(SystemConfig))
    mapping = {row.key: row.value for row in result.scalars()}
    runtime_config.set_many(mapping)
