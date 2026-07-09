# CogniFetch — Frontend

React 18 + Vite frontend for the CogniFetch agentic RAG application.

## Stack

- **React 18** with React Router v6 for navigation
- **Vite 6** for dev server and builds
- **marked** for rendering markdown in chat responses
- No UI framework — plain CSS

## Prerequisites

- Node.js 18+
- The CogniFetch backend running (see root `README.md`)

## Local setup

```bash
cd frontend
cp .env.example .env        # edit VITE_API_BASE_URL if your backend runs elsewhere
npm install
npm run dev                  # starts on http://localhost:5173
```

The dev server talks directly to the backend URL in `.env` — no proxy.

## Environment

| Variable | Default | Purpose |
|---|---|---|
| `VITE_API_BASE_URL` | `http://localhost:8000` | CogniFetch backend base URL |

> **Important:** `VITE_API_BASE_URL` is baked into the bundle at build time, not read at runtime. Set the correct value in `.env` before running `npm run build`, or the frontend will point to the wrong backend.

## Talking to the backend

| What | Where |
|---|---|
| Start backend | `docker compose up` from the repo root |
| API docs | `http://localhost:8000/docs` (Swagger UI) |

## Building for production

```bash
npm run build   # outputs to frontend/dist/
```

The `dist/` folder is a static bundle that can be served by any web server. It is not wired into `docker-compose.yml` — `npm run dev` is the intended local workflow.
