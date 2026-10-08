from typing import Literal, Optional
from pydantic import BaseModel
from langgraph.graph import MessagesState

Route = Literal["rag", "web_research", "multi_doc_synthesis"]


class GradeDocuments(BaseModel):
    binary_score: Literal["yes", "no"]


class RouteDecision(BaseModel):
    route: Route
    reasoning: str


class AgentState(MessagesState):
    """RAG sub-agent state. `route`/`handled_by` are pass-through channels only
    (unused by RAG's own logic) — a subgraph-local state schema must declare
    any field that needs to cross the subgraph boundary back to the parent,
    even when the parent's schema already declares it, or the value is
    silently dropped."""
    rewrite_count: int
    route: Optional[str]
    handled_by: Optional[str]


class WebResearchState(MessagesState):
    handled_by: Optional[str]


class MultiDocSynthesisState(MessagesState):
    resolved_document_ids: list[str]
    handled_by: Optional[str]


class OrchestratorState(MessagesState):
    resolved_document_ids: list[str]
    route: Optional[Route]
    handled_by: Optional[str]
