# PRD: GitHub Repository Integration + LLM Endpoint Integration

## 1. Problem Statement

Pengembang dan tim butuh:
1. **Koneksi GitHub fleksibel** — Bisa connect ke repo GitHub mana saja (public/private, org/owner lain) + browse struktur file, tanpa clone manual
2. **Pemilihan folder lokal** — Bisa pick folder lokal di laptop sebagai "repo" tanpa Git
3. **LLM Multi-provider** — Synapse harus bisa pakai LLM apapun (IBM, OpenAI, Anthropic, NVIDIA, DeepSeek, Ollama, custom endpoint) untuk:
   - Explain code dari graph
   - Review artifact/diff
   - Generate refactor suggestions
   - Answer questions tentang codebase
4. **Context-aware** — LLM harus akses knowledge graph Synapse (nodes, edges, code snippets) sebagai context, bukan cuma raw text

---

## 2. Goals (MVP Scope)

| # | Capability | Priority |
|---|---|---|
| 1 | GitHub OAuth + PAT authentication | P0 |
| 2 | Repo picker (search org/user/repo) + branch picker | P0 |
| 3 | File tree browser (lazy load, search, filter) | P0 |
| 4 | Local folder picker (File System Access API / dialog) | P0 |
| 5 | LLM Provider registry (configurable per project) | P0 |
| 6 | LLM Chat panel di Cortex/Overview (context-aware) | P0 |
| 6 | `explain_topic`, `review_artifact`, `suggest_refactor` powered by LLM | P1 |
| 7 | RAG: embed snippets → vector search → inject ke prompt | P1 |
| 8 | Provider switching + model selection di Settings | P1 |
| 9 | Cost/token tracking per request | P2 |

---

## 3. Non-Goals (Out of Scope)

- Git write operations (commit/push/PR) — read-only dulu
- Self-hosted GitLab/Gitea/Bitbucket (hanya GitHub MVP)
- Fine-tuning / training models
- Multi-user collaboration / real-time editing

---

