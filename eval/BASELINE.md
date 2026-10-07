# Phase 0 baseline — latency, cost, and two findings

Recorded 2026-10-07 against the live graph (`generate_query_or_respond` → `retrieve` → `grade_documents` → `generate_answer`/`rewrite_question`/`no_relevant_docs`), running locally with the real configured LLM provider (`OPENAI_API_BASE` pointed at a third-party gateway, not api.openai.com directly — see cost caveat below). Model: `gpt-4o-mini`. This is the "before" snapshot the Phase 5 README polish will diff against once Phases 1-4 land.

## Method

1. Registered a test user, uploaded 2 of the 4 [eval corpus](./qa_pairs.json) PDFs (`aurora_cloud_sla.pdf`, `northwind_employee_handbook.pdf`), created one chat session scoped to both.
2. Sent 9 real chat turns through the live SSE endpoint — 4 Northwind questions, 4 Aurora questions, 1 out-of-corpus question — timing wall-clock latency from request sent to the `done` event.
3. No mocking anywhere in this pass: real Postgres/pgvector, real MinIO, real embedding + chat completion calls.

## Latency

| Metric | Value |
|---|---|
| p50 | 8.48s |
| p95 | 11.20s |
| min / max | 1.42s / 11.66s |
| mean | 8.22s |
| n | 9 turns |

Per-turn detail:

| Question | Latency |
|---|---|
| northwind-01 | 11.66s |
| northwind-02 | 8.33s |
| northwind-03 | 8.48s |
| northwind-04 | 8.79s |
| aurora-01 | 8.53s |
| aurora-02 | 8.23s |
| aurora-03 | 8.06s |
| aurora-04 | 1.42s |
| out-of-corpus-01 | 10.50s |

8 of 9 turns clustered at 8-12s — slow for `gpt-4o-mini` on short single-fact questions. The one outlier (`aurora-04`, 1.42s) got routed through the same graph but returned in a fraction of the time, which points at inconsistent latency from the upstream gateway (`OPENAI_API_BASE=https://aibe.mygreatlearning.com/...`) rather than the graph logic itself — a plain OpenAI-direct endpoint would be the control to compare against before concluding the *agent* is slow. Worth re-measuring once Phase 4's per-node `step` events exist, to see whether time is dominated by the LLM calls themselves or by the grading/rewrite round-trips.

## Cost (rough lower bound — not a real measurement)

| Metric | Value |
|---|---|
| Total prompt tokens (question text only) | 159 |
| Total completion tokens (visible answer only) | 456 |

**This number is not trustworthy as a real cost figure and shouldn't be quoted as one.** It only counts the literal question and the final answer text. It excludes:
- the two system prompts (`_RETRIEVAL_SYSTEM`, `_GROUNDING_SYSTEM`) sent on every call,
- the retrieved document chunks injected as context,
- the grading LLM call in `grade_documents` (a full extra round-trip per attempt),
- any rewrite-loop iterations,
- conversation history on multi-turn sessions.

The real prompt-token count per turn is several times higher than what's shown here. There's currently no way to get the real number from outside the app — `ChatOpenAI` isn't configured with `stream_usage=True`, and the SSE `done` event doesn't carry token usage. Once `LANGCHAIN_API_KEY` is set (see README's Observability section), LangSmith will report real per-run input/output tokens and cost automatically, which is the correct way to get this number — not worth hand-instrumenting now when Phase 3 does this properly.

Separately: actual billing goes through `aibe.mygreatlearning.com`, a third-party gateway, not OpenAI directly — its pricing may not match OpenAI's published rates at all, so even a correct token count wouldn't translate to a reliable dollar figure without knowing that gateway's actual rate.

## Two findings from this pass

**1. Concurrent document ingestion crashes (real bug, not a baseline-measurement artifact).** Uploading two documents back-to-back triggered:

```
sqlalchemy.exc.InvalidRequestError: Table 'langchain_pg_collection' is already defined for this
MetaData instance. Specify 'extend_existing=True' to redefine options and columns on an existing
Table object.
```

`app/documents/ingestion.py` constructs a new `langchain_postgres.PGVector(...)` instance per ingestion call, which registers a fresh SQLAlchemy declarative class against a shared registry every time. Two ingestion tasks running concurrently (FastAPI `BackgroundTasks`, no serialization) race on that registration and one fails outright — the document is marked `failed` with no retry. Re-uploading the same file sequentially (no concurrent second upload in flight) succeeded. This is a direct, concrete illustration of exactly the gap Phase 1 is meant to close — "no retries, no durability" isn't hypothetical, it reproduces on two uploads in a row. Not fixed here; it's Phase 1's job, and Phase 1's idempotent-retry design should cover it.

**2. Grounding gap on out-of-corpus questions.** The out-of-corpus test question ("What is the maximum altitude a commercial airliner can fly at?") should have produced the `no_relevant_docs` node's fixed refusal. Instead it returned a confident, ungrounded general-knowledge answer ("~40,000 feet..."), violating `_GROUNDING_SYSTEM`'s explicit "Answer ONLY from the retrieved document excerpts... otherwise say you don't have the information" instruction. The ~10.5s latency (in line with turns that complete a full retrieve→grade→answer pass, not a short-circuited refusal) suggests the relevance grader likely scored the irrelevant retrieved chunks as `"yes"` on at least one pass, letting it reach `generate_answer`, which then ignored its own grounding instruction given weak context. Not fixed here — this is exactly the regression class Phase 3's automated faithfulness scoring (LLM-as-judge on "did the answer stay grounded in retrieved context") is designed to catch systematically instead of by spot-checking. It's also a genuine argument for why Phase 3 matters for this specific agent, not just a generic checklist item.

## Status

Candidate baseline for Phase 0. Re-run and update this file once Phase 4 adds per-node timing (to break latency down by node) and once LangSmith tracing (this phase) is live with a real API key (to get real token/cost numbers in place of the rough estimate above).
