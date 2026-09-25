# Master Prompt — Frontend (Graph + Dashboard)

Turunan scoped dari [`../SYNAPSE.md`](../SYNAPSE.md) section 1. Pakai sebagai brief awal ke AI agent kamu di folder `frontend/`.

```
You are building the FRONTEND half of "Synapse" — a live graph + control
dashboard for a reversible, conflict-aware AI-agent guardrail system (IBM Bob
2.0 Hackathon).

ROLE: You render state. All logic (rollback, conflict detection, blast
radius) lives in the backend — you consume its REST API and SSE stream
(`/stream`) as the single source of truth, no duplicate state on your side.

GOAL:
  1. GRAPH (FE-1) — force-directed live graph of nodes (file | symbol |
     dependency | doc | operation) and edges (DOCUMENTS | EXPLAINS |
     REFERENCES | TARGETS | CONFLICTS_WITH | ROLLED_BACK_BY). Operation nodes
     pulse yellow (pending) -> green (verified) or red-blink -> green
     (rolled back).
  2. DASHBOARD (FE-2) — sidebar with plain-language explanations
     (explain_topic results) and approve/deny controls wired to
     list_pending_approvals / approve_operation.

CONSTRAINTS:
  - Next.js + react-force-graph-2d. One lightweight dependency, not full D3.
  - Build against MOCK data first — do not block on backend being ready.
  - Do not implement business logic (rollback plans, conflict rules) here —
    if you find yourself computing blast_radius or deciding rollback, that
    belongs in backend/, flag it instead.

PRIORITY ORDER (stop anywhere, still demoable):
  1. Force-graph rendering mock data + sidebar/approve-deny mock.
  2. Wire graph to real SSE stream.
  3. Wire dashboard to real API (operations, approvals).
  4. Polish animation / empty & error states — cut first if time is short.

Do not touch backend/ or security/ folders.
```

## Checkpoint sync wajib

Jam 0–2: sepakati bentuk event SSE dengan BE-2 (lihat `../backend/MASTER_PROMPT.md`). Jam 16: demo internal pertama.
