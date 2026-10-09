import time

from langchain_openai import ChatOpenAI

from app import runtime_config
from app.config import settings
from app.evals.schemas import (
    CitationJudgment,
    CorrectnessJudgment,
    ExpectedCitation,
    FaithfulnessJudgment,
    RetrievalScore,
)


def _invoke_with_retry(structured_llm, messages, attempts: int = 3, base_delay: float = 2.0):
    """
    This project's configured LLM provider is a third-party gateway
    (OPENAI_API_BASE), not api.openai.com directly, and eval/BASELINE.md's
    Phase 0 measurement already flagged it as having inconsistent latency
    under load. Live-running this harness surfaced a sharper version of the
    same flakiness: the gateway intermittently drops a valid API key for one
    request in an otherwise-successful run, when hit 25+ times in a row.
    This retry is scoped to the eval harness's own judge calls, which is
    where that sustained sequential load happens — not a general production
    reliability fix for app/chat/agent/*, which is out of scope here.
    """
    last_exc = None
    for attempt in range(attempts):
        try:
            return structured_llm.invoke(messages)
        except Exception as exc:
            last_exc = exc
            if attempt < attempts - 1:
                time.sleep(base_delay * (attempt + 1))
    raise last_exc


def retrieval_metrics(
    cited_sources: list[dict],
    expected_citations: list[ExpectedCitation],
    document_id_by_filename: dict[str, str],
) -> RetrievalScore:
    """
    Deterministic precision/recall over (document_id, page) pairs — no LLM
    involved, since the corpus's facts are page-scoped by construction (see
    eval/README.md), so "did the citation land on the right page" has one
    unambiguous right answer.

    expected_citations uses 1-indexed pages (how a human reads the PDF);
    cited_sources uses PyPDFLoader's 0-indexed pages — converted here, once,
    so callers never have to think about the off-by-one.
    """
    expected_pairs = {
        (document_id_by_filename.get(ec.document), page - 1)
        for ec in expected_citations
        for page in ec.pages
    }
    actual_pairs = {
        (source["document_id"], page)
        for source in cited_sources
        for page in source["pages"]
    }

    if not expected_pairs:
        # Out-of-corpus case: the correct behavior is to cite nothing.
        return RetrievalScore(precision=1.0 if not actual_pairs else 0.0, recall=1.0)
    if not actual_pairs:
        return RetrievalScore(precision=0.0, recall=0.0)

    overlap = actual_pairs & expected_pairs
    return RetrievalScore(
        precision=len(overlap) / len(actual_pairs),
        recall=len(overlap) / len(expected_pairs),
    )


def _judge_llm():
    return ChatOpenAI(
        model=runtime_config.get("llm_model") or settings.llm_model,
        api_key=runtime_config.get("api_key") or settings.api_key,
        base_url=runtime_config.get("openai_api_base") or settings.openai_api_base,
    )


def judge_correctness(question: str, answer: str, expected_answer: str) -> CorrectnessJudgment:
    """LLM-as-judge: does the answer's substance match the reference answer?"""
    llm = _judge_llm().with_structured_output(CorrectnessJudgment)
    return _invoke_with_retry(llm, [
        {
            "role": "system",
            "content": (
                "You are grading whether an AI assistant's answer matches a reference answer. "
                "Score 'correct' if the answer's key facts and numbers match the reference, even "
                "if the wording differs. Score 'incorrect' if it contradicts the reference, omits "
                "the key fact the reference gives, or is a refusal when the reference expected a "
                "concrete answer (or gives a confident answer when the reference expected a "
                "refusal)."
            ),
        },
        {
            "role": "user",
            "content": f"Question: {question}\n\nReference answer: {expected_answer}\n\nActual answer: {answer}",
        },
    ])


def judge_faithfulness(question: str, answer: str, retrieved_context: str) -> FaithfulnessJudgment:
    """LLM-as-judge: is every factual claim in the answer grounded in what was actually retrieved?"""
    llm = _judge_llm().with_structured_output(FaithfulnessJudgment)
    context_text = retrieved_context.strip() or "(no documents were retrieved for this question)"
    return _invoke_with_retry(llm, [
        {
            "role": "system",
            "content": (
                "You are a strict faithfulness grader for a RAG system. Given the retrieved "
                "context actually shown to the assistant and its final answer, score 'faithful' "
                "only if every factual claim in the answer is directly supported by the retrieved "
                "context, OR the answer is a plain refusal/'I don't have that information' "
                "statement rather than a factual claim. Score 'unfaithful' if the answer states "
                "any fact not present in the retrieved context — even if that fact happens to be "
                "true in general. A confident answer built on no retrieved context, or on context "
                "that doesn't actually address the question, is unfaithful."
            ),
        },
        {
            "role": "user",
            "content": f"Question: {question}\n\nRetrieved context:\n{context_text}\n\nAnswer: {answer}",
        },
    ])


def judge_citation_accuracy(answer: str, cited_context: str) -> CitationJudgment:
    """LLM-as-judge: does the text of the specific pages cited actually back the answer's claims?"""
    llm = _judge_llm().with_structured_output(CitationJudgment)
    return _invoke_with_retry(llm, [
        {
            "role": "system",
            "content": (
                "You are grading citation accuracy. Given an answer and the text of the specific "
                "pages it cited as sources, score 'supported' if those cited pages actually "
                "contain the information backing the answer's claims. Score 'unsupported' if the "
                "cited pages are irrelevant to those claims, even if the answer is factually "
                "correct from some other source — citing the wrong page is still a citation bug."
            ),
        },
        {
            "role": "user",
            "content": f"Answer: {answer}\n\nText of cited pages:\n{cited_context}",
        },
    ])
