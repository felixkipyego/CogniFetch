import asyncio
import json
import logging
import uuid
from pathlib import Path

from langchain_core.messages import HumanMessage
from sqlalchemy import select

from app.auth.utils import hash_password
from app.chat.agent.orchestrator import build_orchestrator_graph
from app.chat.agent.retriever import make_retriever_tool
from app.chat.agent.runner import stream_agent_turn
from app.db.models import Document, DocumentStatus, User
from app.db.session import AsyncSessionLocal
from app.db.sync_session import SyncSessionLocal
from app.documents import storage
from app.documents.ingestion import _run_pipeline, delete_document_chunks_sync
from app.evals.schemas import EvalCase, EvalCaseResult, RouteBreakdown, ScoreCard
from app.evals.scoring import (
    judge_citation_accuracy,
    judge_correctness,
    judge_faithfulness,
    retrieval_metrics,
)
from app.metrics.service import record_agent_run

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_DIR = _REPO_ROOT / "eval" / "corpus"
QA_PAIRS_PATH = _REPO_ROOT / "eval" / "qa_pairs.json"

# Fixed identity for the harness's own user, so repeated runs reuse the same
# ingested documents instead of re-uploading the corpus every time.
EVAL_USER_EMAIL = "eval-harness@cognifetch.internal"


def load_cases() -> list[EvalCase]:
    raw = json.loads(QA_PAIRS_PATH.read_text())
    return [EvalCase(**c) for c in raw]


