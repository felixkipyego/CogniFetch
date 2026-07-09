from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChatMessage, ChatSession


async def create_session(
    db: AsyncSession,
    user_id: str,
    title: str,
    document_scope: Optional[list] = None,
) -> ChatSession:
    session = ChatSession(
        user_id=user_id,
        title=title,
        document_scope=[str(d) for d in document_scope] if document_scope else None,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def list_sessions(db: AsyncSession, user_id: str) -> list[ChatSession]:
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.user_id == user_id)
        .order_by(ChatSession.created_at.desc())
    )
    return list(result.scalars().all())


async def get_session(db: AsyncSession, session_id: str, user_id: str) -> ChatSession:
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == user_id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return session


async def list_messages(db: AsyncSession, session_id: str, user_id: str) -> list[ChatMessage]:
    await get_session(db, session_id, user_id)  # ownership check
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
    )
    return list(result.scalars().all())


async def add_message(
    db: AsyncSession,
    session_id: str,
    role: str,
    content: str,
    cited_chunk_ids: Optional[list] = None,
) -> ChatMessage:
    msg = ChatMessage(
        session_id=session_id,
        role=role,
        content=content,
        cited_chunk_ids=cited_chunk_ids,
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)
    return msg
