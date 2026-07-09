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
        patch("app.chat.router.build_graph", return_value=mock_graph),
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
        patch("app.chat.router.build_graph", return_value=mock_graph),
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
