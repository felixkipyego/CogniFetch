from langgraph.graph import END, START, StateGraph

from app.chat.agent.graph import build_graph
from app.chat.agent.schemas import OrchestratorState
from app.chat.agent.subagents.multi_doc_synthesis import build_multi_doc_synthesis_subgraph
from app.chat.agent.subagents.web_research import build_web_research_subgraph
from app.chat.agent.supervisor import make_supervisor_node


def _allowed_routes(resolved_document_ids: list[str]) -> list[str]:
    if not resolved_document_ids:
        return ["web_research"]
    if len(resolved_document_ids) == 1:
        return ["rag", "web_research"]
    return ["rag", "web_research", "multi_doc_synthesis"]


def build_orchestrator_graph(retriever_tool, user_id: str, resolved_document_ids: list[str]):
    """
    Shape:
      START → supervisor --Command.goto--> rag_subgraph | web_research_subgraph
                                            | multi_doc_synthesis_subgraph → END
      (rag_subgraph's no_relevant_docs node can additionally escalate to
      web_research_subgraph via Command(graph=PARENT, ...) — see nodes.py)

    `resolved_document_ids` restricts which routes the supervisor may pick:
    no documents → web_research only; one document → rag or web_research;
    two or more → all three, including cross-document synthesis.
    """
    allowed_routes = _allowed_routes(resolved_document_ids)

    graph = StateGraph(OrchestratorState)
    graph.add_node("supervisor", make_supervisor_node(allowed_routes))
    graph.add_node("rag_subgraph", build_graph(retriever_tool))
    graph.add_node("web_research_subgraph", build_web_research_subgraph())
    graph.add_node("multi_doc_synthesis_subgraph", build_multi_doc_synthesis_subgraph(user_id))

    graph.add_edge(START, "supervisor")
    graph.add_edge("rag_subgraph", END)
    graph.add_edge("web_research_subgraph", END)
    graph.add_edge("multi_doc_synthesis_subgraph", END)

    return graph.compile()
