from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.types import Command
from pydantic import BaseModel, create_model

from app import runtime_config
from app.chat.agent.schemas import OrchestratorState
from app.config import settings

_SUPERVISOR_SYSTEM = (
    "You are a routing supervisor for a document question-answering assistant. The user "
    "has uploaded private documents you have no prior knowledge of — they may reference "
    "companies, people, policies, or topics you don't recognize, including entirely "
    "fictional or internal ones. Not recognizing a name is NEVER a reason to pick "
    "web_research — it just means the answer may be in the user's documents.\n"
    "Given the user's question, decide which specialist should handle it:\n"
    "- rag: PREFER THIS by default. Pick it whenever the question could plausibly be "
    "answered from the user's uploaded documents, even if you don't recognize the "
    "subject — e.g. a question about a specific company's policy, a named person, or "
    "any detail that sounds like it could come from an uploaded document.\n"
    "- web_research: ONLY for questions that are clearly about general public knowledge, "
    "current events, or real-world facts with no plausible connection to a private "
    "document (e.g. the weather, today's news, how something works in general).\n"
    "- multi_doc_synthesis: the question explicitly asks to compare, contrast, or "
    "synthesize information across multiple uploaded documents.\n"
    "When genuinely uncertain between rag and web_research, choose rag."
)


def _route_decision_model(allowed_routes: list[str]) -> type[BaseModel]:
    route_literal = Literal[tuple(allowed_routes)]
    return create_model(
        "RouteDecision",
        route=(route_literal, ...),
        reasoning=(str, ...),
    )


def classify_route(question: str, allowed_routes: list[str]) -> str:
    if len(allowed_routes) == 1:
        return allowed_routes[0]

    api_key = runtime_config.get("api_key") or settings.api_key
    base_url = runtime_config.get("openai_api_base") or settings.openai_api_base
    model = runtime_config.get("llm_model") or settings.llm_model
    llm = ChatOpenAI(model=model, api_key=api_key, base_url=base_url)

    decision_model = _route_decision_model(allowed_routes)
    structured_llm = llm.with_structured_output(decision_model)
    decision = structured_llm.invoke([
        SystemMessage(content=_SUPERVISOR_SYSTEM),
        HumanMessage(content=question),
    ])
    return decision.route


def make_supervisor_node(allowed_routes: list[str]):
    def supervisor(state: OrchestratorState) -> Command:
        human_msg = next(
            (m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)), None
        )
        question = human_msg.content if human_msg else ""
        route = classify_route(question, allowed_routes)
        return Command(goto=f"{route}_subgraph", update={"route": route})

    return supervisor
