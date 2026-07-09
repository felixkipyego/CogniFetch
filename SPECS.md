# CogniFetch — Implementation Specifications

> Source of truth for the build. Derived from `cognifetch-backend-spec.md`.
> Build order: scaffold → auth → ingest → documents API → chat CRUD → LangGraph agent → polish.

---

## 1. Project Structure

```
cognifetch/
├── alembic/
│   ├── env.py
│   └── versions/
├── app/
│   ├── __init__.py
│   ├── main.py                  # FastAPI app factory, lifespan, router registration
│   ├── config.py                # Settings via pydantic-settings (reads .env)
│   ├── dependencies.py          # get_db, get_current_user, get_s3_client
│   ├── runtime_config.py        # In-memory runtime overrides for LLM settings (admin panel)
│   ├── auth/
│   │   ├── __init__.py
│   │   ├── router.py            # /auth/register, /auth/login, /auth/refresh, /auth/me/password
│   │   ├── schemas.py           # Pydantic I/O models
│   │   ├── service.py           # register, login, refresh, change_password logic
│   │   └── utils.py             # hash_password, verify_password, create_token, decode_token
│   ├── admin/
│   │   ├── __init__.py
│   │   ├── router.py            # /admin/config — get/set runtime LLM config
│   │   ├── schemas.py
│   │   └── service.py           # reads/writes system_config table + runtime_config cache
│   ├── documents/
│   │   ├── __init__.py
│   │   ├── router.py            # /documents CRUD
│   │   ├── schemas.py
│   │   ├── service.py           # upload, list, get, delete
│   │   ├── ingestion.py         # ingest_document() — runs in FastAPI BackgroundTasks
│   │   └── storage.py           # S3/MinIO wrapper
│   ├── chat/
│   │   ├── __init__.py
│   │   ├── router.py            # /chat/sessions + streaming message endpoint
│   │   ├── schemas.py
│   │   ├── service.py           # session CRUD, message persistence
│   │   └── agent/
│   │       ├── __init__.py
│   │       ├── graph.py         # LangGraph StateGraph definition
│   │       ├── nodes.py         # generate_query_or_respond, generate_answer, rewrite_question, no_relevant_docs
│   │       ├── edges.py         # grade_documents conditional edge
│   │       ├── retriever.py     # pgvector retriever factory (scoped by session docs)
│   │       └── schemas.py       # AgentState, GradeDocuments Pydantic schema
│   └── db/
│       ├── __init__.py
│       ├── base.py              # declarative Base, metadata
│       ├── session.py           # async engine + AsyncSessionLocal
│       └── models.py            # all ORM models
├── tests/
│   ├── conftest.py
│   ├── test_auth.py
│   ├── test_documents.py
│   ├── test_ingestion.py
│   └── test_chat.py
├── alembic.ini
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── pyproject.toml
└── README.md
```

---

## 2. Environment Variables (`.env.example`)

```dotenv
# Database
DATABASE_URL=postgresql+asyncpg://cognifetch:cognifetch@postgres:5432/cognifetch
SYNC_DATABASE_URL=postgresql+psycopg://cognifetch:cognifetch@postgres:5432/cognifetch

# Object storage (MinIO locally, S3 in prod)
S3_ENDPOINT_URL=http://minio:9000
S3_ACCESS_KEY_ID=minioadmin
S3_SECRET_ACCESS_KEY=minioadmin
S3_BUCKET_NAME=cognifetch-docs
S3_REGION=us-east-1

# LLM / embeddings — any OpenAI-compatible provider
API_KEY=your-api-key
OPENAI_API_BASE=https://api.openai.com/v1
EMBEDDING_MODEL=text-embedding-3-small
LLM_MODEL=gpt-4o-mini

# JWT
JWT_SECRET_KEY=change-me-in-production
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7

# App
APP_ENV=development
LOG_LEVEL=INFO
```

---

## 3. Configuration (`app/config.py`)

