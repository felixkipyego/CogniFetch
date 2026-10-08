from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from app.chat.agent.edges import grade_documents
from app.chat.agent.nodes import generate_answer, make_generate_node, no_relevant_docs, rewrite_question
from app.chat.agent.schemas import AgentState


def build_graph(retriever_tool):
    """
    Shape (compiled as a subgraph — see app/chat/agent/orchestrator.py):
      START
        └─► generate_query_or_respond ──tools_condition──► retrieve (ToolNode)
                 ▲                                               │
                 │                                         grade_documents
                 │                                    /         |          \\
           rewrite_question ◄─(not relevant    (relevant)  (no docs after
             + rewrites left)                      │          max rewrites)
                                            generate_answer   no_relevant_docs
                                                   │                │
                                                  END    Command(graph=PARENT,
                                                            goto=web_research_subgraph)
    """
    graph = StateGraph(AgentState)

    graph.add_node("generate_query_or_respond", make_generate_node(retriever_tool))
    graph.add_node("retrieve", ToolNode([retriever_tool]))
    graph.add_node("rewrite_question", rewrite_question)
    graph.add_node("generate_answer", generate_answer)
    graph.add_node("no_relevant_docs", no_relevant_docs)

    graph.set_entry_point("generate_query_or_respond")

    graph.add_conditional_edges(
        "generate_query_or_respond",
        tools_condition,
        {"tools": "retrieve", END: END},
    )
    graph.add_conditional_edges(
        "retrieve",
        grade_documents,
        {
            "generate_answer": "generate_answer",
            "rewrite_question": "rewrite_question",
            "no_relevant_docs": "no_relevant_docs",
        },
    )
    graph.add_edge("rewrite_question", "generate_query_or_respond")
    graph.add_edge("generate_answer", END)
    # no_relevant_docs always returns a Command(graph=PARENT, ...) — no static edge needed.

    return graph.compile()
