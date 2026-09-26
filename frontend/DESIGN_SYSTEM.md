# Synapse — Design System & Page Spec

> Dokumen ini adalah **source of truth** untuk semua tim frontend (FE-1, FE-2) dan backend.
> Berdasarkan `Dashboard Synapsenya.png` yang ditetapkan sebagai desain final.
> Diupdate oleh: @nabilfauzandafa (FE-1)

---

## Color Palette

| Token | Hex | Dipakai untuk |
|---|---|---|
| `bg-app` | `#080d14` | Background utama |
| `bg-panel` | `#0d1117` | Card / panel |
| `bg-sidebar` | `#0d1117` | LeftNav + GuardianPanel |
| `border` | `slate-800/60` | Semua border |
| `text-primary` | `white` | Heading |
| `text-secondary` | `slate-400` | Subtitle / label |
| `text-muted` | `slate-500/600` | Placeholder, meta |
| `accent-blue` | `#3b82f6` | Guardian agent, active nav |
| `accent-purple` | `#a855f7` | Cortex agent |
| `accent-green` | `#22c55e` | Success, verified, healthy |
| `accent-yellow` | `#fbbf24` | Pending, warning |
| `accent-red` | `#ef4444` | High risk, failed, conflict |
| `accent-orange` | `#fb923c` | Executing |

---

## Layout Shell

```
┌─────────────────────────────────────────────────────┐
│  TopNavbar (h-12, bg-panel, border-b)               │
├──────────┬──────────────────────────┬───────────────┤
│ LeftNav  │  <Page Content>          │ GuardianPanel │
│ w-52     │  flex-1 overflow-y-auto  │ w-72          │
│          │                          │ (only on      │
│          │                          │ overview +    │
│          │                          │ guardian)     │
└──────────┴──────────────────────────┴───────────────┘
```

**TopNavbar props:** `isLive`, `nodeCount`, `edgeCount`  
**LeftNav props:** `activePage`, `onNavigate`, `pendingApprovals`  
**GuardianPanel props:** `pendingOps`, `onOpDecided`

---

## Navigation Pages (8 halaman)

| ID | Label | Komponen | Owner | Status |
|---|---|---|---|---|
| `overview` | Overview | `OverviewMain` | FE-1 | ✅ Done |
| `code-graph` | Code Graph | `CodeGraphPage` | FE-1 | 🔲 Needed |
| `guardian` | Guardian | `GuardianPage` | FE-1 | 🔲 Needed |
| `cortex` | Cortex | `CortexPage` | FE-1 | 🔲 Needed |
| `agents` | Agents | `AgentsPage` | FE-1 | 🔲 Needed |
| `approvals` | Approvals | `ApprovalsPage` | FE-2 | ✅ Done (Shann) |
| `operations` | Operations | `OperationsPage` | FE-2 | ✅ Done (Shann) |
| `security` | Security | `SecurityPage` | FE-1 | 🔲 Needed |
| `settings` | Settings | `SettingsPage` | FE-1 | 🔲 Needed |

---

## Page 1 — Code Graph

**Layout:** 2-kolom (graph fullwidth kiri + selected node panel kanan)

### Left Area — Code Graph Canvas
- `SynapseGraph` fullscreen dengan header panel:
  - Title: "Code Graph" + subtitle "Hybrid AST + semantic understanding"
  - Search bar: `Search files, symbols, docs...`
  - Filter pills: `All | File | Symbol | Dependency | Doc`
  - Zoom controls (+/−/reset)
  - Edge Relationships legend (calls, uses, defines, documents, depends on)
- Graph canvas mengisi sisa ruang

### Right Area — Selected Node Panel (`w-64`)
- **Selected Node card:**
  - Icon file type + nama node (e.g. `app.py`)
  - Fields: Type, Path, Imports, Referenced by
  - Button: "View Details →"
- **Live SSE Activity panel:**
  - Badge: `● Live`
  - List real-time events: timestamp + pesan singkat (last 5)

### Backend endpoints:
- `GET /graph/nodes` — load semua nodes
- `GET /graph/edges` — load semua edges
- `GET /stream` — SSE live updates
- `POST /explain_topic` — saat node diklik

---

