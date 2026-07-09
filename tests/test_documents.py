import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_s3_client():
    s3 = MagicMock()
    s3.put_object.return_value = {}
    s3.delete_object.return_value = {}
    s3.download_file.return_value = None
    return s3


TXT_FILE = ("test.txt", b"Hello CogniFetch " * 50, "text/plain")


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upload_document(client, auth_headers):
    with (
        patch("app.documents.storage.make_s3_client", return_value=_fake_s3_client()),
        patch("app.documents.router.ingest_document", new_callable=AsyncMock),
    ):
        resp = await client.post(
            "/documents",
            headers=auth_headers,
            files={"file": TXT_FILE},
        )

    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "pending"
    assert data["filename"] == "test.txt"
    assert data["mime_type"] == "text/plain"
    return data["id"]


@pytest.mark.asyncio
async def test_upload_unsupported_type(client, auth_headers):
    with patch("app.documents.storage.make_s3_client", return_value=_fake_s3_client()):
        resp = await client.post(
            "/documents",
            headers=auth_headers,
            files={"file": ("image.png", b"\x89PNG", "image/png")},
        )
    assert resp.status_code == 415


@pytest.mark.asyncio
async def test_upload_requires_auth(client):
    resp = await client.post("/documents", files={"file": TXT_FILE})
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# List & Get
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_documents_empty(client, auth_headers):
    resp = await client.get("/documents", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_list_shows_own_documents_only(client, auth_headers, session_maker):
    """Two different users should not see each other's documents."""
    # Upload one document as the fixture user
    with (
        patch("app.documents.storage.make_s3_client", return_value=_fake_s3_client()),
        patch("app.documents.router.ingest_document", new_callable=AsyncMock),
    ):
        up = await client.post("/documents", headers=auth_headers, files={"file": TXT_FILE})
    assert up.status_code == 202

    # Register a second user and check their list is empty
    email2 = f"{uuid.uuid4()}@example.com"
    await client.post("/auth/register", json={"email": email2, "password": "pw"})
    login2 = await client.post("/auth/login", json={"email": email2, "password": "pw"})
    headers2 = {"Authorization": f"Bearer {login2.json()['access_token']}"}

    resp2 = await client.get("/documents", headers=headers2)
    assert resp2.status_code == 200
    assert resp2.json() == []


@pytest.mark.asyncio
async def test_get_document(client, auth_headers):
    with (
        patch("app.documents.storage.make_s3_client", return_value=_fake_s3_client()),
        patch("app.documents.router.ingest_document", new_callable=AsyncMock),
    ):
        up = await client.post("/documents", headers=auth_headers, files={"file": TXT_FILE})
    doc_id = up.json()["id"]

    resp = await client.get(f"/documents/{doc_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == doc_id


@pytest.mark.asyncio
async def test_get_document_not_found(client, auth_headers):
    resp = await client.get(f"/documents/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_document_wrong_owner(client, auth_headers):
    """Another user cannot fetch a document they don't own."""
    with (
        patch("app.documents.storage.make_s3_client", return_value=_fake_s3_client()),
        patch("app.documents.router.ingest_document", new_callable=AsyncMock),
    ):
        up = await client.post("/documents", headers=auth_headers, files={"file": TXT_FILE})
    doc_id = up.json()["id"]

    email2 = f"{uuid.uuid4()}@example.com"
    await client.post("/auth/register", json={"email": email2, "password": "pw"})
    login2 = await client.post("/auth/login", json={"email": email2, "password": "pw"})
    headers2 = {"Authorization": f"Bearer {login2.json()['access_token']}"}

    resp = await client.get(f"/documents/{doc_id}", headers=headers2)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_document(client, auth_headers):
    with (
        patch("app.documents.storage.make_s3_client", return_value=_fake_s3_client()),
        patch("app.documents.router.ingest_document", new_callable=AsyncMock),
    ):
        up = await client.post("/documents", headers=auth_headers, files={"file": TXT_FILE})
    doc_id = up.json()["id"]

    with (
        patch("app.documents.storage.make_s3_client", return_value=_fake_s3_client()),
        patch("app.documents.ingestion.delete_document_chunks", new_callable=AsyncMock),
    ):
        resp = await client.delete(f"/documents/{doc_id}", headers=auth_headers)

    assert resp.status_code == 204

    # Confirm it is gone
    get_resp = await client.get(f"/documents/{doc_id}", headers=auth_headers)
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_nonexistent_document(client, auth_headers):
    with patch("app.documents.storage.make_s3_client", return_value=_fake_s3_client()):
        resp = await client.delete(f"/documents/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404
