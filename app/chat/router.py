import json
import logging
import uuid
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat import schemas, service
from app.chat.agent.graph import build_graph
from app.chat.agent.retriever import make_retriever_tool
from app.db.models import ChatSession, User
from app.dependencies import get_current_user, get_db

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

    # 3. Build retriever tool (async_mode=True — safe to call directly)
    retriever_tool = make_retriever_tool(session.document_scope, user_id)
    graph = build_graph(retriever_tool)

    # 4. Stream graph events
    full_response: list[str] = []
    cited_doc_ids: list[str] = []
    used_fallback = False  # True when no_relevant_docs node fires

    try:
        async for event in graph.astream_events({"messages": lc_messages}, version="v2"):
            kind = event["event"]
            node = event.get("metadata", {}).get("langgraph_node", "")

            # Stream text tokens from LLM answer-producing nodes
            if kind == "on_chat_model_stream" and node in (
                "generate_answer",
                "generate_query_or_respond",
            ):
                text = event["data"]["chunk"].content
                if text:  # empty when the LLM is streaming a tool call instead of text
                    full_response.append(text)
                    yield f"event: delta\ndata: {json.dumps({'text': text})}\n\n"

            # Emit the "no information found" message from the fallback node
            elif kind == "on_chain_end" and node == "no_relevant_docs":
                used_fallback = True
                msgs = event["data"].get("output", {}).get("messages", [])
                for msg in msgs:
                    text = getattr(msg, "content", str(msg))
                    if text:
                        full_response.append(text)
                        yield f"event: delta\ndata: {json.dumps({'text': text})}\n\n"

            # Capture which source documents were actually retrieved
            elif kind == "on_retriever_end":
                for doc in event["data"].get("output", []):
                    doc_id = doc.metadata.get("document_id")
                    if doc_id and doc_id not in cited_doc_ids:
                        cited_doc_ids.append(doc_id)

        # Don't cite sources when the fallback "no info" path was taken
        if used_fallback:
            cited_doc_ids = []

        # 5. Persist the completed assistant message
        final_content = "".join(full_response) or "(no response generated)"
        asst_msg = await service.add_message(
            db, str(session.id), "assistant", final_content, cited_doc_ids or None
        )
        yield (
            f"event: done\ndata: "
            f"{json.dumps({'message_id': str(asst_msg.id), 'cited_chunk_ids': cited_doc_ids})}\n\n"
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
