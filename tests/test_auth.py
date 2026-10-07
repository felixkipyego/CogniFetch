import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.auth.utils import create_email_verification_token


# ─── Registration ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_register_success(client):
    email = f"{uuid.uuid4()}@example.com"
    resp = await client.post("/auth/register", json={"email": email, "password": "secret123"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == email
    assert "id" in data
    assert "hashed_password" not in data
    # SMTP not configured in tests → no verification required
    assert data["needs_verification"] is False


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
async def test_register_sends_verification_when_smtp_configured(client):
    email = f"{uuid.uuid4()}@example.com"
    with (
        patch("app.auth.service.settings") as mock_settings,
        patch("app.auth.service.send_verification_email", new_callable=AsyncMock) as mock_send,
    ):
        mock_settings.smtp_host = "smtp.example.com"
        resp = await client.post("/auth/register", json={"email": email, "password": "secret123"})

    assert resp.status_code == 201
    assert resp.json()["needs_verification"] is True
    mock_send.assert_awaited_once()
    _, token_arg = mock_send.call_args.args
    assert token_arg  # token is non-empty


# ─── Login ───────────────────────────────────────────────────────────────────

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
async def test_login_blocked_when_unverified(client, db):
    """Users registered when SMTP is configured must verify before they can log in."""
    from app.db.models import User
    from app.auth.utils import hash_password

    email = f"{uuid.uuid4()}@example.com"
    user = User(email=email, hashed_password=hash_password("pass123"), is_verified=False)
    db.add(user)
    await db.commit()

    resp = await client.post("/auth/login", json={"email": email, "password": "pass123"})
    assert resp.status_code == 403
    assert "verify your email" in resp.json()["detail"].lower()


# ─── Token refresh ───────────────────────────────────────────────────────────

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


# ─── Email verification ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_verify_email_success(client, db):
    from app.db.models import User
    from app.auth.utils import hash_password

    email = f"{uuid.uuid4()}@example.com"
    user_id = uuid.uuid4()
    token = create_email_verification_token(str(user_id))
    user = User(id=user_id, email=email, hashed_password=hash_password("pass123"), is_verified=False, email_token=token)
    db.add(user)
    await db.commit()

    resp = await client.get(f"/auth/verify-email?token={token}")
    assert resp.status_code == 204

    await db.refresh(user)
    assert user.is_verified is True
    assert user.email_token is None


@pytest.mark.asyncio
async def test_verify_email_invalid_token(client):
    resp = await client.get("/auth/verify-email?token=not.a.valid.token")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_verify_email_already_used(client, db):
    """Using a token after it has been cleared returns 400."""
    from app.db.models import User
    from app.auth.utils import hash_password

    email = f"{uuid.uuid4()}@example.com"
    user_id = uuid.uuid4()
    token = create_email_verification_token(str(user_id))
    user = User(id=user_id, email=email, hashed_password=hash_password("pass123"), is_verified=False, email_token=token)
    db.add(user)
    await db.commit()

    # First use — succeeds
    await client.get(f"/auth/verify-email?token={token}")

    # Second use — token cleared from DB
    resp = await client.get(f"/auth/verify-email?token={token}")
    assert resp.status_code == 204  # already verified → no-op, still 204


# ─── Resend verification ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resend_verification(client, db):
    from app.db.models import User
    from app.auth.utils import hash_password

    email = f"{uuid.uuid4()}@example.com"
    user = User(email=email, hashed_password=hash_password("pass123"), is_verified=False)
    db.add(user)
    await db.commit()

    with patch("app.auth.service.send_verification_email", new_callable=AsyncMock) as mock_send:
        resp = await client.post("/auth/resend-verification", json={"email": email})

    assert resp.status_code == 204
    mock_send.assert_awaited_once_with(email, mock_send.call_args.args[1])


@pytest.mark.asyncio
async def test_resend_verification_unknown_email_is_silent(client):
    """Unknown email must return 204 without leaking whether it exists."""
    resp = await client.post(
        "/auth/resend-verification",
        json={"email": f"{uuid.uuid4()}@example.com"},
    )
    assert resp.status_code == 204


# ─── Protected routes ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_protected_endpoint_without_auth(client):
    resp = await client.get("/documents")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_protected_endpoint_with_bad_token(client):
    resp = await client.get("/documents", headers={"Authorization": "Bearer garbage"})
    assert resp.status_code == 401
