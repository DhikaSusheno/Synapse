# Master Prompt — Backend (Guardian + Cortex)

Turunan scoped dari master prompt penuh di [`../SYNAPSE.md`](../SYNAPSE.md) section 1. Pakai ini sebagai brief awal ke Bob 2.0 / AI agent kamu untuk kerja mandiri di folder `backend/`.

```
You are building the BACKEND half of "Synapse" — a reversible, conflict-aware
understanding layer for AI coding agents (IBM Bob 2.0 Hackathon).

ROLE: You own the MCP server (FastAPI). Frontend and Security/QC consume your
API and SSE stream as black boxes — do not change the agreed contract (SQLite
schema in SYNAPSE.md 4.2, SSE event shape) without syncing with them first.

GOAL: Implement two capability groups:
  1. GUARDIAN (BE-1) — before executing any risky, hard-to-reverse operation
     (schema migration first, others are stubs), generate a reversibility
     plan, gate it by risk, execute, verify post-conditions, auto-rollback on
     failure. Before acting, check whether any other in-flight/recent
     operation touches an overlapping resource (conflict-aware gating).
  2. CORTEX (BE-2) — ingest a target repo (tree-sitter AST pass for
     files/functions/classes/imports, then read README/docs and propose
     DOCUMENTS/EXPLAINS/REFERENCES edges), answer "explain this module"
     questions from the graph, and (nice-to-have) score artifacts/diffs.

TOOLS YOU EXPOSE (see SYNAPSE.md section 1 for exact signatures):
  understand_repo, explain_topic, review_artifact, propose_operation,
  execute_operation, list_pending_approvals, approve_operation.

CONSTRAINTS:
  - No Redis, no Neo4j, no Qdrant, no Ollama. Storage = SQLite + in-memory
    networkx. Must run with `pip install -r requirements.txt && uvicorn
    main:app` and nothing else.
  - Ship DB migration end-to-end BEFORE any other operation type.
  - Every risky action MUST have a rollback plan or MUST require human
    approval — fail-closed default for unknown operation types.
  - Build a scripted, reproducible failure scenario (a migration that breaks
    something on purpose) — this is the single most important scene.

PRIORITY ORDER (stop anywhere, still demoable):
  1. propose_operation + execute_operation for migration, no conflict-check.
  2. Add conflict-check (two operations, same target).
  3. understand_repo + explain_topic.
  4. review_artifact (cut first if time is short).
  5. SSE stream polish — frontend needs this to render live, don't gold-plate.

OUTPUT OF EVERY STEP: keep the SQLite graph and the SSE event log as the
single source of truth — frontend renders straight from these, no duplicate
state. Do not touch frontend/ or security/ folders.
```

## Checkpoint sync wajib

Jam 0–2: sepakati bentuk event SSE dengan FE-1/FE-2 (lihat `../frontend/MASTER_PROMPT.md`). Jam 16: demo internal pertama harus jalan meski kasar.
