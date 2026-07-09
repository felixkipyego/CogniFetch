from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app import runtime_config
from app.chat.agent.schemas import AgentState
from app.config import settings

_RETRIEVAL_SYSTEM = SystemMessage(content=(
    "You are a document question-answering assistant. "
    "You MUST ALWAYS call the retrieve tool to search the user's uploaded documents before answering "
    "any question, no matter how simple it seems. "
    "Never answer from your own training knowledge. Always retrieve first."
))

_GROUNDING_SYSTEM = SystemMessage(content=(
    "You are a document question-answering assistant. Answer ONLY from the retrieved document "
    "excerpts shown in this conversation. Follow these rules strictly:\n"
    "1. Re-read the user's exact question before answering. Your answer must directly address "
    "that specific question — do not answer a different or related question.\n"
    "2. Use ONLY information from the retrieved excerpts. Do not add facts from your training data.\n"
    "3. If the retrieved excerpts do not contain a direct, clear answer to the specific question "
    "asked, respond with: \"I don't have information about that in your uploaded documents.\"\n"
    "4. If the documents mention the topic only in passing or in a different context, that is not "
    "sufficient — say you don't have the information.\n"
    "5. Never invent, infer, or extrapolate beyond what is explicitly stated in the excerpts."
))


def _llm(streaming: bool = False, tools=None):
    api_key = runtime_config.get("api_key") or settings.api_key
    base_url = runtime_config.get("openai_api_base") or settings.openai_api_base
    model = runtime_config.get("llm_model") or settings.llm_model
    client = ChatOpenAI(model=model, streaming=streaming, api_key=api_key, base_url=base_url)
    return client.bind_tools(tools) if tools else client


def make_generate_node(retriever_tool):
    def generate_query_or_respond(state: AgentState):
        messages = [_RETRIEVAL_SYSTEM] + list(state["messages"])
        return {"messages": [_llm(streaming=True, tools=[retriever_tool]).invoke(messages)]}
    return generate_query_or_respond


def rewrite_question(state: AgentState):
    original = next(m for m in reversed(state["messages"]) if isinstance(m, HumanMessage))
    rewritten = _llm().invoke([
        {
            "role": "system",
            "content": (
                "Rewrite the following question to make it clearer and more likely to retrieve "
                "relevant documents. Return only the rewritten question, nothing else."
            ),
        },
        {"role": "user", "content": original.content},
    ])
    return {
        "messages": [HumanMessage(content=rewritten.content)],
        "rewrite_count": state.get("rewrite_count", 0) + 1,
    }


def generate_answer(state: AgentState):
    messages = [_GROUNDING_SYSTEM] + list(state["messages"])
    return {"messages": [_llm(streaming=True).invoke(messages)]}


def no_relevant_docs(state: AgentState):
    human_msg = next((m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)), None)
    topic = human_msg.content.strip() if human_msg else "that topic"
    return {
        "messages": [
            AIMessage(content=(
                f"I don't have information about that in your uploaded documents. "
                f"The documents you've provided don't appear to contain anything relevant to: \"{topic}\". "
                f"Please upload documents that cover this topic, or ask something related to your existing documents."
            ))
        ]
    }
