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
from app.db.models import ChatSession, Document, DocumentStatus, User
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


# Nodes whose streamed tokens become SSE `delta` events. Distinctly named per
# sub-agent so this bare-name match stays unambiguous across subgraphs.
_STREAMING_ANSWER_NODES = (
    "generate_answer",
    "generate_query_or_respond",
    "web_answer",
    "synth_answer",
)

# Top-level subgraph-as-node names whose on_chain_end carries the final
# merged state (including handled_by) for this turn.
_SUBGRAPH_NODES = ("rag_subgraph", "web_research_subgraph", "multi_doc_synthesis_subgraph")


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

    # 4. Stream graph events
    full_response: list[str] = []
    # Maps document_id -> sorted list of page numbers (0-indexed from PyPDFLoader)
    cited_pages: dict[str, list[int]] = {}
    handled_by: str | None = None

    try:
        async for event in graph.astream_events(
            {"messages": lc_messages, "resolved_document_ids": resolved_document_ids},
            version="v2",
        ):
            kind = event["event"]
            node = event.get("metadata", {}).get("langgraph_node", "")

            # Stream text tokens from LLM answer-producing nodes
            if kind == "on_chat_model_stream" and node in _STREAMING_ANSWER_NODES:
                text = event["data"]["chunk"].content
                if text:  # empty when the LLM is streaming a tool call instead of text
                    full_response.append(text)
                    yield f"event: delta\ndata: {json.dumps({'text': text})}\n\n"

            # RAG found nothing relevant and escalated to web-research — any
            # citations accumulated during those failed attempts are stale,
            # since the eventual answer won't be grounded in them.
            elif kind == "on_chain_end" and node == "no_relevant_docs":
                cited_pages = {}

            # Capture which sub-agent produced the final answer
            elif kind == "on_chain_end" and node in _SUBGRAPH_NODES:
                output = event["data"].get("output")
                if isinstance(output, dict) and output.get("handled_by"):
                    handled_by = output["handled_by"]

            # Reset at the start of the RAG subgraph's own retrieval rounds so
            # only the final rewrite-loop pass's pages are kept; the synthesis
            # subgraph's N-way fan-out must NOT reset between its own calls,
            # or all but the last document's citations would be lost.
            elif kind == "on_retriever_start":
                checkpoint_ns = event.get("metadata", {}).get("langgraph_checkpoint_ns", "")
                if checkpoint_ns.startswith("rag_subgraph"):
                    cited_pages = {}

            # Capture which source documents (and pages) were actually retrieved
            elif kind == "on_retriever_end":
                for doc in event["data"].get("output", []):
                    doc_id = doc.metadata.get("document_id")
                    if not doc_id:
                        continue
                    if doc_id not in cited_pages:
                        cited_pages[doc_id] = []
                    page = doc.metadata.get("page")  # present for PDFs (0-indexed)
                    if page is not None and page not in cited_pages[doc_id]:
                        cited_pages[doc_id].append(page)

        cited_sources = [
            {"document_id": doc_id, "pages": sorted(pages)}
            for doc_id, pages in cited_pages.items()
        ]

        # 5. Persist the completed assistant message
        final_content = "".join(full_response) or "(no response generated)"
        asst_msg = await service.add_message(
            db, str(session.id), "assistant", final_content, cited_sources or None, handled_by
        )
        yield (
            f"event: done\ndata: "
            f"{json.dumps({'message_id': str(asst_msg.id), 'cited_chunk_ids': cited_sources})}\n\n"
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
