"""
Shared test fixtures.

Requires a Postgres test database. Create it once before running tests:

    docker-compose exec postgres psql -U cognifetch -c "CREATE DATABASE cognifetch_test;"

Then run:

    pytest
"""
import os
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.dependencies import get_db
from app.main import app

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://cognifetch:cognifetch@localhost:5432/cognifetch_test",
)


# ---------------------------------------------------------------------------
# Session-scoped engine: creates all tables once, drops them after the session
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="session")
async def engine():
    _engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield _engine
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await _engine.dispose()


@pytest.fixture(scope="session")
def session_maker(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


# ---------------------------------------------------------------------------
# Per-test DB session (does NOT roll back — tests use unique data per run)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db(session_maker) -> AsyncSession:
    async with session_maker() as session:
        yield session


# ---------------------------------------------------------------------------
# HTTP client with get_db overridden to use the test database
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def client(session_maker):
    async def _override_get_db():
        async with session_maker() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Convenience: a registered user + auth headers
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def registered_user(client):
    """Returns (email, password) of a freshly registered user."""
    email = f"user-{uuid.uuid4()}@example.com"
    password = "testpassword123"
    resp = await client.post("/auth/register", json={"email": email, "password": password})
    assert resp.status_code == 201
    return email, password


@pytest_asyncio.fixture
async def auth_headers(client, registered_user):
    """Returns Authorization headers for a logged-in test user."""
    email, password = registered_user
    resp = await client.post("/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