## 4. Technical Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        FRONTEND (Next.js)                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ GitHub Auth  │  │ Local Folder │  │  LLM Provider Config │  │
│  │ (OAuth/PAT)  │  │ Picker       │  │  (Settings Page)     │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘  │
│         │                 │                      │              │
│         ▼                 ▼                      ▼              │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │           Repository Context Provider                    │  │
│  │  - GitHub API client (REST + GraphQL)                    │  │
│  │  - Local FS reader (File System Access API)              │  │
│  │  - Unified FileTree interface                            │  │
│  └────────────────────┬─────────────────────────────────────┘  │
│                       │                                        │
│                       ▼                                        │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              LLM Gateway (Client-side SDK)               │  │
│  │  - Provider registry: OpenAI, Anthropic, IBM, NVIDIA,   │  │
│  │    DeepSeek, Ollama, Custom OpenAI-compatible            │  │
│  │  - Streaming responses, tool calling, structured output  │  │
│  │  - Token/cost tracking                                   │  │
│  └────────────────────┬─────────────────────────────────────┘  │
│                       │                                        │
└───────────────────────┼────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────────┐
│                      BACKEND (FastAPI)                          │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐              │
│  │ Graph DB    │ │ LLM Proxy   │ │ GitHub Proxy│              │
│  │ (SQLite)    │ │ (optional)  │ │ (rate limit)│              │
│  └─────────────┘ └─────────────┘ └─────────────┘              │
└─────────────────────────────────────────────────────────────────┘
```

---

## 5. Data Models

### 5.1 GitHub Connection
```typescript
interface GitHubConnection {
  id: string;
  type: 'oauth' | 'pat';
  accessToken: string;           // encrypted
  scope: string[];
  user: { login: string; avatar: string };
  createdAt: string;
}
```

### 5.2 Repository Reference
```typescript
interface RepoRef {
  id: string;                    // "github:owner/repo#branch"
  source: 'github' | 'local';
  github?: { owner: string; repo: string; branch: string; };
  local?: { path: string; handle: FileSystemDirectoryHandle };
  name: string;
  lastSynced: string;
}
```

### 5.3 LLM Provider Config
```typescript
interface LLMProvider {
  id: string;
  name: string;                          // "openai", "anthropic", "ibm", "nvidia", "deepseek", "ollama", "custom"
  type: 'openai' | 'anthropic' | 'ibm' | 'nvidia' | 'deepseek' | 'ollama' | 'openai-compatible';
  baseUrl?: string;                      // for custom/ollama
  apiKey?: string;                       // encrypted
  models: string[];                      // ["gpt-4o", "gpt-4o-mini", ...]
  defaultModel: string;
  maxTokens: number;
  supportsTools: boolean;
  supportsVision: boolean;
  enabled: boolean;
}
```

### 5.4 Project LLM Config
```typescript
interface ProjectLLMConfig {
  projectId: string;
  providerId: string;
  model: string;
  temperature: number;
  maxTokens: number;
  systemPrompt?: string;
  ragEnabled: boolean;
  ragTopK: number;
}
```

---

## 6. API Endpoints (Backend)

### GitHub Proxy (rate-limited, cached)
```
GET  /api/github/user                    // current user info
GET  /api/github/repos                   // list accessible repos
GET  /api/github/repos/:owner/:repo/tree // file tree (recursive)
GET  /api/github/repos/:owner/:repo/contents/:path // file content
GET  /api/github/search?q=...            // search code/files
```

### LLM Proxy (optional - for server-side RAG/embeddings)
```
POST /api/llm/chat
POST /api/llm/embeddings
POST /api/llm/explain
POST /api/llm/review
POST /api/llm/refactor
```

### Project Config
```
GET  /api/projects/:id/llm-config
PUT  /api/projects/:id/llm-config
GET  /api/llm/providers                  // list all providers
POST /api/llm/providers                  // add custom provider
```

---

## 7. Frontend Components (New)

### Settings Page (`/settings`)
- **GitHub Tab**: OAuth connect, PAT input, connected account badge, revoke
- **Repositories Tab**: List connected repos, "Add Repository" modal (search + branch picker), "Add Local Folder" button
- **LLM Providers Tab**: Table of providers (built-in + custom), toggle enable/disable, "Add Custom Provider" modal
- **Project LLM Tab**: Per-project provider/model selection, RAG toggle, system prompt editor, temperature/maxTokens

### Repository Browser (Sidebar/Modal)
- Tree view with lazy load (expand folder → fetch children)
- Search/filter (file name, type, content)
- Click file → open in code viewer / add to LLM context
- Multi-select → "Add to LLM Context" button

### LLM Chat Panel (Cortex/Overview/Guardian)
- Floating panel / split view
- Message history (persisted per project)
- Streaming response
- "Attach File" / "Attach Selection" buttons
- "Use Graph Context" toggle (injects relevant nodes/edges as system context)
- Copy code blocks, regenerate, rate response

### RAG Pipeline (Client-side first, server-side optional)
1. User selects files/folders → `Add to Context`
2. Frontend chunks files (by function/class) → sends to `/api/llm/embeddings`
3. Embeddings stored in local IndexedDB (client) or SQLite (server)
4. On query: embed query → vector search (cosine) → top-K chunks injected as system context

---

## 8. Security

- Access tokens encrypted at rest (AES-GCM, key from env `ENCRYPTION_KEY`)
- PAT/OAuth tokens never logged
- GitHub proxy adds rate limiting (5000 req/hr per token)
- LLM proxy strips API keys from logs
- Local folder access: File System Access API (user gesture required)
- CSP headers, no inline scripts

---

## 9. Implementation Phases

| Phase | Deliverable | Est. Effort |
|---|---|---|
| **1. Foundation** | DB schema, GitHub OAuth/PAT, Repo picker modal, File tree | 3 days |
| **2. GitHub Integration** | File tree browser, file content viewer, search | 2 days |
| **3. Local Folder** | File System Access API, recursive scan, virtual tree | 1 day |
| **4. LLM Gateway** | Provider registry, chat completion, streaming, tool calling | 3 days |
| **5. Cortex Integration** | Chat panel, explain/review/refactor via LLM, context injection | 2 days |
| **6. RAG** | Chunking, embeddings (client/server), vector search, context injection | 2 days |
| **6. Settings UI** | Providers table, project config, model selector, RAG toggle | 1 day |
| **8. Polish** | Error handling, loading states, empty states, docs | 1 day |
| **Total** | **MVP** | **~15 days** |

---

## 10. Acceptance Criteria (Definition of Done)

- [ ] User bisa connect GitHub via OAuth atau PAT
- [ ] User bisa search dan pilih repo + branch
- [ ] User bisa browse file tree (lazy load, expand/collapse, search)
- [ ] User bisa pilih folder lokal di laptop
- [ ] User bisa lihat isi file (syntax highlight)
- [ ] User bisa konfigurasi LLM provider (OpenAI, Anthropic, dll)
- [ ] User bisa pilih provider/model per project
- [ ] Cortex chat panel bisa kirim prompt + dapat streaming response
- [ ] `explain_topic` pakai LLM + graph context
- [ ] `review_artifact` pakai LLM + graph context
- [ ] `suggest_refactor` pakai LLM + graph context
- [ ] RAG: attach file → query → context injected
- [ ] Settings page: provider management, project LLM config
- [ ] Semua test pass (backend 175, frontend 54+)
- [ ] Demo migration script 7/7 PASS
- [ ] Build success, TypeScript clean, ESLint clean