async def _get_or_create_eval_user() -> str:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.email == EVAL_USER_EMAIL))
        user = result.scalar_one_or_none()
        if user:
            return str(user.id)

        user = User(
            email=EVAL_USER_EMAIL,
            hashed_password=hash_password(uuid.uuid4().hex),
            is_verified=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return str(user.id)


def _ensure_corpus_ingested(user_id: str) -> dict[str, str]:
    """
    Idempotently ingest the frozen eval corpus for the eval user.

    Calls `_run_pipeline` directly — the same function Celery's
    `ingest_document_task` calls — rather than enqueueing through Celery,
    since the harness needs ingestion to finish before scoring can start,
    not fire-and-forget. Returns {filename: document_id}.
    """
    s3 = storage.make_s3_client()

    with SyncSessionLocal() as db:
        existing = db.execute(
            select(Document).where(
                Document.user_id == user_id, Document.status == DocumentStatus.ready
            )
        ).scalars().all()
        doc_ids = {d.filename: str(d.id) for d in existing}

    for pdf_path in sorted(CORPUS_DIR.glob("*.pdf")):
        filename = pdf_path.name
        if filename in doc_ids:
            continue

        logger.info("Ingesting eval corpus document: %s", filename)
        storage_key = f"{user_id}/eval/{filename}"
        storage.upload_bytes(s3, storage_key, pdf_path.read_bytes(), "application/pdf")

        with SyncSessionLocal() as db:
            doc = Document(
                user_id=user_id,
                filename=filename,
                storage_path=storage_key,
                mime_type="application/pdf",
                status=DocumentStatus.processing,
            )
            db.add(doc)
            db.commit()
            db.refresh(doc)
            document_id = str(doc.id)

        delete_document_chunks_sync(document_id)
        _run_pipeline(str(pdf_path), "application/pdf", document_id, user_id, filename)

        with SyncSessionLocal() as db:
            doc = db.get(Document, document_id)
            doc.status = DocumentStatus.ready
            db.commit()

        doc_ids[filename] = document_id

    missing = {p.name for p in CORPUS_DIR.glob("*.pdf")} - set(doc_ids)
    if missing:
        raise RuntimeError(f"Eval corpus failed to ingest: {missing}")
    return doc_ids


async def _run_case(
    case: EvalCase,
    user_id: str,
    doc_ids_by_filename: dict[str, str],
    all_document_ids: list[str],
) -> EvalCaseResult:
    # Cases that reference specific documents scope the retriever to just
    # those; out-of-corpus cases (documents == []) scope to the FULL corpus —
    # the supervisor has to actively decide nothing's relevant, the same as
    # a real user who's uploaded everything and asks an unrelated question,
    # rather than being handed an artificially narrow scope that makes the
    # refusal trivial.
    resolved_document_ids = (
        [doc_ids_by_filename[d] for d in case.documents] if case.documents else all_document_ids
    )

    retriever_tool = make_retriever_tool(resolved_document_ids, user_id)
    graph = build_orchestrator_graph(retriever_tool, user_id, resolved_document_ids)

    result = None
    async for kind, payload in stream_agent_turn(
        graph, [HumanMessage(content=case.question)], resolved_document_ids
    ):
        if kind == "result":
            result = payload
    assert result is not None

    async with AsyncSessionLocal() as db:
        await record_agent_run(
            db,
            user_id=user_id,
            session_id=None,
            message_id=None,
            handled_by=result.handled_by,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            node_latencies_ms=result.node_latencies_ms,
            total_latency_ms=result.total_latency_ms,
        )

    retrieval = retrieval_metrics(result.cited_sources, case.expected_citations, doc_ids_by_filename)
    correctness = judge_correctness(case.question, result.content, case.expected_answer)

    retrieved_context = "\n\n".join(
        chunk for chunks in result.retrieved_text.values() for chunk in chunks
    )
    faithfulness = judge_faithfulness(case.question, result.content, retrieved_context)

    citation_accuracy = None
    if result.cited_sources:
        cited_context = "\n\n".join(
            "\n".join(result.retrieved_text.get(source["document_id"], []))
            for source in result.cited_sources
        ).strip()
        if cited_context:
            citation_accuracy = judge_citation_accuracy(result.content, cited_context)

    return EvalCaseResult(
        case_id=case.id,
        question=case.question,
        answer=result.content,
        handled_by=result.handled_by,
        retrieval=retrieval,
        correctness=correctness,
        faithfulness=faithfulness,
        citation_accuracy=citation_accuracy,
        total_latency_ms=result.total_latency_ms,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
    )


def _build_scorecard(case_results: list[EvalCaseResult]) -> ScoreCard:
    n = len(case_results)
    cited_results = [r for r in case_results if r.citation_accuracy is not None]

    by_route: dict[str, list[EvalCaseResult]] = {}
    for r in case_results:
        by_route.setdefault(r.handled_by or "unknown", []).append(r)

    return ScoreCard(
        case_results=case_results,
        n_cases=n,
        mean_precision=sum(r.retrieval.precision for r in case_results) / n,
        mean_recall=sum(r.retrieval.recall for r in case_results) / n,
        correctness_rate=sum(r.correctness.score == "correct" for r in case_results) / n,
        faithfulness_rate=sum(r.faithfulness.score == "faithful" for r in case_results) / n,
        citation_accuracy_rate=(
            sum(r.citation_accuracy.score == "supported" for r in cited_results) / len(cited_results)
            if cited_results else 1.0
        ),
        by_route={
            route: RouteBreakdown(
                n=len(rows),
                correctness_rate=sum(r.correctness.score == "correct" for r in rows) / len(rows),
                faithfulness_rate=sum(r.faithfulness.score == "faithful" for r in rows) / len(rows),
            )
            for route, rows in by_route.items()
        },
    )


async def run_eval(cases: list[EvalCase] | None = None) -> ScoreCard:
    cases = cases if cases is not None else load_cases()

    user_id = await _get_or_create_eval_user()
    doc_ids_by_filename = await asyncio.to_thread(_ensure_corpus_ingested, user_id)
    all_document_ids = list(doc_ids_by_filename.values())

    case_results = []
    for case in cases:
        logger.info("Running case: %s", case.id)
        case_results.append(
            await _run_case(case, user_id, doc_ids_by_filename, all_document_ids)
        )

    return _build_scorecard(case_results)
