import uuid

import pytest


@pytest.mark.asyncio
async def test_register_success(client):
    email = f"{uuid.uuid4()}@example.com"
    resp = await client.post("/auth/register", json={"email": email, "password": "secret123"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == email
    assert "id" in data
    assert "hashed_password" not in data


@pytest.mark.asyncio
async def test_register_duplicate_email(client):
    email = f"{uuid.uuid4()}@example.com"
    await client.post("/auth/register", json={"email": email, "password": "secret123"})
    resp = await client.post("/auth/register", json={"email": email, "password": "other"})
    assert resp.status_code == 400
    assert "already registered" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_register_invalid_email(client):
    resp = await client.post("/auth/register", json={"email": "not-an-email", "password": "x"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_login_success(client, registered_user):
    email, password = registered_user
    resp = await client.post("/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password(client, registered_user):
    email, _ = registered_user
    resp = await client.post("/auth/login", json={"email": email, "password": "wrong"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_unknown_email(client):
    resp = await client.post(
        "/auth/login",
        json={"email": f"{uuid.uuid4()}@example.com", "password": "anything"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_refresh_success(client, registered_user):
    email, password = registered_user
    login = await client.post("/auth/login", json={"email": email, "password": password})
    refresh_token = login.json()["refresh_token"]

    resp = await client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


@pytest.mark.asyncio
async def test_refresh_with_access_token_fails(client, registered_user):
    email, password = registered_user
    login = await client.post("/auth/login", json={"email": email, "password": password})
    access_token = login.json()["access_token"]

    resp = await client.post("/auth/refresh", json={"refresh_token": access_token})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_protected_endpoint_without_auth(client):
    resp = await client.get("/documents")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_protected_endpoint_with_bad_token(client):
    resp = await client.get("/documents", headers={"Authorization": "Bearer garbage"})
    assert resp.status_code == 401