Use `pydantic-settings` so all env vars are typed and validated at startup.

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    sync_database_url: str

    s3_endpoint_url: str
    s3_access_key_id: str
    s3_secret_access_key: str
    s3_bucket_name: str
    s3_region: str = "us-east-1"

    api_key: str
    openai_api_base: str = "https://api.openai.com/v1"
    embedding_model: str = "text-embedding-3-small"
    llm_model: str = "gpt-4o-mini"

    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7

    app_env: str = "development"
    log_level: str = "INFO"

    chunk_size: int = 1000
    chunk_overlap: int = 200
    tiktoken_encoding: str = "cl100k_base"

settings = Settings()
```

---

## 4. Data Models (`app/db/models.py`)

```python
import enum
import uuid

from sqlalchemy import Boolean, Column, Enum, ForeignKey, String, Text, DateTime, func
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.db.base import Base


class User(Base):
    __tablename__ = "users"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    is_admin = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SystemConfig(Base):
    """Key-value store for runtime-editable settings that override env vars."""
    __tablename__ = "system_config"
    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class DocumentStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    ready = "ready"
    failed = "failed"


class Document(Base):
    __tablename__ = "documents"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    filename = Column(String(512), nullable=False)
    storage_path = Column(String(1024), nullable=False)
    mime_type = Column(String(128), nullable=False)
    status = Column(Enum(DocumentStatus), nullable=False, default=DocumentStatus.pending)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(512), nullable=False, default="New Chat")
    document_scope = Column(JSONB, nullable=True)  # list of document UUID strings, or null = all docs
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(16), nullable=False)        # "user" | "assistant"
    content = Column(Text, nullable=False)
    cited_chunk_ids = Column(JSONB, nullable=True)   # list of chunk ID strings
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
```

> `document_chunks` / embedding vectors are managed by `langchain-postgres`'s `PGVector` store. It creates its own table (`langchain_pg_embedding`). We tag each chunk with `{"document_id": str, "user_id": str}` metadata so retrieval can be filtered per session scope.

---

## 5. API Specification

### 5.1 Auth (`/auth`)

#### `POST /auth/register`
```
Request:  { "email": str, "password": str }
Response 201: { "id": uuid, "email": str, "created_at": datetime }
Response 400: { "detail": "Email already registered" }
```

#### `POST /auth/login`
```
Request:  { "email": str, "password": str }
Response 200: { "access_token": str, "refresh_token": str, "token_type": "bearer" }
Response 401: { "detail": "Invalid credentials" }
```

#### `POST /auth/refresh`
```
Request:  { "refresh_token": str }
Response 200: { "access_token": str, "token_type": "bearer" }
Response 401: { "detail": "Invalid or expired refresh token" }
```

#### `PATCH /auth/me/password`
```
Request:  { "current_password": str, "new_password": str }
Response 204: (no body)
Response 400: { "detail": "Current password is incorrect" }
```

---

### 5.2 Documents (`/documents`)

All endpoints require `Authorization: Bearer <access_token>`.

#### `POST /documents`
```
Request:  multipart/form-data  file=<file>
Response 202: {
  "id": uuid,
  "filename": str,
  "mime_type": str,
  "status": "pending",
  "created_at": datetime
}
```
Side effect: stores file in S3, creates DB record, enqueues `ingest_document` as a FastAPI BackgroundTask.

#### `GET /documents`
```
Response 200: [
  { "id": uuid, "filename": str, "status": str, "created_at": datetime, "error_message": str | null }
]
```

#### `GET /documents/{id}`
```
Response 200: { "id": uuid, "filename": str, "mime_type": str, "status": str, "error_message": str | null, "created_at": datetime }
Response 404: { "detail": "Document not found" }
```

#### `DELETE /documents/{id}`
```
Response 204: (no body)
```
Side effect: deletes S3 object, deletes DB record, deletes all vector chunks tagged with this `document_id`.

---

### 5.3 Chat Sessions (`/chat/sessions`)

#### `POST /chat/sessions`
```
Request:  { "title": str (optional), "document_scope": [uuid] | null }
Response 201: { "id": uuid, "title": str, "document_scope": [uuid] | null, "created_at": datetime }
```

#### `GET /chat/sessions`
```
Response 200: [{ "id": uuid, "title": str, "document_scope": [...] | null, "created_at": datetime }]
```

#### `GET /chat/sessions/{id}/messages`
```
Response 200: [{ "id": uuid, "role": str, "content": str, "cited_chunk_ids": [...] | null, "created_at": datetime }]
Response 404: { "detail": "Session not found" }
```

#### `POST /chat/sessions/{id}/messages`
```
Request:  { "content": str }
Response: text/event-stream  (SSE)