## Page 2 — Guardian

**Layout:** single column scroll

### Header section:
- Badge: `● ACTIVE`
- Title: "Guardian"
- Subtitle: "Protecting risky changes • Reversible • Conflict-aware"

### Pending Operation Card (merah):
- Title: "Pending Operation" + badge `High Risk`
- Op name + description
- Meta table: Agent | Target | Blast Radius | Time
- **Reversibility Plan** (3 checklist steps)
- **Conflict Detection** panel (overlap resource alert)
- **Automation** checklist: SQLite snapshot / Verification checks / Rollback plan
- **Approval Gate** (requires human approval text)
- Tombol **Approve** (hijau) + **Deny** (merah)

### Operation Timeline:
- Horizontal step bar: Propose → Snapshot → Approve → Execute → Verify → Complete
- Progress indicator current step
- Button: "View Logs →"

### Backend endpoints:
- `GET /list_pending_approvals`
- `POST /approve_operation`
- `POST /execute_operation`
- `GET /operations`

---

## Page 3 — Cortex

**Layout:** 3-kolom (repo tree kiri | explain panel tengah | graph context kanan)

### Left — Repository Tree (`w-56`):
- Search bar
- File tree dengan expand/collapse
- Highlight node yang dipilih

### Center — Explain Topic:
- Badge: `REVIEW MODE`
- Input field: "How does the guardian module work?"
- Button: **Explain**
- Result sections:
  - **Definition** — teks penjelasan
  - **Mental Model** — cara pikir
  - **Example** — code snippet

### Right — Review Artifact + Graph Context:
- **Review Artifact card:**
  - Input path/diff
  - Button: "Run Review"
  - Scores: Completeness / Clarity / Correctness vs Spec / Risk (0–10)
- **Graph Context** mini-graph (subset dari force graph)

### Backend endpoints:
- `POST /explain_topic`
- `POST /review_artifact`
- `GET /graph/nodes` (untuk tree)
- `POST /find_path`
- `GET /complexity_report`

---

## Page 4 — Agents

**Layout:** header agents cards + 2-kolom bawah

### Top — 3 Agent Cards (horizontal):
Setiap card:
- Icon + Name (Guardian / Cortex / Review)
- Subtitle (Protection & Safety / Understanding & Review / Code Review & Analysis)
- Stats: Tasks (number) + Status (● Healthy / ● Running)

### Bottom Left — Current Tasks:
- List 3–5 tasks:
  - Agent name + task description + timestamp
  - Real-time dari SSE `operation_*` events

### Bottom Right — SSE Event Stream:
- Badge: `● Live`
- Scrollable list: timestamp | agent | event message
- Color-coded per agent

### Bottom — Agent Activity Chart:
- Line chart (Guardian=biru, Cortex=ungu, Review=abu)
- X-axis: waktu (10 tick)
- Y-axis: activity level

### Conflict sidebar:
- Badge count merah
- Op name + conflict details + "View →" button

### Recent Actions list:
- Agent | action | timestamp (relative)

### Backend endpoints:
- `GET /stream` — SSE untuk live tasks + event stream
- `GET /operations?limit=5` — recent actions
- `GET /repo_health` — agent health status

---

## Page 5 — Approvals ✅ (Shann)

Sudah diimplementasi oleh @ShannWasHere di commit `8c085c3`.

Spec: table dengan kolom TIME | OPERATION | RISK | AGENT | CONFLICTS + tombol Approve/Deny per row + Operation Details panel di bawah.

---

## Page 6 — Operations ✅ (Shann)

Sudah diimplementasi oleh @ShannWasHere di commit `8c085c3`.

Spec: Live Execution step tracker + Operation History table dengan filter.

---

## Page 7 — Security

**Layout:** 2x2 grid cards + event feed

### Security Overview card:
- Stats: Total Checks | Violations | Blocked Ops | Rules Active
- Badge: `● Healthy`

### Rule Engine card:
- Title + "Static rules & heuristics (not ML)"
- Policy: "Fail-closed (default)"
- Rule list:
  - Dangerous operation detection
  - Conflict detection (overlapping resources)
  - Reversibility requirement
  - Unknown operation fail-closed
  - Blast radius classification
