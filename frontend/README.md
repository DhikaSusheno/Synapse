# Synapse Frontend

**Owner FE-1**: [@nabilfauzandafa](https://github.com/nabilfauzandafa) — Force-directed live graph  
**Owner FE-2**: [@ShannWasHere](https://github.com/ShannWasHere) — Dashboard sidebar + approve/deny

---

## Stack

- **Next.js 14** (App Router, TypeScript)
- **react-force-graph-2d** — live force-directed graph
- **Tailwind CSS**
- Konsumsi **SSE stream** dari backend (`/stream`)

## Jalankan

```bash
npm install
npm run dev
# → http://localhost:3000
```

Backend harus jalan di `http://localhost:8000` (lihat `backend/`).

## Mode Mock vs Live

| Env var | Nilai | Efek |
|---|---|---|
| `NEXT_PUBLIC_USE_LIVE_SSE` | `false` (default) | Pakai mock data + simulasi status |
| `NEXT_PUBLIC_USE_LIVE_SSE` | `true` | Konek ke SSE stream backend |
| `NEXT_PUBLIC_BACKEND_URL` | `http://localhost:8000` | URL backend |

Buat file `.env.local` untuk override:
```
NEXT_PUBLIC_USE_LIVE_SSE=false
NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
```

## Struktur

```
app/
  page.tsx              ← Halaman utama (graph + sidebar)
  layout.tsx            ← Root layout
  globals.css
  api/graph/route.ts    ← Proxy ke backend /graph/nodes + /graph/edges
components/
  SynapseGraph.tsx      ← FE-1: force-directed graph (react-force-graph-2d)
  OperationsSidebar.tsx ← FE-2: sidebar operasi + approve/deny
hooks/
  useSSE.ts             ← Konsumsi SSE stream backend
  useMockSimulation.ts  ← Simulasi status mock (dev only)
lib/
  types.ts              ← Type definitions (GraphNode, GraphLink, SSEEvent)
  mockData.ts           ← Data mock (nodes + links + timeline simulasi)
  nodeVisuals.ts        ← Warna & ukuran node per type/status
```

## Deliverables FE-1

- [x] Force-directed graph dengan mock data
- [x] Warna node per type & status (pending=kuning, verified=hijau, rolled_back=merah)
- [x] Animasi status berubah otomatis (simulasi 3 langkah)
- [x] Hook `useSSE` siap terima event dari backend
- [ ] Wire ke SSE stream asli (tunggu backend deliverable #5)
- [ ] Polish animasi pulse untuk node `pending`

## Kontrak SSE (sepakati dengan BE-2 jam 0-2)

Event yang dikirim backend via `/stream`:

```json
{ "event": "operation_proposed",  "data": { "operation_id": "op::xxx" } }
{ "event": "operation_approved",  "data": { "operation_id": "op::xxx" } }
{ "event": "operation_executing", "data": { "operation_id": "op::xxx" } }
{ "event": "operation_verified",  "data": { "operation_id": "op::xxx" } }
{ "event": "operation_failed",    "data": { "operation_id": "op::xxx" } }
{ "event": "operation_rolled_back","data": { "operation_id": "op::xxx" } }
{ "event": "graph_update",        "data": { "nodes": [...] } }
```
