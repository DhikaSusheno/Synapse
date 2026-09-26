# Synapse Frontend

Owner FE-1: [@nabilfauzandafa](https://github.com/nabilfauzandafa) — Graph + Halaman Core  
Owner FE-2: [@ShannWasHere](https://github.com/ShannWasHere) — Approvals + Operations + GuardianPanel

Stack: **Next.js 14** + **react-force-graph-2d** + **Tailwind CSS**

> Lihat [`DESIGN_SYSTEM.md`](./DESIGN_SYSTEM.md) untuk spec visual lengkap 8 halaman.

## Cara Run

```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
# → http://localhost:3000
```

## Mode Operasi

| `NEXT_PUBLIC_USE_LIVE_SSE` | Mode | Keterangan |
|---|---|---|
| `false` (default) | **MOCK** | Semua halaman pakai mock data. Tidak butuh backend. |
| `true` | **LIVE** | Semua data dari backend FastAPI port 8000. |

## Cara Run Lengkap (Backend + Frontend)

```bash
# 1. Jalankan backend
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
# → http://localhost:8000/docs

# 2. Frontend (terminal baru)
cd frontend
npm install && cp .env.local.example .env.local
# Set NEXT_PUBLIC_USE_LIVE_SSE=true di .env.local
npm run dev
# → http://localhost:3000

# 3. Ingest repo
curl -X POST http://localhost:8000/understand_repo \
  -H "Content-Type: application/json" \
  -d '{"repo_path": ".."}'  
```

## 8 Halaman Dashboard

| Nav | Halaman | Owner | Status |
|---|---|---|---|
| Overview | `OverviewMain.tsx` | FE-1 | ✅ Done |
| Code Graph | `pages/CodeGraphPage.tsx` | FE-1 | ✅ Done |
| Guardian | `pages/GuardianPage.tsx` | FE-1 | ✅ Done |
| Cortex | `pages/CortexPage.tsx` | FE-1 | ✅ Done |
| Agents | `pages/AgentsPage.tsx` | FE-1 | ✅ Done |
| Approvals | `app/page.tsx#ApprovalsPage` | FE-2 | ✅ Done (Shann) |
| Operations | `app/page.tsx#OperationsPage` | FE-2 | ✅ Done (Shann) |
| Security | `pages/SecurityPage.tsx` | FE-1 | ✅ Done |
| Settings | `pages/SettingsPage.tsx` | FE-1 | ✅ Done |

## Endpoints Backend yang Dipakai

| Method | Endpoint | Halaman |
|---|---|---|
| GET | `/stream` | Code Graph, Agents, Operations |
| GET | `/graph/nodes` | Code Graph, Cortex |
| GET | `/graph/edges` | Code Graph |
| GET | `/graph/summary` | Settings (Storage tab) |
| POST | `/understand_repo` | Code Graph (trigger ingest) |
| POST | `/explain_topic` | Code Graph (klik node), Cortex |
| POST | `/review_artifact` | Cortex |
| GET | `/repo_health` | Overview, Agents, Security |
| GET | `/complexity_report` | Cortex |
| POST | `/find_path` | Cortex |
| POST | `/suggest_refactor` | Cortex |
| GET | `/list_pending_approvals` | Guardian, Approvals |
| POST | `/approve_operation` | Guardian, Approvals, GuardianPanel |
| POST | `/execute_operation` | Guardian, Approvals, GuardianPanel |
| GET | `/operations` | Operations, Approvals, Agents |
| GET | `/health` | Settings |

## Endpoint Backend Baru yang Dibutuhkan

Frontend fallback ke mock data jika endpoint ini belum tersedia:

| Method | Endpoint | Response | Dibutuhkan untuk |
|---|---|---|---|
| GET | `/agents/status` | `{guardian,cortex,review: {tasks,healthy}}` | Agents page |
| GET | `/security/report` | security stats + adversarial results | Security page |
| GET | `/settings` | platform config object | Settings page |
| POST | `/settings` | `{ok:true}` | Settings page |

## SSE Events yang Ditangani

| Event | Effect |
|---|---|
| `graph_update` | Tambah nodes ke graph |
| `ingest_progress` | Progress overlay di canvas |
| `operation_proposed` | Node baru `pending` (pulse kuning) |
| `operation_approved` | Node → `approved` |
| `operation_denied` | EventLog + Agents stream |
| `operation_executing` | Node → `executing` (glow oranye) |
| `operation_verified` | Node → `verified` (hijau) |
| `operation_failed` | Node → `failed` (blink merah) |
| `operation_rolled_back` | Node → `rolled_back` |
| `review_done` | EventLog + Agents stream |
| `health_report` | EventLog |
| `refactor_suggestion` | EventLog |

## Struktur File

```
frontend/
├── DESIGN_SYSTEM.md          ← spec visual 8 halaman (source of truth)
├── PRD.md                    ← deliverable spec
├── README.md                 ← file ini
├── app/
│   ├── page.tsx              ← shell + routing 8 halaman
│   ├── globals.css
│   ├── layout.tsx
│   └── api/graph/route.ts
├── components/
│   ├── LeftNav.tsx           ← FE-1
│   ├── TopNavbar.tsx         ← FE-1
│   ├── GuardianPanel.tsx     ← FE-1+2
│   ├── OverviewMain.tsx      ← FE-1
│   ├── SynapseGraph.tsx      ← FE-1+2
│   ├── OperationsSidebar.tsx ← FE-2
│   ├── pages/
│   │   ├── CodeGraphPage.tsx   ← FE-1 ✅
│   │   ├── GuardianPage.tsx    ← FE-1 ✅
│   │   ├── CortexPage.tsx      ← FE-1 ✅
│   │   ├── AgentsPage.tsx      ← FE-1 ✅
│   │   ├── SecurityPage.tsx    ← FE-1 ✅
│   │   └── SettingsPage.tsx    ← FE-1 ✅
│   └── shared/
│       ├── RiskBadge.tsx       ← FE-1 ✅
│       ├── StatusBadge.tsx     ← FE-1 ✅
│       └── AgentBadge.tsx      ← FE-1 ✅
├── hooks/
│   ├── useSSE.ts             ← SSE + exponential backoff
│   └── useMockSimulation.ts
└── lib/
    ├── types.ts
    ├── mockData.ts
    ├── mockAgents.ts         ← FE-1 ✅
    ├── mockSecurity.ts       ← FE-1 ✅
    └── nodeVisuals.ts
```

## Bug Mitigations

| Bug | Backend Fix | Frontend Mitigation |
|---|---|---|
| BUG-08: SSE not thread-safe | `cc9bd5a` | `useSSE` exponential backoff |
| BUG-07: double-execute race | `9d7456a` | N/A |
| BUG-A: Windows path rollback | `6d1813f` | N/A |
| BUG-B: partial migration | `6d1813f` | N/A |
| BUG-D: approvals data leak | `6d1813f` | N/A |