- Button: "View Rules →"

### Adversarial Test Results card:
- N/M tests passed badge
- Checklist items (green=pass, red=fail)
- Button: "View Details →"

### Conflict Checks card:
- Count badge
- "N conflicts today" + list

### Rollback Verification card:
- N/M successful badge
- Recent rollbacks list dengan timestamp

### Security Event Feed:
- Chronological list: timestamp | event | status
- Color-coded: merah=blocked, kuning=warning, hijau=ok

### Backend endpoints:
- `GET /repo_health` — overall health
- `GET /operations?status=failed` — failed ops
- `GET /operations?status=rolled_back` — rollbacks
- `GET /stream` — live security events

---

## Page 8 — Settings

**Layout:** tabs kiri + content kanan

### Tabs:
`General | MCP / Server | Storage | Repository | Approval`

### Tab: General
- Platform Name (input: "Synapse")
- Environment (dropdown: Production)
- Log Level (dropdown)
- Developer mode toggle

### Tab: MCP / Server
- FastAPI Server status (Running / Port)
- SSE Stream status (Connected / Stream)
- MCP Task status

### Tab: Storage
- Database File path
- Tables: nodes, edges, operations
- Button: "View Schema →"

### Tab: Repository
- Default Branch (input)
- Workspace Path (input + Browse)
- Auto DB Migration toggle
- Enable Conflict Detection toggle
- Enable SSM Events toggle

### Tab: Approval
- Default approval mode
- Conflict auto-deny toggle

### Buttons: Reset to Default | Save Changes

### Backend endpoints:
- `GET /health` — server status
- `GET /graph/summary` — storage stats
- (Settings disimpan di localStorage frontend — tidak butuh backend endpoint baru)

---

## Component Library Bersama

### Badge variants
```tsx
// Risk
<RiskBadge level="high|medium|low|unknown" />

// Status
<StatusBadge status="pending|approved|executing|verified|failed|rolled_back" />

// Agent
<AgentBadge agent="guardian|cortex|review" />
```

### Shared tokens (Tailwind classes)
```
panel:     bg-[#0d1117] rounded-xl border border-slate-800/60
card:      bg-slate-800/40 rounded-xl border border-slate-700/60
btn-green: bg-green-600 hover:bg-green-500 text-white text-xs font-bold rounded-lg py-2
btn-red:   bg-red-700/80 hover:bg-red-600 text-white text-xs font-bold rounded-lg py-2
btn-ghost: border border-slate-700/60 text-slate-400 hover:text-slate-200 hover:border-slate-600
```

---

## Backend Endpoints — Mapping ke Halaman

| Endpoint | Method | Dipakai di halaman |
|---|---|---|
| `/stream` | GET SSE | Code Graph, Agents, Operations, Security |
| `/graph/nodes` | GET | Code Graph, Cortex |
| `/graph/edges` | GET | Code Graph |
| `/graph/summary` | GET | Settings (Storage tab) |
| `/understand_repo` | POST | Code Graph (trigger ingest) |
| `/explain_topic` | POST | Code Graph (node click), Cortex |
| `/review_artifact` | POST | Cortex |
| `/repo_health` | GET | Overview, Agents, Security |
| `/complexity_report` | GET | Cortex |
| `/find_path` | POST | Cortex |
| `/suggest_refactor` | POST | Cortex |
| `/list_pending_approvals` | GET | Guardian, Approvals |
| `/propose_operation` | POST | Guardian (demo) |
| `/approve_operation` | POST | Guardian, Approvals, GuardianPanel |
| `/execute_operation` | POST | Guardian, Approvals, GuardianPanel |
| `/operations` | GET | Operations, Approvals, Agents |
| `/health` | GET | Settings |

---

## Mock Data untuk Mode `NEXT_PUBLIC_USE_LIVE_SSE=false`

Semua halaman harus berfungsi di mock mode. Gunakan data dari:
- `lib/mockData.ts` — MOCK_NODES, MOCK_LINKS, MOCK_TIMELINE
- `lib/mockAgents.ts` (baru, dibuat FE-1) — mock agent stats + tasks + events
- `lib/mockSecurity.ts` (baru, dibuat FE-1) — mock security report

---

