# CogniFetch

Full-stack agentic RAG built with **FastAPI** and **LangGraph**.

Most RAG systems retrieve documents and answer immediately, regardless of whether what they found is actually relevant. CogniFetch runs a multi-step agent instead: it retrieves document chunks, **grades their relevance**, rewrites the query and retries if they fall short, and only generates an answer once it has evidence worth using. If it exhausts its retries, it tells you so rather than hallucinating.

Upload PDFs, Word documents, plain text, or HTML. Ask questions. Get answers grounded in your files.

| Layer | Stack | Setup |
|---|---|---|
| Backend (this README) | FastAPI · LangGraph · pgvector · MinIO | `docker-compose up` |
| Frontend | React 18 · Vite · React Router | [`frontend/README.md`](frontend/README.md) |

**Included out of the box:** JWT auth with refresh tokens · SSE streaming · Admin panel (swap model/API key at runtime without restart) · Full pytest suite · One-command Docker Compose setup · Works with any OpenAI-compatible provider

---

## How the agent works

Each chat message enters a LangGraph state machine:

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
    END     generate_query_or_respond  END
```

The agent can answer directly from context, retrieve and grade chunks, rewrite the question and retry, or tell the user no relevant documents were found.

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
- **api** (FastAPI + uvicorn) on port 8000 with `--reload`

### 3. Run database migrations

```bash
docker-compose exec api alembic upgrade head
```

This applies all four migrations:
- `0001` — enables `vector` extension, creates `users` table
- `0002` — creates `documents` table and `documentstatus` enum
- `0003` — creates `chat_sessions` and `chat_messages` tables
- `0004` — adds `is_admin` to users, creates `system_config` table

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
data: {"message_id":"...","cited_chunk_ids":["doc-uuid-1",...]}
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
- **`test_ingestion`** — unit tests for `_run_pipeline` (chunking, metadata tagging) and `ingest_document` status transitions (pending → ready, pending → failed); LangChain and S3 are mocked
- **`test_chat`** — session CRUD, message history, SSE stream structure, message persistence after streaming; LangGraph is mocked

---

## Project structure

```
app/
├── main.py              # FastAPI app, lifespan, middleware, error handler
├── config.py            # Typed settings (pydantic-settings)
├── dependencies.py      # get_db, get_current_user, get_s3_client
├── auth/                # JWT register / login / refresh / password change
├── admin/               # System config panel (API key, model settings)
├── documents/           # Upload, CRUD, S3 storage, background ingestion
│   └── ingestion.py     # load → split → embed → pgvector upsert
└── chat/
    ├── router.py        # SSE streaming endpoint
    ├── service.py       # Session + message persistence
    └── agent/
        ├── graph.py     # LangGraph StateGraph definition
        ├── nodes.py     # generate_query_or_respond, rewrite_question, generate_answer, no_relevant_docs
        ├── edges.py     # grade_documents conditional edge
        ├── retriever.py # pgvector retriever scoped per session + user
        └── schemas.py   # AgentState, GradeDocuments structured-output schema
```

---

## Swapping the LLM provider

Set `API_KEY`, `OPENAI_API_BASE`, `LLM_MODEL`, and `EMBEDDING_MODEL` in `.env`. Any provider that exposes an OpenAI-compatible API works without code changes. To switch to a non-compatible provider, replace `langchain_openai.ChatOpenAI` / `OpenAIEmbeddings` in `nodes.py`, `edges.py`, and `ingestion.py` with the appropriate LangChain class.
