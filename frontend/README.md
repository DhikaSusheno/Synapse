# Synapse Frontend

Owner FE-1: [@nabilfauzandafa](https://github.com/nabilfauzandafa) — Graph + Halaman Core  
Owner FE-2: [@ShannWasHere](https://github.com/ShannWasHere) — Approvals + Operations + GuardianPanel

Stack: **Next.js 14** + **react-force-graph-2d** + **Tailwind CSS**

> Lihat [`DESIGN_SYSTEM.md`](./DESIGN_SYSTEM.md) untuk spec visual lengkap 9 halaman + landing.
> Lihat [`PRD.md`](./PRD.md) untuk scope, bug ledger, dan checklist demo hackathon.
> Lihat [`MASTER_PROMPT.md`](./MASTER_PROMPT.md) untuk prompt lanjutan ke AI agent.

## Routes

| Route | Isi | Rendering |
|---|---|---|
| `/` | Dashboard 9 halaman (shell 3 kolom) | Client |
| `/landing` | Explainer untuk juri hackathon | Server, statis |
| `/api/graph` | Proxy ke backend `/graph/nodes` + `/graph/edges` | Server |

## Cara Run

```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
# dashboard → http://localhost:3000
# landing   → http://localhost:3000/landing
```

## Mode Operasi

| `NEXT_PUBLIC_USE_LIVE_SSE` | Mode | Keterangan |
|---|---|---|
| `false` (default) | **DEMO** | Halaman memakai sample data, banner berlabel `DEMO DATA`. Tidak butuh backend. |
| `true` | **LIVE** | Semua data dari backend FastAPI port 8000. Banner hilang kalau `/health` OK. |

Status koneksi di banner, `TopNavbar`, dan `LeftNav` semuanya datang dari satu
poller: `hooks/useBackendStatus.ts`. Jangan panggil `/health` dari komponen lain.

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

## 9 Halaman Dashboard

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
| GET | `/repo_health` | Cortex (Repo Health card) |
| GET | `/complexity_report` | Cortex (Complexity Ranking card) |
| POST | `/find_path` | Cortex (Find Path card) |
| POST | `/suggest_refactor` | Cortex (Refactor Suggestions card) |
| GET | `/operations` | Operations, Approvals, Agents, Guardian, GuardianPanel, Security |
| POST | `/approve_operation` | Guardian, Approvals, GuardianPanel (via `decideOperation`) |
| POST | `/execute_operation` | Guardian, Approvals, GuardianPanel (via `decideOperation`) |

`/list_pending_approvals` tidak dipakai lagi: endpoint itu tidak mengirim `conflicts`.
Pending + History + conflict banner semuanya dari satu `GET /operations?limit=100`
(`useOperations()` di `app/page.tsx`, filter `requires_approval === 1` untuk pending).
Kontrak: `/approve_operation` → `{ ok, status, new_status }`; execute hanya boleh
setelah approve `ok`, itu diurus satu helper `lib/operations.ts` (`decideOperation`).

## Endpoint Backend yang Dibutuhkan

Tidak ada endpoint baru untuk halaman yang sudah ada. Semua halaman unmet dari endpoint yang sudah ada:

| Halaman | Sumber data |
|---|---|
| Agents | `GET /operations?limit=100` (via `useLiveOps`) + `GET /graph/summary` + SSE `/stream` |
| Security | `GET /operations?limit=100` + SSE `/stream` |
| Settings | `GET /health` + `GET /graph/summary` |

Statistik Agents/Security diturunkan di client (`lib/derive.ts`), bukan mock.
Saat `NEXT_PUBLIC_USE_LIVE_SSE=false` halaman menampilkan badge "Env off" + empty state.

SSE: satu koneksi `/stream` per app, bukan per halaman. Transport tunggal ada di
`lib/sseStream.ts` (fanout + exponential backoff BUG-08), dipakai lewat
`hooks/useSSEStream.ts`. Issue #38.

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
├── DESIGN_SYSTEM.md          ← spec visual 9 halaman + landing (source of truth)
├── PRD.md                    ← scope, bug ledger B-01..B-27, checklist demo
├── MASTER_PROMPT.md          ← prompt untuk lanjutkan ke AI agent
├── README.md                 ← file ini
├── app/
│   ├── page.tsx              ← shell 3 kolom + routing 9 halaman
│   │                            + ApprovalsPage & OperationsPage (fungsi lokal)
│   ├── landing/page.tsx      ← explainer hackathon (server component)
│   ├── globals.css
│   ├── layout.tsx            ← flex column: banner di flow, children h-full
│   └── api/graph/route.ts
├── components/
│   ├── LeftNav.tsx           ← FE-1
│   ├── TopNavbar.tsx         ← FE-1
│   ├── GuardianPanel.tsx     ← FE-1+2
│   ├── OverviewMain.tsx      ← FE-1
│   ├── SynapseGraph.tsx      ← FE-1+2
│   ├── pages/
│   │   ├── CodeGraphPage.tsx   ← FE-1 ✅
│   │   ├── GuardianPage.tsx    ← FE-1 ✅
│   │   ├── CortexPage.tsx      ← FE-1 ✅
│   │   ├── AgentsPage.tsx      ← FE-1 ✅
│   │   ├── SecurityPage.tsx    ← FE-1 ✅
│   │   └── SettingsPage.tsx    ← FE-1 ✅
│   └── shared/
│       ├── RiskBadge.tsx             ← FE-1 ✅
│       ├── StatusBadge.tsx           ← FE-1 ✅
│       ├── AgentBadge.tsx            ← FE-1 ✅
│       └── BackendStatusBanner.tsx   ← label DEMO DATA / LIVE / OFFLINE
├── hooks/
│   ├── useSSE.ts               ← mapping event SSE -> callback
│   ├── useSSEStream.ts         ← wrapper tipis di atas lib/sseStream
│   ├── useLiveOps.ts           ← poll /operations (Agents, Security)
│   ├── useBackendStatus.ts     ← SATU poller /health, banyak subscriber
│   └── useMockSimulation.ts
└── lib/
    ├── types.ts
    ├── mockData.ts
    ├── sseStream.ts            ← 1 koneksi /stream, fanout, backoff (#38)
    ├── operations.ts           ← decideOperation: approve -> execute (#39)
    ├── graphFilter.ts          ← filter + search graph (pure)
    ├── derive.ts               ← derivasi /operations -> UI (pure, diuji)
    ├── derive.test.ts          ← node --test
    ├── graphFilter.test.ts     ← node --test
    ├── operations.test.ts
    ├── sseStream.test.ts
    └── nodeVisuals.ts
```

## Verifikasi

```bash
npm run lint        # next lint
npm run typecheck   # tsc --noEmit
npm test            # node --test "lib/*.test.ts"
npm run build       # wajib: 3 perintah hijau tidak menjamin build
```

## Bug Mitigations

| Bug | Backend Fix | Frontend Mitigation |
|---|---|---|
| BUG-08: SSE not thread-safe | `cc9bd5a` | `lib/sseStream.ts` exponential backoff |
| BUG-07: double-execute race | `9d7456a` | N/A |
| BUG-A: Windows path rollback | `6d1813f` | N/A |
| BUG-B: partial migration | `6d1813f` | N/A |
| BUG-D: approvals data leak | `6d1813f` | N/A |
| #37 double `res.json()` | — | fixed di FE (`8c75932`) |
| #38 4 koneksi `/stream` | — | `lib/sseStream.ts` singleton + `lib/sseStream.test.ts` |
| #39 approve/execute inline | — | `lib/operations.ts` `decideOperation` + 6 test |
| #40 re-render 60fps SynapseGraph | — | animasi lewat ref, bukan `setState` |
