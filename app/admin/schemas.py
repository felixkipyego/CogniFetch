from datetime import datetime
from pydantic import BaseModel


class UserAdminOut(BaseModel):
    id: str
    email: str
    is_admin: bool
    created_at: datetime
    document_count: int

    class Config:
        from_attributes = True


class UserAdminUpdate(BaseModel):
    is_admin: bool


class ConfigOut(BaseModel):
    key: str
    value: str          # api_key is always returned masked
    source: str         # "database" | "environment"
    updated_at: datetime | None = None


class ConfigPatch(BaseModel):
    changes: dict[str, str]   # key → new value; blank value = delete DB override


class RouteStatsOut(BaseModel):
    run_count: int
    p50_latency_ms: float
    p95_latency_ms: float
    avg_latency_ms: float
    prompt_tokens: int
    completion_tokens: int
    total_cost_usd: float | None   # None = no run in this bucket had a priced model
    runs_with_unknown_cost: int


class MetricsSummaryOut(BaseModel):
    window_run_count: int           # how many of the most recent runs this summary covers
    overall: RouteStatsOut
    by_route: dict[str, RouteStatsOut]   # keyed by handled_by (e.g. "rag", "web_research", "unknown")
    avg_node_latency_ms: dict[str, float]
