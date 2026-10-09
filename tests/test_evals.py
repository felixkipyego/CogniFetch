from unittest.mock import MagicMock, patch

from app.evals.schemas import (
    CitationJudgment,
    CorrectnessJudgment,
    EvalCaseResult,
    ExpectedCitation,
    FaithfulnessJudgment,
    RetrievalScore,
)
from app.evals.scoring import (
    judge_citation_accuracy,
    judge_correctness,
    judge_faithfulness,
    retrieval_metrics,
)

# ---------------------------------------------------------------------------
# retrieval_metrics — deterministic, no LLM involved
# ---------------------------------------------------------------------------

DOC_A = "doc-a-id"
DOC_B = "doc-b-id"
FILENAME_MAP = {"a.pdf": DOC_A, "b.pdf": DOC_B}


def test_retrieval_metrics_perfect_match():
    cited = [{"document_id": DOC_A, "pages": [0]}]  # 0-indexed, as the agent emits
    expected = [ExpectedCitation(document="a.pdf", pages=[1])]  # 1-indexed, as qa_pairs.json writes it
    score = retrieval_metrics(cited, expected, FILENAME_MAP)
    assert score.precision == 1.0
    assert score.recall == 1.0


def test_retrieval_metrics_partial_overlap():
    # Agent cites page 0 (correct) and page 2 (extra, wrong) on doc A.
    cited = [{"document_id": DOC_A, "pages": [0, 2]}]
    expected = [ExpectedCitation(document="a.pdf", pages=[1])]
    score = retrieval_metrics(cited, expected, FILENAME_MAP)
    assert score.precision == 0.5  # 1 of 2 cited pairs was correct
    assert score.recall == 1.0      # the 1 expected pair was found


def test_retrieval_metrics_missed_entirely():
    cited: list = []
    expected = [ExpectedCitation(document="a.pdf", pages=[1])]
    score = retrieval_metrics(cited, expected, FILENAME_MAP)
    assert score.precision == 0.0
    assert score.recall == 0.0


def test_retrieval_metrics_out_of_corpus_correctly_cites_nothing():
    cited: list = []
    expected: list = []
    score = retrieval_metrics(cited, expected, FILENAME_MAP)
    assert score.precision == 1.0
    assert score.recall == 1.0


def test_retrieval_metrics_out_of_corpus_hallucinated_citation():
    cited = [{"document_id": DOC_A, "pages": [0]}]
    expected: list = []
    score = retrieval_metrics(cited, expected, FILENAME_MAP)
    assert score.precision == 0.0
    assert score.recall == 1.0  # vacuously true — nothing was expected


def test_retrieval_metrics_cross_doc_both_documents_cited():
    cited = [{"document_id": DOC_A, "pages": [0]}, {"document_id": DOC_B, "pages": [1]}]
    expected = [
        ExpectedCitation(document="a.pdf", pages=[1]),
        ExpectedCitation(document="b.pdf", pages=[2]),
    ]
    score = retrieval_metrics(cited, expected, FILENAME_MAP)
    assert score.precision == 1.0
    assert score.recall == 1.0


# ---------------------------------------------------------------------------
# LLM-as-judge functions — mocked ChatOpenAI, same pattern as
# test_classify_route_uses_structured_output_when_multiple_allowed in
# tests/test_chat.py
# ---------------------------------------------------------------------------

def test_judge_correctness_uses_structured_output():
    fake_judgment = CorrectnessJudgment(score="correct", reasoning="matches")
    with patch("app.evals.scoring.ChatOpenAI") as MockLLM:
        MockLLM.return_value.with_structured_output.return_value.invoke.return_value = fake_judgment
        result = judge_correctness("Q?", "the answer", "the expected answer")

    MockLLM.return_value.with_structured_output.assert_called_once_with(CorrectnessJudgment)
    assert result.score == "correct"


def test_judge_faithfulness_uses_structured_output():
    fake_judgment = FaithfulnessJudgment(score="unfaithful", reasoning="not grounded")
    with patch("app.evals.scoring.ChatOpenAI") as MockLLM:
        MockLLM.return_value.with_structured_output.return_value.invoke.return_value = fake_judgment
        result = judge_faithfulness("Q?", "a confident but ungrounded answer", "")

    MockLLM.return_value.with_structured_output.assert_called_once_with(FaithfulnessJudgment)
    assert result.score == "unfaithful"


def test_judge_faithfulness_handles_empty_context_without_error():
    fake_judgment = FaithfulnessJudgment(score="faithful", reasoning="plain refusal")
    with patch("app.evals.scoring.ChatOpenAI") as MockLLM:
        MockLLM.return_value.with_structured_output.return_value.invoke.return_value = fake_judgment
        result = judge_faithfulness("Q?", "I don't have that information.", "")

    assert result.score == "faithful"


def test_judge_citation_accuracy_uses_structured_output():
    fake_judgment = CitationJudgment(score="supported", reasoning="backed by page text")
    with patch("app.evals.scoring.ChatOpenAI") as MockLLM:
        MockLLM.return_value.with_structured_output.return_value.invoke.return_value = fake_judgment
        result = judge_citation_accuracy("the answer", "cited page text")

    MockLLM.return_value.with_structured_output.assert_called_once_with(CitationJudgment)
    assert result.score == "supported"


# ---------------------------------------------------------------------------
# _build_scorecard — pure aggregation, no LLM/DB
# ---------------------------------------------------------------------------

def _case_result(case_id, handled_by, correct, faithful, cited_ok=None) -> EvalCaseResult:
    return EvalCaseResult(
        case_id=case_id,
        question="q",
        answer="a",
        handled_by=handled_by,
        retrieval=RetrievalScore(precision=1.0, recall=1.0),
        correctness=CorrectnessJudgment(score="correct" if correct else "incorrect", reasoning=""),
        faithfulness=FaithfulnessJudgment(score="faithful" if faithful else "unfaithful", reasoning=""),
        citation_accuracy=(
            None if cited_ok is None
            else CitationJudgment(score="supported" if cited_ok else "unsupported", reasoning="")
        ),
        total_latency_ms=100.0,
        prompt_tokens=10,
        completion_tokens=5,
    )


def test_build_scorecard_aggregates_rates_and_route_breakdown():
    from app.evals.runner import _build_scorecard

    results = [
        _case_result("c1", "rag", correct=True, faithful=True, cited_ok=True),
        _case_result("c2", "rag", correct=False, faithful=True, cited_ok=False),
        _case_result("c3", "web_research", correct=True, faithful=False, cited_ok=None),
    ]
    card = _build_scorecard(results)

    assert card.n_cases == 3
    assert card.correctness_rate == 2 / 3
    assert card.faithfulness_rate == 2 / 3
    # citation_accuracy_rate only counts the 2 cases that cited something
    assert card.citation_accuracy_rate == 1 / 2

    assert card.by_route["rag"].n == 2
    assert card.by_route["rag"].correctness_rate == 0.5
    assert card.by_route["web_research"].n == 1
    assert card.by_route["web_research"].faithfulness_rate == 0.0


def test_build_scorecard_citation_rate_defaults_to_one_when_nothing_cited():
    from app.evals.runner import _build_scorecard

    results = [_case_result("c1", "web_research", correct=True, faithful=True, cited_ok=None)]
    card = _build_scorecard(results)
    assert card.citation_accuracy_rate == 1.0
