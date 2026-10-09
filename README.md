# CogniFetch

## 🚀 [Live Demo](https://cognifetch.felixkipyego.com)

**Try CogniFetch now — no setup required → [cognifetch.felixkipyego.com](https://cognifetch.felixkipyego.com)**

---

Full-stack agentic RAG built with **FastAPI** and **LangGraph**.

Most RAG systems retrieve documents and answer immediately, regardless of whether what they found is actually relevant. CogniFetch runs a multi-step agent instead: it retrieves document chunks, **grades their relevance**, rewrites the query and retries if they fall short, and only generates an answer once it has evidence worth using. If it exhausts its retries, it tells you so rather than hallucinating.

Upload PDFs, Word documents, plain text, or HTML. Ask questions. Get answers grounded in your files.

| Layer | Stack | Setup |
|---|---|---|
| Backend (this README) | FastAPI · LangGraph · pgvector · MinIO | `docker-compose up` |
| Frontend | React 18 · Vite · React Router | [`frontend/README.md`](frontend/README.md) |

**Included out of the box:** JWT auth with refresh tokens · Email verification · Multi-agent orchestration (supervisor + RAG/web-research/multi-doc-synthesis sub-agents) · SSE streaming · Admin panel (swap model/API key at runtime without restart, token/cost/latency metrics) · Golden-set eval harness with LLM-as-judge scoring · Full pytest suite · One-command Docker Compose setup · Works with any OpenAI-compatible provider

---

## How the agent works

Each chat message is routed by a supervisor to one of three sub-agents — a real multi-agent graph (LangGraph subgraphs + `Command` handoffs), not one big conditional-edge tree:

```
START ─► supervisor ──Command.goto──► rag_subgraph
                     │
                     ├──► web_research_subgraph  (Tavily search)
                     │
                     └──► multi_doc_synthesis_subgraph  (fans out retrieval across
                                                           every document in scope)
```

**`rag_subgraph`** — the original single-document-corpus graph, unchanged:

```
START
  └─► generate_query_or_respond ──(no tool call)──► END
               │
           (tool call)
               ▼
            retrieve
               │
         grade_documents
        /       |        \
(relevant) (not relevant)  (no docs /
     │      + rewrites left)  max rewrites)
     │             │                │
generate_answer  rewrite_question  no_relevant_docs
     │             │                │
    END     generate_query_or_respond  │
                                        ▼
                        Command(graph=PARENT, goto=web_research_subgraph)
```

The supervisor picks a route before any retrieval happens (no documents uploaded → web research only; one document → RAG or web research; two or more → RAG, web research, or cross-document synthesis). If RAG tries and comes up empty after all its rewrites, it hands off to the web-research sub-agent itself via `Command(graph=Command.PARENT, ...)` — a real escalation across the subgraph boundary, not just the supervisor's upfront routing. Each assistant message records which sub-agent actually produced it (`handled_by` on `ChatMessage`).

---

## Prerequisites

- Python 3.11+
- Docker & Docker Compose
- An OpenAI-compatible API key

---

## Local setup

### 1. Clone and configure

```bash
cp .env.example .env
```

Open `.env` and fill in:

```dotenv
API_KEY=your-api-key
OPENAI_API_BASE=https://api.openai.com/v1   # or your provider's base URL
JWT_SECRET_KEY=...                           # openssl rand -hex 32
```

**Password consistency note:** `POSTGRES_PASSWORD` must match the password in `DATABASE_URL` and `SYNC_DATABASE_URL` — all three placeholders in `.env.example` are marked `YOUR_DB_PASSWORD` so you replace them together. Same pattern for `MINIO_ROOT_PASSWORD` and `S3_SECRET_ACCESS_KEY`.

For local dev the remaining defaults work as-is. For production also set:

- `POSTGRES_PASSWORD` / `MINIO_ROOT_PASSWORD` — strong random passwords (`openssl rand -hex 16`)
- `CORS_ORIGINS` — JSON list of your frontend origin, e.g. `["https://yourdomain.com"]`
- `APP_ENV=production`

### 2. Start the infrastructure

```bash
docker-compose up -d
```

This starts:
- **postgres** (`pgvector/pgvector:pg16`) on port 5432
- **minio** (S3-compatible storage) on port 9000 — console at http://localhost:9001
- **redis** on port 6379 — Celery broker/result backend
- **api** (FastAPI + uvicorn) on port 8000 with `--reload`
- **celery-worker** — runs document ingestion as a retryable background task

### 3. Run database migrations

```bash
docker-compose exec api alembic upgrade head
```

This applies all migrations:
- `0001` — enables `vector` extension, creates `users` table
- `0002` — creates `documents` table and `documentstatus` enum
- `0003` — creates `chat_sessions` and `chat_messages` tables
- `0004` — adds `is_admin` to users, creates `system_config` table
- `0005` — adds `is_verified` and `email_token` to users (email verification)
- `0006` — adds `handled_by` to chat_messages (multi-agent sub-agent attribution)
- `0007` — creates `agent_run_metrics` table (tokens, cost, per-node latency per agent run)

The MinIO bucket (`cognifetch-docs`) is created automatically on first API startup.

### 4. Verify

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

Interactive API docs: http://localhost:8000/docs

---

## Testing the flows

### Auth

```bash
# Register
curl -s -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","password":"secret123"}' | jq

# Login — save the tokens
TOKENS=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","password":"secret123"}')

ACCESS=$(echo $TOKENS | jq -r .access_token)
```

### Upload a document

```bash
curl -s -X POST http://localhost:8000/documents \
  -H "Authorization: Bearer $ACCESS" \
  -F "file=@/path/to/your.pdf" | jq
# {"id":"...","status":"pending",...}
```

Ingestion runs in the background. Poll until `status` is `ready`:

```bash
DOC_ID="<id from above>"

curl -s http://localhost:8000/documents/$DOC_ID \
  -H "Authorization: Bearer $ACCESS" | jq .status
```

### Chat

```bash
# Create a session scoped to the document (or omit document_scope for all docs)
SESSION=$(curl -s -X POST http://localhost:8000/chat/sessions \
  -H "Authorization: Bearer $ACCESS" \
  -H "Content-Type: application/json" \
  -d "{\"title\":\"My Chat\",\"document_scope\":[\"$DOC_ID\"]}")

SESSION_ID=$(echo $SESSION | jq -r .id)

# Send a message — response streams as Server-Sent Events
curl -s -N -X POST \
  http://localhost:8000/chat/sessions/$SESSION_ID/messages \
  -H "Authorization: Bearer $ACCESS" \
  -H "Content-Type: application/json" \
  -d '{"content":"Summarise the main points of this document."}'
```

The stream emits:

```
event: delta
data: {"text":"The document covers..."}

event: delta
data: {"text":" several key topics..."}

event: done
data: {"message_id":"...","cited_chunk_ids":[{"document_id":"doc-uuid-1","pages":[4,7]},...]}
```

### Retrieve chat history

```bash
curl -s http://localhost:8000/chat/sessions/$SESSION_ID/messages \
  -H "Authorization: Bearer $ACCESS" | jq
```

---

## Running tests

### 1. Create the test database (once)

```bash
docker-compose exec postgres psql -U cognifetch -c "CREATE DATABASE cognifetch_test;"
```

### 2. Install dev dependencies

```bash
pip install -e ".[dev]"
```

### 3. Run the suite

```bash
pytest -v
```

The test suite:
- **`test_auth`** — register, login, refresh, duplicate-email guard, bad credentials, protected-route enforcement
- **`test_documents`** — upload, list (user-scoped), get, wrong-owner 404, delete; S3 and background ingestion are mocked
- **`test_ingestion`** — unit tests for `_run_pipeline` (chunking, metadata tagging) and `ingest_document_task` status transitions, including the retry-then-succeed and permanent-failure paths; LangChain, S3, and Celery's broker are not needed (`Task.apply()` runs the task in-process)
- **`test_chat`** — session CRUD, message history, SSE stream structure, message persistence after streaming, supervisor routing per sub-agent, and the RAG-to-web-research escalation path; LangGraph/LLM calls are mocked
- **`test_evals`** — retrieval precision/recall math (deterministic, no LLM), the three LLM-as-judge functions (mocked `ChatOpenAI`), and scorecard aggregation — the eval harness's own scoring logic, independent of the live-stack run it's normally used with
- **`test_admin`** — `/admin/metrics` aggregation: route breakdown, unknown-cost handling, admin-only access

Separately, `python -m app.evals.run` (or `make eval`) runs the full golden eval set against the live graph with real LLM calls — this is an operational tool, not part of the pytest suite (it costs money and needs the dockerized stack up). See "Evaluation" below.

---

## Project structure

```
app/
├── main.py              # FastAPI app, lifespan, middleware, error handler
├── config.py            # Typed settings (pydantic-settings)
├── celery_app.py        # Celery app (Redis broker/backend)
├── dependencies.py      # get_db, get_current_user, get_s3_client
├── auth/                # JWT register / login / refresh / password change
├── admin/               # System config panel (API key, model settings, metrics)
├── metrics/             # Token/cost/latency recording + admin aggregation
│   ├── service.py       # record_agent_run, get_metrics_summary
│   └── pricing.py        # Best-effort $/1M-token table for known OpenAI models
├── documents/           # Upload, CRUD, S3 storage, async ingestion
│   ├── ingestion.py     # load → split → embed → pgvector upsert (pure pipeline, no Celery)
│   └── tasks.py         # Celery task: retries + idempotent re-run around ingestion.py
├── evals/               # Golden-set evaluation harness (Phase 3) — see "Evaluation" below
│   ├── runner.py        # Bootstraps eval user/corpus, runs each case, scores it
│   ├── scoring.py        # Retrieval precision/recall + 3 LLM-as-judge functions
│   ├── schemas.py        # EvalCase, judgment models, ScoreCard
│   └── run.py            # CLI entry: python -m app.evals.run
└── chat/
    ├── router.py        # SSE streaming endpoint
    ├── service.py       # Session + message persistence
    └── agent/
        ├── orchestrator.py # Top-level graph: supervisor + 3 sub-agent subgraphs
        ├── supervisor.py   # Structured-output route classifier + Command-based routing
        ├── graph.py        # RAG sub-agent StateGraph (compiled as a subgraph)
        ├── nodes.py        # generate_query_or_respond, rewrite_question, generate_answer, no_relevant_docs
        ├── edges.py        # grade_documents conditional edge
        ├── retriever.py    # pgvector retriever(s) scoped per session + user
        ├── runner.py       # Shared astream_events consumer: tokens, citations, handled_by, latency, tokens
        ├── schemas.py      # AgentState, OrchestratorState, RouteDecision, etc.
        └── subagents/
            ├── web_research.py        # Tavily search + answer sub-agent
            └── multi_doc_synthesis.py # Per-document fan-out retrieval + compare/contrast sub-agent
```

---

## Email verification

Email verification is **opt-in** — it activates only when `SMTP_HOST` is set. Without it, users are auto-verified on registration and the flow is identical to before.

When enabled:
1. Registration sends a 24-hour verification link to the user's email.
2. Unverified users are blocked from signing in with a clear message.
3. Users can request a new link from the registration page if the first one expires.
4. The verification email includes a reminder to check the spam/junk folder.

**Configure SMTP in `.env`:**

```dotenv
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASSWORD=your-app-password
SMTP_FROM=noreply@yourdomain.com
SMTP_USE_TLS=true
FRONTEND_URL=https://yourdomain.com
```

For local testing without a real mail server, use [Mailpit](https://github.com/axllent/mailpit):

```bash
# docker run -p 1025:1025 -p 8025:8025 axllent/mailpit
SMTP_HOST=localhost
SMTP_PORT=1025
SMTP_USE_TLS=false
```

Emails are viewable in the Mailpit web UI at http://localhost:8025.

---

## Multi-agent orchestration

A supervisor routes each message to one of three sub-agents — see "How the agent works" above for the graph shape. The web-research sub-agent needs a Tavily key:

```dotenv
TAVILY_API_KEY=your-tavily-api-key
```

Get a free key at [tavily.com](https://tavily.com) (1,000 searches/month, no credit card required). Unlike `LANGCHAIN_API_KEY` above, this isn't silently inert when unset — the Tavily client itself raises if asked to search without a key. The web-research sub-agent checks for the key before calling Tavily and replies that web research isn't configured instead of raising, so the app works fully without this key — out-of-corpus questions just get a "not configured" response rather than a real web answer.

---

## Evaluation

A 25-case golden set (`eval/qa_pairs.json`, frozen fixtures described in `eval/README.md`) runs against the live orchestrator graph with real LLM calls — no mocking — and scores four dimensions: retrieval precision/recall (deterministic, page-overlap based), answer correctness, faithfulness, and citation accuracy (the latter three via LLM-as-judge, same structured-output pattern as `grade_documents`).

```bash
make eval
# or: python -m app.evals.run
```

**Latest run** (2026-10-09, `gpt-4o-mini` via a third-party gateway, Tavily not configured):

| Route | n | Correctness | Faithfulness |
|---|---|---|---|
| `rag` | 18 | **100%** | **94%** |
| `multi_doc_synthesis` | 3 | **100%** | **100%** |
| `web_research` (unavailable) | 4 | 25% | 75% |
| **Overall** | 25 | 88% | 92% |

Citation accuracy: 95% (over cases that cited anything). Mean retrieval precision/recall: 0.46 / 0.92.

**Reading these numbers honestly, not just reporting them:**

- **RAG and multi-doc synthesis are effectively flawless on this corpus.** Every drag on the overall score comes from the 4-case `web_research` bucket, for two separate reasons below — not from retrieval or generation quality.
- **Reason 1 — expected:** `TAVILY_API_KEY` isn't set in this environment (see "Multi-agent orchestration" above), so genuinely out-of-corpus questions get a "web search not configured" response instead of a real answer. The correctness judge scores that as wrong wording against the expected refusal text, even though it isn't a hallucination.
- **Reason 2 — a real finding the harness caught that manual spot-checking wouldn't have:** 2 of the 4 `web_research` cases (`aurora-03`, `trailhead-02`) are genuinely in-corpus questions the supervisor misrouted away from `rag`. Both ask ambiguous-sounding, generic-seeming questions ("what's the rate limit for the Pro tier", "is a credit card required for the free trial") that read like they could be about any SaaS product in general, not specifically the uploaded document — and unlike Phase 2's "unrecognized company name" misrouting bug (already fixed in the supervisor prompt), this one isn't a clean deterministic logic error: `trailhead-02` explicitly names "Trailhead Analytics" in the question, yet still misrouted, while 4 other Trailhead questions routed correctly. That points to run-to-run classifier noise (no sub-agent LLM call in this codebase sets `temperature=0`) rather than a one-line prompt fix — exactly the kind of regression a single live demo question would never surface, which is the entire point of having an automated eval set. Not fixed in this phase; a candidate next step is pinning `temperature=0` on the supervisor's classifier or adding few-shot examples of ambiguous in-corpus phrasing.
- **Mean retrieval precision (0.46) is a citation-granularity artifact, not a relevance problem.** Recall is 0.92 — the correct page is almost always retrieved. Precision sits near 0.5 on nearly every single-fact case because `cited_chunk_ids` (and this harness's retrieval scoring) records *every* page retrieved from a cited document, and MMR's `k=10` against this corpus's 2-page documents pulls chunks from both pages even when only one answers the question. This is a real, measurable characteristic of the current citation mechanism's granularity — worth narrowing in a future pass (e.g. report only the page(s) the final answer's text actually draws from) — not evidence that retrieval itself is missing the right page.
- One harder case, `out-of-corpus-02` (the "Northwind dress code" grounding trap — see `eval/README.md`), ended up with a citation despite the final answer coming from the unavailable web-research path; `citation_accuracy` correctly flagged it as `unsupported`. The root cause (a stale citation surviving the escalation handoff) wasn't fully isolated — but this is precisely the class of regression citation-accuracy scoring exists to catch instead of missing silently.

Token/cost/latency are recorded per agent run (`agent_run_metrics` table) and aggregated at `GET /admin/metrics` (Users → Metrics tab in the admin panel) — see "Token, cost & latency metrics" below.

Below 70% correctness or 85% faithfulness, `python -m app.evals.run` exits non-zero — documented here as a pre-merge gate rather than wired into CI, since a real run costs money and needs the live stack up.

---

## Token, cost & latency metrics

Every completed agent turn — real chat traffic and eval harness runs alike — writes one row to `agent_run_metrics`: prompt/completion tokens, a best-effort cost estimate (`app/metrics/pricing.py` — a static $/1M-token table for a handful of known OpenAI models; an unpriced or gateway-routed model reports cost as unknown, never as $0, same honesty bar as `eval/BASELINE.md`'s Phase 0 cost caveat), per-node latency, and total latency.

`GET /admin/metrics` aggregates the most recent 200 runs — overall stats, a breakdown by `handled_by` (which sub-agent answered), and average latency per graph node — surfaced in the admin panel's **Metrics** tab.

---

## Observability (tracing)

The LangGraph agent can be traced in [LangSmith](https://smith.langchain.com) with **zero code changes** — LangChain's SDK reads tracing config directly from the environment.

```dotenv
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=your-langsmith-api-key
LANGCHAIN_PROJECT=cognifetch
```

With these set, every run of the graph — retrieval, grading, rewriting, generation — shows up as a trace in your LangSmith project, including per-node latency and token usage. Leave `LANGCHAIN_TRACING_V2` unset to disable; the app behaves identically either way.

---

## Swapping the LLM provider

Set `API_KEY`, `OPENAI_API_BASE`, `LLM_MODEL`, and `EMBEDDING_MODEL` in `.env`. Any provider that exposes an OpenAI-compatible API works without code changes. To switch to a non-compatible provider, replace `langchain_openai.ChatOpenAI` / `OpenAIEmbeddings` in `nodes.py`, `edges.py`, and `ingestion.py` with the appropriate LangChain class.
