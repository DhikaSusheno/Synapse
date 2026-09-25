# Synapse

Reversible, conflict-aware understanding layer for AI coding agents.
Built for the **IBM Bob 2.0 Hackathon** (lablab.ai), 25–27 Sept 2026.

Synapse gives an AI coding agent two things: a live map of how code connects
(for onboarding & review), and an automatic reflex that reverses risky
operations before they become disasters — even when multiple agents are
working at once.

Full PRD, master prompt, and architecture: [`SYNAPSE.md`](./SYNAPSE.md).
48-hour build flow diagram: [`synapse-build-flow.html`](./synapse-build-flow.html).

## Team (6 orang, 3 tim, kerja mandiri masing-masing dengan Bob 2.0 + AI tools lain)

| Tim | Orang | Fokus |
|---|---|---|
| Backend (`/backend`) | [@DhikaSusheno](https://github.com/DhikaSusheno) · [@Masrendra](https://github.com/Masrendra) | Guardian (propose/execute/rollback) + Cortex (ingest/mentor/review), MCP server |
| Frontend / UI-UX (`/frontend`) | [@nabilfauzandafa](https://github.com/nabilfauzandafa) · [@ShannWasHere](https://github.com/ShannWasHere) | Live graph (force-graph) + dashboard (sidebar, approve/deny), SSE consumer |
| Security & QC (`/security`) | [@pidpid35](https://github.com/pidpid35) · [@zuyss](https://github.com/zuyss) | Rule engine tests, adversarial/fail-closed testing, demo reliability, rollback verification |

Ownership per folder is enforced via [`CODEOWNERS`](./.github/CODEOWNERS).

## Workflow (48 jam)

Lihat detail lengkap tiap fase & tugas per orang di `synapse-build-flow.html`.
Ringkasan fase:

| Fase | Jam | Checkpoint |
|---|---|---|
| Setup | 0–2 | Skema SQLite & kontrak MCP dikunci |
| Build paralel | 2–16 | Demo internal pertama di jam 16 |
| Integrasi | 16–30 | Semua temuan QC masuk daftar perbaikan di jam 30 |
| Pengerasan | 30–40 | Rehearsal penuh mulai jam 40 — stop nambah fitur baru |
| Rehearsal | 40–46 | Video fallback demo direkam |
| Submit | 46–48 | Kirim lebih awal dari deadline |

## Stack (tanpa dependency server eksternal)

- Backend: Python + FastAPI, SQLite (`nodes`/`edges`/`operations`/`approvals`) + `networkx`, tree-sitter, SSE bawaan FastAPI.
- Frontend: Next.js + `react-force-graph-2d`.
- Tidak ada Redis/Neo4j/Qdrant/Ollama.

## License

MIT — lihat [`LICENSE`](./LICENSE).