## Kontrak API Baru (Backend perlu expose)

Beberapa endpoint baru yang **dibutuhkan frontend** untuk 8 halaman penuh:

| Endpoint | Method | Payload | Response | Dibutuhkan untuk |
|---|---|---|---|---|
| `/agents/status` | GET | — | `{guardian:{tasks,healthy}, cortex:{tasks,healthy}, review:{tasks,healthy}}` | Agents page |
| `/security/report` | GET | — | `{total_checks, violations, blocked_ops, rules_active, adversarial_results, recent_events}` | Security page |
| `/settings` | GET | — | `{platform_name, env, log_level, workspace_path, ...}` | Settings page |
| `/settings` | POST | config object | `{ok:true}` | Settings page |

Jika belum tersedia, frontend akan **fallback ke mock data** secara otomatis.

---

## File Structure (Post-Redesign)

```
frontend/
├── DESIGN_SYSTEM.md         ← dokumen ini
├── PRD.md                   ← deliverable spec (diupdate)
├── README.md                ← cara run + endpoint map (diupdate)
├── app/
│   ├── page.tsx             ← shell layout 3-kolom
│   ├── globals.css
│   ├── layout.tsx
│   └── api/graph/route.ts
├── components/
│   ├── LeftNav.tsx          ← FE-1: navigasi kiri
│   ├── TopNavbar.tsx        ← FE-1: top bar
│   ├── GuardianPanel.tsx    ← FE-1: right panel
│   ├── OverviewMain.tsx     ← FE-1: halaman overview
│   ├── SynapseGraph.tsx     ← FE-1+2: force graph canvas
│   ├── OperationsSidebar.tsx← FE-2: sidebar ops+log
│   ├── pages/
│   │   ├── CodeGraphPage.tsx  ← FE-1 🔲
│   │   ├── GuardianPage.tsx   ← FE-1 🔲
│   │   ├── CortexPage.tsx     ← FE-1 🔲
│   │   ├── AgentsPage.tsx     ← FE-1 🔲
│   │   ├── SecurityPage.tsx   ← FE-1 🔲
│   │   └── SettingsPage.tsx   ← FE-1 🔲
│   └── shared/
│       ├── RiskBadge.tsx      ← FE-1 🔲
│       ├── StatusBadge.tsx    ← FE-1 🔲
│       └── AgentBadge.tsx     ← FE-1 🔲
├── hooks/
│   ├── useSSE.ts
│   └── useMockSimulation.ts
└── lib/
    ├── types.ts
    ├── mockData.ts
    ├── mockAgents.ts          ← FE-1 🔲
    ├── mockSecurity.ts        ← FE-1 🔲
    └── nodeVisuals.ts
```

---

## Checklist Implementasi

### FE-1 @nabilfauzandafa
- [x] OverviewMain (Code Graph panel + Timeline + Risk & Activity + Feature Cards)
- [x] LeftNav (8 item + badge)
- [x] TopNavbar
- [x] GuardianPanel (semua pending ops, scrollable)
- [ ] CodeGraphPage — graph fullscreen + node panel + SSE activity
- [ ] GuardianPage — pending op detail + reversibility + timeline
- [ ] CortexPage — repo tree + explain + review + graph context
- [ ] AgentsPage — 3 agent cards + tasks + SSE stream + activity chart
- [ ] SecurityPage — stats + rule engine + adversarial + event feed
- [ ] SettingsPage — tabs: General + MCP + Storage + Repository
- [ ] Shared badges (RiskBadge, StatusBadge, AgentBadge)
- [ ] lib/mockAgents.ts
- [ ] lib/mockSecurity.ts

### FE-2 @ShannWasHere
- [x] OperationsSidebar (ops tab + log tab)
- [x] ApprovalsPage (table + approve/deny + detail)
- [x] OperationsPage (live execution + history table)
- [x] GuardianPanel — semua pending ops (commit 8c085c3)

### Backend @DhikaSusheno / @Masrendra
- [ ] `GET /agents/status` — agent health + task count
- [ ] `GET /security/report` — security stats + adversarial results
- [ ] `GET /settings` + `POST /settings` — platform config
- (semua existing endpoint sudah ada dan berjalan)
