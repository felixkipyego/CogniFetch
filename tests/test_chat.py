import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_session_default_title(client, auth_headers):
    resp = await client.post("/chat/sessions", json={}, headers=auth_headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "New Chat"
    assert data["document_scope"] is None


@pytest.mark.asyncio
async def test_create_session_with_scope(client, auth_headers):
    doc_id = str(uuid.uuid4())
    resp = await client.post(
        "/chat/sessions",
        json={"title": "My Session", "document_scope": [doc_id]},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "My Session"
    assert doc_id in data["document_scope"]


@pytest.mark.asyncio
async def test_list_sessions(client, auth_headers):
    await client.post("/chat/sessions", json={"title": "S1"}, headers=auth_headers)
    await client.post("/chat/sessions", json={"title": "S2"}, headers=auth_headers)

    resp = await client.get("/chat/sessions", headers=auth_headers)
    assert resp.status_code == 200
    titles = [s["title"] for s in resp.json()]
    assert "S1" in titles
    assert "S2" in titles


@pytest.mark.asyncio
async def test_sessions_scoped_to_user(client, auth_headers):
    await client.post("/chat/sessions", json={"title": "Owner session"}, headers=auth_headers)

    # Second user sees empty list
    email2 = f"{uuid.uuid4()}@example.com"
    await client.post("/auth/register", json={"email": email2, "password": "pw"})
    login2 = await client.post("/auth/login", json={"email": email2, "password": "pw"})
    headers2 = {"Authorization": f"Bearer {login2.json()['access_token']}"}

    resp = await client.get("/chat/sessions", headers=headers2)
    assert resp.json() == []


@pytest.mark.asyncio
async def test_create_session_requires_auth(client):
    resp = await client.post("/chat/sessions", json={})
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

async def _make_session(client, auth_headers, title="Test") -> str:
    resp = await client.post("/chat/sessions", json={"title": title}, headers=auth_headers)
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_list_messages_empty(client, auth_headers):
    session_id = await _make_session(client, auth_headers)
    resp = await client.get(f"/chat/sessions/{session_id}/messages", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_messages_wrong_session(client, auth_headers):
    resp = await client.get(f"/chat/sessions/{uuid.uuid4()}/messages", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_send_message_streams_sse(client, auth_headers):
    """
    Verify the SSE endpoint returns a streaming response with the expected
    event structure, using a mocked LangGraph graph.
    """
    session_id = await _make_session(client, auth_headers)

    async def fake_astream_events(*args, **kwargs):
        # Simulate: on_chat_model_stream from generate_answer
        yield {
            "event": "on_chat_model_stream",
            "metadata": {"langgraph_node": "generate_answer"},
            "data": {"chunk": MagicMock(content="Hello ")},
        }
        yield {
            "event": "on_chat_model_stream",
            "metadata": {"langgraph_node": "generate_answer"},
            "data": {"chunk": MagicMock(content="world!")},
        }

    mock_graph = MagicMock()
    mock_graph.astream_events = fake_astream_events

    with (
        patch("app.chat.router.make_retriever_tool"),
        patch("app.chat.router.build_orchestrator_graph", return_value=mock_graph),
    ):
        resp = await client.post(
            f"/chat/sessions/{session_id}/messages",
            json={"content": "What is CogniFetch?"},
            headers=auth_headers,
        )

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]

    body = resp.text
    assert "event: delta" in body
    assert "Hello " in body
    assert "event: done" in body


@pytest.mark.asyncio
async def test_send_message_persists_history(client, auth_headers):
    """After a streamed response, both user and assistant messages should be in history."""
    session_id = await _make_session(client, auth_headers)

    async def fake_astream_events(*args, **kwargs):
        yield {
            "event": "on_chat_model_stream",
            "metadata": {"langgraph_node": "generate_answer"},
            "data": {"chunk": MagicMock(content="The answer.")},
        }

    mock_graph = MagicMock()
    mock_graph.astream_events = fake_astream_events

    with (
        patch("app.chat.router.make_retriever_tool"),
        patch("app.chat.router.build_orchestrator_graph", return_value=mock_graph),
    ):
        await client.post(
            f"/chat/sessions/{session_id}/messages",
            json={"content": "Tell me something"},
            headers=auth_headers,
        )

    # Check history
    hist = await client.get(f"/chat/sessions/{session_id}/messages", headers=auth_headers)
    assert hist.status_code == 200
    messages = hist.json()
    roles = [m["role"] for m in messages]
    assert "user" in roles
    assert "assistant" in roles


# ---------------------------------------------------------------------------
# Multi-agent orchestration (Phase 2)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("route,node_name", [
    ("rag", "rag_subgraph"),
    ("web_research", "web_research_subgraph"),
    ("multi_doc_synthesis", "multi_doc_synthesis_subgraph"),
])
async def test_send_message_records_handled_by(client, auth_headers, route, node_name):
    """Whichever sub-agent subgraph actually answers, its handled_by tag
    should be the one persisted on the assistant message."""
    session_id = await _make_session(client, auth_headers)

    async def fake_astream_events(*args, **kwargs):
        yield {
            "event": "on_chat_model_stream",
            "metadata": {"langgraph_node": "generate_answer"},
            "data": {"chunk": MagicMock(content="answer")},
        }
        yield {
            "event": "on_chain_end",
            "metadata": {"langgraph_node": node_name},
            "data": {"output": {"handled_by": route, "messages": []}},
        }

    mock_graph = MagicMock()
    mock_graph.astream_events = fake_astream_events

    with (
        patch("app.chat.router.make_retriever_tool"),
        patch("app.chat.router.build_orchestrator_graph", return_value=mock_graph),
    ):
        await client.post(
            f"/chat/sessions/{session_id}/messages",
            json={"content": "question"},
            headers=auth_headers,
        )

    hist = await client.get(f"/chat/sessions/{session_id}/messages", headers=auth_headers)
    assistant_msgs = [m for m in hist.json() if m["role"] == "assistant"]
    assert assistant_msgs[-1]["handled_by"] == route


@pytest.mark.asyncio
async def test_escalation_from_rag_to_web_research(client, auth_headers):
    """RAG finds nothing relevant and hands off to web-research — the final
    message should carry the escalation's handled_by tag, the streamed
    answer should come from web-research's own node, and stale citations
    from RAG's failed retrieval attempts should be discarded."""
    session_id = await _make_session(client, auth_headers)
    fake_doc_id = str(uuid.uuid4())

    async def fake_astream_events(*args, **kwargs):
        yield {
            "event": "on_retriever_start",
            "metadata": {
                "langgraph_node": "retrieve",
                "langgraph_checkpoint_ns": "rag_subgraph:abc|retrieve:def",
            },
            "data": {},
        }
        fake_doc = MagicMock()
        fake_doc.metadata = {"document_id": fake_doc_id, "page": 0}
        yield {
            "event": "on_retriever_end",
            "metadata": {"langgraph_node": "retrieve"},
            "data": {"output": [fake_doc]},
        }
        # no_relevant_docs now always returns a Command, not {"messages": [...]}
        yield {
            "event": "on_chain_end",
            "metadata": {"langgraph_node": "no_relevant_docs"},
            "data": {"output": MagicMock()},
        }
        yield {
            "event": "on_chat_model_stream",
            "metadata": {"langgraph_node": "web_answer"},
            "data": {"chunk": MagicMock(content="Web answer text")},
        }
        yield {
            "event": "on_chain_end",
            "metadata": {"langgraph_node": "web_research_subgraph"},
            "data": {"output": {"handled_by": "rag_escalated_web_research", "messages": []}},
        }

    mock_graph = MagicMock()
    mock_graph.astream_events = fake_astream_events

    with (
        patch("app.chat.router.make_retriever_tool"),
        patch("app.chat.router.build_orchestrator_graph", return_value=mock_graph),
    ):
        resp = await client.post(
            f"/chat/sessions/{session_id}/messages",
            json={"content": "obscure question"},
            headers=auth_headers,
        )

    assert "Web answer text" in resp.text

    hist = await client.get(f"/chat/sessions/{session_id}/messages", headers=auth_headers)
    assistant_msgs = [m for m in hist.json() if m["role"] == "assistant"]
    last = assistant_msgs[-1]
    assert last["handled_by"] == "rag_escalated_web_research"
    assert last["cited_chunk_ids"] is None  # stale RAG citations discarded on escalation


def test_allowed_routes_by_document_count():
    from app.chat.agent.orchestrator import _allowed_routes

    assert _allowed_routes([]) == ["web_research"]
    assert _allowed_routes(["doc-a"]) == ["rag", "web_research"]
    assert _allowed_routes(["doc-a", "doc-b"]) == ["rag", "web_research", "multi_doc_synthesis"]


def test_classify_route_single_allowed_route_short_circuits():
    """With only one legal route, no LLM call should be needed at all."""
    from app.chat.agent.supervisor import classify_route

    with patch("app.chat.agent.supervisor.ChatOpenAI") as MockLLM:
        result = classify_route("anything", ["web_research"])

    MockLLM.assert_not_called()
    assert result == "web_research"


def test_classify_route_uses_structured_output_when_multiple_allowed():
    from app.chat.agent import supervisor as supervisor_module

    fake_decision = MagicMock(route="web_research")

    with patch("app.chat.agent.supervisor.ChatOpenAI") as MockLLM:
        MockLLM.return_value.with_structured_output.return_value.invoke.return_value = fake_decision
        result = supervisor_module.classify_route("what's the weather", ["rag", "web_research"])

    assert result == "web_research"


def test_web_search_graceful_when_tavily_key_missing():
    from langchain_core.messages import HumanMessage
    from app.chat.agent.subagents.web_research import web_search

    with patch("app.chat.agent.subagents.web_research.settings") as mock_settings:
        mock_settings.tavily_api_key = ""
        result = web_search({"messages": [HumanMessage(content="anything")]})

    assert "not configured" in result["messages"][0].content.lower()


def test_web_answer_tags_unavailable_when_tavily_key_missing():
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
    from app.chat.agent.subagents.web_research import web_answer

    with (
        patch("app.chat.agent.subagents.web_research.settings") as mock_settings,
        patch("app.chat.agent.subagents.web_research._llm") as mock_llm,
    ):
        mock_settings.tavily_api_key = ""
        mock_llm.return_value.invoke.return_value = AIMessage(content="no results")
        result = web_answer({
            "messages": [HumanMessage(content="q"), SystemMessage(content="not configured")],
        })

    assert result["handled_by"] == "web_research_unavailable"
