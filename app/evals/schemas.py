from typing import Literal, Optional

from pydantic import BaseModel


class ExpectedCitation(BaseModel):
    document: str
    pages: list[int]  # 1-indexed, matching how a human reads the PDF


class EvalCase(BaseModel):
    id: str
    documents: list[str]  # filenames; [] for out-of-corpus cases
    question: str
    expected_answer: str
    expected_citations: list[ExpectedCitation]
    note: Optional[str] = None


class RetrievalScore(BaseModel):
    precision: float
    recall: float


class CorrectnessJudgment(BaseModel):
    score: Literal["correct", "incorrect"]
    reasoning: str


class FaithfulnessJudgment(BaseModel):
    score: Literal["faithful", "unfaithful"]
    reasoning: str


class CitationJudgment(BaseModel):
    score: Literal["supported", "unsupported"]
    reasoning: str


class EvalCaseResult(BaseModel):
    case_id: str
    question: str
    answer: str
    handled_by: Optional[str]
    retrieval: RetrievalScore
    correctness: CorrectnessJudgment
    faithfulness: FaithfulnessJudgment
    citation_accuracy: Optional[CitationJudgment]  # None when the answer cited nothing
    total_latency_ms: float
    prompt_tokens: int
    completion_tokens: int


class RouteBreakdown(BaseModel):
    n: int
    correctness_rate: float
    faithfulness_rate: float


class ScoreCard(BaseModel):
    case_results: list[EvalCaseResult]
    n_cases: int
    mean_precision: float
    mean_recall: float
    correctness_rate: float
    faithfulness_rate: float
    citation_accuracy_rate: float  # only over cases that cited something
    by_route: dict[str, RouteBreakdown]
