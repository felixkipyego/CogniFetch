import json
import logging
import uuid
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat import schemas, service
from app.chat.agent.orchestrator import build_orchestrator_graph
from app.chat.agent.retriever import make_retriever_tool
from app.chat.agent.runner import stream_agent_turn
from app.db.models import ChatSession, Document, DocumentStatus, User
from app.dependencies import get_current_user, get_db
from app.metrics import service as metrics_service

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/sessions", response_model=schemas.SessionOut, status_code=status.HTTP_201_CREATED)
async def create_session(
    body: schemas.SessionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.create_session(
        db,
        user_id=str(current_user.id),
        title=body.title,
        document_scope=body.document_scope,
    )


@router.get("/sessions", response_model=list[schemas.SessionOut])
async def list_sessions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.list_sessions(db, str(current_user.id))


@router.get("/sessions/{session_id}/messages", response_model=list[schemas.MessageOut])
async def list_messages(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.list_messages(db, str(session_id), str(current_user.id))


async def _resolve_document_ids(db: AsyncSession, user_id: str, document_scope) -> list[str]:
    """Resolve a session's document_scope to concrete, ready document IDs —
    the orchestrator needs real IDs both to fan out multi-doc synthesis
    retrieval and to decide which routes the supervisor may pick."""
    query = select(Document.id).where(
        Document.user_id == user_id, Document.status == DocumentStatus.ready
    )
    if document_scope:
        query = query.where(Document.id.in_(document_scope))
    result = await db.execute(query)
    return [str(row[0]) for row in result.all()]


async def _stream_agent_response(
    session: ChatSession,
    user_id: str,
    user_content: str,
    db: AsyncSession,
) -> AsyncGenerator[str, None]:
    # 1. Persist the user message
    await service.add_message(db, str(session.id), "user", user_content)

    # 2. Load full history as LangChain messages
    db_messages = await service.list_messages(db, str(session.id), user_id)
    lc_messages = [
        HumanMessage(content=m.content) if m.role == "user" else AIMessage(content=m.content)
        for m in db_messages
    ]

    # 3. Resolve document scope and build the orchestrator graph
    resolved_document_ids = await _resolve_document_ids(db, user_id, session.document_scope)
    retriever_tool = make_retriever_tool(session.document_scope, user_id)
    graph = build_orchestrator_graph(retriever_tool, user_id, resolved_document_ids)

    # 4. Stream graph events via the shared runner
    try:
        async for kind, payload in stream_agent_turn(graph, lc_messages, resolved_document_ids):
            if kind == "token":
                yield f"event: delta\ndata: {json.dumps({'text': payload})}\n\n"
                continue

            # kind == "result" — the turn is complete
            result = payload
            final_content = result.content or "(no response generated)"
            asst_msg = await service.add_message(
                db, str(session.id), "assistant", final_content,
                result.cited_sources or None, result.handled_by,
            )
            await metrics_service.record_agent_run(
                db,
                user_id=user_id,
                session_id=str(session.id),
                message_id=str(asst_msg.id),
                handled_by=result.handled_by,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                node_latencies_ms=result.node_latencies_ms,
                total_latency_ms=result.total_latency_ms,
            )
            yield (
                f"event: done\ndata: "
                f"{json.dumps({'message_id': str(asst_msg.id), 'cited_chunk_ids': result.cited_sources})}\n\n"
            )

    except Exception as exc:
        logger.exception("Agent stream error for session %s", session.id)
        yield f"event: error\ndata: {json.dumps({'detail': str(exc)})}\n\n"


@router.post("/sessions/{session_id}/messages")
async def send_message(
    session_id: uuid.UUID,
    body: schemas.MessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = await service.get_session(db, str(session_id), str(current_user.id))
    return StreamingResponse(
        _stream_agent_response(session, str(current_user.id), body.content, db),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