SSE event format:
  event: delta
  data: {"text": "<chunk>"}

  event: done
  data: {"message_id": uuid, "cited_chunk_ids": [...]}

  event: error
  data: {"detail": "<error message>"}
```

On receipt: persist user message, run LangGraph agent, stream token deltas, persist assistant message with cited chunk IDs on completion.

---

### 5.4 Admin (`/admin`)

All endpoints require an admin JWT (`is_admin: true`).

#### `GET /admin/users`
```
Response 200: [{ "id": uuid, "email": str, "is_admin": bool, "created_at": datetime }]
```

#### `PATCH /admin/users/{id}`
```
Request:  { "is_admin": bool }
Response 200: { "id": uuid, "email": str, "is_admin": bool, "created_at": datetime }
Response 400: { "detail": "Cannot change your own admin status" }
```

#### `DELETE /admin/users/{id}`
```
Response 204: (no body)
Response 400: { "detail": "Cannot delete your own account" }
```

#### `GET /admin/config`
```
Response 200: [{ "key": str, "value": str }]
```
Returns current values for `api_key`, `openai_api_base`, `llm_model`, `embedding_model` (api_key is masked).

#### `PATCH /admin/config`
```
Request:  { "changes": { "<key>": "<value>", ... } }
Response 200: [{ "key": str, "value": str }]
```
Writes to `system_config` table and updates the in-memory `runtime_config` cache immediately.

---

## 6. Background Ingestion (`app/documents/ingestion.py`)

No task queue needed — FastAPI's `BackgroundTasks` runs the ingestion function in a thread pool after the upload response is returned.

```python
# In router.py — after saving the DB record and uploading to S3:
background_tasks.add_task(ingest_document, document_id=str(doc.id))
```

```
Function: ingest_document(document_id: str)
(plain async function, called by FastAPI BackgroundTasks)

Steps:
1. Open a new DB session; fetch Document record; set status = "processing"
2. Download file from S3 to a temp path (tempfile.NamedTemporaryFile)
3. Select LangChain loader by mime_type:
     application/pdf         → PyPDFLoader
     application/vnd.openxmlformats-officedocument.wordprocessingml.document → Docx2txtLoader
     text/plain | text/markdown → TextLoader
     text/html               → BSHTMLLoader
4. loader.load() → list[Document]
5. RecursiveCharacterTextSplitter.from_tiktoken_encoder(
       encoding_name=settings.tiktoken_encoding,
       chunk_size=settings.chunk_size,
       chunk_overlap=settings.chunk_overlap
   ).split_documents(docs)
6. Add metadata {"document_id": document_id, "user_id": str(doc.user_id), "filename": filename} to each chunk
7. PGVector(embeddings=embeddings, collection_name="cognifetch_chunks",
       connection=settings.sync_database_url).add_documents(chunks)
