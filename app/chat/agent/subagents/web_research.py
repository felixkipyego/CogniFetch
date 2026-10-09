from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langchain_tavily import TavilySearch
from langgraph.graph import END, StateGraph

from app import runtime_config
from app.chat.agent.schemas import WebResearchState
from app.config import settings

_WEB_ANSWER_SYSTEM = SystemMessage(content=(
    "You are a web research assistant. Answer the user's question using the search "
    "results provided in this conversation. If search results are unavailable or don't "
    "answer the question, say so plainly — do not guess or use outside knowledge."
))


def _llm(streaming: bool = False):
    api_key = runtime_config.get("api_key") or settings.api_key
    base_url = runtime_config.get("openai_api_base") or settings.openai_api_base
    model = runtime_config.get("llm_model") or settings.llm_model
    # stream_usage=True: see app/chat/agent/nodes.py's _llm for why this is needed.
    return ChatOpenAI(
        model=model, streaming=streaming, api_key=api_key, base_url=base_url, stream_usage=True
    )


def _format_results(results: dict) -> str:
    hits = results.get("results", [])
    if not hits:
        return "No search results found."
    return "\n\n".join(f"- {r.get('title', '')}: {r.get('content', '')}" for r in hits)


def web_search(state: WebResearchState):
    human_msg = next(
        (m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)), None
    )
    question = human_msg.content if human_msg else ""

    if not settings.tavily_api_key:
        return {
            "messages": [SystemMessage(content="Web search is not configured — no results available.")],
        }

    tool = TavilySearch(tavily_api_key=settings.tavily_api_key, max_results=5)
    results = tool.invoke({"query": question})
    return {"messages": [SystemMessage(content=f"Search results:\n{_format_results(results)}")]}


def web_answer(state: WebResearchState):
    messages = [_WEB_ANSWER_SYSTEM] + list(state["messages"])
    response = _llm(streaming=True).invoke(messages)

    if not settings.tavily_api_key:
        handled_by = "web_research_unavailable"
    else:
        handled_by = state.get("handled_by") or "web_research"

    return {"messages": [response], "handled_by": handled_by}


def build_web_research_subgraph():
    graph = StateGraph(WebResearchState)
    graph.add_node("web_search", web_search)
    graph.add_node("web_answer", web_answer)
    graph.set_entry_point("web_search")
    graph.add_edge("web_search", "web_answer")
    graph.add_edge("web_answer", END)
    return graph.compile()
