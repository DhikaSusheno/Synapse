# Synapse Frontend

Owner FE-1: [@nabilfauzandafa](https://github.com/nabilfauzandafa) — Force-directed live graph  
Owner FE-2: [@ShannWasHere](https://github.com/ShannWasHere) — Dashboard sidebar

Stack: **Next.js 14** + **react-force-graph-2d** + **Tailwind CSS**

## Cara Run

```bash
cd frontend
npm install

# Salin env vars
cp .env.local.example .env.local
# Edit .env.local sesuai kebutuhan

npm run dev
# → http://localhost:3000
```

## Mode Operasi

| `NEXT_PUBLIC_USE_LIVE_SSE` | Mode | Keterangan |
|---|---|---|
| `false` (default) | **MOCK** | Graph + sidebar pakai data simulasi. Tidak butuh backend. Demo animasi 6-step berjalan otomatis. |
| `true` | **LIVE** | Graph load dari `GET /graph/nodes + /graph/edges`. Sidebar dari `GET /list_pending_approvals`. SSE dari `GET /stream`. |

## Cara Run Lengkap (Backend + Frontend)

```bash
# 1. Jalankan backend
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
# → http://localhost:8000/docs

# 2. Jalankan frontend (terminal baru)
cd frontend
npm install
cp .env.local.example .env.local
# Set NEXT_PUBLIC_USE_LIVE_SSE=true di .env.local
npm run dev
# → http://localhost:3000

# 3. Ingest repo (trigger understand_repo)
curl -X POST http://localhost:8000/understand_repo \
  -H "Content-Type: application/json" \
  -d '{"repo_path": ".."}'
```

## Endpoints Backend yang Dipakai

| Method | Endpoint | Dipakai oleh |
|---|---|---|
| `GET` | `/stream` | `useSSE` — real-time SSE stream |
| `GET` | `/graph/nodes` | `useInitialGraph` — load awal nodes |
| `GET` | `/graph/edges` | `useInitialGraph` — load awal edges |
| `GET` | `/list_pending_approvals` | `useOperations` — daftar operasi pending |
| `POST` | `/approve_operation` | `OperationCard.decide()` — approve/deny |
| `POST` | `/execute_operation` | `OperationCard.decide()` — auto-execute setelah approve |
| `POST` | `/explain_topic` | `NodeInfoPanel` — penjelasan node diklik |
| `GET` | `/repo_health` | `useRepoHealth` — health badge di header |

## SSE Events yang Ditangani

| Event | Handler |
|---|---|
| `graph_update` | Tambah nodes baru ke graph |
| `ingest_progress` | Overlay progress di canvas |
| `operation_proposed` | Node baru status `pending` (pulse kuning) |
| `operation_approved` | Node → `approved` |
| `operation_denied` | Ditampilkan di EventLog |
| `operation_executing` | Node → `executing` (glow oranye) |
| `operation_verified` | Node → `verified` (hijau) |
| `operation_failed` | Node → `failed` (blink merah) |
| `operation_rolled_back` | Node → `rolled_back` (blink merah → hijau) |
| `review_done` | EventLog |
| `health_report` | EventLog |
| `refactor_suggestion` | EventLog |

## Struktur File

```
frontend/
├── app/
│   ├── api/graph/route.ts   # Proxy → backend /graph/nodes + /graph/edges
│   ├── globals.css
│   ├── layout.tsx
│   └── page.tsx             # Header (health badge) + graph + sidebar layout
├── components/
│   ├── SynapseGraph.tsx     # FE-1: canvas force-graph + pulse/blink animation
│   └── OperationsSidebar.tsx # FE-1+2: ops tab + log tab + explain panel
├── hooks/
│   ├── useSSE.ts            # SSE consumer + exponential backoff reconnect
│   └── useMockSimulation.ts # Timeline simulasi 6-step (mode MOCK)
└── lib/
    ├── types.ts             # GraphNode, GraphLink, SSEEvent, Operation
    ├── mockData.ts          # 3 op mock (sukses, konflik, rollback)
    └── nodeVisuals.ts       # Warna, ukuran, label, hexToRgba
```

## Status Deliverable PRD

| # | Deliverable | Status |
|---|---|---|
| 1 | Force-graph mock | ✅ Done |
| 2 | Sidebar approve/deny mock | ✅ Done |
| 3 | Wire graph ke SSE | ✅ Done |
| 4 | Wire dashboard ke API | ✅ Done |
| 5 | Animasi pulse/warna node | ✅ Done |
| 6 | Polish UI + event log | ✅ Done |

## Bug Mitigations (Frontend Side)

| Bug | Status Backend | Frontend Mitigation |
|---|---|---|
| BUG-08: SSE not thread-safe | ✅ Fixed (`cc9bd5a`) | `useSSE` exponential backoff reconnect |
| BUG-07: double-execute race | ✅ Fixed (`9d7456a`) | N/A (backend fix cukup) |
