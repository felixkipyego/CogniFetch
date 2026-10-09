from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph

from app import runtime_config
from app.chat.agent.retriever import make_per_document_retrievers
from app.chat.agent.schemas import MultiDocSynthesisState
from app.config import settings

_SYNTHESIS_SYSTEM = SystemMessage(content=(
    "You are a document comparison assistant. Answer ONLY from the per-document excerpts "
    "shown in this conversation. Explicitly compare/contrast across the documents where "
    "the question asks for it. If the excerpts don't contain enough information to answer, "
    "say so plainly — do not invent or extrapolate."
))


def _llm(streaming: bool = False):
    api_key = runtime_config.get("api_key") or settings.api_key
    base_url = runtime_config.get("openai_api_base") or settings.openai_api_base
    model = runtime_config.get("llm_model") or settings.llm_model
    # stream_usage=True: see app/chat/agent/nodes.py's _llm for why this is needed.
    return ChatOpenAI(
        model=model, streaming=streaming, api_key=api_key, base_url=base_url, stream_usage=True
    )


def _format_per_document(document_id: str, docs: list) -> str:
    excerpts = "\n".join(d.page_content for d in docs)
    return f"Document (id={document_id}):\n{excerpts}"


def make_synth_retrieve_node(user_id: str):
    async def synth_retrieve(state: MultiDocSynthesisState):
        human_msg = next(
            (m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)), None
        )
        question = human_msg.content if human_msg else ""
        document_ids = state["resolved_document_ids"]

        retrievers = make_per_document_retrievers(document_ids, user_id)
        # Sequential, not asyncio.gather: PGVector's own async lazy-init guard
        # (`_async_init`) is documented in its source as having a possible race
        # under concurrent first use. Not latency-critical here, so sequential
        # avoids relying on that guard being safe under concurrency at all.
        results = [await retriever.ainvoke(question) for retriever in retrievers.values()]

        sections = [
            _format_per_document(doc_id, docs)
            for doc_id, docs in zip(retrievers.keys(), results)
        ]
        return {"messages": [SystemMessage(content="\n\n".join(sections))]}

    return synth_retrieve


def synth_answer(state: MultiDocSynthesisState):
    messages = [_SYNTHESIS_SYSTEM] + list(state["messages"])
    response = _llm(streaming=True).invoke(messages)
    return {"messages": [response], "handled_by": "multi_doc_synthesis"}


def build_multi_doc_synthesis_subgraph(user_id: str):
    graph = StateGraph(MultiDocSynthesisState)
    graph.add_node("synth_retrieve", make_synth_retrieve_node(user_id))
    graph.add_node("synth_answer", synth_answer)
    graph.set_entry_point("synth_retrieve")
    graph.add_edge("synth_retrieve", "synth_answer")
    graph.add_edge("synth_answer", END)
    return graph.compile()
