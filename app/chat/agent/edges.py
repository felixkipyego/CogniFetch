import json
import logging
import re
from typing import Literal

from langchain_core.messages import HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI

from app import runtime_config
from app.chat.agent.schemas import AgentState
from app.config import settings

logger = logging.getLogger(__name__)
MAX_REWRITES = 2


def grade_documents(state: AgentState) -> Literal["generate_answer", "rewrite_question", "no_relevant_docs"]:
    """
    Conditional edge: decide whether retrieved documents are relevant to the question.
    - "generate_answer"   → docs are relevant, proceed to answer
    - "rewrite_question"  → docs irrelevant, still have rewrites left
    - "no_relevant_docs"  → docs irrelevant after all rewrites exhausted
    """
    messages = state["messages"]
    tool_msg = next((m for m in reversed(messages) if isinstance(m, ToolMessage)), None)
    human_msg = next((m for m in reversed(messages) if isinstance(m, HumanMessage)), None)

    if not tool_msg or not human_msg:
        return "generate_answer"

    llm = ChatOpenAI(
        model=runtime_config.get("llm_model") or settings.llm_model,
        api_key=runtime_config.get("api_key") or settings.api_key,
        base_url=runtime_config.get("openai_api_base") or settings.openai_api_base,
    )
    response = llm.invoke([
        {
            "role": "system",
            "content": (
                "You are a strict relevance grader. "
                "Given a user question and retrieved document excerpts, decide whether the documents "
                "contain information that DIRECTLY and SPECIFICALLY answers the question. "
                "Score 'yes' only if the documents contain clear, on-topic content addressing the "
                "exact question asked. Score 'no' if the documents are only tangentially related, "
                "discuss a different aspect of a broad topic, or require inference beyond what is stated. "
                'Respond with ONLY a JSON object — {"binary_score": "yes"} or {"binary_score": "no"}. '
                "No explanation, no markdown, nothing else."
            ),
        },
        {
            "role": "user",
            "content": f"Question: {human_msg.content}\n\nRetrieved documents:\n{tool_msg.content}",
        },
    ])

    raw = response.content.strip()
    try:
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
        score = json.loads(cleaned).get("binary_score", "no")
    except (json.JSONDecodeError, AttributeError):
        logger.warning("Grader JSON parse failed (%r) — defaulting to generate_answer", raw)
        score = "yes"

    if score == "yes":
        return "generate_answer"

    if state.get("rewrite_count", 0) >= MAX_REWRITES:
        return "no_relevant_docs"

    return "rewrite_question"
