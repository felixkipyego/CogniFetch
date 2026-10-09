from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import runtime_config
from app.config import settings
from app.db.models import AgentRunMetric
from app.metrics.pricing import estimate_cost_usd

# How many of the most recent runs the admin summary aggregates over — keeps
# the endpoint cheap and the numbers reflective of current behavior rather
# than averaging in months-old runs from a since-changed graph/model.
_RECENT_RUNS_WINDOW = 200


async def record_agent_run(
    db: AsyncSession,
    *,
    user_id: str,
    session_id: Optional[str],
    message_id: Optional[str],
    handled_by: Optional[str],
    prompt_tokens: int,
    completion_tokens: int,
    node_latencies_ms: dict,
    total_latency_ms: float,
) -> AgentRunMetric:
    model = runtime_config.get("llm_model") or settings.llm_model
    cost_usd = estimate_cost_usd(model, prompt_tokens, completion_tokens)

    metric = AgentRunMetric(
        user_id=user_id,
        session_id=session_id,
        message_id=message_id,
        handled_by=handled_by,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=cost_usd,
        node_latencies_ms=node_latencies_ms or None,
        total_latency_ms=total_latency_ms,
    )
    db.add(metric)
    await db.commit()
    await db.refresh(metric)
    return metric


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    idx = min(len(sorted_values) - 1, int(round(pct / 100 * (len(sorted_values) - 1))))
    return sorted_values[idx]


def _bucket_stats(rows: list[AgentRunMetric]) -> dict:
    latencies = sorted(r.total_latency_ms for r in rows)
    prompt_tokens = sum(r.prompt_tokens for r in rows)
    completion_tokens = sum(r.completion_tokens for r in rows)
    known_costs = [r.cost_usd for r in rows if r.cost_usd is not None]
    return {
        "run_count": len(rows),
        "p50_latency_ms": round(_percentile(latencies, 50), 1),
        "p95_latency_ms": round(_percentile(latencies, 95), 1),
        "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else 0.0,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_cost_usd": round(sum(known_costs), 4) if known_costs else None,
        "runs_with_unknown_cost": len(rows) - len(known_costs),
    }


async def get_metrics_summary(db: AsyncSession) -> dict:
    result = await db.execute(
        select(AgentRunMetric)
        .order_by(AgentRunMetric.created_at.desc())
        .limit(_RECENT_RUNS_WINDOW)
    )
    rows = list(result.scalars().all())

    by_route: dict[str, list[AgentRunMetric]] = {}
    for row in rows:
        key = row.handled_by or "unknown"
        by_route.setdefault(key, []).append(row)

    # Aggregate per-node latency across all runs in the window, summed then
    # averaged per run so slower/rarer routes don't get drowned out.
    node_latency_totals: dict[str, float] = {}
    for row in rows:
        for node, ms in (row.node_latencies_ms or {}).items():
            node_latency_totals[node] = node_latency_totals.get(node, 0.0) + ms
    node_latency_avg_ms = {
        node: round(total / len(rows), 1) for node, total in node_latency_totals.items()
    } if rows else {}

    return {
        "window_run_count": len(rows),
        "overall": _bucket_stats(rows),
        "by_route": {route: _bucket_stats(route_rows) for route, route_rows in by_route.items()},
        "avg_node_latency_ms": node_latency_avg_ms,
    }
