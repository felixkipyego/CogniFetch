# CogniFetch Frontend — Specification

## 1. Component Architecture

```
App
├── AuthProvider          (context)
│   └── DocumentsProvider (context)
│       ├── /login        → LoginPage
│       ├── /register     → RegisterPage
│       └── / (protected) → ChatPage
│           ├── Sidebar
│           │   ├── [session list]
│           │   ├── [document library + doc items]
│           │   └── UploadZone
│           ├── ChatPane
│           │   ├── [message list]
│           │   │   └── MessageBubble (×N)
│           │   │       └── CitationChip (×N, assistant only)
│           │   └── Composer
│           └── MarginaliaRail  (hidden until citation clicked)
```

### Responsibility breakdown

| Component | Owns | Receives |
|---|---|---|
| `AuthProvider` | tokens, userId, login/register/logout | — |
| `DocumentsProvider` | documents[], checkedDocIds, upload/delete/poll | — |
| `ChatPage` | sessions[], activeSessionId, messages[], isStreaming, marginaliaDocId, sidebarOpen | — |
| `Sidebar` | — | sessions, activeSessionId, onSelectSession, onNewChat |
| `UploadZone` | drag state | onFile callback |
| `ChatPane` | scroll ref | session, messages, isStreaming, onSendMessage, onCitationClick |
| `MessageBubble` | — | message, onCitationClick |
| `Composer` | textarea value | isStreaming, onSend |
| `MarginaliaRail` | — | docId, onClose |

---

## 2. State Ownership

### Global (React Context)

**`AuthContext`**
- `accessToken` — stored in `localStorage` under `cf_access_token`
- `refreshToken` — stored in `localStorage` under `cf_refresh_token`
- `userId` — decoded from JWT `sub` claim (UUID string)
- `isAuthenticated` — derived from `accessToken !== null`
- Actions: `login()`, `register()`, `logout()`
- Listens for `cf:logout` window event (fired by the API client on unrecoverable 401)

**`DocumentsContext`**
- `documents[]` — array of `{ id, filename, status, error_message, created_at }`
- `checkedDocIds` — `Set<string>` of document IDs checked for next session scope
- `uploading` — boolean
- Actions: `fetchDocuments()`, `uploadDocument(file)`, `deleteDocument(id)`, `toggleDocCheck(id)`
- Polling: 3 s interval active while any doc has `status === 'pending'`; cleared on unmount or when nothing pending

### Local (ChatPage)

- `sessions[]` — sourced from `GET /chat/sessions`; localStorage fallback on 404/error
- `activeSessionId` — which session is open
- `messages[]` — messages for active session; includes synthetic streaming entries
- `isStreaming` — prevents composer submit while SSE stream is open
- `loadingMessages` — spinner while fetching history
- `marginaliaDocId` — `string | null`; which document the rail shows
- `sidebarOpen` — boolean for mobile drawer

---

## 3. SSE Parsing

`EventSource` cannot send `Authorization` headers, so the chat stream uses `fetch` + `ReadableStream`:

```js
const res = await apiFetch(`/chat/sessions/${id}/messages`, {
  method: 'POST',
  body: JSON.stringify({ content }),
});

const reader = res.body.getReader();
const decoder = new TextDecoder();
let buf = '';
let currentEvent = '';

for (;;) {
  const { done, value } = await reader.read();
  if (done) break;
  buf += decoder.decode(value, { stream: true });

  let nl;
  while ((nl = buf.indexOf('\n')) !== -1) {
    const line = buf.slice(0, nl);
    buf = buf.slice(nl + 1);

    if (line.startsWith('event: ')) {
      currentEvent = line.slice(7).trim();
    } else if (line.startsWith('data: ')) {
      const data = JSON.parse(line.slice(6));
      if (currentEvent === 'delta') onDelta(data.text ?? '');
      else if (currentEvent === 'done') onDone(data);
      else if (currentEvent === 'error') onError(data.detail ?? 'Stream error');
      currentEvent = '';
    }
  }
}
```

Key properties:
- `buf` accumulates decoder output; lines are consumed as complete `\n`-delimited units
- `event:` line sets type; `data:` line fires the callback; blank line resets (implicit via currentEvent reset)
- `onError` is called on HTTP non-2xx, JSON parse failure, or network error
- Token refresh happens inside `apiFetch` before the streaming call, transparent to this loop

---

## 4. Milestone Build Plan

| # | Milestone | Deliverables |
|---|---|---|
| M1 | Scaffold | package.json, vite.config.js, index.html, CSS tokens, App.jsx, main.jsx |
| M2 | Auth | AuthContext, LoginPage, RegisterPage, ProtectedRoute, API client with refresh |
| M3 | Documents | DocumentsContext, Sidebar document section, UploadZone, polling |
| M4 | Chat CRUD | ChatPage, session list, session creation, message history load |
| M5 | SSE streaming | streamChat(), Composer, MessageBubble streaming state, auto-scroll |
| M6 | Citations + Rail | CitationChip, MarginaliaRail, cited_chunk_ids → document lookup |
| M7 | Polish | Responsive sidebar, empty states, loading states, error states, a11y |

---

## 5. Design Notes

1. **`GET /chat/sessions`** — implemented on the backend. The localStorage fallback is a resilience measure, not the primary path.

2. **`cited_chunk_ids` are document IDs** — the marginalia rail shows filename, status, and upload date. If chunk-level records (page number, extracted snippet) are added to the backend in future, the rail can surface richer data without layout changes.
