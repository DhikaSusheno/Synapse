# Backend PRD — Guardian + Cortex

Scope untuk: [@DhikaSusheno](https://github.com/DhikaSusheno) (BE-1 · Guardian), [@Masrendra](https://github.com/Masrendra) (BE-2 · Cortex).
Konteks penuh (problem statement, bukti riset, non-goals): [`../SYNAPSE.md`](../SYNAPSE.md) section 2.

## Goals (dari SYNAPSE.md 2.4, bagian yang backend tanggung jawab penuh)

1. Setiap operasi berisiko (`propose_operation` → `execute_operation`) punya jalur rollback otomatis yang terverifikasi.
2. Konflik antar-operasi terdeteksi **sebelum** eksekusi (conflict-aware gating), bukan setelah rusak.
3. `understand_repo` + `explain_topic` mengisi graph yang jadi single source of truth untuk frontend.

## Deliverable wajib (MVP demo, urutan prioritas — stop di mana pun tetap demoable)

| # | Deliverable | Owner | Checkpoint terkait |
|---|---|---|---|
| 1 | `propose_operation` + `execute_operation` untuk DB migration, single agent, tanpa conflict-check, tanpa UI (test via curl) | BE-1 | Jam 10 |
| 2 | Conflict-check: dua operasi menyentuh target sama dalam window waktu → operasi kedua wajib approval | BE-1 | Jam 16 |
| 3 | `understand_repo` (tree-sitter parse + baca README) mengisi graph | BE-2 | Jam 24 |
| 4 | `explain_topic` menjawab dari graph + isi file | BE-2 | Jam 28 |
| 5 | SSE stream (`/stream`) emit tiap state transition | BE-2 | Jam 30 (integrasi ke frontend) |
| 6 | `review_artifact` (nice-to-have, potong duluan kalau mepet) | BE-2 | Jam 38–42 |

## Kontrak yang tidak boleh berubah setelah jam 2 (SYNC checkpoint)

- Skema SQLite: `nodes`, `edges`, `operations`, `approvals` — lihat [`../SYNAPSE.md`](../SYNAPSE.md) section 4.2.
- Rule table format (blast radius, fail-closed default) — section 4.4.
- Bentuk event SSE yang dikonsumsi frontend — sepakati bareng FE-1/FE-2 di jam 0–2.

## Non-Goals (jangan melar dari ini)

- Bukan policy engine generik multi-protokol (MCP-only).
- Bukan ML risk-scoring (rule-based/heuristik saja).
- Bukan garansi reversibilitas untuk efek eksternal non-idempotent (webhook/email) — cukup dideteksi + wajib approval manusia.
- Tidak ada Redis/Neo4j/Qdrant/Ollama. Storage = SQLite + `networkx` in-memory saja.

## Definition of done per fase (dari synapse-build-flow.html)

- **Jam 2**: skema SQLite & kontrak MCP dikunci bareng semua tim.
- **Jam 16**: demo internal pertama — backend & frontend harus sudah nyambung, walau kasar.
- **Jam 30**: semua bug dari QC-1/QC-2 masuk daftar perbaikan (bukan menumpuk di kepala).
- **Jam 40**: stop nambah fitur baru, mulai rehearsal penuh.
