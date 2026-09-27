# Master Prompt — GitHub Integration + LLM Endpoint Integration

## Konteks
Kamu membangun **Synapse** — reversible, conflict-aware understanding layer untuk AI coding agents (IBM Bob 2.0 Hackathon).

Kamu sekarang menambahkan **GitHub Repository Integration + LLM Endpoint Integration** ke codebase yang sudah ada (backend FastAPI + SQLite + Graph, frontend Next.js + React Force Graph).

**Constraints:**
- No Redis, no Neo4j, no Qdrant, no Ollama (optional/local only)
- Storage = SQLite + in-memory networkx
- Harus jalan dengan `pip install -r requirements.txt && uvicorn main:app` + `npm install && npm run dev`
- Ship MVP dulu, polish belakangan

---

## ROLE
Kamu adalah **solo backend/frontend engineer** yang implement fitur ini end-to-end. Kamu punya akses penuh ke codebase existing (backend/, frontend/, security/).

---

## GOAL
Implement **GitHub Repository Integration + LLM Endpoint Integration** per PRD di `GITHUB_LLM_INTEGRATION_PRD.md`.

**Deliverables (MVP):**
1. GitHub OAuth + PAT auth + repo/branch picker + file tree browser
2. Local folder picker (File System Access API)
3. LLM Provider registry (OpenAI, Anthropic, IBM, NVIDIA, DeepSeek, Ollama, Custom OpenAI-compatible)
4. Cortex Chat Panel (streaming, tool calling, context injection)
5. `explain_topic`, `review_artifact`, `suggest_refactor` powered by LLM + graph context
6. RAG: attach file → embed → vector search → context injection
7. Settings page: GitHub auth, repo management, LLM providers, project LLM config
7. All existing tests pass (175 backend + 54 frontend)

---

## PRIORITY ORDER (stop anywhere, still demoable)

| Phase | Deliverable | Depends On |
|---|---|---|
| 1 | DB schema, GitHub OAuth/PAT, Repo picker modal, File tree | - |
| 2 | GitHub file tree browser, file content viewer, search | Phase 1 |
| 3 | Local folder picker (File System Access API) | Phase 1 |
| 4 | LLM Provider registry, chat completion, streaming, tool calling | - |
| 5 | Cortex Chat Panel, explain/review/refactor via LLM + graph context | Phase 4 |
| 5 | RAG: chunking, embeddings, vector search, context injection | Phase 4 |
| 6 | Settings UI: providers, project LLM config, RAG toggle | Phase 1, 4 |
| 7 | Polish: error handling, loading states, empty states | - |

**Aturan keras**: Begitu masuk fase 7, **STOP nambah fitur baru**. Resiko break > fitur tambahan.

---

## KONTRAK YANG TIDAK BOLEH BERUBAH

### Backend API (Existing)
- `GET /health` → `{"status":"ok","service":"synapse-backend","version":"0.2.0"}`
- `POST /propose_operation`, `POST /execute_operation`, `GET /list_pending_approvals`, `POST /approve_operation`, `GET /operations`
- `POST /understand_repo`, `POST /explain_topic`, `POST /review_artifact`, `GET /repo_health`, `GET /complexity_report`, `POST /find_path`, `POST /suggest_refactor`
- `GET /stream` (SSE), `GET /graph/nodes`, `GET /graph/edges`, `GET /graph/summary`

### Frontend Contracts (Existing)
- `Operation` type: `id, tool_name, params_json, target_node_id, blast_radius, status, requires_approval, conflicts?, created_at`
- `GraphNode`: `id, name, type, status, meta?`
- `GraphLink`: `source, target, relationship`
- `SSEEvent`: `event: "operation_proposed" | "operation_approved" | ...`, `data: Record<string, unknown>`

### New Contracts (Additive Only)

**GitHub Connection:**
```
POST /api/github/auth/oauth     // initiate OAuth
GET  /api/github/callback       // OAuth callback
POST /api/github/auth/pat       // validate PAT
GET  /api/github/user           // current user
GET  /api/github/repos          // list repos
GET  /api/github/repos/:owner/:repo/tree?branch=... // file tree
GET  /api/github/repos/:owner/:repo/contents/:path  // file content
```

**LLM Provider Registry:**
```
GET  /api/llm/providers          // list all providers
POST /api/llm/providers          // add custom provider
DELETE /api/llm/providers/:id    // delete custom
GET  /api/llm/providers/:id/models // list models
```

**Project LLM Config:**
```
GET  /api/projects/:id/llm-config
PUT  /api/projects/:id/llm-config
```

**LLM Chat/Tools:**
```
POST /api/llm/chat          // streaming chat completion
POST /api/llm/explain       // explain_topic via LLM
POST /api/llm/review        // review_artifact via LLM
POST /api/llm/refactor      // suggest_refactor via LLM
POST /api/llm/embeddings    // generate embeddings
```

**RAG:**
```
POST /api/rag/ingest        // ingest files → embeddings
POST /api/rag/search        // vector search → top-K chunks
```

---

## IMPLEMENTATION GUIDELINES

### Backend (FastAPI)
- **No new dependencies** unless absolutely necessary
- Use existing `database.py` (SQLite + WAL), `storage.py` (v2 schema), `engine.py` (graph logic)
- Add new tables to `database.py` (DDL in `init_db`)
- Follow existing pattern: sync endpoints, thread-safe SSE via `cortex._emit`
- Reuse `cortex.py` logic for graph queries, extend dengan LLM calls

