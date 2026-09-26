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
| `false` (default) | **MOCK** | Graph + sidebar pakai data simulasi. Tidak butuh backend. Demo animasi berjalan otomatis. |
| `true` | **LIVE** | Graph load dari `GET /graph/nodes` + `/graph/edges`. Sidebar load dari `GET /list_pending_approvals`. SSE dari `GET /stream`. |

## Endpoints Backend yang Dipakai

| Method | Endpoint | Dipakai oleh |
|---|---|---|
| `GET` | `/stream` | `useSSE` — real-time SSE stream |
| `GET` | `/graph/nodes` | `useInitialGraph` — load awal nodes |
| `GET` | `/graph/edges` | `useInitialGraph` — load awal edges |
| `GET` | `/list_pending_approvals` | `useOperations` — daftar operasi pending |
| `POST` | `/approve_operation` | `OperationCard.decide()` — approve/deny |
| `POST` | `/execute_operation` | `OperationCard.decide()` — auto-execute setelah approve |

## SSE Events yang Ditangani

| Event | Handler |
|---|---|
| `graph_update` | Tambah nodes baru ke graph |
| `ingest_progress` | Tampilkan progress overlay di canvas |
| `operation_proposed` | Node baru status `pending` |
| `operation_approved` | Node → `approved` |
| `operation_executing` | Node → `executing` (glow oranye) |
| `operation_verified` | Node → `verified` (hijau) |
| `operation_failed` | Node → `failed` (blink merah) |
| `operation_rolled_back` | Node → `rolled_back` (blink merah → hijau) |

## Struktur File

```
frontend/
├── app/
│   ├── api/graph/route.ts   # Proxy → backend /graph/nodes + /graph/edges
│   ├── globals.css
│   ├── layout.tsx
│   └── page.tsx             # Halaman utama (graph + sidebar)
├── components/
│   ├── SynapseGraph.tsx     # FE-1: force-graph + canvas animation
│   └── OperationsSidebar.tsx # FE-2: approve/deny panel
├── hooks/
│   ├── useSSE.ts            # SSE EventSource consumer
│   └── useMockSimulation.ts # Timeline simulasi (mode MOCK)
└── lib/
    ├── types.ts             # Kontrak GraphNode, GraphLink, SSEEvent, Operation
    ├── mockData.ts          # Data mock + skenario demo (2 ops, conflict, rollback)
    └── nodeVisuals.ts       # Warna, ukuran, label, hexToRgba helper
```