8. Set status = "ready"
9. On any exception: set status = "failed", error_message = str(e)
```

> **Trade-off:** FastAPI BackgroundTasks run in the same process as the API. If the server restarts mid-ingestion, the task is lost and the document stays in `processing` state. A startup hook in `lifespan` should re-queue any documents stuck in `processing` by resetting them to `pending` and re-running ingestion.

---

## 7. LangGraph Agent (`app/chat/agent/`)

### Graph shape

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

`MAX_REWRITES = 2`. The `rewrite_count` field on `AgentState` is incremented each loop; once it reaches the limit, `grade_documents` routes to `no_relevant_docs` instead of retrying.

### Node specs

**`generate_query_or_respond`** (`nodes.py`)
```python
llm = ChatOpenAI(model=settings.llm_model).bind_tools([retrieve_tool])
def generate_query_or_respond(state: AgentState):
    response = llm.invoke(state["messages"])
    return {"messages": [response]}
```

**`retrieve`** — `ToolNode([retrieve_tool])` (no custom code needed)

**`grade_documents`** (`edges.py`) — conditional edge function, not a node
```python
def grade_documents(state: AgentState) -> Literal["generate_answer", "rewrite_question", "no_relevant_docs"]:
    # extract last ToolMessage and last HumanMessage
    # call LLM for binary yes/no relevance score
    # "yes"  → "generate_answer"
    # "no" + rewrites left  → "rewrite_question"
    # "no" + MAX_REWRITES reached → "no_relevant_docs"
```

**`rewrite_question`** (`nodes.py`)
```python
def rewrite_question(state: AgentState):
    # ask LLM to rephrase the original question for better retrieval
    return {"messages": [rewritten_human_message], "rewrite_count": state.get("rewrite_count", 0) + 1}
```

**`generate_answer`** (`nodes.py`)
```python
def generate_answer(state: AgentState):
    # call LLM with question + retrieved context (no tools bound)
    return {"messages": [final_response]}
```

**`no_relevant_docs`** (`nodes.py`)
```python
def no_relevant_docs(state: AgentState):
    # return a fixed "no relevant documents found" AI message
    return {"messages": [AIMessage(content="I couldn't find relevant information in your documents.")]}
```

### Graph assembly (`graph.py`)
```python
def build_graph(retriever_tool) -> CompiledGraph:
    graph = StateGraph(AgentState)
    graph.add_node("generate_query_or_respond", make_generate_node(retriever_tool))
    graph.add_node("retrieve", ToolNode([retriever_tool]))
    graph.add_node("rewrite_question", rewrite_question)
    graph.add_node("generate_answer", generate_answer)
    graph.add_node("no_relevant_docs", no_relevant_docs)

    graph.set_entry_point("generate_query_or_respond")
    graph.add_conditional_edges("generate_query_or_respond", tools_condition,
        {"tools": "retrieve", END: END})
    graph.add_conditional_edges("retrieve", grade_documents,
        {"generate_answer": "generate_answer", "rewrite_question": "rewrite_question",
         "no_relevant_docs": "no_relevant_docs"})
    graph.add_edge("rewrite_question", "generate_query_or_respond")
    graph.add_edge("generate_answer", END)
    graph.add_edge("no_relevant_docs", END)

    return graph.compile()
```

### Retriever factory (`retriever.py`)
```python
def make_retriever_tool(session: ChatSession, user_id: str):
    store = PGVector(
        connection=settings.sync_database_url,
        embeddings=OpenAIEmbeddings(model=settings.embedding_model),
        collection_name="cognifetch_chunks",
    )
    filter_dict = {"user_id": user_id}
    if session.document_scope:
        filter_dict["document_id"] = {"$in": session.document_scope}
    retriever = store.as_retriever(search_kwargs={"filter": filter_dict, "k": 6})
    return create_retriever_tool(retriever, "retrieve_documents",
        "Search the user's uploaded documents for relevant information.")
```

---

## 8. Streaming (`app/chat/router.py`)

```python
from fastapi.responses import StreamingResponse

async def stream_agent_response(session, user_message, db):
    # 1. Persist user ChatMessage
    # 2. Build retriever tool and LangGraph graph
    # 3. Async-iterate graph.astream_events({"messages": history}, version="v2")
    # 4. Yield SSE deltas for on_chat_model_stream events
    # 5. On graph completion: persist assistant ChatMessage, yield "done" event