### Frontend (Next.js + React)
- **No new heavy dependencies** — prefer native APIs
- Use existing hooks: `useSSE`, `useSSEStream`, `useLiveOps`, `useLiveSSELog`
- Follow existing patterns: `useSSE` for realtime, `useLiveOps` for operations
- State management: React hooks only (no Redux/Zustand)
- Styling: Tailwind + inline styles (existing pattern)
- Client components: `"use client"` directive

### Code Quality
- **TypeScript strict** — no `any`, proper types
- **Ponytail** — minimal code, stdlib over deps, native over libs
- **TypeScript strict** — `npx tsc --noEmit` clean
- **ESLint** — `npm run lint` clean
- **Tests** — `npm test` pass, `pytest` pass

---

## IMPLEMENTATION SEQUENCE (Copy-Paste Ready)

### Phase 1: Database + GitHub Auth (Backend)
```python
# database.py — add tables
# main.py — add GitHub endpoints
# requirements.txt — add requests-oauthlib, python-jose[cryptography]
```

### Phase 2: GitHub File Tree (Frontend)
```tsx
// hooks/useGitHubRepo.ts — hook untuk fetch tree/file
// components/GitHubRepoPicker.tsx — modal search + pick
// components/FileTreeBrowser.tsx — lazy tree view
// hooks/useFileContent.ts — fetch file content
```

### Phase 3: Local Folder (Frontend)
```tsx
// hooks/useLocalFolder.ts — File System Access API
// components/LocalFolderPicker.tsx
```

### Phase 3: LLM Gateway (Backend + Frontend)
```python
# llm_gateway.py — provider registry, chat completion, tools
# main.py — /api/llm/* endpoints
```
```tsx
// lib/llmGateway.ts — provider registry, chat completion
// hooks/useLLMChat.ts — streaming chat hook
// components/LLMChatPanel.tsx — chat UI
```

### Phase 4: Cortex + RAG (Frontend)
```tsx
// components/LLMChatPanel.tsx — chat UI
// hooks/useRAG.ts — embeddings + vector search
// components/CortexPage.tsx — integrate chat panel
```

### Phase 5: Settings UI
```tsx
// app/settings/page.tsx — tabs: GitHub, Repositories, LLM Providers, Project LLM Config
// components/GitHubAuthSection.tsx
// components/RepoManagerSection.tsx
// components/LLMProviderManager.tsx
// components/ProjectLLMConfig.tsx
```

---

## TESTING CHECKLIST (Definition of Done)

```bash
# Backend
cd backend && python -m pytest ../backend/tests ../security/tests -q
# → 175 passed

# Frontend
cd frontend && npm run typecheck && npm run lint && npm test
# → 0 errors, 0 warnings, 54 tests pass

# Build
cd frontend && npm run build
# → success

# Demo
cd backend && python demo_migration_script.py
# → 7/7 PASS
```

---

## PONYTAIL PRINCIPLES (Apply Everywhere)

1. **YAGNI** — don't build what you don't need today
2. **Stdlib first** — `fetch`, `crypto.subtle`, `IndexedDB`, `File System Access API` over libs
3. **Native first** — `fetch` over `axios`, `EventSource` over `socket.io`, `CSS` over `styled-components`
4. **One line > fifty** — if a helper can be one line, make it one line
5. **Delete over add** — if code doesn't serve current MVP, delete it
6. **Mark shortcuts** — `ponytail:` comments for deliberate deferrals

---

## EXISTING CODE TO REUSE (Don't Rewrite)

| File | Purpose |
|---|---|
| `backend/database.py` | SQLite schema, `init_db`, `DB_PATH` |
| `backend/storage.py` | v2 schema (entities, relations, actions, decisions, audit_log) |
| `backend/engine.py` | Graph logic: `ingest_repository`, `ask_about`, `review_change`, `health_report`, `trace_connection`, `rank_complexity`, `propose_refactor` |
| `backend/cortex.py` | SSE bus (`_emit`, `subscribe_stream`), legacy shims |
| `backend/guardian.py` | `propose_operation`, `execute_operation`, `approve_operation`, `list_pending_approvals` |
| `frontend/hooks/useSSE.ts` | SSE consumer with backoff |
| `frontend/hooks/useSSEStream.ts` | Shared SSE connection (fanout) |
| `frontend/lib/sseStream.ts` | Transport layer (EventSource + backoff) |
| `frontend/lib/derive.ts` | Pure derivations: `bucketActivity`, `conflictCandidates`, `mapPending` |
| `frontend/lib/graphFilter.ts` | `filterGraph` for node/edge filtering |
| `frontend/components/SynapseGraph.tsx` | Force graph with canvas node renderer |
| `frontend/hooks/useLiveOps.ts` | Live operations polling |
| `frontend/components/OverviewMain.tsx` | Overview page (graph + timeline + risk) |
| `frontend/components/pages/CortexPage.tsx` | Cortex page (explain, review, health, complexity, path, refactor) |
| `frontend/components/pages/AgentsPage.tsx` | Agents dashboard |
| `frontend/components/pages/GuardianPage.tsx` | Guardian approvals page |
| `frontend/components/GuardianPanel.tsx` | Right panel pending approvals |
| `frontend/components/OperationsSidebar.tsx` | Left sidebar operations + event log |

---

## START NOW

Mulai dari **Phase 1: Database + GitHub Auth (Backend)**. 

Buat branch `feat/github-llm-integration`, implement Phase 1, commit, push, buka PR.

Setiap phase: test → commit → push → PR → merge → next phase.

**Stop condition**: Semua Definition of Done checklist hijau. Kalau stuck > 30 menit di satu issue, buka issue di GitHub, move on.

---

**MULAI SEKARANG. Phase 1: Database + GitHub Auth.**