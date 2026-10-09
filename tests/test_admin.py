import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.db.models import User
from app.metrics.service import record_agent_run


async def _make_admin(db, email) -> None:
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one()
    user.is_admin = True
    await db.commit()


@pytest.mark.asyncio
async def test_metrics_requires_admin(client):
    # The very first user ever registered in a fresh DB is auto-promoted to
    # admin (app/auth/service.py's is_first_user bootstrap) — register a
    # throwaway user first so the one under test is guaranteed not to be it,
    # regardless of what other tests have already run in this session.
    await client.post("/auth/register", json={"email": f"{uuid.uuid4()}@example.com", "password": "pw"})

    email = f"{uuid.uuid4()}@example.com"
    await client.post("/auth/register", json={"email": email, "password": "pw"})
    login = await client.post("/auth/login", json={"email": email, "password": "pw"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = await client.get("/admin/metrics", headers=headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_metrics_empty_when_no_runs(client, auth_headers, registered_user, db):
    email, _ = registered_user
    await _make_admin(db, email)

    resp = await client.get("/admin/metrics", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["window_run_count"] == 0
    assert data["overall"]["run_count"] == 0
    assert data["by_route"] == {}


@pytest.mark.asyncio
async def test_metrics_aggregates_recorded_runs(client, auth_headers, registered_user, db):
    email, _ = registered_user
    await _make_admin(db, email)
    user = (await db.execute(select(User).where(User.email == email))).scalar_one()

    # Unique route tags: this suite's agent_run_metrics table is shared and
    # not rolled back between tests, so "overall"/"window_run_count" aren't
    # safe to assert exactly — by_route[unique tag] is, since nothing else
    # writes to these specific tags.
    suffix = uuid.uuid4()
    route_rag, route_web = f"rag-{suffix}", f"web_research-{suffix}"

    with patch("app.metrics.service.estimate_cost_usd", return_value=0.01):
        await record_agent_run(
            db, user_id=str(user.id), session_id=None, message_id=None,
            handled_by=route_rag, prompt_tokens=100, completion_tokens=50,
            node_latencies_ms={"generate_answer": 500.0}, total_latency_ms=800.0,
        )
        await record_agent_run(
            db, user_id=str(user.id), session_id=None, message_id=None,
            handled_by=route_web, prompt_tokens=40, completion_tokens=20,
            node_latencies_ms={"web_answer": 300.0}, total_latency_ms=400.0,
        )

    resp = await client.get("/admin/metrics", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()

    assert data["by_route"][route_rag]["run_count"] == 1
    assert data["by_route"][route_rag]["prompt_tokens"] == 100
    assert data["by_route"][route_rag]["completion_tokens"] == 50
    assert data["by_route"][route_rag]["total_cost_usd"] == 0.01
    assert data["by_route"][route_web]["run_count"] == 1
    assert data["by_route"][route_web]["total_cost_usd"] == 0.01


@pytest.mark.asyncio
async def test_metrics_unpriced_model_reports_null_cost(client, auth_headers, registered_user, db):
    email, _ = registered_user
    await _make_admin(db, email)
    user = (await db.execute(select(User).where(User.email == email))).scalar_one()

    # Unique handled_by tag so this run's bucket in by_route is isolated from
    # whatever other tests have already written into the shared (global,
    # not-rolled-back) agent_run_metrics table in this session — "overall"
    # would mix in their rows too, but by_route[this tag] can't.
    route_tag = f"unpriced-{uuid.uuid4()}"
    with patch("app.metrics.service.estimate_cost_usd", return_value=None):
        await record_agent_run(
            db, user_id=str(user.id), session_id=None, message_id=None,
            handled_by=route_tag, prompt_tokens=10, completion_tokens=5,
            node_latencies_ms={}, total_latency_ms=100.0,
        )

    resp = await client.get("/admin/metrics", headers=auth_headers)
    data = resp.json()
    assert data["by_route"][route_tag]["total_cost_usd"] is None
    assert data["by_route"][route_tag]["runs_with_unknown_cost"] == 1
