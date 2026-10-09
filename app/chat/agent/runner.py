import time
from dataclasses import dataclass, field
from typing import AsyncGenerator, Optional

# Nodes whose streamed tokens are the user-visible answer text. Distinctly
# named per sub-agent so this bare-name match stays unambiguous across
# subgraphs.
STREAMING_ANSWER_NODES = (
    "generate_answer",
    "generate_query_or_respond",
    "web_answer",
    "synth_answer",
)

# Top-level subgraph-as-node names whose on_chain_end carries the final
# merged state (including handled_by) for this turn.
SUBGRAPH_NODES = ("rag_subgraph", "web_research_subgraph", "multi_doc_synthesis_subgraph")


@dataclass
class AgentTurnResult:
    content: str = ""
    # [{"document_id": str, "pages": [int, ...]}, ...]
    cited_sources: list = field(default_factory=list)
    handled_by: Optional[str] = None
    # node name -> total ms spent in that node across all invocations this turn
    # (a rewrite loop invokes some nodes more than once; durations are summed).
    node_latencies_ms: dict = field(default_factory=dict)
    total_latency_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    # document_id -> retrieved chunk texts, for judge-based eval scoring only
    # (not persisted — too large to store per chat turn).
    retrieved_text: dict = field(default_factory=dict)


async def stream_agent_turn(
    graph, lc_messages, resolved_document_ids
) -> AsyncGenerator[tuple, None]:
    """
    Run one orchestrator-graph turn, yielding ("token", str) chunks as they
    stream and finally ("result", AgentTurnResult) once the run completes.

    Shared by the SSE chat endpoint (app/chat/router.py) and the eval harness
    (app/evals/runner.py) so citation/handled_by/token/latency extraction
    can't drift between the two call sites.
    """
    start = time.perf_counter()
    full_response: list[str] = []
    cited_pages: dict[str, list[int]] = {}
    retrieved_text: dict[str, list[str]] = {}
    handled_by: Optional[str] = None
    node_latencies_ms: dict[str, float] = {}
    node_starts: dict[str, float] = {}
    prompt_tokens = 0
    completion_tokens = 0

    async for event in graph.astream_events(
        {"messages": lc_messages, "resolved_document_ids": resolved_document_ids},
        version="v2",
    ):
        kind = event["event"]
        node = event.get("metadata", {}).get("langgraph_node", "")
        run_id = event.get("run_id")

        # Per-node latency bookkeeping — independent of the classification
        # chain below, since on_chain_end fires for every node, not just the
        # ones that carry citations/handled_by.
        if kind == "on_chain_start" and node:
            node_starts[run_id] = time.perf_counter()
        elif kind == "on_chain_end" and node:
            t0 = node_starts.pop(run_id, None)
            if t0 is not None:
                elapsed = (time.perf_counter() - t0) * 1000
                node_latencies_ms[node] = node_latencies_ms.get(node, 0.0) + elapsed

        # Stream text tokens from LLM answer-producing nodes
        if kind == "on_chat_model_stream" and node in STREAMING_ANSWER_NODES:
            text = event["data"]["chunk"].content
            if text:  # empty when the LLM is streaming a tool call instead of text
                full_response.append(text)
                yield ("token", text)

        # Token usage — present on every chat model call (grader, rewriter,
        # supervisor classifier, answer generators), nested under whichever
        # node invoked it.
        elif kind == "on_chat_model_end":
            output = event["data"].get("output")
            message = getattr(output, "message", output)
            usage = getattr(message, "usage_metadata", None)
            if usage:
                prompt_tokens += usage.get("input_tokens", 0) or 0
                completion_tokens += usage.get("output_tokens", 0) or 0

        # RAG found nothing relevant and escalated to web-research — any
        # citations accumulated during those failed attempts are stale,
        # since the eventual answer won't be grounded in them.
        elif kind == "on_chain_end" and node == "no_relevant_docs":
            cited_pages = {}
            retrieved_text = {}

        # Capture which sub-agent produced the final answer
        elif kind == "on_chain_end" and node in SUBGRAPH_NODES:
            output = event["data"].get("output")
            if isinstance(output, dict) and output.get("handled_by"):
                handled_by = output["handled_by"]

        # Reset at the start of the RAG subgraph's own retrieval rounds so
        # only the final rewrite-loop pass's pages are kept; the synthesis
        # subgraph's N-way fan-out must NOT reset between its own calls,
        # or all but the last document's citations would be lost.
        elif kind == "on_retriever_start":
            checkpoint_ns = event.get("metadata", {}).get("langgraph_checkpoint_ns", "")
            if checkpoint_ns.startswith("rag_subgraph"):
                cited_pages = {}
                retrieved_text = {}

        # Capture which source documents (and pages) were actually retrieved
        elif kind == "on_retriever_end":
            for doc in event["data"].get("output", []):
                doc_id = doc.metadata.get("document_id")
                if not doc_id:
                    continue
                cited_pages.setdefault(doc_id, [])
                retrieved_text.setdefault(doc_id, [])
                page = doc.metadata.get("page")  # present for PDFs (0-indexed)
                if page is not None and page not in cited_pages[doc_id]:
                    cited_pages[doc_id].append(page)
                retrieved_text[doc_id].append(doc.page_content)

    cited_sources = [
        {"document_id": doc_id, "pages": sorted(pages)}
        for doc_id, pages in cited_pages.items()
    ]

    yield ("result", AgentTurnResult(
        content="".join(full_response),
        cited_sources=cited_sources,
        handled_by=handled_by,
        node_latencies_ms=node_latencies_ms,
        total_latency_ms=(time.perf_counter() - start) * 1000,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        retrieved_text=retrieved_text,
    ))