@router.post("/sessions/{session_id}/messages")
async def send_message(session_id: UUID, body: MessageCreate, ...):
    return StreamingResponse(
        stream_agent_response(session, body.content, db),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

---

## 9. Docker Compose (`docker-compose.yml`)

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: cognifetch
      POSTGRES_PASSWORD: cognifetch
      POSTGRES_DB: cognifetch
    ports: ["5432:5432"]
    volumes: [postgres_data:/var/lib/postgresql/data]

  minio:
    image: minio/minio
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    ports: ["9000:9000", "9001:9001"]
    volumes: [minio_data:/data]

  api:
    build: { context: ., dockerfile: Dockerfile }
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
    env_file: .env
    ports: ["8000:8000"]
    depends_on: [postgres, minio]
    volumes: [.:/app]

volumes:
  postgres_data:
  minio_data:
```

---

## 10. Python Dependencies (`pyproject.toml` extras / `requirements.txt`)

```
# Web
fastapi>=0.115
uvicorn[standard]>=0.30
python-multipart          # file uploads

# Auth
python-jose[cryptography]
passlib[bcrypt]
bcrypt<4.0.0

# DB / ORM
sqlalchemy[asyncio]>=2.0
asyncpg                   # async postgres driver
psycopg[binary]           # sync driver (langchain-postgres needs it)
alembic

# LangChain / LangGraph (pinned per spec section 9)
langchain==0.3.27
langchain-core==0.3.79
langchain-openai==0.3.35
langchain-community==0.3.31
langgraph==0.6.6
langchain-postgres         # PGVector store

# Document parsing
pypdf==5.4.0
docx2txt
beautifulsoup4
lxml

# Object storage
boto3

# Config
pydantic-settings>=2.0
email-validator>=2.0

# Tokenizer (for RecursiveCharacterTextSplitter.from_tiktoken_encoder)
tiktoken

# Dev / test
pytest
pytest-asyncio
httpx                     # async test client for FastAPI
```

---

## 11. Alembic Setup

1. `alembic init alembic` — then edit `env.py` to import `Base.metadata` and use `settings.sync_database_url` as the connection URL.
2. First migration: `alembic revision --autogenerate -m "initial"` generates DDL for `users`, `documents`, `chat_sessions`, `chat_messages`.
3. The `PGVector` store creates its own table (`langchain_pg_embedding`) on first use — do not include it in Alembic migrations.
4. Enable pgvector extension in Postgres before running migrations:
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   ```
   Add this as a raw `op.execute` in the initial migration.

---

## 12. Phase Checklist

- [x] **Phase 1 — Scaffold**: directory structure, `pyproject.toml`, `Dockerfile`, `docker-compose.yml`, `.env.example`, `config.py`, `db/base.py`, `db/session.py`, `main.py` (no routes yet)
- [x] **Phase 2 — Auth**: `db/models.py` (User), Alembic initial migration, `auth/` module, JWT utils, register/login/refresh endpoints
- [x] **Phase 3 — Ingest**: `db/models.py` (Document), S3 storage wrapper, `POST /documents` endpoint, `ingestion.py` (FastAPI BackgroundTasks; load → split → embed → upsert pgvector), lifespan hook to recover stuck `processing` docs
- [x] **Phase 4 — Documents API**: `GET /documents`, `GET /documents/{id}`, `DELETE /documents/{id}` (with S3 + pgvector chunk cleanup)
- [x] **Phase 5 — Chat CRUD**: `db/models.py` (ChatSession, ChatMessage), Alembic migration, session + message CRUD endpoints (no agent yet)
- [x] **Phase 6 — LangGraph agent**: `chat/agent/` package, retriever factory, graph assembly, SSE streaming in `POST /chat/sessions/{id}/messages`
- [x] **Phase 7 — Polish**: structured logging, error handling, basic pytest suite (auth, ingest, retrieval), `README.md`
